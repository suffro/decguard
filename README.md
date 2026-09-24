# DecGuard

Test, verify and gate **probabilistic AI decision models** — models that answer a typed
question (pick an option, say yes/no, assign a level) with a probability for each answer.

DecGuard sits above your decision backends. You describe the decision once in a small
**contract**, run a dataset through any backend, and get one reproducible **reliability
report** with CI-friendly PASS / WARN / FAIL gates.

> Status: v0.1 release candidate (`0.1.0`), not yet tagged or published. Contracts,
> backends, golden-dataset testing, metrics, reports, metamorphic fuzzing,
> regression/replay, offline post-deployment checks, explicit cascade policies and the
> Python SDK are implemented.

## 5-minute quickstart

```bash
git clone https://github.com/suffro/decguard && cd decguard
uv tool install .            # or, in a virtualenv: pip install .
decguard validate examples/refund/decguard.yaml
decguard test examples/refund/decguard.yaml --all --output stable.json
```

```text
DecGuard 0.1.0 · refund_request (choice) · PASS

  Cases        11 total · 11 decided · 0 errored · 10 labeled
  Accuracy     1.000   macro-F1 1.000
  Calibration  ECE 0.139   Brier 0.049   NLL 0.159   (10 bins)
  Selective    confidence >= 0.8: coverage 0.727   abstention 0.273   accuracy 1.000
  ...
  Checks
    PASS  min_accuracy                           accuracy 1 >= 0.9
    PASS  max_ece                                ece 0.139 <= 0.15
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

### Find what golden tests miss

The refund example also defines `order_sensitive`, a backend that quietly favours whichever
option is listed first. Its ordinary accuracy still looks perfect, but calibration and the
metamorphic properties catch it:

```bash
decguard test examples/refund/decguard.yaml -b order_sensitive       # calibration FAIL
decguard fuzz examples/refund/decguard.yaml -b order_sensitive -o fuzz.json
```

```text
  Properties   seed 42
    option_order         33 compared · 27 violating (81.8%) · flips 0 (0.0%) · max TV 0.100
    label_format         22 compared · 0 violating (0.0%) · flips 0 (0.0%) · max TV 0.000
    ...
    FAIL  option_order.max_violation_rate        option_order.violation_rate 0.8182 violates <= 0 (per case: ...)
  Property failures (10 of 27; replay with `decguard replay`)
    option_order/r1/0
      tv_distance 0.1 > 0.03
      sent: options [reject, refund, review] · The blender arrived damaged and won't turn on.
FAIL: at least one requirement does not hold
```

The broken run exits `1`, records the distribution drift and stores minimal failing
examples. Replay it, then show that the same backend also breaks calibration and the
regression limit:

```bash
decguard replay fuzz.json                                           # reproduces; exit 1
decguard test examples/refund/decguard.yaml -b order_sensitive -o candidate.json
decguard diff stable.json candidate.json -c examples/refund/decguard.yaml
```

### Check production records and route runtime decisions

Analyze records your application collected—fully offline—and gate aggregate, drift and
metadata-segment reliability:

```bash
decguard check examples/refund/decguard.yaml \
  --dataset examples/refund/production.jsonl \
  --output production-report.json
```

Compare an intentionally overconfident, incorrect batch to see calibration drift and
localized segment failures (exit `1`):

```bash
decguard check examples/refund/decguard.yaml \
  --dataset examples/refund/production-drift.jsonl \
  --baseline examples/refund/production.jsonl
```

The same contract can deterministically route one normalized decision:

```bash
decguard run examples/refund/decguard.yaml "The blender arrived damaged"
decguard run examples/refund/decguard.yaml "The parcel never arrived"
decguard run examples/refund/decguard.yaml "Can someone call me?"
```

These three calls deterministically return `accept`, a `fallback -> strong_model`
directive, and `human_review`. The fallback is not invoked automatically.

See [post-deployment checks](docs/production.md) and the
[policy/SDK guide](docs/policy.md).

## Commands

| Command | What it does |
| --- | --- |
| `decguard validate <contract>` | Check the contract, backend settings and dataset offline. |
| `decguard test <contract>` | Run the dataset through a backend (`--backend NAME` picks a named one), print the report, `--output report.json` to keep it. |
| `decguard fuzz <contract>` | Check the contract's metamorphic properties (option order, label format, irrelevant context, whitespace, paraphrase, noul inversion, score monotonicity); deterministic per `--seed`. |
| `decguard test <contract> --all` | Golden gates and properties in one report. |
| `decguard replay <report.json>` | Re-send stored property failures (`--id` for one); exit 1 if they still fail. |
| `decguard diff <baseline.json> <candidate.json>` | Answer flips, confidence/distribution shifts, calibration, latency, error and per-segment changes; `--contract` applies `regression` gates. |
| `decguard report <report.json>` | Show a stored report; `--contract` re-applies (possibly edited) gates without re-running the model. |
| `decguard check <contract> --dataset <records>` | Analyze production JSONL/JSON offline, optionally against `--baseline`, with aggregate and segment gates. |
| `decguard run <contract> <input>` | Make one decision and apply the contract's ordered policy. |

Exit codes: **0** pass (or warn; `--fail-on-warn` turns warn into 1), **1** a reliability
gate failed, **2** configuration or runtime error. Use `--format json` for machine-readable
output on stdout.

### In CI

```yaml
- run: uv tool install git+https://github.com/suffro/decguard
- run: decguard test decguard.yaml --all --output decguard-report.json
- uses: actions/upload-artifact@v4
  if: always()
  with: { name: decguard-report, path: decguard-report.json }
```

A full workflow with a regression diff is in [docs/ci.md](docs/ci.md).

## Documentation

- [Decision Contract reference](docs/contracts.md)
- [Backends and the HTTP protocol](docs/backends.md)
- [Reports, metrics and gates](docs/reports.md)
- [Metamorphic properties, fuzzing and replay](docs/properties.md)
- [Regression diffs](docs/regression.md)
- [Post-deployment checks and record format](docs/production.md)
- [Runtime cascade policy and Python SDK](docs/policy.md)
- [Architecture and integration philosophy](docs/architecture.md)
- [CI with GitHub Actions](docs/ci.md)
- [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## What DecGuard is not

Not a model, not a generic LLM eval framework, not a hosted service or dashboard. It owns
the decision-specific reliability layer (contract, normalized results, metrics, gates,
report) and stays backend-neutral; other tools plug in as optional integrations.

## License

Apache-2.0
