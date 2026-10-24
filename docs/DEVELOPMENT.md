# End-to-end implementation checklist

Preserve the validated ingestion baseline. Use local checks and conventional commits;
never commit datasets, databases, per-order exports, models or secrets. No GitHub Actions.

- [x] Inspect source, schema, dependencies, tests, reports and existing Git state.
- [ ] Preserve the baseline in Git and connect the authenticated account's private repository.
- [ ] Build a shared order-placement contract and strictly historical feature generation.
- [ ] Train/evaluate chronological classifiers, persist the selected pipeline and metadata.
- [ ] Add filtered fulfillment analytics and reproducible analytical persistence.
- [ ] Implement Apriori/FP-Growth, seller segmentation and historical anomaly detection.
- [ ] Implement Portuguese review intelligence and a defensible sentiment baseline.
- [ ] Integrate typed APIs, batch prediction, explanations and failure responses.
- [ ] Validate real data workflows, documentation, regressions and remote commits.

The prediction target requested for the completed system is exact timestamp comparison.
The existing `stats` command and `fact_orders.is_late` retain their original calendar-day
definition for compatibility. New model metrics and operational intelligence must state
their timestamp definition explicitly; never mix the two in an evaluation denominator.
