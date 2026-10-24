"""Load trusted local artifacts once per version; never fit during inference."""

import json
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from fulfilliq.features.orders import FEATURE_VERSION, FEATURES, haversine_km, placement_features
from fulfilliq.ingestion.validation import sha256_file
from fulfilliq.modeling.contracts import OrderRequest, RiskResponse
from fulfilliq.modeling.training import dataset_identity


class ModelUnavailable(ValueError):
    pass


def request_features(requests: list[OrderRequest], history) -> pd.DataFrame:
    orders, items, memberships = [], [], {}
    for order in requests:
        orders.append(
            {
                "order_id": order.order_id,
                "purchased_at": order.purchased_at,
                "estimated_at": order.estimated_delivery_at,
                "customer_state": order.customer_state,
            }
        )
        memberships[order.order_id] = sorted({item.seller_id for item in order.items})
        for item in order.items:
            dimensions = (item.length_cm, item.height_cm, item.width_cm)
            volume = (
                float(np.prod(dimensions)) if all(v is not None for v in dimensions) else np.nan
            )
            distance = haversine_km(
                order.customer_latitude,
                order.customer_longitude,
                item.seller_latitude,
                item.seller_longitude,
            )
            for _ in range(item.quantity):
                items.append(
                    {
                        "order_id": order.order_id,
                        "product_id": "request-product",
                        "seller_id": item.seller_id,
                        "seller_state": item.seller_state,
                        "category": item.product_category,
                        "price": item.price,
                        "freight_value": item.freight_value,
                        "product_weight_g": item.weight_g,
                        "product_volume_cm3": volume,
                        "distance_km": float(distance),
                    }
                )
    item_frame = pd.DataFrame(items)
    for name in ("price", "freight_value", "product_weight_g", "product_volume_cm3", "distance_km"):
        item_frame[name] = pd.to_numeric(item_frame[name], errors="coerce")
    frame = placement_features(pd.DataFrame(orders), item_frame)
    return history.enrich(frame, memberships)[FEATURES]


class RiskService:
    def __init__(self, artifact_dir: Path, database_path: Path):
        self.artifact_dir, self.database_path = artifact_dir, database_path
        self.version = None
        self.bundle = None
        self.metadata = None
        self.database_mtime = None

    def load(self) -> dict:
        root = self.artifact_dir / "delivery"
        try:
            version = json.loads((root / "current.json").read_text())["version"]
            if not re.fullmatch(r"\d{8}T\d{6}-[0-9a-f]{8}", version):
                raise ValueError("Invalid model version manifest")
            if version != self.version:
                folder = root / version
                metadata = json.loads((folder / "metadata.json").read_text())
                if (
                    metadata["feature_version"] != FEATURE_VERSION
                    or metadata["features"] != FEATURES
                ):
                    raise ValueError("Model feature schema is incompatible; retrain")
                if sha256_file(folder / "model.joblib") != metadata["model_sha256"]:
                    raise ValueError("Model artifact checksum mismatch; retrain")
                # joblib is trusted code: only this application's locally trained files are accepted.
                bundle = joblib.load(folder / "model.joblib")
                self.version, self.metadata, self.bundle = version, metadata, bundle
                self.database_mtime = None
            mtime = self.database_path.stat().st_mtime_ns
            if self.database_mtime != mtime:
                if (
                    dataset_identity(self.database_path)["source_sha256"]
                    != self.metadata["dataset"]["source_sha256"]
                ):
                    raise ValueError("Database inputs changed since training; retrain the model")
                self.database_mtime = mtime
            return self.metadata
        except Exception as exc:
            raise ModelUnavailable(f"Model unavailable: {exc}. Run 'fulfilliq train'.") from exc

    def predict(self, requests: list[OrderRequest]) -> list[RiskResponse]:
        metadata = self.load()
        frame = request_features(requests, self.bundle["history"])
        with threadpool_limits(limits=2):
            probabilities = self.bundle["pipeline"].predict_proba(frame)[:, 1]
        predictions = []
        for order, probability in zip(requests, probabilities, strict=True):
            row = frame.loc[order.order_id]
            flagged = probability >= metadata["threshold"]
            rationale = [
                f"Estimated delay probability {probability:.1%}; "
                f"validation-selected threshold {metadata['threshold']:.1%}."
            ]
            if row.seller_history_count:
                rationale.append(
                    f"{int(row.seller_history_count)} observed seller/order outcomes "
                    f"in the trailing history window; "
                    f"{row.seller_history_late_rate:.1%} were late."
                )
            if np.isfinite(row.distance_km):
                rationale.append(
                    f"Approximate item-weighted shipping distance: {row.distance_km:.0f} km."
                )
            rationale.append("These are contextual observations, not causal feature attributions.")
            warnings = []
            if not row.seller_history_count:
                warnings.append(
                    "No seller outcomes available in the historical observation window."
                )
            if order.purchased_at < pd.Timestamp(metadata["split"]["validation_start"]):
                warnings.append(
                    "Purchase predates model training cutoff; this is a retrospective score."
                )
            if order.purchased_at > pd.Timestamp(metadata["split"]["observation_cutoff"]):
                warnings.append(
                    "Purchase is outside the historical Olist observation period; "
                    "current-domain validity is unverified."
                )
            predictions.append(
                RiskResponse(
                    order_id=order.order_id,
                    delay_probability=float(probability),
                    threshold=metadata["threshold"],
                    risk_category="high" if flagged else "standard",
                    model_version=metadata["model_version"],
                    recommendation=(
                        "Prioritize investigation of the promised lead time and seller readiness."
                        if flagged
                        else "Use the standard monitoring queue."
                    ),
                    rationale=rationale,
                    warnings=warnings,
                )
            )
        return predictions
