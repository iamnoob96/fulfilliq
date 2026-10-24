# Nested recency-adaptive calibration — 24 October 2026

Protocol recorded before fitting the new real-data experiment. This extends the
rolling evaluation, preserves every old result and promotion gate, and never
changes the active model. All purchases at/after the original protected test
boundary are removed before history construction.

## Nested chronology and candidate policies

Reuse the existing 180/60/30-day train/calibration/evaluation windows, 30-day
step, seven-day embargo, 14-day promise maturity and 60-day evaluation follow-up.
For each outer origin, selection occurs at its calibration-window end. Only
earlier inner evaluation windows that have fully ended before that cutoff can
participate. Their labels are re-filtered at the earlier of that cutoff and
their ordinary follow-up horizon. Unsupported inner windows are reported, not
filled with future labels. Use the latest three supported inner windows;
require three. Earlier outer origins lacking enough history are excluded.

Candidates: raw; fixed-window sigmoid; observation-recency-weighted sigmoid with
half-lives 30/60/90/180 days; and sigmoid using only outcomes observed in the
last 30/60 days. The latter filters the existing calibration purchase cohort,
not arbitrary future purchases. Recency uses delivery-plus-reporting-lag time,
not purchase time or deadline time. Exponential weights have mean one; minimum
support applies to effective sample size overall and within each class.

Selection reuses the existing minimum-three-fold, full-coverage, ranking-loss
and every-window Brier-skill gates. Among qualifying candidates maximize
worst-window Brier skill, then mean skill, then lower variability. If none
qualifies, use **raw fallback**, explicitly not a passing/adaptive improvement.
Outer results cannot affect this decision. The selected policy is evaluated
once on the later outer cohort, alongside fixed raw/sigmoid and prevalence
references; unselected adaptive policies receive no outer evaluation metrics.
If a selected configuration has insufficient effective calibration support at
the outer fit time, use an explicitly reported raw feasibility fallback instead
of dropping that outer evaluation population.

Base estimators and candidate probabilities may be cached by historical origin:
their training/calibration labels and features are fixed at that origin's fit
clocks. Inner evaluation membership and metrics are always re-filtered for the
current outer cutoff. Histories retain strict availability before prediction.
Thresholds are tuned only on the designated historical calibration cohort.
Calibration uses public scikit-learn metadata routing for sample weights. A
single prediction partition is safe because the underlying estimator is frozen;
it avoids redundant random cross-validation and never refits the base learner.
Observation recency is not purchase recency: a long-delayed historical order
can receive high weight when its outcome finally arrives. Exponential decay
therefore does not remove delayed-label selection bias.

## Outcome observation and sensitivity

Prediction equals purchase. Promise deadline, actual delivery, delivery plus
one-day reporting lag, and calibration fit cutoff are separate clocks. A passed
deadline is not an observed eventual-delivery label. Olist lacks the event audit
trail required for trustworthy early ascertainment; none is attempted.

Snapshot delivered/canceled/undelivered statuses are descriptive retrospective
categories, not reconstructed historical events. Missing delivery timestamps,
unavailable outcomes, promise maturity and coverage are reported separately.
Selected-policy sensitivity recomputes metrics under evaluation maturity buffers
0/14/30 days, keeping every calibration, threshold and selection fixed. This
does not tune policy or substitute on-time labels for incomplete orders.

Assumption bounds use only the eventual-delivered snapshot cohort with a valid
promise. Unknown outcomes receive hypothetical all-on-time/all-late prevalence
bounds and per-order minimum/maximum binary Brier loss bounds. Canceled and
undelivered targets are undefined and excluded from these bounds. Bounds are
not fabricated labels or claims about population-wide accuracy.

The same historical windows were previously inspected. Nesting prevents code
from using outer labels in selection; it cannot undo prior human inspection or
make this an independent future-production benchmark. Overlapping training
histories and reused inner windows also imply dependence; no IID significance
claim is made. No automatic promotion is permitted.

## Running and reproducing the experiment

