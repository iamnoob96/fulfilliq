"""Filtered order cohorts and explicit non-additive seller/category memberships."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from fulfilliq.db.connection import make_engine
from fulfilliq.features.orders import TARGET_DEFINITION

STAGES = [
    "approval_days",
    "fulfillment_days",
    "purchase_to_carrier_days",
    "transit_days",
    "delivery_days",
    "lateness_days",
]


@dataclass(frozen=True)
class CohortFilter:
    seller_id: str | None = None
    region: str | None = None
    product_category: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    def __post_init__(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")


class OperationsService:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.mtime = None
        self.orders = self.memberships = None

    def load(self):
        mtime = self.database_path.stat().st_mtime_ns
        if mtime == self.mtime:
            return
        engine = make_engine(self.database_path, readonly=True)
        try:
            with engine.connect() as conn:
                orders = pd.read_sql_query(
                    text("""
                    SELECT f.*, c.customer_state AS region FROM fact_orders f
                    JOIN dim_customer c ON f.customer_id=c.customer_id
                """),
                    conn,
                )
                memberships = pd.read_sql_query(
                    text("""
                    SELECT DISTINCT i.order_id, i.seller_id,
                      COALESCE(p.product_category_name_english,p.product_category_name,'unknown')
                        AS product_category
                    FROM order_items i JOIN dim_product p ON i.product_id=p.product_id
                """),
                    conn,
                )
        finally:
            engine.dispose()
        for column in (
            "purchased_at",
            "delivered_at",
            "estimated_delivery_at",
            "carrier_handoff_at",
        ):
            orders[column] = pd.to_datetime(orders[column])
        orders["eligible"] = (
            orders.order_status.eq("delivered")
            & orders.purchased_at.notna()
            & orders.delivered_at.ge(orders.purchased_at)
            & orders.estimated_delivery_at.ge(orders.purchased_at)
        )
        orders["late"] = (orders.delivered_at > orders.estimated_delivery_at).where(orders.eligible)
        orders["lateness_days"] = (
            ((orders.delivered_at - orders.estimated_delivery_at).dt.total_seconds() / 86400)
            .clip(lower=0)
            .where(orders.eligible)
        )
        orders["purchase_to_carrier_days"] = (
            (orders.carrier_handoff_at - orders.purchased_at).dt.total_seconds() / 86400
        ).where(orders.carrier_handoff_at.ge(orders.purchased_at))
        orders["month"] = orders.purchased_at.dt.strftime("%Y-%m")
        self.orders, self.memberships, self.mtime = orders, memberships, mtime

    def cohort(self, filters: CohortFilter | None = None) -> pd.DataFrame:
        self.load()
        filters = filters or CohortFilter()
        frame = self.orders
        if filters.seller_id or filters.product_category:
            members = self.memberships
            if filters.seller_id:
                members = members.loc[members.seller_id.eq(filters.seller_id)]
            if filters.product_category:
                members = members.loc[members.product_category.eq(filters.product_category)]
            frame = frame.loc[frame.order_id.isin(members.order_id)]
        if filters.region:
            frame = frame.loc[frame.region.eq(filters.region)]
        if filters.start_date:
            frame = frame.loc[frame.purchased_at.ge(pd.Timestamp(filters.start_date))]
        if filters.end_date:
            frame = frame.loc[
                frame.purchased_at.lt(pd.Timestamp(filters.end_date) + pd.Timedelta(days=1))
            ]
        return frame.copy()

    @staticmethod
    def summarize(frame: pd.DataFrame) -> dict:
        eligible = frame.loc[frame.eligible]
        durations = {}
        for column in STAGES:
            values = frame[column].dropna()
            durations[column] = {
                "count": len(values),
                "mean": float(values.mean()) if len(values) else None,
                "median": float(values.median()) if len(values) else None,
                "p90": float(values.quantile(0.9)) if len(values) else None,
            }
        return {
            "total_orders": len(frame),
            "eligible_outcomes": len(eligible),
            "excluded_outcomes": len(frame) - len(eligible),
            "late_orders": int(eligible.late.sum()),
            "late_rate": float(eligible.late.mean()) if len(eligible) else None,
            "durations": durations,
        }

    def overview(self, filters: CohortFilter | None = None) -> dict:
        frame = self.cohort(filters)
        return {
            "target_definition": TARGET_DEFINITION,
            **self.summarize(frame),
            "status_counts": {str(k): int(v) for k, v in frame.order_status.value_counts().items()},
            "monthly_volume": [
                {"month": str(month), "orders": len(group)}
                for month, group in frame.groupby("month", sort=True)
            ],
        }

    def performance(
        self, group_by: str = "region", filters: CohortFilter | None = None, *, min_orders: int = 1
    ) -> list[dict]:
        if group_by not in {"region", "seller", "category", "month"}:
            raise ValueError("group_by must be region, seller, category or month")
        frame = self.cohort(filters)
        if group_by in {"seller", "category"}:
            key = "seller_id" if group_by == "seller" else "product_category"
            members = self.memberships
            # Keep seller/category attribution consistent with the cohort's item-level filter.
            if filters and filters.seller_id:
                members = members.loc[members.seller_id.eq(filters.seller_id)]
            if filters and filters.product_category:
                members = members.loc[members.product_category.eq(filters.product_category)]
            frame = frame.merge(members[["order_id", key]].drop_duplicates(), on="order_id")
        else:
            key = group_by
        result = []
        for value, group in frame.groupby(key, dropna=False):
            if len(group) < min_orders:
                continue
            result.append(
                {"group": str(value) if pd.notna(value) else "unknown", **self.summarize(group)}
            )
        return sorted(
            result,
            key=lambda row: (
                -(row["late_rate"] if row["late_rate"] is not None else -1),
                -row["total_orders"],
                row["group"],
            ),
        )

    def bottlenecks(
        self, group_by: str, filters: CohortFilter | None = None, *, min_orders: int = 20
    ) -> dict:
        groups = self.performance(group_by, filters, min_orders=min_orders)
        for group in groups:
            # Only disjoint journey stages compete; total journey lengths do not.
            stages = {
                name: group["durations"][name]
                for name in ("approval_days", "fulfillment_days", "transit_days")
                if group["durations"][name]["count"] >= min_orders
            }
            group["longest_median_stage"] = (
                max(stages, key=lambda key: stages[key]["median"]) if stages else None
            )
            group["recommendation"] = (
                "Investigate recurring order milestones and compare with matched operational cohorts."
                if group["late_orders"]
                else "No observed late outcomes in this filtered cohort."
            )
        return {
            "group_by": group_by,
            "items": groups,
            "interpretation": "Historical order-level associations; shared orders are attributed "
            "to every participating seller/category. Groups are not additive, "
            "and durations do not isolate a seller's own dispatch events.",
        }


def numeric_json(value):
    """Convert Pandas/NumPy output to strict JSON, with missing values represented by null."""
    if isinstance(value, dict):
        return {str(key): numeric_json(v) for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [numeric_json(v) for v in value]
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return value
