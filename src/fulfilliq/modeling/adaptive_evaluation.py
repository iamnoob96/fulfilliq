"""Nested historical policy selection with immutable outer evaluation windows."""

import copy
import importlib.metadata
import logging
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from threadpoolctl import threadpool_limits

from fulfilliq.features.risk_v2 import V2_CATEGORICAL, V2_FEATURES, build_dataset_v2
from fulfilliq.ingestion.download import write_json
from fulfilliq.ingestion.validation import sha256_file
from fulfilliq.modeling.calibration import calibrate_predictions, calibration_policies
from fulfilliq.modeling.censoring import censoring_diagnostics
from fulfilliq.modeling.drift import probability_metrics, summarize_policies
from fulfilliq.modeling.evaluation import choose_threshold
from fulfilliq.modeling.experiment import membership_hash, preprocessing_v2
from fulfilliq.modeling.inference import RiskService
from fulfilliq.modeling.rolling import RollingConfig, RollingFold, eligible_at, rolling_folds
from fulfilliq.modeling.training import SEED, model_candidates

logger = logging.getLogger(__name__)


def inner_windows_at(
    folds: list[RollingFold], outer: RollingFold, config: RollingConfig, *, max_inner_folds=3
):
    cutoff = pd.Timestamp(outer.metadata["calibrator_fit_at"])
    valid, excluded = [], []
    for fold in folds:
        if fold.metadata["evaluation_start"] >= outer.metadata["evaluation_start"]:
            continue
        if pd.Timestamp(fold.metadata["evaluation_end"]) > cutoff:
            excluded.append(
                {"fold_id": fold.fold_id, "reason": "Inner window not finished at selection cutoff"}
            )
            continue
        observed_at = min(cutoff, pd.Timestamp(fold.metadata["outcome_observation_cutoff"]))
        eligible = eligible_at(fold.evaluation_cohort, observed_at, config.maturity_days)
        labels = eligible.target_is_late.astype(int)
        if (
            len(eligible) < config.min_observations
            or min(int(labels.sum()), int((labels == 0).sum())) < config.min_positives
        ):
            excluded.append(
                {
                    "fold_id": fold.fold_id,
                    "reason": "Insufficient mature inner evaluation support at outer cutoff",
                    "eligible": len(eligible),
                }
            )
            continue
        valid.append((fold, eligible, observed_at))
    return (
        valid[-max_inner_folds:],
        excluded,
        [fold.fold_id for fold, _, _ in valid[:-max_inner_folds]],
    )


def prepare_predictions(fold: RollingFold, policies, config: RollingConfig, *, quick=False):
    train, calibration, evaluation = (
        fold.train.copy(),
        fold.calibration.copy(),
        fold.evaluation_cohort.copy(),
    )
    for subset in (train, calibration, evaluation):
        for column in V2_CATEGORICAL:
            subset[column] = subset[column].fillna("unknown")
    model = Pipeline(
        [
            ("preprocess", preprocessing_v2()),
            ("classifier", model_candidates(quick=quick)["hist_gradient_boosting"]),
        ]
    )
    model.fit(train[V2_FEATURES], train.target_is_late.astype(int))
    predictions, unsupported = calibrate_predictions(
        model,
        calibration,
        evaluation[V2_FEATURES],
        fold.metadata["calibrator_fit_at"],
        policies,
        config,
    )
    y_cal = calibration.target_is_late.astype(int)
    for name, value in (
        ("training_prevalence", float(train.target_is_late.astype(int).mean())),
        ("recent_prevalence", float(y_cal.mean())),
    ):
        predictions[name] = {
            "evaluation_probabilities": np.full(len(evaluation), value),
            "threshold": choose_threshold(y_cal, np.full(len(y_cal), value)),
        }
    for value in predictions.values():
        value.pop("calibration_probabilities", None)
        value["scores"] = pd.Series(value.pop("evaluation_probabilities"), index=evaluation.index)
    if not {"raw", "sigmoid"}.issubset(predictions):
        raise ValueError(
            "Raw and fixed sigmoid reference policies require adequate calibration support"
        )
    return {"predictions": predictions, "unsupported_policies": unsupported}


