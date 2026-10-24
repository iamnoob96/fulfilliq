"""Historical browsing and explicit placement-only reconstruction for saved-model replay."""

from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import text

from fulfilliq.analytics.operations import CohortFilter, OperationsService, numeric_json
from fulfilliq.db.connection import make_engine
from fulfilliq.modeling.contracts import OrderRequest
from fulfilliq.operations.reviews import ReviewStore


class OrderNotFound(ValueError):
    pass


class OrderService:
    def __init__(self, database_path: Path, reviews: ReviewStore):
        self.database_path = database_path
        self.reviews = reviews
        self.operations = OperationsService(database_path)

    def query(self, sql: str, **params) -> list[dict]:
        engine = make_engine(self.database_path, readonly=True)
        try:
            with engine.connect() as conn:
                return [dict(row) for row in conn.execute(text(sql), params).mappings()]
        finally:
            engine.dispose()

    def options(self) -> dict:
        self.operations.load()
        orders = self.operations.orders
        return {
            "first_purchase": orders.purchased_at.min().date().isoformat(),
            "last_purchase": orders.purchased_at.max().date().isoformat(),
            "regions": sorted(orders.region.dropna().unique()),
            "categories": sorted(self.operations.memberships.product_category.unique()),
            "seller_ids": sorted(self.operations.memberships.seller_id.unique()),
        }

    def list(self, filters: CohortFilter, status: str | None, limit: int, offset: int) -> dict:
        frame = self.operations.cohort(filters)
        states = self.reviews.all()
        frame["review_status"] = frame.order_id.map(
            lambda value: states.get(value, {}).get("status", "pending")
        )
        if status:
            frame = frame.loc[frame.review_status.eq(status)]
        frame = frame.sort_values(["purchased_at", "order_id"], ascending=[False, True])
        columns = ["order_id", "purchased_at", "estimated_delivery_at", "region",
                   "items_value", "freight_value", "review_status"]
        # Historical outcome/status deliberately excluded from the replay candidate table.
        rows = frame.iloc[offset:offset + limit][columns].copy()
        for column in ("purchased_at", "estimated_delivery_at"):
            rows[column] = rows[column].map(lambda v: v.isoformat() if v is not None and str(v) != "NaT" else None)
        return {"total": len(frame), "limit": limit, "offset": offset,
                "items": numeric_json(rows.to_dict("records"))}

    def detail(self, order_id: str) -> dict:
        # Placement query does not select final status, delivery milestones or reviews.
        rows = self.query("""SELECT o.order_id, o.order_purchase_timestamp AS purchased_at,
            o.order_estimated_delivery_date AS estimated_delivery_at,
            c.customer_state, g.latitude AS customer_latitude, g.longitude AS customer_longitude
            FROM orders o JOIN customers c ON c.customer_id=o.customer_id
            LEFT JOIN zip_centroids g ON g.zip_code_prefix=c.customer_zip_code_prefix
            WHERE o.order_id=:order_id""", order_id=order_id)
        if not rows:
            raise OrderNotFound("Order not found")
        products = self.query("""SELECT i.order_item_id, i.product_id, i.seller_id, s.seller_state,
            COALESCE(p.product_category_name_english,p.product_category_name,'unknown')
                AS product_category, i.price, i.freight_value,
            p.product_weight_g AS weight_g, p.product_length_cm AS length_cm,
            p.product_height_cm AS height_cm, p.product_width_cm AS width_cm,
            g.latitude AS seller_latitude, g.longitude AS seller_longitude
            FROM order_items i JOIN sellers s ON s.seller_id=i.seller_id
            JOIN dim_product p ON p.product_id=i.product_id
            LEFT JOIN zip_centroids g ON g.zip_code_prefix=s.seller_zip_code_prefix
            WHERE i.order_id=:order_id ORDER BY i.order_item_id""", order_id=order_id)
        payload = {**rows[0], "items": [
            {key: value for key, value in item.items() if key not in ("order_item_id", "product_id")}
            for item in products
        ]}
        try:
            request = OrderRequest.model_validate(payload)
            replay = request.model_dump(mode="json")
            reason = None
        except ValidationError:
            replay = None
            reason = "Missing or invalid placement-time timestamps, region, seller or items; replay unavailable."
        outcome = self.query("""SELECT order_status, order_approved_at AS approved_at,
            order_delivered_carrier_date AS carrier_handoff_at,
            order_delivered_customer_date AS delivered_at FROM orders WHERE order_id=:order_id""",
            order_id=order_id)[0]
        return {"order_id": order_id, "placement": rows[0], "products": products,
                "observed_after_purchase": outcome, "replay_payload": replay,
                "replay_unavailable_reason": reason, "review": self.reviews.get(order_id),
                "interpretation": "Historical replay with the saved model, not an independent backtest. "
                "Catalog, quoted freight, promise and ZIP centroids are assumed available at checkout; "
                "Olist has no versioned catalog. Outcomes and reviews never enter the replay payload. "
                "Seller/region history remains subject to the saved model's availability rules."}
