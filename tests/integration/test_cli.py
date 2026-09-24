from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from decguard.cli import app
from tests.conftest import EXAMPLES, ContractFactory

runner = CliRunner()


def invoke(*args: str | Path) -> tuple[int, str, str]:
    result = runner.invoke(app, [str(a) for a in args])
    return result.exit_code, result.stdout, result.stderr


def test_help_lists_commands_and_exit_codes() -> None:
    code, out, _ = invoke("--help")
    assert code == 0
    for text in ("validate", "test", "report", "1 = reliability gate failed"):
        assert text in out
    for command in ("validate", "test", "report"):
        code, out, _ = invoke(command, "--help")
        assert code == 0
        assert "Usage:" in out


def test_version() -> None:
    code, out, _ = invoke("--version")
    assert code == 0
    assert out.startswith("decguard ")


def test_validate_ok(make_contract: ContractFactory) -> None:
    code, out, _ = invoke("validate", make_contract())
    assert code == 0
    assert "OK" in out
    assert "refund_request (choice): refund, reject, review" in out
    assert "5 cases, 4 labeled" in out


def test_validate_reports_contract_errors_with_exit_2(make_contract: ContractFactory) -> None:
    path = make_contract({"requirements": {"min_acuracy": 0.9}})
    code, out, err = invoke("validate", path)
    assert code == 2
    assert out == ""
    assert "requirements.min_acuracy: unknown field" in err


def test_validate_checks_dataset_labels(make_contract: ContractFactory) -> None:
    path = make_contract(cases=[{"input": "x", "expected": "refnud"}])
    code, _, err = invoke("validate", path)
    assert code == 2
    assert "'refnud' is not one of the contract labels" in err


def test_test_pass_writes_json_report(make_contract: ContractFactory, tmp_path: Path) -> None:
    out_file = tmp_path / "out" / "report.json"
    code, out, err = invoke("test", make_contract(), "--output", out_file)
    assert code == 0, out + err
    assert "PASS" in out
    assert f"report written to {out_file}" in err
    report = json.loads(out_file.read_text())
    assert report["status"] == "pass"
    assert report["exit_code"] == 0
    assert report["report_version"] == "0.1"
    assert report["contract"]["hash"].startswith("sha256:")
    assert report["dataset"]["n_cases"] == 5
    assert report["backend"]["provider"] == "mock"
    assert len(report["results"]) == 5


def test_test_fail_exits_1(make_contract: ContractFactory) -> None:
    code, out, _ = invoke("test", make_contract({"requirements": {"min_accuracy": 0.99}}))
    assert code == 1
    assert "FAIL  min_accuracy" in out
    assert "c4" in out  # the failing example is shown


def test_warn_exits_0_unless_fail_on_warn(make_contract: ContractFactory) -> None:
    path = make_contract({"warnings": {"min_accuracy": 0.99}})
    code, out, _ = invoke("test", path)
    assert code == 0
    assert "WARN" in out
    code, _, _ = invoke("test", path, "--fail-on-warn")
    assert code == 1


def test_json_format_is_machine_readable(make_contract: ContractFactory) -> None:
    code, out, _ = invoke("test", make_contract(), "--format", "json")
    assert code == 0
    assert json.loads(out)["status"] == "pass"


def test_runtime_errors_exit_2(make_contract: ContractFactory, tmp_path: Path) -> None:
    path = make_contract()
    assert invoke("test", path, "--backend", "nope")[0] == 2
    assert invoke("test", path, "--dataset", tmp_path / "missing.jsonl")[0] == 2
    assert invoke("test", tmp_path / "missing.yaml")[0] == 2
    assert invoke("test", path, "--format", "xml")[0] == 2  # usage error


def test_missing_credentials_exit_2(
    make_contract: ContractFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DG_MISSING_TOKEN", raising=False)
    backend = {
        "provider": "http",
        "url": "http://127.0.0.1:9/decide",
        "bearer_token_env": "DG_MISSING_TOKEN",
    }
    code, _, err = invoke("test", make_contract({"backend": backend}), "--no-healthcheck")
    assert code == 2
    assert "DG_MISSING_TOKEN is not set" in err


def test_unexpected_exceptions_exit_2_not_1(
    make_contract: ContractFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise KeyError("surprise")

    monkeypatch.setattr("decguard.cli.run_test", boom)
    code, _, err = invoke("test", make_contract())
    assert code == 2
    assert "internal error: KeyError" in err


def test_report_renders_and_reevaluates(make_contract: ContractFactory, tmp_path: Path) -> None:
    contract = make_contract()
    stored = tmp_path / "report.json"
    assert invoke("test", contract, "-o", stored)[0] == 0

    code, out, _ = invoke("report", stored)
    assert code == 0
    assert "refund_request (choice) · PASS" in out

    # Tighten the gate without re-running the model: the stored results now fail.
    data = yaml.safe_load(contract.read_text())
    data["requirements"]["min_accuracy"] = 0.99
    strict = tmp_path / "strict.yaml"
    strict.write_text(yaml.safe_dump(data))
    code, out, _ = invoke("report", stored, "--contract", strict)
    assert code == 1
    assert "FAIL  min_accuracy" in out

    original = json.loads(stored.read_text())
    code, out, _ = invoke("report", stored, "--contract", contract, "--format", "json")
    assert code == 0
    assert json.loads(out)["metrics"] == original["metrics"]


def test_report_rejects_mismatched_contract(make_contract: ContractFactory, tmp_path: Path) -> None:
    stored = tmp_path / "report.json"
    invoke("test", make_contract(), "-o", stored)
    other = make_contract(
        {"decision": {"name": "other", "type": "noul"}, "backend": {"provider": "mock"}},
        name="other.yaml",
        cases=[],
    )
    code, _, err = invoke("report", stored, "--contract", other)
    assert code == 2
    assert "but the report is for 'refund_request'" in err


def test_report_rejects_non_report_json(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('{"hello": 1}')
    code, _, err = invoke("report", path)
    assert code == 2
    assert "not a DecGuard 0.1 report" in err


@pytest.mark.parametrize("example", sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir()))
def test_examples_pass(example: str) -> None:
    contract = EXAMPLES / example / "decguard.yaml"
    assert invoke("validate", contract)[0] == 0
    code, out, err = invoke("test", contract)
    assert code == 0, out + err
