"""Editorial design tokens, safe content components and a shared Plotly style."""

from html import escape

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

COLORS = {
    "accent": "#DC6D18",
    "background": "#FFF4E4",
    "surface": "#F8E0C9",
    "ink": "#2B1A12",
    "secondary": "#B1AA81",
}
SERIF = 'Fraunces, Georgia, "Times New Roman", serif'
SANS = '"DM Sans", "Avenir Next", system-ui, sans-serif'
MONO = '"IBM Plex Mono", Menlo, monospace'

PAGES = {
    "Overview": (
        "01",
        "The State of Fulfillment.",
        "An editorial view of e-commerce logistics, delivery performance, and operational intelligence.",
    ),
    "Orders & review queue": (
        "02",
        "Every Order Tells a Story.",
        "Discover a cohort. Prioritize delivery risks. Record the evidence and the next step.",
    ),
    "Logistics": (
        "03",
        "Where Deliveries Slow Down.",
        "Follow the journey from purchase to delivery, and examine the stages that warrant investigation.",
    ),
    "Seller intelligence": (
        "04",
        "Behind Every Delivery.",
        "Seller profiles, measured peer groups, and the historical evidence behind fulfillment.",
    ),
    "Data mining": (
        "05",
        "Patterns Beneath the Surface.",
        "Explore recurring associations, seller groups, and unusual logistics patterns in the Olist archive.",
    ),
    "Review intelligence": (
        "06",
        "What Customers Are Saying.",
        "Read the signals in Portuguese reviews: delivery themes, customer satisfaction, and their limits.",
    ),
    "Model evaluation": (
        "07",
        "Behind the Prediction.",
        "A transparent evidence section for saved delivery-risk models, calibration, and temporal uncertainty.",
    ),
    "Reports & R": (
        "08",
        "The Findings, Documented.",
        "A research archive of operational reports, reproducible exports, and independent R comparisons.",
    ),
}

