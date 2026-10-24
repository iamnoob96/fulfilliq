"""Local batch commands; all business logic lives outside the command handlers."""

import argparse
import json
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from fulfilliq.analytics.service import logistics_summary
from fulfilliq.config import Settings
from fulfilliq.db.connection import make_engine
from fulfilliq.db.integrity import verify_database
from fulfilliq.ingestion.download import download_dataset
from fulfilliq.ingestion.pipeline import ingest
from fulfilliq.logging_config import configure_logging


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description="FulfillIQ logistics intelligence backend")
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
    train = commands.add_parser("train", help="Train and evaluate chronological delay models")
    train.add_argument("--db-path", type=Path, default=settings.database_path)
    train.add_argument("--artifact-dir", type=Path, default=settings.artifact_dir)
    train.add_argument("--maturity-days", type=int, default=14)
    train.add_argument("--lag-days", type=int, default=1)
    train.add_argument("--history-window-days", type=int, default=180)
    train.add_argument("--as-of", help="Optional source-local observation cutoff timestamp")
    score = commands.add_parser("score", help="Score an order JSON file using the persisted model")
    score.add_argument("--input", type=Path, required=True)
    score.add_argument("--db-path", type=Path, default=settings.database_path)
    score.add_argument("--artifact-dir", type=Path, default=settings.artifact_dir)
    insights = commands.add_parser(
        "build-insights", help="Generate persisted historical intelligence"
    )
    insights.add_argument(
        "--module",
        choices=["all", "operations", "rules", "segments", "anomalies", "reviews"],
        default="all",
    )
    insights.add_argument("--artifact-dir", type=Path, default=settings.artifact_dir)
    insights.add_argument("--data-dir", type=Path, default=settings.data_dir)
    insights.add_argument("--min-support", type=float, default=0.01)
    insights.add_argument("--min-confidence", type=float, default=0.15)
    insights.add_argument("--min-lift", type=float, default=1.1)
    insights.add_argument("--max-length", type=int, default=3)
    insights.add_argument("--min-seller-orders", type=int, default=10)
    insights.add_argument("--contamination", type=float, default=0.02)
    insights.add_argument("--anomaly-min-orders", type=int, default=20)
    report = commands.add_parser(
        "export-report", help="Export small aggregate real experiment results"
    )
    report.add_argument("--output", type=Path, default=Path("docs/results/experiment.json"))
    report.add_argument("--data-dir", type=Path, default=settings.data_dir)
    report.add_argument("--artifact-dir", type=Path, default=settings.artifact_dir)
    args = parser.parse_args(argv)
    configure_logging()
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
        elif args.command == "train":
            from fulfilliq.modeling.training import train_delivery_model

            metadata = train_delivery_model(
                args.db_path,
                args.artifact_dir,
                maturity_days=args.maturity_days,
                lag_days=args.lag_days,
                window_days=args.history_window_days,
                as_of=args.as_of,
            )
            print(
                json.dumps(
                    {
                        "model_version": metadata["model_version"],
                        "selected_model": metadata["selected_model"],
                        "test": metadata["comparison"][metadata["selected_model"]]["test"],
                    },
                    indent=2,
                )
            )
        elif args.command == "score":
            from fulfilliq.modeling.contracts import OrderRequest
            from fulfilliq.modeling.inference import RiskService

            request = OrderRequest.model_validate_json(args.input.read_text())
            prediction = RiskService(args.artifact_dir, args.db_path).predict([request])[0]
            print(prediction.model_dump_json(indent=2))
        elif args.command == "build-insights":
            from fulfilliq.analytics.build import build_insights

            result = build_insights(
                Settings(data_dir=args.data_dir, artifact_dir=args.artifact_dir),
                module=args.module,
                min_support=args.min_support,
                min_confidence=args.min_confidence,
                min_lift=args.min_lift,
                max_length=args.max_length,
                min_seller_orders=args.min_seller_orders,
                contamination=args.contamination,
                anomaly_min_orders=args.anomaly_min_orders,
            )
            print(json.dumps(result, indent=2, allow_nan=False))
        elif args.command == "export-report":
            from fulfilliq.analytics.reporting import export_experiment

            export_experiment(
                Settings(data_dir=args.data_dir, artifact_dir=args.artifact_dir), args.output
            )
            print(f"Aggregate experimental results saved to {args.output}")
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
