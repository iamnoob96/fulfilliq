import numpy as np
import pytest

from fulfilliq.modeling.evaluation import evaluate


def test_review_budgets_capture_delays_with_stable_ties():
    labels = np.zeros(100, dtype=int)
    labels[:10] = 1
    scores = np.linspace(1, 0, 100)
    result = evaluate(labels, scores, 0.5)
    assert result["review_budgets"]["5"] == {
        "reviewed_orders": 5,
        "late_orders_captured": 5,
        "precision": 1.0,
        "recall": 0.5,
    }
    assert result["review_budgets"]["10"]["recall"] == 1
    assert result["review_budgets"]["20"]["precision"] == 0.5
    tied = evaluate(labels, np.full(100, 0.1), 0.5)
    assert tied["review_budgets"]["5"]["precision"] == 1
    assert result["precision_at_top_10_percent"] == 1


@pytest.mark.parametrize("scores", [[np.nan, 0.5], [np.inf, 0.5], [-0.1, 0.5], [1.1, 0.5]])
def test_invalid_probability_rejected(scores):
    with pytest.raises(ValueError, match="finite probabilities"):
        evaluate([0, 1], scores, 0.5)


def test_fractional_labels_are_not_silently_truncated():
    with pytest.raises(ValueError, match="binary labels"):
        evaluate([0, 0.5], [0.1, 0.8], 0.5)
