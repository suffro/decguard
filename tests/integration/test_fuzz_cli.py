"""Step 2 end to end: fuzz, test --all, replay and diff through the CLI and over HTTP."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

import decguard.fuzz.replay as replay_module
from decguard.backends import CallableBackend, MockBackend, MockSettings
from decguard.cli import app
from decguard.decisions import DecisionRequest
from decguard.engine import run_test
from decguard.errors import BackendUnavailable, InvalidResponse
from decguard.reports import write_report
from decguard.reports.gates import Status
from tests.conftest import (
    CHOICE_CASES,
    CHOICE_CONTRACT,
    EXAMPLES,
    ContractFactory,
    write_jsonl,
    write_yaml,
)
from tests.integration.conftest import start_server

runner = CliRunner()
REFUND = EXAMPLES / "refund" / "decguard.yaml"


def invoke(*args: str | Path) -> tuple[int, str, str]:
    result = runner.invoke(app, [str(a) for a in args])
    return result.exit_code, result.stdout, result.stderr


@pytest.fixture
def refund(tmp_path: Path) -> Path:
    """A copy of the refund example, so reports can reference it by a stable path."""
    target = tmp_path / "refund"
    shutil.copytree(EXAMPLES / "refund", target)
    return target / "decguard.yaml"


@pytest.mark.parametrize("example", ["refund", "spam", "severity"])
def test_examples_pass_all_checks(example: str) -> None:
    """Choice, noul and score contracts with properties pass `test --all` and `fuzz`."""
    contract = EXAMPLES / example / "decguard.yaml"
    code, out, err = invoke("test", contract, "--all")
    assert code == 0, out + err
    assert "Properties" in out
    code, out, err = invoke("fuzz", contract, "--format", "json")
    assert code == 0, out + err
    report = json.loads(out)
    assert report["mode"] == "fuzz"
    assert report["properties"]["summaries"]
    assert all(s["n_evaluated"] > 0 for s in report["properties"]["summaries"])


def test_help_lists_step_2_commands() -> None:
    code, out, _ = invoke("--help")
    assert code == 0
    for command in ("fuzz", "diff", "replay"):
        assert command in out
        assert invoke(command, "--help")[0] == 0
    assert "--all" in invoke("test", "--help")[1]


def test_validate_lists_properties() -> None:
    code, out, _ = invoke("validate", REFUND)
    assert code == 0
    assert "properties option_order, label_format" in out


def test_fuzz_fails_ci_on_a_property_violation(refund: Path, tmp_path: Path) -> None:
    out_file = tmp_path / "fuzz.json"
    code, out, err = invoke("fuzz", refund, "-b", "order_sensitive", "-o", out_file)
    assert code == 1, out + err
    assert "FAIL  option_order.max_violation_rate" in out
    assert "Property failures" in out
    report = json.loads(out_file.read_text())
    assert report["status"] == "fail"
    assert report["exit_code"] == 1
    assert report["properties"]["seed"] == 42
    assert report["contract"]["hash"].startswith("sha256:")
    assert report["dataset"]["hash"].startswith("sha256:")
    assert report["backend"]["details"]["position_bias"] == 0.1
    failing = [p for p in report["properties"]["pairs"] if p["violations"]]
    assert failing
    assert all(p["property"] == "option_order" for p in failing)
    # `test` without --all ignores properties, but the same flawed backend also violates
    # the demo's stricter calibration gate.
    code, golden, _ = invoke("test", refund, "-b", "order_sensitive")
    assert code == 1
    assert "FAIL  max_ece" in golden
    assert invoke("test", refund, "-b", "order_sensitive", "--all")[0] == 1


def test_seed_override_and_property_selection(refund: Path) -> None:
    code, out, _ = invoke("fuzz", refund, "--seed", "5", "-p", "whitespace", "-f", "json")
    assert code == 0
    report = json.loads(out)
    assert report["properties"]["seed"] == 5
    assert [s["property"] for s in report["properties"]["summaries"]] == ["whitespace"]
    assert invoke("fuzz", refund, "-p", "inversion")[0] == 2


def test_stored_failures_replay(refund: Path, tmp_path: Path) -> None:
    stored = tmp_path / "fuzz.json"
    assert invoke("fuzz", refund, "-b", "order_sensitive", "-o", stored)[0] == 1
    failure_id = next(
        p["id"] for p in json.loads(stored.read_text())["properties"]["pairs"] if p["violations"]
    )

    code, out, err = invoke("replay", stored, "--id", failure_id)
    assert code == 1, out + err
    assert f"{failure_id}: REPRODUCED · regenerated from seed: yes" in out

    code, out, _ = invoke("replay", stored, "--format", "json")
    assert code == 1
    replayed = json.loads(out)
    assert replayed["status"] == "fail"
    assert all(o["reproduced"] and o["regenerated"] for o in replayed["outcomes"])

    # Against the fixed model the same failures no longer reproduce.
    code, out, _ = invoke("replay", stored, "--backend", "default")
    assert code == 0
    assert "PASS: no failure reproduced" in out

    assert invoke("replay", stored, "--id", "option_order/nope/0")[0] == 2
    golden = tmp_path / "golden.json"
    invoke("test", refund, "-o", golden)
    code, _, err = invoke("replay", golden)
    assert code == 2
    assert "no property results" in err


def test_transformed_backend_error_replay_semantics(
    make_contract: ContractFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = make_contract(
        {"properties": {"whitespace": {"max_tv_distance": 0}}},
        cases=[{"id": "c1", "input": "damaged", "expected": "refund"}],
    )

    def backend(
        error: type[Exception] | None, message: str = "transformed request failed"
    ) -> CallableBackend:
        def decide(request: DecisionRequest) -> dict[str, float]:
            if "/" in request.case_id and error is not None:
                raise error(message)
            probabilities = {"refund": 0.8, "reject": 0.1, "review": 0.1}
            return {label: probabilities[label] for label in request.decision.labels}

        return CallableBackend(decide, name="default")

    report = run_test(contract, backend=backend(InvalidResponse), mode="fuzz")
    assert report.status is Status.FAIL
    assert report.exit_code == 1
    assert report.properties is not None
    failures = report.properties.failures()
    assert failures
    assert all(failure.error is not None for failure in failures)
    assert {failure.error.kind for failure in failures if failure.error} == {"invalid_response"}
    stored = tmp_path / "errored-fuzz.json"
    write_report(report, stored)

    monkeypatch.setattr(
        replay_module,
        "create_backend",
        lambda config, *, decision, name: backend(InvalidResponse, "still invalid"),
    )
    code, out, err = invoke("replay", stored, "--format", "json")
    assert code == 1, out + err
    replayed = json.loads(out)
    assert len(replayed["outcomes"]) == len(failures)  # selected without --id
    examples = [outcome["examples"][0] for outcome in replayed["outcomes"]]
    assert all(example["stored_error"]["kind"] == "invalid_response" for example in examples)
    assert all(example["error"]["kind"] == "invalid_response" for example in examples)
    assert all(example["reproduced"] is True for example in examples)

    monkeypatch.setattr(
        replay_module,
        "create_backend",
        lambda config, *, decision, name: backend(None),
    )
    code, out, err = invoke("replay", stored, "--format", "json")
    assert code == 0, out + err
    replayed = json.loads(out)
    assert all(outcome["examples"][0]["reproduced"] is False for outcome in replayed["outcomes"])

    monkeypatch.setattr(
        replay_module,
        "create_backend",
        lambda config, *, decision, name: backend(BackendUnavailable, "temporarily offline"),
    )
    code, out, err = invoke("replay", stored)
    assert code == 0, out + err
    assert "error changed: invalid_response -> unavailable" in out
    assert "PASS: no failure reproduced" in out


def test_default_replay_skips_synthetic_original_errors(
    make_contract: ContractFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = make_contract(
        {"properties": {"whitespace": {"max_tv_distance": 0}}},
        cases=[
            {"id": "c1", "input": "damaged", "expected": "refund"},
            {"id": "c2", "input": "changed", "expected": "reject"},
        ],
    )

    def original_error_backend(request: DecisionRequest) -> dict[str, float]:
        if request.case_id == "c1":
            raise InvalidResponse("original request failed")
        probabilities = {"refund": 0.8, "reject": 0.1, "review": 0.1}
        return {label: probabilities[label] for label in request.decision.labels}

    report = run_test(
        contract,
        backend=CallableBackend(original_error_backend, name="default"),
        mode="fuzz",
    )
    assert report.status is Status.FAIL
    assert report.properties is not None
    original_errors = [pair for pair in report.properties.pairs if pair.error is not None]
    assert original_errors
    assert {pair.error.kind for pair in original_errors if pair.error} == {"original_error"}
    (summary,) = report.properties.summaries
    assert summary.n_errors == len(original_errors)
    assert summary.errors_by_kind == {"original_error": len(original_errors)}
    assert {check.gate: check.status for check in report.checks}[
        "whitespace.max_error_rate"
    ] is Status.FAIL
    assert report.properties.failures() == []

    stored = tmp_path / "original-error-fuzz.json"
    write_report(report, stored)
    replayed_requests: list[str] = []

    def replay_backend(request: DecisionRequest) -> dict[str, float]:
        replayed_requests.append(request.case_id)
        return original_error_backend(request)

    monkeypatch.setattr(
        replay_module,
        "create_backend",
        lambda config, *, decision, name: CallableBackend(replay_backend, name=name),
    )
    code, out, err = invoke("replay", stored, "--format", "json")
    assert code == 0, out + err
    assert json.loads(out)["outcomes"] == []
    assert replayed_requests == []


def test_report_shows_and_reevaluates_fuzz_reports(refund: Path, tmp_path: Path) -> None:
    stored = tmp_path / "fuzz.json"
    invoke("fuzz", refund, "-b", "order_sensitive", "-o", stored)
    code, out, _ = invoke("report", stored)
    assert code == 1
    assert "Properties" in out
    data = yaml.safe_load(refund.read_text())
    data["properties"]["option_order"] = {"max_tv_distance": 0.5, "max_flip_rate": 0.5}
    loose = write_yaml(refund.parent / "loose.yaml", data)
    assert invoke("report", stored, "--contract", loose)[0] == 0


def test_diff_catches_a_regression(refund: Path, tmp_path: Path) -> None:
    baseline, candidate = tmp_path / "base.json", tmp_path / "cand.json"
    data = yaml.safe_load(refund.read_text())
    data["backends"]["degraded"] = {
        **data["backend"],
        "rules": [
            {"contains": "damaged", "probabilities": {"refund": 0.2, "reject": 0.1, "review": 0.7}}
        ],
    }
    contract = write_yaml(refund.parent / "with-degraded.yaml", data)
    assert invoke("test", contract, "-o", baseline)[0] == 0
    invoke("test", contract, "-b", "degraded", "-o", candidate)

    code, out, err = invoke("diff", baseline, candidate, "--contract", contract)
    assert code == 1, out + err
    assert "FAIL  max_answer_flip_rate" in out
    assert "FAIL  max_accuracy_drop" in out
    assert "locale=en" in out

    code, out, _ = invoke(
        "diff", baseline, baseline, "-c", contract, "-f", "json", "-o", tmp_path / "d.json"
    )
    assert code == 0
    assert json.loads(out)["status"] == "pass"
    assert json.loads((tmp_path / "d.json").read_text())["counts"]["answer_flips"] == 0

    assert invoke("diff", baseline, tmp_path / "missing.json")[0] == 2


# --- over HTTP -------------------------------------------------------------------------


def _http_contract(tmp_path: Path, url: str) -> Path:
    data: dict[str, Any] = copy.deepcopy(CHOICE_CONTRACT)
    data["backends"] = {"remote": {"provider": "http", "url": url + "/decide"}}
    data["properties"] = {
        "option_order": {"samples": 5, "max_tv_distance": 0.03},
        "label_format": {"styles": ["upper", "lettered"], "max_tv_distance": 0.03},
        "whitespace": {"max_tv_distance": 0.03},
    }
    data["requirements"] = {}
    write_jsonl(tmp_path / "cases.jsonl", CHOICE_CASES)
    return write_yaml(tmp_path / "decguard.yaml", data)


def _fingerprint(report: Any) -> list[Any]:
    return [
        (p.id, p.input, p.presentation, p.result.probabilities if p.result else None, p.comparison)
        for p in report.properties.pairs
    ]


def test_http_backend_fuzzes_like_the_local_mock(tmp_path: Path) -> None:
    rules = copy.deepcopy(CHOICE_CONTRACT["backend"])
    settings = MockSettings(rules=rules["rules"], default=rules["default"])
    server = start_server(MockBackend(settings))
    try:
        contract = _http_contract(tmp_path, server.base_url)
        local = run_test(contract, mode="fuzz")
        remote = run_test(contract, backend="remote", mode="fuzz", check_health=False)
        assert local.status.value == remote.status.value == "pass"
        assert _fingerprint(local) == _fingerprint(remote)
        sent = {tuple(r["decision"]["labels"]) for r in server.requests_seen}
        assert ("review", "reject", "refund") in sent
        assert ("A) refund", "B) reject", "C) review") in sent
    finally:
        server.shutdown()
        server.server_close()


def test_http_order_sensitive_endpoint_is_caught(tmp_path: Path) -> None:
    rules = copy.deepcopy(CHOICE_CONTRACT["backend"])
    settings = MockSettings(rules=rules["rules"], default=rules["default"], position_bias=0.25)
    server = start_server(MockBackend(settings))
    try:
        contract = _http_contract(tmp_path, server.base_url)
        code, out, err = invoke(
            "fuzz", contract, "-b", "remote", "--no-healthcheck", "-p", "option_order"
        )
        assert code == 1, out + err
        assert "tv_distance 0.25 > 0.03" in out
    finally:
        server.shutdown()
        server.server_close()
