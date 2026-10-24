"""Reproducible batch generation; API readers only consume finished reports."""

import logging

from fulfilliq.analytics.operations import OperationsService
from fulfilliq.analytics.store import save_insight
from fulfilliq.config import Settings
from fulfilliq.features.orders import build_dataset
from fulfilliq.mining.anomalies import detect_anomalies
from fulfilliq.mining.patterns import mine_patterns
from fulfilliq.mining.segments import segment_sellers, seller_features
from fulfilliq.nlp.reviews import analyze_reviews

logger = logging.getLogger(__name__)


def build_insights(
    settings: Settings,
    *,
    module: str = "all",
    min_support: float = 0.01,
    min_confidence: float = 0.15,
    min_lift: float = 1.1,
    max_length: int = 3,
    min_seller_orders: int = 10,
    contamination: float = 0.02,
    anomaly_min_orders: int = 20,
) -> dict:
    if module not in {"all", "operations", "rules", "segments", "anomalies", "reviews"}:
        raise ValueError("Unknown insight module")
    summaries = {}
    if module in {"all", "operations"}:
        service = OperationsService(settings.database_path)
        result = save_insight(
            settings.artifact_dir,
            "operations",
            {
                "overview": service.overview(),
                "seller_performance": service.performance("seller"),
                "category_performance": service.performance("category"),
                "region_performance": service.performance("region"),
                "bottlenecks": service.bottlenecks("region"),
            },
            settings.database_path,
        )
        summaries["operations"] = result["overview"]
        logger.info("Generated historical operational analytics")
        del service
    if module in {"all", "rules", "segments", "anomalies"}:
        frame, _, orders, items = build_dataset(settings.database_path)
        sellers = seller_features(orders, items)
        if module in {"all", "rules"}:
            result = save_insight(
                settings.artifact_dir,
                "rules",
                mine_patterns(
                    frame,
                    min_support=min_support,
                    min_confidence=min_confidence,
                    min_lift=min_lift,
                    max_length=max_length,
                ),
                settings.database_path,
            )
            summaries["rules"] = {"rules": len(result["rules"]), "algorithms": result["algorithms"]}
            logger.info("Generated %s delay association rules", len(result["rules"]))
        if module in {"all", "segments"}:
            result = save_insight(
                settings.artifact_dir,
                "segments",
                segment_sellers(sellers, min_orders=min_seller_orders),
                settings.database_path,
            )
            summaries["segments"] = {
                name: result[name]
                for name in (
                    "selected_k",
                    "silhouette",
                    "mean_stability_ari",
                    "excluded_low_volume_sellers",
                )
            }
            logger.info("Generated %s seller segments", result["selected_k"])
        if module in {"all", "anomalies"}:
            result = save_insight(
                settings.artifact_dir,
                "anomalies",
                detect_anomalies(
                    frame, sellers, contamination=contamination, min_orders=anomaly_min_orders
                ),
                settings.database_path,
            )
            summaries["anomalies"] = result["counts"]
            logger.info("Generated historical anomaly screens: %s", result["counts"])
        del frame, orders, items, sellers
    if module in {"all", "reviews"}:
        result = save_insight(
            settings.artifact_dir,
            "reviews",
            analyze_reviews(settings.database_path, settings.artifact_dir),
            settings.database_path,
        )
        summaries["reviews"] = {
            "reviews_with_text": result["reviews_with_text"],
            "theme_counts": result["theme_counts"],
            "sentiment": result["sentiment"],
        }
        logger.info("Generated Portuguese review intelligence")
    return summaries
