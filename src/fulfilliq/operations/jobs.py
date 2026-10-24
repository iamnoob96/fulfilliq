"""Durable, frozen scoring cohorts. SQL transactions fence expired worker claims."""

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fulfilliq.analytics.operations import CohortFilter
from fulfilliq.config import Settings
from fulfilliq.modeling.inference import RiskService
from fulfilliq.operations.orders import OrderService
from fulfilliq.operations.replay import score_orders
from fulfilliq.operations.reviews import ReviewStore

TERMINAL = {"completed", "failed", "canceled", "stale"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class JobNotFound(ValueError):
    pass


class JobConflict(ValueError):
    pass


class JobStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.scoring_database_path
        self.reviews = ReviewStore(settings.review_database_path)
        self.orders = OrderService(settings.database_path, self.reviews)
        self.risk = RiskService(settings.artifact_dir, settings.database_path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported scoring database schema")
            if version == 0:
                conn.executescript("""BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS scoring_jobs (
                      job_id TEXT PRIMARY KEY, filters_json TEXT NOT NULL,
                      created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
                      completed_at_utc TEXT, status TEXT NOT NULL CHECK(status IN
                        ('pending','running','completed','failed','canceled','stale')),
                      candidate_count INTEGER NOT NULL, processed_count INTEGER NOT NULL DEFAULT 0,
                      scored_count INTEGER NOT NULL DEFAULT 0, unavailable_count INTEGER NOT NULL DEFAULT 0,
                      model_version TEXT NOT NULL, warehouse_snapshot TEXT NOT NULL,
                      review_capacity INTEGER NOT NULL, error_summary TEXT,
                      lease_token TEXT, lease_until REAL);
                    CREATE TABLE IF NOT EXISTS scoring_results (
                      job_id TEXT NOT NULL REFERENCES scoring_jobs(job_id),
                      order_id TEXT NOT NULL, candidate_sequence INTEGER NOT NULL,
                      eligibility TEXT NOT NULL DEFAULT 'pending'
                        CHECK(eligibility IN ('pending','scored','unavailable')),
                      delay_probability REAL CHECK(delay_probability BETWEEN 0 AND 1),
                      prediction_json TEXT, unavailable_reason TEXT, processed_at_utc TEXT,
                      PRIMARY KEY(job_id,order_id), UNIQUE(job_id,candidate_sequence));
                    CREATE INDEX IF NOT EXISTS result_ranking ON
                        scoring_results(job_id,eligibility,delay_probability DESC,candidate_sequence);
                    PRAGMA user_version=1;
                    COMMIT;""")
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def public(row):
        value = dict(row)
        value["filters"] = json.loads(value.pop("filters_json"))
        value.pop("lease_token", None)
        value.pop("lease_until", None)
        value["ranking_complete"] = value["status"] == "completed" and value["processed_count"] == value["candidate_count"]
        value["retrospective_selection"] = bool(value["filters"].get("delivery_outcome") or value["filters"].get("order_status"))
        return value

    def get(self, job_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM scoring_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFound("Scoring job not found")
        return self.public(row)

    def list(self, limit=50, offset=0):
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM scoring_jobs").fetchone()[0]
            rows = conn.execute("SELECT * FROM scoring_jobs ORDER BY created_at_utc DESC,job_id LIMIT ? OFFSET ?",
                                (limit, offset)).fetchall()
        return {"total": total, "limit": limit, "offset": offset, "items": [self.public(row) for row in rows]}

    def create(self, filters: dict, capacity: int):
        before = self.orders.snapshot()
        cohort = CohortFilter(**{key: filters.get(key) for key in
                                ("seller_id", "region", "product_category", "start_date", "end_date")})
        candidates = self.orders.list(cohort, filters.get("review_status"), self.settings.scoring_max_orders + 1, 0,
                                      order_status=filters.get("order_status"), delivery_outcome=filters.get("delivery_outcome"))
        total = candidates["total"]
        if not total:
            raise ValueError("No candidates match this cohort")
        if total > self.settings.scoring_max_orders:
            raise ValueError(f"Cohort has {total} candidates; limit is {self.settings.scoring_max_orders}. Narrow the filters.")
        metadata = self.risk.load()
        if self.orders.snapshot() != before:
            raise JobConflict("Warehouse changed during job creation; refresh and retry")
        identifier, stamp = uuid4().hex, utc_now()
        with self.connect() as conn:
            conn.execute("""INSERT INTO scoring_jobs (job_id,filters_json,created_at_utc,updated_at_utc,
                status,candidate_count,model_version,warehouse_snapshot,review_capacity)
                VALUES (?,?,?,?,'pending',?,?,?,?)""", (identifier, json.dumps(filters, default=str, sort_keys=True),
                stamp, stamp, total, metadata["model_version"], before, capacity))
            conn.executemany("INSERT INTO scoring_results(job_id,order_id,candidate_sequence) VALUES (?,?,?)",
                             [(identifier, row["order_id"], n) for n, row in enumerate(candidates["items"])])
        return self.get(identifier)

    def claim(self, *, lease_seconds=180, job_id=None):
        if not 10 <= lease_seconds <= 3600:
            raise ValueError("Worker lease must be within 10–3600 seconds")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""SELECT * FROM scoring_jobs
                WHERE (status='pending' OR (status='running' AND lease_until<=?))
                AND (? IS NULL OR job_id=?) ORDER BY created_at_utc,job_id LIMIT 1""",
                (time.time(), job_id, job_id)).fetchone()
            if row is None:
                return None
            token = uuid4().hex
            conn.execute("UPDATE scoring_jobs SET status='running',lease_token=?,lease_until=?,updated_at_utc=? WHERE job_id=?",
                         (token, time.time() + lease_seconds, utc_now(), row["job_id"]))
        return row["job_id"], token

    def transition(self, job_id, status, *, token=None, error=None):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM scoring_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise JobNotFound("Scoring job not found")
            if token is not None and (row["lease_token"] != token or row["status"] != "running"):
                return False
            if token is None and row["status"] == "completed":
                raise JobConflict("Completed jobs are immutable")
            conn.execute("""UPDATE scoring_jobs SET status=?,error_summary=?,updated_at_utc=?,
                completed_at_utc=?,lease_token=NULL,lease_until=NULL WHERE job_id=?""",
                (status, error, utc_now(), utc_now() if status in TERMINAL else None, job_id))
        return True

    def check_snapshot(self, job):
        if self.orders.snapshot() != job["warehouse_snapshot"]:
            return False
        return self.risk.load()["model_version"] == job["model_version"]

    def resume(self, job_id):
        job = self.get(job_id)
        if not self.check_snapshot(job):
            raise JobConflict("Original data/model snapshot is no longer active; create a new job")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status,lease_until FROM scoring_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row["status"] == "completed" or (row["status"] == "running" and row["lease_until"] > time.time()):
                raise JobConflict("Job is complete or has an active worker lease")
            conn.execute("""UPDATE scoring_jobs SET status='pending',error_summary=NULL,completed_at_utc=NULL,
                lease_token=NULL,lease_until=NULL,updated_at_utc=? WHERE job_id=?""", (utc_now(), job_id))
        return self.get(job_id)

    def run_once(self, *, batch_size=50, lease_seconds=180, job_id=None):
        if not 1 <= batch_size <= 100:
            raise ValueError("Worker batch size must be within 1–100")
        claim = self.claim(lease_seconds=lease_seconds, job_id=job_id)
        if claim is None:
            return False
        identifier, token = claim
        try:
            job = self.get(identifier)
            if not self.check_snapshot(job):
                self.transition(identifier, "stale", token=token, error="Original warehouse/model snapshot changed; create a new job.")
                return True
            with self.connect() as conn:
                rows = conn.execute("""SELECT order_id FROM scoring_results WHERE job_id=?
                    AND eligibility='pending' ORDER BY candidate_sequence LIMIT ?""", (identifier, batch_size)).fetchall()
            identifiers = [row["order_id"] for row in rows]
            predictions, unavailable = score_orders(self.orders, self.risk, identifiers)
            if not self.check_snapshot(job) or any(row.model_version != job["model_version"] for row in predictions):
                self.transition(identifier, "stale", token=token, error="Snapshot changed during inference; chunk discarded.")
                return True
            scores = {row.order_id: row for row in predictions}
            missing = {row["order_id"]: row["reason"] for row in unavailable}
            if set(scores) & set(missing) or set(scores) | set(missing) != set(identifiers):
                raise ValueError("Incomplete scoring response")
            with self.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute("SELECT status,lease_token,lease_until FROM scoring_jobs WHERE job_id=?", (identifier,)).fetchone()
                if current["status"] != "running" or current["lease_token"] != token or current["lease_until"] <= time.time():
                    return True  # An expired/replaced worker cannot write results.
                stamp = utc_now()
                for order_id in identifiers:
                    prediction = scores.get(order_id)
                    conn.execute("""UPDATE scoring_results SET eligibility=?,delay_probability=?,prediction_json=?,
                        unavailable_reason=?,processed_at_utc=? WHERE job_id=? AND order_id=? AND eligibility='pending'""",
                        ("scored" if prediction else "unavailable", prediction.delay_probability if prediction else None,
                         prediction.model_dump_json() if prediction else None, missing.get(order_id), stamp, identifier, order_id))
                counts = conn.execute("""SELECT COUNT(*) AS processed,
                    SUM(eligibility='scored') AS scored,SUM(eligibility='unavailable') AS unavailable
                    FROM scoring_results WHERE job_id=? AND eligibility!='pending'""", (identifier,)).fetchone()
                complete = counts["processed"] == job["candidate_count"]
                conn.execute("""UPDATE scoring_jobs SET processed_count=?,scored_count=?,unavailable_count=?,
                    status=?,updated_at_utc=?,completed_at_utc=?,lease_token=NULL,lease_until=NULL WHERE job_id=?""",
                    (counts["processed"], counts["scored"] or 0, counts["unavailable"] or 0,
                     "completed" if complete else "pending", stamp, stamp if complete else None, identifier))
        except Exception:
            self.transition(identifier, "failed", token=token,
                            error="Scoring failed; restore compatible model/data and explicitly resume. No incomplete chunk was saved.")
        return True

    def results(self, job_id, *, capacity=None, limit=100, offset=0, review_status=None, include_unavailable=False):
        job = self.get(job_id)
        capacity = job["review_capacity"] if capacity is None else capacity
        if not 0 <= capacity <= self.settings.scoring_max_orders:
            raise ValueError("Review capacity exceeds the configured cohort bound")
        with self.connect() as conn:
            rows = conn.execute("""SELECT * FROM scoring_results WHERE job_id=? AND eligibility!='pending'
                ORDER BY eligibility='scored' DESC,delay_probability DESC,candidate_sequence,order_id""", (job_id,)).fetchall()
        states = self.reviews.statuses()
        items, rank = [], 0
        for row in rows:
            value = dict(row)
            value.pop("job_id")
            prediction = value.pop("prediction_json")
            value["prediction"] = json.loads(prediction) if prediction else None
            value["model_version"] = job["model_version"]
            value["review_status"] = states.get(row["order_id"], {}).get("status", "pending")
            scored = value["eligibility"] == "scored"
            rank += int(scored)
            value["rank"] = rank if scored else None
            value["within_review_capacity"] = scored and rank <= capacity
            if (include_unavailable or scored) and (review_status is None or value["review_status"] == review_status):
                items.append(value)
        return {"job": job, "review_capacity": capacity, "total": len(items), "limit": limit, "offset": offset,
                "items": items[offset:offset + limit], "interpretation":
                ("Complete cohort-wide ranking of successfully scored orders; every frozen candidate has a recorded outcome."
                 if job["ranking_complete"] else "Preliminary partial results only; this is not a complete cohort ranking.")
                + " Historical replay, not a pre-delivery performance benchmark. Workflow statuses are current and separate from scores."}
