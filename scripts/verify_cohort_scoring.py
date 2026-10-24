"""Opt-in real-data worker restart demo; all generated jobs/notes live in a temporary directory."""

import csv
import hashlib
import io
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.operations.jobs import JobStore


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    base = Settings()
    pointer = base.artifact_dir / "delivery/current.json"
    version = json.loads(pointer.read_text())["version"]
    protected = [base.database_path, pointer, pointer.parent / version / "model.joblib"]
    before = [digest(path) for path in protected]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="fulfilliq-cohort-demo-") as temporary:
        settings = Settings(data_dir=base.data_dir, artifact_dir=base.artifact_dir,
                            operational_dir=Path(temporary), write_token="temporary-demo-token")
        api = TestClient(create_app(settings))
        headers = {"Authorization": "Bearer temporary-demo-token"}
        created = api.post("/api/v1/scoring-jobs", json={"filters": {"region": "AL"}, "review_capacity": 20}, headers=headers)
        assert created.status_code == 201, created.text
        job = created.json()
        identifier = job["job_id"]
        assert 50 < job["candidate_count"] <= settings.scoring_max_orders
        env = {**os.environ, "FULFILIQ_DATA_DIR": str(base.data_dir), "FULFILIQ_ARTIFACT_DIR": str(base.artifact_dir),
               "FULFILIQ_OPERATIONS_DIR": temporary}
        command = [sys.executable, "-m", "fulfilliq.operations.worker", "--job-id", identifier, "--batch-size", "50", "--max-batches"]
        subprocess.run(command + ["1"], env=env, check=True)
        partial = JobStore(settings).get(identifier)
        assert partial["processed_count"] == 50 and not partial["ranking_complete"]
        # The first worker process has exited. Fresh API and worker processes resume persisted work.
        api = TestClient(create_app(settings))
        assert api.get(f"/api/v1/scoring-jobs/{identifier}").json()["processed_count"] == 50
        subprocess.run(command + ["100"], env=env, check=True)
        final = api.get(f"/api/v1/scoring-jobs/{identifier}").json()
        assert final["ranking_complete"] and final["processed_count"] == final["candidate_count"]
        assert final["scored_count"] + final["unavailable_count"] == final["candidate_count"]
        result = api.get(f"/api/v1/scoring-jobs/{identifier}/results", params={"capacity": 20}).json()
        assert result["total"] == final["scored_count"]
        probabilities = [row["delay_probability"] for row in result["items"]]
        assert probabilities == sorted(probabilities, reverse=True)
        first = result["items"][0]
        detail = api.get(f"/api/v1/orders/{first['order_id']}").json()
        assert detail["replay_payload"] is not None
        saved = api.put(f"/api/v1/orders/{first['order_id']}/review", json={"status": "investigating",
                        "notes": "Temporary isolated cohort restart demo", "expected_revision": 0}, headers=headers)
        assert saved.status_code == 200
        restarted = TestClient(create_app(settings))
        assert restarted.get(f"/api/v1/orders/{first['order_id']}").json()["review"]["revision"] == 1
        export = api.get(f"/api/v1/scoring-jobs/{identifier}/export.csv", params={"capacity": 20})
        rows = list(csv.DictReader(io.StringIO(export.text)))
        assert len(rows) == final["scored_count"] and rows[0]["order_id"] == first["order_id"]
        assert sum(row["within_review_capacity"] == "True" for row in rows) == min(20, final["scored_count"])
        assert export.headers["x-ranking-complete"] == "true"
        with JobStore(settings).connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM scoring_results WHERE job_id=?", (identifier,)).fetchone()[0] == final["candidate_count"]
    assert [digest(path) for path in protected] == before
    return {"candidate_count": final["candidate_count"], "scored_count": final["scored_count"],
            "unavailable_count": final["unavailable_count"], "stopped_after": partial["processed_count"],
            "worker_process_restart_verified": True, "csv_rows": len(rows),
            "isolated_investigation_persisted": True, "warehouse_and_active_model_unchanged": True,
            "model_version": version, "duration_seconds": round(time.monotonic()-started, 2),
            "max_child_rss_platform_units": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
