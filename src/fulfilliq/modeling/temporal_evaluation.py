"""Offline rolling calibration research; never writes a serving model or pointer."""

import importlib.metadata
import logging
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.pipeline import Pipeline
from threadpoolctl import threadpool_limits

from fulfilliq.features.risk_v2 import V2_CATEGORICAL, V2_FEATURES, build_dataset_v2
from fulfilliq.ingestion.download import write_json
from fulfilliq.modeling.drift import feature_drift, probability_metrics, summarize_policies
from fulfilliq.modeling.evaluation import choose_threshold
from fulfilliq.modeling.experiment import membership_hash, preprocessing_v2
from fulfilliq.modeling.inference import RiskService
from fulfilliq.modeling.rolling import RollingConfig, rolling_folds
from fulfilliq.modeling.training import SEED, model_candidates

logger = logging.getLogger(__name__)


def fit_fold(fold, config: RollingConfig, *, quick=False) -> dict:
    start = perf_counter()
    estimator = model_candidates(quick=quick)["hist_gradient_boosting"]
    pipeline = Pipeline([("preprocess", preprocessing_v2()), ("classifier", estimator)])
    subsets = [fold.train.copy(), fold.calibration.copy(), fold.evaluation.copy()]
    for subset in subsets:
        for name in V2_CATEGORICAL:
            subset[name] = subset[name].fillna("unknown")
    train, calibration, evaluation = subsets
    x_cal, y_cal = calibration[V2_FEATURES], calibration.target_is_late.astype(int)
    x_eval, y_eval = evaluation[V2_FEATURES], evaluation.target_is_late.astype(int)
    y_train = train.target_is_late.astype(int)
    pipeline.fit(train[V2_FEATURES], y_train)
    fitted = {"raw": pipeline}
    skipped = []
    for method in ("sigmoid", "isotonic"):
        if method == "isotonic" and (
            len(calibration) < config.isotonic_min_observations
            or min(int(y_cal.sum()), int((y_cal == 0).sum())) < config.isotonic_min_positives
        ):
            skipped.append(
                {"policy": method, "reason": "Insufficient calibration support for isotonic"}
            )
            continue
        calibrated = CalibratedClassifierCV(FrozenEstimator(pipeline), method=method)
        calibrated.fit(x_cal, y_cal)
        fitted[method] = calibrated
    probabilities = {
        name: (model.predict_proba(x_cal)[:, 1], model.predict_proba(x_eval)[:, 1])
        for name, model in fitted.items()
    }
    for name, probability in (
        ("training_prevalence", float(y_train.mean())),
        ("recent_prevalence", float(y_cal.mean())),
    ):
        probabilities[name] = (np.full(len(y_cal), probability), np.full(len(y_eval), probability))
    metrics = {
        name: probability_metrics(
            y_eval, evaluation_values, choose_threshold(y_cal, calibration_values)
        )
        for name, (calibration_values, evaluation_values) in probabilities.items()
    }
    for values in metrics.values():
        for baseline, name in (
            ("recent_prevalence", "recent"),
            ("training_prevalence", "training"),
        ):
            values[f"brier_skill_vs_{name}_prevalence"] = (
                1 - values["brier_score"] / metrics[baseline]["brier_score"]
            )
        values["ap_delta_vs_raw"] = (
            values["pr_auc_average_precision"] - metrics["raw"]["pr_auc_average_precision"]
        )
        values["top10_precision_delta_vs_raw"] = (
            values["precision_at_top_10_percent"] - metrics["raw"]["precision_at_top_10_percent"]
        )
    return {
        **fold.metadata,
        "policies": metrics,
        "skipped_policies": skipped,
        "prevalence": {
            "training": float(y_train.mean()),
            "calibration": float(y_cal.mean()),
            "evaluation": float(y_eval.mean()),
        },
        "membership_sha256": {
            name: membership_hash(getattr(fold, name))
            for name in ("train", "calibration", "evaluation")
        },
        "fit_seconds": perf_counter() - start,
    }