def evaluate_predictions(prepared, evaluation: pd.DataFrame, names=None) -> dict:
    names = list(prepared["predictions"]) if names is None else names
    metrics = {}
    for name in names:
        prediction = prepared["predictions"][name]
        metrics[name] = probability_metrics(
            evaluation.target_is_late.astype(int),
            prediction["scores"].loc[evaluation.index],
            prediction["threshold"],
        )
    for row in metrics.values():
        for baseline, short in (
            ("recent_prevalence", "recent"),
            ("training_prevalence", "training"),
        ):
            row[f"brier_skill_vs_{short}_prevalence"] = (
                1 - row["brier_score"] / metrics[baseline]["brier_score"]
            )
        row["ap_delta_vs_raw"] = (
            row["pr_auc_average_precision"] - metrics["raw"]["pr_auc_average_precision"]
        )
        row["top10_precision_delta_vs_raw"] = (
            row["precision_at_top_10_percent"] - metrics["raw"]["precision_at_top_10_percent"]
        )
    return metrics


def select_inner_policy(inner_results, candidates):
    summary = summarize_policies(inner_results, candidate_names=candidates)
    selected = summary["recommended_policy"]
    return selected or "raw", selected is None, summary


def nested_evaluate(
    folds: list[RollingFold],
    config: RollingConfig,
    policies,
    *,
    min_inner_folds=3,
    max_inner_folds=3,
    quick=False,
):
    if min_inner_folds < 3 or max_inner_folds < min_inner_folds:
        raise ValueError("Require at least three inner folds and max >= min")
    cache, failures, excluded, completed = {}, [], [], []
    cache_hits = 0

    def cached(fold):
        nonlocal cache_hits
        if fold.fold_id in cache:
            cache_hits += 1
        else:
            cache[fold.fold_id] = prepare_predictions(fold, policies, config, quick=quick)
        return cache[fold.fold_id]

    for outer in folds:
        inner, skipped, older = inner_windows_at(
            folds, outer, config, max_inner_folds=max_inner_folds
        )
        if len(inner) < min_inner_folds:
            excluded.append(
                {
                    "fold_id": outer.fold_id,
                    "reason": "Insufficient supported historical inner windows",
                    "supported_inner_folds": len(inner),
                    "excluded_inner_windows": skipped,
                }
            )
            continue
        try:
            inner_results = []
            for fold, eligible, observed_at in inner:
                prepared = cached(fold)
                inner_results.append(
                    {
                        "fold_id": fold.fold_id,
                        "evaluation_start": fold.metadata["evaluation_start"],
                        "evaluation_end": fold.metadata["evaluation_end"],
                        "outcome_observation_cutoff": observed_at.isoformat(),
                        "last_observed_label": eligible.label_available_at.max().isoformat(),
                        "membership_sha256": membership_hash(eligible),
                        "policies": evaluate_predictions(prepared, eligible),
                        "unsupported_policies": prepared["unsupported_policies"],
                    }
                )
            selected, fallback, selection = select_inner_policy(
                inner_results, [p.name for p in policies]
            )
            inner_selected = selected
            fallback_reason = (
                "No candidate passed every inner consistency gate" if fallback else None
            )
            # No outer labels or metrics have been passed to policy selection.
            prepared = cached(outer)
            if selected not in prepared["predictions"]:
                selected, fallback = "raw", True
                fallback_reason = "Inner-selected policy lacks effective support at outer fit time"
            names = list(
                dict.fromkeys(
                    ["raw", "sigmoid", "recent_prevalence", "training_prevalence", selected]
                )
            )
            metrics = evaluate_predictions(prepared, outer.evaluation, names)
            exported = {
                name: metrics[name]
                for name in ("raw", "sigmoid", "recent_prevalence", "training_prevalence")
            }
            exported["nested_selected"] = metrics[selected]
            prediction = prepared["predictions"][selected]
            result = {
                **outer.metadata,
                "selected_policy": selected,
                "inner_selected_policy": inner_selected,
                "raw_fallback": fallback,
                "fallback_reason": fallback_reason,
                "selection_cutoff": outer.metadata["calibrator_fit_at"],
                "selected_fit_audit": prediction.get("fit_audit"),
                "inner_folds": inner_results,
                "inner_summary": selection,
                "excluded_inner_windows": skipped,
                "unused_older_supported_inner_folds": older,
                "policies": exported,
                "membership_sha256": membership_hash(outer.evaluation),
                "unsupported_outer_policies": prepared["unsupported_policies"],
                "censoring": censoring_diagnostics(
                    outer.evaluation_cohort,
                    outer.metadata["outcome_observation_cutoff"],
                    prediction["scores"],
                    prediction["threshold"],
                    maturity_days=(0, config.maturity_days, 30),
                ),
            }
            completed.append(result)
            logger.info(
                "Outer %s selected %s%s; Brier %.5f",
                outer.fold_id,
                selected,
                " (fallback)" if fallback else "",
                metrics[selected]["brier_score"],
            )
        except (ValueError, RuntimeError) as exc:
            logger.exception("Nested outer %s failed", outer.fold_id)
            failures.append({"fold_id": outer.fold_id, "reason": f"{type(exc).__name__}: {exc}"})
    summary = summarize_policies(
        completed, len(failures), candidate_names=("raw", "sigmoid", "nested_selected")
    )
    summary["selection_frequency"] = dict(Counter(row["selected_policy"] for row in completed))
    summary["raw_fallback_count"] = sum(row["raw_fallback"] for row in completed)
    summary["inner_selection_frequency"] = dict(
        Counter(row["inner_selected_policy"] for row in completed)
    )
    return {
        "folds": completed,
        "excluded_outer_windows": excluded,
        "failed_folds": failures,
        "summary": summary,
        "base_model_fits": len(cache),
        "prediction_cache_hits": cache_hits,
    }


