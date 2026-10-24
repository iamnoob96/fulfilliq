import joblib
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from fulfilliq.features.risk_v2 import (
    V2_FEATURES,
    DeliveryHistoryV2,
    build_dataset_v2,
    placement_v2,
)
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.modeling.contracts import OrderRequest
from fulfilliq.modeling.inference import request_features


def events():
    orders = pd.DataFrame(
        {
            "order_id": ["a", "b", "c"],
            "order_status": "delivered",
            "purchased_at": pd.to_datetime(["2018-01-01", "2018-01-02", "2018-02-01"]),
            "delivered_at": pd.to_datetime(["2018-01-04", "2018-01-10", "2018-02-10"]),
            "estimated_at": pd.to_datetime(["2018-01-03", "2018-01-11", "2018-02-02"]),
            "approved_at": pd.to_datetime(["2018-01-01", "2018-01-02", "2018-02-01"]),
            "carrier_at": pd.to_datetime(["2018-01-02", "2018-01-03", "2018-02-02"]),
            "customer_state": "RJ",
        }
    )
    items = pd.DataFrame(
        {"order_id": ["a", "a", "b", "c"], "seller_id": "s1", "seller_state": "SP"}
    )
    return orders, items


def request(at="2018-01-05T00:00:00", seller="s1", **changes):
    value = {
        "order_id": "query",
        "purchased_at": at,
        "estimated_delivery_at": "2018-03-01T00:00:00",
        "customer_state": "RJ",
        "items": [
            {
                "seller_id": seller,
                "seller_state": "SP",
                "price": 50,
                "freight_value": 10,
                "quantity": 2,
            }
        ],
    }
    value.update(changes)
    return OrderRequest.model_validate(value)


def test_availability_equality_lag_and_future_outcome_invariance():
    orders, items = events()
    history = DeliveryHistoryV2(orders, items)
    at_boundary = request_features([request()], history).iloc[0]
    assert at_boundary.seller_history_count == 0
    assert np.isnan(at_boundary.seller_smoothed_late_rate)
    after = request_features([request("2018-01-05T00:00:01")], history)
    assert after.iloc[0].seller_history_count == 1  # duplicate items count once
    assert after.iloc[0].route_history_count == 1
    assert after.iloc[0].seller_history_delivery_days == 3
    assert after.iloc[0].seller_smoothed_late_rate == 1
    changed = orders.copy()
    changed.loc[1:, "delivered_at"] = pd.Timestamp("2019-01-01")
    changed.loc[1, "estimated_at"] = pd.Timestamp("2018-01-03")
    changed_history = DeliveryHistoryV2(changed, items)
    assert_frame_equal(after, request_features([request("2018-01-05T00:00:01")], changed_history))


def test_cold_start_shrinkage_window_and_roundtrip(tmp_path):
    orders, items = events()
    history = DeliveryHistoryV2(orders, items)
    row = request_features([request("2018-01-12", seller="new")], history).iloc[0]
    assert row.seller_history_count == 0
    assert row.seller_smoothed_late_rate == 0.5  # available global prior only
    assert row.route_history_count == 2
    assert row.route_smoothed_late_rate == 0.5
    assert np.isnan(row.seller_history_delivery_days)
    assert row.route_history_delivery_days == 5.5
    old = DeliveryHistoryV2(orders, items, window_days=2)
    assert request_features([request("2018-01-15")], old).iloc[0].route_history_count == 0
    path = tmp_path / "history.joblib"
    joblib.dump(history, path)
    assert_frame_equal(
        request_features([request()], history), request_features([request()], joblib.load(path))
    )


def test_multiseller_route_dedup_and_offline_online_parity():
    orders, items = events()
    items.loc[len(items)] = ["a", "s2", "SP"]
    history = DeliveryHistoryV2(orders, items)
    req = request(
        "2018-01-12",
        items=[
            {
                "seller_id": "s1",
                "seller_state": "SP",
                "price": 50,
                "freight_value": 10,
                "quantity": 2,
            },
            {"seller_id": "s2", "seller_state": "SP", "price": 20, "freight_value": 4},
        ],
    )
    online = request_features([req], history)
    item_frame = pd.DataFrame(
        {
            "order_id": "query",
            "seller_id": ["s1", "s1", "s2"],
            "seller_state": "SP",
            "product_id": "p",
            "category": "unknown",
            "price": [50.0, 50.0, 20.0],
            "freight_value": [10.0, 10.0, 4.0],
            "product_weight_g": np.nan,
            "product_volume_cm3": np.nan,
            "distance_km": np.nan,
        }
    )
    order_frame = pd.DataFrame(
        [
            {
                "order_id": "query",
                "purchased_at": req.purchased_at,
                "estimated_at": req.estimated_delivery_at,
                "customer_state": "RJ",
            }
        ]
    )
    offline = history.enrich(placement_v2(order_frame, item_frame), {"query": ["s1", "s2"]})[
        V2_FEATURES
    ]
    assert_frame_equal(offline, online)
    row = online.iloc[0]
    assert row.seller_history_count == 3  # a/s1, a/s2, b/s1
    assert row.route_history_count == 2  # a/SP>RJ and b/SP>RJ
    assert row.freight_value_ratio == pytest.approx(0.2)
    assert row.interstate_item_fraction == 1
    assert row.primary_route == "SP>RJ"


def test_zero_order_value_ratio_is_unknown():
    orders, items = events()
    history = DeliveryHistoryV2(orders, items)
    req = request(
        items=[{"seller_id": "s1", "seller_state": "SP", "price": 0, "freight_value": 10}]
    )
    assert np.isnan(request_features([req], history).iloc[0].freight_value_ratio)


def test_protected_purchases_are_removed_before_history_construction(raw_dir, tmp_path):
    db = tmp_path / "warehouse.sqlite3"
    ingest(raw_dir, db, tmp_path)
    frame, history, orders, items = build_dataset_v2(db, purchase_before="2018-01-02")
    assert set(frame.index) == {"o1"}
    assert set(orders.order_id) == set(items.order_id) == {"o1"}
    assert history.global_history["all"][1][-1, 0] == 1
