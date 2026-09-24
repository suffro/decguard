"""Concise human-readable terminal rendering of a report."""

from __future__ import annotations

import json

from decguard.reports.gates import Status
from decguard.reports.model import Report
from decguard.reports.properties import Presentation, PropertyRun

_MAX_FAILURES_SHOWN = 10


def num(value: float | None, digits: int = 3) -> str:
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
    ]
    if report.mode != "fuzz":
        lines += _golden_lines(report)
    if report.properties is not None:
        lines += _property_lines(report.properties)

    lines += ["", "  Checks"]
    for check in report.checks:
        tag = "" if check.level == "requirement" else " (warning)"
        lines.append(f"    {check.status.value.upper():<4}  {check.gate:<38} {check.message}{tag}")

    if report.failures and report.mode != "fuzz":
        shown = report.failures[:_MAX_FAILURES_SHOWN]
        lines += ["", f"  Failures ({len(shown)} of {len(report.failures)})"]
        for failure in shown:
            if failure.kind == "error":
                what = failure.error or "error"
            else:
                what = (
                    f"expected {failure.expected}, got {failure.selected}"
                    f" ({num(failure.confidence, 2)})"
                )
            lines.append(f"    {failure.case_id:<12} {what}")
            lines.append(f"    {'':<12} input: {_input_preview(failure.input)}")
    if report.properties is not None:
        lines += _property_failure_lines(report.properties)

    lines += ["", _VERDICTS[report.status]]
    return "\n".join(lines)


_VERDICTS = {
    Status.PASS: "PASS: all gates hold",
    Status.WARN: "WARN: requirements hold, some warning gates do not",
    Status.FAIL: "FAIL: at least one requirement does not hold",
}


def _golden_lines(report: Report) -> list[str]:
    m = report.metrics
    lines = [
        f"  Accuracy     {num(m.classification.accuracy)}"
        f"   macro-F1 {num(m.classification.macro_f1)}"
        + (
            f"   ordinal MAE {num(m.classification.ordinal_mae)}"
            if m.classification.ordinal_mae is not None
            else ""
        ),
        f"  Calibration  ECE {num(m.calibration.ece)}   Brier {num(m.calibration.brier)}"
        f"   NLL {num(m.calibration.nll)}   ({m.calibration.bins} bins)",
    ]
    if m.selective is not None:
        lines.append(
            f"  Selective    confidence >= {m.selective.threshold:g}:"
            f" coverage {num(m.selective.coverage)}"
            f"   abstention {num(m.selective.abstention_rate)}"
            f"   accuracy {num(m.selective.selective_accuracy)}"
        )
    lines.append(
        f"  Latency ms   mean {num(m.latency.mean_ms, 1)}   p50 {num(m.latency.p50_ms, 1)}"
        f"   p95 {num(m.latency.p95_ms, 1)}   max {num(m.latency.max_ms, 1)}"
    )
    return lines


def _property_lines(run: PropertyRun) -> list[str]:
    lines = ["", f"  Properties   seed {run.seed}"]
    for s in run.summaries:
        parts = [
            f"{s.n_evaluated} compared",
            f"{s.n_violations} violating ({pct(s.violation_rate)})",
            f"flips {s.n_flips} ({pct(s.flip_rate)})",
        ]
        if s.max_level_decrease is not None:
            parts.append(f"max level drop {num(s.max_level_decrease)}")
        else:
            parts.append(f"max TV {num(s.max_tv_distance)}")
        if s.n_errors:
            parts.append(f"{s.n_errors} errored")
        if s.n_skipped:
            parts.append(f"{s.n_skipped} skipped")
        lines.append(f"    {s.property:<20} " + " · ".join(parts))
    return lines


def describe_example(presentation: Presentation | None, value: object) -> str:
    """One line: the options as shown (when reordered/reformatted) and the input."""
    text = _input_preview(value)
    if presentation:
        shown = ", ".join(shown for shown, _ in presentation)
        text = f"options [{shown}] · {text}"
    return text


def _property_failure_lines(run: PropertyRun) -> list[str]:
    failures = run.failures()
    if not failures:
        return []
    shown = failures[:_MAX_FAILURES_SHOWN]
    lines = [
        "",
        f"  Property failures ({len(shown)} of {len(failures)}; replay with `decguard replay`)",
    ]
    for pair in shown:
        lines.append(f"    {pair.id}")
        if pair.error is not None:
            lines.append(f"      error: {pair.error.kind}: {pair.error.message}")
        else:
            lines.append(f"      {'; '.join(pair.violations)}")
        lines.append(f"      sent: {describe_example(pair.presentation, pair.input)}")
        if pair.reduced is not None:
            lines.append(
                f"      minimal: {describe_example(pair.reduced.presentation, pair.reduced.input)}"
                f" ({'; '.join(pair.reduced.violations)})"
            )
    return lines


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"
