"""Opt-in real-data application rendering; HTTP FastAPI plus Streamlit's test harness."""

import json
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fulfilliq.console.client import BackendClient

client = BackendClient()
entry = Path(__file__).resolve().parents[1] / "src/fulfilliq/console/app.py"
app = AppTest.from_file(entry).run(timeout=120)
assert not app.exception and not app.error, (app.exception, app.error)
assert app.metric[0].value == "99,441"
pages = list(app.sidebar.radio[0].options)
verified = []
for page in pages:
    app.sidebar.radio[0].set_value(page).run(timeout=120)
    assert not app.exception and not app.error, (page, app.exception, app.error)
    if page == "Orders & review queue":
        next(button for button in app.button if button.label == "Score candidate page").click().run(timeout=120)
        assert not app.exception and not app.error, (page, app.exception, app.error)
        runs = list(app.session_state["scored_pages"].values())
        assert len(runs) == 1 and runs[0]["scored_count"] > 0
        assert runs[0]["candidate_count"] == 50 and runs[0]["scored_at_utc"]
        scored = runs[0]["scored_count"]
    verified.append(page)
print(json.dumps({"pages_rendered": verified, "historical_orders": 99441,
                  "candidate_predictions": scored, "r_available": client.get("/reports/r")["available"]}, indent=2))