```sh
uv run fulfilliq evaluate-adaptive-calibration
uv run fulfilliq evaluate-adaptive-calibration --half-lives 30 60 90 180 \
  --observation-windows 30 60 --min-inner-folds 3 --max-inner-folds 3 \
  --output artifacts/adaptive/my-study.json
```

All rolling-window/support parameters remain configurable through the existing
CLI conventions. Each half-life/window list is limited to four distinct positive
integers. Defaults use eight candidate policies; there is no estimator or
hyperparameter search. Output defaults to a UTC/UUID path under
`artifacts/adaptive/`. It includes full `.json`, `.md` and compact `.summary.json`
files; existing paths are rejected. Full reports contain repeated inner evidence
and remain local. Compact reports preserve all outer metrics and inner gate
evidence, and link to the full report by checksum. No model binaries are saved.

## Measured nested experiment

The frozen first run (`b847080`) completed **eight outer folds**, **24 inner
selection evaluations**, and **10 distinct historical inner origins**. Each outer
decision used the latest three supported inner windows. There were no fitting
failures. Four early outer origins lacked three historical inner windows; the
original schedule also excluded its sparse initial window and partial final
window crossing the protected boundary. No unsupported window was fabricated.

Outer evaluation spans 13 October 2017 to 10 June 2018 and contains **51,126
distinct matured orders**. The feature source remains the same 84,524
pre-protected purchases. All 14,917 purchases at/after the boundary, including
14,551 previously inspected test orders, remain excluded.

Only **12 base models** were fitted, with **20 prediction-cache hits**. The
first run took 53.23 seconds. A complete second run from `9a46188` exactly
reproduced all outer results, inner selections, censoring diagnostics and
summary metrics. All 64 checked raw/fixed-sigmoid reference metrics matched the
previous rolling experiment within 1e-12 on the identical windows. See
[compact measured evidence](results/adaptive-20261024-summary.json) and
[reproduction proof](results/adaptive-20261024-reproduction.json).

| Outer evaluation purchases | Selected policy | Raw fallback | N | Raw Brier | Fixed sigmoid Brier | Nested Brier |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 2017-10-13 to 2017-11-12 | raw | True | 4,324 | 0.05292 | 0.05303 | 0.05292 |
| 2017-11-12 to 2017-12-12 | sigmoid | False | 8,250 | 0.14156 | 0.13691 | 0.13691 |
| 2017-12-12 to 2018-01-11 | sigmoid | False | 5,003 | 0.04687 | 0.04628 | 0.04628 |
| 2018-01-11 to 2018-02-10 | weighted_sigmoid_30d | False | 6,889 | 0.06781 | 0.06697 | 0.07174 |
| 2018-02-10 to 2018-03-12 | raw | True | 7,045 | 0.18606 | 0.18578 | 0.18606 |
| 2018-03-12 to 2018-04-11 | raw | True | 6,630 | 0.11345 | 0.11553 | 0.11345 |
| 2018-04-11 to 2018-05-11 | raw | True | 7,381 | 0.04719 | 0.06088 | 0.04719 |
| 2018-05-11 to 2018-06-10 | sigmoid | False | 5,604 | 0.06350 | 0.06765 | 0.06765 |

Intervals are half-open. The weighted policy was selected using inner results
before the January outer window, then evaluated once. Its Brier **0.07174** was
worse than raw **0.06781** and fixed sigmoid **0.06697** in that window. Unselected
adaptive configurations have no outer-window performance estimates.

| Candidate | Outer selections |
| --- | ---: |
| raw | 4 |
| sigmoid | 3 |
| weighted_sigmoid_30d | 1 |
| weighted_sigmoid_60d | 0 |
| weighted_sigmoid_90d | 0 |
| weighted_sigmoid_180d | 0 |
| rolling_sigmoid_30d | 0 |
| rolling_sigmoid_60d | 0 |

All four raw choices were explicit fallbacks because no candidate passed every
inner gate. There were no outer support fallbacks in the real run. A controlled
regression test verifies that insufficient outer calibration support falls back
without discarding the evaluation cohort.

## Matched outer robustness comparison

All means below weight the same eight outer windows equally. **Do not compare
these means directly with the earlier twelve-window means** (0.07387/0.07405);
the nested study needs more initial history and evaluates a different subset.

