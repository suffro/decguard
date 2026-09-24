"""Stored reports are re-validated on load: tampered or corrupted results are rejected."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from decguard.backends import CallableBackend
from decguard.cli import app
from decguard.decisions import TOLERANCE_CONTEXT_KEY, DecisionResult
from decguard.engine import run_test
from decguard.errors import ReportError
from decguard.reports import load_report, write_report
from decguard.runner import CaseRecord
from tests.conftest import ContractFactory

VALID_RESULT: dict[str, Any] = {
    "case_id": "c1",
    "decision": "d",
    "decision_type": "choice",
    "labels": ["a", "b", "c"],
    "probabilities": {"a": 0.2, "b": 0.5, "c": 0.3},
    "selected": "b",
    "confidence": 0.5,
    "backend": "default",
    "provider": "mock",
    "latency_ms": 1.0,
}


def result(**changes: Any) -> dict[str, Any]:
    return {**VALID_RESULT, **changes}


def test_valid_result_round_trips() -> None:
    parsed = DecisionResult.model_validate(VALID_RESULT)
    assert DecisionResult.model_validate_json(parsed.model_dump_json()) == parsed


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"probabilities": {"a": 0.4, "b": 0.5, "c": 0.3}}, "sum to 1.2"),
        ({"probabilities": {"a": -0.1, "b": 0.8, "c": 0.3}}, "negative"),
        ({"probabilities": {"a": 0.5, "b": 0.5}}, "exactly the labels"),
        ({"probabilities": {"a": 0.2, "b": 0.5, "c": 0.2, "d": 0.1}}, "exactly the labels"),
        ({"probabilities": {"b": 0.5, "a": 0.2, "c": 0.3}}, "in that order"),
        ({"labels": ["a", "b", "b"]}, "duplicates"),
        ({"labels": [], "probabilities": {}}, "must not be empty"),
        ({"selected": "c", "confidence": 0.3}, "not the most probable label 'b'"),
        ({"selected": "z"}, "not the most probable label"),
        ({"confidence": 0.9}, "confidence 0.9 does not equal"),
    ],
)
def test_invalid_results_are_rejected(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        DecisionResult.model_validate(result(**changes))


def test_tie_must_select_first_canonical_label() -> None:
    tie = {"a": 0.4, "b": 0.4, "c": 0.2}
    DecisionResult.model_validate(result(probabilities=tie, selected="a", confidence=0.4))
    with pytest.raises(ValidationError, match="not the most probable label 'a'"):
        DecisionResult.model_validate(result(probabilities=tie, selected="b", confidence=0.4))


def test_sum_tolerance_comes_from_validation_context() -> None:
    loose = result(probabilities={"a": 0.2, "b": 0.5, "c": 0.33})
    with pytest.raises(ValidationError, match="sum to"):
        DecisionResult.model_validate(loose)
    DecisionResult.model_validate(loose, context={TOLERANCE_CONTEXT_KEY: 0.05})


def test_case_record_needs_exactly_one_of_result_or_error() -> None:
    base = {"case_id": "c1", "input": "x"}
    error = {"kind": "timeout", "message": "slow"}
    CaseRecord.model_validate({**base, "result": VALID_RESULT})
    CaseRecord.model_validate({**base, "error": error})
    with pytest.raises(ValidationError, match="exactly one of 'result' or 'error'"):
        CaseRecord.model_validate({**base, "result": VALID_RESULT, "error": error})
    with pytest.raises(ValidationError, match="exactly one of 'result' or 'error'"):
        CaseRecord.model_validate(base)
    with pytest.raises(ValidationError, match="does not match case_id"):
        CaseRecord.model_validate({**base, "case_id": "c2", "result": VALID_RESULT})


# --- whole stored reports -------------------------------------------------------------


@pytest.fixture
def stored_report(make_contract: ContractFactory, tmp_path: Path) -> Path:
    path = tmp_path / "report.json"
    write_report(run_test(make_contract()), path)
    return path


def tamper(path: Path, edit: Callable[[dict[str, Any]], None]) -> Path:
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))
    return path


def _first_result(data: dict[str, Any]) -> dict[str, Any]:
    return data["results"][0]["result"]  # type: ignore[no-any-return]


def _bump_probability(data: dict[str, Any]) -> None:
    _first_result(data)["probabilities"]["refund"] += 0.2


def _wrong_selected(data: dict[str, Any]) -> None:
    res = _first_result(data)
    res["selected"] = "review"
    res["confidence"] = res["probabilities"]["review"]


def _wrong_confidence(data: dict[str, Any]) -> None:
    _first_result(data)["confidence"] = 0.99


def _both(data: dict[str, Any]) -> None:
    data["results"][0]["error"] = {"kind": "timeout", "message": "slow"}


def _neither(data: dict[str, Any]) -> None:
    data["results"][0]["result"] = None


def _wrong_metrics(data: dict[str, Any]) -> None:
    data["metrics"]["classification"]["accuracy"] = 0.0


def _wrong_status(data: dict[str, Any]) -> None:
    data["status"] = "fail"
    data["exit_code"] = 1


def _duplicate_case(data: dict[str, Any]) -> None:
    data["results"].append(copy.deepcopy(data["results"][0]))
    data["dataset"]["n_cases"] += 1
    data["dataset"]["n_labeled"] += int(data["results"][0]["expected"] is not None)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (_bump_probability, "results.0.result: probabilities sum to 1.2"),
        (_wrong_selected, "results.0.result: selected 'review' is not the most probable"),
        (_wrong_confidence, "results.0.result: confidence 0.99 does not equal"),
        (_both, "results.0: a case record must have exactly one of 'result' or 'error'"),
        (_neither, "results.0: a case record must have exactly one of 'result' or 'error'"),
        (_wrong_metrics, "metrics do not match stored case results"),
        (_wrong_status, "status/exit_code do not match stored checks"),
        (_duplicate_case, "duplicate case id"),
    ],
)
def test_tampered_reports_are_rejected(
    stored_report: Path, edit: Callable[[dict[str, Any]], None], message: str
) -> None:
    assert load_report(stored_report).status.value == "pass"  # untouched report loads
    tamper(stored_report, edit)
    with pytest.raises(ReportError, match=re.escape(message)):
        load_report(stored_report)

    cli = CliRunner().invoke(app, ["report", str(stored_report)])
    assert cli.exit_code == 2
    assert message in cli.stderr


def test_report_keeps_the_contract_tolerance(
    make_contract: ContractFactory, tmp_path: Path
) -> None:
    contract = make_contract({"evaluation": {"probability_tolerance": 0.05}})
    report = run_test(
        contract, backend=CallableBackend(lambda r: {"refund": 0.53, "reject": 0.2, "review": 0.3})
    )
    path = tmp_path / "report.json"
    write_report(report, path)
    assert load_report(path).results == report.results

    # Lowering the recorded tolerance makes the same stored results inconsistent.
    tamper(path, lambda data: data["evaluation"].update(probability_tolerance=0.01))
    with pytest.raises(ReportError, match=re.escape("sum to 1.03")):
        load_report(path)
