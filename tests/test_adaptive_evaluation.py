import json

import numpy as np
import pandas as pd
import pytest
from test_end_to_end import complete_raw

from fulfilliq.config import Settings
from fulfilliq.features.risk_v2 import NEW_NUMERIC, V2_FEATURES
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.modeling.adaptive_evaluation import (
    inner_windows_at,
    nested_evaluate,
    prepare_predictions,
    run_adaptive_evaluation,
)
from fulfilliq.modeling.calibration import calibrate_predictions, calibration_policies
from fulfilliq.modeling.rolling import RollingConfig, rolling_folds
from fulfilliq.modeling.training import train_delivery_model


def config():
    return RollingConfig(
        train_days=90,
        calibration_days=45,
        evaluation_days=30,
        step_days=30,
        gap_days=3,
        maturity_days=0,
        min_observations=5,
        min_positives=1,
    )


def synthetic_folds(training_frame):
    frame = training_frame.copy()
    for name in NEW_NUMERIC:
        frame[name] = 1.0
    frame["primary_route"] = "SP>RJ"
    return rolling_folds(frame, config(), protected_start="2018-01-01", as_of="2018-04-01")[0]


def test_inner_labels_are_strictly_known_at_outer_selection(training_frame):
    folds = synthetic_folds(training_frame)
    outer = folds[-1]
    inner, skipped, older = inner_windows_at(folds, outer, config())
    assert len(inner) == 3 and skipped
    cutoff = pd.Timestamp(outer.metadata["calibrator_fit_at"])
    for fold, eligible, observed_at in inner:
        assert pd.Timestamp(fold.metadata["evaluation_end"]) <= cutoff
        assert eligible.label_available_at.max() < cutoff
        assert not set(eligible.index) & set(outer.evaluation.index)
        assert observed_at <= cutoff
    fold, eligible, _ = inner[-1]
    changed_id = eligible.index[0]
    fold.evaluation_cohort.loc[changed_id, "label_available_at"] = cutoff
    changed = inner_windows_at(folds, outer, config())[0]
    assert changed_id not in changed[-1][1].index


def test_outer_outcome_perturbation_cannot_select_a_policy(training_frame):
    folds = synthetic_folds(training_frame)
    policies = calibration_policies((30,), (15,))
    first = nested_evaluate(folds, config(), policies, quick=True)
    assert len(first["folds"]) >= 3
    assert first["prediction_cache_hits"] > 0
    folds[-1].evaluation["target_is_late"] = 1 - folds[-1].evaluation.target_is_late.astype(int)
    folds[-1].evaluation_cohort["target_is_late"] = 1 - folds[
        -1
    ].evaluation_cohort.target_is_late.astype(int)
    second = nested_evaluate(folds, config(), policies, quick=True)
    assert [(f["selected_policy"], f["raw_fallback"]) for f in first["folds"]] == [
        (f["selected_policy"], f["raw_fallback"]) for f in second["folds"]
    ]
    assert first["folds"][-1]["inner_summary"] == second["folds"][-1]["inner_summary"]
    assert (
        first["folds"][-1]["policies"]["nested_selected"]["threshold"]
        == second["folds"][-1]["policies"]["nested_selected"]["threshold"]
    )
    for row in first["folds"]:
        assert set(row["policies"]) == {
            "raw",
            "sigmoid",
            "nested_selected",
            "recent_prevalence",
            "training_prevalence",
        }
        assert all(
            inner["last_observed_label"] < row["selection_cutoff"] for inner in row["inner_folds"]
        )


def test_weights_reach_calibrator_and_boundary_rejected(training_frame, monkeypatch):
    folds = synthetic_folds(training_frame)
    from fulfilliq.modeling import calibration as module

    original = module.CalibratedClassifierCV.fit
    weights = []

    def capture(model, X, y, sample_weight=None, **fit_params):
        weights.append(sample_weight)
        assert set(X.index).issubset(folds[0].calibration.index)
        return original(model, X, y, sample_weight=sample_weight, **fit_params)

    monkeypatch.setattr(module.CalibratedClassifierCV, "fit", capture)
    prepared = prepare_predictions(
        folds[0], calibration_policies((30,), (15,)), config(), quick=True
    )
    assert any(not np.allclose(w, 1) for w in weights)
    assert all(
        p["fit_audit"]["last_outcome_observed"] < p["fit_audit"]["cutoff"]
        for p in prepared["predictions"].values()
        if "fit_audit" in p
    )
    calibration = folds[0].calibration.copy()
    calibration.loc[calibration.index[0], "label_available_at"] = pd.Timestamp(
        folds[0].metadata["calibrator_fit_at"]
    )
    with pytest.raises(ValueError, match="unavailable or immature"):
        calibrate_predictions(
            None,
            calibration,
            folds[0].evaluation[V2_FEATURES],
            folds[0].metadata["calibrator_fit_at"],
            calibration_policies(),
            config(),
        )


def test_insufficient_policy_support_is_explicit(training_frame):
    fold = synthetic_folds(training_frame)[0]
    prepared = prepare_predictions(fold, calibration_policies((), (1,)), config(), quick=True)
    assert "rolling_sigmoid_1d" not in prepared["predictions"]
    assert prepared["unsupported_policies"][0]["policy"] == "rolling_sigmoid_1d"
    with pytest.raises(ValueError, match="three inner"):
        nested_evaluate([fold], config(), calibration_policies(), min_inner_folds=2)


def test_nested_real_schema_artifact_and_report_compatibility(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", artifact_dir=tmp_path / "artifacts")
    settings.data_dir.mkdir()
    complete_raw(settings.raw_dir, n=600)
    ingest(settings.raw_dir, settings.database_path, settings.processed_dir)
    train_delivery_model(settings.database_path, settings.artifact_dir, quick=True, maturity_days=0)
    pointer = settings.artifact_dir / "delivery/current.json"
    original = pointer.read_bytes()
    output = tmp_path / "adaptive.json"
    report = run_adaptive_evaluation(
        settings.database_path,
        settings.artifact_dir,
        output,
        config(),
        half_lives=(30,),
        windows=(15,),
        quick=True,
    )
    assert report["status"] == "complete", report["failed_folds"]
    assert report["folds"] and report["summary"]["selection_frequency"]
    assert pointer.read_bytes() == original and report["active_model_unchanged"]
    assert json.loads(output.read_text()) == report
    summary = json.loads(output.with_suffix(".summary.json").read_text())
    assert summary["folds"][0]["policies"] == report["folds"][0]["policies"]
    assert summary["full_report_sha256"] and summary["summary_format_version"] == 1
    assert "Nested recency-adaptive" in output.with_suffix(".md").read_text()
    assert all(row["evaluation_end"] <= report["protected_start"] for row in report["folds"])
    with pytest.raises(ValueError, match="preserved"):
        run_adaptive_evaluation(settings.database_path, settings.artifact_dir, output, config())


def test_outer_support_failure_falls_back_without_dropping_population(training_frame, monkeypatch):
    from fulfilliq.modeling import adaptive_evaluation as module

    monkeypatch.setattr(
        module, "select_inner_policy", lambda *args: ("rolling_sigmoid_1d", False, {})
    )
    results = nested_evaluate(
        synthetic_folds(training_frame), config(), calibration_policies((), (1,)), quick=True
    )
    assert results["folds"] and not results["failed_folds"]
    for row in results["folds"]:
        assert row["selected_policy"] == "raw" and row["raw_fallback"]
        assert row["inner_selected_policy"] == "rolling_sigmoid_1d"
        assert "effective support" in row["fallback_reason"]