| Procedure | Mean Brier | Worst Brier | Brier std | Worst skill vs recent prevalence | Mean ECE |
| --- | ---: | ---: | ---: | ---: | ---: |
| raw | 0.08992 | 0.18606 | 0.04835 | -0.0437 | 0.05868 |
| sigmoid | 0.09163 | 0.18578 | 0.04632 | -0.1994 | 0.06768 |
| nested_selected | 0.09027 | 0.18606 | 0.04734 | -0.0327 | 0.06557 |
| training_prevalence | 0.09477 | 0.20910 | 0.05477 | -0.0539 | 0.05981 |
| recent_prevalence | 0.09541 | 0.19841 | 0.05043 | 0.0000 | 0.07529 |

**Conclusion: adaptive selection did not establish improved reliability.** Its
mean Brier is worse than raw, and its worst absolute Brier is unchanged. The
worst relative regression against recent prevalence is smaller (3.27% versus
4.37% for raw and 19.94% for fixed sigmoid), but still fails the unchanged
nonnegative-every-window skill gate. This mixed result does not justify model
promotion or selecting a different grid after seeing the outer results.

Calibration preserved ranking on these outer windows. Raw, fixed sigmoid and
nested selection all have mean ROC-AUC **0.66372**, mean AP **0.18480**, and the
following identical window-mean budget metrics:

| Review capacity | Precision | Captured recall |
| --- | ---: | ---: |
| 5% | 0.24542 | 0.12712 |
| 10% | 0.21851 | 0.22070 |
| 20% | 0.18689 | 0.37603 |

All 24 real inner selections were checked to have evaluation windows ending
no later than the outer selection cutoff, with labels observed strictly before
it. All eight selected calibrators satisfy the same strict cutoff check. Tests
also perturb outer outcomes and verify unchanged configuration selection and
validation-selected thresholds. This proves code-level isolation, not immunity
from prior human inspection of the dataset.

## Censoring and eligibility sensitivity

The eight purchase cohorts contain **52,825 orders**: **51,452 delivered**,
**238 canceled**, and **1,135 in other snapshot statuses**. There are **1,374
missing delivery timestamps**. These final status counts are retrospective and
overlap the missing-time category. They are not historical event observations.

After the 60-day follow-up, **108 eventual-delivered outcomes** remain
unobservable under the conservative reporting clock. Hypothetical prevalence
bounds for the 51,452 eventual-delivered orders are **10.692%–10.901%**; binary
Brier bounds for their selected-policy probabilities are **0.09486–0.09650**.
Canceled/undelivered outcomes remain undefined; these are not all-order bounds.

Keeping every policy, calibration and threshold fixed gives these pooled
evaluation-population sensitivity results (sample-weighted across windows,
not the equal-window means above):

| Promise maturity buffer | Eligible orders | Late prevalence | Pooled nested Brier |
| --- | ---: | ---: | ---: |
| 0 days | 51,298 | 10.724% | 0.09510 |
| 14 days | 51,126 | 10.754% | 0.09534 |
| 30 days | 48,197 | 11.183% | 0.09870 |

The May window is particularly sensitive: changing the buffer from 0 to 30
days reduces support from **5,692 to 4,359**, raises measured prevalence from
**7.20% to 9.25%**, and changes selected-policy Brier from **0.06682 to 0.08248**.
This is a change in the evaluated population, not a change in model quality.
Changing the buffer was never used for policy selection or to manufacture a
passing robustness result.

## Decision and next objective

The original active model remains `20261024T031015-f87ea646`. No candidate
passed all outer consistency gates; all old validation requirements still apply.
No prior-probability-shift correction was added: observed covariate and ranking
drift do not support a pure prior-shift assumption. No early-late labels or
IID uncertainty intervals are claimed.

The next most valuable objective is an **availability-based, censoring-aware
calibration cohort built from out-of-time predictions**, evaluated with this
nested framework. Expanding a calibration purchase window into its training
cohort without cross-fitting would create in-sample calibration bias and should
be avoided. Independent future observations are still required for stronger
promotion evidence.
