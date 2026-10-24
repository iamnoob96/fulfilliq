# Real Olist experimental results

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
