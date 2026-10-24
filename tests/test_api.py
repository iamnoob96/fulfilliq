from fastapi.testclient import TestClient

from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.ingestion.pipeline import ingest


def test_health_before_ingestion_does_not_create_database(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["database"] == "missing"
        assert not settings.database_path.exists()
        schema = client.get("/openapi.json").json()
        assert set(schema["paths"]) == {"/health"}
        assert "503" in schema["paths"]["/health"]["get"]["responses"]


def test_health_after_ingestion(raw_dir, tmp_path):
    settings = Settings(data_dir=tmp_path)
    ingest(raw_dir, settings.database_path, settings.processed_dir)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "FulfillIQ",
            "version": "0.1.0",
            "database": "ready",
        }


def test_corrupt_database_reports_invalid(tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.processed_dir.mkdir()
    settings.database_path.write_text("not SQLite")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["database"] == "invalid"


def test_readonly_database_path_with_spaces_and_special_characters(raw_dir, tmp_path):
    settings = Settings(data_dir=tmp_path / "space # ? data")
    ingest(raw_dir, settings.database_path, settings.processed_dir)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
