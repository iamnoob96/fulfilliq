# Real Olist experimental results

The subsequent [nested recency-adaptive study](ADAPTIVE_CALIBRATION.md) evaluated
eight outer windows with 24 mature inner selections. On matched outer windows,
mean Brier was 0.08992 raw, 0.09163 fixed sigmoid and 0.09027 nested selection.
No procedure passed every consistency gate, and no promotion occurred. These
eight-window means must not be compared directly with earlier twelve-window
means. [Compact results](results/adaptive-20261024-summary.json) and
[determinism evidence](results/adaptive-20261024-reproduction.json) retain the
original measured provenance.

The later [rolling-origin calibration study](TEMPORAL_VALIDATION.md) preserves
the benchmarks below and excludes the inspected test cohort. It evaluated 12
historical windows (66,575 orders): no calibration policy beat a recent-prevalence
baseline in every window. Sigmoid was the least-worst ranking-safe research
candidate, with slightly worse mean Brier than raw probabilities; no model was
promoted. See the [original rolling report](results/temporal-20261024-v1.json) and
[exact-reproduction/matched-window evidence](results/temporal-analysis-20261024.json).

Executed 24 October 2026 on macOS/Apple Silicon, Python 3.11.3. These are actual outputs
from the pinned original CSVs. Full precision, source hashes, seeds, software versions,
split boundaries, thresholds and calibration bins are in [experiment.json](results/experiment.json).

## Delivery-risk comparison

| Candidate | Validation AP | Test precision | Recall | F1 | ROC-AUC | AP | Brier | Top 10% precision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| logistic_regression | 0.1190 | 0.0889 | 0.9655 | 0.1628 | 0.8141 | 0.2864 | 0.1649 | 0.2898 |
| random_forest | 0.1252 | 0.2105 | 0.5914 | 0.3105 | 0.7853 | 0.1798 | 0.0653 | 0.2163 |
| hist_gradient_boosting | 0.1470 | 0.1025 | 0.1735 | 0.1289 | 0.6483 | 0.0977 | 0.0684 | 0.1030 |

**Validation selected histogram gradient boosting**, with threshold 0.22624452. Candidate rankings reversed in the later test period. The stronger test ranking of another candidate does not change the validation-only promotion rule.

The test set has 14,551 orders and late prevalence 6.5769%. The selected model flags 11.13%; its confusion matrix is `[[12141, 1453], [791, 166]]` in TN/FP/FN/TP order. Top-decile precision is 10.3022%, or 1.566 times test prevalence.

The training-prevalence baseline Brier score is 0.061546, better than the selected model. Calibration and ranking are distinct: these probabilities require caution and forward validation. The API exposes this observed limitation. The default F1 threshold is an experimental investigation policy, not an optimal operational cost policy.

Training-period eligible count: 58,954. After an additional internal purge, 37,082 fit the base estimators and 14,739 calibrate them. Validation has 7,986 orders; test has 14,551. Another 2,971 orders are unlabeled and 14,979 are purged/immature at the outer boundaries. These exclusions are recorded rather than silently reassigned.

Observation availability uses delivery plus one day; maturity uses estimate plus 14 days. Validation begins 13 April 2018, test begins 20 June 2018, and the assumed observation cutoff is 17 October 2018. No preprocessing or estimator fits test rows. This is exploratory: initial test diagnostics were inspected during engineering, so it is not a blind external benchmark.

## Delivery-risk optimization sprint (same-day follow-up)

The original benchmark above is retained. The bounded follow-up ran from committed
code `1db8037`, in 31.95 seconds on the same environment and exact source hashes.
Full-precision outputs, frozen membership hashes, calibration bins, validation
comparisons and promotion gates are in
[risk-sprint-20261024.json](results/risk-sprint-20261024.json); the predeclared
method and feature definitions are in [RISK_SPRINT.md](RISK_SPRINT.md).

Two fixed estimators, each raw and sigmoid calibrated, were compared using
validation only. The chosen challenger is **raw histogram gradient boosting with
schema 2**, version `20261024T035136-9caf890e`. Schema 2 adds seller/route delivery
duration and promise slack, availability-indexed smoothed rates, route counts,
state-pair geography, interstate fraction, and freight/value ratio. Signed slack
and calendar/rate features avoid the original universal log transform.

