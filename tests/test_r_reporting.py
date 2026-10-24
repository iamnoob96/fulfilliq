"""R is optional; Python exports and verification remain deterministic without R installed."""

import csv
import json

import pytest
from fastapi.testclient import TestClient

from fulfilliq.analytics.r_export import export_r_inputs, verify_r_outputs
from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.ingestion.pipeline import ingest


def test_r_exports_exact_transactions_and_refuses_changed_inputs(raw_dir, tmp_path):
    settings = Settings(data_dir=tmp_path, artifact_dir=tmp_path / "artifacts")
    ingest(raw_dir, settings.database_path, settings.processed_dir)
    output = tmp_path / "inputs"
    manifest = export_r_inputs(settings, output, sample_size=100)
    with (output / "transactions.csv").open() as stream:
        baskets = list(csv.reader(stream))
    assert len(baskets) == manifest["transaction_count"] == 2
    assert all(len(basket) == 9 for basket in baskets)
    assert all("outcome=late" in basket for basket in baskets)
    assert manifest["plot_order_count"] == 2
    original = (output / "transactions.csv").read_bytes()
    export_r_inputs(settings, output, sample_size=100)
    assert original == (output / "transactions.csv").read_bytes()
    (output / "transactions.csv").write_text("changed")
    results = tmp_path / "results"
    results.mkdir()
    with pytest.raises(ValueError, match="input changed"):
        verify_r_outputs(settings, output, results)
    assert not (results / "summary.json").exists()


def test_r_report_optional_and_file_access_is_bounded(tmp_path):
    client = TestClient(create_app(Settings(data_dir=tmp_path, artifact_dir=tmp_path / "artifacts")))
    response = client.get("/api/v1/reports/r")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert "Optional R" in response.json()["message"]
    assert client.get("/api/v1/reports/r/files/secret.env").status_code == 404


def test_r_verification_rejects_rule_disagreement(raw_dir, tmp_path):
    settings = Settings(data_dir=tmp_path, artifact_dir=tmp_path / "artifacts")
    ingest(raw_dir, settings.database_path, settings.processed_dir)
    inputs, output = tmp_path / "inputs", tmp_path / "r-results"
    export_r_inputs(settings, inputs, sample_size=100)
    output.mkdir()
    (output / "r-session.json").write_text('{"r_version":"unit fixture"}')
    (output / "input-manifest.json").write_bytes((inputs / "manifest.json").read_bytes())
    rules = json.loads((inputs / "python-rules.json").read_text())["rules"]
    with (output / "rules.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["antecedents", "support", "confidence", "lift"])
        writer.writeheader()
        for rule in rules or [{"antecedents": ["unrecognized=value"], "confidence": .5, "lift": 2}]:
            writer.writerow({"antecedents": "|".join(rule["antecedents"]), "support": .99,
                             "confidence": rule["confidence"], "lift": rule["lift"]})
    with pytest.raises(ValueError, match="metric differs|rule identities differ"):
        verify_r_outputs(settings, inputs, output)
