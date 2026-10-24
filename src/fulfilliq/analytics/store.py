"""Atomic, provenance-checked analytical snapshots kept outside the source database."""

import json
from datetime import datetime, timezone
from pathlib import Path

from fulfilliq.analytics.operations import numeric_json
from fulfilliq.ingestion.download import write_json
from fulfilliq.modeling.training import dataset_identity

REPORTS = {"operations", "rules", "segments", "anomalies", "reviews"}


class InsightUnavailable(ValueError):
    pass


def save_insight(artifact_dir: Path, name: str, payload: dict, database_path: Path) -> dict:
    if name not in REPORTS:
        raise ValueError("Unknown analytical report")
    value = numeric_json(
        {
            "schema_version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "dataset": dataset_identity(database_path),
            **payload,
        }
    )
    write_json(artifact_dir / "insights" / f"{name}.json", value)
    return value


def load_insight(artifact_dir: Path, name: str, database_path: Path) -> dict:
    if name not in REPORTS:
        raise ValueError("Unknown analytical report")
    try:
        value = json.loads((artifact_dir / "insights" / f"{name}.json").read_text())
        if value["schema_version"] != 1:
            raise ValueError("Incompatible report schema")
        if value["dataset"]["source_sha256"] != dataset_identity(database_path)["source_sha256"]:
            raise ValueError("Database inputs changed; regenerate analytical outputs")
        return value
    except (OSError, ValueError, KeyError) as exc:
        raise InsightUnavailable(
            f"{name} insights unavailable: {exc}. Run 'fulfilliq build-insights'."
        ) from exc
