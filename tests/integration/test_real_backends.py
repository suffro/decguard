"""Opt-in end-to-end checks against real System One backends. Nothing here is mocked.

    uv run pytest -m real_kev   # needs a Kev server on 127.0.0.1:8009 (docs/backends.md)
    uv run pytest -m real_jev   # needs OPENROUTER_API_KEY; three billed Jev calls

Without ``-m`` these tests are skipped. Once selected with ``-m``, a missing server,
checkpoint or credential fails them: a skip would not prove anything.

Set ``DECGUARD_KEV_RUN`` to the checkpoint the Kev server must be serving (as reported by
its ``GET /v1/models``), and ``DECGUARD_REAL_REPORTS`` to a directory that keeps the JSON
reports.
"""

from __future__ import annotations

import math
import os
import secrets
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner, Result

from decguard.cli import app
from decguard.contracts import load_contract
from decguard.reports import Report, load_report

REAL = Path(__file__).parent / "real"
DECISIONS = ("choice", "noul", "score")
KEV_URL = "http://127.0.0.1:8009"
KEV_MODEL = "kev-latest"
JEV_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "typesafe/jev-1.13"


def invoke(*args: str | Path) -> Result:
    return CliRunner().invoke(app, [str(arg) for arg in args])


def run_contract(decision: str, tmp_path: Path, *options: str) -> tuple[Report, str]:
    """``decguard test`` on a real contract, then ``decguard report`` on its output."""
    output = tmp_path / "report.json"
    result = invoke("test", REAL / f"{decision}.yaml", "--output", output, *options)
    text = result.stdout + result.stderr
    assert result.exit_code == 0, text
    shown = invoke("report", output)
    assert shown.exit_code == 0, shown.stdout + shown.stderr
    assert "PASS" in shown.stdout
    return load_report(output), text + shown.stdout + output.read_text()


def check_decisions(report: Report, decision: str) -> None:
    """Every case got a genuine, valid decision over exactly the contract labels."""
    contract = load_contract(REAL / f"{decision}.yaml").contract
    spec = contract.spec()
    counts = report.metrics.counts
    assert counts.total == len(report.results) > 0
    assert (counts.succeeded, counts.errored) == (counts.total, 0)
    for record in report.results:
        result = record.result
        assert result is not None, record.error
        assert (result.decision, result.decision_type) == (spec.name, spec.type)
        assert result.provider == "systemone"
        assert result.labels == spec.labels
        assert list(result.probabilities) == list(spec.labels)
        assert all(0.0 <= p <= 1.0 for p in result.probabilities.values())
        total = math.fsum(result.probabilities.values())
        assert abs(total - 1.0) <= contract.evaluation.probability_tolerance
        assert result.selected in spec.labels
        assert result.confidence == max(result.probabilities.values())
        assert result.metadata["usage"]["input_tokens"] > 0
        assert result.metadata["request_id"]


def keep(report_text: str, name: str) -> None:
    directory = os.environ.get("DECGUARD_REAL_REPORTS")
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        Path(directory, f"{name}.json").write_text(report_text)


@pytest.fixture(scope="module")
def kev_card() -> dict[str, Any]:
    try:
        response = httpx.get(f"{KEV_URL}/v1/models", timeout=10)
    except httpx.HTTPError as exc:
        pytest.fail(f"no Kev server at {KEV_URL} ({type(exc).__name__}); start kev.serve first")
    assert response.status_code == 200, f"GET /v1/models returned HTTP {response.status_code}"
    cards = {card["name"]: card for card in response.json()["models"]}
    assert KEV_MODEL in cards, f"the server does not serve {KEV_MODEL!r}: {sorted(cards)}"
    card: dict[str, Any] = cards[KEV_MODEL]
    expected = os.environ.get("DECGUARD_KEV_RUN")
    if expected:
        assert card.get("run") == expected, f"Kev serves {card.get('run')!r}, not {expected!r}"
    return card


@pytest.fixture(scope="module")
def openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        pytest.fail("OPENROUTER_API_KEY is not set; the real Jev check needs it")
    return key


@pytest.mark.real_kev
@pytest.mark.parametrize("decision", DECISIONS)
def test_real_kev_decision(decision: str, kev_card: dict[str, Any], tmp_path: Path) -> None:
    report, _ = run_contract(decision, tmp_path)
    check_decisions(report, decision)
    backend = report.backend
    assert (backend.provider, backend.model, backend.model_version) == (
        "systemone",
        KEV_MODEL,
        KEV_MODEL,
    )
    assert backend.details["url"] == f"{KEV_URL}/v1/systemone"
    assert report.health is not None
    assert report.health.status == "ok"
    keep((tmp_path / "report.json").read_text(), f"kev-{decision}")
    print(f"REAL KEV {decision}: {kev_card.get('run')} -> {report.results[0].result}")


@pytest.mark.real_jev
@pytest.mark.parametrize("decision", DECISIONS)
def test_real_jev_decision(decision: str, openrouter_key: str, tmp_path: Path) -> None:
    report, text = run_contract(decision, tmp_path, "--backend", "jev")
    assert openrouter_key not in text, "the API key leaked into output or the report"
    check_decisions(report, decision)
    backend = report.backend
    assert (backend.provider, backend.model) == ("systemone", JEV_MODEL)
    assert backend.model_version is not None
    assert backend.model_version.startswith(JEV_MODEL)  # the dated snapshot that answered
    assert backend.details["url"] == JEV_URL
    assert backend.details["upstream_providers"] == ["TypeSafe"]
    for record in report.results:
        assert record.result is not None
        assert record.result.metadata["upstream_provider"] == "TypeSafe"
    keep((tmp_path / "report.json").read_text(), f"jev-{decision}")
    print(f"REAL JEV {decision}: {report.results[0].result}")


@pytest.mark.real_jev
def test_real_jev_rejected_key_does_not_leak(
    openrouter_key: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A key OpenRouter rejects (HTTP 401, not billed) never appears in errors or output."""
    canary = f"sk-or-v1-decguard-canary-{secrets.token_hex(16)}"
    monkeypatch.setenv("OPENROUTER_API_KEY", canary)
    output = tmp_path / "report.json"
    result = invoke("test", REAL / "choice.yaml", "--backend", "jev", "--output", output)
    text = result.stdout + result.stderr + repr(result.exception)
    if output.exists():
        text += output.read_text()
    assert result.exit_code == 2, text
    assert "HTTP 401" in text
    assert canary not in text
    assert openrouter_key not in text


def test_real_contracts_validate_offline() -> None:
    """The real-backend contracts stay valid without any server or credential."""
    for decision in DECISIONS:
        result = invoke("validate", REAL / f"{decision}.yaml")
        assert result.exit_code == 0, result.stdout + result.stderr
