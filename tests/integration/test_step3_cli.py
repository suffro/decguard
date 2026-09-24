from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from decguard import DecGuard
from decguard.cli import app
from decguard.errors import ReportError
from decguard.production import load_production_report
from tests.conftest import CHOICE_CONTRACT, write_jsonl, write_yaml

runner = CliRunner()


def invoke(*args: str | Path) -> tuple[int, str, str]:
    result = runner.invoke(app, [str(arg) for arg in args])
    return result.exit_code, result.stdout, result.stderr


def production_record(
    record_id: str,
    *,
    locale: str,
    correct: bool,
    confidence: float = 0.9,
    action: str = "accept",
) -> dict[str, object]:
    selected = "refund"
    remainder = (1.0 - confidence) / 2
    return {
        "id": record_id,
        "timestamp": "2026-09-24T12:00:00Z",
        "decision": "refund_request",
        "input": f"request {record_id}",
        "probabilities": {
            "refund": confidence,
            "reject": remainder,
            "review": remainder,
        },
        "selected": selected,
        "backend": "production",
        "model": "refund-v1",
        "outcome": selected if correct else "reject",
        "metadata": {"locale": locale},
        "action": action,
        "fallback": action == "fallback",
        "latency_ms": 12.0,
        "cost": 0.002,
    }


def production_contract(tmp_path: Path) -> Path:
    data = copy.deepcopy(CHOICE_CONTRACT)
    data["evaluation"] = {"confidence_threshold": 0.85, "calibration_bins": 10}
    data["production"] = {
        "segments": ["locale"],
        "requirements": {
            "min_accuracy": 0.4,
            "max_ece_increase": 0.2,
            "max_confidence_tv_distance": 0.1,
        },
        "segment_requirements": {"min_accuracy": 0.5},
    }
    return write_yaml(tmp_path / "decguard.yaml", data)


def test_check_detects_calibration_drift_and_localized_failure(tmp_path: Path) -> None:
    contract = production_contract(tmp_path)
    baseline = write_jsonl(
        tmp_path / "baseline.jsonl",
        [
            production_record("b-en-1", locale="en", correct=True),
            production_record("b-en-2", locale="en", correct=True),
            production_record("b-it-1", locale="it", correct=True),
            production_record("b-it-2", locale="it", correct=True),
        ],
    )
    current = write_jsonl(
        tmp_path / "current.jsonl",
        [
            production_record("c-en-1", locale="en", correct=True),
            production_record("c-en-2", locale="en", correct=True),
            production_record("c-it-1", locale="it", correct=False, action="fallback"),
            production_record("c-it-2", locale="it", correct=False, action="human_review"),
        ],
    )
    output = tmp_path / "production-report.json"
    code, out, err = invoke(
        "check",
        contract,
        "--dataset",
        current,
        "--baseline",
        baseline,
        "--output",
        output,
    )
    assert code == 1, out + err
    assert "FAIL  max_ece_increase" in out
    assert "locale=it" in out
    assert "FAIL  segment[locale=it].min_accuracy" in out
    report = load_production_report(output)
    assert report.status.value == "fail"
    assert report.drift.ece_increase is not None
    assert report.drift.ece_increase > 0.2
    assert report.drift.confidence_tv_distance == 0.0
    assert report.metrics.routing.fallback_rate == 0.25


def test_check_accepts_previous_report_as_baseline_and_is_offline(tmp_path: Path) -> None:
    contract = production_contract(tmp_path)
    data = yaml.safe_load(contract.read_text())
    data["production"]["requirements"] = {
        "max_ece_increase": 0.0,
        "max_confidence_tv_distance": 0.0,
    }
    data["production"]["segment_requirements"] = {}
    contract = write_yaml(contract, data)
    records = write_jsonl(
        tmp_path / "production.jsonl",
        [production_record("one", locale="en", correct=True)],
    )
    baseline_report = tmp_path / "baseline-report.json"
    assert invoke("check", contract, "-d", records, "-o", baseline_report)[0] == 1
    code, out, err = invoke(
        "check",
        contract,
        "-d",
        records,
        "--baseline",
        baseline_report,
        "--format",
        "json",
    )
    assert code == 0, out + err
    parsed = json.loads(out)
    assert parsed["status"] == "pass"
    assert parsed["baseline"]["source"] == "report"
    assert parsed["drift"]["ece_increase"] == 0.0


def test_production_report_rejects_tampered_metrics(tmp_path: Path) -> None:
    contract = production_contract(tmp_path)
    data = yaml.safe_load(contract.read_text())
    data["production"]["requirements"] = {}
    data["production"]["segment_requirements"] = {}
    contract = write_yaml(contract, data)
    records = write_jsonl(
        tmp_path / "production.jsonl",
        [production_record("one", locale="en", correct=True)],
    )
    report_path = tmp_path / "report.json"
    assert invoke("check", contract, "-d", records, "-o", report_path)[0] == 0
    report = json.loads(report_path.read_text())
    report["metrics"]["outcomes"]["accuracy"] = 0.0
    report_path.write_text(json.dumps(report))
    with pytest.raises(ReportError, match="metrics do not match"):
        load_production_report(report_path)


def policy_contract(tmp_path: Path) -> Path:
    data = copy.deepcopy(CHOICE_CONTRACT)
    data["backend"] = {
        "provider": "mock",
        "model": "fast",
        "rules": [
            {
                "contains": "certain",
                "probabilities": {"refund": 0.96, "reject": 0.02, "review": 0.02},
            },
            {
                "contains": "medium",
                "probabilities": {"refund": 0.8, "reject": 0.1, "review": 0.1},
            },
        ],
        "default": {"refund": 0.6, "reject": 0.2, "review": 0.2},
    }
    data["backends"] = {
        "strong_model": {
            "provider": "mock",
            "model": "strong",
            "default": {"refund": 0.99, "reject": 0.005, "review": 0.005},
        }
    }
    data["policy"] = {
        "routes": [
            {"when": {"confidence_gte": 0.95}, "action": "accept"},
            {
                "when": {"confidence_gte": 0.75},
                "action": "fallback",
                "backend": "strong_model",
            },
            {"action": "human_review"},
        ]
    }
    return write_yaml(tmp_path / "policy.yaml", data)


def test_same_policy_routes_through_cli_and_python_sdk(tmp_path: Path) -> None:
    contract = policy_contract(tmp_path)
    expected = {
        "certain request": ("accept", None),
        "medium request": ("fallback", "strong_model"),
        "unclear request": ("human_review", None),
    }
    with DecGuard.from_contract(contract) as guard:
        for text, route in expected.items():
            sdk = guard.decide(text, case_id=text)
            code, out, err = invoke("run", contract, text, "--id", text, "--format", "json")
            assert code == 0, out + err
            cli = json.loads(out)
            assert (sdk.action, sdk.fallback_backend) == route
            assert (cli["action"], cli["fallback_backend"]) == route
            assert cli["route_index"] == sdk.route_index
            assert cli["result"]["probabilities"] == sdk.result.probabilities


def test_policy_contract_validation_rejects_unknown_fallback_backend(tmp_path: Path) -> None:
    data = yaml.safe_load(policy_contract(tmp_path).read_text())
    data["policy"]["routes"][1]["backend"] = "missing"
    contract = write_yaml(tmp_path / "bad-policy.yaml", data)
    code, _, err = invoke("validate", contract)
    assert code == 2
    assert "unknown backend 'missing'" in err
