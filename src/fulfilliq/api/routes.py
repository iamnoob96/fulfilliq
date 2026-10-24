"""Thin versioned routes; training and mining are explicit offline CLI operations."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from fulfilliq.analytics.operations import CohortFilter, OperationsService
from fulfilliq.analytics.store import InsightUnavailable, load_insight
from fulfilliq.api.intelligence_schemas import (
    AnomaliesResponse,
    BottlenecksResponse,
    ModelInfoResponse,
    ModelMetricsResponse,
    OverviewResponse,
    PerformanceResponse,
    ReviewsResponse,
    RulesResponse,
    SegmentsResponse,
    SellerInsights,
)
from fulfilliq.config import Settings
from fulfilliq.features.orders import TARGET_DEFINITION
from fulfilliq.modeling.contracts import BatchRequest, BatchResponse, OrderRequest, RiskResponse
from fulfilliq.modeling.inference import RiskService

GroupBy = Literal["region", "seller", "category", "month"]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


def cohort_filter(
    seller_id: str | None = Query(default=None, max_length=100),
    region: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"),
    product_category: str | None = Query(default=None, max_length=100),
    start_date: date | None = None,
    end_date: date | None = None,
) -> CohortFilter:
    return CohortFilter(seller_id, region, product_category, start_date, end_date)


def page(rows: list, limit: int, offset: int) -> dict:
    return {
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows[offset : offset + limit],
    }


def intelligence_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    operations = OperationsService(settings.database_path)
    risk = RiskService(settings.artifact_dir, settings.database_path)

    def insight(name):
        return load_insight(settings.artifact_dir, name, settings.database_path)

    @router.post("/orders/predict-delay", response_model=RiskResponse, tags=["Delivery risk"])
    def predict_delay(order: OrderRequest):
        return risk.predict([order])[0]

    @router.post("/orders/predict-batch", response_model=BatchResponse, tags=["Delivery risk"])
    def predict_batch(batch: BatchRequest):
        predictions = risk.predict(batch.orders)
        ranked = sorted(predictions, key=lambda value: -value.delay_probability)
        return {
            "predictions": predictions,
            "priority_order_ids": [row.order_id for row in ranked if row.risk_category == "high"],
            "review_order_ids": [row.order_id for row in ranked[: batch.review_capacity]]
            if batch.review_capacity is not None
            else [],
        }

    @router.get("/analytics/overview", response_model=OverviewResponse, tags=["Operations"])
    def overview(filters: Annotated[CohortFilter, Depends(cohort_filter)]):
        return operations.overview(filters)

    @router.get(
        "/analytics/delivery-performance", response_model=PerformanceResponse, tags=["Operations"]
    )
    def performance(
        filters: Annotated[CohortFilter, Depends(cohort_filter)],
        group_by: GroupBy = "region",
        min_orders: int = Query(default=1, ge=1),
        limit: Limit = 100,
        offset: Offset = 0,
    ):
        return {
            **page(operations.performance(group_by, filters, min_orders=min_orders), limit, offset),
            "group_by": group_by,
            "target_definition": TARGET_DEFINITION,
            "interpretation": "Historical order-level associations. Seller/category groups can "
            "share orders and must not be summed to obtain overall totals.",
        }

    @router.get("/analytics/bottlenecks", response_model=BottlenecksResponse, tags=["Operations"])
    def bottlenecks(
        filters: Annotated[CohortFilter, Depends(cohort_filter)],
        group_by: GroupBy = "region",
        min_orders: int = Query(default=20, ge=1),
        limit: Limit = 100,
        offset: Offset = 0,
    ):
        result = operations.bottlenecks(group_by, filters, min_orders=min_orders)
        return {**result, **page(result["items"], limit, offset)}

    @router.get("/mining/association-rules", response_model=RulesResponse, tags=["Data mining"])
    def rules(
        min_support: float = Query(default=0, ge=0, le=1),
        min_confidence: float = Query(default=0, ge=0, le=1),
        min_lift: float = Query(default=0, ge=0),
        antecedent_contains: str | None = Query(default=None, max_length=100),
        sort_by: Literal["lift", "confidence", "support"] = "lift",
        sort_order: Literal["asc", "desc"] = "desc",
        limit: Limit = 100,
        offset: Offset = 0,
    ):
        report = insight("rules")
        rows = [
            row
            for row in report["rules"]
            if row["support"] >= min_support
            and row["confidence"] >= min_confidence
            and row["lift"] >= min_lift
            and (
                not antecedent_contains
                or any(antecedent_contains in value for value in row["antecedents"])
            )
        ]
        rows.sort(key=lambda row: (row[sort_by], row["support"], row["antecedents"]),
                  reverse=sort_order == "desc")
        return {**report, "mining_parameters": report.get("parameters", {}),
                "created_at_utc": report.get("created_at_utc"), **page(rows, limit, offset)}

    @router.get("/mining/anomalies", response_model=AnomaliesResponse, tags=["Data mining"])
    def anomalies(
        kind: Literal["order", "seller", "region", "seller_fulfillment"] | None = None,
        entity_id: str | None = Query(default=None, max_length=100),
        limit: Limit = 100,
        offset: Offset = 0,
    ):
        report = insight("anomalies")
        rows = [
            row
            for row in report["anomalies"]
            if (kind is None or row["kind"] == kind)
            and (entity_id is None or row["entity_id"] == entity_id)
        ]
        return {**report, **page(rows, limit, offset)}

    @router.get("/sellers/segments", response_model=SegmentsResponse, tags=["Sellers"])
    def segments(
        segment_id: int | None = Query(default=None, ge=0),
        seller_state: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"),
        limit: Limit = 100,
        offset: Offset = 0,
    ):
        report = insight("segments")
        rows = [
            row
            for row in report["assignments"]
            if (segment_id is None or row["segment_id"] == segment_id)
            and (seller_state is None or row["features"]["seller_state"] == seller_state)
        ]
        return {**report, "feature_names": report.get("features", []), **page(rows, limit, offset)}

    @router.get("/sellers/{seller_id}/insights", response_model=SellerInsights, tags=["Sellers"])
    def seller_insights(seller_id: str):
        operations.load()
        if not operations.memberships.seller_id.eq(seller_id).any():
            raise HTTPException(404, "Seller not found in order items")
        performance = operations.performance("seller", CohortFilter(seller_id=seller_id))
        result = {
            "seller_id": seller_id,
            "performance": performance[0] if performance else None,
            "segment": None,
            "reviews": None,
            "anomalies": [],
            "warnings": [],
        }
        for name, key, list_key in (
            ("segments", "segment", "assignments"),
            ("reviews", "reviews", "by_seller"),
            ("anomalies", "anomalies", "anomalies"),
        ):
            try:
                report = insight(name)
                if name == "anomalies":
                    result[key] = [
                        row
                        for row in report[list_key]
                        if row["kind"].startswith("seller") and row["entity_id"] == seller_id
                    ]
                else:
                    identity = "seller_id" if name == "segments" else "group"
                    result[key] = next(
                        (row for row in report[list_key] if row[identity] == seller_id), None
                    )
            except InsightUnavailable as exc:
                result["warnings"].append(str(exc))
        if result["segment"] is None:
            result["warnings"].append(
                "No supported seller segment; history may be below the minimum volume."
            )
        return result

    @router.get("/reviews/insights", response_model=ReviewsResponse, tags=["Review intelligence"])
    def reviews(
        group_by: Literal["seller", "category", "region"] = "region",
        group: str | None = Query(default=None, max_length=100),
        theme: Literal[
            "late_delivery",
            "damaged_packaging",
            "missing_or_incorrect_items",
            "product_quality",
            "positive_delivery",
        ]
        | None = None,
        min_text_reviews: int = Query(default=1, ge=0),
        limit: Limit = 100,
        offset: Offset = 0,
    ):
        report = insight("reviews")
        rows = [
            row
            for row in report[f"by_{group_by}"]
            if row["text_review_count"] >= min_text_reviews
            and (group is None or row["group"] == group)
            and (theme is None or row["themes"][theme] > 0)
        ]
        return {
            **page(rows, limit, offset),
            "group_by": group_by,
            "global_summary": report,
            "interpretation": report["interpretation"],
        }

    @router.get("/models/metrics", response_model=ModelMetricsResponse, tags=["Models"])
    def model_metrics():
        return risk.load()

    @router.get("/models/info", response_model=ModelInfoResponse, tags=["Models"])
    def model_info():
        return risk.load()

    return router
