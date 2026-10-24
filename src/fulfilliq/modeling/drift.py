"""Descriptive input/probability drift; these summaries do not establish causes."""

import numpy as np
import pandas as pd

from fulfilliq.features.risk_v2 import V2_CATEGORICAL, V2_FEATURES, V2_NUMERIC
from fulfilliq.modeling.evaluation import evaluate


def probability_metrics(labels, probabilities, threshold: float) -> dict:
    result = evaluate(labels, probabilities, threshold)
    labels, probabilities = np.asarray(labels, dtype=int), np.asarray(probabilities, dtype=float)
    bins = np.minimum((probabilities * 10).astype(int), 9)
    reliability = []
    for index in range(10):
        selected = bins == index
        if selected.any():
            reliability.append(
                {
                    "lower": index / 10,
                    "upper": (index + 1) / 10,
                    "count": int(selected.sum()),
                    "predicted": float(probabilities[selected].mean()),
                    "observed": float(labels[selected].mean()),
                }
            )
    result["ece_10_equal_width"] = sum(
        row["count"] * abs(row["predicted"] - row["observed"]) for row in reliability
    ) / len(labels)
    result["reliability_equal_width"] = reliability
    result["probability_quantiles"] = {
        str(q): float(np.quantile(probabilities, q)) for q in (0.01, 0.05, 0.5, 0.95, 0.99)
    }
    return result


def numeric_summary(values) -> dict:
    values = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    known = values.dropna()
    return {
        "missing_fraction": float(values.isna().mean()),
        "mean": float(known.mean()) if len(known) else None,
        "p10": float(known.quantile(0.1)) if len(known) else None,
        "median": float(known.median()) if len(known) else None,
        "p90": float(known.quantile(0.9)) if len(known) else None,
    }


def numeric_psi(reference, observed) -> float | None:
    reference, observed = np.asarray(reference, dtype=float), np.asarray(observed, dtype=float)
    known = reference[np.isfinite(reference)]
    if not len(known):
        return None
    edges = np.unique(np.quantile(known, np.linspace(0, 1, 11)))
    edges = np.unique(
        np.r_[
            -np.inf,
            np.nextafter(edges[0], -np.inf),
            edges[1:-1],
            np.nextafter(edges[-1], np.inf),
            np.inf,
        ]
    )

    def proportions(values):
        finite = np.isfinite(values)
        counts = np.r_[np.histogram(values[finite], bins=edges)[0], (~finite).sum()]
        values = np.maximum(counts / len(values), 1e-6)
        return values / values.sum()

    expected, actual = proportions(reference), proportions(observed)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def feature_drift(train: pd.DataFrame, evaluation: pd.DataFrame, items: pd.DataFrame) -> dict:
    numeric = {
        name: {
            "training": numeric_summary(train[name]),
            "evaluation": numeric_summary(evaluation[name]),
            "psi": numeric_psi(train[name], evaluation[name]),
        }
        for name in V2_NUMERIC
    }
    categorical = {}
    for name in V2_CATEGORICAL:
        reference = train[name].fillna("unknown").value_counts(normalize=True)
        observed = evaluation[name].fillna("unknown").value_counts(normalize=True)
        combined = reference.index.union(observed.index)
        categorical[name] = {
            "total_variation": float(
                0.5
                * (
                    reference.reindex(combined, fill_value=0)
                    - observed.reindex(combined, fill_value=0)
                )
                .abs()
                .sum()
            ),
            "unseen_fraction": float(observed.loc[~observed.index.isin(reference.index)].sum()),
            "training_top5": {str(k): float(v) for k, v in reference.head(5).items()},
            "evaluation_top5": {str(k): float(v) for k, v in observed.head(5).items()},
        }
    train_items = items.loc[items.order_id.isin(train.index)]
    evaluation_items = items.loc[items.order_id.isin(evaluation.index)]
    known_sellers, active_sellers = set(train_items.seller_id), set(evaluation_items.seller_id)
    new = active_sellers - known_sellers
    new_orders = evaluation_items.loc[evaluation_items.seller_id.isin(new)].order_id.nunique()
    return {
        "purchase_cohorts": {"training": len(train), "evaluation": len(evaluation)},
        "numeric": numeric,
        "categorical": categorical,
        "feature_missingness": {
            name: {
                "training": float(train[name].isna().mean()),
                "evaluation": float(evaluation[name].isna().mean()),
            }
            for name in V2_FEATURES
        },
        "seller_activity": {
            "training_active": len(known_sellers),
            "evaluation_active": len(active_sellers),
            "new_sellers": len(new),
            "new_seller_fraction": len(new) / max(1, len(active_sellers)),
            "orders_with_new_seller_fraction": new_orders / len(evaluation),
            "no_observed_seller_history_fraction": float(
                evaluation.seller_history_count.eq(0).mean()
            ),
        },
    }


