import json

from fulfilliq.analytics.build import build_insights
from fulfilliq.cli import main
from fulfilliq.config import Settings
from fulfilliq.ingestion.pipeline import ingest


def test_individual_batch_modules_and_cli(raw_dir, tmp_path, capsys):
    settings = Settings(data_dir=tmp_path, artifact_dir=tmp_path / "artifacts")
    ingest(raw_dir, settings.database_path, settings.processed_dir)
    operations = build_insights(settings, module="operations")
    assert operations["operations"]["total_orders"] == 6
    reviews = build_insights(settings, module="reviews")
    assert reviews["reviews"]["reviews_with_text"] == 3
    assert (
        main(
            [
                "build-insights",
                "--data-dir",
                str(tmp_path),
                "--artifact-dir",
                str(settings.artifact_dir),
                "--module",
                "rules",
                "--min-support",
                ".1",
            ]
        )
        == 0
    )
    assert "rules" in json.loads(capsys.readouterr().out)
