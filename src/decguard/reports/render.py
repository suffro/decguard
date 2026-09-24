"""Concise human-readable terminal rendering of a report."""

from __future__ import annotations

import json

from decguard.reports.gates import Status
from decguard.reports.model import Report

_MAX_FAILURES_SHOWN = 10


def _num(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _short_hash(value: str) -> str:
    algorithm, _, digest = value.partition(":")
    return f"{algorithm}:{digest[:12]}"


def _input_preview(value: object, width: int = 70) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def render_text(report: Report) -> str:
    m = report.metrics
    c = m.counts
    backend = report.backend
    model = " / ".join(p for p in (backend.model, backend.model_version) if p) or "-"
    lines = [
        f"DecGuard {report.decguard_version} · {report.contract.name} ({report.contract.type})"
        f" · {report.status.value.upper()}",
        "",
        f"  contract  {report.contract.path}  {_short_hash(report.contract.hash)}",
        f"  dataset   {report.dataset.path}  {_short_hash(report.dataset.hash)}",
        f"  backend   {backend.name}: {backend.provider} · {model}",
    ]
    if report.health is not None and report.health.status != "ok":
        lines.append(f"  health    {report.health.status}: {report.health.detail}")

    errors = ", ".join(f"{kind} {n}" for kind, n in c.errors_by_kind.items())
    lines += [
        "",
        f"  Cases        {c.total} total · {c.succeeded} decided · {c.errored} errored"
        + (f" ({errors})" if errors else "")
        + f" · {c.labeled} labeled",
        f"  Accuracy     {_num(m.classification.accuracy)}"
        f"   macro-F1 {_num(m.classification.macro_f1)}"
        + (
            f"   ordinal MAE {_num(m.classification.ordinal_mae)}"
            if m.classification.ordinal_mae is not None
            else ""
        ),
        f"  Calibration  ECE {_num(m.calibration.ece)}   Brier {_num(m.calibration.brier)}"
        f"   NLL {_num(m.calibration.nll)}   ({m.calibration.bins} bins)",
    ]
    if m.selective is not None:
        lines.append(
            f"  Selective    confidence >= {m.selective.threshold:g}:"
            f" coverage {_num(m.selective.coverage)}"
            f"   abstention {_num(m.selective.abstention_rate)}"
            f"   accuracy {_num(m.selective.selective_accuracy)}"
        )
    lines.append(
        f"  Latency ms   mean {_num(m.latency.mean_ms, 1)}   p50 {_num(m.latency.p50_ms, 1)}"
        f"   p95 {_num(m.latency.p95_ms, 1)}   max {_num(m.latency.max_ms, 1)}"
    )

    lines += ["", "  Checks"]
    for check in report.checks:
        tag = "" if check.level == "requirement" else " (warning)"
        lines.append(f"    {check.status.value.upper():<4}  {check.gate:<24} {check.message}{tag}")

    if report.failures:
        shown = report.failures[:_MAX_FAILURES_SHOWN]
        lines += ["", f"  Failures ({len(shown)} of {len(report.failures)})"]
        for failure in shown:
            if failure.kind == "error":
                what = failure.error or "error"
            else:
                what = (
                    f"expected {failure.expected}, got {failure.selected}"
                    f" ({_num(failure.confidence, 2)})"
                )
            lines.append(f"    {failure.case_id:<12} {what}")
            lines.append(f"    {'':<12} input: {_input_preview(failure.input)}")

    verdict = {
        Status.PASS: "PASS: all gates hold",
        Status.WARN: "WARN: requirements hold, some warning gates do not",
        Status.FAIL: "FAIL: at least one requirement does not hold",
    }[report.status]
    lines += ["", verdict]
    return "\n".join(lines)