| Validation candidate | AP | Precision at 10% | Brier |
| --- | ---: | ---: | ---: |
| Original calibrated HGB | 0.14697 | 0.18023 | 0.06967 |
| Schema 2 logistic, raw | 0.11320 | 0.13267 | 0.06621 |
| Schema 2 logistic, sigmoid | 0.11320 | 0.13267 | 0.07894 |
| Schema 2 HGB, raw (selected challenger) | 0.13657 | 0.16896 | 0.06517 |
| Schema 2 HGB, sigmoid | 0.13657 | 0.16896 | 0.07311 |

Only the selected challenger received a new held-out evaluation. Test membership
is unchanged: **14,551 orders, 957 late**. No test-driven iteration followed.

| Held-out metric | Original active model | Selected challenger |
| --- | ---: | ---: |
| Precision (validation F1 threshold) | 0.10253 | 0.13009 |
| Recall | 0.17346 | 0.53710 |
| F1 | 0.12888 | 0.20945 |
| ROC-AUC | 0.64829 | 0.72760 |
| AP (PR-AUC convention) | 0.09771 | 0.12774 |
| Brier score | 0.06842 | 0.05992 |
| Mean predicted probability | 0.12433 | 0.07315 |
| Actual late prevalence | 0.06577 | 0.06577 |
| Brier skill vs training constant | -0.11176 | 0.02637 |
| Validation-selected threshold | 0.22624 | 0.09387 |

| Review capacity | Reviewed | Baseline precision / recall | Challenger precision / recall |
| --- | ---: | ---: | ---: |
| Highest-risk 5% | 728 | 0.10577 / 0.08046 | 0.15934 / 0.12121 |
| Highest-risk 10% | 1,456 | 0.10302 / 0.15674 | 0.14560 / 0.22153 |
| Highest-risk 20% | 2,911 | 0.10374 / 0.31557 | 0.12951 / 0.39394 |

The challenger captures **212 versus 150** late orders within 1,456 reviews
(41.3% relative precision gain). Its F1 threshold flags approximately 27.2% of
orders, so it should not be confused with a 10% review policy. Budget metrics
rank the cohort independently of that threshold; ties use stable source order.

**Promotion decision: retain the original active model.** The challenger passes
all eight test/calibration gates but fails both validation ranking gates: AP
0.13657 versus 0.14697 and top-decile precision 0.16896 versus 0.18023. The
better test result does not override that rule. It is saved separately; the
active pointer remains `20261024T031015-f87ea646`. No deployed prediction
improvement is claimed.

### Calibration investigation and remaining weaknesses

Base-training prevalence is 5.56%, the reserved January–March calibration period
12.32%, validation 7.15%, and the final test 6.58%. On validation, removing only
the original model's sigmoid leaves AP unchanged at 0.14697 but lowers Brier
from 0.06967 to **0.06482**. This supports calibration-period drift as a problem;
it does not prove the cause of the change. That ablation was validation-only and
was not subsequently selected or tested as another challenger.

The deployable training-prevalence constant has test Brier **0.06155**; the
descriptive test-prevalence oracle is **0.06144** and is never used for fitting.
The challenger improves probability error modestly against the constant, but
ranking remains weak and seasonal generalization remains unresolved. Route
promise slack, distance, and historical route delivery duration lead the
challenger's validation permutation importance; correlated-feature importance
does not establish causality or isolate which change produced improvement.

The most valuable next experiment is rolling-origin validation across several
seasons with recent, maturity-safe calibration. Freeze a new future holdout
before further tuning: this existing test cohort has now been inspected and
cannot serve as independent evidence for another iteration. Static attribute
history, canceled-order selection bias, sparse routes and absent carrier-service
information remain limitations. No intervention benefit is established.

## Operational observations

The exact timestamp definition yields **7,826 / 96,470 eligible deliveries late (8.1124%)**. The legacy calendar-day definition remains **6,534 / 96,470 (6.7731%)**.

Across coherent milestones, mean approval is 0.4341 days, approval-to-carrier fulfillment 2.8592 days, carrier-to-delivery transit 9.3348 days, and purchase-to-delivery 12.5582 days. Their observation counts differ. Transit is the longest of the disjoint median stages in many regional cohorts; this is an investigative association, not a demonstrated carrier cause.

## Frequent patterns

At default cutoffs, both algorithms return **2,191 identical frequent itemsets** and one retained late-delivery rule:

- Antecedent: customer state RJ and primary seller state SP.
- Joint support: 1.3103% (1,264 late orders matching the rule).
- Confidence: 15.5512%; lift: 1.9170; leverage: 0.006268.

