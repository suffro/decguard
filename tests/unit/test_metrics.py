"""Metric values checked against hand computations (and scikit-learn/NumPy conventions)."""

from __future__ import annotations

import math

import pytest

from decguard.contracts import Evaluation
from decguard.decisions import DecisionResult, DecisionSpec, DecisionType
from decguard.metrics import compute_metrics, core
from decguard.runner import CaseError, CaseRecord

EXPECTED = ["a", "a", "b", "c"]
PREDICTED = ["a", "b", "b", "a"]


def test_accuracy() -> None:
    assert core.accuracy(EXPECTED, PREDICTED) == 0.5
    assert core.accuracy([], []) is None


def test_macro_f1_matches_sklearn_definition() -> None:
    # a: P=1/2 R=1/2 F1=1/2; b: P=1/2 R=1 F1=2/3; c: P=0 R=0 F1=0
    assert core.macro_f1(EXPECTED, PREDICTED, ["a", "b", "c", "d"]) == pytest.approx(
        (0.5 + 2 / 3 + 0.0) / 3
    )
    scores = core.per_label_scores(EXPECTED, PREDICTED, ["a", "b", "c"])
    assert scores["b"].precision == 0.5
    assert scores["b"].recall == 1.0
    assert scores["c"].support == 1


def test_nll_and_brier() -> None:
    probabilities = [
        {"a": 0.7, "b": 0.2, "c": 0.1},
        {"a": 0.4, "b": 0.5, "c": 0.1},
    ]
    assert core.nll(["a", "a"], probabilities) == pytest.approx(
        -(math.log(0.7) + math.log(0.4)) / 2
    )
    # (0.3^2 + 0.2^2 + 0.1^2 + 0.6^2 + 0.5^2 + 0.1^2) / 2
    assert core.brier(["a", "a"], probabilities) == pytest.approx((0.14 + 0.62) / 2)


def test_nll_is_finite_for_zero_probability_on_truth() -> None:
    assert core.nll(["a"], [{"a": 0.0, "b": 1.0}]) == pytest.approx(-math.log(1e-15))


def test_ece_hand_computed() -> None:
    bins = core.reliability_bins([0.95, 0.85, 0.3, 0.3], [True, False, True, False], 10)
    assert [b.count for b in bins] == [0, 0, 2, 0, 0, 0, 0, 0, 1, 1]
    # 1/4*|1-.95| + 1/4*|0-.85| + 2/4*|.5-.3|
    assert core.expected_calibration_error(bins) == pytest.approx(0.325)


@pytest.mark.parametrize(
    ("confidence", "index"),
    [(0.0, 0), (0.1, 0), (0.1000001, 1), (0.3, 2), (0.7, 6), (0.95, 9), (1.0, 9)],
)
def test_bin_edges_are_upper_inclusive(confidence: float, index: int) -> None:
    bins = core.reliability_bins([confidence], [True], 10)
    assert bins[index].count == 1


def test_perfect_calibration_has_zero_ece() -> None:
    bins = core.reliability_bins([0.5, 0.5, 1.0], [True, False, True], 10)
    assert core.expected_calibration_error(bins) == 0.0


def test_percentile_uses_linear_interpolation() -> None:
    assert core.percentile([4.0, 1.0, 3.0, 2.0], 50) == 2.5
    assert core.percentile([1.0, 2.0, 3.0, 4.0], 95) == pytest.approx(3.85)
    assert core.percentile([7.0], 99) == 7.0
    assert core.percentile([], 50) is None


def test_ordinal_mae() -> None:
    assert core.ordinal_mae(["1", "4"], ["2", "2"], ["1", "2", "3", "4"]) == 1.5


SPEC = DecisionSpec(name="d", type=DecisionType.CHOICE, labels=("a", "b"))


def _record(case_id: str, expected: str | None, p_a: float | None) -> CaseRecord:
    if p_a is None:
        return CaseRecord(
            case_id=case_id,
            input="x",
            expected=expected,
            error=CaseError(kind="timeout", message="slow"),
        )
    probabilities = {"a": p_a, "b": 1 - p_a}
    selected = "a" if p_a >= 0.5 else "b"
    return CaseRecord(
        case_id=case_id,
        input="x",
        expected=expected,
        result=DecisionResult(
            case_id=case_id,
            decision="d",
            decision_type=DecisionType.CHOICE,
            labels=("a", "b"),
            probabilities=probabilities,
            selected=selected,
            confidence=probabilities[selected],
            backend="default",
            provider="mock",
            latency_ms=float(len(case_id)),
        ),
    )


RECORDS = [
    _record("1", "a", 0.9),
    _record("22", "b", 0.6),  # wrong, confidence 0.6
    _record("333", "b", 0.2),
    _record("4444", None, 0.95),  # unlabeled
    _record("5", "a", None),  # errored
]


def test_compute_metrics_counts_and_sections() -> None:
    metrics = compute_metrics(SPEC, RECORDS, Evaluation(confidence_threshold=0.8))
    counts = metrics.counts
    assert (counts.total, counts.succeeded, counts.errored, counts.labeled) == (5, 4, 1, 3)
    assert counts.errors_by_kind == {"timeout": 1}
    assert counts.error_rate == pytest.approx(0.2)
    assert metrics.classification.accuracy == pytest.approx(2 / 3)
    assert metrics.selective is not None
    # confidences over decided cases: 0.9, 0.6, 0.8, 0.95 -> three at or above 0.8
    assert metrics.selective.coverage == pytest.approx(0.75)
    assert metrics.selective.abstention_rate == pytest.approx(0.25)
    assert metrics.selective.selective_accuracy == 1.0
    assert metrics.latency.n == 4
    assert metrics.latency.max_ms == 4.0
    assert metrics.classification.ordinal_mae is None


def test_metrics_are_reproducible() -> None:
    evaluation = Evaluation(confidence_threshold=0.8)
    first = compute_metrics(SPEC, RECORDS, evaluation).model_dump_json()
    assert all(
        compute_metrics(SPEC, RECORDS, evaluation).model_dump_json() == first for _ in range(5)
    )


def test_no_labels_means_no_accuracy_but_other_metrics_work() -> None:
    unlabeled = [_record("1", None, 0.9), _record("2", None, 0.3)]
    metrics = compute_metrics(SPEC, unlabeled, Evaluation(confidence_threshold=0.8))
    assert metrics.classification.accuracy is None
    assert metrics.calibration.ece is None
    assert metrics.selective is not None
    assert metrics.selective.coverage == 0.5
