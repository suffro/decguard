"""The same dataset against two backends implementing the same interface."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from decguard.backends import CallableBackend, MockBackend, MockSettings
from decguard.contracts import load_contract
from decguard.datasets import load_dataset
from decguard.engine import run_test
from decguard.errors import DecGuardError
from decguard.runner import run_cases
from tests.conftest import CHOICE_CASES, CHOICE_CONTRACT, write_jsonl, write_yaml
from tests.integration.conftest import DecisionServer, start_server

# Fields that legitimately differ between backends for the same decision.
PROVENANCE = {"backend", "provider", "latency_ms"}


def _two_backend_contract(tmp_path: Path, server: DecisionServer) -> Path:
    data = copy.deepcopy(CHOICE_CONTRACT)
    del data["backend"]["rules"], data["backend"]["default"]
    data["backend"]["model_version"] = "1"
    data["backends"] = {
        "remote": {
            "provider": "http",
            "url": server.base_url + "/decide",
            "health_url": server.base_url + "/health",
            "model": "unit-mock",
        }
    }
    data["requirements"] = {}
    write_jsonl(tmp_path / "cases.jsonl", CHOICE_CASES)
    return write_yaml(tmp_path / "decguard.yaml", data)


def _normalized(report: Any) -> list[dict[str, Any]]:
    return [
        {k: v for k, v in record.result.model_dump().items() if k not in PROVENANCE}
        for record in report.results
    ]


def test_mock_and_http_normalize_identically(
    tmp_path: Path, decision_server: DecisionServer
) -> None:
    contract = _two_backend_contract(tmp_path, decision_server)
    local = run_test(contract)
    remote = run_test(contract, backend="remote")

    assert local.backend.provider == "mock"
    assert remote.backend.provider == "http"
    assert remote.health is not None
    assert remote.health.status == "ok"
    assert len(decision_server.requests_seen) == len(CHOICE_CASES)
    assert _normalized(local) == _normalized(remote)
    for key in ("classification", "calibration", "counts"):
        assert getattr(local.metrics, key) == getattr(remote.metrics, key)
    assert local.status == remote.status
    assert local.contract.hash == remote.contract.hash
    assert local.dataset.hash == remote.dataset.hash


def test_rerunning_is_reproducible(tmp_path: Path, decision_server: DecisionServer) -> None:
    contract = _two_backend_contract(tmp_path, decision_server)
    first = run_test(contract, backend="remote", max_concurrency=4)
    second = run_test(contract, backend="remote", max_concurrency=1)
    assert _normalized(first) == _normalized(second)
    assert first.metrics.classification == second.metrics.classification
    assert first.metrics.calibration == second.metrics.calibration


def test_backend_failing_every_case_is_a_runtime_error(
    tmp_path: Path, decision_server: DecisionServer
) -> None:
    decision_server.fail_with = 500
    contract = _two_backend_contract(tmp_path, decision_server)
    with pytest.raises(DecGuardError, match="failed on every case; first error: backend_error"):
        run_test(contract, backend="remote")


def test_unhealthy_backend_stops_before_running(tmp_path: Path) -> None:
    server = start_server(MockBackend())
    contract = _two_backend_contract(tmp_path, server)
    server.shutdown()
    server.server_close()
    with pytest.raises(DecGuardError, match="unhealthy"):
        run_test(contract, backend="remote")


def test_partial_failures_are_counted_not_dropped(tmp_path: Path) -> None:
    def flaky(request: Any) -> dict[str, float]:
        if request.case_id == "c3":
            raise RuntimeError("plugin bug")
        return {"refund": 0.8, "reject": 0.1, "review": 0.1}

    contract = write_yaml(tmp_path / "decguard.yaml", CHOICE_CONTRACT)
    write_jsonl(tmp_path / "cases.jsonl", CHOICE_CASES)
    report = run_test(contract, backend=CallableBackend(flaky))
    assert report.metrics.counts.total == len(CHOICE_CASES)
    assert report.metrics.counts.errors_by_kind == {"exception": 1}
    assert [r.case_id for r in report.results] == [c["id"] for c in CHOICE_CASES]
    error = next(f for f in report.failures if f.kind == "error")
    assert error.case_id == "c3"
    assert error.error == "exception: RuntimeError: plugin bug"
    assert report.status.value == "fail"


def test_concurrency_preserves_dataset_order(tmp_path: Path) -> None:
    rows = [{"id": f"k{i}", "input": f"text {i}"} for i in range(50)]
    path = write_jsonl(tmp_path / "many.jsonl", rows)
    loaded = load_contract(write_yaml(tmp_path / "decguard.yaml", CHOICE_CONTRACT))
    spec = loaded.contract.spec()
    cases = load_dataset(path, spec).cases
    backend = MockBackend(MockSettings(seed=5))
    serial = run_cases(backend, spec, cases, max_concurrency=1)
    parallel = run_cases(backend, spec, cases, max_concurrency=8)
    assert [r.case_id for r in parallel] == [row["id"] for row in rows]
    assert [r.result.probabilities for r in parallel if r.result] == [
        r.result.probabilities for r in serial if r.result
    ]
