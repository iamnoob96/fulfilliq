# API guide

Start `uvicorn fulfilliq.api.main:app --host 127.0.0.1 --port 8000` after ingestion,
training and insight generation. `/docs` and `/openapi.json` contain full Pydantic schemas
and constraints. No route performs training or mining as a request side effect.

## Delivery risk

Request timestamps support years 1900–2100 to keep temporal arithmetic within the
supported operational range. Incoherent or unsupported dates return 422.

```sh
curl -X POST http://127.0.0.1:8000/api/v1/orders/predict-delay \
  -H 'Content-Type: application/json' --data-binary @examples/order.json
```

`order_id` is a correlation key, not an ML predictor. Provide source-local checkout and
promised timestamps, customer state, optional coordinates and item entries. Each entry
describes one unit, multiplied by quantity; seller IDs attach strictly historical outcomes.
Unknown sellers are allowed and marked as a cold start. State codes are uppercase letters;
categories should follow source/translation names. Counts, complete values/weights/volumes,
distances and primary category/state are computed internally. Clients cannot inject
precomputed history rates or outcome data.

`POST /api/v1/orders/predict-batch` accepts `{"orders": [<order>, ...]}`. Bounds: 100 orders,
100 item entries and 1,000 units per order; unique batch IDs. Results preserve input order;
`priority_order_ids` sorts flagged orders by decreasing score. Single and batch scoring
use the same persisted estimator and feature generator.

Optionally add `"review_capacity": 10` to select the ten highest probabilities
within the submitted batch. `review_order_ids` returns this separate queue,
independent of the threshold-based `priority_order_ids`. Capacity must be an
integer from zero to the number of submitted orders; omission returns an empty
review queue. Tied probabilities preserve input order. This is a batch-relative
ranking, not a global percentile or a guarantee of delay. Across multiple
batches, merge scores and rank the full cohort to enforce one global budget.

```json
{
  "orders": [
    {
      "order_id": "investigate-001",
      "purchased_at": "2018-07-01T12:00:00",
      "estimated_delivery_at": "2018-07-20T00:00:00",
      "customer_state": "RJ",
      "items": [{"seller_id": "unknown-seller", "seller_state": "SP", "price": 50, "freight_value": 10}]
    }
  ],
  "review_capacity": 1
}
```

Responses include probability, validation-selected threshold, high/standard category,
model version, recommendation, contextual rationale and evidence-based warnings. Context
is not a causal local attribution. Purchases outside the historical observation horizon
or before training are flagged. Inferior observed Brier error also appears in warnings.
An investigation recommendation does not establish a preventable delay.

## Operations

`/api/v1/analytics/overview` returns counts, statuses, milestone statistics and monthly
volumes. `/delivery-performance` and `/bottlenecks` under the same prefix accept
`group_by=region|seller|category|month`, `min_orders`, `limit` (1–500) and `offset`.
Bottlenecks compare disjoint approval, fulfillment and transit stages with enough coherent
observations; total journey durations do not compete with their parts.

All three combine `seller_id`, `region`, `product_category`, `start_date`, `end_date`.
Date bounds are inclusive purchase calendar dates. Seller/category filters apply to the
same item membership before selecting distinct orders. Seller/category groups overlap
and are non-additive; whole-order milestones cannot isolate one seller's shipment.

```sh
curl 'http://127.0.0.1:8000/api/v1/analytics/overview?region=RJ&start_date=2018-01-01&end_date=2018-06-30'
curl 'http://127.0.0.1:8000/api/v1/analytics/delivery-performance?group_by=category&min_orders=100&limit=20'
```

New analytics use exact timestamp lateness. Legacy `stats` and the original mart retain
calendar-day lateness. Empty denominators give null rates, not zero.

## Mining, sellers and reviews

`GET /api/v1/mining/association-rules`: filter saved rules by `min_support`, `min_confidence`,
`min_lift`, `antecedent_contains`, then paginate. Lower query cutoffs cannot recover rules
excluded during mining; change CLI parameters and regenerate to explore another search.

`GET /api/v1/mining/anomalies`: filter `kind=order|seller|region|seller_fulfillment` or
`entity_id`. Scores include method-specific thresholds/reasons and are not directly
comparable between methods.

`GET /api/v1/sellers/segments`: filter `segment_id` or `seller_state`; includes profiles,
silhouette, stability and low-volume exclusions. `GET /api/v1/sellers/{seller_id}/insights`
returns order performance and available segment/review/anomaly associations. Missing
optional reports appear in warnings; unknown order-item sellers return 404. Low-volume
sellers can have no supported segment.

`GET /api/v1/reviews/insights`: choose `group_by=seller|category|region`, optional exact
`group`, `theme`, `min_text_reviews`, `limit` and `offset`. These select aggregate groups;
`global_summary` explicitly remains the entire corpus. Theme counts overlap. Sentiment
evaluates noisy review-score labels, not complaint correctness. Raw text is not returned.

## Models, health and failures

`GET /api/v1/models/info` provides schema, target, provenance, versions, splits and
assumptions. `/metrics` provides all candidates, baselines, threshold, calibration and
validation permutation importance. Newly generated metrics also include
`mean_probability` and `review_budgets` for 5%, 10% and 20% review capacity
(precision, captured late orders and recall). Older artifacts return null/empty
for these additive fields rather than inventing unavailable measurements.
Model selection uses validation only; the sprint's optional promotion also
requires predeclared final-test safety gates. Better test metrics cannot override
a failed validation gate. Models returning invalid probability vectors fail with
503 rather than emitting a malformed risk score.

