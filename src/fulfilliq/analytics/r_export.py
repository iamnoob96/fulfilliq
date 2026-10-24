"""Deterministic R inputs and cross-language verification, with no estimator fitting."""

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from fulfilliq.analytics.operations import OperationsService
from fulfilliq.config import Settings
from fulfilliq.features.orders import build_dataset
from fulfilliq.ingestion.download import write_json
from fulfilliq.mining.patterns import mine_patterns, transactions
from fulfilliq.mining.segments import seller_features
from fulfilliq.modeling.training import dataset_identity


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_r_inputs(settings: Settings, output: Path, *, sample_size: int = 5000) -> dict:
    if not 100 <= sample_size <= 20000:
        raise ValueError("R comparison subset must contain 100–20000 orders")
    output.mkdir(parents=True, exist_ok=True)
    frame, _, orders, items = build_dataset(settings.database_path)
    eligible = frame.loc[frame.target_is_late.notna()].sort_values(["purchased_at"], kind="stable")
    subset = eligible.iloc[np.linspace(0, len(eligible) - 1,
                                      min(sample_size, len(eligible)), dtype=int)]
    # Invalidate an earlier completed run before replacing any inputs.
    (output / "manifest.json").unlink(missing_ok=True)
    with (output / "transactions.csv").open("w", newline="") as stream:
        csv.writer(stream).writerows(transactions(subset))
    python_rules = mine_patterns(subset, min_support=.01, min_confidence=.15, min_lift=1.1)
    write_json(output / "python-rules.json", python_rules)
    plotting = eligible[["customer_state", "distance_km", "purchased_at"]].copy()
    plotting["delivery_days"] = (eligible.delivered_at - eligible.purchased_at).dt.total_seconds() / 86400
    plotting["late"] = eligible.target_is_late.astype(int)
    plotting.to_csv(output / "logistics.csv", index=False)
    sellers = seller_features(orders, items)
    sellers.to_csv(output / "sellers.csv", index=False)
    service = OperationsService(settings.database_path)
    pd.DataFrame(service.performance("region")).drop(columns="durations").to_csv(
        output / "regions.csv", index=False)
    files = ("transactions.csv", "python-rules.json", "logistics.csv", "sellers.csv", "regions.csv")
    manifest = {
        "schema_version": 1, "dataset": dataset_identity(settings.database_path),
        "transaction_count": len(subset), "plot_order_count": len(plotting),
        "selection": "Evenly spaced eligible delivered orders across purchase timestamp/order_id order; deterministic, no outcome stratification.",
        "first_purchase": subset.purchased_at.min().isoformat(),
        "last_purchase": subset.purchased_at.max().isoformat(),
        "parameters": python_rules["parameters"],
        "sha256": {name: sha256(output / name) for name in files},
        "interpretation": "Identical full baskets and fixed bins in Python/R. These are exploratory "
        "outcome associations, not prediction-time features or causal claims. R rule filtering keeps "
        "only outcome=late as sole consequent; lift filtering occurs after Apriori.",
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def verify_r_outputs(settings: Settings, inputs: Path, output: Path) -> dict:
    manifest = json.loads((inputs / "manifest.json").read_text())
    (output / "summary.json").unlink(missing_ok=True)
    for name, expected in manifest["sha256"].items():
        if sha256(inputs / name) != expected:
            raise ValueError(f"R input changed after export: {name}")
    if manifest["dataset"]["source_sha256"] != dataset_identity(settings.database_path)["source_sha256"]:
        raise ValueError("R input warehouse differs from current warehouse")
    run = json.loads((output / "r-session.json").read_text())
    # R copies the exact manifest before analysis; require byte equality, not a declared filename.
    if (output / "input-manifest.json").read_bytes() != (inputs / "manifest.json").read_bytes():
        raise ValueError("R outputs were generated from a different input manifest")
    python = json.loads((inputs / "python-rules.json").read_text())["rules"]
    with (output / "rules.csv").open(newline="") as stream:
        r_rules = list(csv.DictReader(stream))
    expected = {tuple(row["antecedents"]): row for row in python}
    observed = {tuple(sorted(row["antecedents"].split("|"))): row for row in r_rules}
    if len(observed) != len(r_rules) or expected.keys() != observed.keys():
        raise ValueError("Python/R rule identities differ")
    maximum = 0.0
    for key, row in expected.items():
        for metric in ("support", "confidence", "lift"):
            error = abs(row[metric] - float(observed[key][metric]))
            if not pd.notna(error) or error > 1e-8:
                raise ValueError(f"Python/R metric differs: {metric}")
            maximum = max(maximum, error)
    required = ["delivery-duration.png", "regional-delay.png", "distance-duration.png",
                "seller-performance.png", "region-summary.csv", "rules.csv"]
    if any(not (output / name).is_file() for name in required):
        raise ValueError("R run is incomplete; expected plots/tables are missing")
    comparison = {"rules_compared": len(expected), "all_rules_agree": True,
                  "maximum_absolute_metric_error": maximum, "tolerance": 1e-8}
    write_json(output / "comparison.json", comparison)
    summary = {"dataset": manifest["dataset"], "input_sha256": manifest["sha256"],
               "transaction_count": manifest["transaction_count"],
               "plot_order_count": manifest["plot_order_count"],
               "parameters": manifest["parameters"], "comparison": comparison,
               "r_session": run, "interpretation": manifest["interpretation"]}
    write_json(output / "summary.json", summary)
    return summary
