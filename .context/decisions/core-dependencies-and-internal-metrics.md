# Core dependencies and internal metrics

## Context

Step 1 of the v0.1 plan needs schemas, a CLI, an HTTP client, YAML parsing and reliability
metrics (accuracy, macro-F1, NLL, Brier, ECE, coverage, latency percentiles). The plan asks
to reuse mature OSS where it solves the problem, but not to add dependencies for
convenience.

## Decision

Runtime dependencies are limited to four mature, permissively licensed libraries:

- `pydantic` (MIT): typed, strict contract/result/report schemas and error messages.
- `typer` (MIT): CLI with useful `--help`; brings `click`, `rich`, `shellingham`.
- `httpx` (BSD-3): HTTP backend with timeouts and `MockTransport` for tests.
- `PyYAML` (MIT): contracts, loaded only through a `SafeLoader` subclass that also rejects
  duplicate keys.

Metrics are implemented internally in `src/decguard/metrics/core.py` (about 150 lines,
stdlib only), following scikit-learn/NumPy conventions and checked against hand-computed
values in `tests/unit/test_metrics.py`.

Build backend: `hatchling`. Tooling: `uv` (lockfile `uv.lock` committed), `ruff`, `mypy
--strict`, `pytest`.

## Alternatives considered

- scikit-learn / NumPy for metrics: correct and well known, but pull in a large
  native dependency tree for a handful of formulas over small lists; ECE is not in
  scikit-learn anyway. Rejected for v0.1; revisit if metrics grow substantially.
- `torchmetrics` / `netcal` for calibration: too heavy or too coupled for a CLI tool.
- `requests` / stdlib `urllib`: `requests` lacks a built-in mock transport; `urllib`
  makes timeouts and error typing clumsy.
- `click` directly instead of `typer`: viable; typer keeps command definitions typed.

## Consequences

- `pip install decguard` stays light and pure-Python.
- Metric definitions are ours to keep correct; `docs/reports.md` documents every formula
  and the tests pin them. Any change to a metric definition is a report-format change.
