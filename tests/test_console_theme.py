"""Check data preservation and accessible content in the shared editorial components."""

import tomllib
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")

from fulfilliq.console import theme


def test_configured_fonts_exist_under_the_console_static_root():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / ".streamlit/config.toml").read_text())
    assert config["server"]["enableStaticServing"]
    console = root / "src/fulfilliq/console"
    for face in config["theme"]["fontFaces"]:
        relative = face["url"].removeprefix("app/")
        assert relative.startswith("static/fonts/")
        assert (console / relative).read_bytes()[:4] == b"\x00\x01\x00\x00"


def test_editorial_charts_preserve_observations_and_units():
    frame = pd.DataFrame({"region": ["RJ", "AL"], "late_rate": [0.1, 0.2]})
    figure = theme.editorial_figure(frame, "region", "late_rate", "Historical late rate")
    assert list(figure.data[0].x) == ["RJ", "AL"]
    assert list(figure.data[0].y) == [0.1, 0.2]
    assert figure.layout.yaxis.tickformat == ".0%"
    assert figure.layout.template.layout.paper_bgcolor == theme.COLORS["background"]
    assert figure.data[0].marker.color == theme.COLORS["accent"]
    assert frame.late_rate.tolist() == [0.1, 0.2]


def test_dynamic_editorial_content_is_escaped(monkeypatch):
    rendered = []
    monkeypatch.setattr(theme.st, "html", rendered.append)
    theme.review_quote("<img src=x onerror=alert(1)>", 1, ["late_delivery"])
    theme.facts({"<script>": "& private text"})
    assert "<img" not in rendered[0] and "&lt;img" in rendered[0]
    assert "<script>" not in rendered[1] and "&lt;script&gt;" in rendered[1]


def test_espresso_text_meets_aa_on_editorial_surfaces():
    def luminance(hex_color):
        channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return sum(v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

    ink = luminance(theme.COLORS["ink"])
    for background in ("background", "surface", "accent", "secondary"):
        assert (luminance(theme.COLORS[background]) + 0.05) / (ink + 0.05) >= 4.5
