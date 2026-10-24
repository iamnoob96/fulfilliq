"""Durable scoring tests use synthetic checkout inputs and never fit an estimator."""

import csv
import io
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.modeling.contracts import RiskResponse
from fulfilliq.modeling.inference import RiskService
from fulfilliq.operations.jobs import JobStore
from fulfilliq.operations.reviews import ReviewUpdate


@pytest.fixture
def job_system(raw_dir, tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, artifact_dir=tmp_path / "artifacts", write_token="fixture")
    ingest(raw_dir, settings.database_path, settings.processed_dir)
    state = {"version": "fixture-v1", "requests": []}
    monkeypatch.setattr(RiskService, "load", lambda _: {"model_version": state["version"]})

    def predict(_self, orders):
        state["requests"].extend(orders)
        return [RiskResponse(order_id=o.order_id, delay_probability=.9 if o.order_id == "o1" else .6,
                             threshold=.5, risk_category="high", model_version=state["version"],
                             recommendation="Review", rationale=[], warnings=[]) for o in orders]

    monkeypatch.setattr(RiskService, "predict", predict)
    return settings, TestClient(create_app(settings)), JobStore(settings), state


def create(client, filters=None):
    response = client.post("/api/v1/scoring-jobs", json={"filters": filters or {}, "review_capacity": 2},
                           headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def finish(store, identifier):
    for _ in range(10):
        if not store.run_once(batch_size=2, job_id=identifier):
            break
    return store.get(identifier)


def test_creation_authentication_limits_and_frozen_membership(job_system):
    settings, client, store, _ = job_system
    assert client.post("/api/v1/scoring-jobs", json={"filters": {}}).status_code == 403
    identifier = create(client, {"review_status": "pending"})
    store.reviews.update("o1", ReviewUpdate(
        status="resolved", notes="Synthetic", expected_revision=0))
    assert store.get(identifier)["candidate_count"] == 6
    assert finish(store, identifier)["processed_count"] == 6
    assert any(row["order_id"] == "o1" and row["review_status"] == "resolved" for row in store.results(identifier)["items"])
    assert client.get("/api/v1/scoring-jobs").json()["total"] == 1
    assert client.get("/api/v1/scoring-jobs/missing").status_code == 404
    small = Settings(data_dir=settings.data_dir, artifact_dir=settings.artifact_dir, scoring_max_orders=2)
    with pytest.raises(ValueError, match="limit is 2"):
        JobStore(small).create({}, 1)
    assert client.post("/api/v1/scoring-jobs", json={"filters": {"future_feature": 1}}, headers={"Authorization": "Bearer fixture"}).status_code == 422
    assert client.post("/api/v1/scoring-jobs", json={"filters": {"start_date": "2019-01-01", "end_date": "2018-01-01"}}, headers={"Authorization": "Bearer fixture"}).status_code == 422
    with pytest.raises(ValueError, match="No candidates"):
        store.create({"region": "ZZ"}, 1)


def test_restart_progress_ranking_export_and_review_status(job_system):
    settings, client, store, state = job_system
    warehouse = settings.database_path.read_bytes()
    identifier = create(client)
    assert store.run_once(batch_size=2)
    assert store.get(identifier)["processed_count"] == 2
    assert not store.results(identifier)["job"]["ranking_complete"]
    restarted = JobStore(settings)
    final = finish(restarted, identifier)
    assert final["status"] == "completed" and final["processed_count"] == 6
    assert final["scored_count"] == 3 and final["unavailable_count"] == 3
    ranked = client.get(f"/api/v1/scoring-jobs/{identifier}/results", params={"capacity": 1}).json()
    assert ranked["job"]["ranking_complete"]
    assert [r["order_id"] for r in ranked["items"]] == ["o1", "o4", "o2"]
    assert [r["within_review_capacity"] for r in ranked["items"]] == [True, False, False]
    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/v1/scoring-jobs/{identifier}/export.csv", params={"capacity": 1}).text)))
    assert [r["order_id"] for r in rows] == ["o1", "o4", "o2"]
    lower_limit = TestClient(create_app(Settings(data_dir=settings.data_dir, artifact_dir=settings.artifact_dir,
                                                scoring_max_orders=2)))
    historical_csv = lower_limit.get(f"/api/v1/scoring-jobs/{identifier}/export.csv")
    assert len(list(csv.DictReader(io.StringIO(historical_csv.text)))) == 3
    before_requests = len(state["requests"])
    assert not restarted.run_once(job_id=identifier)
    assert len(state["requests"]) == before_requests == 3
    for request in state["requests"]:
        assert not {"delivered_at", "order_status", "review", "carrier_handoff_at"} & request.model_dump().keys()
    assert settings.database_path.read_bytes() == warehouse
    assert client.get(f"/api/v1/scoring-jobs/{identifier}/results", params={"limit": 1, "offset": 1}).json()["items"][0]["order_id"] == "o4"
    assert client.post(f"/api/v1/scoring-jobs/{identifier}/resume", headers={"Authorization": "Bearer fixture"}).status_code == 409


def test_lease_recovery_fences_old_claim_and_preserves_uniqueness(job_system):
    settings, client, store, _ = job_system
    identifier = create(client)
    _, old_token = store.claim()
    assert JobStore(settings).claim() is None
    with store.connect() as conn:
        conn.execute("UPDATE scoring_jobs SET lease_until=0 WHERE job_id=?", (identifier,))
    assert JobStore(settings).run_once(batch_size=2)
    assert not store.transition(identifier, "failed", token=old_token)
    finish(store, identifier)
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM scoring_results WHERE job_id=?", (identifier,)).fetchone()[0] == 6
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO scoring_results(job_id,order_id,candidate_sequence) VALUES (?,?,?)", (identifier, "o1", 999))


def test_cancel_in_flight_prevents_commit_and_explicit_resume(job_system, monkeypatch):
    _, client, store, _ = job_system
    identifier = create(client)
    original = RiskService.predict

    def cancel(_self, orders):
        store.transition(identifier, "canceled")
        return original(_self, orders)

    monkeypatch.setattr(RiskService, "predict", cancel)
    assert store.run_once(batch_size=6)
    assert store.get(identifier)["status"] == "canceled"
    assert store.get(identifier)["processed_count"] == 0
    assert client.post(f"/api/v1/scoring-jobs/{identifier}/resume").status_code == 403
    monkeypatch.setattr(RiskService, "predict", original)
    assert client.post(f"/api/v1/scoring-jobs/{identifier}/resume", headers={"Authorization": "Bearer fixture"}).status_code == 200
    assert finish(store, identifier)["status"] == "completed"


@pytest.mark.parametrize("changed", ["model", "warehouse"])
def test_snapshot_drift_stops_job(job_system, changed):
    settings, client, store, state = job_system
    identifier = create(client)
    if changed == "model":
        state["version"] = "fixture-v2"
    else:
        stamp = settings.database_path.stat()
        os.utime(settings.database_path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1000000))
    store.run_once()
    assert store.get(identifier)["status"] == "stale"
    assert store.get(identifier)["processed_count"] == 0
    assert client.post(f"/api/v1/scoring-jobs/{identifier}/resume", headers={"Authorization": "Bearer fixture"}).status_code == 409


@pytest.mark.parametrize("method", ["predict", "load"])
def test_missing_model_failure_is_recoverable_and_does_not_expose_paths(job_system, monkeypatch, method):
    _, client, store, _ = job_system
    identifier = create(client)
    original = getattr(RiskService, method)

    def missing(*_):
        raise OSError("/private/local/secret/model")

    monkeypatch.setattr(RiskService, method, missing)
    store.run_once(batch_size=6)
    assert store.get(identifier)["status"] == "failed"
    assert "/private" not in store.get(identifier)["error_summary"]
    monkeypatch.setattr(RiskService, method, original)
    store.resume(identifier)
    assert finish(store, identifier)["ranking_complete"]


def test_all_unavailable_cohort_finishes_without_invented_scores(job_system):
    _, client, store, state = job_system
    identifier = create(client, {"order_status": "canceled"})
    final = finish(store, identifier)
    assert final["ranking_complete"] and final["scored_count"] == 0 and final["unavailable_count"] == 1
    assert store.results(identifier)["items"] == []
    assert store.results(identifier, include_unavailable=True)["items"][0]["unavailable_reason"]
    assert state["requests"] == []
