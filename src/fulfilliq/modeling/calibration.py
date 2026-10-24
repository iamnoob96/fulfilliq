"""Small historical calibration policies; recency means outcome-observation time."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn import config_context
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator

from fulfilliq.features.risk_v2 import V2_FEATURES
from fulfilliq.modeling.evaluation import choose_threshold
from fulfilliq.modeling.rolling import RollingConfig, eligible_at


@dataclass(frozen=True)
class CalibrationPolicy:
    name: str
    half_life_days: int | None = None
    observation_window_days: int | None = None


def calibration_policies(half_lives=(30, 60, 90, 180), windows=(30, 60)) -> list[CalibrationPolicy]:
    for values in (half_lives, windows):
        if (
            len(values) > 4
            or len(set(values)) != len(values)
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 1
                for value in values
            )
        ):
            raise ValueError("Use at most four distinct positive integer half-lives/windows")
    return (
        [CalibrationPolicy("raw"), CalibrationPolicy("sigmoid")]
        + [
            CalibrationPolicy(f"weighted_sigmoid_{days}d", half_life_days=days)
            for days in half_lives
        ]
        + [
            CalibrationPolicy(f"rolling_sigmoid_{days}d", observation_window_days=days)
            for days in windows
        ]
    )


def recency_weights(observed_at: pd.Series, cutoff, half_life_days: int) -> np.ndarray:
    cutoff = pd.Timestamp(cutoff)
    if half_life_days <= 0 or observed_at.isna().any() or not observed_at.lt(cutoff).all():
        raise ValueError(
            "Recency requires positive half-life and outcomes strictly observed before cutoff"
        )
    age = (cutoff - observed_at).dt.total_seconds().to_numpy() / 86400
    weights = np.exp2(-age / half_life_days)
    if not len(weights) or not np.isfinite(weights).all() or weights.sum() <= 0:
        raise ValueError("No usable historical recency weights")
    return weights / weights.mean()


def effective_sample_size(weights) -> float:
    weights = np.asarray(weights, dtype=float)
    denominator = np.square(weights).sum()
    return float(weights.sum() ** 2 / denominator) if denominator > 0 else 0.0


def calibrate_predictions(
    pipeline,
    calibration: pd.DataFrame,
    evaluation_features: pd.DataFrame,
    cutoff,
    policies: list[CalibrationPolicy],
    config: RollingConfig,
):
    if not eligible_at(calibration, pd.Timestamp(cutoff), config.maturity_days).index.equals(
        calibration.index
    ):
        raise ValueError("Calibration contains unavailable or immature labels")
    x_cal, y_cal = calibration[V2_FEATURES], calibration.target_is_late.astype(int)
    raw_cal = pipeline.predict_proba(x_cal)[:, 1]
    predictions, unsupported = {}, []
    for policy in policies:
        selected = np.ones(len(calibration), dtype=bool)
        weights = np.ones(len(calibration))
        if policy.observation_window_days is not None:
            selected = calibration.label_available_at.ge(
                pd.Timestamp(cutoff) - pd.Timedelta(days=policy.observation_window_days)
            ).to_numpy()
        if policy.half_life_days is not None:
            weights = recency_weights(calibration.label_available_at, cutoff, policy.half_life_days)
        labels, subset_weights = y_cal.to_numpy()[selected], weights[selected]
        ess = effective_sample_size(subset_weights)
        class_ess = [effective_sample_size(subset_weights[labels == label]) for label in (0, 1)]
        if ess < config.min_observations or min(class_ess) < config.min_positives:
            unsupported.append(
                {
                    "policy": policy.name,
                    "reason": "Insufficient effective calibration support",
                    "observations": int(selected.sum()),
                    "effective_sample_size": ess,
                    "class_effective_sample_sizes": class_ess,
                }
            )
            continue
        if policy.name == "raw":
            values_cal, values_eval = raw_cal, pipeline.predict_proba(evaluation_features)[:, 1]
        else:
            indices = np.arange(int(selected.sum()))
            # The estimator is frozen: one partition avoids redundant random CV fits.
            calibrated = CalibratedClassifierCV(
                FrozenEstimator(pipeline), method="sigmoid", cv=[(indices, indices)]
            )
            with config_context(enable_metadata_routing=True):
                calibrated.fit(
                    x_cal.loc[selected], y_cal.loc[selected], sample_weight=subset_weights
                )
            values_cal = calibrated.predict_proba(x_cal)[:, 1]
            values_eval = calibrated.predict_proba(evaluation_features)[:, 1]
        predictions[policy.name] = {
            "calibration_probabilities": values_cal,
            "evaluation_probabilities": values_eval,
            "threshold": choose_threshold(y_cal, values_cal),
            "fit_audit": {
                "observations": int(selected.sum()),
                "effective_sample_size": ess,
                "class_effective_sample_sizes": class_ess,
                "last_outcome_observed": calibration.loc[selected, "label_available_at"]
                .max()
                .isoformat(),
                "cutoff": pd.Timestamp(cutoff).isoformat(),
            },
        }
    return predictions, unsupported
