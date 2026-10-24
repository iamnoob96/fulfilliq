"""Purchase-time rolling origins with separate fit and outcome-observation clocks."""

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass(frozen=True)
class RollingConfig:
    train_days: int = 180
    calibration_days: int = 60
    evaluation_days: int = 30
    step_days: int = 30
    gap_days: int = 7
    maturity_days: int = 14
    followup_days: int = 60
    min_observations: int = 500
    min_positives: int = 30
    isotonic_min_observations: int = 1000
    isotonic_min_positives: int = 100

    def __post_init__(self):
        for name, value in asdict(self).items():
            minimum = 0 if name in {"gap_days", "maturity_days"} else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if self.step_days < self.evaluation_days:
            raise ValueError(
                "Step must be at least evaluation days; evaluation cohorts must not overlap"
            )
        if self.min_positives < 1:
            raise ValueError("Both classes must have observations")


@dataclass
class RollingFold:
    fold_id: str
    train: pd.DataFrame
    calibration: pd.DataFrame
    evaluation: pd.DataFrame
    train_cohort: pd.DataFrame
    evaluation_cohort: pd.DataFrame
    metadata: dict


def eligible_at(cohort: pd.DataFrame, cutoff: pd.Timestamp, maturity_days: int) -> pd.DataFrame:
    """Strict availability and promise maturity; delivery time never defines purchase cohorts."""
    return cohort.loc[
        cohort.target_is_late.notna()
        & cohort.delivered_at.ge(cohort.purchased_at)
        & cohort.label_available_at.ge(cohort.delivered_at)
        & cohort.label_available_at.lt(cutoff)
        & (cohort.estimated_at + pd.Timedelta(days=maturity_days)).lt(cutoff)
    ].copy()


def rolling_folds(frame: pd.DataFrame, config: RollingConfig, *, protected_start, as_of):
    protected_start, as_of = pd.Timestamp(protected_start), pd.Timestamp(as_of)
    if pd.isna(protected_start) or pd.isna(as_of):
        raise ValueError("Protected boundary and observation cutoff must be valid timestamps")
    if not frame.index.is_unique:
        raise ValueError("Order IDs must be unique")
    if "prediction_at" in frame and not frame.prediction_at.equals(frame.purchased_at):
        raise ValueError("Placement prediction timestamps must equal purchase timestamps")
    data = frame.loc[frame.purchased_at.lt(protected_start)].sort_values(
        "purchased_at", kind="stable"
    )
    if data.empty:
        return [], [{"reason": "No purchases before the protected test boundary"}]

    def delta(days):
        return pd.Timedelta(days=days)

    origin = data.purchased_at.min().normalize() + delta(
        config.train_days + config.calibration_days + 2 * config.gap_days
    )
    folds, excluded = [], []
    while origin < protected_start:
        evaluation_end = origin + delta(config.evaluation_days)
        calibration_end = origin - delta(config.gap_days)
        calibration_start = calibration_end - delta(config.calibration_days)
        train_end = calibration_start - delta(config.gap_days)
        train_start = train_end - delta(config.train_days)
        observation_cutoff = min(evaluation_end + delta(config.followup_days), as_of)
        metadata = {
            "fold_id": origin.strftime("%Y%m%dT%H%M%S"),
            "train_start": train_start.isoformat(),
            "train_end": train_end.isoformat(),
            "model_fit_at": train_end.isoformat(),
            "calibration_start": calibration_start.isoformat(),
            "calibration_end": calibration_end.isoformat(),
            "calibrator_fit_at": calibration_end.isoformat(),
            "evaluation_start": origin.isoformat(),
            "evaluation_end": evaluation_end.isoformat(),
            "outcome_observation_cutoff": observation_cutoff.isoformat(),
        }
        if evaluation_end > protected_start or evaluation_end > as_of:
            excluded.append(
                {
                    **metadata,
                    "reason": "Full evaluation window exceeds protected boundary or snapshot",
                }
            )
            origin += delta(config.step_days)
            continue

        def cohort(start, end):
            return data.loc[data.purchased_at.ge(start) & data.purchased_at.lt(end)].copy()

        contexts = {
            "train": cohort(train_start, train_end),
            "calibration": cohort(calibration_start, calibration_end),
            "evaluation": cohort(origin, evaluation_end),
        }
        cutoffs = {
            "train": train_end,
            "calibration": calibration_end,
            "evaluation": observation_cutoff,
        }
        subsets = {
            name: eligible_at(values, cutoffs[name], config.maturity_days)
            for name, values in contexts.items()
        }
        audits, reasons = {}, []
        for name, subset in subsets.items():
            labels = subset.target_is_late.astype(int)
            positives, negatives = int(labels.sum()), int((labels == 0).sum())
            audits[name] = {
                "purchase_cohort": len(contexts[name]),
                "eligible": len(subset),
                "excluded": len(contexts[name]) - len(subset),
                "unlabeled": int(contexts[name].target_is_late.isna().sum()),
                "positives": positives,
                "negatives": negatives,
                "last_label_available": subset.label_available_at.max().isoformat()
                if len(subset)
                else None,
            }
            if (
                len(subset) < config.min_observations
                or min(positives, negatives) < config.min_positives
            ):
                reasons.append(
                    f"{name}: {len(subset)} eligible, {positives} positive, {negatives} negative; insufficient support"
                )
        metadata["audits"] = audits
        if reasons:
            excluded.append({**metadata, "reason": "; ".join(reasons)})
        else:
            folds.append(
                RollingFold(
                    metadata["fold_id"],
                    subsets["train"],
                    subsets["calibration"],
                    subsets["evaluation"],
                    contexts["train"],
                    contexts["evaluation"],
                    metadata,
                )
            )
        origin += delta(config.step_days)
    return folds, excluded
