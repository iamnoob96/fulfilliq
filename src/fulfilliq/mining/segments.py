"""Small-data alternate-update K-Medoids with KMeans comparison and resample stability."""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import adjusted_rand_score, pairwise_distances, silhouette_score
from sklearn.preprocessing import RobustScaler
from threadpoolctl import threadpool_limits

from fulfilliq.features.orders import outcome_mask

SEGMENT_FEATURES = [
    "order_volume",
    "median_fulfillment_days",
    "late_rate",
    "mean_freight",
    "mean_distance_km",
    "mean_order_value",
    "category_diversity",
]


def seller_features(orders: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    events = orders.copy()
    eligible = outcome_mask(events)
    events["late"] = (events.delivered_at > events.estimated_at).astype(float).where(eligible)
    duration = (events.carrier_at - events.approved_at).dt.total_seconds() / 86400
    events["fulfillment"] = duration.where(
        duration.ge(0) & events.approved_at.ge(events.purchased_at)
    )
    pairs = items[["order_id", "seller_id"]].drop_duplicates().merge(events, on="order_id")
    performance = pairs.groupby("seller_id").agg(
        order_volume=("order_id", "size"),
        eligible_outcomes=("late", "count"),
        late_orders=("late", "sum"),
        late_rate=("late", "mean"),
        median_fulfillment_days=("fulfillment", "median"),
    )
    attributes = items.groupby("seller_id").agg(
        mean_freight=("freight_value", "mean"),
        mean_distance_km=("distance_km", "mean"),
        category_diversity=("category", "nunique"),
        seller_state=("seller_state", "first"),
    )
    seller_orders = (
        items.assign(value=items.price + items.freight_value)
        .groupby(["seller_id", "order_id"])
        .value.agg(lambda values: values.sum(min_count=len(values)))
    )
    attributes["mean_order_value"] = seller_orders.groupby("seller_id").mean()
    return performance.join(attributes).sort_index()


def kmedoids(distances: np.ndarray, k: int, *, seed: int = 42, max_iter: int = 30):
    n = len(distances)
    if not 1 < k < n:
        raise ValueError("K-Medoids requires 1 < k < number of sellers")
    rng = np.random.default_rng(seed)
    medoids = [int(rng.integers(n))]
    while len(medoids) < k:
        nearest = distances[:, medoids].min(axis=1)
        nearest[medoids] = -1
        remaining = np.setdiff1d(np.arange(n), medoids)
        medoids.append(int(remaining[np.argmax(nearest[remaining])]))
    for iteration in range(max_iter):
        labels = np.argmin(distances[:, medoids], axis=1)
        updated = medoids.copy()
        for cluster in range(k):
            members = np.flatnonzero(labels == cluster)
            if len(members):
                updated[cluster] = int(
                    members[np.argmin(distances[np.ix_(members, members)].sum(axis=1))]
                )
        if updated == medoids:
            break
        medoids = updated
    return np.argmin(distances[:, medoids], axis=1), np.asarray(medoids), iteration + 1


def segment_sellers(features: pd.DataFrame, *, min_orders: int = 10) -> dict:
    if min_orders < 1:
        raise ValueError("min_orders must be positive")
    selected = features.loc[features.order_volume.ge(min_orders)].copy()
    if len(selected) < 6:
        raise ValueError("Seller segmentation needs at least six sellers above min_orders")
    # Olist has about 3,000 sellers; an n*n matrix is practical here, not for large marketplaces.
    if len(selected) > 5000:
        raise ValueError("K-Medoids is limited to 5000 sellers; use a sampled CLARA implementation")
    values = selected[SEGMENT_FEATURES].copy()
    for column in (
        "order_volume",
        "mean_freight",
        "mean_distance_km",
        "mean_order_value",
        "category_diversity",
    ):
        values[column] = np.log1p(values[column])
    x = RobustScaler().fit_transform(
        SimpleImputer(strategy="median", keep_empty_features=True).fit_transform(values)
    )
    candidates = []
    distinct = len(np.unique(x, axis=0))
    if distinct < 2:
        raise ValueError("Seller segmentation needs at least two distinct feature profiles")
    with threadpool_limits(limits=2):
        distances = pairwise_distances(x, metric="manhattan")
        for k in range(2, min(5, distinct, len(selected) - 1) + 1):
            labels, medoids, iterations = kmedoids(distances, k)
            score = silhouette_score(
                x, labels, metric="manhattan", sample_size=min(1000, len(x)), random_state=42
            )
            candidates.append((float(score), k, labels, medoids, iterations))
        score, k, labels, medoids, iterations = max(candidates, key=lambda row: row[0])
        baseline_labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(x)
        baseline_silhouette = silhouette_score(
            x, baseline_labels, sample_size=min(1000, len(x)), random_state=42
        )
        stability = []
        for seed in (11, 22, 33):
            indices = np.sort(
                np.random.default_rng(seed).choice(
                    len(x), max(k + 1, int(0.8 * len(x))), replace=False
                )
            )
            _, sub_medoids, _ = kmedoids(distances[np.ix_(indices, indices)], k, seed=seed)
            perturbed = np.argmin(distances[:, indices[sub_medoids]], axis=1)
            stability.append(float(adjusted_rand_score(labels, perturbed)))
    summaries, names = [], {}
    for cluster in range(k):
        group = selected.iloc[np.flatnonzero(labels == cluster)]
        medians = group[SEGMENT_FEATURES].median().to_dict()
        rate = medians["late_rate"]
        name = f"Segment {cluster}: median late rate {rate:.1%}, median volume {medians['order_volume']:.0f}"
        names[cluster] = name
        summaries.append(
            {
                "segment_id": cluster,
                "name": name,
                "sellers": len(group),
                "medoid_seller_id": str(selected.index[medoids[cluster]]),
                "medians": medians,
            }
        )
    assignments = [
        {
            "seller_id": str(seller),
            "segment_id": int(label),
            "segment_name": names[int(label)],
            "features": selected.loc[seller].to_dict(),
        }
        for seller, label in zip(selected.index, labels, strict=True)
    ]
    return {
        "method": "alternate-update K-Medoids, Manhattan distance, log transforms and robust scaling",
        "features": SEGMENT_FEATURES,
        "min_orders": min_orders,
        "selected_k": k,
        "silhouette": float(score),
        "kmeans_euclidean_silhouette": float(baseline_silhouette),
        "candidates": [{"k": row[1], "silhouette": row[0]} for row in candidates],
        "stability_80_percent_resample_ari": stability,
        "mean_stability_ari": float(np.mean(stability)),
        "iterations": iterations,
        "excluded_low_volume_sellers": len(features) - len(selected),
        "segments": summaries,
        "assignments": assignments,
        "interpretation": "Descriptive historical segments. Fulfillment and late outcomes belong "
        "to orders involving a seller, not separately observed seller shipments.",
    }