def adaptive_markdown(report: dict) -> str:
    lines = [
        "# Nested recency-adaptive calibration",
        "",
        f"Status: {report['status']}; valid outer folds: {len(report['folds'])}; no promotion.",
        f"Selection frequency: {report['summary']['selection_frequency']}; raw fallbacks: {report['summary']['raw_fallback_count']}.",
        "",
        "| Evaluation start | Inner folds | Selected policy | Fallback | N | Raw Brier | Fixed sigmoid Brier | Nested Brier | Nested AP | P@10% |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["folds"]:
        p = row["policies"]
        n = p["nested_selected"]
        lines.append(
            f"| {row['evaluation_start'][:10]} | {len(row['inner_folds'])} | {row['selected_policy']} | {row['raw_fallback']} | {n['samples']} | {p['raw']['brier_score']:.5f} | {p['sigmoid']['brier_score']:.5f} | {n['brier_score']:.5f} | {n['pr_auc_average_precision']:.4f} | {n['precision_at_top_10_percent']:.4f} |"
        )
    lines += [
        "",
        "## Across outer windows",
        "",
        "| Policy | Mean Brier | Worst Brier | Mean AP | Worst skill vs recent prevalence |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, row in report["summary"]["policies"].items():
        m = row["metrics"]
        lines.append(
            f"| {name} | {m['brier_score']['mean']:.5f} | {m['brier_score']['worst']:.5f} | {m['pr_auc_average_precision']['mean']:.4f} | {m['brier_skill_vs_recent_prevalence']['worst']:.4f} |"
        )
    lines += [
        "",
        f"Consistency-gate recommendation: {report['summary']['recommended_policy'] or 'none'}; research only.",
        "",
        "## Exclusions and failures",
        "",
    ]
    for row in (
        report["excluded_schedule_windows"]
        + report["excluded_outer_windows"]
        + report["failed_folds"]
    ):
        lines.append(f"- {row.get('fold_id', 'schedule')}: {row['reason']}")
    return "\n".join(lines) + "\n"


def compact_adaptive_report(report: dict) -> dict:
    """Keep all outer results and inner gate evidence without repeated bin tables."""
    compact = copy.deepcopy(report)
    compact["summary_format_version"] = 1
    compact["inner_metric_scope"] = (
        "Selection diagnostics only; complete inner reliability/budget metrics remain in full report"
    )
    for fold in compact["folds"]:
        for inner in fold["inner_folds"]:
            inner["policies"] = {
                name: {
                    key: metrics[key]
                    for key in (
                        "samples",
                        "brier_score",
                        "brier_skill_vs_recent_prevalence",
                        "pr_auc_average_precision",
                        "precision_at_top_10_percent",
                        "ap_delta_vs_raw",
                        "top10_precision_delta_vs_raw",
                        "threshold",
                    )
                }
                for name, metrics in inner["policies"].items()
            }
        for policy in fold["inner_summary"]["policies"].values():
            policy["metrics"] = {
                key: value
                for key, value in policy["metrics"].items()
                if key
                in (
                    "brier_score",
                    "brier_skill_vs_recent_prevalence",
                    "ap_delta_vs_raw",
                    "top10_precision_delta_vs_raw",
                )
            }
    return compact


def run_adaptive_evaluation(
    database_path: Path,
    artifact_dir: Path,
    output: Path,
    config: RollingConfig,
    *,
    half_lives=(30, 60, 90, 180),
    windows=(30, 60),
    min_inner_folds=3,
    max_inner_folds=3,
    quick=False,
):
    summary_path = output.with_suffix(".summary.json")
    if output.suffix != ".json" or any(
        path.exists() for path in (output, output.with_suffix(".md"), summary_path)
    ):
        raise ValueError("Use a new .json report path; existing results are preserved")
    policies = calibration_policies(half_lives, windows)
    if min_inner_folds < 3 or max_inner_folds < min_inner_folds:
        raise ValueError("Require at least three inner folds and max >= min")
    pointer = artifact_dir / "delivery/current.json"
    before = pointer.read_bytes()
    active = RiskService(artifact_dir, database_path).load()
    start = perf_counter()
    frame, _, _, _ = build_dataset_v2(
        database_path,
        lag_days=active["history_lag_days"],
        window_days=active["history_window_days"],
        purchase_before=active["split"]["test_start"],
    )
    frame["prediction_at"] = frame.purchased_at
    folds, schedule_excluded = rolling_folds(
        frame,
        config,
        protected_start=active["split"]["test_start"],
        as_of=active["split"]["observation_cutoff"],
    )
    with threadpool_limits(limits=2):
        results = nested_evaluate(
            folds,
            config,
            policies,
            min_inner_folds=min_inner_folds,
            max_inner_folds=max_inner_folds,
            quick=quick,
        )
    if pointer.read_bytes() != before:
        raise ValueError("Serving pointer changed externally during evaluation")
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "config": asdict(config),
        "half_lives": list(half_lives),
        "observation_windows": list(windows),
        "min_inner_folds": min_inner_folds,
        "max_inner_folds": max_inner_folds,
        "candidate_policies": [asdict(policy) for policy in policies],
        "seed": SEED,
        "quick": quick,
        "protected_start": active["split"]["test_start"],
        "pre_protected_purchase_rows": len(frame),
        "active_model_version": active["model_version"],
        "active_model_unchanged": True,
        "dataset": active["dataset"],
        "versions": {name: importlib.metadata.version(name) for name in active["versions"]},
        "excluded_schedule_windows": schedule_excluded,
        **results,
        "status": "no_valid_folds"
        if not results["folds"]
        else "complete_with_failures"
        if results["failed_folds"]
        else "complete",
        "duration_seconds": perf_counter() - start,
        "limitations": [
            "Historical previously inspected data, not independent current-production validation",
            "No early late-label ascertainment; delivered-only target and residual censoring remain",
            "Snapshot status is retrospective; no historical cancellation event log",
            "Overlapping training/inner histories create dependence; no IID inference",
            "No promotion permitted; earlier validation gates remain required",
        ],
    }
    write_json(output, report)
    output.with_suffix(".md").write_text(adaptive_markdown(report))
    compact = compact_adaptive_report(report)
    compact["full_report_sha256"] = sha256_file(output)
    compact["full_report_filename"] = output.name
    write_json(summary_path, compact)
    return report
