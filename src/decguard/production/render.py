"""Concise terminal rendering for production reports."""

from __future__ import annotations

from typing import Any

from decguard.production.report import ProductionReport
from decguard.reports.gates import Status


def _number(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _segment_value(value: Any) -> str:
    return "<missing>" if value is None else str(value)


def render_production_text(report: ProductionReport) -> str:
    metrics = report.metrics
    lines = [
        f"DecGuard {report.decguard_version} · {report.contract.name} "
        f"({report.contract.type}) · {report.status.upper()}",
        "",
        f"  Records       {metrics.counts.total} total · "
        f"{metrics.counts.with_correctness} with correctness · "
        f"{metrics.counts.with_outcome} with label outcome",
        f"  Outcomes      accuracy {_number(metrics.outcomes.accuracy)} · "
        f"error {_number(metrics.outcomes.error_rate)}",
        f"  Calibration   ECE {_number(metrics.calibration.ece)} · "
        f"Brier {_number(metrics.calibration.brier)} · NLL {_number(metrics.calibration.nll)}",
        f"  Confidence    mean {_number(metrics.confidence.mean)} · "
        f"p50 {_number(metrics.confidence.p50)} · p95 {_number(metrics.confidence.p95)}",
    ]
    if metrics.threshold is not None:
        lines.append(
            f"  Threshold     confidence >= {metrics.threshold.threshold:g}: "
            f"coverage {_number(metrics.threshold.coverage)}"
        )
    lines.append(
        f"  Routing       abstain {_number(metrics.routing.abstention_rate)} · "
        f"fallback {_number(metrics.routing.fallback_rate)} · "
        f"review {_number(metrics.routing.human_review_rate)}"
    )
    if report.baseline is not None:
        lines += [
            "",
            f"  Baseline      {report.baseline.source} · {report.baseline.n_records} records",
            f"  Drift         confidence TV {_number(report.drift.confidence_tv_distance)} · "
            f"mean delta {_number(report.drift.confidence_mean_delta)} · "
            f"accuracy drop {_number(report.drift.accuracy_drop)} · "
            f"ECE increase {_number(report.drift.ece_increase)}",
        ]
    if report.segments:
        lines += ["", "  Segments"]
        for segment in report.segments:
            lines.append(
                f"    {segment.status.upper():<4} {segment.key}="
                f"{_segment_value(segment.value)} · {segment.metrics.counts.total} records · "
                f"accuracy {_number(segment.metrics.outcomes.accuracy)} · "
                f"ECE {_number(segment.metrics.calibration.ece)}"
            )
    if report.checks:
        lines += ["", "  Checks"]
        for check in report.checks:
            lines.append(f"    {check.status.upper():<4}  {check.gate:<48} {check.message}")
    verdict = {
        Status.PASS: "PASS: all post-deployment gates hold",
        Status.WARN: "WARN: requirements hold, some warning gates do not",
        Status.FAIL: "FAIL: at least one post-deployment requirement does not hold",
    }[report.status]
    lines += ["", verdict]
    return "\n".join(lines)
