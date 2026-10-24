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
