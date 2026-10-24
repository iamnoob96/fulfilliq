"""Verify offline/API features and probabilities on actual source-schema orders.

Uses trusted local artifacts named in a completed experiment; never reads labels
for sample selection or computes evaluation metrics.
"""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from sqlalchemy import text

from fulfilliq.config import Settings
from fulfilliq.db.connection import make_engine
from fulfilliq.features.orders import load_orders, placement_features
from fulfilliq.features.risk_v2 import FEATURE_SCHEMAS, placement_v2
from fulfilliq.ingestion.download import write_json
from fulfilliq.ingestion.validation import sha256_file
from fulfilliq.modeling.contracts import OrderRequest
from fulfilliq.modeling.inference import request_features


def optional(value):
    return None if pd.isna(value) else float(value)


def check_parity(settings, report):
    orders, items = load_orders(settings.database_path)
    counts = items.groupby("order_id").seller_id.nunique()
    valid = orders[orders.estimated_at.ge(orders.purchased_at) & orders.order_id.isin(counts.index)]
    selected = list(valid.order_id.iloc[np.linspace(0, len(valid) - 1, 8, dtype=int)])
    selected += list(valid.loc[valid.order_id.isin(counts[counts > 1].index), "order_id"].head(8))
    selected = list(dict.fromkeys(selected))
    sample_orders = orders.loc[orders.order_id.isin(selected)].copy()
    sample_items = items.loc[items.order_id.isin(selected)].copy()
    engine = make_engine(settings.database_path, readonly=True)
    try:
        with engine.connect() as conn:
            dimensions = pd.read_sql_query(
                text(
                    "SELECT product_id, product_length_cm, product_height_cm, product_width_cm FROM products"
                ),
                conn,
            ).set_index("product_id")
    finally:
        engine.dispose()

    requests = []
    for row in sample_orders.itertuples():
        entries = []
        for item in sample_items.loc[sample_items.order_id.eq(row.order_id)].itertuples():
            dim = dimensions.loc[item.product_id]
            entries.append(
                dict(
                    seller_id=item.seller_id,
                    seller_state=item.seller_state,
                    product_category=item.category,
                    price=optional(item.price),
                    freight_value=optional(item.freight_value),
                    weight_g=optional(item.product_weight_g),
                    length_cm=optional(dim.product_length_cm),
                    height_cm=optional(dim.product_height_cm),
                    width_cm=optional(dim.product_width_cm),
                    seller_latitude=optional(item.seller_latitude),
                    seller_longitude=optional(item.seller_longitude),
                )
            )
        requests.append(
            OrderRequest(
                order_id=row.order_id,
                purchased_at=row.purchased_at.to_pydatetime(),
                estimated_delivery_at=row.estimated_at.to_pydatetime(),
                customer_state=row.customer_state,
                customer_latitude=optional(row.customer_latitude),
                customer_longitude=optional(row.customer_longitude),
                items=entries,
            )
        )

    results = {}
    for kind, version in [
        ("baseline", report["baseline_model_version"]),
        ("challenger", report["challenger_model_version"]),
    ]:
        folder = settings.artifact_dir / "delivery" / version
        metadata = json.loads((folder / "metadata.json").read_text())
        assert metadata["model_sha256"] == sha256_file(folder / "model.joblib")
        bundle = joblib.load(folder / "model.joblib")
        feature_version = metadata["feature_version"]
        placement = placement_v2 if feature_version == 2 else placement_features
        memberships = sample_items.groupby("order_id").seller_id.unique().apply(list).to_dict()
        offline = bundle["history"].enrich(placement(sample_orders, sample_items), memberships)[
            FEATURE_SCHEMAS[feature_version]
        ]
        online = request_features(requests, bundle["history"])
        assert_frame_equal(
            offline.sort_index(), online.sort_index(), check_dtype=False, rtol=1e-12, atol=1e-12
        )
        p1 = bundle["pipeline"].predict_proba(offline.sort_index())[:, 1]
        p2 = bundle["pipeline"].predict_proba(online.sort_index())[:, 1]
        np.testing.assert_allclose(p1, p2, rtol=1e-12, atol=1e-12)
        results[kind] = {
            "model_version": version,
            "feature_version": feature_version,
            "orders_checked": len(requests),
            "feature_columns": len(offline.columns),
            "feature_parity": "passed",
            "probability_parity": "passed",
        }
    results["selection"] = (
        "Eight evenly spaced purchases plus eight earliest multi-seller purchases; no outcome-based selection"
    )
    results["multi_seller_orders_checked"] = int((counts.reindex(selected) > 1).sum())

    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output exists; select a new path to preserve previous evidence")
    results = check_parity(Settings(), json.loads(args.experiment.read_text()))
    if args.output:
        write_json(args.output, results)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