def temporal_markdown(report: dict) -> str:
    lines = [
        "# Rolling-origin calibration results",
        "",
        f"Status: {report['status']}. Completed folds: {len(report['folds'])}; excluded windows: {len(report['excluded_windows'])}; fit failures: {len(report['failed_folds'])}.",
        f"Protected purchases: >= {report['protected_start']}; no model promotion.",
        "",
        "| Evaluation purchases | N | Late rate | Policy | AP | ROC-AUC | F1 | Brier | ECE | P@10% | Recall@10% |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fold in report["folds"]:
        window = fold["evaluation_start"][:10] + " to " + fold["evaluation_end"][:10]
        for name, metrics in fold["policies"].items():
            lines.append(
                f"| {window} | {metrics['samples']} | {metrics['late_rate']:.4f} | {name} | {metrics['pr_auc_average_precision']:.4f} | {metrics['roc_auc']:.4f} | {metrics['f1']:.4f} | {metrics['brier_score']:.5f} | {metrics['ece_10_equal_width']:.4f} | {metrics['review_budgets']['10']['precision']:.4f} | {metrics['review_budgets']['10']['recall']:.4f} |"
            )
    lines += [
        "",
        "## Across-window stability",
        "",
        "| Policy | Folds | Mean Brier | Worst Brier | Brier std | Mean recent-baseline skill | Worst skill | Mean AP | Worst P@10% |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in report["summary"]["policies"].items():
        m = row["metrics"]
        lines.append(
            f"| {name} | {row['folds']} | {m['brier_score']['mean']:.5f} | {m['brier_score']['worst']:.5f} | {m['brier_score']['std']:.5f} | {m['brier_skill_vs_recent_prevalence']['mean']:.4f} | {m['brier_skill_vs_recent_prevalence']['min']:.4f} | {m['pr_auc_average_precision']['mean']:.4f} | {m['top_10_precision']['worst']:.4f} |"
        )
    lines += [
        "",
        f"Advisory recommendation: {report['summary']['recommended_policy'] or 'none meets all consistency gates'}.",
        f"Least-worst ranking-safe policy: {report['summary']['least_worst_ranking_safe_policy'] or 'none'}.",
        "No promotion is permitted. Earlier inspected data remain exploratory; independent future observations are needed.",
        "",
        "## Exclusions and failures",
        "",
    ]
    for row in report["excluded_windows"] + report["failed_folds"]:
        lines.append(f"- {row.get('fold_id', 'no origin')}: {row['reason']}")
    return "\n".join(lines) + "\n"


def run_temporal_evaluation(
    database_path: Path, artifact_dir: Path, output: Path, config: RollingConfig, *, quick=False
) -> dict:
    markdown = output.with_suffix(".md")
    if output.suffix != ".json" or output.exists() or markdown.exists():
        raise ValueError("Use a new .json report path; existing experiment results are preserved")
    pointer_path = artifact_dir / "delivery/current.json"
    original_pointer = pointer_path.read_bytes()
    active = RiskService(artifact_dir, database_path).load()
    protected = active["split"]["test_start"]
    start = perf_counter()
    frame, _, _, items = build_dataset_v2(
        database_path,
        lag_days=active["history_lag_days"],
        window_days=active["history_window_days"],
        purchase_before=protected,
    )
    frame["prediction_at"] = frame.purchased_at
    folds, excluded = rolling_folds(
        frame, config, protected_start=protected, as_of=active["split"]["observation_cutoff"]
    )
    completed, failed = [], []
    with threadpool_limits(limits=2):
        for fold in folds:
            try:
                result = fit_fold(fold, config, quick=quick)
                result["feature_drift"] = feature_drift(
                    fold.train_cohort, fold.evaluation_cohort, items
                )
                completed.append(result)
                logger.info(
                    "Rolling fold %s: %d evaluation orders, raw Brier %.5f",
                    fold.fold_id,
                    len(fold.evaluation),
                    result["policies"]["raw"]["brier_score"],
                )
            except (ValueError, RuntimeError) as exc:
                logger.exception("Rolling fold %s failed", fold.fold_id)
                failed.append({**fold.metadata, "reason": f"{type(exc).__name__}: {exc}"})
    if pointer_path.read_bytes() != original_pointer:
        raise ValueError(
            "Active model pointer changed externally during evaluation; inspect concurrent work"
        )
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "status": "no_valid_folds"
        if not completed
        else "complete_with_failures"
        if failed
        else "complete",
        "config": asdict(config),
        "quick": quick,
        "seed": SEED,
        "model": "hist_gradient_boosting_schema_2_fixed_hyperparameters",
        "feature_version": 2,
        "features": V2_FEATURES,
        "protected_start": protected,
        "protected_test_cohort_size": active["split"]["counts"]["test"],
        "pre_protected_purchase_rows": len(frame),
        "snapshot_observation_cutoff": active["split"]["observation_cutoff"],
        "history_lag_days": active["history_lag_days"],
        "history_window_days": active["history_window_days"],
        "active_model_version": active["model_version"],
        "active_model_unchanged": True,
        "dataset": active["dataset"],
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("scikit-learn", "pandas", "numpy", "fulfilliq")
        },
        "folds": completed,
        "excluded_windows": excluded,
        "failed_folds": failed,
        "summary": summarize_policies(completed, len(failed)),
        "duration_seconds": perf_counter() - start,
        "limitations": [
            "Historical backtesting only; no contemporary production validity",
            "All policies examined on these windows: recommendation is exploratory, not an independent confirmation",
            "Delivered-only selection and residual right censoring remain",
            "Delivery plus reporting lag approximates observation time; static attributes assumed available at purchase",
            "Folds share training history and are time-dependent; no IID uncertainty claims",
            "No serving artifacts are written; original validation gates are preserved",
        ],
    }
    write_json(output, report)
    markdown.write_text(temporal_markdown(report))
    return report
