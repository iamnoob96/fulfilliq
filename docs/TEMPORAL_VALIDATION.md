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

## Running the framework

```sh
uv run fulfilliq evaluate-temporal
uv run fulfilliq evaluate-temporal --train-days 180 --calibration-days 60 \
  --evaluation-days 30 --step-days 30 --gap-days 7 --maturity-days 14 \
  --followup-days 60 --min-observations 500 --min-positives 30 \
  --isotonic-min-observations 1000 --isotonic-min-positives 100 \
  --output artifacts/temporal/my-study.json
```

The default output is a new UTC/UUID path under `artifacts/temporal/`, with an
adjacent Markdown summary. Explicit JSON/Markdown collisions are rejected.
Exit status is zero for a complete run, and one for no supported folds, fitting
failures or invalid configuration. Excluded unsupported windows are listed even
when the remaining run completes. No dependencies, API routes, serving model
files or model pointer are changed. `--db-path` and `--artifact-dir` follow the
existing CLI conventions. The validated source hashes and original protected
boundary are read from the compatible active artifact; this command cannot move
the protected boundary through a CLI option.

## Fold-by-fold results

All metrics below are measured on the same immutable first run. The follow-up
audit/reproduction from `8e8d8d6` exactly matched all **57 policy/fold metric
objects, 12 membership sets and 12 drift profiles**. See
[reproduction and matched-window analysis](results/temporal-analysis-20261024.json).
Runtime was 43.95 seconds for the first run. There are **66,575 distinct matured
evaluation orders**, all purchased before the protected boundary; 84,524 orders
remain in the pre-protected feature source. All 14,917 purchases at/after the
boundary are excluded, covering the 14,551 previously inspected test orders.
No model, serving pointer or old benchmark was replaced.

Intervals below are half-open. AP means average precision. F1 and budget metrics
in these tables use the raw policy; every policy's full metrics, thresholds,
5/10/20% precision/recall and reliability bins are in the structured report.

| Evaluation purchases | N | Late % | Raw ROC-AUC | Raw AP | Raw F1 | Raw Brier | Sigmoid Brier | Isotonic Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2017-06-15 to 2017-07-15 | 3,207 | 3.55 | 0.4998 | 0.0363 | 0.0686 | 0.03543 | 0.03897 | 0.03960 |
| 2017-07-15 to 2017-08-14 | 3,890 | 3.32 | 0.6214 | 0.0493 | 0.0846 | 0.03276 | 0.03197 | insufficient support |
| 2017-08-14 to 2017-09-13 | 4,094 | 3.98 | 0.5802 | 0.0549 | 0.0687 | 0.05238 | 0.03820 | insufficient support |
| 2017-09-13 to 2017-10-13 | 4,258 | 4.93 | 0.6760 | 0.1067 | 0.1646 | 0.04643 | 0.04645 | insufficient support |
| 2017-10-13 to 2017-11-12 | 4,324 | 5.62 | 0.6457 | 0.0976 | 0.1503 | 0.05292 | 0.05303 | 0.05284 |
| 2017-11-12 to 2017-12-12 | 8,250 | 14.99 | 0.6009 | 0.2031 | 0.0913 | 0.14156 | 0.13691 | 0.13725 |
| 2017-12-12 to 2018-01-11 | 5,003 | 4.82 | 0.5679 | 0.0635 | 0.0939 | 0.04687 | 0.04628 | 0.04655 |
| 2018-01-11 to 2018-02-10 | 6,889 | 7.32 | 0.6572 | 0.1405 | 0.2006 | 0.06781 | 0.06697 | 0.06699 |
| 2018-02-10 to 2018-03-12 | 7,045 | 22.58 | 0.6729 | 0.3601 | 0.4158 | 0.18606 | 0.18578 | 0.18176 |
| 2018-03-12 to 2018-04-11 | 6,630 | 13.94 | 0.7128 | 0.3111 | 0.3735 | 0.11345 | 0.11553 | 0.11401 |
| 2018-04-11 to 2018-05-11 | 7,381 | 4.71 | 0.6857 | 0.1027 | 0.1309 | 0.04719 | 0.06088 | 0.06229 |
| 2018-05-11 to 2018-06-10 | 5,604 | 7.32 | 0.7665 | 0.1998 | 0.2691 | 0.06350 | 0.06765 | 0.06770 |

| Evaluation start | P@5% / recall | P@10% / recall | P@20% / recall |
| --- | ---: | ---: | ---: |
| 2017-06-15 | 0.0435 / 0.0614 | 0.0280 / 0.0789 | 0.0358 / 0.2018 |
| 2017-07-15 | 0.0564 / 0.0853 | 0.0540 / 0.1628 | 0.0476 / 0.2868 |
| 2017-08-14 | 0.0585 / 0.0736 | 0.0634 / 0.1595 | 0.0684 / 0.3436 |
| 2017-09-13 | 0.1549 / 0.1571 | 0.1221 / 0.2476 | 0.1021 / 0.4143 |
| 2017-10-13 | 0.1521 / 0.1358 | 0.0947 / 0.1687 | 0.1029 / 0.3663 |
| 2017-11-12 | 0.2349 / 0.0784 | 0.2400 / 0.1601 | 0.2152 / 0.2870 |
| 2017-12-12 | 0.0637 / 0.0664 | 0.0659 / 0.1369 | 0.0569 / 0.2365 |
| 2018-01-11 | 0.2000 / 0.1369 | 0.1698 / 0.2321 | 0.1335 / 0.3651 |
| 2018-02-10 | 0.4703 / 0.1043 | 0.4298 / 0.1904 | 0.3825 / 0.3388 |
| 2018-03-12 | 0.4277 / 0.1537 | 0.3831 / 0.2749 | 0.3084 / 0.4426 |
| 2018-04-11 | 0.1514 / 0.1609 | 0.1367 / 0.2902 | 0.1083 / 0.4598 |
| 2018-05-11 | 0.2633 / 0.1805 | 0.2282 / 0.3122 | 0.1873 / 0.5122 |

