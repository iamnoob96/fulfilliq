"""Statistics consistently state their denominator and missing-outcome handling."""

from typing import Any

from sqlalchemy import Connection, text


def logistics_summary(connection: Connection) -> dict[str, Any]:
    overview = dict(
        connection.execute(
            text("""
        SELECT COUNT(*) AS total_orders,
          COALESCE(SUM(order_status = 'delivered'), 0) AS delivered_orders,
          COALESCE(SUM(order_status = 'canceled'), 0) AS canceled_orders,
          COALESCE(SUM(outcome_eligible), 0) AS eligible_outcomes,
          COALESCE(SUM(is_late = 1), 0) AS late_orders,
          COUNT(*) - COALESCE(SUM(outcome_eligible), 0) AS excluded_outcomes,
          COALESCE(SUM(item_count = 0), 0) AS orders_without_items,
          COALESCE(SUM(payment_count = 0), 0) AS orders_without_payments,
          COALESCE(SUM(seller_count > 1), 0) AS multi_seller_orders,
          MIN(purchased_at) AS first_purchase, MAX(purchased_at) AS last_purchase,
          AVG(delivery_days) AS mean_delivery_days,
          COUNT(delivery_days) AS delivery_duration_count,
          AVG(approval_days) AS mean_approval_days, COUNT(approval_days) AS approval_duration_count,
          AVG(fulfillment_days) AS mean_fulfillment_days,
          COUNT(fulfillment_days) AS fulfillment_duration_count,
          AVG(transit_days) AS mean_transit_days, COUNT(transit_days) AS transit_duration_count
        FROM fact_orders
    """)
        )
        .mappings()
        .one()
    )
    overview["late_rate"] = (
        overview["late_orders"] / overview["eligible_outcomes"]
        if overview["eligible_outcomes"]
        else None
    )
    states = [
        dict(row)
        for row in connection.execute(
            text("""
        SELECT c.customer_state, COUNT(*) AS total_orders,
          SUM(f.outcome_eligible) AS eligible_outcomes,
          COALESCE(SUM(f.is_late = 1), 0) AS late_orders,
          1.0 * SUM(f.is_late = 1) / NULLIF(SUM(f.outcome_eligible), 0) AS late_rate,
          AVG(f.delivery_days) AS mean_delivery_days
        FROM fact_orders f JOIN dim_customer c ON f.customer_id = c.customer_id
        GROUP BY c.customer_state ORDER BY total_orders DESC, c.customer_state
    """)
        ).mappings()
    ]
    statuses = dict(
        connection.execute(
            text("""
        SELECT order_status, COUNT(*) FROM orders GROUP BY order_status ORDER BY order_status
    """)
        ).all()
    )
    return {
        "kind": "historical_descriptive_statistics",
        "late_definition": "delivery calendar date > estimated calendar date",
        "late_denominator": "delivered orders with coherent purchase, delivery and estimated dates",
        "currency": "BRL",
        "duration_unit": "days",
        "overview": overview,
        "order_status_counts": statuses,
        "by_customer_state": states,
    }


def relationship_checks(connection: Connection) -> dict[str, Any]:
    return dict(
        connection.execute(
            text("""
        SELECT
          (SELECT COUNT(*) FROM orders WHERE order_status = 'delivered' AND
            (order_delivered_customer_date IS NULL OR order_estimated_delivery_date IS NULL
             OR order_purchase_timestamp IS NULL)) AS delivered_missing_outcome_timestamps,
          (SELECT COUNT(*) FROM orders WHERE
            order_delivered_customer_date < order_purchase_timestamp)
            AS delivery_before_purchase,
          (SELECT COUNT(*) FROM orders WHERE order_approved_at < order_purchase_timestamp)
            AS approval_before_purchase,
          (SELECT COUNT(*) FROM orders WHERE order_delivered_carrier_date < order_approved_at)
            AS carrier_before_approval,
          (SELECT COUNT(*) FROM orders WHERE
            order_delivered_customer_date < order_delivered_carrier_date)
            AS delivery_before_carrier,
          (SELECT COUNT(*) FROM orders WHERE
            date(order_estimated_delivery_date) < date(order_purchase_timestamp))
            AS estimate_before_purchase,
          (SELECT COUNT(*) FROM products p LEFT JOIN category_translation t
            ON p.product_category_name = t.product_category_name
            WHERE p.product_category_name IS NOT NULL AND t.product_category_name IS NULL)
            AS products_without_category_translation,
          (SELECT COUNT(*) FROM customers c LEFT JOIN zip_centroids z
            ON c.customer_zip_code_prefix = z.zip_code_prefix
            WHERE z.latitude IS NULL) AS customers_without_valid_zip_coordinates,
          (SELECT COUNT(*) FROM sellers s LEFT JOIN zip_centroids z
            ON s.seller_zip_code_prefix = z.zip_code_prefix
            WHERE z.latitude IS NULL) AS sellers_without_valid_zip_coordinates,
          (SELECT COUNT(*) FROM (SELECT review_id FROM order_reviews
            GROUP BY review_id HAVING COUNT(*) > 1)) AS repeated_review_ids,
          (SELECT COUNT(*) FROM (SELECT order_id FROM order_reviews
            GROUP BY order_id HAVING COUNT(*) > 1)) AS orders_with_multiple_reviews,
          (SELECT COUNT(*) FROM fact_orders WHERE order_status = 'delivered' AND outcome_eligible = 0)
            AS delivered_excluded_from_late_rate
    """)
        )
        .mappings()
        .one()
    )
