# Data Mining syllabus mapping

| Concept | Implementation and reason |
| --- | --- |
| Data warehousing / OLAP | Nine normalized SQLite sources plus order facts, customer/seller/product/date dimensions and many-to-many bridges. Explicit grain prevents multiplied values and supports operational slicing. |
| Data preprocessing | Schema/key validation, timestamp/numeric coercion, missingness/duplicate reports, safe aggregation, geographic approximation, imputation, log transforms, scaling and categorical encoding. |
| Frequent itemsets | Apriori and FP-Growth operate on identical discretized transactions. Itemset support equality is checked; measured wall-clock times describe the current workload. |
| Association analysis | Delay consequents with support/confidence/lift/leverage. Fixed bins and bounded itemset lengths improve interpretability; associations do not establish causes. |
| Classification | Logistic Regression is a linear baseline, Random Forest tests bagging/nonlinearity, and histogram gradient boosting provides CPU-efficient boosting without another XGBoost native dependency. |
| Honest evaluation | Purged chronological base/calibration/validation/test periods, explicit outcome availability, validation-only candidate/threshold choice, PR/ROC metrics, Brier/calibration and risk-decile precision. |
| Clustering | Robust-scaled seller profiles with alternate-update K-Medoids use actual exemplar sellers and Manhattan distances. KMeans is a baseline; silhouette and resample ARI measure separation/stability. |
| Advanced mining / outliers | Isolation Forest screens rare characteristics; Wilson intervals and robust dispersion identify unusual seller/region summaries. Scores are not confirmed incidents or fraud. |
| Text mining | Portuguese normalization and negation-aware stop words, lexical themes, TF-IDF terms and Logistic Regression with explicitly noisy star-based sentiment labels. Evaluation excludes duplicated templates. |
| Interpretability / operationalization | Validation permutation importance, measured segment profiles, explicit anomaly reasons, contextual scoring rationale, investigation recommendations and typed APIs. |

Offline batch services generate saved artifacts; FastAPI consumes them. SQLite and Pandas
fit this roughly 100,000-order local project without distributed frameworks, microservices,
mandatory cloud storage, a GPU, frontend or live event infrastructure.
