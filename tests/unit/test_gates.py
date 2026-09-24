from __future__ import annotations

from decguard.contracts import Evaluation, Gates
from decguard.decisions import DecisionSpec, DecisionType
from decguard.metrics import compute_metrics
from decguard.reports import GATES, Status, evaluate_gates
from tests.unit.test_metrics import RECORDS, _record

SPEC = DecisionSpec(name="d", type=DecisionType.CHOICE, labels=("a", "b"))
CLEAN = [r for r in RECORDS if r.error is None]  # accuracy 2/3, no errors


def evaluate(records=CLEAN, requirements=None, warnings=None, **evaluation):
    metrics = compute_metrics(SPEC, records, Evaluation(**evaluation))
    return evaluate_gates(Gates(**(requirements or {})), Gates(**(warnings or {})), metrics)


def test_every_gate_field_is_mapped() -> None:
    assert set(GATES) == set(Gates.model_fields)


def test_pass_when_all_requirements_hold() -> None:
    checks, status = evaluate(requirements={"min_accuracy": 0.6})
    assert status is Status.PASS
    assert {c.gate for c in checks} == {"min_accuracy", "max_error_rate"}


def test_threshold_is_inclusive() -> None:
    _, status = evaluate(requirements={"min_accuracy": 2 / 3})
    assert status is Status.PASS


def test_fail_when_a_requirement_is_violated() -> None:
    checks, status = evaluate(requirements={"min_accuracy": 0.9})
    assert status is Status.FAIL
    failed = next(c for c in checks if c.gate == "min_accuracy")
    assert failed.status is Status.FAIL
    assert "violates >= 0.9" in failed.message


def test_warning_gates_only_warn() -> None:
    checks, status = evaluate(requirements={"min_accuracy": 0.5}, warnings={"min_accuracy": 0.9})
    assert status is Status.WARN
    assert [c.status for c in checks if c.level == "warning"] == [Status.WARN]


def test_requirement_failure_dominates_warnings() -> None:
    _, status = evaluate(requirements={"min_accuracy": 0.9}, warnings={"max_ece": 0.0})
    assert status is Status.FAIL


def test_errored_cases_fail_by_default() -> None:
    checks, status = evaluate(records=RECORDS)
    assert status is Status.FAIL
    assert [c.gate for c in checks if c.status is Status.FAIL] == ["max_error_rate"]


def test_error_rate_can_be_tolerated_explicitly() -> None:
    _, status = evaluate(records=RECORDS, requirements={"max_error_rate": 0.25})
    assert status is Status.PASS


def test_unevaluable_gate_fails() -> None:
    unlabeled = [_record("1", None, 0.9)]
    checks, status = evaluate(records=unlabeled, requirements={"min_accuracy": 0.5})
    assert status is Status.FAIL
    check = next(c for c in checks if c.gate == "min_accuracy")
    assert check.value is None
    assert "could not be computed" in check.message


def test_selective_gates() -> None:
    _, status = evaluate(
        requirements={"min_coverage": 0.75, "min_selective_accuracy": 1.0},
        confidence_threshold=0.8,
    )
    assert status is Status.PASS
    _, status = evaluate(requirements={"max_abstention_rate": 0.1}, confidence_threshold=0.8)
    assert status is Status.FAIL
