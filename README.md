# DecGuard

Test, verify and gate **probabilistic AI decision models** — models that answer a typed
question (pick an option, say yes/no, assign a level) with a probability for each answer.

DecGuard sits above your decision backends. You describe the decision once in a small
**contract**, run a dataset through any backend, and get one reproducible **reliability
report** with CI-friendly PASS / WARN / FAIL gates.

> Status: pre-release (`0.1.0.dev0`). Step 1 of the v0.1 plan is implemented: contracts,
> backends, golden-dataset testing, metrics, reports and CLI. Metamorphic fuzzing,
> regression diffs, post-deployment checks and fallback policies come next.

## 5-minute quickstart

```bash
git clone https://github.com/suffro/decguard && cd decguard
uv tool install .            # or: pip install .
decguard test examples/refund/decguard.yaml
```

```text
DecGuard 0.1.0.dev0 · refund_request (choice) · PASS

  Cases        11 total · 11 decided · 0 errored · 10 labeled
  Accuracy     1.000   macro-F1 1.000
  Calibration  ECE 0.139   Brier 0.049   NLL 0.159   (10 bins)
  Selective    confidence >= 0.8: coverage 0.727   abstention 0.273   accuracy 1.000
  ...
  Checks
    PASS  min_accuracy             accuracy 1 >= 0.9
    PASS  max_ece                  ece 0.139 <= 0.15
    ...
PASS: all gates hold
```

A contract looks like this ([full reference](docs/contracts.md)):

```yaml
schema_version: "0.1"

decision:
  name: refund_request
  type: choice                # choice | noul | score
  options: [refund, reject, review]

backend:
  provider: http              # or: mock, or an installed plugin
  url: https://decisions.internal/v1/decide
  model: open-jev-2b
  bearer_token_env: DECISIONS_TOKEN

dataset: cases.jsonl          # {"input": ..., "expected": ...?, "metadata": ...?} per line

evaluation:
  confidence_threshold: 0.8   # below this, a decision counts as an abstention

requirements:                 # hard gates -> exit code 1
  min_accuracy: 0.95
  max_ece: 0.05

warnings:                     # soft gates -> WARN
  max_latency_p95_ms: 300
```

## Commands

| Command | What it does |
| --- | --- |
| `decguard validate <contract>` | Check the contract, backend settings and dataset offline. |
| `decguard test <contract>` | Run the dataset through a backend (`--backend NAME` picks a named one), print the report, `--output report.json` to keep it. |
| `decguard report <report.json>` | Show a stored report; `--contract` re-applies (possibly edited) gates without re-running the model. |

Exit codes: **0** pass (or warn; `--fail-on-warn` turns warn into 1), **1** a reliability
gate failed, **2** configuration or runtime error. Use `--format json` for machine-readable
output on stdout.

### In CI

```yaml
- run: uv tool install git+https://github.com/suffro/decguard
- run: decguard test decguard.yaml --output decguard-report.json
- uses: actions/upload-artifact@v4
  if: always()
  with: { name: decguard-report, path: decguard-report.json }
```

## Documentation

- [Decision Contract reference](docs/contracts.md)
- [Backends and the HTTP protocol](docs/backends.md)
- [Reports, metrics and gates](docs/reports.md)
- [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## What DecGuard is not

Not a model, not a generic LLM eval framework, not a hosted service or dashboard. It owns
the decision-specific reliability layer (contract, normalized results, metrics, gates,
report) and stays backend-neutral; other tools plug in as optional integrations.

## License

Apache-2.0
