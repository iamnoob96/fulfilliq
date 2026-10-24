import numpy as np
import pandas as pd
import pytest

from fulfilliq.modeling.calibration import (
    calibration_policies,
    effective_sample_size,
    recency_weights,
)
from fulfilliq.modeling.censoring import censoring_diagnostics
from fulfilliq.modeling.rolling import eligible_at


def test_recency_uses_observation_age_and_normalized_half_life():
    times = pd.Series(pd.to_datetime(["2018-01-01", "2018-01-31"]))
    weights = recency_weights(times, "2018-02-01", 30)
    assert weights[1] / weights[0] == pytest.approx(2)
    assert weights.mean() == pytest.approx(1)
    assert 1 < effective_sample_size(weights) < 2
    assert effective_sample_size([]) == 0
    assert effective_sample_size([0, 0]) == 0


@pytest.mark.parametrize("at", ["2018-02-01", "2018-02-02", None])
def test_unavailable_recency_observations_are_rejected(at):
    with pytest.raises(ValueError, match="strictly observed"):
        recency_weights(pd.Series(pd.to_datetime([at])), "2018-02-01", 30)


def test_candidate_grid_is_bounded_and_explicit():
    policies = calibration_policies()
    assert len(policies) == 8 and policies[0].name == "raw"
    for half_lives in [(0,), (30, 30), (1, 2, 3, 4, 5)]:
        with pytest.raises(ValueError):
            calibration_policies(half_lives)


def test_deadline_passed_is_not_an_observed_label(training_frame):
    frame = training_frame.iloc[:1].copy()
    frame["label_available_at"] = pd.Timestamp("2018-02-01")
    assert frame.estimated_at.iloc[0] < pd.Timestamp("2018-01-31")
    assert eligible_at(frame, pd.Timestamp("2018-01-31"), 14).empty


def test_censoring_reports_unknowns_without_assigning_labels(training_frame):
    frame = training_frame.iloc[:6].copy()
    frame["target_is_late"] = frame.target_is_late.astype(float)
    frame.loc[frame.index[0], "order_status"] = "canceled"
    frame.loc[frame.index[0], ["target_is_late", "delivered_at", "label_available_at"]] = [
        np.nan,
        pd.NaT,
        pd.NaT,
    ]
    frame.loc[frame.index[1], "label_available_at"] = pd.Timestamp("2019-01-01")
    original = frame.target_is_late.copy()
    scores = pd.Series(0.2, index=frame.index)
    report = censoring_diagnostics(frame, "2018-01-01", scores, 0.1)
    assert report["snapshot_status_counts"]["canceled"] == 1
    assert report["missing_delivery_timestamps"] == 1
    bounds = report["eventually_delivered_bounds"]
    assert bounds["population"] == 5 and bounds["unobserved_outcomes"] == 1
    assert bounds["late_prevalence_upper"] - bounds["late_prevalence_lower"] == pytest.approx(1 / 5)
    assert bounds["brier_upper"] >= bounds["brier_lower"]
    pd.testing.assert_series_equal(frame.target_is_late, original)
