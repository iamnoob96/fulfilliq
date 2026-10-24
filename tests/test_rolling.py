import pandas as pd
import pytest

from fulfilliq.modeling.rolling import RollingConfig, eligible_at, rolling_folds


def config(**changes):
    return RollingConfig(
        **{
            **dict(
                train_days=90,
                calibration_days=45,
                evaluation_days=30,
                step_days=30,
                gap_days=3,
                maturity_days=2,
                min_observations=10,
                min_positives=2,
            ),
            **changes,
        }
    )


def test_windows_are_chronological_disjoint_mature_and_protected(training_frame):
    frame = training_frame.assign(prediction_at=training_frame.purchased_at)
    protected = pd.Timestamp("2017-12-01")
    folds, excluded = rolling_folds(frame, config(), protected_start=protected, as_of="2018-04-01")
    assert len(folds) >= 3
    assert excluded
    evaluated = set()
    for fold in folds:
        m = fold.metadata
        assert fold.train.purchased_at.max() < pd.Timestamp(m["train_end"])
        assert pd.Timestamp(m["train_end"]) < fold.calibration.purchased_at.min()
        assert fold.calibration.purchased_at.max() < pd.Timestamp(m["calibrator_fit_at"])
        assert pd.Timestamp(m["calibrator_fit_at"]) < fold.evaluation.purchased_at.min()
        assert fold.train.label_available_at.max() < pd.Timestamp(m["model_fit_at"])
        assert fold.calibration.label_available_at.max() < pd.Timestamp(m["calibrator_fit_at"])
        assert fold.evaluation.purchased_at.max() < protected
        assert not set(fold.train.index) & set(fold.calibration.index)
        assert not set(fold.evaluation.index) & evaluated
        evaluated.update(fold.evaluation.index)
        # Outcomes can mature after evaluation ends; fitting never uses them early.
        assert fold.evaluation.label_available_at.max() > pd.Timestamp(m["evaluation_end"])
        for audit in m["audits"].values():
            assert audit["purchase_cohort"] == audit["eligible"] + sum(
                audit[key]
                for key in (
                    "unlabeled",
                    "invalid_labeled_timestamps_or_target",
                    "outcome_not_observable",
                    "promise_not_mature",
                )
            )


def test_strict_availability_promise_maturity_and_unresolved(training_frame):
    frame = training_frame.iloc[:6].copy()
    cutoff = pd.Timestamp("2017-02-01")
    frame.loc[frame.index[0], "label_available_at"] = cutoff
    frame.loc[frame.index[1], "estimated_at"] = cutoff - pd.Timedelta(days=2)
    frame.loc[frame.index[2], "target_is_late"] = float("nan")
    frame.loc[frame.index[3], "label_available_at"] = pd.Timestamp("2030-01-01")
    selected = eligible_at(frame, cutoff, 2)
    assert set(selected.index) == set(frame.index[4:])


def test_future_and_protected_labels_cannot_change_earlier_membership(training_frame):
    frame = training_frame.copy()
    protected = pd.Timestamp("2017-12-01")
    original, _ = rolling_folds(frame, config(), protected_start=protected, as_of="2018-04-01")
    frame.loc[frame.purchased_at.ge(protected), "target_is_late"] = 0
    frame.loc[frame.purchased_at.ge(protected), "label_available_at"] = pd.Timestamp("2016-01-01")
    changed, _ = rolling_folds(frame, config(), protected_start=protected, as_of="2018-04-01")
    assert [fold.metadata for fold in original] == [fold.metadata for fold in changed]
    delayed = original[0].train.index[0]
    frame.loc[delayed, "label_available_at"] = pd.Timestamp("2030-01-01")
    changed, _ = rolling_folds(frame, config(), protected_start=protected, as_of="2018-04-01")
    assert delayed not in changed[0].train.index


def test_missing_class_and_small_folds_are_reported(training_frame):
    frame = training_frame.assign(target_is_late=0)
    folds, skipped = rolling_folds(
        frame, config(), protected_start="2018-01-01", as_of="2018-03-01"
    )
    assert not folds and all(
        "insufficient support" in row["reason"] or "exceeds" in row["reason"] for row in skipped
    )
    folds, skipped = rolling_folds(
        training_frame.iloc[:15], config(), protected_start="2017-03-01", as_of="2018-01-01"
    )
    assert not folds


@pytest.mark.parametrize(
    "changes",
    [
        {"train_days": 0},
        {"gap_days": -1},
        {"step_days": 29},
        {"min_positives": 0},
        {"evaluation_days": True},
    ],
)
def test_invalid_configuration(changes):
    with pytest.raises(ValueError):
        config(**changes)


def test_prediction_time_contract(training_frame):
    frame = training_frame.assign(prediction_at=training_frame.purchased_at + pd.Timedelta(days=1))
    with pytest.raises(ValueError, match="prediction timestamps"):
        rolling_folds(frame, config(), protected_start="2018-01-01", as_of="2018-03-01")


def test_invalid_labeled_times_and_nonbinary_targets_are_excluded(training_frame):
    frame = training_frame.iloc[:4].copy()
    frame.loc[frame.index[0], "target_is_late"] = 0.5
    frame.loc[frame.index[1], "estimated_at"] = frame.purchased_at.iloc[1] - pd.Timedelta(days=1)
    frame.loc[frame.index[2], "label_available_at"] = frame.delivered_at.iloc[2] - pd.Timedelta(
        days=1
    )
    assert list(eligible_at(frame, pd.Timestamp("2018-01-01"), 2).index) == [frame.index[3]]


def test_zero_embargo_and_duplicate_id_rejection(training_frame):
    folds, _ = rolling_folds(
        training_frame, config(gap_days=0), protected_start="2018-01-01", as_of="2018-04-01"
    )
    assert folds[0].metadata["train_end"] == folds[0].metadata["calibration_start"]
    assert folds[0].metadata["calibration_end"] == folds[0].metadata["evaluation_start"]
    frame = pd.concat([training_frame, training_frame.iloc[:1]])
    with pytest.raises(ValueError, match="unique"):
        rolling_folds(frame, config(), protected_start="2018-01-01", as_of="2018-04-01")
