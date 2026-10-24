"""Purged purchase-time splits: no label learned after the next period begins."""

from dataclasses import dataclass

import pandas as pd


@dataclass
class TemporalSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    metadata: dict


def calibration_partition(train: pd.DataFrame, *, maturity_days: int = 14):
    """Reserve the latest quarter of training for calibration; purge earlier labels."""
    train = train.sort_values("purchased_at", kind="stable")
    boundary = train.purchased_at.iloc[int(len(train) * 0.75)]
    base = train.loc[
        train.purchased_at.lt(boundary)
        & train.label_available_at.lt(boundary)
        & (train.estimated_at + pd.Timedelta(days=maturity_days)).lt(boundary)
    ]
    calibration = train.loc[train.purchased_at.ge(boundary)]
    for name, subset in (("base training", base), ("calibration", calibration)):
        if len(subset) < 5 or subset.target_is_late.astype(int).nunique() != 2:
            raise ValueError(f"{name} needs at least five mature orders and both classes")
    return base, calibration, boundary


def chronological_split(
    frame: pd.DataFrame,
    *,
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
    maturity_days: int = 14,
    as_of=None,
) -> TemporalSplit:
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1 - train_fraction:
        raise ValueError("Fractions must leave nonempty train, validation and test periods")
    if maturity_days < 0:
        raise ValueError("Maturity days cannot be negative")
    frame = frame.sort_values(["purchased_at"], kind="stable")
    valid = frame.target_is_late.notna() & frame.purchased_at.notna()
    eligible = frame.loc[valid]
    if len(eligible) < 30:
        raise ValueError("At least 30 eligible orders are required for chronological evaluation")
    # Boundaries depend on purchase dates, not class values, feature distributions or performance.
    dates = frame.loc[frame.purchased_at.notna(), "purchased_at"].sort_values()
    validation_start = dates.iloc[int(len(dates) * train_fraction)]
    test_start = dates.iloc[int(len(dates) * (train_fraction + validation_fraction))]
    as_of = pd.Timestamp(as_of) if as_of is not None else dates.max()
    lag = pd.Timedelta(days=maturity_days)

    def mature(boundary):
        return eligible.label_available_at.lt(boundary) & (eligible.estimated_at + lag).lt(boundary)

    train_period = eligible.purchased_at.lt(validation_start)
    validation_period = eligible.purchased_at.ge(validation_start) & eligible.purchased_at.lt(
        test_start
    )
    test_period = eligible.purchased_at.ge(test_start)
    train = eligible.loc[train_period & mature(validation_start)].copy()
    validation = eligible.loc[validation_period & mature(test_start)].copy()
    test = eligible.loc[test_period & mature(as_of)].copy()
    periods = {"train": train, "validation": validation, "test": test}
    for name, subset in periods.items():
        if len(subset) < 5 or subset.target_is_late.astype(int).nunique() != 2:
            raise ValueError(f"{name} needs at least five mature orders and both outcome classes")
    metadata = {
        "validation_start": validation_start.isoformat(),
        "test_start": test_start.isoformat(),
        "observation_cutoff": as_of.isoformat(),
        "maturity_days": maturity_days,
        "rule": "labels and estimated date + maturity buffer strictly before next boundary",
        "counts": {name: len(subset) for name, subset in periods.items()},
        "excluded_unlabeled": int((~valid).sum()),
        "purged_or_immature": int(len(eligible) - sum(map(len, periods.values()))),
        "periods": {
            name: {
                "first_purchase": subset.purchased_at.min().isoformat(),
                "last_purchase": subset.purchased_at.max().isoformat(),
                "last_label_available": subset.label_available_at.max().isoformat(),
                "late_rate": float(subset.target_is_late.astype(int).mean()),
            }
            for name, subset in periods.items()
        },
    }
    return TemporalSplit(train, validation, test, metadata)