`GET /health` retains its original response: 200 for a valid database, otherwise 503 with
database missing/invalid. This is database readiness, not model readiness. Required model
or report failures return 503 with recovery instructions; invalid inputs are 422. Changed
input hashes require retraining/rebuilding, while reingesting identical sources remains
compatible. Paging beyond the end returns an empty list with the filtered total.

## Operations console workflows

All original routes and fields remain available. `/analytics/overview` additionally
returns `active_sellers` for the filtered item membership. Exact-time operational
late rates retain their existing target; legacy mart calendar-day flags are distinct.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/console/options` | Historical date bounds, states, categories and seller IDs |
| GET | `/api/v1/console/dependencies` | Read-only warehouse/model/insight readiness; no generation |
| GET | `/api/v1/orders` | Filtered historical candidate pages |
| GET | `/api/v1/orders/{order_id}` | Placement inputs, products, separate observed milestones, replay eligibility and human state |
| POST | `/api/v1/orders/replay` | Reconstruct placement-only inputs and score the existing model |
| PUT | `/api/v1/orders/{order_id}/review` | Persist a human decision in the separate operations database |
| GET | `/api/v1/mining/itemsets` | Saved frequent itemsets for Apriori or FP-Growth |
| GET | `/api/v1/reviews/evidence` | Filtered score counts and conservatively redacted lexical examples |
| GET | `/api/v1/models/research` | Read-only saved temporal/adaptive report summaries |
| GET | `/api/v1/reports/operations` | Reproducible filtered operational report plus Markdown |
| GET | `/api/v1/reports/r` | Optional completed R summary and available filenames |
| GET | `/api/v1/reports/r/files/{filename}` | Known completed CSV/JSON/PNG reports only |

Order listing accepts the existing `seller_id`, `region`, `product_category`,
`start_date`, `end_date` filters plus `review_status`, `limit` (1–100), `offset` (>=0).
Dates are inclusive purchase dates. Seller/category filters match the same item
membership; orders are never multiplied by item count. Listing sorts purchase descending,
then identifier ascending. No outcomes are included in candidate table rows.

```json
{"order_ids": ["a-real-warehouse-order-id"], "review_capacity": 1}
```

Replay accepts 1–100 unique IDs and integer capacity 0–candidate count. Response contains
`predictions`, descending-risk `review_order_ids`, and per-ID `unavailable` reasons.
Missing IDs or invalid required checkout attributes are unavailable, never filled with
invented valid values. Optional missing product/geography inputs retain the existing
model's missing-value policy. Capacity applies within this submitted batch. Ties preserve
input order. A completely unavailable batch does not require a model load. A valid batch
without a compatible saved model returns 503. Prediction responses retain their original
probability/threshold/category/model-version/rationale/warnings fields.

Human update example (the launcher configures the shared token without displaying it):

```sh
curl -X PUT http://127.0.0.1:8000/api/v1/orders/ORDER_ID/review \
  -H "Authorization: Bearer $FULFILIQ_WRITE_TOKEN" -H 'Content-Type: application/json' \
  --data '{"status":"investigating","notes":"Compare carrier milestones","expected_revision":0}'
```

Valid states: pending, investigating, reviewed, escalated, resolved. Notes are limited to
5,000 characters. Revision begins at 0, increments on save, and must match the current
value: stale updates return **409**. Unknown orders return **404**. Missing/wrong token or
unconfigured write access returns **403**. Extra fields and invalid states return **422**.
This endpoint never changes historical orders, milestones, predictions or model artifacts.
Tokens are process configuration, not returned by any endpoint. Local access is a
single-team assumption, not production-grade identity/authorization.

Itemsets accept `algorithm=apriori|fp_growth`, support filter, limit (1–500), offset. Both
algorithms' identical itemsets/support are verified offline and stored once; an old
snapshot without itemsets returns 503 with the targeted `build-insights --module rules`
recovery command. Display filtering never re-mines or lowers saved mining thresholds.
Review evidence accepts seller/state/category and up to 30 examples; examples are
post-order lexical evidence, not prediction inputs. Date filters do not apply there.

Operational reports apply cohort filters to operational tables. Seller report groups
require at least five orders and show the first 50 by late rate. Mining findings are
explicitly full-history snapshots. Equal inputs produce equal report text, including
saved snapshot provenance. R availability is optional: missing/incompatible outputs
return 200 with `available=false`, setup guidance and no files. R file paths are restricted
to known names, and completed outputs must match current warehouse source hashes.

### Discovery and replay reliability additions

`GET /orders` additionally accepts `order_status` (one of the eight source states),
`delivery_outcome=late|on_time|unavailable`, and repeated `order_ids` (up to 100 bounded
identifiers). The latter refreshes workflow state for an already scored page without
running inference. Rows now include historical status/outcome as browsing context;
these fields never enter the independently reconstructed checkout payload.
`review_counts` includes all five workflow states after cohort/status/outcome/ID
filters but before `review_status`; `cohort_total` is their sum. `total` remains the
count after the workflow filter, before pagination. Original fields are retained.

`GET /console/options` adds source order states, a warehouse snapshot token and the
active model manifest version. Replay adds `scored_at_utc`, `model_version`,
`warehouse_snapshot`, `candidate_count`, and `scored_count`. These describe exactly
one submitted batch, not a global ranking. If the warehouse changes during scoring,
409 asks the caller to retry. Optimistic review conflicts retain their existing 409
contract. Malformed discovery filters return 422. Operational updates do not invalidate
prediction inputs, because workflow data remains in the separate database.
