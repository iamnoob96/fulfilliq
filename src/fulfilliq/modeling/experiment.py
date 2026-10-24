"""Bounded, validation-selected challenger; test evaluated only after selection freezes."""

import copy
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

from fulfilliq.features.orders import FEATURES
from fulfilliq.features.risk_v2 import (
    V2_CATEGORICAL,
    V2_FEATURES,
    V2_NUMERIC,
    build_dataset_v2,
)
from fulfilliq.ingestion.download import write_json
from fulfilliq.ingestion.validation import sha256_file
from fulfilliq.modeling.evaluation import choose_threshold, evaluate
from fulfilliq.modeling.inference import RiskService
from fulfilliq.modeling.temporal import calibration_partition, chronological_split
from fulfilliq.modeling.training import SEED, model_candidates

logger = logging.getLogger(__name__)


def preprocessing_v2():
    # Signed slack, calendar fields and proportions must not receive log1p.
    logged = [
        name
        for name in V2_NUMERIC
        if name
        in {
            "items_value",
            "freight_value",
            "total_weight_g",
            "total_volume_cm3",
            "distance_km",
            "item_count",
            "seller_count",
            "category_count",
            "seller_state_count",
            "seller_history_count",
            "region_history_count",
            "route_history_count",
            "freight_value_ratio",
            "promised_lead_days",
        }
    ]
    numeric = [name for name in V2_NUMERIC if name not in logged]

    def numeric_pipeline(log=False):
        steps = []
        if log:
            steps.append(("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")))
        return Pipeline(
            steps
            + [
                (
                    "impute",
                    SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                ),
                ("scale", StandardScaler()),
            ]
        )

    return ColumnTransformer(
        [
            ("logged", numeric_pipeline(True), logged),
            ("numeric", numeric_pipeline(), numeric),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="constant", fill_value="unknown")),
                        (
                            "onehot",
                            OneHotEncoder(
                                handle_unknown="ignore", min_frequency=20, sparse_output=False
                            ),
                        ),
                    ]
                ),
                V2_CATEGORICAL,
            ),
        ],
        sparse_threshold=0,
    )


def membership_hash(subset):
    return hashlib.sha256("\n".join(sorted(map(str, subset.index))).encode()).hexdigest()


def selection_key(metrics):
    # Sigmoid is monotone: numerical AP differences must not defeat Brier tie-breaking.
    return (
        round(metrics["review_budgets"]["10"]["precision"], 12),
        round(metrics["pr_auc_average_precision"], 12),
        -metrics["brier_score"],
    )


def promotion_checks(baseline_validation, validation, baseline_test, test, constants):
    return {
        "validation_top10_not_worse": validation["precision_at_top_10_percent"]
        >= baseline_validation["precision_at_top_10_percent"],
        "validation_ap_not_worse": validation["pr_auc_average_precision"]
        >= baseline_validation["pr_auc_average_precision"],
        "validation_brier_beats_constant": validation["brier_score"]
        <= constants["validation"]["brier_score"],
        "test_top10_relative_gain_20_percent": test["precision_at_top_10_percent"]
        >= 1.2 * baseline_test["precision_at_top_10_percent"],
        "test_ap_not_worse": test["pr_auc_average_precision"]
        >= baseline_test["pr_auc_average_precision"],
        "test_roc_auc_not_worse": test["roc_auc"] >= baseline_test["roc_auc"],
        "test_brier_not_worse": test["brier_score"] <= baseline_test["brier_score"],
        "test_brier_beats_constant": test["brier_score"] <= constants["test"]["brier_score"],
        **{
            f"test_recall_at_{budget}_not_materially_worse": test["review_budgets"][budget][
                "recall"
            ]
            >= baseline_test["review_budgets"][budget]["recall"] - 0.01
            for budget in ("5", "20")
        },
    }


