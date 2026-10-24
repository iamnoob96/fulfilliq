# Temporal robustness protocol — 24 October 2026

This protocol precedes the rolling experiment. It does not replace the original
validation gates or authorize model promotion. The inspected test cohort is
excluded: **all purchases on or after the active model's original test boundary**
(2018-06-20T16:28:15) are removed before feature history construction. No results
from that cohort guide this sprint. Existing benchmarks remain unchanged.

## Clocks and windows

Prediction time equals purchase time. Delivery time determines the exact existing
late target; outcome availability is delivery plus the existing one-day reporting
lag. These are different timestamps. Historical feature queries continue to use
strict availability before purchase, with a 180-day trailing window.

Defaults: 180-day rolling training purchases, seven-day embargo, 60-day
calibration/threshold-validation purchases, seven-day embargo, 30-day evaluation
purchases, then advance 30 days. Origins are derived from the earliest available
purchase and configured durations, not targets. Intervals are half-open; no
partial final fold is fabricated. Evaluation purchase cohorts cannot overlap.
Each retained partition requires at least 500 observations and 30 examples of
each class; undersized or single-class windows are reported as excluded.

Training labels must be observable strictly before the training window ends;
calibration labels strictly before its window ends. Both also require promised
delivery plus the unchanged 14-day buffer strictly before that cutoff. This
purges immature examples instead of moving them to a different partition.
Evaluation uses a separate observation horizon: evaluation end plus 60 days,
capped at the recorded snapshot cutoff. Otherwise short windows would favor
fast deliveries. Purchases remain before the protected boundary, even when
their delivery outcomes are observed later. Unresolved/censored outcomes are
excluded from supervised metrics and counted explicitly. This is not a survival
model; delivered-order and residual censoring bias remain.

## Bounded comparisons and advisory selection

Use one fixed schema-2 histogram gradient boosting configuration (existing seed
42 and hyperparameters), fitted separately per fold. Compare raw, sigmoid and
isotonic probabilities using only that fold's designated calibration window.
Isotonic additionally requires 1,000 calibration samples and 100 of each class;
these are conservative engineering support cutoffs, not statistical guarantees.
Compare constant probabilities from training and recent calibration prevalence.
No calibration or threshold fitting uses evaluation outcomes. F1 thresholds are
selected on the historical calibration/threshold-validation window; it is used
for fitting policy, not reported as independent performance evidence.

Report all fold metrics, fixed-bin calibration error/reliability, probability
distributions, review-budget precision/recall, and mean/worst/variability across
windows. Calibration can change ranking through isotonic ties or an inverted
sigmoid, so operational ranking is measured explicitly. Constant-predictor
budget ranking uses stable time order and has no meaningful ranking skill.

Advisory recommendation requires at least three valid folds, coverage of every
valid fold, no fitting failures, AP and top-decile precision losses versus raw
no larger than 0.01 absolute in any fold, and nonnegative Brier skill versus the
recent-calibration prevalence constant in every fold. Among qualifying policies,
maximize worst-window Brier skill, then mean skill, then lower variability.
If no policy qualifies, report that no consistently superior policy was found;
also identify the least-worst fully covered ranking-safe policy for investigation.
This conservative screen is descriptive historical backtesting, not promotion.

Feature drift uses purchase cohorts (including unlabeled orders), separately from
the matured metric population. Report seller activity/new-seller exposure,
numeric distributions and missingness, train-binned population stability indices,
and state/category distribution changes. These are associations, not causes.

## Initial measured run

The first complete run from code `32b5e77` completed 12 valid folds, excluded two
windows, and had no fitting failures. No calibration policy passed every
consistency gate; sigmoid was the least-worst ranking-safe policy. Original
outputs are preserved in [structured results](results/temporal-20261024-v1.json)
and the [generated summary](results/temporal-20261024-v1.md).

Subsequent reporting checks add disjoint maturity-exclusion accounting and an
isotonic comparison on exactly matched windows. Isotonic's nine-window mean
must not be compared directly with raw/sigmoid's twelve-window mean. These
reporting improvements do not change model configurations, predictions or the
predeclared advisory gates.
