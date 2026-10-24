"""Read-only mining, review evidence and report integration for the console."""

import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from fulfilliq.analytics.operations import CohortFilter
from fulfilliq.analytics.store import load_insight
from fulfilliq.api.intelligence_schemas import (
    AssociationRule,
    BottleneckRow,
    OverviewResponse,
    Page,
    PerformanceRow,
)
from fulfilliq.api.routes import cohort_filter, page
from fulfilliq.config import Settings
from fulfilliq.operations.feedback import review_samples
from fulfilliq.operations.orders import OrderService
from fulfilliq.operations.reporting import operational_report
from fulfilliq.operations.reviews import ReviewStore


class FrequentItemset(BaseModel):
    items: list[str]
    support: float
    support_count: int


class ItemsetsResponse(Page[FrequentItemset]):
    algorithm: str
    algorithms: dict[str, dict[str, float | int]] = Field(default_factory=dict)
    algorithms_agree: bool = False
    transaction_count: int = 0
    mining_parameters: dict[str, float | int] = Field(default_factory=dict)
    created_at_utc: str | None = None
    interpretation: str


class ReviewExcerpt(BaseModel):
    excerpt: str
    themes: list[str]
    review_score: int | None


class FeedbackResponse(BaseModel):
    review_records: int
    score_counts: dict[str, int]
    examples: list[ReviewExcerpt]
    redaction: str


class OperationsReport(BaseModel):
    filters: dict[str, str | None]
    overview: OverviewResponse
    regions: list[PerformanceRow]
    sellers: list[PerformanceRow]
    bottlenecks: list[BottleneckRow]
    rules: list[AssociationRule]
    limitations: list[str]
    markdown: str
    mining_created_at_utc: str | None = None


class ResearchReport(BaseModel):
    name: str
    available: bool
    summary: dict


class ResearchResponse(BaseModel):
    interpretation: str
    reports: list[ResearchReport]


def explorer_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Operations console"])
    orders = OrderService(settings.database_path, ReviewStore(settings.review_database_path))

    @router.get("/mining/itemsets", response_model=ItemsetsResponse)
    def itemsets(algorithm: Literal["apriori", "fp_growth"] = "apriori",
                 min_support: float = Query(default=0, ge=0, le=1),
                 sort_by: Literal["support", "support_count", "size", "items"] | None = None,
                 sort_order: Literal["asc", "desc"] = "desc",
                 limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
        report = load_insight(settings.artifact_dir, "rules", settings.database_path)
        if "itemsets" not in report:
            raise HTTPException(503, "Rebuild only mining outputs: fulfilliq build-insights --module rules")
        rows = [row for row in report["itemsets"] if row["support"] >= min_support]
        if sort_by == "support":
            rows.sort(key=lambda row: (row["support"], row["support_count"], row["items"]), reverse=sort_order == "desc")
        elif sort_by == "support_count":
            rows.sort(key=lambda row: (row["support_count"], row["support"], row["items"]), reverse=sort_order == "desc")
        elif sort_by == "size":
            rows.sort(key=lambda row: (len(row["items"]), row["support"], row["items"]), reverse=sort_order == "desc")
        elif sort_by == "items":
            rows.sort(key=lambda row: tuple(row["items"]), reverse=sort_order == "desc")
        return {**page(rows, limit, offset), "algorithm": algorithm,
                "algorithms": report["algorithms"], "algorithms_agree": report["algorithms_agree"],
                "transaction_count": report["transaction_count"], "mining_parameters": report["parameters"],
                "created_at_utc": report.get("created_at_utc"),
                "interpretation": "Identical itemsets/support verified for Apriori and FP-Growth "
                "during offline mining; one shared representation is stored. Full-history associations."}

    @router.get("/reviews/evidence", response_model=FeedbackResponse)
    def feedback(seller_id: str | None = Query(default=None, max_length=100),
                 region: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"),
                 product_category: str | None = Query(default=None, max_length=100),
                 limit: int = Query(default=12, ge=1, le=30)):
        return review_samples(orders, seller_id=seller_id, region=region,
                              category=product_category, limit=limit)

    @router.get("/reports/operations", response_model=OperationsReport)
    def report(filters: Annotated[CohortFilter, Depends(cohort_filter)]):
        return operational_report(settings, filters)

    @router.get("/models/research", response_model=ResearchResponse)
    def research():
        folder = Path(__file__).resolve().parents[3] / "docs" / "results"
        result = []
        for filename in ("temporal-20261024-v1.json", "adaptive-20261024-summary.json"):
            path = folder / filename
            if path.exists():
                value = json.loads(path.read_text())
                summary = {key: value[key] for key in (
                    "summary", "config", "status", "limitations", "protected_start", "created_at_utc"
                ) if key in value}
                result.append({"name": filename, "available": True, "summary": summary})
            else:
                result.append({"name": filename, "available": False, "summary": {}})
        return {"reports": result, "interpretation": "Read-only historical experiments. Previously "
                "inspected test cohorts are not independent evidence. No model training or promotion."}

    return router
