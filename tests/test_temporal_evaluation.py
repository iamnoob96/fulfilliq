import json

import numpy as np
import pytest
from pandas.testing import assert_frame_equal
from test_end_to_end import complete_raw

from fulfilliq.config import Settings
from fulfilliq.features.risk_v2 import NEW_NUMERIC
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.modeling.drift import numeric_psi, probability_metrics, summarize_policies
from fulfilliq.modeling.rolling import RollingConfig, rolling_folds
from fulfilliq.modeling.temporal_evaluation import fit_fold, run_temporal_evaluation
from fulfilliq.modeling.training import train_delivery_model


def small_config(**changes):
    return RollingConfig(
        **{
            **dict(
                train_days=90,
                calibration_days=60,
                evaluation_days=30,
                step_days=60,
                gap_days=3,
                maturity_days=0,
                min_observations=10,
                min_positives=2,
                isotonic_min_observations=20,
                isotonic_min_positives=2,
            ),
            **changes,
        }
    )


def test_calibration_metrics_boundaries_and_distribution_shift():
    values = probability_metrics([0, 0, 1, 1], [0.0, 0.0, 1.0, 1.0], 0.5)
    assert values["ece_10_equal_width"] == 0
    assert [row["count"] for row in values["reliability_equal_width"]] == [2, 2]
    assert numeric_psi([1.0, 1.0, np.nan], [1.0, 1.0, np.nan]) == 0
    assert numeric_psi([1.0, 1.0, np.nan], [9.0, 9.0, 9.0]) > 1
    assert numeric_psi([np.nan], [1.0]) is None


def test_calibrator_isolation_thresholds_and_determinism(training_frame, monkeypatch):
    frame = training_frame.copy()
    for name in NEW_NUMERIC:
        frame[name] = 1.0
    frame["primary_route"] = "SP>RJ"
    fold = rolling_folds(frame, small_config(), protected_start="2018-01-01", as_of="2018-03-01")[
        0
    ][0]
    from fulfilliq.modeling import temporal_evaluation as module

    original_fit = module.CalibratedClassifierCV.fit
    observed = []

    def capture(calibrator, features, labels, *args, **kwargs):
        observed.append(list(features.index))
        assert not set(features.index) & set(fold.evaluation.index)
        return original_fit(calibrator, features, labels, *args, **kwargs)

    monkeypatch.setattr(module.CalibratedClassifierCV, "fit", capture)
    first = fit_fold(fold, small_config(), quick=True)
    second = fit_fold(fold, small_config(), quick=True)
    assert first["policies"] == second["policies"]
    assert observed == [list(fold.calibration.index)] * 4
    original_calibration = fold.calibration.copy()
    fold.evaluation["target_is_late"] = 1 - fold.evaluation.target_is_late.astype(int)
    changed = fit_fold(fold, small_config(), quick=True)
    assert {name: m["threshold"] for name, m in first["policies"].items()} == {
        name: m["threshold"] for name, m in changed["policies"].items()
    }
    assert_frame_equal(original_calibration, fold.calibration)
    without_isotonic = fit_fold(fold, small_config(isotonic_min_observations=10000), quick=True)
    assert "isotonic" not in without_isotonic["policies"]
    assert without_isotonic["skipped_policies"][0]["policy"] == "isotonic"


def test_advisory_policy_requires_every_window_and_ranking_safety():
    raw = probability_metrics([0, 0, 1, 1], [0.1, 0.2, 0.7, 0.9], 0.5)
    raw.update(
        brier_skill_vs_recent_prevalence=0.1,
        brier_skill_vs_training_prevalence=0.1,
        ap_delta_vs_raw=0.0,
        top10_precision_delta_vs_raw=0.0,
    )
    bad = {**raw, "brier_skill_vs_recent_prevalence": -0.1}
    folds = [{"policies": {"raw": raw, "sigmoid": bad}} for _ in range(3)]
    summary = summarize_policies(folds)
    assert summary["recommended_policy"] == "raw"
    assert summarize_policies(folds, failed_folds=1)["recommended_policy"] is None
    folds[-1]["policies"]["raw"] = bad
    assert summarize_policies(folds)["recommended_policy"] is None
    incomplete = [
        {"policies": {"raw": raw, "isotonic": raw}},
        {"policies": {"raw": raw}},
        {"policies": {"raw": raw}},
    ]
    assert not summarize_policies(incomplete)["policies"]["isotonic"]["ranking_safe_full_coverage"]
    degraded = {**raw, "top10_precision_delta_vs_raw": -0.02}
    assert not summarize_policies([{"policies": {"isotonic": degraded}}] * 3)["policies"][
        "isotonic"
    ]["ranking_safe_full_coverage"]


def test_real_schema_runner_preserves_artifacts_and_reports_failures(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", artifact_dir=tmp_path / "artifacts")
    settings.data_dir.mkdir()
    complete_raw(settings.raw_dir)
    ingest(settings.raw_dir, settings.database_path, settings.processed_dir)
    train_delivery_model(settings.database_path, settings.artifact_dir, quick=True, maturity_days=0)
    pointer = settings.artifact_dir / "delivery/current.json"
    original = pointer.read_bytes()
    output = tmp_path / "rolling.json"
    report = run_temporal_evaluation(
        settings.database_path, settings.artifact_dir, output, small_config(), quick=True
    )
    assert report["status"] == "complete"
    assert len(report["folds"]) >= 3
    assert report["active_model_unchanged"] and pointer.read_bytes() == original
    assert json.loads(output.read_text()) == report
    assert "Across-window stability" in output.with_suffix(".md").read_text()
    assert all(fold["evaluation_end"] <= report["protected_start"] for fold in report["folds"])
    with pytest.raises(ValueError, match="preserved"):
        run_temporal_evaluation(
            settings.database_path, settings.artifact_dir, output, small_config(), quick=True
        )
    from fulfilliq.modeling import temporal_evaluation as module

    def fail(*args, **kwargs):
        raise ValueError("Injected fitting failure")

    monkeypatch.setattr(module, "fit_fold", fail)
    failed = run_temporal_evaluation(
        settings.database_path,
        settings.artifact_dir,
        tmp_path / "failures.json",
        small_config(),
        quick=True,
    )
    assert failed["status"] == "no_valid_folds"
    assert failed["failed_folds"] and failed["summary"]["recommended_policy"] is None
    assert pointer.read_bytes() == original
