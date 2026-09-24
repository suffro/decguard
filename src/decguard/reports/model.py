"""The canonical reliability report (JSON) and its construction."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from decguard import __version__
from decguard._validation import format_validation_error
from decguard.backends.base import BackendMetadata, HealthStatus
from decguard.contracts.loader import LoadedContract
from decguard.contracts.models import Evaluation
from decguard.decisions import DecisionInput, DecisionType
from decguard.errors import ReportError
from decguard.metrics import Metrics, compute_metrics
from decguard.reports.gates import Check, Status, evaluate_gates
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


class Report(_Section):
    report_version: Literal["0.1"] = REPORT_VERSION
    decguard_version: str
    created_at: str
    status: Status
    exit_code: int
    """0 for pass/warn, 1 for fail (``--fail-on-warn`` makes the CLI exit 1 on warn too)."""
    contract: ContractInfo
    dataset: DatasetInfo
    backend: BackendMetadata
    health: HealthStatus | None = None
    evaluation: Evaluation
    metrics: Metrics
    checks: list[Check]
    failures: list[Failure]
    results: list[CaseRecord]


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
) -> Report:
    """Evaluate records against a contract. A pure function of its inputs (bar the timestamp)."""
    contract = loaded.contract
    spec = contract.spec()
    metrics = compute_metrics(spec, records, contract.evaluation)
    checks, status = evaluate_gates(contract.requirements, contract.warnings, metrics)
    return Report(
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
        dataset=dataset,
        backend=backend,
        health=health,
        evaluation=contract.evaluation,
        metrics=metrics,
        checks=checks,
        failures=collect_failures(records),
        results=list(records),
    )


def reevaluate(report: Report, loaded: LoadedContract) -> Report:
    """Re-apply a (possibly edited) contract's gates to a stored report's results."""
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
    return build_report(
        loaded, report.dataset, report.backend, report.results, health=report.health
    )


def write_report(report: Report, path: str | Path) -> None:
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"{path}: cannot write report: {exc.strerror or exc}") from exc


def load_report(path: str | Path) -> Report:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReportError(f"{path}: cannot read report: {exc}") from exc
    try:
        return Report.model_validate_json(text)
    except ValidationError as exc:
        raise ReportError(
            f"{path}: not a DecGuard {REPORT_VERSION} report:\n" + format_validation_error(exc)
        ) from exc
