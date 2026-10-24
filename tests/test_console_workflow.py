"""Application integration uses controlled warehouse inputs and no model training."""

import pytest
from fastapi.testclient import TestClient

from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.modeling.contracts import RiskResponse
from fulfilliq.operations.orders import OrderService
from fulfilliq.operations.reviews import ReviewStore


@pytest.fixture
def application(raw_dir, tmp_path):
    settings = Settings(data_dir=tmp_path, artifact_dir=tmp_path / "artifacts", write_token="test-token")
    ingest(raw_dir, settings.database_path, settings.processed_dir)
    return settings, TestClient(create_app(settings))


def test_orders_filters_details_and_missing_inputs(application):
    settings, client = application
    assert client.get("/api/v1/analytics/overview").json()["total_orders"] == 6
    options = client.get("/api/v1/console/options").json()
    assert options["categories"] == ["books", "sem_traducao", "unknown"]
    response = client.get("/api/v1/orders", params={"seller_id": "s2", "region": "SP"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["order_id"] == "o1"
    assert client.get("/api/v1/orders", params={"start_date": "2018-01-02", "end_date": "2018-01-02"}).json()["total"] == 1
    assert client.get("/api/v1/orders", params={"start_date": "2018-02-01", "end_date": "2018-01-01"}).status_code == 422
    assert client.get("/api/v1/orders", params={"limit": 101}).status_code == 422
    detail = client.get("/api/v1/orders/o1").json()
    assert len(detail["products"]) == 2
    assert len(detail["replay_payload"]["items"]) == 2
    assert detail["observed_after_purchase"]["order_status"] == "delivered"
    assert "delivered_at" not in str(detail["replay_payload"])
    assert "review" not in str(detail["replay_payload"])
    assert client.get("/api/v1/orders/o3").json()["replay_payload"] is None
    assert client.get("/api/v1/orders/absent").status_code == 404
    assert client.get("/api/v1/orders", params={"product_category": "books"}).json()["total"] == 2
    assert settings.database_path.exists()


def test_review_persistence_authorization_conflict_and_isolation(application):
    settings, client = application
    before = settings.database_path.read_bytes()
    update = {"status": "investigating", "notes": "Compare carrier milestones", "expected_revision": 0}
    url = "/api/v1/orders/o1/review"
    assert client.put(url, json=update).status_code == 403
    headers = {"Authorization": "Bearer test-token"}
    response = client.put(url, json=update, headers=headers)
    assert response.status_code == 200
    assert response.json()["revision"] == 1
    assert client.put(url, json=update, headers=headers).status_code == 409
    restarted = TestClient(create_app(settings))
    assert restarted.get("/api/v1/orders/o1").json()["review"]["notes"] == update["notes"]
    assert restarted.get("/api/v1/orders", params={"review_status": "investigating"}).json()["total"] == 1
    assert restarted.get("/api/v1/orders", params={"review_status": "pending"}).json()["total"] == 5
    assert client.put(url, json={**update, "status": "fraud"}, headers=headers).status_code == 422
    assert client.put("/api/v1/orders/missing/review", json=update, headers=headers).status_code == 404
    assert settings.database_path.read_bytes() == before


def test_replay_uses_existing_inference_contract_and_excludes_outcomes(application, monkeypatch):
    settings, client = application
    captured = []

    def predict(_self, orders):
        captured.extend(orders)
        return [RiskResponse(order_id=o.order_id, delay_probability=0.2, threshold=0.15,
            risk_category="high", model_version="saved-fixture", recommendation="Review",
            rationale=[], warnings=["Historical replay"]) for o in orders]

    monkeypatch.setattr("fulfilliq.modeling.inference.RiskService.predict", predict)
    response = client.post("/api/v1/orders/replay", json={
        "order_ids": ["o1", "o2", "o3", "absent"], "review_capacity": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["review_order_ids"] == ["o1"]
    assert len(body["predictions"]) == 2 and len(body["unavailable"]) == 2
    assert body["candidate_count"] == 4 and body["scored_count"] == 2
    assert body["model_version"] == "saved-fixture" and body["scored_at_utc"].endswith("+00:00")
    assert body["warehouse_snapshot"]
    assert captured[0].items[0].price == 100
    assert not hasattr(captured[0], "delivered_at")
    orders = OrderService(settings.database_path, ReviewStore(settings.review_database_path))
    assert orders.detail("o1")["replay_payload"] == captured[0].model_dump(mode="json")
    assert client.post("/api/v1/orders/replay", json={"order_ids": ["o1", "o1"], "review_capacity": 1}).status_code == 422


def test_replay_missing_saved_model_is_clear(application):
    _, client = application
    response = client.post("/api/v1/orders/replay", json={"order_ids": ["o1"], "review_capacity": 1})
    assert response.status_code == 503
    assert "model" in response.json()["detail"].lower()


def test_feedback_redaction_and_report_reproducibility(application):
    from fulfilliq.operations.feedback import redacted_excerpt

    _, client = application
    evidence = client.get("/api/v1/reviews/evidence", params={"seller_id": "s1"})
    assert evidence.status_code == 200
    assert evidence.json()["review_records"] == 3
    assert evidence.json()["score_counts"] == {"1": 1, "2": 1, "5": 1}
    assert "late_delivery" in evidence.json()["examples"][0]["themes"]
    assert "joao" not in redacted_excerpt("João entrega atrasada joao@example.com 11999999999 Rua Inventada")
    assert "inventada" not in redacted_excerpt("Rua Inventada")
    first = client.get("/api/v1/reports/operations", params={"seller_id": "s2"})
    assert first.status_code == 200
    assert first.json()["overview"]["total_orders"] == 1
    assert first.json() == client.get("/api/v1/reports/operations", params={"seller_id": "s2"}).json()
    assert "Historical Olist" in first.json()["markdown"]
    assert client.get("/api/v1/reports/operations", params={"region": "ZZ"}).json()["overview"]["total_orders"] == 0
    assert client.get("/api/v1/models/research").status_code == 200


def test_dependency_checks_do_not_generate_or_train(tmp_path):
    settings = Settings(data_dir=tmp_path, artifact_dir=tmp_path / "artifacts")
    client = TestClient(create_app(settings))
    result = client.get("/api/v1/console/dependencies")
    assert result.status_code == 200
    assert all(not row["ready"] for row in result.json()["dependencies"])
    assert not result.json()["review_writes_enabled"]
    assert not settings.database_path.exists()
    assert not settings.artifact_dir.exists()


def test_active_seller_counts_follow_item_filters(application):
    _, client = application
    assert client.get("/api/v1/analytics/overview").json()["active_sellers"] == 2
    assert client.get("/api/v1/analytics/overview", params={"seller_id": "s1"}).json()["active_sellers"] == 1
    assert client.get("/api/v1/analytics/overview", params={"product_category": "books"}).json()["active_sellers"] == 1
    assert client.get("/api/v1/analytics/overview", params={"region": "ZZ"}).json()["active_sellers"] == 0


def test_discovery_outcomes_statuses_counts_and_pagination(application):
    _, client = application
    assert client.get("/api/v1/orders", params={"order_status": "canceled"}).json()["items"][0]["order_id"] == "o3"
    assert client.get("/api/v1/orders", params={"delivery_outcome": "late"}).json()["total"] == 2
    assert client.get("/api/v1/orders", params={"delivery_outcome": "on_time"}).json()["total"] == 0
    assert client.get("/api/v1/orders", params={"delivery_outcome": "unavailable"}).json()["total"] == 4
    first = client.get("/api/v1/orders", params={"limit": 2}).json()
    second = client.get("/api/v1/orders", params={"limit": 2, "offset": 2}).json()
    assert not ({r["order_id"] for r in first["items"]} & {r["order_id"] for r in second["items"]})
    assert first["review_counts"]["pending"] == first["cohort_total"] == 6
    client.put("/api/v1/orders/o1/review", json={"status": "resolved", "notes": "Synthetic test", "expected_revision": 0},
               headers={"Authorization": "Bearer test-token"})
    result = client.get("/api/v1/orders", params={"review_status": "pending", "order_ids": ["o1", "o2"]}).json()
    assert result["total"] == 1 and result["cohort_total"] == 2
    assert result["review_counts"]["resolved"] == 1
    assert [r["order_id"] for r in result["items"]] == ["o2"]
    assert client.get("/api/v1/orders", params={"order_status": "fictional"}).status_code == 422
    assert client.get("/api/v1/orders", params={"delivery_outcome": "predicted"}).status_code == 422
    assert client.get("/api/v1/orders", params={"order_ids": ["o1"] * 101}).status_code == 422
    options = client.get("/api/v1/console/options").json()
    assert "canceled" in options["order_statuses"] and options["warehouse_snapshot"]
