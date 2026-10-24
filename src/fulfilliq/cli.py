"""Local batch commands; all business logic lives outside the command handlers."""

import argparse
import json
import logging
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from fulfilliq.analytics.service import logistics_summary
from fulfilliq.config import Settings
from fulfilliq.db.connection import make_engine
from fulfilliq.db.integrity import verify_database
from fulfilliq.ingestion.download import download_dataset
from fulfilliq.ingestion.pipeline import ingest


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description="FulfillIQ Phase 1 data foundation")
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download", help="Download the nine original public CSVs")
    download.add_argument("--raw-dir", type=Path, default=settings.raw_dir)
    download.add_argument("--force", action="store_true", help="Replace existing CSVs explicitly")
    ingestion = commands.add_parser("ingest", help="Validate and rebuild the local SQLite snapshot")
    ingestion.add_argument("--raw-dir", type=Path, default=settings.raw_dir)
    ingestion.add_argument("--db-path", type=Path, default=settings.database_path)
    ingestion.add_argument("--report-dir", type=Path, default=settings.processed_dir)
    for name in ("verify", "stats"):
        command = commands.add_parser(name, help=f"Read local database {name}")
        command.add_argument("--db-path", type=Path, default=settings.database_path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if args.command == "download":
            result = download_dataset(args.raw_dir, force=args.force)
            print(f"Validated {len(result['files'])} CSVs in {args.raw_dir}")
        elif args.command == "ingest":
            report = ingest(args.raw_dir, args.db_path, args.report_dir)
            print(
                json.dumps(
                    {
                        "status": report["status"],
                        "row_counts": report["verification"]["row_counts"],
                    },
                    indent=2,
                )
            )
        else:
            engine = make_engine(args.db_path, readonly=True)
            try:
                with engine.connect() as connection:
                    result = (
                        verify_database(connection)
                        if args.command == "verify"
                        else logistics_summary(connection)
                    )
                print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
            finally:
                engine.dispose()
        return 0
    except (OSError, ValueError, SQLAlchemyError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
