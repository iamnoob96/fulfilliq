import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import pairwise_distances

from fulfilliq.features.orders import build_dataset
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.mining.anomalies import detect_anomalies, wilson_interval
from fulfilliq.mining.patterns import mine_patterns, transactions
from fulfilliq.mining.segments import kmedoids, segment_sellers, seller_features


def mining_frame(n=100):
    late = np.arange(n) % 3 == 0
    return pd.DataFrame(
        {
            "target_is_late": late,
            "customer_state": np.where(late, "RJ", "SP"),
            "primary_seller_state": "SP",
            "primary_category": "books",
            "distance_km": np.where(late, 2000.0, 100.0),
            "items_value": 80.0,
            "freight_value": 15.0,
            "total_weight_g": 500.0,
            "total_volume_cm3": 100.0,
            "seller_history_late_rate": 0.1,
            "item_count": 1.0,
            "promised_lead_days": 10.0,
        },
        index=[f"a{i}" for i in range(n)],
    )


def seller_frame(n=20):
    rng = np.random.default_rng(42)
    group = np.arange(n) % 2
    return pd.DataFrame(
        {
            "order_volume": rng.integers(30, 100, n),
            "eligible_outcomes": 30,
            "late_orders": 2 + group * 18,
            "late_rate": 0.05 + group * 0.5,
            "median_fulfillment_days": rng.uniform(1, 2, n) + group * 7,
            "mean_freight": 10 + group * 20 + rng.random(n),
            "mean_distance_km": 100 + group * 1000 + rng.random(n),
            "mean_order_value": rng.uniform(50, 100, n) + group * 300,
            "category_diversity": rng.integers(1, 5, n),
            "seller_state": "SP",
        },
        index=pd.Index([f"s{i}" for i in range(n)], name="seller_id"),
    )


def test_both_frequent_pattern_algorithms_agree():
    report = mine_patterns(mining_frame(), min_support=0.1, min_confidence=0.5)
    assert report["algorithms_agree"]
    assert len(report["rules"]) > 0
    assert all(row["consequents"] == ["outcome=late"] for row in report["rules"])
    rule = next(r for r in report["rules"] if r["antecedents"] == ["customer_state=RJ"])
    assert rule["confidence"] == 1
    assert rule["support_count"] == 34
    assert rule["lift"] == pytest.approx(1 / 0.34)
    assert len(transactions(mining_frame())) == 100
    with pytest.raises(ValueError):
        mine_patterns(mining_frame(), min_support=0)


def test_medoids_and_stable_interpretable_segments():
    x = np.array([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [10.0, 10.0], [11.0, 10.0], [10.0, 11.0]])
    labels, medoids, _ = kmedoids(pairwise_distances(x, metric="manhattan"), 2)
    assert len(set(labels[:3])) == len(set(labels[3:])) == 1
    assert labels[0] != labels[-1]
    assert len(set(medoids)) == 2
    report = segment_sellers(seller_frame())
    assert len(report["assignments"]) == 20
    assert report["selected_k"] >= 2
    assert report["silhouette"] > 0
    assert len(report["stability_80_percent_resample_ari"]) == 3
    assert all("median" in row["name"] for row in report["segments"])


def test_anomaly_scores_are_reproducible_and_explainable():
    frame = mining_frame()
    frame.loc["a99", ["items_value", "total_weight_g", "item_count"]] = [1e8, 1e7, 500]
    first = detect_anomalies(frame, seller_frame(), contamination=0.05)
    second = detect_anomalies(frame, seller_frame(), contamination=0.05)
    assert first == second
    assert any(row["entity_id"] == "a99" and row["kind"] == "order" for row in first["anomalies"])
    assert any(row["kind"] == "seller" for row in first["anomalies"])
    assert all(row["reasons"] for row in first["anomalies"])
    assert wilson_interval(0, 0) == (0, 1)
    assert wilson_interval(20, 20)[0] > 0.8


def test_seller_features_deduplicate_multi_item_memberships(raw_dir, tmp_path):
    db = tmp_path / "db.sqlite3"
    ingest(raw_dir, db, tmp_path)
    _, _, orders, items = build_dataset(db)
    features = seller_features(orders, items)
    assert features.loc["s1", "order_volume"] == 3
    assert features.loc["s2", "order_volume"] == 1
    assert features.loc["s1", "eligible_outcomes"] == 2
    with pytest.raises(ValueError, match="six sellers"):
        segment_sellers(features, min_orders=1)
