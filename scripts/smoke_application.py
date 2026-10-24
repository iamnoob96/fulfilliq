"""Read-only real Olist API checks, saved-model parity and isolated review persistence."""

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.db.connection import make_engine


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    settings = Settings()
    pointer = settings.artifact_dir / "delivery/current.json"
    version = json.loads(pointer.read_text())["version"]
    model = pointer.parent / version / "model.joblib"
    before = {"warehouse": digest(settings.database_path), "pointer": digest(pointer),
              "model": digest(model)}
    engine = make_engine(settings.database_path, readonly=True)
    try:
        with engine.connect() as conn:
            total = conn.scalar(text("SELECT COUNT(*) FROM fact_orders"))
            identifier = conn.scalar(text("""SELECT order_id FROM orders
                WHERE order_status='delivered' AND order_purchase_timestamp > '2018-07-01'
                ORDER BY order_purchase_timestamp, order_id LIMIT 1"""))
    finally:
        engine.dispose()
    with tempfile.TemporaryDirectory(prefix="fulfilliq-review-smoke-") as temporary:
        review_path = Path(temporary) / "operations.sqlite3"

        @dataclass(frozen=True)
        class DemoSettings(Settings):
            @property
            def review_database_path(self):
                return review_path

        isolated = DemoSettings(data_dir=settings.data_dir, artifact_dir=settings.artifact_dir,
                                write_token="isolated-smoke-token")
        api = TestClient(create_app(isolated))
        overview = api.get("/api/v1/analytics/overview").json()
        assert overview["total_orders"] == total == 99441
        detail = api.get("/api/v1/orders/" + identifier).json()
        assert detail["replay_payload"] is not None
        direct = api.post("/api/v1/orders/predict-delay", json=detail["replay_payload"])
        replay = api.post("/api/v1/orders/replay", json={"order_ids": [identifier], "review_capacity": 1})
        assert direct.status_code == replay.status_code == 200
        assert direct.json() == replay.json()["predictions"][0]
        assert 0 <= direct.json()["delay_probability"] <= 1
        assert direct.json()["model_version"] == version
        response = api.put(f"/api/v1/orders/{identifier}/review", json={
            "status": "investigating", "notes": "Isolated real-data integration check", "expected_revision": 0},
            headers={"Authorization": "Bearer isolated-smoke-token"})
        assert response.status_code == 200
        restarted = TestClient(create_app(isolated))
        assert restarted.get("/api/v1/orders/" + identifier).json()["review"]["revision"] == 1
        seller = detail["products"][0]["seller_id"]
        checks = [f"/sellers/{seller}/insights", "/sellers/segments", "/mining/association-rules",
                  "/mining/itemsets", "/mining/anomalies", "/reviews/insights", "/reviews/evidence",
                  "/reports/operations", "/models/metrics", "/models/research", "/console/dependencies"]
        for path in checks:
            response = api.get("/api/v1" + path)
            assert response.status_code == 200, (path, response.text[:200])
        assert api.get("/api/v1/orders", params={"seller_id": seller}).json()["total"] > 0
        report = api.get("/api/v1/reports/operations", params={"region": "RJ"}).json()
        assert report["overview"]["total_orders"] < total
        r = api.get("/api/v1/reports/r").json()
        if r["available"]:
            for filename in r["files"]:
                response = api.get("/api/v1/reports/r/files/" + filename)
                assert response.status_code == 200
                if filename.endswith(".png"):
                    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    after = {"warehouse": digest(settings.database_path), "pointer": digest(pointer), "model": digest(model)}
    assert before == after
    return {"total_orders": total, "eligible_outcomes": overview["eligible_outcomes"],
            "late_orders": overview["late_orders"], "active_sellers": overview["active_sellers"],
            "model_version": version, "warehouse_and_model_unchanged": before == after,
            "single_and_replay_predictions_identical": True, "review_restart_persistence": True,
            "read_only_api_workflows_checked": len(checks), "r_available": r["available"],
            "sha256": after}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
