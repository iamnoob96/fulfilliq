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
