"""Build a complete validated snapshot before replacing an existing database."""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from fulfilliq.analytics.service import logistics_summary, relationship_checks
from fulfilliq.db.connection import make_engine
from fulfilliq.db.integrity import verify_database
from fulfilliq.db.mart import SCHEMA_VERSION, build_mart
from fulfilliq.db.schema import SOURCES, metadata
from fulfilliq.ingestion.download import write_json
from fulfilliq.ingestion.validation import DataValidationError, load_source, validate_header

logger = logging.getLogger(__name__)


def ingest(raw_dir: Path, database_path: Path, report_dir: Path) -> dict[str, Any]:
    """One writer at a time. Raw inputs and previous successful snapshots stay intact."""
    raw_dir, database_path, report_dir = (
        path.resolve() for path in (raw_dir, database_path, report_dir)
    )
    source_paths = {(raw_dir / spec.filename).resolve() for spec in SOURCES}
    output_paths = {database_path} | {
        report_dir / name
        for name in ("data_quality.json", "logistics_summary.json", "ingestion_failure.json")
    }
    if source_paths & output_paths or database_path in {
        report_dir / name
        for name in ("data_quality.json", "logistics_summary.json", "ingestion_failure.json")
    }:
        raise DataValidationError("Database/report paths must not overwrite CSVs or each other")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    # The lock covers a whole rebuild, including final report exports.
    lock_path = database_path.with_name(f".{database_path.name}.ingest.lock")
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise DataValidationError(
            f"Ingestion is already running (or a crashed run left {lock_path}); "
            "remove a stale lock only after confirming no ingest process is active"
        ) from exc
    os.close(descriptor)
    temporary: Path | None = None
    engine = None
    published = False
    report: dict[str, Any] = {
        "run_id": str(uuid4()),
        "schema_version": SCHEMA_VERSION,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "tables": {},
    }
    try:
        errors = []
        for spec in SOURCES:
            try:
                validate_header(raw_dir / spec.filename, spec)
            except DataValidationError as exc:
                errors.append(str(exc))
        if errors:
            raise DataValidationError("Source validation failed:\n" + "\n".join(errors))
        descriptor, name = tempfile.mkstemp(
            prefix=f".{database_path.name}.", suffix=".staging", dir=database_path.parent
        )
        os.close(descriptor)
        temporary = Path(name)
        engine = make_engine(temporary)
        with engine.begin() as connection:
            metadata.create_all(connection)
            for spec in SOURCES:
                frame, table_report = load_source(raw_dir / spec.filename, spec)
                report["tables"][spec.table.name] = table_report
                try:
                    frame.to_sql(
                        spec.table.name, connection, if_exists="append", index=False, chunksize=2000
                    )
                except IntegrityError as exc:
                    # Do not print row payloads (including review text) from SQLAlchemy errors.
                    raise DataValidationError(
                        f"{spec.filename}: relational constraint failed: {exc.orig}"
                    ) from exc
                logger.info("Loaded %s: %s rows", spec.table.name, len(frame))
                del frame
            build_mart(connection)
            report["relationship_checks"] = relationship_checks(connection)
            summary = logistics_summary(connection)
            # Insert a placeholder run before checking all row counts; update within this transaction.
            completed = datetime.now(timezone.utc).isoformat()
            connection.execute(
                text("""
                INSERT INTO etl_runs VALUES (:run_id, :version, :completed, '{}', '{}')
            """),
                {"run_id": report["run_id"], "version": SCHEMA_VERSION, "completed": completed},
            )
            report["verification"] = verify_database(connection)
            for spec in SOURCES:
                if (
                    report["tables"][spec.table.name]["loaded_rows"]
                    != (report["verification"]["row_counts"][spec.table.name])
                ):
                    raise DataValidationError(f"Inserted count mismatch for {spec.table.name}")
            report.update(status="success", completed_at_utc=completed)
            summary["run_id"] = report["run_id"]
            connection.execute(
                text("""
                UPDATE etl_runs SET quality_json=:quality, summary_json=:summary WHERE run_id=:run_id
            """),
                {
                    "quality": json.dumps(report, allow_nan=False),
                    "summary": json.dumps(summary, allow_nan=False),
                    "run_id": report["run_id"],
                },
            )
        engine.dispose()
        engine = None
        os.replace(temporary, database_path)
        published = True
        # Canonical reports are committed in etl_runs; exports can be recovered from that row.
        write_json(report_dir / "data_quality.json", report)
        write_json(report_dir / "logistics_summary.json", summary)
        (report_dir / "ingestion_failure.json").unlink(missing_ok=True)
        return report
    except Exception as exc:
        report.update(status="failed", error=str(exc), database_published=published)
        try:
            write_json(report_dir / "ingestion_failure.json", report)
        except OSError:
            logger.error("Could not write ingestion_failure.json")
        if published:
            logger.error("Database is valid and published; report export failed. Read etl_runs.")
        raise
    finally:
        if engine is not None:
            engine.dispose()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
            Path(f"{temporary}-journal").unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)
