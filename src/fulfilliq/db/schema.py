"""Explicit source keys; reviews and geolocation intentionally use surrogate keys."""

from dataclasses import dataclass

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table

metadata = MetaData()

category_translation = Table(
    "category_translation",
    metadata,
    Column("product_category_name", String, primary_key=True),
    Column("product_category_name_english", String),
)
customers = Table(
    "customers",
    metadata,
    Column("customer_id", String, primary_key=True),
    Column("customer_unique_id", String, nullable=False),
    Column("customer_zip_code_prefix", String),
    Column("customer_city", String),
    Column("customer_state", String),
)
sellers = Table(
    "sellers",
    metadata,
    Column("seller_id", String, primary_key=True),
    Column("seller_zip_code_prefix", String),
    Column("seller_city", String),
    Column("seller_state", String),
)
products = Table(
    "products",
    metadata,
    Column("product_id", String, primary_key=True),
    # Some original categories have no translation, so this is not a foreign key.
    Column("product_category_name", String),
    Column("product_name_lenght", Integer),
    Column("product_description_lenght", Integer),
    Column("product_photos_qty", Integer),
    Column("product_weight_g", Float),
    Column("product_length_cm", Float),
    Column("product_height_cm", Float),
    Column("product_width_cm", Float),
)
orders = Table(
    "orders",
    metadata,
    Column("order_id", String, primary_key=True),
    Column("customer_id", String, ForeignKey("customers.customer_id"), nullable=False),
    Column("order_status", String, nullable=False),
    Column("order_purchase_timestamp", DateTime),
    Column("order_approved_at", DateTime),
    Column("order_delivered_carrier_date", DateTime),
    Column("order_delivered_customer_date", DateTime),
    Column("order_estimated_delivery_date", DateTime),
)
order_items = Table(
    "order_items",
    metadata,
    Column("order_id", String, ForeignKey("orders.order_id"), primary_key=True),
    Column("order_item_id", Integer, primary_key=True),
    Column("product_id", String, ForeignKey("products.product_id"), nullable=False),
    Column("seller_id", String, ForeignKey("sellers.seller_id"), nullable=False),
    Column("shipping_limit_date", DateTime),
    Column("price", Float),
    Column("freight_value", Float),
)
order_payments = Table(
    "order_payments",
    metadata,
    Column("order_id", String, ForeignKey("orders.order_id"), primary_key=True),
    Column("payment_sequential", Integer, primary_key=True),
    Column("payment_type", String),
    Column("payment_installments", Integer),
    Column("payment_value", Float),
)
order_reviews = Table(
    "order_reviews",
    metadata,
    Column("review_row_id", Integer, primary_key=True, autoincrement=True),
    Column("review_id", String, nullable=False, index=True),
    Column("order_id", String, ForeignKey("orders.order_id"), nullable=False, index=True),
    Column("review_score", Integer),
    Column("review_comment_title", String),
    Column("review_comment_message", String),
    Column("review_creation_date", DateTime),
    Column("review_answer_timestamp", DateTime),
)
geolocation = Table(
    "geolocation",
    metadata,
    Column("geolocation_row_id", Integer, primary_key=True, autoincrement=True),
    Column("geolocation_zip_code_prefix", String, nullable=False, index=True),
    Column("geolocation_lat", Float),
    Column("geolocation_lng", Float),
    Column("geolocation_city", String),
    Column("geolocation_state", String),
)


@dataclass(frozen=True)
class SourceSpec:
    filename: str
    table: Table

    @property
    def columns(self) -> list[str]:
        return [
            c.name
            for c in self.table.columns
            if c.name not in {"review_row_id", "geolocation_row_id"}
        ]


# Parent tables precede children so foreign keys are enforced during ingestion.
SOURCES = (
    SourceSpec("product_category_name_translation.csv", category_translation),
    SourceSpec("olist_customers_dataset.csv", customers),
    SourceSpec("olist_sellers_dataset.csv", sellers),
    SourceSpec("olist_products_dataset.csv", products),
    SourceSpec("olist_orders_dataset.csv", orders),
    SourceSpec("olist_order_items_dataset.csv", order_items),
    SourceSpec("olist_order_payments_dataset.csv", order_payments),
    SourceSpec("olist_order_reviews_dataset.csv", order_reviews),
    SourceSpec("olist_geolocation_dataset.csv", geolocation),
)
