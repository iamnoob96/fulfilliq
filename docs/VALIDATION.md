# Phase 1 verification

This section preserves the original ingestion baseline. Current end-to-end results are in
[RESULTS.md](RESULTS.md) and [the aggregate experiment](results/experiment.json).

Verified on **24 October 2026**, using Python 3.11.3 on macOS / Apple Silicon (arm64). The tested dependency
versions are recorded in `uv.lock`. These are observed local results, not model results.

## Automated checks

- `pytest -q`: **27 passed**. Fixtures are synthetic and confined to temporary directories.
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- `python -m compileall -q src`: passed.
- `uv sync --locked --extra dev --offline`: passed using the already downloaded cache.
- A real Uvicorn server returned HTTP **200** for `/health`, `/docs` and `/openapi.json`.
  Health returned `status: ok`, `database: ready`; OpenAPI exposed only `/health`.
  The temporary smoke-test server was shut down afterward.

There are **no remaining failed checks**. Pytest emits one dependency deprecation warning:
the installed Starlette test client warns that its `httpx` integration is deprecated in
favor of `httpx2`. All HTTP tests pass; no deprecated integration is used by the running
API. This can be addressed when updating the test dependency stack.

The initial tests caught an encoded SQLite URI path issue and a test fixture that changed
timestamp column names while editing statuses. Both were corrected before the final run.
The host sandbox initially blocked network access and local port binding; dependency/data
downloads and the temporary local HTTP test succeeded through approved tool execution.

## Real dataset ingestion

All nine original CSVs were downloaded successfully from the pinned public mirror.
Per-file SHA-256 hashes and download URLs are in `data/raw/download_manifest.json`.
The successful database and canonical quality/summary JSON are in `data/processed/` and
are intentionally ignored by Git. Exact source hashes are also embedded in `etl_runs`.

| Original source | CSV rows | Loaded rows |
| --- | ---: | ---: |
| Customers | 99,441 | 99,441 |
| Sellers | 3,095 | 3,095 |
| Products | 32,951 | 32,951 |
| Orders | 99,441 | 99,441 |
| Order items | 112,650 | 112,650 |
| Order payments | 103,886 | 103,886 |
| Order reviews | 99,224 | 99,224 |
| Geolocation | 1,000,163 | 738,332 |
| Category translations | 71 | 71 |

The 261,831 removed geolocation records were exact duplicates across the original columns.
Distinct ZIP observations remain, yielding **19,015 ZIP centroid rows**. No source rows
were removed from the other tables. Whitespace-only review fields were normalized to null:
2 titles and 27 messages; these records themselves remain.

The mart contains **99,441 fact rows**, **100,010 order/seller pairs**, **102,425 order/product
pairs**, and **634 observed purchase dates**. Dimension counts match their source tables.
`PRAGMA integrity_check` returned `ok`; `PRAGMA foreign_key_check` found **zero violations**.
All item/payment/review counts, bridge item counts and per-order monetary sums reconciled
against independently aggregated source data.

A second full ingestion of the real CSVs reproduced identical per-table cleaning reports,
row counts, integrity checks and logistics statistics. Only the run UUID and metadata
timestamps changed. The final run UUID is `7f163742-9bfb-4b69-b421-639cb24caaa2`.

## Initial historical logistics results

- Orders with delivered status: **96,478**.
- Delivered orders with complete, coherent outcome timestamps: **96,470**.
- Late deliveries (calendar delivery date after promised date): **6,534**, or **6.7731%**
  of eligible outcomes.
- Orders excluded from the late-rate denominator: **2,971** across all statuses;
  **8** of these have delivered status but missing required outcome timestamps.
- Mean purchase-to-delivery duration: **12.5582 days**, based on **96,470** coherent
  delivered outcomes.
- Orders involving multiple sellers: **1,278**.
- Orders without item records: **775**; without payment records: **1**.

Reported quality gaps include **1,359** carrier handoffs before approval, **23** deliveries
before carrier handoff, **13** products with an untranslated nonmissing category, **278**
customers and **7** sellers without valid ZIP coordinates, **789** repeated review IDs,
and **547** orders with more than one review. Repeated reviews remain separate records;
incoherent durations are excluded only from the affected metric. These observations
do not establish operational causes or future prediction performance.

## Reproduce and inspect

```sh
source .venv/bin/activate
fulfilliq download
fulfilliq ingest
fulfilliq verify
fulfilliq stats
pytest -q
ruff check .
```

Report files carry a run UUID that matches `etl_runs` inside the current database.
The static numbers here describe the pinned source revision and documented cleaning rules.
If inputs or policies change, regenerate reports and update this record. The original
CSV files and generated artifacts remain local and are not included in version control.

## Limits

This phase provides a historical reporting snapshot. It does not create purchase-time
features, chronological/label-mature splits, predictive models, mining results, seller
clusters, anomaly detection, or Portuguese NLP results. It is a local batch workflow,
not a concurrent production ingestion system. See `DATA_DECISIONS.md` for timezone,
calendar-day lateness, missing values, coordinate and floating-point assumptions.
