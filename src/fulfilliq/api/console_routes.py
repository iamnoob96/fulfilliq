"""Application workflow routes; warehouse reads and model inference only."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from fulfilliq.analytics.operations import CohortFilter
from fulfilliq.api.console_schemas import (
    FilterOptions,
    HistoricalOrderPage,
    OrderDetail,
    ReplayRequest,
    ReplayResponse,
)
from fulfilliq.api.routes import cohort_filter
from fulfilliq.config import Settings
from fulfilliq.modeling.contracts import OrderRequest
from fulfilliq.modeling.inference import RiskService
from fulfilliq.operations.orders import OrderNotFound, OrderService
from fulfilliq.operations.reviews import (
    ReviewConflict,
    ReviewState,
    ReviewStatus,
    ReviewStore,
    ReviewUpdate,
)


def console_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Operations console"])
    reviews = ReviewStore(settings.review_database_path)
    orders = OrderService(settings.database_path, reviews)
    risk = RiskService(settings.artifact_dir, settings.database_path)

    def detail(order_id: str):
        try:
            return orders.detail(order_id)
        except OrderNotFound as exc:
            raise HTTPException(404, str(exc)) from exc

    def authorize(authorization: Annotated[str | None, Header()] = None):
        expected = "Bearer " + settings.write_token
        if not settings.write_token or not secrets.compare_digest(authorization or "", expected):
            raise HTTPException(403, "Review writes require the configured local operations token")

    @router.get("/console/options", response_model=FilterOptions)
    def options():
        return orders.options()

    @router.get("/orders", response_model=HistoricalOrderPage)
    def list_orders(
        filters: Annotated[CohortFilter, Depends(cohort_filter)],
        review_status: ReviewStatus | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return orders.list(filters, review_status, limit, offset)

    @router.post("/orders/replay", response_model=ReplayResponse)
    def replay(batch: ReplayRequest):
        requests, unavailable = [], []
        for identifier in batch.order_ids:
            try:
                order = orders.detail(identifier)
                if order["replay_payload"] is not None:
                    requests.append(OrderRequest.model_validate(order["replay_payload"]))
                else:
                    unavailable.append({"order_id": identifier, "reason": order["replay_unavailable_reason"]})
            except OrderNotFound:
                unavailable.append({"order_id": identifier, "reason": "Order not found"})
        predictions = risk.predict(requests) if requests else []
        ranked = sorted(predictions, key=lambda value: -value.delay_probability)
        return {"predictions": predictions,
                "review_order_ids": [row.order_id for row in ranked[:batch.review_capacity]],
                "unavailable": unavailable,
                "interpretation": "Historical saved-model replay. Capacity applies only to this "
                "submitted candidate batch, not all warehouse orders. Scores are uncertain risk "
                "estimates; human decisions are separate. This is not an independent backtest."}

    @router.get("/orders/{order_id}", response_model=OrderDetail)
    def order_detail(order_id: str):
        return detail(order_id)

    @router.put("/orders/{order_id}/review", response_model=ReviewState,
                dependencies=[Depends(authorize)], responses={409: {"description": "Revision conflict"}})
    def update_review(order_id: str, change: ReviewUpdate):
        detail(order_id)
        try:
            return reviews.update(order_id, change)
        except ReviewConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
