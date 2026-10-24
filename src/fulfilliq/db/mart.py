"""A historical reporting mart. These columns are NOT a purchase-time ML feature set."""

from sqlalchemy import Connection

SCHEMA_VERSION = 1

# These statements run against a newly created staging database, never a live snapshot.
STATEMENTS = (
    """CREATE TABLE dim_customer (
        customer_id TEXT PRIMARY KEY, customer_unique_id TEXT NOT NULL,
        customer_zip_code_prefix TEXT, customer_city TEXT, customer_state TEXT)""",
    "INSERT INTO dim_customer SELECT * FROM customers",
    """CREATE TABLE dim_seller (
        seller_id TEXT PRIMARY KEY, seller_zip_code_prefix TEXT,
        seller_city TEXT, seller_state TEXT)""",
    "INSERT INTO dim_seller SELECT * FROM sellers",
    """CREATE TABLE dim_product (
        product_id TEXT PRIMARY KEY, product_category_name TEXT,
        product_category_name_english TEXT, product_weight_g REAL,
        product_length_cm REAL, product_height_cm REAL, product_width_cm REAL)""",
    """INSERT INTO dim_product
        SELECT p.product_id, p.product_category_name, t.product_category_name_english,
               p.product_weight_g, p.product_length_cm, p.product_height_cm, p.product_width_cm
        FROM products p LEFT JOIN category_translation t
        ON p.product_category_name = t.product_category_name""",
    """CREATE TABLE dim_date (
        date_key INTEGER PRIMARY KEY, calendar_date TEXT UNIQUE NOT NULL,
        year INTEGER NOT NULL, month INTEGER NOT NULL, day INTEGER NOT NULL,
        weekday INTEGER NOT NULL, quarter INTEGER NOT NULL)""",
    """INSERT INTO dim_date
        SELECT DISTINCT CAST(strftime('%Y%m%d', order_purchase_timestamp) AS INTEGER),
          date(order_purchase_timestamp),
          CAST(strftime('%Y', order_purchase_timestamp) AS INTEGER),
          CAST(strftime('%m', order_purchase_timestamp) AS INTEGER),
          CAST(strftime('%d', order_purchase_timestamp) AS INTEGER),
          (CAST(strftime('%w', order_purchase_timestamp) AS INTEGER) + 6) % 7,
          (CAST(strftime('%m', order_purchase_timestamp) AS INTEGER) + 2) / 3
        FROM orders WHERE order_purchase_timestamp IS NOT NULL""",
    """CREATE TABLE zip_centroids (
        zip_code_prefix TEXT PRIMARY KEY, latitude REAL, longitude REAL,
        source_record_count INTEGER NOT NULL, valid_coordinate_count INTEGER NOT NULL)""",
    """INSERT INTO zip_centroids
        SELECT geolocation_zip_code_prefix,
          AVG(CASE WHEN geolocation_lat IS NOT NULL AND geolocation_lng IS NOT NULL
              THEN geolocation_lat END),
          AVG(CASE WHEN geolocation_lat IS NOT NULL AND geolocation_lng IS NOT NULL
              THEN geolocation_lng END), COUNT(*),
          SUM(geolocation_lat IS NOT NULL AND geolocation_lng IS NOT NULL)
        FROM geolocation GROUP BY geolocation_zip_code_prefix""",
    """CREATE TABLE bridge_order_sellers (
        order_id TEXT NOT NULL REFERENCES orders(order_id),
        seller_id TEXT NOT NULL REFERENCES dim_seller(seller_id),
        item_count INTEGER NOT NULL, items_value REAL, freight_value REAL,
        PRIMARY KEY (order_id, seller_id))""",
    """INSERT INTO bridge_order_sellers
        SELECT order_id, seller_id, COUNT(*),
          CASE WHEN COUNT(price) = COUNT(*) THEN SUM(price) END,
          CASE WHEN COUNT(freight_value) = COUNT(*) THEN SUM(freight_value) END
        FROM order_items GROUP BY order_id, seller_id""",
    """CREATE TABLE bridge_order_products (
        order_id TEXT NOT NULL REFERENCES orders(order_id),
        product_id TEXT NOT NULL REFERENCES dim_product(product_id),
        item_count INTEGER NOT NULL, PRIMARY KEY (order_id, product_id))""",
    """INSERT INTO bridge_order_products
        SELECT order_id, product_id, COUNT(*) FROM order_items GROUP BY order_id, product_id""",
    """CREATE TABLE fact_orders (
        order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
        customer_id TEXT NOT NULL REFERENCES dim_customer(customer_id),
        purchase_date_key INTEGER REFERENCES dim_date(date_key),
        order_status TEXT NOT NULL, purchased_at DATETIME, approved_at DATETIME,
        carrier_handoff_at DATETIME, delivered_at DATETIME, estimated_delivery_at DATETIME,
        item_count INTEGER NOT NULL, seller_count INTEGER NOT NULL,
        product_count INTEGER NOT NULL, items_value REAL, freight_value REAL,
        total_order_value REAL, total_product_weight_g REAL,
        payment_count INTEGER NOT NULL, payment_total REAL,
        review_count INTEGER NOT NULL, average_review_score REAL,
        outcome_eligible INTEGER NOT NULL CHECK(outcome_eligible IN (0, 1)),
        is_late INTEGER CHECK(is_late IN (0, 1)), delay_days INTEGER,
        delivery_days REAL, approval_days REAL, fulfillment_days REAL, transit_days REAL,
        promised_lead_days REAL)""",
    """INSERT INTO fact_orders
        WITH items AS (
          SELECT i.order_id, COUNT(*) AS item_count,
            COUNT(DISTINCT i.seller_id) AS seller_count,
            COUNT(DISTINCT i.product_id) AS product_count,
            CASE WHEN COUNT(i.price) = COUNT(*) THEN SUM(i.price) END AS items_value,
            CASE WHEN COUNT(i.freight_value) = COUNT(*)
              THEN SUM(i.freight_value) END AS freight_value,
            CASE WHEN COUNT(p.product_weight_g) = COUNT(*)
              THEN SUM(p.product_weight_g) END AS total_product_weight_g
          FROM order_items i JOIN products p ON i.product_id = p.product_id GROUP BY i.order_id
        ), payments AS (
          SELECT order_id, COUNT(*) AS payment_count,
            CASE WHEN COUNT(payment_value) = COUNT(*) THEN SUM(payment_value) END AS payment_total
          FROM order_payments GROUP BY order_id
        ), reviews AS (
          SELECT order_id, COUNT(*) AS review_count, AVG(review_score) AS average_review_score
          FROM order_reviews GROUP BY order_id
        ), outcomes AS (
          SELECT *, CASE WHEN order_status = 'delivered'
            AND order_purchase_timestamp IS NOT NULL
            AND order_delivered_customer_date >= order_purchase_timestamp
            AND date(order_estimated_delivery_date) >= date(order_purchase_timestamp)
            THEN 1 ELSE 0 END AS eligible
          FROM orders
        )
        SELECT o.order_id, o.customer_id,
          CAST(strftime('%Y%m%d', o.order_purchase_timestamp) AS INTEGER), o.order_status,
          o.order_purchase_timestamp, o.order_approved_at, o.order_delivered_carrier_date,
          o.order_delivered_customer_date, o.order_estimated_delivery_date,
          COALESCE(i.item_count, 0), COALESCE(i.seller_count, 0), COALESCE(i.product_count, 0),
          i.items_value, i.freight_value, i.items_value + i.freight_value,
          i.total_product_weight_g, COALESCE(p.payment_count, 0), p.payment_total,
          COALESCE(r.review_count, 0), r.average_review_score, o.eligible,
          CASE WHEN o.eligible = 1 THEN
            date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date) END,
          CASE WHEN o.eligible = 1 THEN CAST(MAX(0,
            julianday(date(o.order_delivered_customer_date)) -
            julianday(date(o.order_estimated_delivery_date))) AS INTEGER) END,
          CASE WHEN o.order_status = 'delivered'
            AND o.order_delivered_customer_date >= o.order_purchase_timestamp THEN
            julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp) END,
          CASE WHEN o.order_approved_at >= o.order_purchase_timestamp THEN
            julianday(o.order_approved_at) - julianday(o.order_purchase_timestamp) END,
          CASE WHEN o.order_delivered_carrier_date >= o.order_approved_at
            AND o.order_approved_at >= o.order_purchase_timestamp THEN
            julianday(o.order_delivered_carrier_date) - julianday(o.order_approved_at) END,
          CASE WHEN o.order_status = 'delivered'
            AND o.order_delivered_customer_date >= o.order_delivered_carrier_date
            AND o.order_delivered_carrier_date >= o.order_purchase_timestamp THEN
            julianday(o.order_delivered_customer_date) - julianday(o.order_delivered_carrier_date) END,
          CASE WHEN date(o.order_estimated_delivery_date) >= date(o.order_purchase_timestamp) THEN
            julianday(date(o.order_estimated_delivery_date)) -
            julianday(date(o.order_purchase_timestamp)) END
        FROM outcomes o
        LEFT JOIN items i ON i.order_id = o.order_id
        LEFT JOIN payments p ON p.order_id = o.order_id
        LEFT JOIN reviews r ON r.order_id = o.order_id""",
    "CREATE INDEX ix_fact_orders_customer ON fact_orders(customer_id)",
    "CREATE INDEX ix_fact_orders_purchase ON fact_orders(purchase_date_key)",
    "CREATE INDEX ix_bridge_sellers_seller ON bridge_order_sellers(seller_id)",
    "CREATE INDEX ix_bridge_products_product ON bridge_order_products(product_id)",
    """CREATE TABLE etl_runs (
        run_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
        completed_at_utc TEXT NOT NULL, quality_json TEXT NOT NULL, summary_json TEXT NOT NULL)""",
)


def build_mart(connection: Connection) -> None:
    for statement in STATEMENTS:
        connection.exec_driver_sql(statement)
