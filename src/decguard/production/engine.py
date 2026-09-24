"""Orchestration for ``decguard check`` and the Python API."""

from __future__ import annotations

from pathlib import Path

from decguard.contracts.loader import LoadedContract, load_contract
from decguard.errors import ReportError
from decguard.production.metrics import compute_production_metrics
from decguard.production.records import load_production_dataset, normalize_record
from decguard.production.report import (
    BaselineInfo,
    ProductionReport,
    build_production_report,
    load_production_report,
    looks_like_production_report,
    report_file_hash,
)


def _baseline_info(loaded: LoadedContract, path: str | Path) -> BaselineInfo:
    contract = loaded.contract
    path = Path(path)
    if looks_like_production_report(path):
        report = load_production_report(path)
        spec = contract.spec()
        if (report.contract.name, report.contract.type, report.contract.labels) != (
            spec.name,
            spec.type,
            spec.labels,
        ):
            raise ReportError(
                f"baseline report {path} is for {report.contract.name!r} "
                f"({report.contract.type}, {list(report.contract.labels)}), not "
                f"{spec.name!r} ({spec.type}, {list(spec.labels)})"
            )
        records = [
            normalize_record(
                record,
                spec,
                tolerance=contract.evaluation.probability_tolerance,
                source=f"{path}: records[{record.id}]",
            )
            for record in report.records
        ]
        return BaselineInfo(
            source="report",
            path=str(path),
            hash=report_file_hash(path),
            n_records=len(records),
            metrics=compute_production_metrics(records, contract.evaluation),
        )
    dataset = load_production_dataset(
        path,
        contract.spec(),
        tolerance=contract.evaluation.probability_tolerance,
    )
    return BaselineInfo(
        source="dataset",
        path=str(path),
        hash=dataset.hash,
        n_records=len(dataset.records),
        metrics=compute_production_metrics(dataset.records, contract.evaluation),
    )


def run_check(
    contract: LoadedContract | str | Path,
    *,
    dataset: str | Path,
    baseline: str | Path | None = None,
) -> ProductionReport:
    """Analyze production records without calling a backend or external service."""
    loaded = contract if isinstance(contract, LoadedContract) else load_contract(contract)
    data = load_production_dataset(
        dataset,
        loaded.contract.spec(),
        tolerance=loaded.contract.evaluation.probability_tolerance,
    )
    base = _baseline_info(loaded, baseline) if baseline is not None else None
    return build_production_report(loaded, data, baseline=base)
