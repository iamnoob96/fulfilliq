"""Persistent jobs enqueue work only; inference runs in the local worker."""

import csv
import io
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fulfilliq.analytics.operations import CohortFilter
from fulfilliq.api.console_routes import write_access
from fulfilliq.api.console_schemas import DeliveryOutcome, OrderStatus
from fulfilliq.api.intelligence_schemas import Page
from fulfilliq.config import Settings
from fulfilliq.modeling.contracts import RiskResponse
from fulfilliq.modeling.inference import ModelUnavailable
from fulfilliq.operations.jobs import JobStore
from fulfilliq.operations.reviews import ReviewStatus


class JobFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seller_id: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    product_category: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    order_status: OrderStatus | None = None
    delivery_outcome: DeliveryOutcome | None = None
    review_status: ReviewStatus | None = None

    @model_validator(mode="after")
    def dates(self):
        CohortFilter(start_date=self.start_date, end_date=self.end_date)
        return self


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: JobFilters
    review_capacity: int = Field(default=20, ge=0, le=5000, strict=True)


class ScoringJob(BaseModel):
    job_id: str
    filters: JobFilters
    status: Literal["pending", "running", "completed", "failed", "canceled", "stale"]
    created_at_utc: str
    updated_at_utc: str
    completed_at_utc: str | None
    candidate_count: int
    processed_count: int
    scored_count: int
    unavailable_count: int
    model_version: str
    warehouse_snapshot: str
    review_capacity: int
    error_summary: str | None
    ranking_complete: bool
    retrospective_selection: bool


class ScoringResult(BaseModel):
    order_id: str
    candidate_sequence: int
    eligibility: Literal["scored", "unavailable"]
    delay_probability: float | None = Field(ge=0, le=1)
    prediction: RiskResponse | None
    unavailable_reason: str | None
    processed_at_utc: str
    model_version: str
    review_status: ReviewStatus
    rank: int | None
    within_review_capacity: bool


class JobResults(Page[ScoringResult]):
    job: ScoringJob
    review_capacity: int
    interpretation: str


class JobsResponse(Page[ScoringJob]):
    max_cohort_size: int


def scoring_router(settings: Settings):
    router = APIRouter(prefix="/api/v1/scoring-jobs", tags=["Cohort scoring"],
                       responses={404: {"description": "Job not found"}, 409: {"description": "Job state conflict"}})
    store = JobStore(settings)
    access = Depends(write_access(settings))

    @router.post("", response_model=ScoringJob, status_code=201, dependencies=[access])
    def create(request: JobRequest):
        if request.review_capacity > settings.scoring_max_orders:
            raise ValueError("Review capacity exceeds the configured cohort limit")
        try:
            return store.create(request.filters.model_dump(), request.review_capacity)
        except ModelUnavailable as exc:
            raise HTTPException(503, "Compatible saved model unavailable; restore existing artifacts before creating a job.") from exc

    @router.get("", response_model=JobsResponse)
    def jobs(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        return {**store.list(limit, offset), "max_cohort_size": settings.scoring_max_orders}

    @router.get("/{job_id}", response_model=ScoringJob)
    def job(job_id: str):
        return store.get(job_id)

    @router.post("/{job_id}/cancel", response_model=ScoringJob, dependencies=[access])
    def cancel(job_id: str):
        store.transition(job_id, "canceled")
        return store.get(job_id)

    @router.post("/{job_id}/resume", response_model=ScoringJob, dependencies=[access])
    def resume(job_id: str):
        try:
            return store.resume(job_id)
        except ModelUnavailable as exc:
            raise HTTPException(503, "Recorded saved model unavailable; restore it before resuming.") from exc

    @router.get("/{job_id}/results", response_model=JobResults)
    def results(job_id: str, capacity: int | None = Query(default=None, ge=0, le=5000),
                limit: int = Query(default=100, ge=1, le=100), offset: int = Query(default=0, ge=0),
                review_status: ReviewStatus | None = None, include_unavailable: bool = False):
        return store.results(job_id, capacity=capacity, limit=limit, offset=offset,
                             review_status=review_status, include_unavailable=include_unavailable)

    @router.get("/{job_id}/export.csv", response_class=Response)
    def export(job_id: str, capacity: int | None = Query(default=None, ge=0, le=5000),
               review_status: ReviewStatus | None = None, include_unavailable: bool = False):
        report = store.results(job_id, capacity=capacity, limit=settings.scoring_max_orders,
                               review_status=review_status, include_unavailable=include_unavailable)
        fields = ["order_id", "rank", "eligibility", "delay_probability", "model_version", "review_status",
                  "within_review_capacity", "unavailable_reason", "processed_at_utc"]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in report["items"]:
            writer.writerow({key: "'" + value if isinstance(value := row.get(key), str)
                             and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for key in fields})
        return Response(stream.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="cohort-ranking.csv"',
            "X-Ranking-Complete": str(report["job"]["ranking_complete"]).lower()})

    return router
