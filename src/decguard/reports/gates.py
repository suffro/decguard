"""Turn contract gates and metrics into PASS / WARN / FAIL checks."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from decguard.contracts.models import Gates
from decguard.metrics import Metrics


class Status(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


# gate key -> (metric name, comparison that must hold)
GATES: dict[str, tuple[str, Literal[">=", "<="]]] = {
    "min_accuracy": ("accuracy", ">="),
    "min_macro_f1": ("macro_f1", ">="),
    "max_nll": ("nll", "<="),
    "max_brier": ("brier", "<="),
    "max_ece": ("ece", "<="),
    "min_coverage": ("coverage", ">="),
    "max_abstention_rate": ("abstention_rate", "<="),
    "min_selective_accuracy": ("selective_accuracy", ">="),
    "max_error_rate": ("error_rate", "<="),
    "max_latency_p95_ms": ("latency_p95_ms", "<="),
    "max_ordinal_mae": ("ordinal_mae", "<="),
}
assert set(GATES) == set(Gates.model_fields)


Level = Literal["requirement", "warning"]


class Check(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: str
    level: Level
    metric: str
    comparison: Literal[">=", "<="]
    threshold: float
    value: float | None
    status: Status
    message: str


def make_check(
    gate: str,
    metric: str,
    comparison: Literal[">=", "<="],
    threshold: float,
    value: float | None,
    *,
    level: Level,
    missing: str = "no eligible cases",
    detail: str = "",
) -> Check:
    """A check that ``value comparison threshold`` holds. A missing value fails."""
    if value is None:
        holds = False
        message = f"{metric} could not be computed ({missing})"
    else:
        holds = value >= threshold if comparison == ">=" else value <= threshold
        message = f"{metric} {value:.4g} {comparison} {threshold:g}"
        if not holds:
            message = f"{metric} {value:.4g} violates {comparison} {threshold:g}"
    if detail:
        message += f" ({detail})"
    failed = Status.FAIL if level == "requirement" else Status.WARN
    return Check(
        gate=gate,
        level=level,
        metric=metric,
        comparison=comparison,
        threshold=threshold,
        value=value,
        status=Status.PASS if holds else failed,
        message=message,
    )


def _check(gate: str, threshold: float, level: Level, values: dict[str, float | None]) -> Check:
    metric, comparison = GATES[gate]
    return make_check(gate, metric, comparison, threshold, values[metric], level=level)


def overall_status(checks: list[Check]) -> Status:
    if any(c.status is Status.FAIL for c in checks):
        return Status.FAIL
    if any(c.status is Status.WARN for c in checks):
        return Status.WARN
    return Status.PASS


def evaluate_gates(
    requirements: Gates, warnings: Gates, metrics: Metrics
) -> tuple[list[Check], Status]:
    """Check every configured gate.

    ``max_error_rate`` defaults to 0 as a requirement: a case the backend could not decide is
    a failure unless the contract explicitly tolerates some. A gate whose metric cannot be
    computed (e.g. accuracy without labeled cases) fails, since it was not demonstrated.
    """
    values = metrics.gate_values()
    required = requirements.configured()
    required.setdefault("max_error_rate", 0.0)
    checks = [_check(gate, t, "requirement", values) for gate, t in required.items()]
    checks += [_check(gate, t, "warning", values) for gate, t in warnings.configured().items()]
    return checks, overall_status(checks)
