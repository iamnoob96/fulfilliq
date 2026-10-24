"""Reproducible reports use the same services and filters as the dashboard."""

from dataclasses import asdict

from fulfilliq.analytics.operations import CohortFilter, OperationsService
from fulfilliq.analytics.store import InsightUnavailable, load_insight
from fulfilliq.config import Settings

LIMITATIONS = [
    "Historical Olist data (2016–2018), not current live logistics performance.",
    "Late means actual delivery timestamp > promised timestamp for valid delivered orders. "
    "Missing/invalid/unresolved outcomes are excluded from rates. The original mart's is_late "
    "uses calendar days; operational APIs consistently use the documented exact-time target.",
    "Seller/category groups overlap for multi-seller/item orders and are not additive.",
    "Mining and review snapshots cover full history; cohort filters apply to operational tables only.",
    "Associations and anomaly scores do not establish causes, fraud or intervention benefits.",
    "Saved risk model calibration is weak; historical replay is demonstration, not independent validation.",
]


def operational_report(settings: Settings, filters: CohortFilter) -> dict:
    service = OperationsService(settings.database_path)
    overview = service.overview(filters)
    result = {
        "filters": {k: str(v) if v is not None else None for k, v in asdict(filters).items()},
        "overview": overview,
        "regions": service.performance("region", filters),
        "sellers": service.performance("seller", filters, min_orders=5)[:50],
        "bottlenecks": service.bottlenecks("region", filters, min_orders=5)["items"],
        "rules": [], "limitations": list(LIMITATIONS),
    }
    try:
        rules = load_insight(settings.artifact_dir, "rules", settings.database_path)
        result["rules"] = rules["rules"][:20]
        result["mining_created_at_utc"] = rules["created_at_utc"]
    except InsightUnavailable as exc:
        result["limitations"].append(str(exc))
    # No wall-clock timestamp in report body: identical inputs give identical output.
    lines = ["# FulfillIQ historical operations report", "", "## Selected cohort", "",
             *[f"- {key}: {value or 'all'}" for key, value in result["filters"].items()], "",
             f"Orders: {overview['total_orders']}; eligible outcomes: {overview['eligible_outcomes']}; "
             f"late orders: {overview['late_orders']}; excluded: {overview['excluded_outcomes']}.", ""]
    for title, rows in (("Regional performance", result["regions"]),
                        ("Seller performance (minimum 5 orders; top 50 by late rate)", result["sellers"])):
        lines += [f"## {title}", "", "| Group | Orders | Late rate |", "|---|---:|---:|"]
        lines += [f"| {row['group']} | {row['total_orders']} | "
                  + (f"{row['late_rate']:.2%}" if row["late_rate"] is not None else "unavailable") + " |"
                  for row in rows]
        lines += [""]
    lines += ["## Bottlenecks", ""] + [
        f"- {row['group']}: longest observed median stage {row['longest_median_stage'] or 'unavailable'}."
        for row in result["bottlenecks"]]
    lines += ["", "## Full-history association findings", ""] + [
        f"- {', '.join(row['antecedents'])} → late: support {row['support']:.4f}, "
        f"confidence {row['confidence']:.4f}, lift {row['lift']:.3f}." for row in result["rules"]]
    lines += ["", "## Limitations", ""] + [f"- {value}" for value in result["limitations"]]
    return {**result, "markdown": "\n".join(lines) + "\n"}
