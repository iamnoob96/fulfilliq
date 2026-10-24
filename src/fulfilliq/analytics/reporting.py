"""Export small aggregate experiment results, never individual orders or reviews."""

from pathlib import Path

from fulfilliq.analytics.store import load_insight
from fulfilliq.config import Settings
from fulfilliq.ingestion.download import write_json
from fulfilliq.modeling.inference import RiskService


def export_experiment(settings: Settings, output: Path) -> dict:
    metadata = RiskService(settings.artifact_dir, settings.database_path).load()
    reports = {
        name: load_insight(settings.artifact_dir, name, settings.database_path)
        for name in ("operations", "rules", "segments", "anomalies", "reviews")
    }
    result = {
        "dataset": metadata["dataset"],
        "model": metadata,
        "operations": reports["operations"]["overview"],
        "rules": {
            key: reports["rules"][key]
            for key in (
                "transaction_count",
                "parameters",
                "algorithms",
                "algorithms_agree",
                "interpretation",
            )
        },
        "seller_segments": {
            key: reports["segments"][key]
            for key in (
                "selected_k",
                "silhouette",
                "kmeans_euclidean_silhouette",
                "mean_stability_ari",
                "stability_80_percent_resample_ari",
                "excluded_low_volume_sellers",
                "interpretation",
            )
        },
        "anomalies": {
            key: reports["anomalies"][key]
            for key in (
                "counts",
                "reference_order_count",
                "contamination",
                "min_orders",
                "interpretation",
            )
        },
        "reviews": {
            key: reports["reviews"][key]
            for key in (
                "total_review_records",
                "reviews_with_text",
                "reviews_without_text",
                "theme_counts",
                "complaint_reviews",
                "sentiment",
                "interpretation",
            )
        },
    }
    result["rules"]["top_rules"] = reports["rules"]["rules"][:10]
    result["seller_segments"]["segmented_sellers"] = len(reports["segments"]["assignments"])
    result["seller_segments"]["profiles"] = [
        {key: profile[key] for key in ("segment_id", "name", "sellers", "medians")}
        for profile in reports["segments"]["segments"]
    ]
    selected = metadata["comparison"][metadata["selected_model"]]["test"]
    result["model_assessment"] = {
        "top_decile_lift_over_test_prevalence": selected["precision_at_top_10_percent"]
        / selected["late_rate"],
        "brier_beats_prevalence_baseline": selected["brier_score"]
        < metadata["baselines"]["training_prevalence"]["brier_score"],
        "benchmark_status": "Exploratory chronological experiment; test diagnostics were seen during engineering",
        "production_ready": False,
    }
    write_json(output, result)
    return result
