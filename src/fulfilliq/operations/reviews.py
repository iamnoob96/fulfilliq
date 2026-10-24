"""Human decisions live outside the immutable Olist warehouse; schema v1 migration."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewStatus = Literal["pending", "investigating", "reviewed", "escalated", "resolved"]


class ReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ReviewStatus
    notes: str = Field(default="", max_length=5000)
    expected_revision: int = Field(ge=0, strict=True)


class ReviewState(BaseModel):
    order_id: str
    status: ReviewStatus = "pending"
    notes: str = ""
    revision: int = 0
    updated_at_utc: str | None = None


class ReviewConflict(ValueError):
    pass


class ReviewStore:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported operational review database version")
            if version == 0:
                conn.execute("""CREATE TABLE IF NOT EXISTS order_reviews_workflow (
                    order_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN
                        ('pending','investigating','reviewed','escalated','resolved')),
                    notes TEXT NOT NULL, revision INTEGER NOT NULL,
                    updated_at_utc TEXT NOT NULL)""")
                conn.execute("PRAGMA user_version=1")
                conn.commit()
            return conn
        except Exception:
            conn.close()
            raise

    def all(self) -> dict[str, dict]:
        conn = self.connect()
        try:
            return {row["order_id"]: dict(row) for row in conn.execute(
                "SELECT * FROM order_reviews_workflow"
            )}
        finally:
            conn.close()

    def get(self, order_id: str) -> dict:
        return self.all().get(order_id, ReviewState(order_id=order_id).model_dump())

    def update(self, order_id: str, change: ReviewUpdate) -> dict:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT revision FROM order_reviews_workflow WHERE order_id=?", (order_id,)
            ).fetchone()
            revision = row[0] if row else 0
            if change.expected_revision != revision:
                raise ReviewConflict("Review changed in another session; reload before saving")
            conn.execute("""INSERT INTO order_reviews_workflow VALUES (?,?,?,?,?)
                ON CONFLICT(order_id) DO UPDATE SET status=excluded.status, notes=excluded.notes,
                revision=excluded.revision, updated_at_utc=excluded.updated_at_utc""",
                (order_id, change.status, change.notes, revision + 1,
                 datetime.now(timezone.utc).isoformat()))
            conn.commit()
            return dict(conn.execute(
                "SELECT * FROM order_reviews_workflow WHERE order_id=?", (order_id,)
            ).fetchone())
        finally:
            conn.close()
