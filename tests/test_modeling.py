import json

import pandas as pd
import pytest
from pydantic import ValidationError

from fulfilliq.features.orders import (
    FEATURES,
    OutcomeHistory,
    build_dataset,
)
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.modeling.contracts import BatchRequest, OrderRequest
from fulfilliq.modeling.evaluation import choose_threshold, evaluate
from fulfilliq.modeling.inference import ModelUnavailable, RiskService, request_features
from fulfilliq.modeling.temporal import calibration_partition, chronological_split
from fulfilliq.modeling.training import train_delivery_model


def example_order(**changes):
    value = {
        "order_id": "example",
        "purchased_at": "2018-07-01T12:00:00",
        "estimated_delivery_at": "2018-07-20T00:00:00",
        "customer_state": "RJ",
        "items": [
            {
                "seller_id": "s1",
                "seller_state": "SP",
                "product_category": "books",
                "price": 50,
                "freight_value": 10,
                "quantity": 2,
            }
        ],
    }
    value.update(changes)
    return OrderRequest.model_validate(value)


def test_purged_splits_and_future_labels(training_frame):
    split = chronological_split(training_frame, maturity_days=2)
    assert split.train.purchased_at.max() < split.validation.purchased_at.min()
    assert split.validation.purchased_at.max() < split.test.purchased_at.min()
    assert split.train.label_available_at.max() < pd.Timestamp(split.metadata["validation_start"])
    assert split.validation.label_available_at.max() < pd.Timestamp(split.metadata["test_start"])
    assert split.test.label_available_at.max() < pd.Timestamp(split.metadata["observation_cutoff"])
    assert not set(split.train.index) & set(split.test.index)
    base, calibration, boundary = calibration_partition(split.train, maturity_days=2)
    assert base.label_available_at.max() < boundary
    assert calibration.purchased_at.min() >= boundary
    assert not set(base.index) & set(calibration.index)
    changed = training_frame.copy()
    changed.loc[split.train.index[0], "label_available_at"] = pd.Timestamp("2030-01-01")
    assert split.train.index[0] not in chronological_split(changed, maturity_days=2).train.index
    with pytest.raises(ValueError, match="Fractions"):
        chronological_split(training_frame, train_fraction=1)


def test_validation_threshold_and_metrics():
    labels = [0, 0, 1, 1]
    probabilities = [0.05, 0.1, 0.7, 0.9]
    threshold = choose_threshold(labels, probabilities)
    assert threshold == 0.7
    metrics = evaluate(labels, probabilities, threshold)
    assert metrics["f1"] == metrics["roc_auc"] == metrics["pr_auc_average_precision"] == 1
    assert metrics["confusion_matrix"] == [[2, 0], [0, 2]]
    assert metrics["precision_at_top_10_percent"] == 1


def test_request_features_match_offline_item_aggregation(raw_dir, tmp_path):
    db = tmp_path / "db.sqlite3"
    ingest(raw_dir, db, tmp_path)
    frame, history, _, _ = build_dataset(db)
    request = example_order(
        order_id="o1",
        purchased_at="2018-01-01T12:00:00",
        estimated_delivery_at="2018-01-05T00:00:00",
        customer_state="SP",
        items=[
            {
                "seller_id": "s1",
                "seller_state": "SP",
                "product_category": "books",
                "price": 100,
                "freight_value": 10,
                "weight_g": 100,
                "length_cm": 10,
                "height_cm": 2,
                "width_cm": 10,
            },
            {
                "seller_id": "s2",
                "seller_state": "AM",
                "product_category": "sem_traducao",
                "price": 50,
                "freight_value": 5,
                "weight_g": 200,
            },
        ],
    )
    actual = request_features([request], history).loc["o1"]
    for name in FEATURES:
        if name == "distance_km":
            continue  # Request deliberately omits coordinates.
        expected = frame.loc["o1", name]
        assert pd.isna(actual[name]) and pd.isna(expected) or actual[name] == expected


def test_train_persist_infer_and_artifact_integrity(raw_dir, tmp_path, training_frame):
    db, artifacts = tmp_path / "db.sqlite3", tmp_path / "artifacts"
    ingest(raw_dir, db, tmp_path)
    events = training_frame.reset_index()
    history = OutcomeHistory(events, pd.DataFrame({"order_id": events.order_id, "seller_id": "s1"}))
    metadata = train_delivery_model(
        db, artifacts, frame=training_frame, history=history, maturity_days=0, quick=True
    )
    assert set(metadata["comparison"]) == {
        "logistic_regression",
        "random_forest",
        "hist_gradient_boosting",
    }
    assert metadata["features"] == FEATURES
    service = RiskService(artifacts, db)
    first = service.predict([example_order()])[0]
    second = service.predict([example_order()])[0]
    assert first == second
    assert 0 <= first.delay_probability <= 1
    assert first.model_version == metadata["model_version"]
    assert metadata["split"]["counts"]["test"] > 5
    model_path = artifacts / "delivery" / metadata["model_version"] / "model.joblib"
    model_path.write_bytes(b"damaged")
    with pytest.raises(ModelUnavailable, match="checksum"):
        RiskService(artifacts, db).load()
    assert json.loads((artifacts / "delivery" / "current.json").read_text())["version"]


@pytest.mark.parametrize(
    "changes",
    [
        {"delivered_at": "2018-07-04"},
        {"items": []},
        {"customer_state": "Brazil"},
        {"estimated_delivery_at": "2018-01-01"},
        {"customer_latitude": 95},
    ],
)
def test_prediction_validation_rejects_outcome_fields_and_bad_values(changes):
    with pytest.raises(ValidationError):
        example_order(**changes)


def test_batch_unique_ids_and_timezone_conversion():
    first = example_order()
    with pytest.raises(ValidationError, match="unique"):
        BatchRequest(orders=[first, first])
    order = example_order(purchased_at="2018-07-01T15:00:00Z")
    assert order.purchased_at.hour == 12


def test_missing_model_is_actionable(tmp_path):
    with pytest.raises(ModelUnavailable, match="fulfilliq train"):
        RiskService(tmp_path, tmp_path / "absent.sqlite3").load()
