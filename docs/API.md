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
validation permutation importance. Test performance does not drive model promotion.

`GET /health` retains its original response: 200 for a valid database, otherwise 503 with
database missing/invalid. This is database readiness, not model readiness. Required model
or report failures return 503 with recovery instructions; invalid inputs are 422. Changed
input hashes require retraining/rebuilding, while reingesting identical sources remains
compatible. Paging beyond the end returns an empty list with the filtered total.
