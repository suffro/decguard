from __future__ import annotations

import math

import pytest

from decguard.decisions import DecisionResult
from decguard.fuzz.compare import compare
from decguard.metrics import distribution as d

LABELS = ("a", "b", "c")


def test_identical_distributions_have_zero_distance() -> None:
    p = {"a": 0.2, "b": 0.5, "c": 0.3}
    assert d.tv_distance(p, p, LABELS) == 0.0
    assert d.js_divergence(p, p, LABELS) == 0.0
    assert d.max_abs_delta(p, p, LABELS) == 0.0


def test_disjoint_distributions_have_maximal_distance() -> None:
    p = {"a": 1.0, "b": 0.0, "c": 0.0}
    q = {"a": 0.0, "b": 0.0, "c": 1.0}
    assert d.tv_distance(p, q, LABELS) == 1.0
    assert d.js_divergence(p, q, LABELS) == pytest.approx(1.0)
    assert d.max_abs_delta(p, q, LABELS) == 1.0


def test_known_values_and_symmetry() -> None:
    p = {"a": 0.5, "b": 0.5, "c": 0.0}
    q = {"a": 0.25, "b": 0.25, "c": 0.5}
    assert d.tv_distance(p, q, LABELS) == pytest.approx(0.5)
    assert d.max_abs_delta(p, q, LABELS) == pytest.approx(0.5)
    # m = (0.375, 0.375, 0.25): JS = 0.5*KL(p||m) + 0.5*KL(q||m)
    expected = 0.5 * (2 * 0.5 * math.log2(0.5 / 0.375)) + 0.5 * (
        2 * 0.25 * math.log2(0.25 / 0.375) + 0.5 * math.log2(0.5 / 0.25)
    )
    assert d.js_divergence(p, q, LABELS) == pytest.approx(expected)
    assert d.js_divergence(p, q, LABELS) == d.js_divergence(q, p, LABELS)
    assert d.tv_distance(p, q, LABELS) == d.tv_distance(q, p, LABELS)


def test_expected_level_and_ranking() -> None:
    p = {"a": 0.2, "b": 0.4, "c": 0.4}
    assert d.expected_level(p, LABELS) == pytest.approx(0.4 + 0.8)
    assert d.ranking(p, LABELS) == ("b", "c", "a")  # tie keeps canonical order


def _result(
    probabilities: dict[str, float], labels: tuple[str, ...] = LABELS, **kw: object
) -> DecisionResult:
    selected = max(labels, key=lambda label: (probabilities[label], -labels.index(label)))
    return DecisionResult.model_validate(
        {
            "case_id": "x",
            "decision": "d",
            "decision_type": kw.get("decision_type", "choice"),
            "labels": labels,
            "probabilities": probabilities,
            "selected": selected,
            "confidence": probabilities[selected],
            "backend": "b",
            "provider": "p",
            "latency_ms": 0.0,
        }
    )


def test_compare_invariant_measures_drift_and_flip() -> None:
    before = _result({"a": 0.6, "b": 0.3, "c": 0.1})
    after = _result({"a": 0.3, "b": 0.6, "c": 0.1})
    c = compare(before, after, "invariant")
    assert c.tv_distance == pytest.approx(0.3)
    assert c.max_abs_delta == pytest.approx(0.3)
    assert c.flipped
    assert c.rank_changed
    assert (c.selected_before, c.selected_after) == ("a", "b")
    assert c.confidence_delta == pytest.approx(0.0)
    assert c.level_delta is None


def test_compare_swapped_measures_distance_from_the_inverted_answer() -> None:
    labels = ("yes", "no")
    before = _result({"yes": 0.9, "no": 0.1}, labels, decision_type="noul")
    inverted = _result({"yes": 0.1, "no": 0.9}, labels, decision_type="noul")
    same = _result({"yes": 0.9, "no": 0.1}, labels, decision_type="noul")
    good = compare(before, inverted, "swapped")
    assert good.tv_distance == pytest.approx(0.0)
    assert not good.flipped
    bad = compare(before, same, "swapped")
    assert bad.tv_distance == pytest.approx(0.8)
    assert bad.flipped


def test_compare_monotonic_uses_direction() -> None:
    labels = ("1", "2", "3")
    low = _result({"1": 0.7, "2": 0.2, "3": 0.1}, labels, decision_type="score")
    high = _result({"1": 0.1, "2": 0.2, "3": 0.7}, labels, decision_type="score")
    up = compare(low, high, "monotonic", direction="increasing")
    assert up.level_delta == pytest.approx(1.2)
    assert not up.flipped
    down = compare(high, low, "monotonic", direction="increasing")
    assert down.flipped
    assert not compare(high, low, "monotonic", direction="decreasing").flipped
