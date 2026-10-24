# Operational mining and review intelligence

All modules describe historical Olist observations. None establishes intervention effects,
fraud, an active disruption, a seller's intent, or guaranteed benefits from investigation.
No ordinary API request runs a miner, fits a classifier, or regenerates artifacts.

## Association rules

The console presents Apriori, FP-Growth, or a side-by-side comparison. Per-algorithm time and
itemset counts come from the saved full-history mining snapshot. Selecting one algorithm changes
the method explanation and benchmark context; the itemsets and rules remain the shared result
that was checked for equal support. These saved runtimes describe one historical machine/run,
not a reliable prediction of which algorithm will be faster on another workload.

Console filters and sorting only select rows from this snapshot. The API includes the source
mining thresholds and report timestamp. A requested cutoff below a saved threshold cannot
recover patterns that were omitted; rerun the explicit offline `fulfilliq build-insights
--module rules` command to create a new snapshot. Dashboard date/region/seller/category filters
do not apply to mining, clustering or anomaly snapshots. Itemset/rule exports are bounded to
the currently filtered page and include raw item tokens for reproducibility.

One transaction represents one eligible delivered order. The target is exact timestamp
lateness. Attributes include customer state, lexicographic primary seller state/category,
fixed distance, item-value, freight, weight and backward-looking seller-delay bands.
Missing values receive an explicit `unknown` token. Numeric bins are left-closed,
right-open and are recorded in the report; they are domain cutoffs, not continuous numbers
passed directly into Apriori. Item value excludes freight, which has its own attribute.

Apriori (memory-saving mode) and FP-Growth mine the identical Boolean transaction matrix
with the same support and maximum itemset length. Their itemset/support maps must agree.
Elapsed wall-clock times are measured on the current machine and are not universal speed
claims. Rules retain only the singleton consequent `outcome=late`, prohibit outcome tokens
in antecedents, and report support, confidence, lift, leverage and support count. There are
no duplicate exact-value/derived-band tokens. A single state/category summary avoids a
combinatorial set of redundant membership attributes, while sacrificing some basket detail.

The defaults require 1% joint support, 15% confidence, lift >=1.1 and itemsets of length
at most three. This favors interpretable, supported associations, not rare single-seller
rules. These are exploratory full-history findings without held-out confirmation or
multiple-comparison correction. Rule confidence is a subgroup late rate, not a causal effect
or a substitute for the purchase-time risk model. Canceled/undelivered orders have no known
delay label and do not enter these rules.

## Seller segmentation

The Data Mining page displays the saved segment summaries, medians and evaluation measures;
it does not refit clusters. Seller assignments are fetched by selected segment and bounded page.
Compare a seller's observed historical features with its cluster medians before opening its
Seller Intelligence record. Segment names repeat measured rates and volumes rather than
assigning unsupported labels.

Each seller/order pair contributes once to volume and outcome rates. Features are volume,
median coherent approval-to-carrier duration, late rate, average item freight, average
item shipping distance, mean seller-specific order value and category diversity. Value
sums are complete only when all contributing item prices/freight are known. Shared-order
milestones are associated with every seller, since Olist has no per-seller dispatch event.

Nonnegative skewed size/value features use log1p; missing values use seller-population
medians, then robust scaling. The alternate-update K-Medoids implementation uses Manhattan
distances and chooses k=2..5 by silhouette. Medoids are actual sellers, with deterministic
farthest-point initialization and a bounded iteration count. This is a local optimum,
not exhaustive PAM. A full pairwise matrix is practical for Olist's roughly 3,000 sellers;
the implementation refuses >5,000 eligible sellers and recommends sampled CLARA instead.
Low-volume sellers (default fewer than ten orders) are explicitly excluded, not assigned
an invented segment. Segment names quote measured median delay rates and volumes.

A seeded KMeans baseline reports its Euclidean silhouette. Stability refits K-Medoids on
three independent 80% seller subsets, assigns all sellers to their new medoids and reports
adjusted Rand indices. Low stability is a limitation to report, not hide. The different
KMeans/medoid distance metrics mean their silhouette values need that context.

## Anomaly screening

The console separates unusual orders, sellers, regions and slow-fulfillment sellers. It displays
the method's own evidence and threshold for the selected category. Isolation Forest scores,
Wilson interval bounds and robust duration cutoffs have different meanings and must not be
ranked on one shared scale. Order flags link to order review; seller flags link to seller
history. A flag is a historical investigation candidate, not a confirmed incident.

Isolation Forest fits the full historical checkout-characteristic population, using
log-transformed, imputed and robust-scaled counts, values, freight, weight, volume, distance
and promised lead. The default tail threshold is the empirical 98th percentile of anomaly
scores. Ties can yield slightly more than 2% flags. Output includes the score, threshold,
observed values and the largest robust deviations. This uses a global historical reference;
it is not a deployment-time novelty detector or a matched-cohort disruption monitor.

Seller/region delay screens require at least 20 observed outcomes and compare a 95% Wilson
lower bound with the global late-rate upper bound. A separate seller fulfillment screen
uses the median plus three robust deviations. These are transparent prioritization rules,
not corrected significance tests. Case mix, seasonality, dependence between shared orders
and multiple comparisons can explain flags. Thresholds and volume minima are configurable.

## Portuguese NLP

Raw text stays in the source tables. NLP lowercases, strips accents, URLs/email-like tokens,
digits/punctuation and normalizes whitespace. A curated Portuguese function-word list
retains `nao`, `sem` and `nunca` because negation matters. It uses no English sentiment model,
paid API, downloaded language model, or expensive external service.

Overlapping lexical themes describe late delivery, damaged packaging, missing/incorrect
items, product quality and positive delivery experiences. Simple negated-delay phrases
such as `sem atraso` are handled. These rules have no manually verified complaint labels;
no theme precision/recall is claimed. Sarcasm, misspellings and complex negation remain
limitations. TF-IDF terms help interpret each matched theme. Seller/category/region
counts use distinct review/membership pairs and are non-additive across shared orders.
Review-filter endpoints select aggregate groups, not arbitrary joint raw-text cohorts.

A separate TF-IDF + Logistic Regression baseline learns noisy **general sentiment** from
stars 1–2 versus 4–5, excluding neutral 3-star examples. It retains only the earliest copy
of each normalized text so identical templates cannot leak across evaluation periods.
The first 80% of authored review timestamps train the vectorizer/classifier, and later
timestamps are the test set; equal timestamps stay in the same period. Accuracy, ROC-AUC,
class precision/recall/F1, confusion matrix and a majority baseline are recorded. A small
fixture with insufficient texts/classes reports that fact without fabricating a trained
model. Stars do not supply ground truth for logistical complaints, and these post-order
analyses never feed the same order's purchase-time model.

## Persistence

`artifacts/insights/{operations,rules,segments,anomalies,reviews}.json` are individually
atomic snapshots with source CSV hashes and schema version. Stale inputs cause HTTP 503
until reports/models are regenerated. Reingesting identical sources remains compatible.
All generated record-level reports and joblib models are ignored by Git; only small
aggregate experimental summaries in `docs/results/` are committed. This is a local
single-writer workflow. Regeneration may replace snapshots one module at a time, so their
generation times can differ while source provenance stays identical.
