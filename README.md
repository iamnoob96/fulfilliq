# FulfillIQ

An internal **e-commerce logistics intelligence backend**, built for a university Data
Mining project. It uses the nine original Olist CSVs to predict purchase-time delivery
risk, investigate historical fulfillment, mine delay associations, segment sellers,
screen unusual operations and analyze Portuguese reviews. There is no storefront.

Private source repository: [iamnoob96/fulfilliq](https://github.com/iamnoob96/fulfilliq).

## Implemented capabilities

- Validated, idempotent ETL of all nine tables into SQLite; normalized sources and a
  star-schema-style mart with exactly one fact per order.
- Strictly backward-looking seller/region histories, chronological mature-label splits,
  Logistic Regression, Random Forest and histogram gradient boosting, probability
  calibration, validation-only candidate/threshold selection and persisted inference.
- Filterable approval, dispatch, transit, delivery and lateness analytics, with seller,
  region, category and monthly cohorts. Shared orders never multiply financial totals.
- Apriori and FP-Growth, support/confidence/lift/leverage, interpreted seller K-Medoids
  segments with stability checks, and historical Isolation Forest/Wilson/robust screens.
- Portuguese normalization, lexical delivery themes, TF-IDF interpretation and a
  separate chronological review-score-supervised sentiment model.
- Thirteen typed FastAPI routes, single/batch scoring, investigation recommendations,
  pagination, explicit failures, structured application logs and Swagger examples.

This is a working **historical offline simulation and local API**. The selected delay
model has modest discrimination and poorer test probability error than a prevalence
baseline. It requires forward validation before operational deployment. No intervention
benefits, causal bottlenecks, confirmed incidents or verified complaint labels are claimed.

## Install

Use Python **3.11+**; Python 3.11 on macOS/Apple Silicon is verified. Install
[uv](https://docs.astral.sh/uv/) and work from the repository root:

```sh
git clone https://github.com/iamnoob96/fulfilliq.git
cd fulfilliq
uv sync --locked --extra dev
source .venv/bin/activate
```

The private clone requires your GitHub access. Data/model workflows require no paid APIs,
cloud accounts, Docker or GPU. `uv.lock` pins tested versions. Alternatively use
`python3.11 -m venv .venv`, activation, then `python -m pip install -e '.[dev]'`.
Pip uses the ranges in `pyproject.toml` rather than the uv lockfile.

`.env.example` is a reference, not automatically loaded. Export `FULFILIQ_DATA_DIR` and
`FULFILIQ_ARTIFACT_DIR` to change default `./data` and `./artifacts` locations. Relative
paths resolve against the working directory. The default Python version for uv is 3.11.

## Acquire the original data

```sh
fulfilliq download
```

The credential-free downloader fetches only original CSVs from a pinned public
[mirror revision](https://huggingface.co/datasets/miminmoons/olist-ecommerce-for-delivery-and-review-prediction/tree/2d912b5439d1c42d8c0e6ae84b906f995cbbbeb4/data).
It validates headers/response lengths, uses atomic temporary downloads, reuses existing
files, and records SHA-256 hashes. `--force` explicitly replaces existing files.
It does not use the mirror's preprocessed Parquet dataset.

If downloading fails, obtain the original
[Olist dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) or its CSV
mirror manually and place these exact files in `data/raw/`:

```text
olist_customers_dataset.csv
olist_geolocation_dataset.csv
olist_order_items_dataset.csv
olist_order_payments_dataset.csv
olist_order_reviews_dataset.csv
olist_orders_dataset.csv
olist_products_dataset.csv
olist_sellers_dataset.csv
product_category_name_translation.csv
```

Retain UTF-8, original headers, IDs and ZIP leading zeros. Do not round-trip raw files
through a spreadsheet. The original dataset is **Olist, CC BY-NC-SA 4.0**; its attribution
and terms are retained despite the mirror's different repository license label.
See [dataset attribution](docs/DATASET.md).

## Reproduce the complete backend

```sh
fulfilliq ingest
fulfilliq verify
fulfilliq stats
fulfilliq train
fulfilliq build-insights
fulfilliq export-report
pytest -q
ruff check .
uvicorn fulfilliq.api.main:app --host 127.0.0.1 --port 8000
```

Training compares all three candidates, calibrates frozen estimators on a reserved mature
training period, selects the candidate/threshold on validation and evaluates later test
orders. It saves the pipeline, calibration, history indices, schema, threshold, metrics,
source hashes and versions. The selected estimator is not refitted on test data.

`build-insights` creates every historical analytical output. Individual runs and parameters:

```sh
fulfilliq train --maturity-days 14 --lag-days 1 --history-window-days 180
fulfilliq build-insights --module operations
fulfilliq build-insights --module rules --min-support .01 --min-confidence .15 --min-lift 1.1 --max-length 3
fulfilliq build-insights --module segments --min-seller-orders 10
fulfilliq build-insights --module anomalies --contamination .02 --anomaly-min-orders 20
fulfilliq build-insights --module reviews
fulfilliq score --input examples/order.json
```

For the bounded delivery-risk challenger protocol, run:

```bash
fulfilliq experiment-risk --output artifacts/risk-experiment.json
```

This preserves the active model and saves a separate challenger. Optional
`--promote-if-qualified` applies the documented validation and final-test gates;
existing report paths are never overwritten. The October optimization sprint
improved held-out top-decile precision from 10.30% to 14.56%, but **did not
promote** because validation ranking regressed. See the preserved comparisons in
[experimental results](docs/RESULTS.md) and [protocol](docs/RISK_SPRINT.md).

The dataset is about 126 MB of CSVs. Allow a few GB of disk and roughly 1–2 GB RAM for a
full workflow; CPU parallelism is bounded. Training and mining take minutes depending on
hardware. Stop the API during database refreshes. This is a local single-writer workflow.

## API and examples

Swagger: <http://127.0.0.1:8000/docs>. OpenAPI: <http://127.0.0.1:8000/openapi.json>.

```sh
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/api/v1/orders/predict-delay \
  -H 'Content-Type: application/json' --data-binary @examples/order.json
curl 'http://127.0.0.1:8000/api/v1/analytics/bottlenecks?group_by=region&min_orders=100'
curl 'http://127.0.0.1:8000/api/v1/mining/association-rules?min_lift=1.5&limit=10'
python scripts/smoke_api.py
```

`examples/order.json` is an explicitly synthetic historical scenario, not an Olist record
or reported model result. Each item price/freight/dimension describes one unit; `quantity`
multiplies it. Coordinates are optional pairs. Batch requests accept `{"orders": [...]}`
with unique IDs and at most 100 orders. Requests forbid delivery outcomes, handoffs,
statuses and review fields. Naive timestamps are Brazilian source-local; aware timestamps
convert to America/Sao_Paulo. Responses include contextual rationale, cautions, model
version, threshold and an investigation recommendation.

| Method | Route |
| --- | --- |
| GET | `/health` |
| POST | `/api/v1/orders/predict-delay` |
| POST | `/api/v1/orders/predict-batch` |
| GET | `/api/v1/analytics/overview` |
| GET | `/api/v1/analytics/bottlenecks` |
| GET | `/api/v1/analytics/delivery-performance` |
| GET | `/api/v1/mining/association-rules` |
| GET | `/api/v1/mining/anomalies` |
| GET | `/api/v1/sellers/segments` |
| GET | `/api/v1/sellers/{seller_id}/insights` |
| GET | `/api/v1/reviews/insights` |
| GET | `/api/v1/models/metrics` |
| GET | `/api/v1/models/info` |

Operational filters combine seller, region, category and inclusive purchase-date ranges.
Lists use `limit`/`offset`; mining endpoints filter already-generated reports. Health
retains its original database-readiness contract. Missing models/reports return **503**
with CLI recovery instructions; invalid inputs return **422** and unknown seller insights
return **404**. No request trains a model. See [API details](docs/API.md).

## Observed results

Real ingestion: **99,441 orders**, **112,650 items**, **103,886 payments**, **99,224 reviews**.
Integrity, foreign keys, order grain and monetary reconciliation passed.

The new exact timestamp target has **7,826 late / 96,470 eligible deliveries (8.11%)**.
Original `stats` and `fact_orders.is_late` retain calendar-day comparison for compatibility:
**6,534 / 96,470 (6.77%)**. These definitions must not be mixed.

Validation selected **calibrated histogram gradient boosting**. Its later test period
contains **14,551 orders**: ROC-AUC **0.6483**, average precision **0.0977**, precision
**0.1025**, recall **0.1735**, F1 **0.1289**, Brier **0.0684**, and top-decile precision
**0.1030** (test prevalence **0.0658**). The prevalence baseline has better Brier error
(**0.0615**). Candidate rankings reversed on test, demonstrating temporal instability;
the executable selection rule still uses validation only.

Other findings: one supported SP-seller/RJ-customer delay rule (lift **1.917**); two
segments across **1,271** sufficiently observed sellers; **1,989** order-characteristic
anomaly flags; **42,454** reviews with text. The separate noisy-star sentiment model has
chronological test accuracy **95.06%**, versus **73.79%** for the majority baseline.

See [full results](docs/RESULTS.md) and the reproducible
[aggregate JSON](docs/results/experiment.json). Test diagnostics were inspected during
engineering; this is exploratory evaluation, not a blind external production benchmark.

## Tests, artifacts and limitations

Tests cover ingestion, temporal leakage, calibration, multi-seller aggregation, training,
persistence, deterministic single/batch scoring, miners, clustering stability, anomalies,
Portuguese text, provenance, all API routes and a complete nine-table synthetic workflow.
Real workflows and live HTTP checks are recorded in [validation](docs/VALIDATION.md).
Synthetic test performance is never presented as real Olist model performance.

Raw CSVs, databases, record-level outputs, binaries, environment files and secrets are
ignored by Git. `data/processed/fulfilliq.sqlite3` holds sources/marts; `etl_runs` stores
canonical ingestion reports. `artifacts/delivery/<version>/` stores trusted local models
and metadata, with atomic `current.json`; `artifacts/insights/` stores provenance-checked
JSON snapshots; `artifacts/reviews/sentiment.joblib` stores the NLP model. Only small
aggregate results are committed. Never load untrusted joblib files.

Key limits: historical 2016–2018 data, unknown modern-domain validity, approximate event
observation times, static checkout attributes, unavailable-outcome selection bias, limited
probability calibration, global historical anomaly references, non-causal shared-order
seller attribution, moderate segment stability, unverified lexical complaint rules and
noisy sentiment stars. The local API has no production authentication layer.

Technical details: [architecture/schema](docs/ARCHITECTURE.md),
[cleaning assumptions](docs/DATA_DECISIONS.md), [model methodology](docs/METHODOLOGY.md),
[mining/NLP](docs/MINING_AND_NLP.md), [syllabus mapping](docs/SYLLABUS.md).
