"""Verify physical integrity and analytical grain/totals independently of ETL joins."""

import math
from typing import Any

from sqlalchemy import Connection, inspect, text

from fulfilliq.db.schema import SOURCES

MART_TABLES = (
    "dim_customer",
    "dim_seller",
    "dim_product",
    "dim_date",
    "zip_centroids",
    "bridge_order_sellers",
    "bridge_order_products",
    "fact_orders",
    "etl_runs",
)
REQUIRED_TABLES = tuple(spec.table.name for spec in SOURCES) + MART_TABLES


def verify_database(connection: Connection) -> dict[str, Any]:
    missing = set(REQUIRED_TABLES) - set(inspect(connection).get_table_names())
    if missing:
        raise ValueError(f"Database is missing tables: {sorted(missing)}")
    physical = [row[0] for row in connection.exec_driver_sql("PRAGMA integrity_check")]
    foreign_keys = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    if physical != ["ok"] or foreign_keys:
        raise ValueError(
            f"SQLite integrity failure: {physical}; FK violations: {len(foreign_keys)}"
        )
    # Names below come only from the internal allowlist, never a request or CLI argument.
    counts = {
        name: connection.exec_driver_sql(f'SELECT COUNT(*) FROM "{name}"').scalar_one()
        for name in REQUIRED_TABLES
    }
    if counts["fact_orders"] != counts["orders"]:
        raise ValueError("Order mart must contain exactly one row per source order")
    for dim, source in (
        ("dim_customer", "customers"),
        ("dim_seller", "sellers"),
        ("dim_product", "products"),
    ):
        if counts[dim] != counts[source]:
            raise ValueError(f"Dimension row count differs from source: {dim}")
    for column, source in (
        ("item_count", "order_items"),
        ("payment_count", "order_payments"),
        ("review_count", "order_reviews"),
    ):
        total = connection.exec_driver_sql(
            f"SELECT COALESCE(SUM({column}), 0) FROM fact_orders"
        ).scalar_one()
        if total != counts[source]:
            raise ValueError(f"Order aggregation did not conserve {source} rows")
    for bridge in ("bridge_order_sellers", "bridge_order_products"):
        total = connection.exec_driver_sql(
            f"SELECT COALESCE(SUM(item_count), 0) FROM {bridge}"
        ).scalar_one()
        if total != counts["order_items"]:
            raise ValueError(f"Bridge did not conserve item counts: {bridge}")
    # Compare only complete groups; a missing price must not silently become zero.
    for source, source_column, fact_column in (
        ("order_items", "price", "items_value"),
        ("order_items", "freight_value", "freight_value"),
        ("order_payments", "payment_value", "payment_total"),
    ):
        mismatch = connection.execute(
            text(f"""
            WITH expected AS (
              SELECT order_id, CASE WHEN COUNT({source_column}) = COUNT(*)
                THEN SUM({source_column}) END AS amount FROM {source} GROUP BY order_id
            )
            SELECT e.amount, f.{fact_column} FROM expected e
            JOIN fact_orders f ON f.order_id = e.order_id
        """)
        ).all()
        for expected, actual in mismatch:
            if (expected is None) != (actual is None) or (
                expected is not None and not math.isclose(expected, actual, abs_tol=1e-6)
            ):
                raise ValueError(f"Per-order totals differ: {source}.{source_column}")
    return {
        "integrity_check": "ok",
        "foreign_key_violations": 0,
        "order_grain": "one row per order",
        "row_counts": counts,
    }
