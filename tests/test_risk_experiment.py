import json

import pytest
from fastapi.testclient import TestClient
from test_end_to_end import complete_raw

from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.modeling.experiment import (
    promotion_checks,
    run_risk_experiment,
    selection_key,
)
from fulfilliq.modeling.inference import ModelUnavailable, RiskService
from fulfilliq.modeling.training import train_delivery_model


def test_bounded_challenger_roundtrip_and_no_automatic_promotion(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", artifact_dir=tmp_path / "artifacts")
    settings.data_dir.mkdir()
    complete_raw(settings.raw_dir)
    ingest(settings.raw_dir, settings.database_path, settings.processed_dir)
    baseline = train_delivery_model(
        settings.database_path, settings.artifact_dir, quick=True, maturity_days=0
    )
    pointer = settings.artifact_dir / "delivery/current.json"
    original = pointer.read_bytes()
    output = tmp_path / "experiment.json"
    report = run_risk_experiment(settings.database_path, settings.artifact_dir, output, quick=True)
    assert not report["promoted"]
    assert pointer.read_bytes() == original
    assert len(report["validation_candidates"]) == 4
    assert all("test" not in row for row in report["validation_candidates"].values())
    assert report["split"] == baseline["split"]
    assert all(len(value) == 64 for value in report["split_membership_sha256"].values())
    assert json.loads(output.read_text()) == report
    with pytest.raises(ValueError, match="preserve provenance"):
        run_risk_experiment(settings.database_path, settings.artifact_dir, output, quick=True)
    version = report["challenger_model_version"]
    pointer.write_text(json.dumps({"version": version}))
    service = RiskService(settings.artifact_dir, settings.database_path)
    assert service.load()["feature_version"] == 2
    payload = {
        "order_id": "query",
        "purchased_at": "2018-03-01",
        "estimated_delivery_at": "2018-03-15",
        "customer_state": "SP",
        "items": [{"seller_id": "cold", "seller_state": "SP", "price": 50, "freight_value": 10}],
    }
    with TestClient(create_app(settings)) as client:
        single = client.post("/api/v1/orders/predict-delay", json=payload)
        assert single.status_code == 200, single.text
        batch = client.post("/api/v1/orders/predict-batch", json={"orders": [payload]})
        assert batch.status_code == 200
        assert batch.json()["predictions"][0] == single.json()
        assert single.json()["model_version"] == version
        assert 0 <= single.json()["delay_probability"] <= 1
        assert client.get("/api/v1/models/metrics").status_code == 200
        assert client.get("/api/v1/models/info").status_code == 200
    metadata_path = settings.artifact_dir / "delivery" / version / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["feature_version"] = 1
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ModelUnavailable, match="schema is incompatible"):
        RiskService(settings.artifact_dir, settings.database_path).load()


def metrics(p10=0.2, ap=0.2, brier=0.05, roc=0.8, recall=0.3):
    return {
        "precision_at_top_10_percent": p10,
        "pr_auc_average_precision": ap,
        "brier_score": brier,
        "roc_auc": roc,
        "review_budgets": {key: {"precision": p10, "recall": recall} for key in ("5", "10", "20")},
    }


def test_promotion_requires_every_gate_and_validation_selection_ignores_test():
    baseline = metrics(p10=0.1, ap=0.1, brier=0.07)
    challenger = metrics()
    constants = {name: metrics(brier=0.06) for name in ("validation", "test")}
    assert all(promotion_checks(baseline, challenger, baseline, challenger, constants).values())
    assert not all(
        promotion_checks(baseline, challenger, baseline, metrics(brier=0.08), constants).values()
    )
    assert not all(
        promotion_checks(baseline, challenger, baseline, metrics(recall=0.1), constants).values()
    )
    assert selection_key(metrics(p10=0.3, ap=0.1)) > selection_key(metrics(p10=0.2, ap=0.4))
    assert selection_key(metrics(brier=0.04)) > selection_key(metrics(brier=0.05))
