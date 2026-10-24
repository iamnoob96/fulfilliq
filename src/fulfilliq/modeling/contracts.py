"""Checkout request contract; no outcome, review or handoff fields are accepted."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
State = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seller_id: str = Field(min_length=1, max_length=64)
    seller_state: State
    product_category: str = Field(default="unknown", min_length=1, max_length=100)
    quantity: int = Field(default=1, ge=1, le=100)
    price: Nonnegative | None = None
    freight_value: Nonnegative | None = None
    weight_g: Nonnegative | None = None
    length_cm: Nonnegative | None = None
    height_cm: Nonnegative | None = None
    width_cm: Nonnegative | None = None
    seller_latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    seller_longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.seller_latitude is None) != (self.seller_longitude is None):
            raise ValueError("Seller latitude and longitude must be provided together")
        return self


class OrderRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "order_id": "new-order-001",
                    "purchased_at": "2018-07-01T12:00:00",
                    "estimated_delivery_at": "2018-07-20T00:00:00",
                    "customer_state": "RJ",
                    "customer_latitude": -22.9,
                    "customer_longitude": -43.2,
                    "items": [
                        {
                            "seller_id": "seller-example",
                            "seller_state": "SP",
                            "product_category": "housewares",
                            "price": 120,
                            "freight_value": 20,
                            "weight_g": 500,
                            "length_cm": 20,
                            "height_cm": 10,
                            "width_cm": 15,
                            "seller_latitude": -23.55,
                            "seller_longitude": -46.63,
                        }
                    ],
                }
            ]
        },
    )
    order_id: str = Field(default="new-order", min_length=1, max_length=100)
    purchased_at: datetime
    estimated_delivery_at: datetime
    customer_state: State
    customer_latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    customer_longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    items: list[OrderItem] = Field(min_length=1, max_length=100)

    @field_validator("purchased_at", "estimated_delivery_at")
    @classmethod
    def source_local_time(cls, value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value.astimezone(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)
        return value

    @model_validator(mode="after")
    def coherent_order(self):
        if self.estimated_delivery_at < self.purchased_at:
            raise ValueError("Estimated delivery cannot precede purchase")
        if sum(item.quantity for item in self.items) > 1000:
            raise ValueError("An order may contain at most 1000 units")
        if (self.customer_latitude is None) != (self.customer_longitude is None):
            raise ValueError("Customer latitude and longitude must be provided together")
        states = {}
        for item in self.items:
            if item.seller_id in states and states[item.seller_id] != item.seller_state:
                raise ValueError("A seller cannot have conflicting states in one order")
            states[item.seller_id] = item.seller_state
        return self


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orders: list[OrderRequest] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_orders(self):
        if len({order.order_id for order in self.orders}) != len(self.orders):
            raise ValueError("Batch order identifiers must be unique")
        return self


class RiskResponse(BaseModel):
    order_id: str
    delay_probability: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    risk_category: str
    model_version: str
    recommendation: str
    rationale: list[str]
    warnings: list[str]


class BatchResponse(BaseModel):
    predictions: list[RiskResponse]
    priority_order_ids: list[str] = Field(default_factory=list)