Apriori took 0.498 seconds and FP-Growth 0.594 seconds for mining itself in this run. This small, bounded transaction space does not demonstrate a universal runtime advantage. Full preprocessing/runtime is longer. No causal or held-out confirmation is claimed.

## Seller segments

K-Medoids selected two segments for **1,271 sellers**; **1,824** have fewer than ten orders and are excluded. Manhattan silhouette is **0.2830**, mean 80%-resample adjusted Rand stability **0.6663**. The stability is moderate and limits operational use of hard segment labels.

| Segment | Sellers | Median orders | Median late rate | Median fulfillment days |
| --- | ---: | ---: | ---: | ---: |
| 0 | 1,085 | 31 | 6.31% | 1.428 |
| 1 | 186 | 20 | 9.09% | 5.041 |

These measured profiles motivate reviewing the longer-fulfillment group, with due attention to case mix, small volumes and shared-order milestone attribution.

## Historical anomalies

Default screens flag **1,989 order-characteristic outliers**, **81 seller delay-rate groups**, **14 regional delay-rate groups**, and **71 seller fulfillment-duration groups**. Methods have different scores/thresholds and may flag the same seller. They are historical review candidates, not confirmed incidents or fraud. Global comparisons are not adjusted for seasonal or operational case mix.

## Portuguese review intelligence

There are **42,454** reviews with normalized title/message text. Themes overlap and use unverified lexical rules:

| Lexical theme | Matching reviews |
| --- | ---: |
| late_delivery | 1,421 |
| damaged_packaging | 156 |
| missing_or_incorrect_items | 3,720 |
| product_quality | 889 |
| positive_delivery | 7,023 |

The general sentiment baseline uses 25,349 unique earlier texts for training and 6,338 later texts for evaluation. Test accuracy is **95.0615%**, majority-baseline accuracy **73.7930%**, ROC-AUC **0.9814**, and macro F1 **0.9364**. Duplicate templates are excluded across periods; neutral stars are excluded.

Sentiment labels are noisy review stars, not verified logistics sentiment. Theme matching has no claimed precision/recall. Post-order review information does not enter the purchase-time model.

## Reproduction

Run `fulfilliq train`, `fulfilliq build-insights`, and `fulfilliq export-report` against the original sources and locked dependencies. Seeds are fixed; UUIDs, timestamps and runtime timings vary. Preserve full precision in the JSON when comparing repeated experiments. Raw data, record-level reports and binaries stay outside Git.

## Application integration — 2026-10-24

The internal Streamlit/Plotly operations console integrates eight pages with FastAPI:
warehouse overview, historical replay/review queue, logistics, sellers, mining, review
intelligence, read-only model evidence, and operational/R reports. Review decisions
persist in an independent SQLite database with token-protected revision-checked writes.
Real-data checks confirmed 99,441 order totals, 96,470 eligible delivered outcomes,
7,826 exact-time late orders and 3,095 active sellers. All eight pages rendered, 22 of
50 recent candidate orders could be reconstructed/scored, and unavailable records were
reported honestly. Direct checkout and replay scoring agreed; temporary workflow state
survived API recreation. Warehouse, model pointer and model binary SHA-256 values stayed
unchanged. The full regression suite passed **139 tests** with the console extra.

Optional R execution used R 4.5.2, arules 1.7.15, ggplot2 4.0.3 and jsonlite 2.0.0.
On 5,000 deterministic evenly spaced historical transactions, Python and R retained the
same one late-delivery rule at support >= .01, confidence >= .15, lift >= 1.1, max length
3. The SP-seller/RJ-customer rule had support **.0118**, confidence **.1501272265**, lift
**1.7872288865**, and support count **59**. Maximum cross-language metric difference was
**2.220446049250313e-15**. These subset figures differ from full-dataset mining because
the input population differs; this is reproducibility evidence, not a new causal or
predictive improvement claim. Both Python algorithms still agreed on all **2,191**
full-history frequent itemsets. Four R plots used real logistics inputs, including all
96,470 valid delivered orders for delivery plots.

The active delivery model was not optimized, refitted, recalibrated or promoted. Its original
version **20261024T031015-f87ea646** and its previously reported limitations remain.
See the [reproduction evidence](results/application-integration-20261024.json),
[application walkthrough](OPERATIONS_CONSOLE.md) and [R instructions](../r_analysis/README.md).
