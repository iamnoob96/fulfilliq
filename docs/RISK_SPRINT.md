# Delivery risk optimization protocol — 24 October 2026

This protocol is recorded before challenger fitting or new test evaluation. The
original benchmark remains in RESULTS.md and results/experiment.json. Active
baseline: 20261024T031015-f87ea646 (calibrated histogram gradient boosting).

## Frozen evaluation and selection

Preserve source hashes, exact-timestamp target, one-day outcome reporting lag,
180-day history, and 14-day promised-date maturity policy. Retain chronological
boundaries 2018-04-13T21:53:34 / 2018-06-20T16:28:15 and observation cutoff
2018-10-17T17:30:18. Expected retained train/validation/test: 58,954/7,986/14,551.
Persist sorted order-ID membership hashes; refuse a mismatch against the baseline
split metadata or dataset identity. Do not change the held-out population.

Bounded design: two estimators (regularized logistic regression and histogram
gradient boosting), each raw and sigmoid calibrated. Fit base estimators on the
same purged earlier training partition as the baseline; fit sigmoid only on the
reserved latest training quarter. No class weighting: it changes probability
priors and is unnecessary for a rank/budget objective. Select the candidate by
validation precision at 10% review capacity, then average precision, then lower
Brier score. Select its decision threshold by validation F1 only. Examine the
test predictions once, only for the selected challenger and the fixed baseline.

Promotion requires validation top-decile precision and AP at least the baseline,
and validation Brier no worse than a constant probability estimated on training.
On the final test, require at least 20% relative top-decile precision gain, AP and
ROC-AUC no worse than the baseline, Brier no worse than both the baseline and
training-prevalence constant, and recall at 5% and 20% capacity no more than
0.01 absolute below baseline. Otherwise retain the active model. These are
engineering gates, not a claim of statistical significance or causal benefit.

The test prevalence oracle (p*(1-p)) is descriptive only; never use test
prevalence to calibrate, choose thresholds, or select a candidate. Report Brier
skill relative to the deployable training-prevalence constant as well.

## Audit findings

The existing history implementation excludes delivery outcomes unavailable at
purchase and deduplicates seller/order membership. It already guards temporal
label maturity. Primary limitations: geography represented by separate states
rather than routes; unregularized sparse seller rates; no historical end-to-end
delivery duration; universal log transforms on calendar/rate fields; model
selection based only on AP; no budget recall; calibration drift. Existing
validation calibration bins show substantial overprediction. Purchase-time
product, seller and promised-date fields remain static-data assumptions because
Olist has no attribute revision log. Reviews, final status and current-order
milestones remain excluded.

Continuous historical queries can use earlier test deliveries only after their
reporting lag has elapsed before a later order: this simulates online updating,
not estimator fitting on test labels. Model parameters stay frozen.

## Feature schema 2

Retain schema 1 and add freight / merchandise value (unknown for zero/missing
value), item-weighted interstate fraction, primary seller-state/customer-state
route, observed seller and route mean purchase-to-delivery days, promise minus
those observed means, route observation count, and smoothed seller/route delay
rates. Primary state retains the existing lexicographic convention; the history
queries use **all** distinct sellers and routes, not only the primary one.

History is indexed by actual delivery plus one day, queried strictly before
purchase over the trailing 180 days. Seller observations are distinct
seller/order pairs; routes are distinct seller-state/customer-state/order pairs.
For a multi-seller order, pool the available seller observations; shared historic
orders can contribute once for each distinct seller. A route contributes once
per state pair, even with multiple sellers in that state. No item duplication.
Smoothed rate = (late count + 20 * past global late rate) / (count + 20). The
global prior uses the same availability/window restrictions and counts each
order once. Cold sellers use that prior; without any available global history
the rate is unknown. Unknown durations remain missing. Delivery duration uses
only delivered, nonnegative-duration outcomes; unavailable deliveries never enter
the aggregates. This is contextual evidence rather than causal attribution.

Shared placement and history code generates both training and API features.
Schema 1 artifacts remain loadable; schema 2 requires matching history metadata.

Schema 2 preprocessing logs positive magnitudes/counts and promised lead time;
calendar values, rates, duration means and signed slack are median-imputed and
scaled without logs. Missing-value indicators and unknown-category handling are
retained. Both estimators use the existing fixed hyperparameters (seed 42), with
no additional search. The old model without its sigmoid is measured on
validation only as a calibration ablation; it is not a promotion candidate.

`fulfilliq experiment-risk --output docs/results/risk-sprint-20261024.json`
runs the protocol and preserves the active pointer. Add `--promote-if-qualified`
to apply the predeclared gates. Existing output paths are rejected. The selected
challenger is saved as a separate version even when it fails; no other
challenger is evaluated on test. Aggregate reports are safe to commit; local
model/history binaries remain ignored. Retraining the original `train` command
still uses the original schema-1 workflow; use this experiment command to
reproduce the sprint rather than silently changing the historical benchmark.

For feature/inference parity on real source records after the experiment:

```sh
python scripts/check_risk_feature_parity.py --experiment artifacts/risk-experiment.json
```

This compares both saved feature schemas and predicted probabilities on 16
deterministically sampled purchases, including multi-seller examples. It uses
the source product dimensions and coordinates to reconstruct API payloads;
selection never uses outcome labels. Optional `--output` writes a new aggregate
report; existing output paths are rejected. It does not activate either model.

Subsequent API work adds optional `review_capacity` and a separate
`review_order_ids` queue. This ranks the submitted cohort without changing
probabilities, the model version or the legacy F1-threshold queue. No new global
high/medium/low categories are assigned: validation-relative percentile cutoffs
would not guarantee a fixed workload under drift. The active model's existing
high/standard semantics remain explicit in the API documentation.