def run_risk_experiment(
    database_path: Path,
    artifact_dir: Path,
    output: Path,
    *,
    promote_if_qualified=False,
    quick=False,
):
    """No model/test search. Saves one selected challenger even when promotion fails."""
    if output.exists():
        raise ValueError("Experiment output exists; use a new path to preserve provenance")
    active = RiskService(artifact_dir, database_path)
    baseline_metadata = active.load()
    if baseline_metadata["feature_version"] != 1:
        raise ValueError("This bounded protocol compares against the frozen schema-1 baseline")
    start = perf_counter()
    frame, history, _, _ = build_dataset_v2(
        database_path,
        lag_days=baseline_metadata["history_lag_days"],
        window_days=baseline_metadata["history_window_days"],
    )
    maturity = baseline_metadata["split"]["maturity_days"]
    split = chronological_split(
        frame, maturity_days=maturity, as_of=baseline_metadata["split"]["observation_cutoff"]
    )
    if split.metadata != baseline_metadata["split"]:
        raise ValueError("Frozen baseline split differs; refusing challenger evaluation")
    hashes = {
        name: membership_hash(getattr(split, name)) for name in ("train", "validation", "test")
    }
    base, calibration, boundary = calibration_partition(split.train, maturity_days=maturity)
    for subset in (base, calibration, split.validation, split.test):
        for name in V2_CATEGORICAL:
            subset[name] = subset[name].fillna("unknown")
    y_train = base.target_is_late.astype(int)
    y_val = split.validation.target_is_late.astype(int)
    fitted, comparisons = {}, {}
    with threadpool_limits(limits=2):
        for name, estimator in model_candidates(quick=quick).items():
            if name not in ("logistic_regression", "hist_gradient_boosting"):
                continue
            fit_start = perf_counter()
            pipeline = Pipeline([("preprocess", preprocessing_v2()), ("classifier", estimator)])
            pipeline.fit(base[V2_FEATURES], y_train)
            calibrated = CalibratedClassifierCV(FrozenEstimator(pipeline), method="sigmoid")
            calibrated.fit(calibration[V2_FEATURES], calibration.target_is_late.astype(int))
            for method, candidate in (("raw", pipeline), ("sigmoid", calibrated)):
                key = f"{name}_{method}_v2"
                values = candidate.predict_proba(split.validation[V2_FEATURES])[:, 1]
                metrics = evaluate(y_val, values, choose_threshold(y_val, values))
                comparisons[key] = {
                    "validation": metrics,
                    "fit_seconds": perf_counter() - fit_start,
                }
                fitted[key] = candidate
                logger.info(
                    "%s validation AP=%.4f P10=%.4f Brier=%.4f",
                    key,
                    metrics["pr_auc_average_precision"],
                    metrics["precision_at_top_10_percent"],
                    metrics["brier_score"],
                )
        selected = max(comparisons, key=lambda key: selection_key(comparisons[key]["validation"]))
        candidate, threshold = fitted[selected], comparisons[selected]["validation"]["threshold"]
        # Freeze selection before either baseline or challenger test predictions are evaluated.
        logger.info("Selection frozen: %s; beginning single final comparison", selected)
        baseline_pipeline = active.bundle["pipeline"]
        baseline_validation = evaluate(
            y_val,
            baseline_pipeline.predict_proba(split.validation[FEATURES])[:, 1],
            baseline_metadata["threshold"],
        )
        # Validation-only ablation isolates the old sigmoid's contribution to drift.
        raw_baseline = baseline_pipeline.estimator
        raw_values = raw_baseline.predict_proba(split.validation[FEATURES])[:, 1]
        raw_baseline_validation = evaluate(y_val, raw_values, choose_threshold(y_val, raw_values))
        y_test = split.test.target_is_late.astype(int)
        baseline_test = evaluate(
            y_test,
            baseline_pipeline.predict_proba(split.test[FEATURES])[:, 1],
            baseline_metadata["threshold"],
        )
        test = evaluate(y_test, candidate.predict_proba(split.test[V2_FEATURES])[:, 1], threshold)
        probability = float(y_train.mean())
        constants = {
            name: evaluate(
                subset.target_is_late.astype(int), np.full(len(subset), probability), 0.5
            )
            for name, subset in (("validation", split.validation), ("test", split.test))
        }
        sample = split.validation.sample(min(1500, len(split.validation)), random_state=SEED)
        importance = permutation_importance(
            candidate,
            sample[V2_FEATURES],
            sample.target_is_late.astype(int),
            scoring="average_precision",
            n_repeats=2,
            random_state=SEED,
            n_jobs=1,
        )
    checks = promotion_checks(
        baseline_validation, comparisons[selected]["validation"], baseline_test, test, constants
    )
    qualified = all(checks.values())
    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    metadata = copy.deepcopy(baseline_metadata)
    comparisons[selected]["test"] = test
    metadata.update(
        {
            "model_version": version,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "selected_model": selected,
            "selection_metric": "validation P@10%, then AP, then lower Brier",
            "threshold": threshold,
            "feature_version": 2,
            "features": V2_FEATURES,
            "comparison": {selected: comparisons[selected]},
            "baselines": {"training_prevalence": constants["test"]},
            "feature_importance": sorted(
                [
                    {"feature": name, "average_precision_decrease": float(mean), "std": float(std)}
                    for name, mean, std in zip(
                        V2_FEATURES,
                        importance.importances_mean,
                        importance.importances_std,
                        strict=True,
                    )
                ],
                key=lambda row: -row["average_precision_decrease"],
            ),
            "importance_method": "validation permutation AP decrease; 1500 rows, two repeats",
            "calibration": {
                "method": "sigmoid on reserved training quarter"
                if "sigmoid" in selected
                else "none: raw unweighted probabilities; reserved calibration quarter unused",
                "start": boundary.isoformat(),
                "base_train_count": len(base),
                "calibration_count": len(calibration) if "sigmoid" in selected else 0,
                "base_last_label_available": base.label_available_at.max().isoformat(),
            },
            "baseline_model_version": baseline_metadata["model_version"],
            "split_membership_sha256": hashes,
            "promotion_checks": checks,
        }
    )
    root = artifact_dir / "delivery"
    staging = Path(tempfile.mkdtemp(prefix=".challenger-", dir=root))
    try:
        joblib.dump(
            {"pipeline": candidate, "history": history}, staging / "model.joblib", compress=3
        )
        metadata["model_sha256"] = sha256_file(staging / "model.joblib")
        write_json(staging / "metadata.json", metadata)
        os.replace(staging, root / version)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    report = {
        "protocol": "docs/RISK_SPRINT.md",
        "created_at_utc": metadata["created_at_utc"],
        "code_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "quick": quick,
        "baseline_model_version": baseline_metadata["model_version"],
        "challenger_model_version": version,
        "selected_challenger": selected,
        "dataset": metadata["dataset"],
        "versions": metadata["versions"],
        "split": split.metadata,
        "split_membership_sha256": hashes,
        "training": {
            "base_count": len(base),
            "calibration_count": len(calibration),
            "base_late_rate": probability,
            "calibration_late_rate": float(calibration.target_is_late.astype(int).mean()),
            "calibration_start": boundary.isoformat(),
        },
        "validation_candidates": {
            name: {key: value for key, value in row.items() if key != "test"}
            for name, row in comparisons.items()
        },
        "baseline": {"validation": baseline_validation, "test": baseline_test},
        "baseline_without_sigmoid_validation_only": raw_baseline_validation,
        "challenger": {"validation": comparisons[selected]["validation"], "test": test},
        "training_prevalence_constant": constants,
        "brier_skill_vs_training_constant": {
            name: 1 - metrics["brier_score"] / constants["test"]["brier_score"]
            for name, metrics in (("baseline", baseline_test), ("challenger", test))
        },
        "test_prevalence_oracle_brier_descriptive_only": float(y_test.mean() * (1 - y_test.mean())),
        "feature_importance": metadata["feature_importance"],
        "promotion_checks": checks,
        "qualified": qualified,
        "promoted": bool(promote_if_qualified and qualified),
        "duration_seconds": perf_counter() - start,
    }
    write_json(output, report)
    if report["promoted"]:
        current = json.loads((root / "current.json").read_text())["version"]
        if current != baseline_metadata["model_version"]:
            raise ValueError("Active version changed during experiment; refusing promotion")
        # Validate saved bundle and schema before atomically changing the serving pointer.
        write_json(root / "current.json", {"version": version})
        try:
            RiskService(artifact_dir, database_path).load()
        except Exception:
            write_json(root / "current.json", {"version": current})
            raise
    return report
