# The FulfillIQ editorial edition

The eight-page Streamlit console uses a shared publication-style shell: numbered contents,
a masthead, a section headline and deck, typographic metrics, thin rules, and source annotations.
The backend, saved-model selection, mining algorithms, cohort membership, and investigation
revision rules retain their existing contracts. Figures and narrative copy describe historical
observations rather than current operations or causal effects.

## Design system

| Token | Color | Role |
| --- | --- | --- |
| Accent | `#DC6D18` | Selected controls, emphasis, primary data series |
| Background | `#FFF4E4` | Main editorial canvas |
| Surface | `#F8E0C9` | Secondary surfaces and case-file facts |
| Ink | `#2B1A12` | Text, rules, occasional dark findings panel |
| Secondary | `#B1AA81` | Supporting data and reference lines |

Fraunces provides display and section type, DM Sans the interface, and IBM Plex Mono
numbers and metadata. The unmodified fonts and their SIL Open Font Licenses live under
`src/fulfilliq/console/static/fonts/`. Streamlit serves them from the **console script's**
static directory at `/app/static/fonts/`; no external font service is needed. Georgia,
Avenir/system sans, and Menlo/monospace provide fallbacks. These font licenses do not
assign a license to the project's source code.

`.streamlit/config.toml` configures native widgets, dataframes, typography and palette.
`console/theme.py` owns shared visual tokens, escaped HTML content components, and the
Plotly template. Native controls retain labels, keyboard access, focus states, loading
states and error handling. CSS uses semantic custom classes, keyed containers, and
Streamlit `data-testid` selectors rather than generated class names. Recheck these
selectors when updating the locked Streamlit version (verified here: 1.66.1).

Figure headings live in normal document flow so they wrap at narrow widths. Plotly
retains its scales, units, tooltips, zoom controls and underlying values. Its modebar PNG
contains the chart and axes; the editorial heading/source annotation lives in the page.
Use the consolidated report for accompanying context. Dataframe display formatting never
changes the raw values in CSV exports. Status text accompanies visual emphasis; benchmark
metadata is not presented as a positive/negative metric delta.

## Page compositions

| Section | Editorial treatment |
| --- | --- |
| Overview | Opening spread, large order-count spotlight, secondary rates and operational metrics, four annotated figures, workload counts |
| Orders | Discover → Prioritize → Investigate → Record the next step; case-file facts, persistent-job progress and provenance, accessible revision-checked forms |
| Logistics | Journey comparisons, bottleneck ledger, separately scoped regional signals |
| Sellers | Profile facts and metrics, measured peer groups, supporting historical evidence |
| Mining | Algorithm-specific benchmark views and comparison, shared verified outputs, cluster profiles, method-specific anomaly evidence |
| Reviews | Corpus summaries, lexical themes and review-score figures, sentiment context, escaped redacted quotations |
| Models | Saved model identity, historical scorecard, comparison table, calibration/reference diagonal, preserved temporal research |
| Reports | Consolidated operations issue, CSV archive, optional R supplement and source files |

Global cohort filters continue to apply only where the API supports them. Mining, seller
segments and saved review/model summaries explicitly retain their documented full-history
scope. Threshold caveats, model limitations and preliminary-ranking warnings remain visible.

## Responsive and visual verification

Actual browser review covered all eight pages with the saved Olist data. Desktop captures
are 1440 × 900. The design was also inspected at 1280 × 720, 768 × 1024 and 390 × 844.
The headline/deck stacks below 900 px; the mobile contents panel collapses using Streamlit's
native sidebar control. At 390 px, the checked overview, mining view and investigation
form had no page-wide horizontal overflow. Wide data tables intentionally scroll internally.
Responsive figures use native headings to avoid SVG title clipping.

- [Overview](screenshots/editorial/01-overview-desktop.png)
- [Orders](screenshots/editorial/02-orders-desktop.png)
- [Logistics](screenshots/editorial/03-logistics-desktop.png)
- [Sellers](screenshots/editorial/04-sellers-desktop.png)
- [Mining](screenshots/editorial/05-mining-desktop.png)
- [Reviews](screenshots/editorial/06-reviews-desktop.png)
- [Models](screenshots/editorial/07-models-desktop.png)
- [Reports](screenshots/editorial/08-reports-desktop.png)
- [Verified R figure](screenshots/editorial/08-r-figure.png)
- [Measured algorithm comparison](screenshots/editorial/05-mining-comparison.png)
- [Tablet mining](screenshots/editorial/05-mining-tablet.png)
- [Mobile overview](screenshots/editorial/01-overview-mobile.png)
- [Mobile investigation form](screenshots/editorial/02-investigation-mobile.png)

These are actual running-application screenshots, not mockups. The dense research tables
remain most comfortable on a laptop. Physical mobile devices, other browser engines and
a complete assistive-technology audit were not tested. Contrast checks verify Espresso
text against each supplied surface at the WCAG AA 4.5:1 threshold; reduced-motion and
visible focus styles are included.

## Functional verification — 24 October 2026

- **158 automated tests passed**, including the original 154. Added checks cover chart
  observations/units, escaped content, text contrast, and the configured static font paths.
- Ruff and formatting checks passed for the changed Python UI files. Existing mining
  selector, filtering, stale-edit, navigation and durable-job interaction tests passed.
- All eight pages rendered against the actual API. The quick-scoring smoke scored 22 of
  50 recent candidates and reported unavailable reconstructions explicitly.
- Real-data API smoke verified 99,441 orders, 96,470 eligible outcomes and 7,826 late
  deliveries; direct/replay inference agreed and isolated notes survived API recreation.
- Isolated cohort restart verification stopped after 50 of 413 AL candidates, then a new
  worker completed **411 scored + 2 unavailable**. CSV and investigation persistence passed.
- Warehouse, active-model pointer and active model binary checksums remained unchanged.
- R figures were regenerated with the supplied palette from the same input files.
  Python/R Apriori still agreed on one rule across 5,000 shared transactions, with maximum
  metric difference `2.22e-15`; plots describe all 96,470 valid delivered orders.

Reproduce the application and checks from the project root:

```sh
./scripts/start_app.sh
# Separate terminal, with services running:
uv run --extra console python scripts/verify_console.py
uv run --extra dev python scripts/smoke_application.py
uv run --extra dev python scripts/verify_cohort_scoring.py
uv run --extra dev --extra console pytest -q
uv run --extra dev ruff check src tests scripts
```

Optional R palette reproduction reuses the existing exported inputs:

```sh
Rscript r_analysis/analyze.R data/processed/r_inputs artifacts/r_analysis
uv run fulfilliq verify-r
```

No real-data model training, recalibration or promotion was performed for this redesign.
Existing modeling tests continue to fit isolated fixtures. The existing non-failing
Starlette/httpx deprecation warning remains.
