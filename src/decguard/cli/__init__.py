"""Command-line interface.

Exit codes: 0 = PASS (or WARN), 1 = a reliability gate failed, 2 = configuration or runtime
error (including invalid command-line usage).
"""

from __future__ import annotations

import os
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from decguard import __version__
from decguard.backends.registry import create_backend
from decguard.contracts.loader import load_contract
from decguard.engine import resolve_dataset, run_test
from decguard.errors import DecGuardError
from decguard.reports.gates import Status
from decguard.reports.model import Report, load_report, reevaluate, write_report
from decguard.reports.render import render_text

EXIT_PASS = 0
EXIT_GATE_FAILED = 1
EXIT_ERROR = 2

app = typer.Typer(
    name="decguard",
    help=(
        "Test, verify and gate probabilistic AI decision models.\n\n"
        "Exit codes: 0 = pass (or warn), 1 = reliability gate failed, "
        "2 = configuration/runtime error."
    ),
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
)


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


@contextmanager
def _handle_errors() -> Iterator[None]:
    """Map every error to exit code 2 so it can never be mistaken for a failed gate (1)."""
    try:
        yield
    except DecGuardError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc
    except (typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        if os.environ.get("DECGUARD_DEBUG"):
            traceback.print_exc()
        typer.echo(
            f"internal error: {type(exc).__name__}: {exc} (set DECGUARD_DEBUG=1 for a traceback)",
            err=True,
        )
        raise typer.Exit(EXIT_ERROR) from exc


def _emit(report: Report, fmt: OutputFormat, output: Path | None, fail_on_warn: bool) -> None:
    if output is not None:
        write_report(report, output)
        typer.echo(f"report written to {output}", err=True)
    if fmt is OutputFormat.JSON:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(render_text(report))
    if report.status is Status.FAIL or (fail_on_warn and report.status is Status.WARN):
        raise typer.Exit(EXIT_GATE_FAILED)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"decguard {__version__}")
        raise typer.Exit(EXIT_PASS)


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    pass


ContractArg = Annotated[
    Path, typer.Argument(help="Decision contract (.yaml, .yml or .json).", show_default=False)
]
DatasetOpt = Annotated[
    Path | None,
    typer.Option(
        "--dataset", "-d", help="Golden dataset (.jsonl/.json); overrides the contract's dataset."
    ),
]
FormatOpt = Annotated[
    OutputFormat, typer.Option("--format", "-f", help="Report format written to stdout.")
]
OutputOpt = Annotated[
    Path | None, typer.Option("--output", "-o", help="Also write the JSON report to this file.")
]
FailOnWarnOpt = Annotated[
    bool, typer.Option("--fail-on-warn", help="Exit 1 when warning gates are violated.")
]


@app.command()
def validate(contract: ContractArg, dataset: DatasetOpt = None) -> None:
    """Check a contract, its backend settings and its dataset (offline)."""
    with _handle_errors():
        loaded = load_contract(contract)
        c = loaded.contract
        spec = c.spec()
        for name in c.backend_names():
            create_backend(c.backend_config(name), decision=spec, name=name).close()
        lines = [
            f"OK  {contract}",
            f"    decision  {spec.name} ({spec.type}): {', '.join(spec.labels)}",
            "    backends  "
            + ", ".join(f"{name}={c.backend_config(name).provider}" for name in c.backend_names()),
        ]
        if dataset is not None or c.dataset is not None:
            data = resolve_dataset(loaded, dataset)
            lines.append(
                f"    dataset   {data.path}: {len(data.cases)} cases, {data.n_labeled} labeled"
            )
        else:
            lines.append("    dataset   none (pass --dataset to `decguard test`)")
        lines += [
            f"    gates     requirements: {len(c.requirements.configured())}, "
            f"warnings: {len(c.warnings.configured())}",
            f"    hash      {loaded.hash}",
        ]
        typer.echo("\n".join(lines))


@app.command("test")
def cmd_test(
    contract: ContractArg,
    dataset: DatasetOpt = None,
    backend: Annotated[
        str | None,
        typer.Option(
            "--backend", "-b", help="Named backend from the contract's 'backends' section."
        ),
    ] = None,
    output: OutputOpt = None,
    fmt: FormatOpt = OutputFormat.TEXT,
    max_concurrency: Annotated[
        int | None,
        typer.Option(
            "--max-concurrency",
            min=1,
            max=256,
            help="Parallel backend calls (default: evaluation.max_concurrency).",
        ),
    ] = None,
    fail_on_warn: FailOnWarnOpt = False,
    healthcheck: Annotated[
        bool,
        typer.Option("--healthcheck/--no-healthcheck", help="Check backend health before running."),
    ] = True,
) -> None:
    """Run the golden dataset through a backend and check the contract's gates."""
    with _handle_errors():
        report = run_test(
            contract,
            dataset=dataset,
            backend=backend,
            max_concurrency=max_concurrency,
            check_health=healthcheck,
        )
        _emit(report, fmt, output, fail_on_warn)


@app.command()
def report(
    results: Annotated[
        Path, typer.Argument(help="JSON report written by `decguard test --output`.")
    ],
    contract: Annotated[
        Path | None,
        typer.Option(
            "--contract",
            "-c",
            help="Re-evaluate the stored results against this contract's gates.",
        ),
    ] = None,
    output: OutputOpt = None,
    fmt: FormatOpt = OutputFormat.TEXT,
    fail_on_warn: FailOnWarnOpt = False,
) -> None:
    """Show a stored report; exits with the report's gate status."""
    with _handle_errors():
        stored = load_report(results)
        if contract is not None:
            stored = reevaluate(stored, load_contract(contract))
        _emit(stored, fmt, output, fail_on_warn)


def main() -> None:
    app(prog_name="decguard")
