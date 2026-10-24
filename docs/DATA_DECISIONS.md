# Cleaning, reporting and reproducibility decisions

## Source validation

All nine exact filenames and required source columns must exist. Empty source tables,
duplicate headers, missing mandatory identifiers/statuses, conflicting primary keys and
orphaned foreign keys fail the run. Extra columns are listed in the report and ignored.
Malformed CSVs and HTML/LFS pointers fail parsing or header validation. All raw files stay
unchanged; validation never repairs them in place.

Read CSV fields initially as strings with UTF-8 (optional BOM). Empty/whitespace-only
fields become null. Text such as `NA` is not automatically interpreted as missing.
Identifier strings, ZIP leading zeros, city spellings, accents, review punctuation and
original Portuguese text are retained. No deduplication by customer identity, seller,
ZIP, order, or review identifier is performed unless that column is an actual source key.

Exact duplicate rows across expected source columns are removed before type coercion
and counted. If two remaining rows share a declared primary key, ingestion fails rather
than arbitrarily choosing the first. A repeated review ID or ZIP prefix is valid; distinct
records remain. This means loaded geolocation counts can be lower than original CSV
counts, and the report states both. Surrogate review/geolocation IDs are sequential in
retained input order and are not business identifiers.

Timestamps use the original `%Y-%m-%d %H:%M:%S` format. Invalid nonempty timestamps become
null with counts. They remain timezone-naive source-local times; no timezone conversion
is invented. Original CSVs and SHA-256 hashes allow inspection of rejected values.
UTC timestamps are used only for ingestion metadata.

Numeric fields become numeric types. Invalid/nonfinite/negative values become null,
with exceptions for valid signed geographic coordinates. Integer fields must be integral
and fit signed int64. Item and payment sequence numbers must be >=1; invalid sequence
keys fail. Zero installments are retained because they occur in the source. Review
scores outside 1–5 become null. Latitude must be in [-90, 90] and longitude in [-180, 180].
These are global validity checks, not a guarantee that every coordinate lies in Brazil.
Only complete valid coordinate pairs enter ZIP means.

Missing numeric attributes are not imputed in Phase 1. In particular, a sum across a
nonempty set is null when any contributing value is missing: incomplete prices, freight,
payment values or product weights must not appear to be a complete total. Counts stay
available. Orders without child rows have count zero and null monetary/weight totals.
Reviews with missing scores still count as review records; score averages use known scores.

Money is BRL represented with SQLite REAL/Python floats, consistent with the analytical
CSV workflow. Integrity comparisons allow a small floating-point tolerance. This is not
an accounting ledger; use integer centavos or Decimal before implementing settlement.
Payment totals and item-plus-freight totals remain distinct; they need not always match.

## Historical delivery outcomes

All orders remain in `orders` and `fact_orders`, including canceled, unavailable,
undelivered and missing-outcome orders. An order enters the late-rate denominator only
when its status is `delivered`, purchase/delivery/estimate timestamps are known, delivery
is not earlier than purchase, and the estimated calendar date is not before purchase.

An eligible order is late when `date(delivered_at) > date(estimated_delivery_at)`. A
delivery at 23:59 on the promised day is on time. This avoids falsely declaring same-day
deliveries late because estimates are often midnight. `delay_days` is the nonnegative
calendar-day difference (zero for on-time outcomes); ineligible orders have null lateness
and delay days. The late rate is null, not zero, when there are no eligible outcomes.
This is a historical descriptive flag, not yet a training label or maturity policy.

Durations use fractional 24-hour days from the recorded timestamps:

- Approval: purchase to approval, only when approval >= purchase.
- Fulfillment: approval to carrier handoff, only when carrier >= approval >= purchase.
- Transit: carrier handoff to customer delivery for delivered orders, only when
  delivery >= carrier >= purchase.
- Delivery: purchase to customer delivery for delivered orders, only when delivery >= purchase.
- Promised lead: estimated calendar date minus purchase calendar date, if nonnegative.

Missing or inconsistent endpoints yield null for the affected measure; no clipping of
negative historical durations to zero occurs. Promised lead uses calendar days because
the source promise is a date, unlike recorded event durations. Date inconsistencies remain in source tables
and are counted in the quality report. Approval/fulfillment descriptive means include
any status with coherent recorded endpoints; delivery/transit means require delivered
status. The report provides duration counts alongside means because denominators differ.

## Report contents

`data_quality.json` includes input hashes, original/loaded row counts, exact duplicate
counts, per-column missing counts before/after cleaning, invalid-to-null counts, ignored
columns, cross-table coverage, date anomalies, SQLite/FK results and mart row counts.
`logistics_summary.json` includes total/delivered/canceled/eligible/excluded orders,
late counts and rates, duration means and counts, status counts, state-level delivery
statistics, multi-seller counts and orders missing item/payment records.

Failures produce `ingestion_failure.json` with the stage's available reports and an error.
The last successful database and its reports remain available. Successful ingestion removes
the stale failure report. Check the exit code and run IDs rather than assuming an old
success report describes a newly failed input set.

Repeat ingestion rebuilds rather than appends. For the same raw files, table values,
cleaning decisions, hashes and statistics are stable; run IDs, metadata timestamps and
SQLite file bytes are not promised to be identical. The download manifest hashes local
bytes for reproducibility; a locally computed hash alone is not a publisher signature.
Manually supplied/reused files have unverified acquisition origin. Header validation
cannot prove those files are the original Kaggle data; retain your source provenance.
