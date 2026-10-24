"""Trust-boundary validation and deterministic, reported cleaning decisions."""

import csv
import hashlib
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import DateTime, Float, Integer

from fulfilliq.db.schema import SourceSpec


class DataValidationError(ValueError):
    """A source cannot be ingested without losing relational meaning."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_header(path: Path, spec: SourceSpec) -> None:
    if not path.is_file():
        raise DataValidationError(f"Missing file: {path.name}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream), [])
    except (UnicodeError, csv.Error) as exc:
        raise DataValidationError(f"{path.name}: invalid UTF-8 CSV header") from exc
    missing = sorted(set(spec.columns) - set(header))
    if missing or len(header) != len(set(header)):
        raise DataValidationError(f"{path.name}: missing columns {missing}; headers must be unique")


def load_source(path: Path, spec: SourceSpec) -> tuple[pd.DataFrame, dict[str, Any]]:
    validate_header(path, spec)
    try:
        # Otherwise Pandas can infer an index from excess fields or discard them silently.
        with warnings.catch_warnings():
            warnings.simplefilter("error", pd.errors.ParserWarning)
            frame = pd.read_csv(
                path,
                dtype=str,
                keep_default_na=False,
                na_values=[""],
                encoding="utf-8-sig",
                index_col=False,
            )
    except (ValueError, UnicodeError, pd.errors.ParserError, pd.errors.ParserWarning) as exc:
        raise DataValidationError(f"{path.name}: cannot parse CSV: {exc}") from exc
    if frame.empty:
        raise DataValidationError(f"{path.name}: source table is empty")
    report: dict[str, Any] = {
        "filename": path.name,
        "sha256": sha256_file(path),
        "input_rows": len(frame),
        "ignored_extra_columns": sorted(set(frame.columns) - set(spec.columns)),
        "input_missing": {c: int(frame[c].isna().sum()) for c in spec.columns},
        "invalid_to_null": {},
    }
    # Compare original source columns before coercion to avoid merging distinct bad records.
    frame = frame[spec.columns].drop_duplicates().copy()
    report["exact_duplicates_removed"] = report["input_rows"] - len(frame)

    for column in spec.table.columns:
        name = column.name
        if name not in frame:
            continue
        values = frame[name]
        if isinstance(column.type, DateTime):
            converted = pd.to_datetime(values, format="%Y-%m-%d %H:%M:%S", errors="coerce")
        elif isinstance(column.type, (Integer, Float)):
            converted = pd.to_numeric(values, errors="coerce")
            invalid = ~np.isfinite(converted) | (converted < 0)
            if isinstance(column.type, Integer):
                invalid |= converted.mod(1).ne(0)
                invalid |= converted >= 2**63
            if name in {"order_item_id", "payment_sequential"}:
                invalid |= converted < 1
            if name == "review_score":
                invalid |= ~converted.between(1, 5)
            # Geographic coordinates may legitimately be negative.
            if name == "geolocation_lat":
                invalid = ~converted.between(-90, 90)
            elif name == "geolocation_lng":
                invalid = ~converted.between(-180, 180)
            converted = converted.mask(invalid)
            if isinstance(column.type, Integer):
                converted = converted.astype("Int64")
        else:
            # Preserve nonempty strings, including leading zeros and Portuguese review text.
            converted = values.mask(values.fillna("").str.strip().eq(""))
        report["invalid_to_null"][name] = int((values.notna() & converted.isna()).sum())
        frame[name] = converted
        if not column.nullable and converted.isna().any():
            raise DataValidationError(f"{path.name}: missing/invalid required key or field {name}")

    keys = [c.name for c in spec.table.primary_key.columns if c.name in frame]
    if keys and frame.duplicated(keys).any():
        raise DataValidationError(f"{path.name}: conflicting duplicate primary key {keys}")
    report["loaded_rows"] = len(frame)
    report["output_missing"] = {c: int(frame[c].isna().sum()) for c in spec.columns}
    return frame, report
