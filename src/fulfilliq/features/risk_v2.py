"""Placement-only geography and availability-indexed, smoothed delivery history.

Keep v1 immutable so previously persisted model bundles remain loadable.
"""

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from fulfilliq.features.orders import (
    CATEGORICAL_FEATURES,
    FEATURES,
    NUMERIC_FEATURES,
    OutcomeHistory,
    load_orders,
    outcome_mask,
    placement_features,
)

FEATURE_VERSION = 2
NEW_NUMERIC = [
    "freight_value_ratio",
    "interstate_item_fraction",
    "seller_smoothed_late_rate",
    "route_history_count",
    "route_smoothed_late_rate",
    "seller_history_delivery_days",
    "route_history_delivery_days",
    "seller_promise_slack_days",
    "route_promise_slack_days",
]
V2_NUMERIC = NUMERIC_FEATURES + NEW_NUMERIC
V2_CATEGORICAL = CATEGORICAL_FEATURES + ["primary_route"]
V2_FEATURES = V2_NUMERIC + V2_CATEGORICAL
FEATURE_SCHEMAS = {1: FEATURES, 2: V2_FEATURES}


def placement_v2(orders: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    frame = placement_features(orders, items)
    states = items.groupby("order_id").seller_state.apply(
        lambda values: tuple(sorted(set(values.dropna())))
    )
    frame["seller_states"] = states.reindex(frame.index)
    customers = orders.set_index("order_id").customer_state
    interstate = items.seller_state.ne(items.order_id.map(customers)).astype(float)
    interstate = interstate.where(
        items.seller_state.notna() & items.order_id.map(customers).notna()
    )
    frame["interstate_item_fraction"] = interstate.groupby(items.order_id).mean()
    frame["freight_value_ratio"] = frame.freight_value / frame.items_value.where(
        frame.items_value > 0
    )
    frame["primary_route"] = (
        frame.primary_seller_state.fillna("unknown") + ">" + frame.customer_state.fillna("unknown")
    )
    return frame


class DeliveryHistoryV2(OutcomeHistory):
    feature_version = FEATURE_VERSION
    prior_strength = 20.0

    def __init__(self, orders, items, *, lag_days=1, window_days=180):
        super().__init__(orders, items, lag_days=lag_days, window_days=window_days)
        eligible = orders.loc[outcome_mask(orders)].copy()
        eligible["available_at"] = eligible.delivered_at + pd.Timedelta(days=lag_days)
        eligible["late"] = (eligible.delivered_at > eligible.estimated_at).astype(float)
        # Reuse the four-element prefix layout; fulfillment now stores delivery duration.
        eligible["fulfillment"] = (
            eligible.delivered_at - eligible.purchased_at
        ).dt.total_seconds() / 86400
        pairs = items[["order_id", "seller_id"]].drop_duplicates()
        self.seller_delivery = self._index(pairs.merge(eligible, on="order_id"), "seller_id")
        routes = (
            items[["order_id", "seller_state"]].drop_duplicates().merge(eligible, on="order_id")
        )
        routes["route"] = routes.seller_state + ">" + routes.customer_state
        self.routes = self._index(routes, "route")
        eligible["global_key"] = "all"
        self.global_history = self._index(eligible, "global_key")

    def enrich(self, frame, memberships):
        result = super().enrich(frame, memberships)
        columns = defaultdict(list)
        for order_id, row in result.iterrows():
            timestamp = row.purchased_at
            global_stats = self.query(self.global_history, "all", timestamp)
            prior = global_stats[1] / global_stats[0] if global_stats[0] else np.nan
            seller_stats = [
                self.query(self.seller_delivery, seller, timestamp)
                for seller in sorted(set(memberships.get(order_id, [])))
            ]
            states = row.seller_states if isinstance(row.seller_states, tuple) else ()
            route_stats = [
                self.query(self.routes, state + ">" + row.customer_state, timestamp)
                for state in states
                if pd.notna(row.customer_state)
            ]
            for name, entries in (("seller", seller_stats), ("route", route_stats)):
                stats = np.sum(entries, axis=0) if entries else np.zeros(4)
                rate = (stats[1] + self.prior_strength * prior) / (stats[0] + self.prior_strength)
                duration = stats[2] / stats[3] if stats[3] else np.nan
                columns[f"{name}_smoothed_late_rate"].append(float(rate))
                columns[f"{name}_history_delivery_days"].append(float(duration))
                columns[f"{name}_promise_slack_days"].append(
                    float(row.promised_lead_days - duration)
                )
                if name == "route":
                    columns["route_history_count"].append(float(stats[0]))
        return result.assign(**columns)


def build_dataset_v2(database_path: Path, *, lag_days=1, window_days=180, purchase_before=None):
    orders, items = load_orders(database_path)
    if purchase_before is not None:
        orders = orders.loc[orders.purchased_at.lt(pd.Timestamp(purchase_before))].copy()
        items = items.loc[items.order_id.isin(orders.order_id)].copy()
    history = DeliveryHistoryV2(orders, items, lag_days=lag_days, window_days=window_days)
    memberships = items.groupby("order_id").seller_id.unique().apply(list).to_dict()
    frame = history.enrich(placement_v2(orders, items), memberships)
    eligible = outcome_mask(frame)
    frame["target_is_late"] = (frame.delivered_at > frame.estimated_at).where(eligible)
    frame["label_available_at"] = frame.delivered_at + pd.Timedelta(days=lag_days)
    return frame, history, orders, items
