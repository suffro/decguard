# DecGuard

Reliability testing for **probabilistic AI decisions**: models that answer a typed
question — pick an option, say yes or no, assign a level — with a probability for each
answer.

You describe the decision once in a small **Decision Contract**, run a dataset through
any backend, and get one reproducible **reliability report** with CI-friendly
PASS / WARN / FAIL gates. DecGuard measures accuracy and calibration, fuzzes behavioral
invariants, compares model versions, and checks production records offline.

> Status: alpha (v0.1). The contract format and reports are versioned; the `systemone`
> backend is validated end to end against a real Kev-0.8B server and real Jev through
> OpenRouter, on Linux and macOS.

## Install

```bash
pip install decguard          # or: uv tool install decguard
```

Python 3.11+. Four runtime dependencies (pydantic, typer, httpx, PyYAML); no GPU,
server or account.

## Quickstart

```bash
git clone --depth 1 https://github.com/suffro/decguard && cd decguard
decguard validate examples/refund/decguard.yaml
decguard test examples/refund/decguard.yaml --all
```

```text
DecGuard 0.1.1 · refund_request (choice) · PASS

  Cases        11 total · 11 decided · 0 errored · 10 labeled
  Accuracy     1.000   macro-F1 1.000
  Calibration  ECE 0.139   Brier 0.049   NLL 0.159   (10 bins)
  Selective    confidence >= 0.8: coverage 0.727   abstention 0.273   accuracy 1.000
  ...
  Checks
    PASS  min_accuracy                           accuracy 1 >= 0.9
    PASS  max_ece                                ece 0.139 <= 0.15
    PASS  option_order.max_violation_rate        option_order.violation_rate 0 <= 0 (per case: max_tv_distance 0.03)
    ...
PASS: all gates hold
```

A contract ([reference](https://github.com/suffro/decguard/blob/main/docs/contracts.md)):

```yaml
schema_version: "0.1"

decision:
  name: refund_request
  description: How should this customer refund request be handled?
  type: choice                # choice | noul | score
  options: [refund, reject, review]

backend:
  provider: systemone         # or: mock, http, an installed plugin
  model: typesafe/jev-1.13
  url: https://openrouter.ai/api/alpha/decisions
  bearer_token_env: OPENROUTER_API_KEY

dataset: cases.jsonl          # {"input": ..., "expected": ...?, "metadata": ...?} per line

evaluation:
  confidence_threshold: 0.8   # below this, a decision counts as an abstention
  probability_tolerance: 0.02 # Jev rounds probabilities to two decimals

requirements:                 # hard gates -> exit code 1
  min_accuracy: 0.95
  max_ece: 0.05

warnings:                     # soft gates -> WARN
  max_latency_p95_ms: 300

properties:                   # metamorphic checks (decguard fuzz / test --all)
  option_order:
    max_tv_distance: 0.03
```

The [quickstart guide](https://github.com/suffro/decguard/blob/main/docs/quickstart.md) walks through writing your first contract
and dataset.

## Capabilities

| Command | What it does |
| --- | --- |
| `decguard validate` | Check the contract, backend settings and dataset offline. |
| `decguard test` | Golden-dataset metrics (accuracy, calibration, coverage, latency, errors) and gates; `--all` adds properties. |
| `decguard fuzz` | Metamorphic properties: option order, label format, irrelevant/repeated context, whitespace, paraphrase, noul inversion, score monotonicity. Seeded and minimized. |
| `decguard replay` | Re-send stored property failures; exit 1 if they still fail. |
| `decguard diff` | Compare a baseline and a candidate run: flips, distribution and confidence shifts, calibration, errors, segments. |
| `decguard report` | Show a stored report; `--contract` re-applies edited gates without re-running the model. |
| `decguard check` | Analyze collected production records offline: calibration, drift, metadata segments. |
| `decguard run` | Make one decision and apply the contract's policy: `accept`, `abstain`, `fallback` or `human_review`. |

Exit codes: **0** pass (or warn), **1** a reliability gate failed, **2** configuration or
runtime error.

Backends: an offline `mock`, a generic `http` protocol, `systemone` for **Kev**
(self-hosted), **Jev through OpenRouter** and TypeSafe endpoints — validated with real Kev
and Jev inference on Linux and macOS — plus Python plugins.

## Documentation

The full documentation is a [VitePress](https://vitepress.dev) site in [`docs/`](https://github.com/suffro/decguard/tree/main/docs):

- Getting started: [What is DecGuard?](https://github.com/suffro/decguard/blob/main/docs/introduction.md) ·
  [Installation](https://github.com/suffro/decguard/blob/main/docs/installation.md) · [Quickstart](https://github.com/suffro/decguard/blob/main/docs/quickstart.md)
- Concepts: [Decisions and results](https://github.com/suffro/decguard/blob/main/docs/decisions.md) ·
  [Golden datasets](https://github.com/suffro/decguard/blob/main/docs/datasets.md) · [Requirements and warnings](https://github.com/suffro/decguard/blob/main/docs/gates.md)
- Testing: [Metrics](https://github.com/suffro/decguard/blob/main/docs/metrics.md) · [Metamorphic properties](https://github.com/suffro/decguard/blob/main/docs/properties.md) ·
  [Fuzzing and replay](https://github.com/suffro/decguard/blob/main/docs/fuzzing.md) · [Regression diffs](https://github.com/suffro/decguard/blob/main/docs/regression.md)
- Production: [Production checks](https://github.com/suffro/decguard/blob/main/docs/production.md) ·
  [Policies and Python SDK](https://github.com/suffro/decguard/blob/main/docs/policy.md)
- Backends: [Overview](https://github.com/suffro/decguard/blob/main/docs/backends.md) · [System One: Kev and Jev](https://github.com/suffro/decguard/blob/main/docs/systemone.md) ·
  [HTTP](https://github.com/suffro/decguard/blob/main/docs/http.md) · [Custom backends](https://github.com/suffro/decguard/blob/main/docs/custom-backends.md)
- Reference: [CLI](https://github.com/suffro/decguard/blob/main/docs/cli.md) · [Decision Contract](https://github.com/suffro/decguard/blob/main/docs/contracts.md) ·
  [Reports and formats](https://github.com/suffro/decguard/blob/main/docs/reports.md)
- [CI with GitHub Actions](https://github.com/suffro/decguard/blob/main/docs/ci.md) · [Architecture](https://github.com/suffro/decguard/blob/main/docs/architecture.md)

To browse it locally (Node.js 18+):

```bash
cd docs
npm ci
npm run dev
```

## What DecGuard is not

Not a model, a model server, a generic LLM evaluation framework or a hosted service. It
owns the decision-specific reliability layer — contract, normalized results, metrics,
gates, reports — and stays backend-neutral.

## Contributing and license

See [CONTRIBUTING.md](https://github.com/suffro/decguard/blob/main/CONTRIBUTING.md) and the [changelog](https://github.com/suffro/decguard/blob/main/CHANGELOG.md).
Licensed under Apache-2.0.