Excluded origins:

- 2017-05-16: only 336 mature training observations, including four positives.
- 2018-06-10: a full 30-day evaluation would cross the protected boundary.

## Calibration stability and recommendation

Means below weight windows equally; standard deviation describes temporal
variability, not an independent-sample standard error. Unequal-coverage isotonic
results require the matched comparison below.

| Policy | Folds | Mean Brier | Worst Brier | Brier std | Mean ECE | Worst recent-baseline Brier skill |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| raw | 12 | 0.07387 | 0.18606 | 0.04577 | 0.05158 | -0.3702 |
| sigmoid | 12 | 0.07405 | 0.18578 | 0.04535 | 0.05272 | -0.1994 |
| isotonic | 9 | 0.08544 | 0.18176 | 0.04552 | 0.06654 | -0.2272 |
| training_prevalence | 12 | 0.07583 | 0.20910 | 0.05224 | 0.04201 | -0.0539 |
| recent_prevalence | 12 | 0.07662 | 0.19841 | 0.04911 | 0.05764 | 0.0000 |

On the nine identical isotonic-supported windows:

| Policy | Mean Brier | Mean ECE | Mean AP | Mean P@10% |
| --- | ---: | ---: | ---: | ---: |
| raw | 0.08387 | 0.05534 | 0.16830 | 0.19735 |
| sigmoid | 0.08578 | 0.06741 | 0.16830 | 0.19735 |
| isotonic | 0.08544 | 0.06654 | 0.15600 | 0.19095 |

**Recommendation: no universally reliable calibration policy qualifies.** Retain
the active serving model and use these findings to design the next experiment.
Sigmoid is only the **least-worst ranking-safe research candidate** under the
predeclared worst-window criterion: its worst relative Brier skill is -19.94%,
versus -37.02% for raw. It preserves raw AP/risk ranking in every evaluated fold,
but has slightly worse mean Brier and ECE. This is not evidence of a blanket
improvement. Isotonic lacks support in three folds and reduces matched mean AP
and review precision through tied scores. None should be promoted from this run.

## Temporal drift findings

- Mature evaluation prevalence ranges from **3.32% to 22.58%**. The November
  2017 and February 2018 windows reach 14.99% and 22.58%; these are observed
  temporal regimes, not proof of a recurring annual seasonal cause.
- Recent calibration prevalence can lag the evaluation population substantially.
  In the April 2018 fold it is 12.35% versus 4.71% in evaluation; sigmoid Brier
  worsens from raw 0.04719 to 0.06088. In February it is 7.23% versus 22.58%.
  A fixed calibration policy cannot be assumed to track changing prevalence.
- Ranking changes independently: raw ROC-AUC ranges from **0.4998 to 0.7665**
  and AP from **0.0363 to 0.3601**. AP depends on prevalence; these changes do
  not isolate an improvement in conditional ranking. Calibration alone cannot
  repair a weak ranker.
- Median known shipping distance ranges from **376.3 to 475.2 km**; median
  promised lead time ranges from **21.38 to 27.42 days**. Median aggregate
  product weight ranges from **600 to 967 g**. These feature shifts coexist
  with outcome changes but do not establish their causes.
- Customer-state total-variation distance from each training cohort ranges
  from **0.0191 to 0.0788**; category distance ranges from **0.1041 to 0.1797**.
  New sellers comprise **28.0% to 40.2% of distinct evaluation sellers** versus
  each training cohort; this is a seller denominator, not an order fraction.
  Only **4.08% to 6.91% of evaluation orders** lack observed seller outcomes.
- Aggregate weight missingness falls from roughly **1.49%** in the first
  evaluation cohort to **0.22%** in the last, with nonmonotone intermediate
  values. Full feature missingness and train-binned PSI are preserved per fold.

## Maturity and interpretation limits

The follow-up audit partitions every excluded observation into unlabeled,
invalid labeled times/target, unavailable outcome, or observed outcome with an
immature promise. Counts reconcile exactly. The audit also records the actual
first/last eligible purchase, last delivery and last available label per window.
For example, calibration cohorts lose 4,406–10,217 observations across these
folds; many already-observed deliveries are still excluded by the unchanged
promise-plus-14-day rule. Calibration population selection and stale labels
are therefore plausible contributors, alongside input and prevalence drift.
This is an association and a limitation, not a claim that one factor causes error.

The 60-day outcome follow-up reduces rapid-delivery selection in evaluation,
but does not remove delivered-order selection or extreme-delay censoring.
Calibration and F1 threshold tuning reuse the same historical fitting window;
only later evaluation metrics are out of that window. ECE depends on binning
and sample size. Overlapping training histories create dependence across folds;
no IID bootstrap intervals or significance claims are made.

Every rolling window has now been inspected during policy research. Any future
promotion still requires the existing validation ranking/calibration gates and
new independent forward evidence; the previously inspected test cohort remains
protected. The next most valuable experiment is **nested rolling evaluation of
a recency-adaptive calibration policy with explicit delayed-label/censoring
sensitivity**, rather than selecting a lookback on these same reported scores.
