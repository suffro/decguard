---
description: How DecGuard is structured, how data flows through it, the design principles it keeps, and what it deliberately does not do.
---

# Architecture

DecGuard is a local Python library and CLI around a small, provider-neutral core. There
is no server, database, telemetry collector or hosted account: every command reads files,
optionally calls a backend, and writes a JSON document.

```text
Decision Contract
      │
      ├──> backend adapter ──> normalized DecisionResult ──> golden / property report
      │                                                        │
      │                                   two reports ──> regression diff
      │
      ├──> production JSONL ─────────────────────────────> production report
      │
      └──> DecisionResult + explicit policy ─────────────> route directive
```

- **Contracts** own the typed decision semantics, reliability gates, metamorphic
  properties, post-deployment checks and deterministic policies.
- **Adapters** normalize local functions, HTTP and System One endpoints, and third-party
  `decguard.backends` entry points into one `DecisionResult`.
- **Engines** — golden testing, fuzzing, diff, replay, production checks and policy
  evaluation — are shared by the CLI and the Python API, and emit versioned JSON plus a
  concise terminal view with consistent PASS / WARN / FAIL exit semantics.

## Data flow

**Golden test.** contract file → load and validate → decision spec + backend; dataset
file → validated cases → run with bounded concurrency, dataset order preserved → results
or per-case errors → metrics → gates → report → JSON file, terminal text, exit code.

**Fuzz.** After the golden run, each enabled property generates transformations per case
from the seed → options presented as shown, sent to the backend, mapped back → compared
with the original → failing transformations minimized → recorded in the same report.

**Diff.** Two stored reports → cases matched by id → shifts, metric deltas, segments →
regression gates → diff report.

**Production.** Collected records → strict normalization → aggregate and segment metrics
→ optional baseline drift → gates → production report. No backend is called.

**Runtime.** Backend result → ordered policy → action directive. A fallback is returned,
not invoked.

## Components

| Package | Responsibility |
| --- | --- |
| `decguard.contracts` | schema `0.1` models, safe loading with duplicate-key rejection, contract hash |
| `decguard.decisions` | decision spec, request, raw `Prediction`, normalized `DecisionResult`, probability validation |
| `decguard.datasets` | golden cases from JSONL/JSON, validated against the contract labels |
| `decguard.backends` | `DecisionBackend` interface; `mock`, `http`, `systemone`; `CallableBackend`; entry-point registry |
| `decguard.runner` | bounded thread pool; per-case errors |
| `decguard.metrics` | pure-stdlib metrics and distribution comparisons |
| `decguard.fuzz` | seeded RNG, transformations, paraphrase providers, comparison, minimization, replay |
| `decguard.regression` | report diffs and regression gates |
| `decguard.production` | production records, metrics, drift, segments, production reports |
| `decguard.policy` | pure first-match route evaluation |
| `decguard.reports` | gates, the report model with load-time verification, terminal rendering |
| `decguard.engine`, `decguard.sdk`, `decguard.cli` | orchestration, the `DecGuard` SDK, the command line |

## Design principles

- **Never repair, never drop.** Malformed backend output, invalid dataset rows and invalid
  production records are errors. Probabilities are validated, not rescaled.
- **Deterministic and reproducible.** Metrics use exact summation in dataset order; fuzz
  transformations derive from a SHA-256 stream keyed by seed, property and case id; the
  mock backend's output is pinned by tests.
- **Reports are verifiable.** Every stored report is re-checked on load: results, counts,
  metrics, property comparisons, checks and status must all agree.
- **Exit codes are API.** `0` pass/warn, `1` gate failed, `2` could not evaluate.
  Unexpected exceptions map to `2`, never `1`.
- **Contracts are data.** Safe YAML, strict schemas, no import paths, no secrets; plugins
  are installed packages, never code referenced by a contract.
- **Credentials only from the environment.** They never appear in reports, errors or
  logs; authenticated healthchecks stay on the backend's origin.
- **Small dependency footprint.** Four runtime dependencies: pydantic, typer, httpx and
  PyYAML. Metrics are implemented in the standard library.

## Integration philosophy

DecGuard deliberately does not recreate model servers, generic LLM evaluation or
red-teaming frameworks, training systems or observability platforms. External projects
plug in at two boundaries:

- **backends** — anything that returns label probabilities, through `http`, `systemone`
  or a `decguard.backends` plugin;
- **paraphrase providers** — `file`, OpenAI-compatible APIs, or a `decguard.paraphrasers`
  plugin.

DecGuard keeps the decision-specific layer: the contract, normalization, comparisons,
gating and reproducibility. The core stays fully usable when no optional integration is
installed.

## Non-goals for v0.1

- Automatically invoking fallback backends or optimizing routing policies. A `fallback`
  route is a directive; cascade execution stays in the application.
- Ingesting telemetry or running as a service. Production checks read exported files.
- A general analytics query language. Segments are simple groups by scalar metadata
  values.
- Hosting models or managing credentials.
