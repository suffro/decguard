"""Versioned report for offline post-deployment checks."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from decguard import __version__
from decguard._validation import format_validation_error
from decguard.contracts.loader import LoadedContract
from decguard.contracts.models import Evaluation
from decguard.contracts.production import Production, ProductionGates, SegmentGates
from decguard.decisions import DecisionSpec, DecisionType
from decguard.errors import DatasetError, ReportError
from decguard.production.metrics import ProductionMetrics, compute_production_metrics
from decguard.production.records import (
    ProductionDataset,
    ProductionRecord,
    SegmentValue,
    normalize_record,
    segment_value,
)
from decguard.reports.gates import Check, Level, Status, make_check, overall_status
from decguard.reports.model import ContractInfo

CHECK_VERSION: Final = "0.1"
EXIT_CODES = {Status.PASS: 0, Status.WARN: 0, Status.FAIL: 1}


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProductionDatasetInfo(_Section):
    path: str
    hash: str
    n_records: int
    n_outcomes: int
    n_correctness: int


class BaselineInfo(_Section):
    source: Literal["dataset", "report"]
    path: str
    hash: str
    n_records: int
    metrics: ProductionMetrics


class ProductionDrift(_Section):
    confidence_mean_delta: float | None
    confidence_tv_distance: float | None
    accuracy_drop: float | None
    ece_increase: float | None

    def gate_values(self) -> dict[str, float | None]:
        return {
            "confidence_tv_distance": self.confidence_tv_distance,
            "accuracy_drop": self.accuracy_drop,
            "ece_increase": self.ece_increase,
        }


class SegmentReport(_Section):
    key: str
    value: SegmentValue
    metrics: ProductionMetrics
    checks: list[Check]
    status: Status


PRODUCTION_GATES: dict[str, tuple[str, Literal[">=", "<="]]] = {
    "min_accuracy": ("accuracy", ">="),
    "max_error_rate": ("error_rate", "<="),
    "max_ece": ("ece", "<="),
    "max_brier": ("brier", "<="),
    "max_nll": ("nll", "<="),
    "min_threshold_coverage": ("threshold_coverage", ">="),
    "max_abstention_rate": ("abstention_rate", "<="),
    "max_fallback_rate": ("fallback_rate", "<="),
    "max_confidence_tv_distance": ("confidence_tv_distance", "<="),
    "max_accuracy_drop": ("accuracy_drop", "<="),
    "max_ece_increase": ("ece_increase", "<="),
}
assert set(PRODUCTION_GATES) == set(ProductionGates.model_fields)
assert set(SegmentGates.model_fields) < set(PRODUCTION_GATES)


def compute_drift(
    current: ProductionMetrics, baseline: ProductionMetrics | None
) -> ProductionDrift:
    if baseline is None:
        return ProductionDrift(
            confidence_mean_delta=None,
            confidence_tv_distance=None,
            accuracy_drop=None,
            ece_increase=None,
        )
    current_mean = current.confidence.mean
    baseline_mean = baseline.confidence.mean
    left = current.confidence.histogram
    right = baseline.confidence.histogram
    if len(left) != len(right):
        raise ReportError("baseline and current confidence histograms use different bin counts")
    left_total = sum(left)
    right_total = sum(right)
    tv = None
    if left_total and right_total:
        tv = 0.5 * math.fsum(
            abs(a / left_total - b / right_total) for a, b in zip(left, right, strict=True)
        )
    current_accuracy = current.outcomes.accuracy
    baseline_accuracy = baseline.outcomes.accuracy
    current_ece = current.calibration.ece
    baseline_ece = baseline.calibration.ece
    return ProductionDrift(
        confidence_mean_delta=(
            None if current_mean is None or baseline_mean is None else current_mean - baseline_mean
        ),
        confidence_tv_distance=tv,
        accuracy_drop=(
            None
            if current_accuracy is None or baseline_accuracy is None
            else baseline_accuracy - current_accuracy
        ),
        ece_increase=(
            None if current_ece is None or baseline_ece is None else current_ece - baseline_ece
        ),
    )


def _evaluate_section(
    settings: ProductionGates | SegmentGates,
    metrics: ProductionMetrics,
    drift: ProductionDrift,
    *,
    level: Level,
    prefix: str = "",
) -> list[Check]:
    values = {**metrics.gate_values(), **drift.gate_values()}
    checks = []
    for gate, threshold in settings.configured().items():
        metric, comparison = PRODUCTION_GATES[gate]
        missing = (
            "no baseline was provided or the metric is unavailable"
            if metric in drift.gate_values()
            else "no eligible production records"
        )
        checks.append(
            make_check(
                prefix + gate,
                prefix + metric,
                comparison,
                threshold,
                values[metric],
                level=level,
                missing=missing,
            )
        )
    return checks


def evaluate_production_gates(
    config: Production, metrics: ProductionMetrics, drift: ProductionDrift
) -> list[Check]:
    return _evaluate_section(config.requirements, metrics, drift, level="requirement") + (
        _evaluate_section(config.warnings, metrics, drift, level="warning")
    )


def build_segments(
    records: Sequence[ProductionRecord], config: Production, evaluation: Evaluation
) -> list[SegmentReport]:
    reports = []
    no_drift = compute_drift(compute_production_metrics(records, evaluation), None)
    for key in config.segments:
        groups: dict[tuple[str, str], list[ProductionRecord]] = defaultdict(list)
        values: dict[tuple[str, str], SegmentValue] = {}
        for record in records:
            value = segment_value(record, key)
            identity = (type(value).__name__, repr(value))
            values[identity] = value
            groups[identity].append(record)
        for identity, members in sorted(groups.items()):
            value = values[identity]
            metrics = compute_production_metrics(members, evaluation)
            shown = "<missing>" if value is None else str(value)
            prefix = f"segment[{key}={shown}]."
            checks = _evaluate_section(
                config.segment_requirements,
                metrics,
                no_drift,
                level="requirement",
                prefix=prefix,
            ) + _evaluate_section(
                config.segment_warnings,
                metrics,
                no_drift,
                level="warning",
                prefix=prefix,
            )
            reports.append(
                SegmentReport(
                    key=key,
                    value=value,
                    metrics=metrics,
                    checks=checks,
                    status=overall_status(checks),
                )
            )
    return reports


class ProductionReport(_Section):
    check_version: Literal["0.1"] = CHECK_VERSION
    decguard_version: str
    created_at: str
    status: Status
    exit_code: int
    contract: ContractInfo
    evaluation: Evaluation
    config: Production
    dataset: ProductionDatasetInfo
    baseline: BaselineInfo | None = None
    metrics: ProductionMetrics
    drift: ProductionDrift
    segments: list[SegmentReport]
    checks: list[Check]
    records: list[ProductionRecord]

    @model_validator(mode="after")
    def _check_integrity(self) -> ProductionReport:
        spec = DecisionSpec(
            name=self.contract.name,
            type=DecisionType(self.contract.type),
            labels=self.contract.labels,
        )
        normalized = []
        seen = set()
        if not self.records:
            raise ValueError("production report contains no records")
        for record in self.records:
            if record.id in seen:
                raise ValueError(f"duplicate production record id {record.id!r}")
            seen.add(record.id)
            try:
                checked = normalize_record(
                    record,
                    spec,
                    tolerance=self.evaluation.probability_tolerance,
                    source=f"records[{record.id}]",
                )
            except DatasetError as exc:
                raise ValueError(str(exc)) from exc
            if checked != record:
                raise ValueError(f"record {record.id!r} is not canonically normalized")
            normalized.append(record)
        expected_info = (
            len(normalized),
            sum(record.outcome is not None for record in normalized),
            sum(record.outcome_correct is not None for record in normalized),
        )
        if expected_info != (
            self.dataset.n_records,
            self.dataset.n_outcomes,
            self.dataset.n_correctness,
        ):
            raise ValueError("dataset counts do not match stored production records")
        metrics = compute_production_metrics(normalized, self.evaluation)
        if metrics != self.metrics:
            raise ValueError("metrics do not match stored production records")
        if self.baseline is not None and (
            self.baseline.n_records <= 0
            or self.baseline.n_records != self.baseline.metrics.counts.total
        ):
            raise ValueError("baseline record count does not match baseline metrics")
        drift = compute_drift(metrics, self.baseline.metrics if self.baseline else None)
        if drift != self.drift:
            raise ValueError("drift does not match current and baseline metrics")
        segments = build_segments(normalized, self.config, self.evaluation)
        if segments != self.segments:
            raise ValueError("segments do not match stored production records")
        checks = evaluate_production_gates(self.config, metrics, drift)
        checks += [check for segment in segments for check in segment.checks]
        if checks != self.checks:
            raise ValueError("checks do not match metrics and production configuration")
        status = overall_status(checks)
        if self.status is not status or self.exit_code != EXIT_CODES[status]:
            raise ValueError("status/exit_code do not match stored checks")
        return self


def build_production_report(
    loaded: LoadedContract,
    dataset: ProductionDataset,
    *,
    baseline: BaselineInfo | None = None,
) -> ProductionReport:
    contract = loaded.contract
    metrics = compute_production_metrics(dataset.records, contract.evaluation)
    drift = compute_drift(metrics, baseline.metrics if baseline else None)
    segments = build_segments(dataset.records, contract.production, contract.evaluation)
    checks = evaluate_production_gates(contract.production, metrics, drift)
    checks += [check for segment in segments for check in segment.checks]
    status = overall_status(checks)
    spec = contract.spec()
    return ProductionReport(
        decguard_version=__version__,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        status=status,
        exit_code=EXIT_CODES[status],
        contract=ContractInfo(
            name=spec.name,
            type=spec.type,
            labels=spec.labels,
            schema_version=contract.schema_version,
            hash=loaded.hash,
            path=str(loaded.path),
        ),
        evaluation=contract.evaluation,
        config=contract.production,
        dataset=ProductionDatasetInfo(
            path=str(dataset.path),
            hash=dataset.hash,
            n_records=len(dataset.records),
            n_outcomes=dataset.n_outcomes,
            n_correctness=dataset.n_correctness,
        ),
        baseline=baseline,
        metrics=metrics,
        drift=drift,
        segments=segments,
        checks=checks,
        records=list(dataset.records),
    )


def write_production_report(report: ProductionReport, path: str | Path) -> None:
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"{path}: cannot write production report: {exc.strerror or exc}") from exc


def load_production_report(path: str | Path) -> ProductionReport:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReportError(f"{path}: cannot read production report: {exc.strerror or exc}") from exc
    try:
        return ProductionReport.model_validate_json(raw)
    except ValidationError as exc:
        raise ReportError(
            f"{path}: not a DecGuard production report {CHECK_VERSION}:\n"
            + format_validation_error(exc)
        ) from exc


def report_file_hash(path: str | Path) -> str:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ReportError(f"{path}: cannot read baseline report: {exc.strerror or exc}") from exc
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def looks_like_production_report(path: str | Path) -> bool:
    path = Path(path)
    if path.suffix.lower() != ".json":
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return isinstance(value, dict) and "check_version" in value
