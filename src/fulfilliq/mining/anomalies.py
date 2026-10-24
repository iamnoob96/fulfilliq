"""Retrospective screening: an anomaly is neither an incident nor a fraud finding."""

import math

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import RobustScaler
from threadpoolctl import threadpool_limits

ANOMALY_FEATURES = [
    "item_count",
    "items_value",
    "freight_value",
    "total_weight_g",
    "total_volume_cm3",
    "distance_km",
    "promised_lead_days",
]


def wilson_interval(positives: int, count: int, z: float = 1.96) -> tuple[float, float]:
    if not count:
        return 0.0, 1.0
    rate, denominator = positives / count, 1 + z * z / count
    middle = (rate + z * z / (2 * count)) / denominator
    spread = z * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count)) / denominator
    return middle - spread, middle + spread


def detect_anomalies(
    frame: pd.DataFrame, sellers: pd.DataFrame, *, contamination: float = 0.02, min_orders: int = 20
) -> dict:
    if not 0 < contamination <= 0.2 or min_orders < 1:
        raise ValueError("contamination must be in (0, .2] and min_orders must be positive")
    if len(frame) < 10:
        raise ValueError("Order anomaly screening requires at least ten orders")
    values = frame[ANOMALY_FEATURES].copy()
    for name in ANOMALY_FEATURES:
        values[name] = np.log1p(values[name].clip(lower=0))
    prepared = RobustScaler().fit_transform(
        SimpleImputer(strategy="median", keep_empty_features=True).fit_transform(values)
    )
    with threadpool_limits(limits=2):
        estimator = IsolationForest(
            n_estimators=120, contamination=contamination, random_state=42, n_jobs=2
        )
        estimator.fit(prepared)
        scores = -estimator.score_samples(prepared)
    threshold = float(np.quantile(scores, 1 - contamination))
    center = np.median(prepared, axis=0)
    mad = np.maximum(np.median(np.abs(prepared - center), axis=0) * 1.4826, 0.1)
    results = []
    for position in np.flatnonzero(scores >= threshold):
        deviation = np.abs((prepared[position] - center) / mad)
        extreme = np.argsort(-deviation)[:3]
        observed = frame.iloc[position]
        results.append(
            {
                "kind": "order",
                "entity_id": str(frame.index[position]),
                "score": float(scores[position]),
                "threshold": threshold,
                "region": str(observed.customer_state),
                "reasons": [
                    f"{ANOMALY_FEATURES[i]} differs from the historical robust center "
                    f"by {deviation[i]:.1f} scaled units"
                    for i in extreme
                ],
                "observed_features": {name: observed[name] for name in ANOMALY_FEATURES},
            }
        )
    eligible = frame.loc[frame.target_is_late.notna()]
    total, late = len(eligible), int(eligible.target_is_late.sum())
    _, baseline_upper = wilson_interval(late, total)
    for kind, groups in (
        (
            "seller",
            [
                (str(seller), row.eligible_outcomes, row.late_orders, row.late_rate)
                for seller, row in sellers.iterrows()
            ],
        ),
        (
            "region",
            [
                (
                    str(region),
                    len(group),
                    int(group.target_is_late.sum()),
                    float(group.target_is_late.mean()),
                )
                for region, group in eligible.groupby("customer_state")
            ],
        ),
    ):
        for identifier, count, positives, rate in groups:
            if count < min_orders:
                continue
            lower, upper = wilson_interval(int(positives), int(count))
            if lower > baseline_upper:
                results.append(
                    {
                        "kind": kind,
                        "entity_id": identifier,
                        "score": float(lower),
                        "threshold": float(baseline_upper),
                        "eligible_outcomes": int(count),
                        "late_orders": int(positives),
                        "late_rate": float(rate),
                        "wilson_interval": [lower, upper],
                        "reasons": [
                            "95% Wilson lower bound exceeds the global late-rate upper bound; "
                            "historical screening only, without case-mix adjustment."
                        ],
                    }
                )
    coherent = sellers.loc[sellers.order_volume.ge(min_orders), "median_fulfillment_days"].dropna()
    if len(coherent):
        median = float(coherent.median())
        mad_duration = float((coherent - median).abs().median())
        limit = median + 3 * max(1.4826 * mad_duration, 0.25)
        for identifier, duration in coherent.loc[coherent.gt(limit)].items():
            results.append(
                {
                    "kind": "seller_fulfillment",
                    "entity_id": str(identifier),
                    "score": float(duration),
                    "threshold": limit,
                    "reasons": [
                        "Median approval-to-carrier duration exceeds median + 3 robust deviations; "
                        "order milestones may span multiple sellers."
                    ],
                }
            )
    results.sort(key=lambda row: (row["kind"], -row["score"], row["entity_id"]))
    return {
        "method": "Isolation Forest order characteristics; Wilson delay screens; robust duration thresholds",
        "contamination": contamination,
        "min_orders": min_orders,
        "order_threshold": threshold,
        "reference_order_count": len(frame),
        "global_late_rate": late / total if total else None,
        "counts": pd.Series([row["kind"] for row in results]).value_counts().to_dict(),
        "anomalies": results,
        "interpretation": "Full-history retrospective screening, not real-time incident/fraud detection. "
        "Order scores use a global reference distribution, not matched causal cohorts. "
        "Sellers/regions differ in volume and case mix; investigate before acting.",
    }
