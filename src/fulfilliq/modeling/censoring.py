"""Retrospective coverage and assumption bounds; never invent undelivered labels."""

import numpy as np
import pandas as pd

from fulfilliq.modeling.drift import probability_metrics
from fulfilliq.modeling.rolling import coherent_labels, eligible_at


def censoring_diagnostics(
    cohort: pd.DataFrame,
    cutoff,
    probabilities: pd.Series,
    threshold: float,
    maturity_days=(0, 14, 30),
) -> dict:
    cutoff = pd.Timestamp(cutoff)
    if (
        not probabilities.index.equals(cohort.index)
        or not np.isfinite(probabilities).all()
        or not probabilities.between(0, 1).all()
    ):
        raise ValueError("Sensitivity requires aligned finite probabilities in [0, 1]")
    observable = coherent_labels(cohort) & cohort.label_available_at.lt(cutoff)
    delivered = cohort.order_status.eq("delivered") & cohort.estimated_at.ge(cohort.purchased_at)
    known = delivered & observable
    unknown = delivered & ~observable
    population = int(delivered.sum())
    positives = int(cohort.loc[known, "target_is_late"].astype(int).sum())
    known_loss = float(
        np.square(probabilities.loc[known] - cohort.loc[known, "target_is_late"].astype(int)).sum()
    )
    unknown_scores = probabilities.loc[unknown].to_numpy()
    loss_zero, loss_one = unknown_scores**2, (1 - unknown_scores) ** 2
    sensitivity = {}
    for days in sorted(set(maturity_days)):
        eligible = eligible_at(cohort, cutoff, days)
        row = {
            "eligible": len(eligible),
            "coverage": len(eligible) / max(1, len(cohort)),
            "late_rate": float(eligible.target_is_late.astype(int).mean())
            if len(eligible)
            else None,
        }
        if len(eligible) and eligible.target_is_late.nunique() == 2:
            row["metrics"] = probability_metrics(
                eligible.target_is_late.astype(int), probabilities.loc[eligible.index], threshold
            )
        else:
            row["unsupported_reason"] = "Both classes required for ranking metrics"
        sensitivity[str(days)] = row
    return {
        "purchase_cohort": len(cohort),
        "snapshot_status_counts": {
            str(k): int(v) for k, v in cohort.order_status.value_counts(dropna=False).items()
        },
        "snapshot_status_interpretation": "Final snapshot categories, not reconstructed historical status events",
        "missing_delivery_timestamps": int(cohort.delivered_at.isna().sum()),
        "outcome_observable": int(observable.sum()),
        "deadline_passed_without_observed_outcome": int(
            (cohort.estimated_at.lt(cutoff) & ~observable).sum()
        ),
        "maturity_sensitivity": sensitivity,
        "eventually_delivered_bounds": {
            "population": population,
            "known_outcomes": int(known.sum()),
            "unobserved_outcomes": int(unknown.sum()),
            "late_prevalence_lower": positives / population if population else None,
            "late_prevalence_upper": (positives + int(unknown.sum())) / population
            if population
            else None,
            "brier_lower": (known_loss + np.minimum(loss_zero, loss_one).sum()) / population
            if population
            else None,
            "brier_upper": (known_loss + np.maximum(loss_zero, loss_one).sum()) / population
            if population
            else None,
            "interpretation": "Hypothetical bounds for eventual delivered snapshot cohort only; canceled/undelivered targets are undefined and excluded",
        },
    }
