"""Aggregate case records into the report's metric sections."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from decguard.contracts.models import Evaluation
from decguard.decisions import DecisionSpec, DecisionType
from decguard.metrics import core
from decguard.runner import CaseRecord


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Counts(_Section):
    total: int
    succeeded: int
    errored: int
    labeled: int
    """Succeeded cases that have an expected label (the base for accuracy/calibration)."""
    errors_by_kind: dict[str, int]
    error_rate: float


class LabelMetrics(_Section):
    precision: float
    recall: float
    f1: float
    support: int


class ClassificationMetrics(_Section):
    n: int
    accuracy: float | None
    macro_f1: float | None
    per_label: dict[str, LabelMetrics]
    ordinal_mae: float | None = None
    """Score decisions only: mean distance between predicted and expected level."""


class ReliabilityBin(_Section):
    lower: float
    upper: float
    count: int
    mean_confidence: float | None
    accuracy: float | None


class CalibrationMetrics(_Section):
    n: int
    ece: float | None
    brier: float | None
    nll: float | None
    bins: int
    reliability: list[ReliabilityBin]


class SelectiveMetrics(_Section):
    threshold: float
    n: int
    coverage: float | None
    """Share of decisions with confidence >= threshold."""
    abstention_rate: float | None
    selective_accuracy: float | None
    """Accuracy on labeled decisions at or above the threshold."""
    n_covered_labeled: int


class LatencyMetrics(_Section):
    n: int
    mean_ms: float | None
    p50_ms: float | None
    p90_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    max_ms: float | None


class Metrics(_Section):
    counts: Counts
    classification: ClassificationMetrics
    calibration: CalibrationMetrics
    selective: SelectiveMetrics | None
    latency: LatencyMetrics

    def gate_values(self) -> dict[str, float | None]:
        """Flat metric values addressed by gates."""
        return {
            "accuracy": self.classification.accuracy,
            "macro_f1": self.classification.macro_f1,
            "ordinal_mae": self.classification.ordinal_mae,
            "nll": self.calibration.nll,
            "brier": self.calibration.brier,
            "ece": self.calibration.ece,
            "coverage": self.selective.coverage if self.selective else None,
            "abstention_rate": self.selective.abstention_rate if self.selective else None,
            "selective_accuracy": self.selective.selective_accuracy if self.selective else None,
            "error_rate": self.counts.error_rate,
            "latency_p95_ms": self.latency.p95_ms,
        }


def compute_metrics(
    spec: DecisionSpec, records: Sequence[CaseRecord], evaluation: Evaluation
) -> Metrics:
    results = [r.result for r in records if r.result is not None]
    labeled = [
        (r.expected, r.result) for r in records if r.result is not None and r.expected is not None
    ]
    expected = [e for e, _ in labeled]
    predicted = [res.selected for _, res in labeled]
    probabilities = [res.probabilities for _, res in labeled]
    errors = Counter(r.error.kind for r in records if r.error is not None)

    counts = Counts(
        total=len(records),
        succeeded=len(results),
        errored=sum(errors.values()),
        labeled=len(labeled),
        errors_by_kind=dict(sorted(errors.items())),
        error_rate=sum(errors.values()) / len(records) if records else 0.0,
    )

    classification = ClassificationMetrics(
        n=len(labeled),
        accuracy=core.accuracy(expected, predicted),
        macro_f1=core.macro_f1(expected, predicted, spec.labels),
        per_label={
            label: LabelMetrics(**vars(scores))
            for label, scores in core.per_label_scores(expected, predicted, spec.labels).items()
        }
        if labeled
        else {},
        ordinal_mae=core.ordinal_mae(expected, predicted, spec.labels)
        if spec.type is DecisionType.SCORE
        else None,
    )

    bins = core.reliability_bins(
        [res.confidence for _, res in labeled],
        [e == p for e, p in zip(expected, predicted, strict=True)],
        evaluation.calibration_bins,
    )
    calibration = CalibrationMetrics(
        n=len(labeled),
        ece=core.expected_calibration_error(bins),
        brier=core.brier(expected, probabilities),
        nll=core.nll(expected, probabilities),
        bins=evaluation.calibration_bins,
        reliability=[ReliabilityBin(**vars(b)) for b in bins],
    )

    selective = None
    threshold = evaluation.confidence_threshold
    if threshold is not None:
        covered = [res.confidence >= threshold for res in results]
        covered_labeled = [(e, res) for e, res in labeled if res.confidence >= threshold]
        coverage = core.mean([float(c) for c in covered])
        selective = SelectiveMetrics(
            threshold=threshold,
            n=len(results),
            coverage=coverage,
            abstention_rate=None if coverage is None else 1.0 - coverage,
            selective_accuracy=core.accuracy(
                [e for e, _ in covered_labeled], [res.selected for _, res in covered_labeled]
            ),
            n_covered_labeled=len(covered_labeled),
        )

    latencies = [res.latency_ms for res in results]
    latency = LatencyMetrics(
        n=len(latencies),
        mean_ms=core.mean(latencies),
        p50_ms=core.percentile(latencies, 50),
        p90_ms=core.percentile(latencies, 90),
        p95_ms=core.percentile(latencies, 95),
        p99_ms=core.percentile(latencies, 99),
        max_ms=max(latencies) if latencies else None,
    )

    return Metrics(
        counts=counts,
        classification=classification,
        calibration=calibration,
        selective=selective,
        latency=latency,
    )
