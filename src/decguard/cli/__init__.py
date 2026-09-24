"""Command-line interface.

Exit codes: 0 = PASS (or WARN), 1 = a reliability gate failed, 2 = configuration or runtime
error (including invalid command-line usage).
"""

from __future__ import annotations

import json
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
from decguard.fuzz.paraphrase import create_paraphraser
from decguard.fuzz.replay import render_replay_text
from decguard.fuzz.replay import replay as replay_failures
from decguard.production.engine import run_check
from decguard.production.render import render_production_text
from decguard.production.report import ProductionReport, write_production_report
from decguard.regression.diff import load_and_diff, render_diff_text, write_diff
from decguard.reports.gates import Status
from decguard.reports.model import Report, load_report, reevaluate, write_report
from decguard.reports.render import render_text
from decguard.sdk import DecGuard

EXIT_PASS = 0
EXIT_GATE_FAILED = 1
EXIT_ERROR = 2

app = typer.Typer(
    name="decguard",
    help=(
        "Test, verify and gate probabilistic AI decision models.\n\n"
        "validate a contract, test it on a golden dataset, fuzz its metamorphic properties, "
        "diff two runs for regressions, replay stored failures, check collected production "
        "records, and apply explicit runtime policies.\n\n"
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
        paraphrase = c.properties.paraphrase
        if paraphrase is not None and paraphrase.enabled:
            create_paraphraser(paraphrase.source, base_dir=loaded.path.parent).close()
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
            "    properties "
            + (", ".join(c.properties.configured()) or "none (add 'properties' to fuzz)"),
            "    production "
            f"segments: {', '.join(c.production.segments) or 'none'}; "
            f"requirements: {len(c.production.requirements.configured())}; "
            f"segment requirements: {len(c.production.segment_requirements.configured())}",
            "    policy     "
            + (f"{len(c.policy.routes)} routes" if c.policy is not None else "none"),
            f"    hash      {loaded.hash}",
        ]
        typer.echo("\n".join(lines))


BackendOpt = Annotated[
    str | None,
    typer.Option("--backend", "-b", help="Named backend from the contract's 'backends' section."),
]
MaxConcurrencyOpt = Annotated[
    int | None,
    typer.Option(
        "--max-concurrency",
        min=1,
        max=256,
        help="Parallel backend calls (default: evaluation.max_concurrency).",
    ),
]
HealthcheckOpt = Annotated[
    bool,
    typer.Option("--healthcheck/--no-healthcheck", help="Check backend health before running."),
]
SeedOpt = Annotated[
    int | None,
    typer.Option("--seed", min=0, help="Transformation seed (default: fuzz.seed, else 0)."),
]
PropertyOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--property", "-p", help="Run only this property (repeatable). Default: all enabled."
    ),
]
MinimizeOpt = Annotated[
    bool | None,
    typer.Option(
        "--minimize/--no-minimize",
        help="Shrink failing transformations (default: fuzz.minimize).",
        show_default=False,
    ),
]


@app.command("test")
def cmd_test(
    contract: ContractArg,
    dataset: DatasetOpt = None,
    backend: BackendOpt = None,
    output: OutputOpt = None,
    fmt: FormatOpt = OutputFormat.TEXT,
    max_concurrency: MaxConcurrencyOpt = None,
    fail_on_warn: FailOnWarnOpt = False,
    healthcheck: HealthcheckOpt = True,
    all_checks: Annotated[
        bool,
        typer.Option("--all", help="Also check the contract's metamorphic properties (fuzz)."),
    ] = False,
    seed: SeedOpt = None,
    properties: PropertyOpt = None,
    minimize: MinimizeOpt = None,
) -> None:
    """Run the golden dataset through a backend and check the contract's gates."""
    with _handle_errors():
        report = run_test(
            contract,
            dataset=dataset,
            backend=backend,
            max_concurrency=max_concurrency,
            check_health=healthcheck,
            mode="all" if all_checks else "test",
            seed=seed,
            properties=properties,
            minimize=minimize,
        )
        _emit(report, fmt, output, fail_on_warn)


