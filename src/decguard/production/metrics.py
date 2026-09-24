"""Metrics over already-collected production decisions."""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from decguard.contracts.models import Evaluation
from decguard.metrics import core
from decguard.metrics.summary import ReliabilityBin
from decguard.production.records import ProductionRecord


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProductionCounts(_Section):
    total: int
    with_outcome: int
    with_correctness: int
    with_action: int
    with_fallback: int
    with_latency: int
    with_cost: int


class OutcomeMetrics(_Section):
    n: int
    accuracy: float | None
    error_rate: float | None


class ProductionCalibration(_Section):
    n: int
    ece: float | None
    n_label_outcomes: int
    brier: float | None
    nll: float | None
    bins: int
    reliability: list[ReliabilityBin]


class ConfidenceMetrics(_Section):
    n: int
    mean: float | None
    p50: float | None
    p95: float | None
    histogram: list[int]


class ThresholdMetrics(_Section):
    threshold: float
    n: int
    coverage: float | None


class RoutingMetrics(_Section):
    n_actions: int
    abstention_rate: float | None
    human_review_rate: float | None
    n_fallback: int
    fallback_rate: float | None


class OptionalAggregate(_Section):
    n: int
    mean: float | None
    p95: float | None
    total: float | None = None


class ProductionMetrics(_Section):
    counts: ProductionCounts
    outcomes: OutcomeMetrics
    calibration: ProductionCalibration
    confidence: ConfidenceMetrics
    threshold: ThresholdMetrics | None
    routing: RoutingMetrics
    latency_ms: OptionalAggregate
    cost: OptionalAggregate

    def gate_values(self) -> dict[str, float | None]:
        return {
            "accuracy": self.outcomes.accuracy,
            "error_rate": self.outcomes.error_rate,
            "ece": self.calibration.ece,
            "brier": self.calibration.brier,
            "nll": self.calibration.nll,
            "threshold_coverage": self.threshold.coverage if self.threshold else None,
            "abstention_rate": self.routing.abstention_rate,
            "fallback_rate": self.routing.fallback_rate,
        }


def _histogram(values: Sequence[float], n_bins: int) -> list[int]:
    counts = [0] * n_bins
    edges = [(index + 1) / n_bins for index in range(n_bins)]
    for value in values:
        counts[min(bisect_left(edges, value), n_bins - 1)] += 1
    return counts


def _optional(values: list[float], *, total: bool = False) -> OptionalAggregate:
    return OptionalAggregate(
        n=len(values),
        mean=core.mean(values),
        p95=core.percentile(values, 95),
        total=math.fsum(values) if values and total else None,
    )


def compute_production_metrics(
    records: Sequence[ProductionRecord], evaluation: Evaluation
) -> ProductionMetrics:
    correctness = [record for record in records if record.outcome_correct is not None]
    correct = [bool(record.outcome_correct) for record in correctness]
    outcome_records = [record for record in records if record.outcome is not None]
    confidences = [record.confidence for record in records]
    calibration_bins = core.reliability_bins(
        [record.confidence for record in correctness], correct, evaluation.calibration_bins
    )
    actions = [record.action for record in records if record.action is not None]
    fallback_known = [
        record for record in records if record.fallback is not None or record.action is not None
    ]
    fallback_values = [
        record.fallback is True or record.action == "fallback" for record in fallback_known
    ]
    latencies = [record.latency_ms for record in records if record.latency_ms is not None]
    costs = [record.cost for record in records if record.cost is not None]
    accuracy = core.mean([float(value) for value in correct])

    threshold = None
    if evaluation.confidence_threshold is not None:
        value = evaluation.confidence_threshold
        threshold = ThresholdMetrics(
            threshold=value,
            n=len(records),
            coverage=core.mean([float(record.confidence >= value) for record in records]),
        )

    return ProductionMetrics(
        counts=ProductionCounts(
            total=len(records),
            with_outcome=len(outcome_records),
            with_correctness=len(correctness),
            with_action=len(actions),
            with_fallback=len(fallback_known),
            with_latency=len(latencies),
            with_cost=len(costs),
        ),
        outcomes=OutcomeMetrics(
            n=len(correctness),
            accuracy=accuracy,
            error_rate=None if accuracy is None else 1.0 - accuracy,
        ),
        calibration=ProductionCalibration(
            n=len(correctness),
            ece=core.expected_calibration_error(calibration_bins),
            n_label_outcomes=len(outcome_records),
            brier=core.brier(
                [record.outcome for record in outcome_records if record.outcome is not None],
                [record.probabilities for record in outcome_records],
            ),
            nll=core.nll(
                [record.outcome for record in outcome_records if record.outcome is not None],
                [record.probabilities for record in outcome_records],
            ),
            bins=evaluation.calibration_bins,
            reliability=[ReliabilityBin(**vars(item)) for item in calibration_bins],
        ),
        confidence=ConfidenceMetrics(
            n=len(confidences),
            mean=core.mean(confidences),
            p50=core.percentile(confidences, 50),
            p95=core.percentile(confidences, 95),
            histogram=_histogram(confidences, evaluation.calibration_bins),
        ),
        threshold=threshold,
        routing=RoutingMetrics(
            n_actions=len(actions),
            abstention_rate=core.mean([float(action == "abstain") for action in actions]),
            human_review_rate=core.mean([float(action == "human_review") for action in actions]),
            n_fallback=len(fallback_known),
            fallback_rate=core.mean([float(value) for value in fallback_values]),
        ),
        latency_ms=_optional(latencies),
        cost=_optional(costs, total=True),
    )
