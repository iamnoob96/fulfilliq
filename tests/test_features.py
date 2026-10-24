import numpy as np
import pandas as pd
import pytest

from fulfilliq.features.orders import (
    FEATURES,
    OutcomeHistory,
    build_dataset,
    haversine_km,
    load_orders,
    placement_features,
)
from fulfilliq.ingestion.pipeline import ingest


def test_allowlisted_placement_features_and_multi_seller(raw_dir, tmp_path):
    db = tmp_path / "db.sqlite3"
    ingest(raw_dir, db, tmp_path)
    frame, history, orders, items = build_dataset(db, lag_days=0)
    assert frame.index.is_unique
    assert frame.loc["o1", "seller_count"] == 2
    assert frame.loc["o1", "items_value"] == 150
    assert frame.loc["o1", "freight_value"] == 15
    assert frame.loc["o1", "target_is_late"]
    assert frame.loc[
        "o2", "target_is_late"
    ]  # New exact timestamp target, not legacy calendar flag.
    assert not set(FEATURES) & {
        "delivered_at",
        "carrier_at",
        "approved_at",
        "order_status",
        "target_is_late",
        "average_review_score",
    }
    modified = orders.copy()
    modified["delivered_at"] += pd.Timedelta(days=100)
    pd.testing.assert_frame_equal(
        placement_features(orders, items)[FEATURES[:14] + FEATURES[-3:]],
        placement_features(modified, items)[FEATURES[:14] + FEATURES[-3:]],
    )
    assert frame.loc["o1", "seller_history_count"] == 0
    assert frame.loc["o1", "region_history_count"] == 0
    assert np.isnan(frame.loc["o4", "items_value"])


def test_history_uses_delivery_availability_not_purchase_or_future_outcomes(raw_dir, tmp_path):
    db = tmp_path / "db.sqlite3"
    ingest(raw_dir, db, tmp_path)
    orders, items = load_orders(db)
    history = OutcomeHistory(orders, items, lag_days=1, window_days=30)
    # o2 outcome is not available at its own purchase, or just before delivery+lag.
    assert history.query(history.sellers, "s1", "2018-01-06 23:59:59")[0] == 0
    # Strictly less than the query time, including exclusion at an identical timestamp.
    assert history.query(history.sellers, "s1", "2018-01-06 23:59:59.000001")[0] == 1
    assert history.query(history.sellers, "s1", "2018-01-08")[0] == 2
    assert history.query(history.sellers, "s2", "2018-01-08")[0] == 1
    assert history.query(history.sellers, "s1", "2018-03-01")[0] == 0
    changed = orders.copy()
    changed.loc[changed.order_id.eq("o1"), "delivered_at"] += pd.Timedelta(days=20)
    later = OutcomeHistory(changed, items, lag_days=1)
    assert later.query(later.sellers, "s1", "2018-01-08")[0] == 1
    with pytest.raises(ValueError):
        OutcomeHistory(orders, items, lag_days=-1)


def test_distance_and_missing_coordinates():
    assert haversine_km(0, 0, 0, 0) == pytest.approx(0)
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.195, rel=1e-4)
    assert np.isnan(haversine_km(np.nan, 0, 0, 1))
