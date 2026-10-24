# Optional R component

Run these commands from the repository root, after ingestion. R is optional; the
console and all Python services run without it and display an unavailable state
until a completed, verified R report exists.

Install R from CRAN (tested: R 4.5.2 on macOS Apple Silicon), then install packages
into the project's ignored local directory:

```sh
mkdir -p data/processed/R-library
Rscript -e 'install.packages(c("arules", "ggplot2", "jsonlite"), repos="https://cloud.r-project.org", lib="data/processed/R-library")'
uv run fulfilliq export-r
Rscript r_analysis/analyze.R data/processed/r_inputs artifacts/r_analysis
uv run fulfilliq verify-r
```

The Python export does **not** fit any prediction or clustering model. It reuses
existing leakage-safe feature construction and the existing transaction encoder.
Mining comparison uses 5,000 evenly spaced valid delivered orders across the complete
purchase/identifier ordering (`export-r --sample-size` accepts 100–20,000). Selection does not stratify on late
outcomes; spanning history avoids an unrepresentative early-only slice. Each basket has nine
unique `field=value` tokens: customer state, primary seller state, primary category,
distance band, value band, freight band, weight band, historical seller late-rate
band, and observed late/on-time outcome. Fixed bins are defined in
`src/fulfilliq/mining/patterns.py` and saved in `python-rules.json`. Unknown values
have explicit tokens. Multi-seller/category orders use the existing documented
primary summaries, not one basket per item. Outcomes are legitimate mining items,
never checkout risk inputs.

The basket CSV contains no header, no identifiers, nine comma-separated tokens per
row. R `arules::read.transactions(format="basket", sep=",")` reads exactly the same
transactions. Python mlxtend Apriori and FP-Growth verify their itemsets agree. Both
Python and R use support 0.01, confidence 0.15, lift >= 1.1 and maximum length 3
(including consequent); only `outcome=late` is retained as the sole consequent and
outcome tokens are excluded from antecedents. R's default rule measures also include
coverage/count; only support/confidence/lift are cross-language comparison targets.
Antecedents are serialized with `|` and compared as sorted item sets.

`verify-r` verifies input hashes, warehouse provenance, copied input manifest, exact
rule identities and all three metrics within 1e-8, plus required output presence.
It publishes `summary.json` only on success. Starting a new R run invalidates that
completion marker. The API checks warehouse provenance before exposing known report
files; arbitrary paths cannot be served. Do not edit generated inputs or outputs.
Python mining timings can vary; transactions and selected rules are deterministic.

Plots use **all** valid delivered orders for delivery duration, regional late rates,
and ZIP-centroid distance versus duration. The fourth plot shows the full seller
late-rate distribution and includes low-volume sellers; it is descriptive, not a
ranking of statistically reliable outliers. Regions and seller counts use the same
backend calculations. Missing distance observations are excluded by ggplot. CSV,
JSON and PNG outputs appear in **Reports & R**. They are generated locally, ignored
by Git, and can be reproduced with these commands. A small actual execution summary
is retained under `docs/results/application-integration-20261024.json`.
