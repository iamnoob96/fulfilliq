"""Typed public responses; internal report dictionaries never define the HTTP contract."""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ValidationDetail(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ErrorResponse(BaseModel):
    detail: str | list[ValidationDetail]


class Page(BaseModel, Generic[T]):
    total: int
    limit: int
    offset: int
    items: list[T]


class DurationStats(BaseModel):
    count: int
    mean: float | None
    median: float | None
    p90: float | None


class PerformanceRow(BaseModel):
    group: str
    total_orders: int
    eligible_outcomes: int
    excluded_outcomes: int
    late_orders: int
    late_rate: float | None
    durations: dict[str, DurationStats]


class MonthVolume(BaseModel):
    month: str
    orders: int


class OverviewResponse(BaseModel):
    target_definition: str
    total_orders: int
    eligible_outcomes: int
    excluded_outcomes: int
    late_orders: int
    late_rate: float | None
    durations: dict[str, DurationStats]
    status_counts: dict[str, int]
    monthly_volume: list[MonthVolume]


class PerformanceResponse(Page[PerformanceRow]):
    group_by: str
    target_definition: str
    interpretation: str


class BottleneckRow(PerformanceRow):
    longest_median_stage: str | None
    recommendation: str


class BottlenecksResponse(Page[BottleneckRow]):
    group_by: str
    interpretation: str


class AssociationRule(BaseModel):
    antecedents: list[str]
    consequents: list[str]
    support: float
    confidence: float
    lift: float
    leverage: float
    support_count: int


class AlgorithmBenchmark(BaseModel):
    seconds: float
    frequent_itemsets: int


class RulesResponse(Page[AssociationRule]):
    transaction_count: int
    algorithms_agree: bool
    algorithms: dict[str, AlgorithmBenchmark]
    target_definition: str
    interpretation: str


class AnomalyRecord(BaseModel):
    kind: Literal["order", "seller", "region", "seller_fulfillment"]
    entity_id: str
    score: float
    threshold: float
    reasons: list[str]
    region: str | None = None
    eligible_outcomes: int | None = None
    late_orders: int | None = None
    late_rate: float | None = None
    wilson_interval: list[float] | None = None
    observed_features: dict[str, float | None] | None = None


class AnomaliesResponse(Page[AnomalyRecord]):
    method: str
    interpretation: str
    counts: dict[str, int]
    contamination: float


class SellerFeatures(BaseModel):
    order_volume: int
    eligible_outcomes: int
    late_orders: int
    late_rate: float | None
    median_fulfillment_days: float | None
    mean_freight: float | None
    mean_distance_km: float | None
    mean_order_value: float | None
    category_diversity: int
    seller_state: str | None


class SellerSegment(BaseModel):
    seller_id: str
    segment_id: int
    segment_name: str
    features: SellerFeatures


class SegmentSummary(BaseModel):
    segment_id: int
    name: str
    sellers: int
    medoid_seller_id: str
    medians: dict[str, float | None]


class SegmentsResponse(Page[SellerSegment]):
    method: str
    selected_k: int
    silhouette: float
    mean_stability_ari: float
    excluded_low_volume_sellers: int
    segments: list[SegmentSummary]
    interpretation: str


class ReviewGroup(BaseModel):
    group: str
    review_count: int
    text_review_count: int
    complaint_reviews: int
    complaint_fraction_of_text: float | None
    themes: dict[str, int]


class SentimentSummary(BaseModel):
    status: str
    model: str | None = None
    label_source: str | None = None
    unique_texts: int | None = None
    duplicate_texts_excluded: int | None = None
    train_count: int | None = None
    test_count: int | None = None
    split_at: str | None = None
    last_training_review: str | None = None
    accuracy: float | None = None
    majority_baseline_accuracy: float | None = None
    roc_auc: float | None = None
    classification_report: dict[str, dict[str, float] | float] | None = None
    confusion_matrix_negative_positive: list[list[int]] | None = None
    positive_terms: list[str] = Field(default_factory=list)
    negative_terms: list[str] = Field(default_factory=list)
    limitations: str | None = None


class ReviewSummary(BaseModel):
    total_review_records: int
    reviews_with_text: int
    reviews_without_text: int
    theme_counts: dict[str, int]
    theme_keywords: dict[str, list[str]]
    complaint_reviews: int
    sentiment: SentimentSummary


class ReviewsResponse(Page[ReviewGroup]):
    group_by: str
    global_summary: ReviewSummary
    interpretation: str


class SellerInsights(BaseModel):
    seller_id: str
    performance: PerformanceRow | None
    segment: SellerSegment | None
    reviews: ReviewGroup | None
    anomalies: list[AnomalyRecord]
    warnings: list[str]


class CalibrationBin(BaseModel):
    predicted: float
    observed: float


class ReviewBudgetMetrics(BaseModel):
    reviewed_orders: int = Field(ge=1)
    late_orders_captured: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)


class EvaluationMetrics(BaseModel):
    precision: float
    recall: float
    f1: float
    roc_auc: float
    pr_auc_average_precision: float
    brier_score: float
    mean_probability: float | None = Field(default=None, ge=0, le=1)
    review_budgets: dict[str, ReviewBudgetMetrics] = Field(default_factory=dict)
    precision_at_top_10_percent: float
    top_10_percent_count: int
    confusion_matrix: list[list[int]]
    confusion_matrix_order: list[list[str]]
    threshold: float
    samples: int
    late_rate: float
    flagged_fraction: float
    calibration: list[CalibrationBin]


class CandidateMetrics(BaseModel):
    validation: EvaluationMetrics
    test: EvaluationMetrics
    fit_seconds: float


class FeatureImportance(BaseModel):
    feature: str
    average_precision_decrease: float
    std: float


class ModelMetricsResponse(BaseModel):
    model_version: str
    selected_model: str
    threshold: float
    target_definition: str
    comparison: dict[str, CandidateMetrics]
    baselines: dict[str, EvaluationMetrics]
    feature_importance: list[FeatureImportance]
    importance_method: str


class SplitPeriod(BaseModel):
    first_purchase: str
    last_purchase: str
    last_label_available: str
    late_rate: float


class TemporalMetadata(BaseModel):
    validation_start: str
    test_start: str
    observation_cutoff: str
    maturity_days: int
    rule: str
    counts: dict[str, int]
    excluded_unlabeled: int
    purged_or_immature: int
    periods: dict[str, SplitPeriod]


class CalibrationMetadata(BaseModel):
    method: str
    start: str
    base_train_count: int
    calibration_count: int
    base_last_label_available: str


class DatasetIdentity(BaseModel):
    etl_run_id: str
    source_sha256: dict[str, str]


class ModelInfoResponse(BaseModel):
    model_version: str
    created_at_utc: str
    selected_model: str
    selection_metric: str
    threshold_selection: str
    threshold: float
    target_definition: str
    feature_version: int
    features: list[str]
    seed: int
    history_lag_days: int
    history_window_days: int
    split: TemporalMetadata
    calibration: CalibrationMetadata
    dataset: DatasetIdentity
    versions: dict[str, str]
    limitations: list[str]
