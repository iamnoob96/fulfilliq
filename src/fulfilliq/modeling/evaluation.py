import math

import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)


def choose_threshold(labels, probabilities) -> float:
    """Maximize validation F1; prefer a higher threshold in ties (less operational load)."""
    precision, recall, thresholds = precision_recall_curve(labels, probabilities)
    f1 = np.divide(
        2 * precision * recall,
        precision + recall,
        out=np.zeros_like(precision),
        where=(precision + recall) != 0,
    )[:-1]
    return float(thresholds[np.flatnonzero(f1 == f1.max())[-1]])


def evaluate(labels, probabilities, threshold: float) -> dict:
    labels = np.asarray(labels, dtype=int)
    probabilities = np.asarray(probabilities, dtype=float)
    if (
        labels.ndim != 1 or probabilities.shape != labels.shape or not len(labels)
        or not np.isin(labels, [0, 1]).all()
        or not np.isfinite(probabilities).all()
        or ((probabilities < 0) | (probabilities > 1)).any()
        or not np.isfinite(threshold) or not 0 <= threshold <= 1
    ):
        raise ValueError("Evaluation requires binary labels and finite probabilities in [0, 1]")
    predicted = probabilities >= threshold
    ranking = np.argsort(-probabilities, kind="stable")
    budgets = {}
    for percent in (5, 10, 20):
        top = ranking[: max(1, math.ceil(len(labels) * percent / 100))]
        budgets[str(percent)] = {
            "reviewed_orders": len(top),
            "late_orders_captured": int(labels[top].sum()),
            "precision": float(labels[top].mean()),
            "recall": float(labels[top].sum() / max(1, labels.sum())),
        }
    top = ranking[:budgets["10"]["reviewed_orders"]]
    observed, predicted_bins = calibration_curve(
        labels, probabilities, n_bins=10, strategy="quantile"
    )
    return {
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "pr_auc_average_precision": float(average_precision_score(labels, probabilities)),
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "mean_probability": float(probabilities.mean()),
        "review_budgets": budgets,
        "precision_at_top_10_percent": float(labels[top].mean()),
        "top_10_percent_count": len(top),
        "confusion_matrix": confusion_matrix(labels, predicted, labels=[0, 1]).tolist(),
        "confusion_matrix_order": [
            ["true_negative", "false_positive"],
            ["false_negative", "true_positive"],
        ],
        "threshold": threshold,
        "samples": len(labels),
        "late_rate": float(labels.mean()),
        "flagged_fraction": float(predicted.mean()),
        "calibration": [
            {"predicted": float(p), "observed": float(o)}
            for p, o in zip(predicted_bins, observed, strict=True)
        ],
    }
