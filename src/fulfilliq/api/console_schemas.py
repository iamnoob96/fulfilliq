"""Contracts for historical browsing, replay and human decisions."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fulfilliq.api.intelligence_schemas import Page
from fulfilliq.modeling.contracts import OrderRequest, RiskResponse
from fulfilliq.operations.reviews import ReviewState


class FilterOptions(BaseModel):
    first_purchase: str
    last_purchase: str
    regions: list[str]
    categories: list[str]
    seller_ids: list[str]


class HistoricalOrder(BaseModel):
    order_id: str
    purchased_at: str | None
    estimated_delivery_at: str | None
    region: str | None
    items_value: float | None
    freight_value: float | None
    review_status: str


class Placement(BaseModel):
    order_id: str
    purchased_at: str | None
    estimated_delivery_at: str | None
    customer_state: str | None
    customer_latitude: float | None
    customer_longitude: float | None


class HistoricalProduct(BaseModel):
    order_item_id: int
    product_id: str
    seller_id: str
    seller_state: str | None
    product_category: str
    price: float | None
    freight_value: float | None
    weight_g: float | None
    length_cm: float | None
    height_cm: float | None
    width_cm: float | None
    seller_latitude: float | None
    seller_longitude: float | None


class ObservedOutcome(BaseModel):
    order_status: str
    approved_at: str | None
    carrier_handoff_at: str | None
    delivered_at: str | None


class OrderDetail(BaseModel):
    order_id: str
    placement: Placement
    products: list[HistoricalProduct]
    observed_after_purchase: ObservedOutcome
    replay_payload: OrderRequest | None
    replay_unavailable_reason: str | None
    review: ReviewState
    interpretation: str


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_ids: list[str] = Field(min_length=1, max_length=100)
    review_capacity: int = Field(default=10, ge=0, le=100, strict=True)

    @model_validator(mode="after")
    def valid_identifiers(self):
        if any(not value or len(value) > 100 for value in self.order_ids):
            raise ValueError("Order identifiers must have 1-100 characters")
        if len(set(self.order_ids)) != len(self.order_ids):
            raise ValueError("Order identifiers must be unique")
        if self.review_capacity > len(self.order_ids):
            raise ValueError("Review capacity cannot exceed candidate count")
        return self


class ReplayUnavailable(BaseModel):
    order_id: str
    reason: str


class ReplayResponse(BaseModel):
    predictions: list[RiskResponse]
    review_order_ids: list[str]
    unavailable: list[ReplayUnavailable]
    interpretation: str


HistoricalOrderPage = Page[HistoricalOrder]
