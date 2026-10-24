"""Train/build from the original nine-table schema, then exercise every HTTP route."""

from datetime import datetime, timedelta

import pytest
from conftest import write_source
from fastapi.testclient import TestClient

from fulfilliq.analytics.build import build_insights
from fulfilliq.analytics.reporting import export_experiment
from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.modeling.training import train_delivery_model


def complete_raw(directory, n=400):
    directory.mkdir()
    customers, orders, items, payments, reviews = [], [], [], [], []

    def stamp(value):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    for i in range(n):
        purchase = datetime(2017, 1, 1, 12) + timedelta(days=i)
        late = i % 5 in {0, 1}
        delivery = purchase + timedelta(days=14 if late else 6)
        order_id = f"order{i:04}"
        customers.append(
            {
                "customer_id": f"c{i}",
                "customer_unique_id": f"u{i}",
                "customer_state": "RJ" if i % 2 else "SP",
                "customer_city": "Cidade",
                "customer_zip_code_prefix": "00001",
            }
        )
        orders.append(
            {
                "order_id": order_id,
                "customer_id": f"c{i}",
                "order_status": "delivered",
                "order_purchase_timestamp": stamp(purchase),
                "order_approved_at": stamp(purchase + timedelta(hours=1)),
                "order_delivered_carrier_date": stamp(purchase + timedelta(days=1 + i % 3)),
                "order_delivered_customer_date": stamp(delivery),
                "order_estimated_delivery_date": stamp(purchase + timedelta(days=10)),
            }
        )
        for j in range(2 if i % 3 == 0 else 1):
            items.append(
                {
                    "order_id": order_id,
                    "order_item_id": j + 1,
                    "product_id": f"p{j}",
                    "seller_id": f"s{(i + j) % 8}",
                    "price": 30 + i % 50,
                    "freight_value": 10 + i % 10,
                    "shipping_limit_date": stamp(purchase + timedelta(days=3)),
                }
            )
        payments.append(
            {
                "order_id": order_id,
                "payment_sequential": 1,
                "payment_type": "credit_card",
                "payment_installments": 1,
                "payment_value": 50 + i % 50,
            }
        )
        suffix = chr(97 + i // 26) + chr(97 + i % 26)
        reviews.append(
            {
                "review_id": f"r{i}",
                "order_id": order_id,
                "review_score": 1 if late else 5,
                "review_comment_message": (
                    "entrega atrasada pessima " if late else "entrega rapida otima antes do prazo "
                )
                + suffix,
                "review_creation_date": stamp(delivery),
                "review_answer_timestamp": stamp(delivery + timedelta(days=1)),
            }
        )
    for name, data in (
        ("customers", customers),
        ("orders", orders),
        ("order_items", items),
        ("order_payments", payments),
        ("order_reviews", reviews),
    ):
        write_source(directory, name, data)
    write_source(
        directory,
        "sellers",
        [
            {
                "seller_id": f"s{i}",
                "seller_state": "SP" if i % 2 else "AM",
                "seller_zip_code_prefix": "00002",
                "seller_city": "Cidade",
            }
            for i in range(8)
        ],
    )
    write_source(
        directory,
        "products",
        [
            {
                "product_id": f"p{i}",
                "product_category_name": "livros",
                "product_weight_g": 100 + i * 100,
                "product_length_cm": 10,
                "product_height_cm": 3,
                "product_width_cm": 8,
            }
            for i in range(2)
        ],
    )
    write_source(
        directory,
        "category_translation",
        [{"product_category_name": "livros", "product_category_name_english": "books"}],
    )
    write_source(
        directory,
        "geolocation",
        [
            {
                "geolocation_zip_code_prefix": "00001",
                "geolocation_lat": -23,
                "geolocation_lng": -45,
            },
            {
                "geolocation_zip_code_prefix": "00002",
                "geolocation_lat": -25,
                "geolocation_lng": -47,
            },
        ],
    )


@pytest.fixture(scope="module")
def integrated_backend(tmp_path_factory):
    root = tmp_path_factory.mktemp("integrated-backend")
    settings = Settings(data_dir=root / "data", artifact_dir=root / "artifacts")
    settings.data_dir.mkdir()
    complete_raw(settings.raw_dir)
    ingest(settings.raw_dir, settings.database_path, settings.processed_dir)
    metadata = train_delivery_model(
        settings.database_path, settings.artifact_dir, quick=True, maturity_days=0
    )
    build_insights(settings, min_support=0.1, min_seller_orders=1, anomaly_min_orders=5)
    with TestClient(create_app(settings)) as client:
        yield client, settings, metadata


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/api/v1/analytics/overview",
        "/api/v1/analytics/delivery-performance",
        "/api/v1/analytics/bottlenecks?min_orders=1",
        "/api/v1/mining/association-rules",
        "/api/v1/mining/anomalies",
        "/api/v1/sellers/segments",
        "/api/v1/sellers/s1/insights",
        "/api/v1/reviews/insights",
        "/api/v1/models/metrics",
        "/api/v1/models/info",
    ],
)
def test_integrated_get_routes(integrated_backend, path):
    client, _, _ = integrated_backend
    response = client.get(path)
    assert response.status_code == 200, response.text


