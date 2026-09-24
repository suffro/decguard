"""The canonical reliability report: gates, JSON model, terminal rendering."""

from decguard.reports.gates import GATES, Check, Status, evaluate_gates
from decguard.reports.model import (
    EXIT_CODES,
    REPORT_VERSION,
    ContractInfo,
    DatasetInfo,
    Failure,
    Report,
    build_report,
    load_report,
    reevaluate,
    write_report,
)
from decguard.reports.render import render_text

__all__ = [
    "EXIT_CODES",
    "GATES",
    "REPORT_VERSION",
    "Check",
    "ContractInfo",
    "DatasetInfo",
    "Failure",
    "Report",
    "Status",
    "build_report",
    "evaluate_gates",
    "load_report",
    "reevaluate",
    "render_text",
    "write_report",
]