CSS = """
html { scroll-behavior: smooth; }
.stApp { background: var(--color-background); color: var(--color-ink); font-family: var(--sans); }
[data-testid="stHeader"] { background: var(--color-background); }
[data-testid="stMainBlockContainer"] { max-width: 1480px; padding: 4.3rem 3.4rem 3rem; }
[data-testid="stSidebar"] { border-right: 1px solid var(--line); }
[data-testid="stSidebarContent"] { padding: 1.7rem 1.1rem; }
[data-testid="stSidebar"] [data-testid="stRadio"] label { padding: .36rem .25rem; }
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
  background: var(--color-background); border-right: 3px solid var(--color-accent); }
[data-testid="stSidebar"] [data-testid="stRadio"] p { font-size: .91rem; }
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p { font-size: .79rem; font-weight: 600; }
.editorial-brand { font-family: var(--serif); font-size: 2.15rem; font-weight: 600;
  letter-spacing: -.07em; line-height: 1.1; padding-bottom: .5rem; }
.editorial-brand span { color: var(--color-accent); padding: 0 .1em; }
.editorial-tagline { font-size: .8rem; line-height: 1.5; max-width: 24ch; margin-bottom: 1.7rem; }
.editorial-masthead { display: flex; justify-content: space-between; align-items: center; gap: 1rem;
  border-top: 3px solid var(--color-ink); border-bottom: 1px solid var(--color-ink); padding: .65rem 0;
  font: 500 .68rem/1.5 var(--mono); text-transform: uppercase; letter-spacing: .1em; }
.editorial-masthead strong { font: 600 1rem/1 var(--sans); letter-spacing: -.03em; }
.editorial-hero { display: grid; grid-template-columns: minmax(0, 1.8fr) minmax(0, 1fr);
  column-gap: 3rem; align-items: end; padding: 2.6rem 0 2.2rem; }
.editorial-kicker { font: 500 .7rem/1.6 var(--mono); text-transform: uppercase;
  letter-spacing: .12em; margin: 0 0 1rem; }
.editorial-hero h1 { font: 500 clamp(2.9rem, 4.8vw, 5.9rem)/1.02 var(--serif); letter-spacing: -.055em;
  max-width: 15ch; margin: 0; text-wrap: balance; color: var(--color-ink); }
.editorial-deck { font: 400 1.03rem/1.7 var(--sans); max-width: 32ch; margin: 0 0 .2rem; }
.editorial-section { display: flex; gap: 1rem; border-top: 1px solid var(--color-ink);
  padding-top: 1rem; margin: 2.2rem 0 1.2rem; align-items: baseline; }
.editorial-section .section-no { font: 500 .75rem var(--mono); color: var(--color-ink); }
.editorial-section h2 { font: 500 clamp(1.7rem, 2.4vw, 2.3rem)/1.2 var(--serif); margin: 0; letter-spacing: -.025em; }
.editorial-section p { font: .9rem/1.5 var(--sans); margin: .5rem 0 0; max-width: 65ch; }
.editorial-finding { background: var(--color-ink); color: var(--color-background); padding: 1.5rem 1.8rem;
  margin: 1rem 0; border-left: 5px solid var(--color-accent); }
.editorial-finding small { font: .68rem var(--mono); text-transform: uppercase; letter-spacing: .1em; }
.editorial-finding p { font: 400 1.3rem/1.5 var(--serif); margin: .6rem 0 0; color: inherit; }
.editorial-folio { display: flex; justify-content: space-between; flex-wrap: wrap; gap: .5rem;
  border-top: 1px solid var(--color-ink); padding-top: 1rem; margin-top: 3.5rem;
  font: .65rem/1.6 var(--mono); text-transform: uppercase; letter-spacing: .07em; }
.editorial-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
  gap: 1.2rem; padding: 1.3rem; margin: .5rem 0 1rem; background: var(--color-surface); }
.editorial-facts dt { font: .68rem/1.5 var(--mono); text-transform: uppercase; margin-bottom: .3rem; }
.editorial-facts dd { font: .95rem/1.5 var(--sans); margin: 0; overflow-wrap: anywhere; }
.editorial-quote { border-left: 2px solid var(--color-accent); padding: .3rem 1.2rem; margin: 1rem 0; }
.editorial-quote p { font: 1.15rem/1.65 var(--serif); margin: .2rem 0; }
.editorial-quote small { font: .7rem/1.6 var(--mono); }
[data-testid="stMetric"] { border-top: 1px solid var(--line); padding: .8rem 0; min-width: 0; }
[data-testid="stMetricLabel"] p { font: .73rem/1.5 var(--sans); text-transform: uppercase; letter-spacing: .055em; }
[data-testid="stMetricValue"] { font: 400 clamp(1.7rem, 2.7vw, 3.2rem)/1.2 var(--mono);
  font-variant-numeric: tabular-nums; letter-spacing: -.07em; overflow-wrap: anywhere; }
[data-testid="stMetricDelta"] { color: var(--color-ink); }
.st-key-overview_spread { background: var(--color-surface); padding: 1.1rem 1.5rem; border-top: 2px solid var(--color-ink); }
.st-key-overview_spotlight [data-testid="stMetricValue"] { font-size: clamp(3rem, 5.5vw, 5.7rem); }
.st-key-overview_spread [data-testid="stMetric"] { border: 0; }
[data-testid="stHeading"] h2, [data-testid="stHeading"] h3 { font-family: var(--serif); font-weight: 500; letter-spacing: -.025em; }
[data-testid="stCaptionContainer"] p { font-size: .79rem; line-height: 1.6; color: var(--color-ink); opacity: .83; }
[data-testid="stWidgetLabel"] p { font-size: .87rem; }
[data-testid="stExpander"] { border-color: var(--line); border-radius: 2px; background: transparent; }
[data-testid="stExpander"] summary { font-weight: 500; }
[data-testid="stDataFrame"] { border-top: 2px solid var(--color-ink); border-radius: 0; }
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button, [data-testid="stLinkButton"] a {
  border-radius: 2px; font-weight: 500; transition: background .15s ease, border-color .15s ease; }
button[kind="primary"] { color: var(--color-ink) !important; }
button:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible {
  outline: 2px solid var(--color-ink) !important; outline-offset: 3px; }
[data-testid="stAlert"] { border-radius: 2px; color: var(--color-ink); border: 1px solid var(--line); background: var(--color-surface); }
[data-testid="stAlert"] svg { fill: var(--color-ink); }
[role="tablist"] { border-bottom: 1px solid var(--color-ink); gap: 1.5rem; }
[role="tab"] { font-family: var(--sans); font-size: .87rem; padding-bottom: .85rem; }
[role="tab"][aria-selected="true"] { color: var(--color-ink); font-weight: 700; }
@media (max-width: 900px) {
 [data-testid="stMainBlockContainer"] { padding: 4rem 1.5rem 2rem; }
 .editorial-hero { column-gap: 1.5rem; }
 .editorial-deck { font-size: .93rem; }
}
@media (max-width: 640px) {
 [data-testid="stMainBlockContainer"] { padding: 3.8rem 1rem 2rem; }
 .editorial-hero { grid-template-columns: 1fr; gap: 1.2rem; padding: 2rem 0; }
 .editorial-hero h1 { font-size: 2.9rem; max-width: 16ch; }
 .editorial-deck { max-width: 40ch; }
 .editorial-masthead { font-size: .6rem; flex-wrap: wrap; }
 .editorial-section { margin-top: 1.7rem; }
 [role="tablist"] { gap: .8rem; overflow-x: auto; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; scroll-behavior: auto; } }
"""


def apply_theme() -> None:
    variables = "".join(f"--color-{name}:{value};" for name, value in COLORS.items())
    st.html(
        f"<style>:root{{{variables}--line:rgba(43,26,18,.22);--serif:{SERIF};"
        f"--sans:{SANS};--mono:{MONO};}}{CSS}</style>"
    )


