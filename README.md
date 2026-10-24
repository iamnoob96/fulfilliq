# FulfillIQ

Intelligent E-Commerce Order & Logistics Management — a university Data Mining project.
**Phase 1 is implemented:** original Olist CSV acquisition, validation, SQLite ingestion,
a historical order mart, data-quality reporting, descriptive statistics, and a health API.
There is no storefront, trained model, prediction endpoint, mining, or NLP yet.

## Install (macOS / Apple Silicon)

Use Python **3.11 or newer**. The macOS system Python may be older.
From this project directory:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Alternatively, with [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked --extra dev
source .venv/bin/activate
```

The committed `uv.lock` records the tested dependency versions. With pip, the version
ranges in `pyproject.toml` apply. No cloud accounts, credentials, Docker, or GPU are needed.
Phase 2 will add scikit-learn/joblib; Phase 3 will add mlxtend when those modules are built.

## Acquire the nine original CSVs

```sh
fulfilliq download
```

This downloads only the original CSV tables from a pinned revision of the public
[Hugging Face mirror](https://huggingface.co/datasets/miminmoons/olist-ecommerce-for-delivery-and-review-prediction/tree/2d912b5439d1c42d8c0e6ae84b906f995cbbbeb4/data).
It never downloads the mirror's preprocessed Parquet file. Downloads use temporary files,
validate headers, and record SHA-256 hashes in `data/raw/download_manifest.json`.
Existing valid files are reused; use `--force` explicitly to replace them.

If public downloading fails, obtain the original
[Olist dataset on Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce),
or manually download the CSVs from the mirror, and put these files directly in `data/raw/`:

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

Keep the original filenames, headers, UTF-8 encoding, and identifiers. Do not edit them
in a spreadsheet that converts identifiers or ZIP prefixes to numbers.
See [dataset attribution](docs/DATASET.md) for the original CC BY-NC-SA 4.0 license.

## Ingest and inspect

```sh
fulfilliq ingest
fulfilliq verify
fulfilliq stats
```

Defaults: raw files in `data/raw/`, database at `data/processed/fulfilliq.sqlite3`,
reports at `data/processed/data_quality.json` and `data/processed/logistics_summary.json`.
Reports are also stored inside the database in `etl_runs`, so they stay tied to its contents.
Failed runs write `ingestion_failure.json` with validation details and preserve the previous
database. A completed run clears an older failure report.

Ingestion rebuilds a temporary database, validates keys, foreign keys, totals and SQLite
integrity, then atomically replaces the previous snapshot. Repeating it produces the same
tables and metrics from the same files. Stop the API while refreshing the database; this
is a single-writer local batch workflow. Budget roughly 1 GB of free disk and up to 1 GB
of RAM for the original dataset; geolocation is read one table at a time.

For other locations, export `FULFILIQ_DATA_DIR=/absolute/path/to/data` or use explicit flags:

```sh
fulfilliq download --raw-dir /path/to/raw
fulfilliq ingest --raw-dir /path/to/raw --db-path /path/to/fulfilliq.sqlite3 --report-dir /path/to/reports
fulfilliq verify --db-path /path/to/fulfilliq.sqlite3
fulfilliq stats --db-path /path/to/fulfilliq.sqlite3
```

`.env.example` documents the environment variable; it is not automatically loaded.
Never point a report directory or database path at an original source CSV.

## Run the API

```sh
uvicorn fulfilliq.api.main:app --host 127.0.0.1 --port 8000
```

```sh
curl http://127.0.0.1:8000/health
```

Swagger UI: <http://127.0.0.1:8000/docs>. OpenAPI: <http://127.0.0.1:8000/openapi.json>.
`GET /health` is a typed liveness/readiness response: HTTP 200 after ingestion, HTTP 503
with `database: missing` before ingestion, or `database: invalid` for an unreadable or
incompatible database. The server starts before any data exists and never creates a
database as a side effect of a health check. Health verifies the schema version and a
small required-table query; full data integrity checks belong to `fulfilliq verify`.

## Tests

```sh
pytest
ruff check .
```

Tests use explicitly synthetic temporary fixtures. They cover all nine source tables,
multi-item/multi-seller/multi-payment joins, missing/invalid values, duplicates, Unicode
reviews, foreign keys, repeat ingestion, failed-run preservation, downloader failures,
and API behavior. They require no internet or real data.

## Data and scope

See [architecture and grain](docs/ARCHITECTURE.md),
[cleaning and reporting assumptions](docs/DATA_DECISIONS.md), and
[verification results](docs/VALIDATION.md).
The mart contains **historical outcomes**, final statuses and review summaries; it is
**not a purchase-time prediction dataset**. Phase 2 must build a separate feature view
and implement chronological, label-mature splits before fitting preprocessing or models.
Initial late-delivery statistics compare calendar delivery dates with estimated dates;
only delivered orders with coherent, complete timestamps enter the denominator.
All orders, including canceled and missing-outcome orders, remain in source and fact tables.

Remaining phases: leakage-safe Logistic Regression/Random Forest and evaluation;
Apriori/FP-Growth, seller clustering and historical anomalies; Portuguese review analysis;
analytical/prediction APIs and the final project report. No results from those phases
are claimed here. Raw data, databases, reports and model artifacts are ignored by Git.
