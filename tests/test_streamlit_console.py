"""Render the console against a real fixture API without training any model."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fulfilliq.api.main import create_app
from fulfilliq.config import Settings
from fulfilliq.console.client import BackendClient, BackendError
from fulfilliq.ingestion.pipeline import ingest

pytest.importorskip("streamlit", reason="Install the console extra to run UI tests")


@pytest.fixture
def console_backend(raw_dir, tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, artifact_dir=tmp_path / "artifacts", write_token="local")
    ingest(raw_dir, settings.database_path, settings.processed_dir)
    (settings.artifact_dir / "delivery").mkdir(parents=True)
    (settings.artifact_dir / "delivery/current.json").write_text('{"version":"saved-fixture"}')
    api = TestClient(create_app(settings))
    api.application_settings = settings

    def request(_self, method, path, *, params=None, body=None):
        response = api.request(method, path, params=params, json=body,
                               headers={"Authorization": "Bearer local"})
        if response.is_error:
            raise BackendError(str(response.json()), status_code=response.status_code)
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


def test_stale_review_draft_is_not_silently_overwritten(console_backend):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "src/fulfilliq/console/app.py").run(timeout=30)
    app.sidebar.radio[0].set_value("Orders & review queue").run(timeout=30)
    console_backend.put("/api/v1/orders/o6/review", json={"status": "investigating", "notes": "Other session",
                        "expected_revision": 0}, headers={"Authorization": "Bearer local"})
    next(box for box in app.text_area if box.label.startswith("Investigation notes")).set_value("My unsaved draft")
    next(button for button in app.button if button.label == "Save review").click().run(timeout=30)
    assert not app.exception
    assert "Another session" in app.error[0].value
    assert console_backend.get("/api/v1/orders/o6").json()["review"]["notes"] == "Other session"
    assert next(box for box in app.text_area if box.label.startswith("Investigation notes")).value == "My unsaved draft"
    next(button for button in app.button if button.label.startswith("Reload saved review")).click().run(timeout=30)
    assert next(box for box in app.text_area if box.label.startswith("Investigation notes")).value == "Other session"
    next(box for box in app.text_area if box.label.startswith("Investigation notes")).set_value("Merged after reload")
    next(button for button in app.button if button.label == "Save review").click().run(timeout=30)
    assert not app.exception and not app.error
    assert console_backend.get("/api/v1/orders/o6").json()["review"]["revision"] == 2
    app.sidebar.radio[0].set_value("Overview").run(timeout=30)
    app.sidebar.radio[0].set_value("Orders & review queue").run(timeout=30)
    assert next(box for box in app.text_area if box.label.startswith("Investigation notes")).value == "Merged after reload"


def test_scored_page_cache_navigation_capacity_and_filtered_export(console_backend, monkeypatch):
    import io

    import pandas as pd
    from streamlit.testing.v1 import AppTest

    from fulfilliq.console.client import csv_export
    from fulfilliq.modeling.contracts import RiskResponse

    calls, exports = [], []

    def predict(_self, orders):
        calls.append(len(orders))
        return [RiskResponse(order_id=o.order_id, delay_probability=.8 if o.order_id == "o1" else .2,
            threshold=.15, risk_category="high", model_version="saved-fixture", recommendation="Review",
            rationale=[], warnings=["Synthetic fixture"]) for o in orders]

    def export(frame):
        exports.append(frame.copy())
        return csv_export(frame)

    monkeypatch.setattr("fulfilliq.modeling.inference.RiskService.predict", predict)
    monkeypatch.setattr("fulfilliq.console.client.csv_export", export)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "src/fulfilliq/console/app.py").run(timeout=30)
    app.sidebar.radio[0].set_value("Orders & review queue").run(timeout=30)
    next(button for button in app.button if button.label == "Score candidate page").click().run(timeout=30)
    assert not app.exception and not app.error
    assert len(calls) == 1
    next(button for button in app.button if button.label == "Inspect highest-risk match").click().run(timeout=30)
    assert next(box for box in app.selectbox if box.label == "Inspect candidate order").value == "o1"
    app.slider[0].set_value(1).run(timeout=30)
    next(button for button in app.button if button.label == "Score candidate page").click().run(timeout=30)
    assert len(calls) == 1
    app.sidebar.radio[0].set_value("Overview").run(timeout=30)
    app.sidebar.radio[0].set_value("Orders & review queue").run(timeout=30)
    assert app.slider[0].value == 1
    assert next(box for box in app.selectbox if box.label == "Inspect candidate order").value == "o1"
    assert len(calls) == 1
    console_backend.put("/api/v1/orders/o1/review", json={"status": "reviewed", "notes": "Synthetic", "expected_revision": 0},
                        headers={"Authorization": "Bearer local"})
    next(box for box in app.selectbox if box.label == "Scored queue workflow filter").set_value("reviewed").run(timeout=30)
    assert not app.exception and not app.error
    exported = next(frame for frame in reversed(exports) if "delay_probability" in frame)
    assert exported.order_id.tolist() == ["o1"] and exported.review_status.tolist() == ["reviewed"]
    assert pd.read_csv(io.BytesIO(csv_export(exported))).order_id.tolist() == ["o1"]
    assert len(calls) == 1
    next(button for button in app.button if button.label == "Open seller evidence").click().run(timeout=30)
    assert app.sidebar.radio[0].value == "Seller intelligence"
    next(button for button in app.button if button.label == "Find this seller’s orders").click().run(timeout=30)
    assert app.sidebar.radio[0].value == "Orders & review queue"
    assert app.sidebar.selectbox[1].value == "s1"
    app.sidebar.selectbox[1].set_value("All").run(timeout=30)
    assert any(header.value == "Risk-ranked review queue" for header in app.subheader)
    # A changed model manifest cannot reuse scores from the previous version.
    (console_backend.application_settings.artifact_dir / "delivery/current.json").write_text(
        '{"version":"changed-fixture"}')
    app.run(timeout=30)
    assert not any(header.value == "Risk-ranked review queue" for header in app.subheader)


def test_csv_formula_text_is_escaped_without_changing_numeric_values():
    import io

    import pandas as pd

    from fulfilliq.console.client import csv_export

    result = pd.read_csv(io.BytesIO(csv_export(pd.DataFrame({
        "note": ["=SUM(A1:A2)", "+command", "normal"], "amount": [-5, 0, 12]}))))
    assert result.note.tolist() == ["'=SUM(A1:A2)", "'+command", "normal"]
    assert result.amount.tolist() == [-5, 0, 12]


def test_durable_cohort_progress_survives_browser_restart_and_opens_investigation(console_backend, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from fulfilliq.modeling.contracts import RiskResponse
    from fulfilliq.modeling.inference import RiskService
    from fulfilliq.operations.jobs import JobStore

    monkeypatch.setattr(RiskService, "load", lambda _: {"model_version": "saved-fixture"})
    monkeypatch.setattr(RiskService, "predict", lambda _, orders: [RiskResponse(
        order_id=o.order_id, delay_probability=.5, threshold=.4, risk_category="high",
        model_version="saved-fixture", recommendation="Review", rationale=[], warnings=[]) for o in orders])
    entry = Path(__file__).resolve().parents[1] / "src/fulfilliq/console/app.py"
    app = AppTest.from_file(entry).run(timeout=30)
    app.sidebar.radio[0].set_value("Orders & review queue").run(timeout=30)
    next(b for b in app.button if b.label == "Create persistent cohort job").click().run(timeout=30)
    assert not app.exception and not app.error
    store = JobStore(console_backend.application_settings)
    identifier = store.list()["items"][0]["job_id"]
    store.run_once(batch_size=2)
    assert store.get(identifier)["processed_count"] == 2
    # A new browser session discovers the persisted job without prior session state.
    restarted = AppTest.from_file(entry).run(timeout=30)
    restarted.sidebar.radio[0].set_value("Orders & review queue").run(timeout=30)
    assert restarted.session_state["cohort_job"] == identifier
    while store.run_once(batch_size=2):
        pass
    next(b for b in restarted.button if b.label == "Refresh cohort progress").click().run(timeout=30)
    assert any("Complete cohort-wide" in value.value for value in restarted.success)
    next(b for b in restarted.button if b.label == "Investigate cohort order").click().run(timeout=30)
    assert not restarted.exception
    next(box for box in restarted.text_area if box.label.startswith("Investigation notes")).set_value("Synthetic cohort investigation")
    next(b for b in restarted.button if b.label == "Save review").click().run(timeout=30)
    opened = restarted.session_state["cohort_open"][1]
    assert console_backend.get(f"/api/v1/orders/{opened}").json()["review"]["notes"] == "Synthetic cohort investigation"
    assert store.get(identifier)["processed_count"] == 6