def masthead(first: str, last: str) -> None:
    st.html(
        f'<div class="editorial-masthead"><strong>FULFILL / IQ</strong>'
        f"<span>The logistics intelligence edition</span><span>{escape(first)} — {escape(last)}</span></div>"
    )


def page_header(page: str) -> None:
    number, title, deck = PAGES[page]
    st.html(
        f'<header class="editorial-hero"><div><p class="editorial-kicker">{number} / {escape(page)}</p>'
        f'<h1>{escape(title)}</h1></div><p class="editorial-deck">{escape(deck)}</p></header>'
    )


def section(number: str, title: str, caption: str = "") -> None:
    st.html(
        f'<div class="editorial-section"><span class="section-no">{escape(number)}</span><div>'
        f"<h2>{escape(title)}</h2>{'<p>' + escape(caption) + '</p>' if caption else ''}</div></div>"
    )


def finding(label: str, text: str) -> None:
    st.html(
        f'<aside class="editorial-finding"><small>{escape(label)}</small><p>{escape(text)}</p></aside>'
    )


def facts(values: dict) -> None:
    rows = "".join(
        f"<div><dt>{escape(str(key).replace('_', ' '))}</dt>"
        f"<dd>{escape(str(value)) if value is not None else 'Unavailable'}</dd></div>"
        for key, value in values.items()
    )
    st.html(f'<dl class="editorial-facts">{rows}</dl>')


def review_quote(text: str, score: int | None, themes: list[str]) -> None:
    st.html(
        f'<blockquote class="editorial-quote"><p>{escape(text)}</p>'
        f"<small>Redacted lexical example · score {escape(str(score))} / 5 · "
        f"{escape(', '.join(themes))}</small></blockquote>"
    )


def folio(page: str) -> None:
    st.html(
        f'<footer class="editorial-folio"><span>FULFILL / IQ · {PAGES[page][0]}</span>'
        "<span>Historical Olist observations · CC BY-NC-SA 4.0</span><span>Local demonstration</span></footer>"
    )


def editorial_figure(frame, x: str, y: str, title: str, *, kind: str = "bar", **kwargs):
    """Style figures without changing their source observations or scales."""
    template = go.layout.Template(
        layout=go.Layout(
            paper_bgcolor=COLORS["background"],
            plot_bgcolor=COLORS["background"],
            font={"family": SANS, "size": 13, "color": COLORS["ink"]},
            colorway=[COLORS[k] for k in ("accent", "secondary", "ink", "surface")],
            title={"font": {"family": SERIF, "size": 23}, "x": 0, "xanchor": "left"},
            xaxis={
                "showgrid": False,
                "zeroline": False,
                "linecolor": "rgba(43,26,18,.25)",
                "automargin": True,
            },
            yaxis={"gridcolor": "rgba(43,26,18,.12)", "zeroline": False, "automargin": True},
            hoverlabel={
                "bgcolor": COLORS["ink"],
                "font": {"family": SANS, "color": COLORS["background"]},
            },
            legend={"orientation": "h", "title": {"text": ""}},
            margin={"l": 5, "r": 15, "t": 65, "b": 35},
            height=390,
        )
    )
    labels = {
        name: name.replace("durations.", "")
        .replace(".mean", " (days)")
        .replace("_", " ")
        .capitalize()
        for name in frame.columns
    }
    labels.update(
        {
            "group": "Group",
            "late_rate": "Late deliveries / eligible outcomes",
            "total_orders": "Orders",
            "orders": "Orders",
            "month": "Purchase month",
            "support": "Support · eligible transactions",
            "seconds": "Execution time (seconds)",
            "mean": "Mean duration (days)",
            "predicted": "Mean predicted probability",
            "observed": "Observed late rate",
        }
    )
    labels.update(kwargs.pop("labels", {}))
    figure = {"bar": px.bar, "line": px.line, "scatter": px.scatter}[kind](
        frame, x=x, y=y, title=title, template=template, labels=labels, **kwargs
    )
    figure.update_layout(bargap=0.24)
    if kind == "scatter":
        figure.update_traces(
            marker={"size": 8, "opacity": 0.7, "line": {"width": 1, "color": COLORS["ink"]}}
        )
    elif kind == "line":
        figure.update_traces(line={"width": 2.5})
    for axis, column in (("x", x), ("y", y)):
        if "rate" in column or column in {
            "support",
            "confidence",
            "predicted",
            "observed",
            "precision",
            "recall",
        }:
            figure.update_layout(**{axis + "axis": {"tickformat": ".0%"}})
    if x == "predicted" and y == "observed":
        figure.add_shape(
            type="line",
            x0=0,
            x1=1,
            y0=0,
            y1=1,
            line={"color": COLORS["secondary"], "dash": "dash", "width": 1},
        )
        figure.update_xaxes(range=[0, 1])
        figure.update_yaxes(range=[0, 1])
    return figure