def test_live_scoring_batch_parity_and_filters(integrated_backend):
    client, _, metadata = integrated_backend
    payload = {
        "order_id": "new",
        "purchased_at": "2018-03-01T12:00:00",
        "estimated_delivery_at": "2018-03-15T00:00:00",
        "customer_state": "SP",
        "items": [
            {
                "seller_id": "s1",
                "seller_state": "SP",
                "product_category": "books",
                "quantity": 2,
                "price": 40,
                "freight_value": 10,
                "weight_g": 100,
            }
        ],
    }
    single = client.post("/api/v1/orders/predict-delay", json=payload)
    assert single.status_code == 200, single.text
    batch = client.post("/api/v1/orders/predict-batch", json={"orders": [payload]})
    assert batch.status_code == 200, batch.text
    assert batch.json()["predictions"][0] == single.json()
    assert single.json()["model_version"] == metadata["model_version"]
    assert single.json()["recommendation"]
    assert client.get("/api/v1/analytics/overview?region=RJ").json()["total_orders"] == 200
    response = client.get("/api/v1/analytics/delivery-performance?group_by=seller&limit=2&offset=1")
    assert len(response.json()["items"]) == 2
    assert response.json()["total"] == 8
    assert client.get("/api/v1/sellers/absent/insights").status_code == 404
    assert client.get("/api/v1/reviews/insights?group_by=seller&group=s1").json()["total"] == 1
    assert (
        client.get(
            "/api/v1/analytics/overview?start_date=2018-01-02&end_date=2018-01-01"
        ).status_code
        == 422
    )
    assert client.get("/api/v1/mining/anomalies?limit=0").status_code == 422
    assert (
        client.post(
            "/api/v1/orders/predict-delay",
            json={**payload, "actual_delivery_timestamp": "2018-03-10"},
        ).status_code
        == 422
    )


def test_unbuilt_and_corrupted_artifacts_fail_cleanly(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", artifact_dir=tmp_path / "artifacts")
    with TestClient(create_app(settings)) as client:
        for path in [
            "/api/v1/models/info",
            "/api/v1/mining/association-rules",
            "/api/v1/analytics/overview",
            "/api/v1/sellers/segments",
        ]:
            response = client.get(path)
            assert response.status_code == 503, response.text
            assert "detail" in response.json()
        assert client.post("/api/v1/orders/predict-delay", json={}).status_code == 422


def test_openapi_documents_all_backend_routes(integrated_backend):
    client, _, _ = integrated_backend
    paths = client.get("/openapi.json").json()["paths"]
    assert len(paths) >= 13
    assert "/api/v1/orders/predict-batch" in paths
    assert "200" in paths["/api/v1/models/metrics"]["get"]["responses"]


def test_aggregate_report_and_reingestion_compatibility(integrated_backend, tmp_path):
    client, settings, _ = integrated_backend
    result = export_experiment(settings, tmp_path / "experiment.json")
    assert result["model"]["selected_model"]
    assert "assignments" not in result["seller_segments"]
    assert "anomalies" not in result["anomalies"]
    assert "by_seller" not in result["reviews"]
    # A rebuilt database with identical source hashes remains compatible with saved artifacts.
    ingest(settings.raw_dir, settings.database_path, settings.processed_dir)
    assert client.get("/api/v1/models/info").status_code == 200
    assert client.get("/api/v1/reviews/insights").status_code == 200


def test_changed_sources_reject_stale_models_and_reports(integrated_backend):
    client, settings, _ = integrated_backend
    source = settings.raw_dir / "olist_orders_dataset.csv"
    original = source.read_bytes()
    try:
        source.write_bytes(original.replace(b",delivered,", b",shipped,", 1))
        ingest(settings.raw_dir, settings.database_path, settings.processed_dir)
        assert client.get("/api/v1/models/info").status_code == 503
        assert client.get("/api/v1/mining/association-rules").status_code == 503
    finally:
        source.write_bytes(original)
        ingest(settings.raw_dir, settings.database_path, settings.processed_dir)


def test_corrupt_insight_shape_fails_cleanly(integrated_backend):
    client, settings, _ = integrated_backend
    report = settings.artifact_dir / "insights/rules.json"
    original = report.read_bytes()
    try:
        report.write_text("[]")
        assert client.get("/api/v1/mining/association-rules").status_code == 503
    finally:
        report.write_bytes(original)
