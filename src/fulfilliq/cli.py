"""Local batch commands; all business logic lives outside the command handlers."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

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
    experiment = commands.add_parser(
        "experiment-risk", help="Run frozen, bounded risk challenger comparison"
    )
    experiment.add_argument("--db-path", type=Path, default=settings.database_path)
    experiment.add_argument("--artifact-dir", type=Path, default=settings.artifact_dir)
    experiment.add_argument("--output", type=Path, required=True)
    experiment.add_argument(
        "--promote-if-qualified",
        action="store_true",
        help="Activate only if every preregistered validation/test gate passes",
    )
    temporal = commands.add_parser(
        "evaluate-temporal", help="Backtest rolling calibration policies without promotion"
    )
    temporal.add_argument("--db-path", type=Path, default=settings.database_path)
    temporal.add_argument("--artifact-dir", type=Path, default=settings.artifact_dir)
    temporal.add_argument(
        "--output", type=Path, help="New JSON path; a Markdown summary is saved alongside"
    )
    from fulfilliq.modeling.rolling import RollingConfig

    for name, default in vars(RollingConfig()).items():
        temporal.add_argument("--" + name.replace("_", "-"), type=int, default=default)
    adaptive = commands.add_parser(
        "evaluate-adaptive-calibration",
        help="Run nested historical recency-calibration selection without promotion",
    )
    adaptive.add_argument("--db-path", type=Path, default=settings.database_path)
    adaptive.add_argument("--artifact-dir", type=Path, default=settings.artifact_dir)
    adaptive.add_argument("--output", type=Path)
    for name, default in vars(RollingConfig()).items():
        if not name.startswith("isotonic_"):
            adaptive.add_argument("--" + name.replace("_", "-"), type=int, default=default)
    adaptive.add_argument("--half-lives", type=int, nargs="*", default=[30, 60, 90, 180])
    adaptive.add_argument("--observation-windows", type=int, nargs="*", default=[30, 60])
    adaptive.add_argument("--min-inner-folds", type=int, default=3)
    adaptive.add_argument("--max-inner-folds", type=int, default=3)
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
        elif args.command == "experiment-risk":
            from fulfilliq.modeling.experiment import run_risk_experiment

            report = run_risk_experiment(
                args.db_path,
                args.artifact_dir,
                args.output,
                promote_if_qualified=args.promote_if_qualified,
            )
            print(
                json.dumps(
                    {
                        key: report[key]
                        for key in (
                            "selected_challenger",
                            "qualified",
                            "promoted",
                            "promotion_checks",
                        )
                    },
                    indent=2,
                )
            )
        elif args.command == "evaluate-temporal":
            from fulfilliq.modeling.temporal_evaluation import run_temporal_evaluation

            config = RollingConfig(**{name: getattr(args, name) for name in vars(RollingConfig())})
            output = args.output or args.artifact_dir / "temporal" / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                + "-"
                + uuid4().hex[:8]
                + ".json"
            )
            report = run_temporal_evaluation(args.db_path, args.artifact_dir, output, config)
            print(output.with_suffix(".md").read_text())
            print(f"Structured report: {output}")
            return 0 if report["status"] == "complete" else 1
        elif args.command == "evaluate-adaptive-calibration":
            from fulfilliq.modeling.adaptive_evaluation import run_adaptive_evaluation

            config = RollingConfig(
                **{
                    name: getattr(args, name, default)
                    for name, default in vars(RollingConfig()).items()
                }
            )
            output = args.output or args.artifact_dir / "adaptive" / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                + "-"
                + uuid4().hex[:8]
                + ".json"
            )
            report = run_adaptive_evaluation(
                args.db_path,
                args.artifact_dir,
                output,
                config,
                half_lives=tuple(args.half_lives),
                windows=tuple(args.observation_windows),
                min_inner_folds=args.min_inner_folds,
                max_inner_folds=args.max_inner_folds,
            )
            print(output.with_suffix(".md").read_text())
            print(f"Structured report: {output}")
            return 0 if report["status"] == "complete" else 1
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