@app.command()
def fuzz(
    contract: ContractArg,
    dataset: DatasetOpt = None,
    backend: BackendOpt = None,
    seed: SeedOpt = None,
    properties: PropertyOpt = None,
    minimize: MinimizeOpt = None,
    output: OutputOpt = None,
    fmt: FormatOpt = OutputFormat.TEXT,
    max_concurrency: MaxConcurrencyOpt = None,
    fail_on_warn: FailOnWarnOpt = False,
    healthcheck: HealthcheckOpt = True,
) -> None:
    """Check the contract's metamorphic properties: transform each case in controlled
    ways (option order, formatting, irrelevant context, paraphrase, ...) and compare the
    decision distributions before and after. Deterministic for a given seed."""
    with _handle_errors():
        report = run_test(
            contract,
            dataset=dataset,
            backend=backend,
            max_concurrency=max_concurrency,
            check_health=healthcheck,
            mode="fuzz",
            seed=seed,
            properties=properties,
            minimize=minimize,
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


@app.command()
def diff(
    baseline: Annotated[
        Path, typer.Argument(help="Baseline JSON report (e.g. the current model).")
    ],
    candidate: Annotated[Path, typer.Argument(help="Candidate JSON report (e.g. a new model).")],
    contract: Annotated[
        Path | None,
        typer.Option(
            "--contract", "-c", help="Apply this contract's 'regression' gates and evaluation."
        ),
    ] = None,
    segment_by: Annotated[
        list[str] | None,
        typer.Option("--segment-by", "-s", help="Case metadata key to segment by (repeatable)."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Also write the JSON diff to this file.")
    ] = None,
    fmt: FormatOpt = OutputFormat.TEXT,
    fail_on_warn: FailOnWarnOpt = False,
) -> None:
    """Compare two reports of the same decision: answer flips, confidence and distribution
    shifts, calibration/accuracy/latency changes, new errors, per-segment changes. Exits 1
    when a regression gate is violated (new errors always count)."""
    with _handle_errors():
        result = load_and_diff(baseline, candidate, contract=contract, segment_by=segment_by)
        if output is not None:
            write_diff(result, output)
            typer.echo(f"diff written to {output}", err=True)
        if fmt is OutputFormat.JSON:
            typer.echo(result.model_dump_json(indent=2))
        else:
            typer.echo(render_diff_text(result))
        if result.status is Status.FAIL or (fail_on_warn and result.status is Status.WARN):
            raise typer.Exit(EXIT_GATE_FAILED)


@app.command()
def replay(
    results: Annotated[
        Path, typer.Argument(help="JSON report written by `decguard fuzz --output`.")
    ],
    ids: Annotated[
        list[str] | None,
        typer.Option(
            "--id",
            help="Transformed case to replay, as '<property>/<case id>/<sample>' "
            "(repeatable). Default: every failure in the report.",
        ),
    ] = None,
    contract: Annotated[
        Path | None,
        typer.Option("--contract", "-c", help="Contract to use (default: the report's)."),
    ] = None,
    backend: BackendOpt = None,
    fmt: FormatOpt = OutputFormat.TEXT,
) -> None:
    """Re-send stored property failures to the backend and check whether they still fail.
    Exits 1 when a failure reproduces, 0 when none does."""
    with _handle_errors():
        result = replay_failures(results, ids=ids, contract=contract, backend=backend)
        if fmt is OutputFormat.JSON:
            typer.echo(result.model_dump_json(indent=2))
        else:
            typer.echo(render_replay_text(result))
        if result.status is Status.FAIL:
            raise typer.Exit(EXIT_GATE_FAILED)


def _emit_production(
    report: ProductionReport,
    fmt: OutputFormat,
    output: Path | None,
    fail_on_warn: bool,
) -> None:
    if output is not None:
        write_production_report(report, output)
        typer.echo(f"production report written to {output}", err=True)
    if fmt is OutputFormat.JSON:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(render_production_text(report))
    if report.status is Status.FAIL or (fail_on_warn and report.status is Status.WARN):
        raise typer.Exit(EXIT_GATE_FAILED)


@app.command()
def check(
    contract: ContractArg,
    dataset: Annotated[
        Path,
        typer.Option(
            "--dataset",
            "-d",
            help="Collected production records (.jsonl/.json).",
            show_default=False,
        ),
    ],
    baseline: Annotated[
        Path | None,
        typer.Option(
            "--baseline",
            help="Baseline production dataset or a previous `decguard check` JSON report.",
        ),
    ] = None,
    output: OutputOpt = None,
    fmt: FormatOpt = OutputFormat.TEXT,
    fail_on_warn: FailOnWarnOpt = False,
) -> None:
    """Analyze collected production decisions offline and apply post-deployment gates."""
    with _handle_errors():
        result = run_check(contract, dataset=dataset, baseline=baseline)
        _emit_production(result, fmt, output, fail_on_warn)


@app.command("run")
def run_policy(
    contract: ContractArg,
    input_value: Annotated[
        str,
        typer.Argument(
            help="Decision input as text, or a JSON object when --input-json is set.",
            show_default=False,
        ),
    ],
    backend: BackendOpt = None,
    input_json: Annotated[
        bool,
        typer.Option("--input-json", help="Parse INPUT_VALUE as a JSON object."),
    ] = False,
    case_id: Annotated[str, typer.Option("--id", help="Decision/correlation id.")] = "runtime",
    fmt: FormatOpt = OutputFormat.TEXT,
    healthcheck: HealthcheckOpt = True,
) -> None:
    """Make one decision and apply the contract's deterministic runtime policy."""
    with _handle_errors():
        input_data: str | dict[str, object] = input_value
        if input_json:
            try:
                parsed = json.loads(input_value)
            except ValueError as exc:
                raise DecGuardError(f"--input-json is not valid JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise DecGuardError("--input-json must decode to a JSON object")
            input_data = parsed
        with DecGuard.from_contract(contract, backend=backend, check_health=healthcheck) as guard:
            decision = guard.decide(input_data, case_id=case_id)
        if fmt is OutputFormat.JSON:
            typer.echo(decision.model_dump_json(indent=2))
        else:
            suffix = (
                f" -> {decision.fallback_backend}" if decision.fallback_backend is not None else ""
            )
            typer.echo(
                f"{decision.action}{suffix} · selected {decision.result.selected} · "
                f"confidence {decision.result.confidence:.3f} · route {decision.route_index}"
            )


def main() -> None:
    app(prog_name="decguard")
