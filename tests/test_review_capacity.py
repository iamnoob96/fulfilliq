import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_risk_features_v2 import events, request

from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.features.orders import OutcomeHistory
from fulfilliq.modeling.contracts import RiskResponse
from fulfilliq.modeling.inference import ModelUnavailable, RiskService


@pytest.fixture
def client(monkeypatch, tmp_path):
    def predict(self, orders):
        scores = {"a": 0.3, "b": 0.9, "c": 0.3}
        return [
            RiskResponse(
                order_id=order.order_id,
                delay_probability=scores[order.order_id],
                threshold=0.5,
                risk_category="high" if scores[order.order_id] >= 0.5 else "standard",
                model_version="test",
                recommendation="Investigate",
                rationale=[],
                warnings=[],
            )
            for order in orders
        ]

    monkeypatch.setattr(RiskService, "predict", predict)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as result:
        yield result


def payload():
    return {"orders": [request(order_id=name).model_dump(mode="json") for name in ("a", "b", "c")]}


@pytest.mark.parametrize(
    "capacity, expected", [(None, []), (0, []), (1, ["b"]), (2, ["b", "a"]), (3, ["b", "a", "c"])]
)
def test_review_capacity_and_stable_ties_preserve_legacy_queue(client, capacity, expected):
    body = payload()
    if capacity is not None:
        body["review_capacity"] = capacity
    response = client.post("/api/v1/orders/predict-batch", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["review_order_ids"] == expected
    assert response.json()["priority_order_ids"] == ["b"]
    assert [row["order_id"] for row in response.json()["predictions"]] == ["a", "b", "c"]


@pytest.mark.parametrize("capacity", [-1, 4, 1.5, True, "2"])
def test_invalid_review_capacity(client, capacity):
    response = client.post(
        "/api/v1/orders/predict-batch", json={**payload(), "review_capacity": capacity}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "values",
    [
        [[np.nan, 0.5]],
        [[np.inf, -np.inf]],
        [[-0.1, 1.1]],
        [[0.2, 0.2]],
        [[0.1]],
        [[0.1, 0.9], [0.1, 0.9]],
    ],
)
def test_model_probability_guard(monkeypatch, tmp_path, values):
    orders, items = events()
    service = RiskService(tmp_path, tmp_path / "unused.sqlite3")
    history = OutcomeHistory(orders, items)

    class InvalidPipeline:
        def predict_proba(self, frame):
            return values

    service.bundle = {"pipeline": InvalidPipeline(), "history": history}
    monkeypatch.setattr(service, "load", lambda: {})
    with pytest.raises(ModelUnavailable, match="invalid risk probabilities"):
        service.predict([request()])
