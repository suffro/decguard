"""The canonical reliability report (JSON) and its construction."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from decguard import __version__
from decguard._validation import format_validation_error
from decguard.backends.base import BackendMetadata, HealthStatus
from decguard.contracts.loader import LoadedContract
from decguard.contracts.models import Evaluation, Gates
from decguard.decisions import (
    DEFAULT_PROBABILITY_TOLERANCE,
    TOLERANCE_CONTEXT_KEY,
    DecisionInput,
    DecisionResult,
    DecisionSpec,
    DecisionType,
)
from decguard.errors import ReportError
from decguard.metrics import Metrics, compute_metrics
from decguard.reports.gates import Check, Status, evaluate_gates, overall_status
from decguard.reports.properties import (
    PropertyRun,
    property_checks,
    rejudge,
    summarize,
    verify_run,
)
from decguard.runner import CaseRecord

REPORT_VERSION: Final = "0.1"

EXIT_CODES = {Status.PASS: 0, Status.WARN: 0, Status.FAIL: 1}


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ContractInfo(_Section):
    name: str
    type: DecisionType
    labels: tuple[str, ...]
    schema_version: str
    hash: str
    path: str


class DatasetInfo(_Section):
    path: str
    hash: str
    n_cases: int
    n_labeled: int


class Failure(_Section):
    """A reproducible failing example: the input plus what went wrong."""

    case_id: str
    kind: Literal["error", "mismatch"]
    input: DecisionInput
    expected: str | None = None
    selected: str | None = None
    confidence: float | None = None
    error: str | None = None


Mode = Literal["test", "fuzz", "all"]
"""``test``: golden gates; ``fuzz``: property checks; ``all``: both."""


class Report(_Section):
    report_version: Literal["0.1"] = REPORT_VERSION
    decguard_version: str
    created_at: str
    mode: Mode = "test"
    status: Status
    exit_code: int
    """0 for pass/warn, 1 for fail (``--fail-on-warn`` makes the CLI exit 1 on warn too)."""
    contract: ContractInfo
    dataset: DatasetInfo
    backend: BackendMetadata
    health: HealthStatus | None = None
    evaluation: Evaluation
    requirements: Gates
    warnings: Gates
    metrics: Metrics
    checks: list[Check]
    failures: list[Failure]
    results: list[CaseRecord]
    properties: PropertyRun | None = None
    """Metamorphic property results (modes ``fuzz`` and ``all``)."""

    @model_validator(mode="after")
    def _check_integrity(self) -> Report:
        if (self.mode == "test") != (self.properties is None):
            raise ValueError("'properties' must be present exactly in 'fuzz' and 'all' reports")

        try:
            spec = DecisionSpec(
                name=self.contract.name,
                type=self.contract.type,
                labels=self.contract.labels,
            )
        except ValidationError as exc:
            raise ValueError("report contract decision is invalid") from exc
        if not self.results:
            raise ValueError("report contains no case results")
        records: dict[str, CaseRecord] = {}
        for record in self.results:
            if record.case_id in records:
                raise ValueError(f"duplicate case id {record.case_id!r}")
            records[record.case_id] = record
            if record.expected is not None and record.expected not in spec.labels:
                raise ValueError(
                    f"case {record.case_id!r}: expected {record.expected!r} is not a report label"
                )
            if record.result is not None:
                self._check_result_context(record.result, expected_case_id=record.case_id)

        if (self.dataset.n_cases, self.dataset.n_labeled) != (
            len(self.results),
            sum(record.expected is not None for record in self.results),
        ):
            raise ValueError("dataset counts do not match stored case results")

        metrics = compute_metrics(spec, self.results, self.evaluation)
        if metrics != self.metrics:
            raise ValueError("metrics do not match stored case results")
        if collect_failures(self.results) != self.failures:
            raise ValueError("failures do not match stored case results")

        properties = self.properties
        if self.properties is not None:
            verify_run(self.properties, records)
            for pair in self.properties.pairs:
                if pair.result is not None:
                    self._check_result_context(pair.result, expected_case_id=pair.id)
                if pair.reduced is not None:
                    self._check_result_context(pair.reduced.result, expected_case_id=pair.id)
            summary_names = [summary.property for summary in self.properties.summaries]
            if len(summary_names) != len(set(summary_names)):
                raise ValueError("property summaries contain duplicate properties")
            enabled = self.properties.config.configured()
            if any(name not in enabled for name in summary_names):
                raise ValueError("property summaries contain a property not in configuration")
            summaries = tuple(
                summarize(
                    name,
                    enabled[name],
                    self.properties.pairs,
                    self.properties.skipped,
                    len(self.results),
                )
                for name in summary_names
            )
            if summaries != self.properties.summaries:
                raise ValueError("property summaries do not match stored transformed cases")

        checks: list[Check] = []
        if self.mode in ("test", "all"):
            checks, _ = evaluate_gates(self.requirements, self.warnings, metrics)
        if properties is not None:
            checks += property_checks(properties, properties.config)
        if checks != self.checks:
            raise ValueError("checks do not match stored metrics and configuration")
        status = overall_status(checks)
        if self.status is not status or self.exit_code != EXIT_CODES[status]:
            raise ValueError("status/exit_code do not match stored checks")
        return self

    def _check_result_context(self, result: DecisionResult, *, expected_case_id: str) -> None:
        expected = (
            expected_case_id,
            self.contract.name,
            self.contract.type,
            self.contract.labels,
            self.backend.name,
            self.backend.provider,
        )
        actual = (
            result.case_id,
            result.decision,
            result.decision_type,
            result.labels,
            result.backend,
            result.provider,
        )
        if actual != expected:
            raise ValueError(
                f"result {result.case_id!r} does not match the report decision/backend context"
            )

    def records_by_id(self) -> dict[str, CaseRecord]:
        return {record.case_id: record for record in self.results}


def collect_failures(records: Sequence[CaseRecord]) -> list[Failure]:
    failures = []
    for record in records:
        if record.error is not None:
            failures.append(
                Failure(
                    case_id=record.case_id,
                    kind="error",
                    input=record.input,
                    expected=record.expected,
                    error=f"{record.error.kind}: {record.error.message}",
                )
            )
        elif (
            record.result is not None
            and record.expected is not None
            and record.result.selected != record.expected
        ):
            failures.append(
                Failure(
                    case_id=record.case_id,
                    kind="mismatch",
                    input=record.input,
                    expected=record.expected,
                    selected=record.result.selected,
                    confidence=record.result.confidence,
                )
            )
    return failures


def build_report(
    loaded: LoadedContract,
    dataset: DatasetInfo,
    backend: BackendMetadata,
    records: Sequence[CaseRecord],
    *,
    health: HealthStatus | None = None,
    mode: Mode = "test",
    properties: PropertyRun | None = None,
) -> Report:
    """Evaluate records against a contract. A pure function of its inputs (bar the timestamp)."""
    contract = loaded.contract
    spec = contract.spec()
    metrics = compute_metrics(spec, records, contract.evaluation)
    checks: list[Check] = []
    if mode in ("test", "all"):
        checks, _ = evaluate_gates(contract.requirements, contract.warnings, metrics)
    if properties is not None:
        checks += property_checks(properties, properties.config)
    status = overall_status(checks)
    return Report(
        decguard_version=__version__,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        mode=mode,
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
        dataset=dataset,
        backend=backend,
        health=health,
        evaluation=contract.evaluation,
        requirements=contract.requirements,
        warnings=contract.warnings,
        metrics=metrics,
        checks=checks,
        failures=collect_failures(records),
        results=list(records),
        properties=properties,
    )


def ensure_same_decision(report: Report, loaded: LoadedContract) -> None:
    spec = loaded.contract.spec()
    if (spec.name, spec.type, spec.labels) != (
        report.contract.name,
        report.contract.type,
        report.contract.labels,
    ):
        raise ReportError(
            f"contract {loaded.path} describes {spec.name!r} ({spec.type}, {list(spec.labels)}) "
            f"but the report is for {report.contract.name!r} ({report.contract.type}, "
            f"{list(report.contract.labels)})"
        )


def reevaluate(report: Report, loaded: LoadedContract) -> Report:
    """Re-apply a (possibly edited) contract's gates to a stored report's results.

    Property tolerances and levels are re-applied to the stored transformed cases;
    transformations are not regenerated."""
    ensure_same_decision(report, loaded)
    properties = report.properties
    if properties is not None:
        properties = rejudge(properties, loaded.contract.properties, report.records_by_id())
    return build_report(
        loaded,
        report.dataset,
        report.backend,
        report.results,
        health=report.health,
        mode=report.mode,
        properties=properties,
    )


def write_report(report: Report, path: str | Path) -> None:
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"{path}: cannot write report: {exc.strerror or exc}") from exc


def _stored_tolerance(text: str) -> float:
    """The probability tolerance the report was produced with, used to re-check results.

    Falls back to the default when absent or malformed; ``Evaluation`` validation then
    reports the malformed value itself.
    """
    try:
        value = json.loads(text)["evaluation"]["probability_tolerance"]
    except (ValueError, TypeError, KeyError):
        return DEFAULT_PROBABILITY_TOLERANCE
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value <= 0.1:
        return DEFAULT_PROBABILITY_TOLERANCE
    return float(value)


def load_report(path: str | Path) -> Report:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReportError(f"{path}: cannot read report: {exc}") from exc
    try:
        return Report.model_validate_json(
            text, context={TOLERANCE_CONTEXT_KEY: _stored_tolerance(text)}
        )
    except ValidationError as exc:
        raise ReportError(
            f"{path}: not a DecGuard {REPORT_VERSION} report:\n" + format_validation_error(exc)
        ) from exc