def summarize_policies(
    folds: list[dict], failed_folds: int = 0, *, candidate_names=("raw", "sigmoid", "isotonic")
) -> dict:
    policies = sorted({name for fold in folds for name in fold["policies"]})
    summaries = {}
    for name in policies:
        rows = [fold["policies"][name] for fold in folds if name in fold["policies"]]
        metrics = [
            "roc_auc",
            "pr_auc_average_precision",
            "f1",
            "brier_score",
            "ece_10_equal_width",
            "brier_skill_vs_recent_prevalence",
            "brier_skill_vs_training_prevalence",
            "ap_delta_vs_raw",
            "top10_precision_delta_vs_raw",
        ]
        values = {key: [row[key] for row in rows] for key in metrics}
        for budget in ("5", "10", "20"):
            for metric in ("precision", "recall"):
                values[f"top_{budget}_{metric}"] = [
                    row["review_budgets"][budget][metric] for row in rows
                ]
        summaries[name] = {
            "folds": len(rows),
            "metrics": {
                key: {
                    "mean": float(np.mean(items)),
                    "std": float(np.std(items)),
                    "min": float(np.min(items)),
                    "max": float(np.max(items)),
                    "worst": float(
                        np.max(items)
                        if key in {"brier_score", "ece_10_equal_width"}
                        else np.min(items)
                    ),
                }
                for key, items in values.items()
            },
        }
    eligible = []
    for name in candidate_names:
        if name not in summaries:
            continue
        row = summaries[name]
        metrics = row["metrics"]
        row["ranking_safe_full_coverage"] = (
            row["folds"] == len(folds)
            and len(folds) >= 3
            and not failed_folds
            and metrics["ap_delta_vs_raw"]["min"] >= -0.01
            and metrics["top10_precision_delta_vs_raw"]["min"] >= -0.01
        )
        row["qualifies_for_advisory_recommendation"] = (
            row["ranking_safe_full_coverage"]
            and metrics["brier_skill_vs_recent_prevalence"]["min"] >= 0
        )
        if row["ranking_safe_full_coverage"]:
            eligible.append(name)

    def key(name):
        value = summaries[name]["metrics"]["brier_skill_vs_recent_prevalence"]
        return value["min"], value["mean"], -value["std"]

    qualified = [
        name for name in eligible if summaries[name]["qualifies_for_advisory_recommendation"]
    ]
    common = [
        fold
        for fold in folds
        if all(name in fold["policies"] for name in ("raw", "sigmoid", "isotonic"))
    ]
    matched = {
        "folds": len(common),
        "fold_ids": [fold.get("fold_id") for fold in common],
        "interpretation": "Same supported windows for each method; descriptive only. Primary recommendation still requires all valid folds.",
        "policies": {
            name: {
                key: float(np.mean([fold["policies"][name][key] for fold in common]))
                for key in (
                    "brier_score",
                    "ece_10_equal_width",
                    "roc_auc",
                    "pr_auc_average_precision",
                    "precision_at_top_10_percent",
                )
            }
            for name in ("raw", "sigmoid", "isotonic")
            if common
        },
    }
    return {
        "policies": summaries,
        "recommended_policy": max(qualified, key=key) if qualified else None,
        "least_worst_ranking_safe_policy": max(eligible, key=key) if eligible else None,
        "matched_isotonic_comparison": matched,
        "promotion": "Not permitted by this evaluation command; existing validation gates remain required",
    }
