"""``decguard diff``: controlled degradations must be caught, identical runs must pass."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from decguard.backends import CallableBackend
from decguard.contracts import load_contract
from decguard.decisions import DecisionRequest
from decguard.engine import run_test
from decguard.errors import InvalidResponse, ReportError
from decguard.regression import diff_reports
from decguard.regression.diff import DiffReport
from decguard.reports import Report
from decguard.reports.gates import Status
from tests.conftest import ContractFactory

CASES = [
    {"id": f"k{i}", "input": f"case {i} {text}", "expected": label, "metadata": {"locale": loc}}
    for i, (text, label, loc) in enumerate(
        [
            ("damaged", "refund", "en"),
            ("damaged again", "refund", "en"),
            ("changed", "reject", "en"),
            ("changed twice", "reject", "de"),
            ("invoice", "review", "de"),
            ("other", "review", "de"),
        ]
    )
]
GOOD = {
    "damaged": {"refund": 0.9, "reject": 0.05, "review": 0.05},
    "changed": {"refund": 0.1, "reject": 0.8, "review": 0.1},
}
FALLBACK = {"refund": 0.1, "reject": 0.1, "review": 0.8}


def model(
    overrides: dict[str, dict[str, float]] | None = None, fail_on: str | None = None
) -> Callable[[DecisionRequest], dict[str, float]]:
    overrides = overrides or {}
    rules = {**overrides, **{k: v for k, v in GOOD.items() if k not in overrides}}  # first match

    def decide(request: DecisionRequest) -> dict[str, float]:
        text = str(request.input)
        if fail_on and fail_on in text:
            raise InvalidResponse("broken")
        for key, answer in rules.items():
            if key in text:
                return answer
        return FALLBACK

    return decide


REGRESSION = {
    "max_answer_flip_rate": 0.0,
    "max_accuracy_drop": 0.0,
    "max_ece_increase": 0.05,
    "segment_by": ["locale"],
    "min_segment_size": 3,
    "max_segment_accuracy_drop": 0.0,
}


@pytest.fixture
def contract(make_contract: ContractFactory) -> Path:
    return make_contract({"regression": REGRESSION, "requirements": None}, cases=CASES)


def run(contract: Path, fn: Callable[[DecisionRequest], dict[str, float]]) -> Report:
    return run_test(contract, backend=CallableBackend(fn))


def diff(contract: Path, baseline: Report, candidate: Report, **kw: Any) -> DiffReport:
    return diff_reports(baseline, candidate, contract=load_contract(contract), **kw)


def gate(result: DiffReport, name: str) -> tuple[Status, float | None]:
    (found,) = [c for c in result.checks if c.gate == name]
    return found.status, found.value


def test_identical_runs_pass(contract: Path) -> None:
    baseline = run(contract, model())
    result = diff(contract, baseline, run(contract, model()))
    assert result.status is Status.PASS
    assert result.exit_code == 0
    assert result.counts.answer_flips == 0
    assert result.shift.mean_tv_distance == 0.0
    assert result.same_dataset
    assert result.changes == []


def test_answer_flips_and_accuracy_drop_are_caught(contract: Path) -> None:
    worse = model({"changed": {"refund": 0.6, "reject": 0.3, "review": 0.1}})
    result = diff(contract, run(contract, model()), run(contract, worse))
    assert result.status is Status.FAIL
    assert result.counts.answer_flips == 2
    assert result.counts.newly_wrong == 2
    assert gate(result, "max_answer_flip_rate")[0] is Status.FAIL
    assert gate(result, "max_answer_flip_rate")[1] == pytest.approx(2 / 6)
    assert gate(result, "max_accuracy_drop")[0] is Status.FAIL
    assert gate(result, "max_accuracy_drop")[1] == pytest.approx(2 / 6)
    assert {c.case_id for c in result.changes} == {"k2", "k3"}
    assert all(c.kind == "flip" for c in result.changes)
    assert result.shift.max_tv_distance == pytest.approx(0.5)


def test_confidence_and_calibration_shifts_are_measured(contract: Path) -> None:
    # Same answers, less confident: no flip, but calibration and confidence move.
    hedging = model(
        {
            "damaged": {"refund": 0.4, "reject": 0.3, "review": 0.3},
            "changed": {"refund": 0.3, "reject": 0.4, "review": 0.3},
        }
    )
    result = diff(contract, run(contract, model()), run(contract, hedging))
    assert result.counts.answer_flips == 0
    assert result.shift.mean_confidence_delta == pytest.approx((4 * -0.45 + 0) / 6)
    ece_delta = result.metrics["ece"].delta
    assert ece_delta is not None
    assert ece_delta > 0.05
    assert gate(result, "max_ece_increase")[0] is Status.FAIL
    assert gate(result, "max_answer_flip_rate")[0] is Status.PASS


def test_new_errors_always_fail(make_contract: ContractFactory) -> None:
    path = make_contract({"requirements": None}, cases=CASES)  # no regression section
    baseline = run(path, model())
    candidate = run_test(path, backend=CallableBackend(model(fail_on="invoice")))
    result = diff(path, baseline, candidate)
    assert result.status is Status.FAIL
    assert gate(result, "max_error_rate_increase")[0] is Status.FAIL
    assert gate(result, "max_error_rate_increase")[1] == pytest.approx(1 / 6)
    assert result.counts.newly_errored == 1
    (change,) = result.changes
    assert change.kind == "newly_errored"
    assert "invalid_response" in (change.error or "")
    # And the reverse direction: the error is recovered, nothing regresses.
    back = diff(path, candidate, baseline)
    assert back.status is Status.PASS
    assert back.counts.recovered == 1


def test_segments_localize_a_regression(contract: Path) -> None:
    # Only German "changed twice" breaks: the en segment is untouched.
    worse = model({"changed twice": {"refund": 0.8, "reject": 0.1, "review": 0.1}})
    result = diff(contract, run(contract, model()), run(contract, worse))
    segments = {(s.key, s.value): s for s in result.segments}
    assert segments[("locale", "en")].accuracy_drop == 0.0
    assert segments[("locale", "de")].accuracy_drop == pytest.approx(1 / 3)
    status, value = gate(result, "max_segment_accuracy_drop")
    assert status is Status.FAIL
    assert value == pytest.approx(1 / 3)
    assert "worst segment locale=de" in next(
        c.message for c in result.checks if c.gate == "max_segment_accuracy_drop"
    )
    small = diff(contract, run(contract, model()), run(contract, worse), segment_by=["locale"])
    assert small.segments == result.segments


def test_unmatched_cases_are_counted(make_contract: ContractFactory, tmp_path: Path) -> None:
    path = make_contract({"requirements": None}, cases=CASES)
    baseline = run(path, model())
    fewer = make_contract({"requirements": None}, cases=[*CASES[:4], {"id": "new", "input": "x"}])
    candidate = run(fewer, model())
    result = diff(path, baseline, candidate)
    assert (
        result.counts.matched,
        result.counts.only_in_baseline,
        result.counts.only_in_candidate,
    ) == (4, 2, 1)
    assert not result.same_dataset


def test_warning_gates_warn(make_contract: ContractFactory) -> None:
    path = make_contract(
        {"requirements": None, "regression": {"warnings": {"max_answer_flip_rate": 0.0}}},
        cases=CASES,
    )
    worse = model({"changed": {"refund": 0.6, "reject": 0.3, "review": 0.1}})
    result = diff(path, run(path, model()), run(path, worse))
    assert result.status is Status.WARN
    assert result.exit_code == 0


def test_different_decisions_cannot_be_compared(make_contract: ContractFactory) -> None:
    path = make_contract({"requirements": None}, cases=CASES)
    other = make_contract(
        {
            "requirements": None,
            "decision": {
                "name": "refund_request",
                "type": "choice",
                "options": ["refund", "reject"],
            },
            "backend": {"provider": "mock"},
        },
        cases=[{"input": "x"}],
        name="other.yaml",
    )
    with pytest.raises(ReportError, match="cannot compare"):
        diff_reports(run(path, model()), run_test(other))


def test_diff_without_contract_uses_candidate_evaluation(contract: Path) -> None:
    result = diff_reports(run(contract, model()), run(contract, model()))
    assert result.status is Status.PASS
    assert [c.gate for c in result.checks] == ["max_error_rate_increase"]
