"""Opt-in check against a real decision backend (never part of the default suite).

    DECGUARD_EXTERNAL_CONTRACT=path/to/decguard.yaml uv run pytest -m external

The contract should point its backend at the real endpoint (e.g. an Open-Jev server
speaking decguard.http/0.1); credentials come from the environment as usual.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from decguard.cli import app
from decguard.reports import Report

CONTRACT = os.environ.get("DECGUARD_EXTERNAL_CONTRACT")

pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(not CONTRACT, reason="set DECGUARD_EXTERNAL_CONTRACT to run"),
]


def test_real_backend_produces_a_valid_report(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    result = CliRunner().invoke(app, ["test", str(CONTRACT), "--output", str(output)])
    assert result.exit_code in (0, 1), result.stdout + result.stderr
    report = Report.model_validate(json.loads(output.read_text()))
    assert report.metrics.counts.succeeded > 0
