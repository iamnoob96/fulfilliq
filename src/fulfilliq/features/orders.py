"""Explicit feature allowlist; historical outcomes enter only backward-looking queries."""

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from fulfilliq.db.connection import make_engine

NUMERIC_FEATURES = [
    "purchase_year",
    "purchase_month",
    "purchase_weekday",
    "purchase_hour",
    "promised_lead_days",
    "item_count",
    "seller_count",
    "category_count",
    "seller_state_count",
    "items_value",
    "freight_value",
    "total_weight_g",
    "total_volume_cm3",
    "distance_km",
    "seller_history_count",
    "seller_history_late_rate",
    "seller_history_fulfillment_days",
    "region_history_count",
    "region_history_late_rate",
]
CATEGORICAL_FEATURES = ["customer_state", "primary_seller_state", "primary_category"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET_DEFINITION = "actual_delivery_timestamp > estimated_delivery_timestamp"
FEATURE_VERSION = 1


def haversine_km(lat1, lon1, lat2, lon2):
    """Vectorized great-circle distance. Missing coordinates propagate as NaN."""
    lat1, lon1, lat2, lon2 = [
        np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2)
    ]
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def complete_sum(values):
    return values.sum(min_count=len(values))


def load_orders(database_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read only order/item-sized tables, not raw reviews or million-row geolocation."""
    engine = make_engine(database_path, readonly=True)
    try:
        with engine.connect() as conn:
            orders = pd.read_sql_query(
                text("""
                SELECT o.order_id, o.order_status, o.order_purchase_timestamp AS purchased_at,
                  o.order_estimated_delivery_date AS estimated_at,
                  o.order_delivered_customer_date AS delivered_at,
                  o.order_approved_at AS approved_at,
                  o.order_delivered_carrier_date AS carrier_at,
                  c.customer_state, g.latitude AS customer_latitude,
                  g.longitude AS customer_longitude
                FROM orders o JOIN customers c ON o.customer_id=c.customer_id
                LEFT JOIN zip_centroids g ON g.zip_code_prefix=c.customer_zip_code_prefix
                ORDER BY o.order_purchase_timestamp, o.order_id
            """),
                conn,
            )
            items = pd.read_sql_query(
                text("""
                SELECT i.order_id, i.seller_id, i.product_id, i.price, i.freight_value,
                  s.seller_state, g.latitude AS seller_latitude, g.longitude AS seller_longitude,
                  COALESCE(t.product_category_name_english,p.product_category_name,'unknown')
                    AS category,
                  p.product_weight_g, p.product_length_cm*p.product_height_cm*p.product_width_cm
                    AS product_volume_cm3
                FROM order_items i JOIN sellers s ON i.seller_id=s.seller_id
                JOIN products p ON p.product_id=i.product_id
                LEFT JOIN category_translation t ON p.product_category_name=t.product_category_name
                LEFT JOIN zip_centroids g ON g.zip_code_prefix=s.seller_zip_code_prefix
                ORDER BY i.order_id, i.order_item_id
            """),
                conn,
            )
    finally:
        engine.dispose()
    for name in ("purchased_at", "estimated_at", "delivered_at", "approved_at", "carrier_at"):
        orders[name] = pd.to_datetime(orders[name], errors="coerce")
    coordinates = orders.set_index("order_id")
    items["distance_km"] = haversine_km(
        items.order_id.map(coordinates.customer_latitude),
        items.order_id.map(coordinates.customer_longitude),
        items.seller_latitude,
        items.seller_longitude,
    )
    return orders, items


def placement_features(orders: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """One row per order; exactly the same aggregation policy used for API items."""
    aggregates = items.groupby("order_id", sort=False).agg(
        item_count=("product_id", "size"),
        seller_count=("seller_id", "nunique"),
        category_count=("category", "nunique"),
        seller_state_count=("seller_state", "nunique"),
        items_value=("price", complete_sum),
        freight_value=("freight_value", complete_sum),
        total_weight_g=("product_weight_g", complete_sum),
        total_volume_cm3=("product_volume_cm3", complete_sum),
        distance_km=("distance_km", "mean"),
        primary_seller_state=("seller_state", lambda v: min(v.dropna(), default="unknown")),
        primary_category=("category", "min"),
    )
    result = orders.set_index("order_id").join(aggregates, how="left")
    for name in ("item_count", "seller_count", "category_count", "seller_state_count"):
        result[name] = result[name].fillna(0)
    for name, part in (
        ("purchase_year", "year"),
        ("purchase_month", "month"),
        ("purchase_weekday", "dayofweek"),
        ("purchase_hour", "hour"),
    ):
        result[name] = getattr(result.purchased_at.dt, part)
    result["promised_lead_days"] = (
        result.estimated_at - result.purchased_at
    ).dt.total_seconds() / 86400
    return result


def outcome_mask(orders: pd.DataFrame) -> pd.Series:
    return (
        orders.order_status.eq("delivered")
        & orders.purchased_at.notna()
        & orders.delivered_at.ge(orders.purchased_at)
        & orders.estimated_at.ge(orders.purchased_at)
    )


class OutcomeHistory:
    """Prefix sums indexed by outcome availability, with optional rolling windows.

    Delivery+reporting lag proxies when a recorded delivery becomes known. There is no
    historical audit log in Olist; the default one-day lag is a documented assumption.
    """

    def __init__(
        self,
        orders: pd.DataFrame,
        items: pd.DataFrame,
        *,
        lag_days: int = 1,
        window_days: int = 180,
    ):
        if lag_days < 0 or window_days < 1:
            raise ValueError("History lag must be nonnegative and window must be positive")
        eligible = orders.loc[outcome_mask(orders)].copy()
        eligible["available_at"] = eligible.delivered_at + pd.Timedelta(days=lag_days)
        eligible["late"] = (eligible.delivered_at > eligible.estimated_at).astype(float)
        duration = (eligible.carrier_at - eligible.approved_at).dt.total_seconds() / 86400
        eligible["fulfillment"] = duration.where(
            eligible.approved_at.ge(eligible.purchased_at) & duration.ge(0)
        )
        pairs = items[["order_id", "seller_id"]].drop_duplicates()
        self.window_days, self.lag_days = window_days, lag_days
        self.sellers = self._index(pairs.merge(eligible, on="order_id"), "seller_id")
        self.regions = self._index(eligible, "customer_state")

    @staticmethod
    def _index(frame: pd.DataFrame, key: str) -> dict:
        result = {}
        for identifier, group in frame.groupby(key, sort=True):
            group = group.sort_values(["available_at", "order_id"])
            values = np.column_stack(
                [
                    np.ones(len(group)),
                    group.late,
                    group.fulfillment.fillna(0),
                    group.fulfillment.notna().astype(float),
                ]
            )
            result[identifier] = (
                group.available_at.to_numpy(dtype="datetime64[ns]"),
                np.vstack([np.zeros(4), np.cumsum(values, axis=0)]),
            )
        return result

    def query(self, mapping: dict, key: str, timestamp) -> np.ndarray:
        entry = mapping.get(key)
        if entry is None or pd.isna(timestamp):
            return np.zeros(4)
        times, cumulative = entry
        timestamp = np.datetime64(pd.Timestamp(timestamp).to_datetime64(), "ns")
        # side=left strictly excludes simultaneous outcomes and the current order.
        end = np.searchsorted(times, timestamp, side="left")
        start = np.searchsorted(
            times, timestamp - np.timedelta64(self.window_days, "D"), side="left"
        )
        return cumulative[end] - cumulative[start]

    def enrich(self, frame: pd.DataFrame, memberships: dict[str, list[str]]) -> pd.DataFrame:
        result = frame.copy()
        columns = defaultdict(list)
        for order_id, row in result.iterrows():
            histories = [
                self.query(self.sellers, seller, row.purchased_at)
                for seller in memberships.get(order_id, [])
            ]
            seller = np.sum(histories, axis=0) if histories else np.zeros(4)
            region = self.query(self.regions, row.customer_state, row.purchased_at)
            columns["seller_history_count"].append(float(seller[0]))
            columns["seller_history_late_rate"].append(
                seller[1] / seller[0] if seller[0] else np.nan
            )
            columns["seller_history_fulfillment_days"].append(
                seller[2] / seller[3] if seller[3] else np.nan
            )
            columns["region_history_count"].append(float(region[0]))
            columns["region_history_late_rate"].append(
                region[1] / region[0] if region[0] else np.nan
            )
        return result.assign(**columns)


def build_dataset(database_path: Path, *, lag_days: int = 1, window_days: int = 180):
    orders, items = load_orders(database_path)
    history = OutcomeHistory(orders, items, lag_days=lag_days, window_days=window_days)
    memberships = items.groupby("order_id").seller_id.unique().apply(list).to_dict()
    result = history.enrich(placement_features(orders, items), memberships)
    eligible = outcome_mask(result)
    result["target_is_late"] = (result.delivered_at > result.estimated_at).where(eligible)
    result["label_available_at"] = result.delivered_at + pd.Timedelta(days=lag_days)
    return result, history, orders, items
