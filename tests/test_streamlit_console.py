"""Render the console against a real fixture API without training any model."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.console.client import BackendClient, BackendError
from fulfilliq.ingestion.pipeline import ingest


@pytest.fixture
def console_backend(raw_dir, tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, artifact_dir=tmp_path / "artifacts", write_token="local")
    ingest(raw_dir, settings.database_path, settings.processed_dir)
    api = TestClient(create_app(settings))

    def request(_self, method, path, *, params=None, body=None):
        response = api.request(method, path, params=params, json=body,
                               headers={"Authorization": "Bearer local"})
        if response.is_error:
            raise BackendError(str(response.json()))
        return response.json()

    monkeypatch.setattr(BackendClient, "request", request)
    return api


def test_overview_and_review_console_render_and_save(console_backend):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "src/fulfilliq/console/app.py").run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "6"
    app.sidebar.radio[0].set_value("Orders & review queue").run(timeout=30)
    assert not app.exception
    assert "pending" in [box.value for box in app.selectbox]
    status = next(box for box in app.selectbox if box.label == "Investigation status")
    status.set_value("escalated")
    next(box for box in app.text_area if box.label.startswith("Investigation notes")).set_value("Needs milestone review")
    next(button for button in app.button if button.label == "Save review").click().run(timeout=30)
    assert not app.exception
    assert app.success
    assert console_backend.get("/api/v1/orders/o6").json()["review"]["status"] == "escalated"


def test_console_handles_missing_dependency_and_backend(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def unavailable(*args, **kwargs):
        raise BackendError("Backend unavailable for this test")

    monkeypatch.setattr(BackendClient, "get", unavailable)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "src/fulfilliq/console/app.py").run(timeout=30)
    assert not app.exception
    assert "unavailable" in app.error[0].value
