"""Compare a candidate run with a baseline run of the same decision.

Cases are matched by id. Per-case shifts (answer flips, confidence, distribution distance)
use cases both runs decided; metrics are recomputed on the matched cases of each run with
the same evaluation settings, so datasets that differ slightly remain comparable.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from decguard import __version__
from decguard.backends.base import BackendMetadata
from decguard.contracts.loader import LoadedContract, load_contract
from decguard.contracts.models import Evaluation
from decguard.contracts.properties import Regression, RegressionGates
from decguard.decisions import DecisionInput, DecisionSpec
from decguard.errors import ReportError
from decguard.metrics import Metrics, compute_metrics
from decguard.metrics import distribution as dist
from decguard.metrics.core import mean
from decguard.reports.gates import Check, Level, Status, make_check, overall_status
from decguard.reports.model import (
    EXIT_CODES,
    ContractInfo,
    DatasetInfo,
    Report,
    ensure_same_decision,
    load_report,
)
from decguard.reports.render import describe_example, num, pct
from decguard.runner import CaseRecord

DIFF_VERSION: Final = "0.1"
MISSING_SEGMENT = "(missing)"


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RunInfo(_Section):
    path: str
    created_at: str
    mode: str
    contract_hash: str
    dataset: DatasetInfo
    backend: BackendMetadata


class DiffCounts(_Section):
    baseline_cases: int
    candidate_cases: int
    matched: int
    only_in_baseline: int
    only_in_candidate: int
    compared: int
    """Matched cases both runs decided."""
    answer_flips: int
    newly_wrong: int
    """Labeled cases the baseline got right and the candidate gets wrong."""
    newly_correct: int
    newly_errored: int
    recovered: int
    """Cases the baseline failed on and the candidate decides."""
    still_errored: int


class Shift(_Section):
    answer_flip_rate: float | None
    mean_tv_distance: float | None
    max_tv_distance: float | None
    mean_js_divergence: float | None
    mean_confidence_delta: float | None
    """Signed: candidate minus baseline confidence."""
    mean_abs_confidence_delta: float | None
    max_abs_confidence_delta: float | None


class MetricDelta(_Section):
    baseline: float | None
    candidate: float | None
    delta: float | None
    """Candidate minus baseline."""


class SegmentDiff(_Section):
    key: str
    value: str
    matched: int
    compared: int
    baseline_accuracy: float | None
    candidate_accuracy: float | None
    accuracy_drop: float | None
    answer_flip_rate: float | None
    gated: bool
    """At least ``min_segment_size`` matched cases."""


class CaseChange(_Section):
    case_id: str
    kind: Literal["flip", "newly_errored", "recovered"]
    input: DecisionInput
    expected: str | None = None
    baseline_selected: str | None = None
    candidate_selected: str | None = None
    baseline_confidence: float | None = None
    candidate_confidence: float | None = None
    tv_distance: float | None = None
    error: str | None = None


class DiffReport(_Section):
    diff_version: Literal["0.1"] = DIFF_VERSION
    decguard_version: str
    created_at: str
    status: Status
    exit_code: int
    contract: ContractInfo
    baseline: RunInfo
    candidate: RunInfo
    same_dataset: bool
    evaluation: Evaluation
    counts: DiffCounts
    shift: Shift
    metrics: dict[str, MetricDelta]
    segments: list[SegmentDiff]
    checks: list[Check]
    changes: list[CaseChange]


# regression gate -> (value key, comparison)
REGRESSION_GATES: dict[str, str] = {
    "max_answer_flip_rate": "answer_flip_rate",
    "max_accuracy_drop": "accuracy_drop",
    "max_macro_f1_drop": "macro_f1_drop",
    "max_ece_increase": "ece_increase",
    "max_brier_increase": "brier_increase",
    "max_nll_increase": "nll_increase",
    "max_mean_tv_distance": "mean_tv_distance",
    "max_mean_confidence_shift": "mean_abs_confidence_delta",
    "max_error_rate_increase": "error_rate_increase",
    "max_latency_p95_increase_ms": "latency_p95_increase_ms",
    "max_segment_accuracy_drop": "segment_accuracy_drop",
}
assert set(REGRESSION_GATES) == set(RegressionGates.model_fields)


def _metric_values(m: Metrics) -> dict[str, float | None]:
    return {
        "accuracy": m.classification.accuracy,
        "macro_f1": m.classification.macro_f1,
        "ordinal_mae": m.classification.ordinal_mae,
        "ece": m.calibration.ece,
        "brier": m.calibration.brier,
        "nll": m.calibration.nll,
        "coverage": m.selective.coverage if m.selective else None,
        "error_rate": m.counts.error_rate,
        "latency_p50_ms": m.latency.p50_ms,
        "latency_p95_ms": m.latency.p95_ms,
    }


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else b - a


def _run_info(report: Report, path: str) -> RunInfo:
    return RunInfo(
        path=path,
        created_at=report.created_at,
        mode=report.mode,
        contract_hash=report.contract.hash,
        dataset=report.dataset,
        backend=report.backend,
    )


def _segment_value(record: CaseRecord, key: str) -> str:
    if key not in record.metadata:
        return MISSING_SEGMENT
    value: Any = record.metadata[key]
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _accuracy(pairs: Sequence[tuple[CaseRecord, CaseRecord]], side: int) -> float | None:
    hits = [
        result.selected == record.expected
        for record in (pair[side] for pair in pairs)
        if record.expected is not None and (result := record.result) is not None
    ]
    return sum(hits) / len(hits) if hits else None


def diff_reports(
    baseline: Report,
    candidate: Report,
    *,
    contract: LoadedContract | None = None,
    segment_by: Sequence[str] | None = None,
    baseline_path: str = "baseline",
    candidate_path: str = "candidate",
) -> DiffReport:
    """Compare two reports of the same decision and apply the contract's regression gates
    (``max_error_rate_increase`` defaults to 0 as a requirement)."""
    if (baseline.contract.name, baseline.contract.type, baseline.contract.labels) != (
        candidate.contract.name,
        candidate.contract.type,
        candidate.contract.labels,
    ):
        raise ReportError(
            f"cannot compare {baseline.contract.name!r} ({list(baseline.contract.labels)}) "
            f"with {candidate.contract.name!r} ({list(candidate.contract.labels)})"
        )
    if contract is not None:
        ensure_same_decision(candidate, contract)
    regression = contract.contract.regression if contract is not None else Regression()
    evaluation = contract.contract.evaluation if contract is not None else candidate.evaluation
    spec = contract.contract.spec() if contract is not None else _spec_from(candidate)
    keys = tuple(segment_by) if segment_by else regression.segment_by

    base_by_id = baseline.records_by_id()
    cand_by_id = candidate.records_by_id()
    matched_ids = [record.case_id for record in candidate.results if record.case_id in base_by_id]
    pairs = [(base_by_id[i], cand_by_id[i]) for i in matched_ids]

    shift, tally, changes = _compare_cases(pairs, spec.labels)
    counts = DiffCounts(
        baseline_cases=len(baseline.results),
        candidate_cases=len(candidate.results),
        matched=len(pairs),
        only_in_baseline=len(base_by_id) - len(pairs),
        only_in_candidate=len(cand_by_id) - len(pairs),
        **tally,
    )

    base_metrics = _metric_values(compute_metrics(spec, [b for b, _ in pairs], evaluation))
    cand_metrics = _metric_values(compute_metrics(spec, [c for _, c in pairs], evaluation))
    metrics = {
        name: MetricDelta(
            baseline=base_metrics[name],
            candidate=cand_metrics[name],
            delta=_delta(base_metrics[name], cand_metrics[name]),
        )
        for name in base_metrics
    }

    segments = _segments(pairs, keys, regression.min_segment_size)
    gated = [s for s in segments if s.gated and s.accuracy_drop is not None]
    worst = max(gated, key=lambda s: s.accuracy_drop or 0.0, default=None)

    def drop(name: str) -> float | None:
        delta = metrics[name].delta
        return None if delta is None else -delta

    values: dict[str, float | None] = {
        "answer_flip_rate": shift.answer_flip_rate,
        "accuracy_drop": drop("accuracy"),
        "macro_f1_drop": drop("macro_f1"),
        "ece_increase": metrics["ece"].delta,
        "brier_increase": metrics["brier"].delta,
        "nll_increase": metrics["nll"].delta,
        "mean_tv_distance": shift.mean_tv_distance,
        "mean_abs_confidence_delta": shift.mean_abs_confidence_delta,
        "error_rate_increase": metrics["error_rate"].delta,
        "latency_p95_increase_ms": metrics["latency_p95_ms"].delta,
        "segment_accuracy_drop": worst.accuracy_drop if worst else None,
    }
    worst_detail = f"worst segment {worst.key}={worst.value}" if worst else ""

    def check(gate: str, threshold: float, level: Level) -> Check:
        return make_check(
            gate,
            REGRESSION_GATES[gate],
            "<=",
            threshold,
            values[REGRESSION_GATES[gate]],
            level=level,
            missing="no comparable cases",
            detail=worst_detail if gate == "max_segment_accuracy_drop" else "",
        )

    required = regression.configured()
    required.setdefault("max_error_rate_increase", 0.0)
    checks = [check(gate, t, "requirement") for gate, t in required.items()]
    checks += [check(gate, t, "warning") for gate, t in regression.warnings.configured().items()]
    status = overall_status(checks)

    return DiffReport(
        decguard_version=__version__,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        status=status,
        exit_code=EXIT_CODES[status],
        contract=candidate.contract,
        baseline=_run_info(baseline, baseline_path),
        candidate=_run_info(candidate, candidate_path),
        same_dataset=baseline.dataset.hash == candidate.dataset.hash,
        evaluation=evaluation,
        counts=counts,
        shift=shift,
        metrics=metrics,
        segments=segments,
        checks=checks,
        changes=changes,
    )


def _compare_cases(
    pairs: Sequence[tuple[CaseRecord, CaseRecord]], labels: Sequence[str]
) -> tuple[Shift, dict[str, int], list[CaseChange]]:
    """Per-case differences between matched baseline and candidate records."""
    changes: list[CaseChange] = []
    tv: list[float] = []
    js: list[float] = []
    conf: list[float] = []
    flips = newly_wrong = newly_correct = newly_errored = recovered = still_errored = 0
    for base, cand in pairs:
        if base.result is None and cand.result is None:
            still_errored += 1
            continue
        if cand.result is None:
            newly_errored += 1
            assert cand.error is not None
            changes.append(
                CaseChange(
                    case_id=cand.case_id,
                    kind="newly_errored",
                    input=cand.input,
                    expected=cand.expected,
                    baseline_selected=base.result.selected if base.result else None,
                    error=f"{cand.error.kind}: {cand.error.message}",
                )
            )
            continue
        if base.result is None:
            recovered += 1
            changes.append(
                CaseChange(
                    case_id=cand.case_id,
                    kind="recovered",
                    input=cand.input,
                    expected=cand.expected,
                    candidate_selected=cand.result.selected,
                    candidate_confidence=cand.result.confidence,
                )
            )
            continue
        p, q = base.result.probabilities, cand.result.probabilities
        distance = dist.tv_distance(p, q, labels)
        tv.append(distance)
        js.append(dist.js_divergence(p, q, labels))
        conf.append(cand.result.confidence - base.result.confidence)
        if base.result.selected != cand.result.selected:
            flips += 1
            expected = cand.expected
            if expected is not None:
                newly_wrong += base.result.selected == expected
                newly_correct += cand.result.selected == expected
            changes.append(
                CaseChange(
                    case_id=cand.case_id,
                    kind="flip",
                    input=cand.input,
                    expected=expected,
                    baseline_selected=base.result.selected,
                    candidate_selected=cand.result.selected,
                    baseline_confidence=base.result.confidence,
                    candidate_confidence=cand.result.confidence,
                    tv_distance=distance,
                )
            )

    shift = Shift(
        answer_flip_rate=flips / len(tv) if tv else None,
        mean_tv_distance=mean(tv),
        max_tv_distance=max(tv) if tv else None,
        mean_js_divergence=mean(js),
        mean_confidence_delta=mean(conf),
        mean_abs_confidence_delta=mean([abs(c) for c in conf]),
        max_abs_confidence_delta=max((abs(c) for c in conf), default=None),
    )
    tally = {
        "compared": len(tv),
        "answer_flips": flips,
        "newly_wrong": newly_wrong,
        "newly_correct": newly_correct,
        "newly_errored": newly_errored,
        "recovered": recovered,
        "still_errored": still_errored,
    }
    return shift, tally, changes


def _spec_from(report: Report) -> DecisionSpec:
    return DecisionSpec(
        name=report.contract.name, type=report.contract.type, labels=report.contract.labels
    )


def _segments(
    pairs: Sequence[tuple[CaseRecord, CaseRecord]], keys: Sequence[str], min_size: int
) -> list[SegmentDiff]:
    segments = []
    for key in keys:
        groups: dict[str, list[tuple[CaseRecord, CaseRecord]]] = {}
        for pair in pairs:
            groups.setdefault(_segment_value(pair[1], key), []).append(pair)
        for value in sorted(groups):
            group = groups[value]
            decided = [
                (b.result, c.result)
                for b, c in group
                if b.result is not None and c.result is not None
            ]
            flips = len([1 for b, c in decided if b.selected != c.selected])
            base_acc, cand_acc = _accuracy(group, 0), _accuracy(group, 1)
            segments.append(
                SegmentDiff(
                    key=key,
                    value=value,
                    matched=len(group),
                    compared=len(decided),
                    baseline_accuracy=base_acc,
                    candidate_accuracy=cand_acc,
                    accuracy_drop=None
                    if base_acc is None or cand_acc is None
                    else base_acc - cand_acc,
                    answer_flip_rate=flips / len(decided) if decided else None,
                    gated=len(group) >= min_size,
                )
            )
    return segments


def load_and_diff(
    baseline: str | Path,
    candidate: str | Path,
    *,
    contract: str | Path | None = None,
    segment_by: Sequence[str] | None = None,
) -> DiffReport:
    return diff_reports(
        load_report(baseline),
        load_report(candidate),
        contract=load_contract(contract) if contract is not None else None,
        segment_by=segment_by,
        baseline_path=str(baseline),
        candidate_path=str(candidate),
    )


def write_diff(report: DiffReport, path: str | Path) -> None:
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"{path}: cannot write diff: {exc.strerror or exc}") from exc


def render_diff_text(report: DiffReport, *, max_changes: int = 10) -> str:
    c, s = report.counts, report.shift
    lines = [
        f"DecGuard {report.decguard_version} · diff {report.contract.name}"
        f" ({report.contract.type}) · {report.status.value.upper()}",
        "",
    ]
    for role, run in (("baseline", report.baseline), ("candidate", report.candidate)):
        model = " / ".join(p for p in (run.backend.model, run.backend.model_version) if p) or "-"
        lines.append(
            f"  {role:<10}{run.path}  {run.backend.name}: {run.backend.provider} · {model}"
        )
    if not report.same_dataset:
        lines.append("  note      the runs used different datasets; cases are matched by id")
    lines += [
        "",
        f"  Cases        {c.matched} matched · {c.compared} compared"
        f" · {c.only_in_baseline} only in baseline · {c.only_in_candidate} only in candidate",
        f"  Answers      {c.answer_flips} flipped ({pct(s.answer_flip_rate)})"
        f" · {c.newly_wrong} newly wrong · {c.newly_correct} newly correct",
        f"  Errors       {c.newly_errored} new · {c.recovered} recovered · {c.still_errored} still",
        f"  Shift        mean TV {num(s.mean_tv_distance)}   max TV {num(s.max_tv_distance)}"
        f"   mean JS {num(s.mean_js_divergence)}",
        f"  Confidence   mean shift {num(s.mean_confidence_delta)}"
        f"   mean |shift| {num(s.mean_abs_confidence_delta)}"
        f"   max |shift| {num(s.max_abs_confidence_delta)}",
        "",
        f"  {'Metric':<16}{'baseline':>10}{'candidate':>11}{'delta':>10}",
    ]
    for name, m in report.metrics.items():
        if m.baseline is None and m.candidate is None:
            continue
        lines.append(
            f"  {name:<16}{num(m.baseline):>10}{num(m.candidate):>11}"
            f"{'n/a' if m.delta is None else f'{m.delta:+.3f}':>10}"
        )
    if report.segments:
        lines += ["", "  Segments"]
        for seg in report.segments:
            lines.append(
                f"    {seg.key}={seg.value:<14} n={seg.matched:<4}"
                f" accuracy {num(seg.baseline_accuracy)} -> {num(seg.candidate_accuracy)}"
                f"   flips {pct(seg.answer_flip_rate)}"
                + ("" if seg.gated else "   (not gated: small)")
            )
    lines += ["", "  Checks"]
    for check in report.checks:
        tag = "" if check.level == "requirement" else " (warning)"
        lines.append(f"    {check.status.value.upper():<4}  {check.gate:<30} {check.message}{tag}")
    if report.changes:
        shown = report.changes[:max_changes]
        lines += ["", f"  Changes ({len(shown)} of {len(report.changes)})"]
        for change in shown:
            if change.kind == "flip":
                what = (
                    f"{change.baseline_selected} ({num(change.baseline_confidence, 2)}) -> "
                    f"{change.candidate_selected} ({num(change.candidate_confidence, 2)})"
                    + (f", expected {change.expected}" if change.expected else "")
                )
            elif change.kind == "newly_errored":
                what = f"now errors: {change.error}"
            else:
                what = f"recovered: {change.candidate_selected}"
            lines.append(f"    {change.case_id:<12} {what}")
            lines.append(f"    {'':<12} input: {describe_example(None, change.input)}")
    verdict = {
        Status.PASS: "PASS: no regression gate is violated",
        Status.WARN: "WARN: requirements hold, some warning gates do not",
        Status.FAIL: "FAIL: the candidate regresses beyond the contract's limits",
    }[report.status]
    lines += ["", verdict]
    return "\n".join(lines)
