---
description: Write a Decision Contract and a golden dataset, validate them, and run your first reliability test in a few minutes.
---

# Quickstart

In this guide you describe a refund-handling decision, give DecGuard a handful of
labeled examples, and run a reliability test against an offline mock backend. Every
command and output below was produced by `decguard 0.1.1` installed from PyPI.

You need DecGuard [installed](./installation.md) and an empty directory:

```bash
pip install decguard
mkdir refund-demo && cd refund-demo
```

## 1. Describe the decision

A support tool receives a customer message and must decide whether to **refund**,
**reject** or send the request to manual **review**. Create `decguard.yaml`:

```yaml
schema_version: "0.1"

decision:
  name: refund_request
  description: Decide how to handle a customer refund request.
  type: choice
  options: [refund, reject, review]

backend:
  provider: mock
  model: refund-mock-v1
  rules:
    - contains: "damaged"
      probabilities: {refund: 0.96, reject: 0.01, review: 0.03}
    - contains: "never arrived"
      probabilities: {refund: 0.90, reject: 0.02, review: 0.08}
    - contains: "changed my mind"
      probabilities: {refund: 0.05, reject: 0.85, review: 0.10}
  default: {refund: 0.20, reject: 0.15, review: 0.65}

dataset: cases.jsonl

evaluation:
  confidence_threshold: 0.8

requirements:
  min_accuracy: 0.9
  max_ece: 0.2

warnings:
  min_coverage: 0.6
  max_latency_p95_ms: 500
```

What each section says:

- **`decision`** — the question. A `choice` decision picks one of its `options`; the model
  returns a probability for each. `description` documents the question (and is what
  [System One](./systemone.md) backends are asked).
- **`backend`** — what answers it. The [`mock`](./backends.md#mock) backend is offline and
  deterministic: the first rule whose `contains` text appears in the input answers, and
  `default` answers everything else. You will swap it for a real model in step 7.
- **`dataset`** — the golden examples, relative to the contract.
- **`evaluation.confidence_threshold`** — decisions below 0.8 confidence count as
  abstentions: cases your application would not act on automatically.
- **`requirements`** — hard gates. If one does not hold, the run **fails** (exit code 1).
- **`warnings`** — soft gates. If one does not hold, the run **warns** (exit code 0).

## 2. Add a golden dataset

Create `cases.jsonl`, one JSON object per line. `input` is what the model sees;
`expected` is the correct label.

```json
{"id": "r1", "input": "The blender arrived damaged and won't turn on.", "expected": "refund"}
{"id": "r2", "input": "My parcel never arrived, tracking stopped two weeks ago.", "expected": "refund"}
{"id": "r3", "input": "I changed my mind about the colour, please take it back.", "expected": "reject"}
{"id": "r4", "input": "The invoice shows a different price than the website did.", "expected": "review"}
{"id": "r5", "input": "Screen was damaged in transit, photos attached.", "expected": "refund"}
{"id": "r6", "input": "I changed my mind, found it cheaper elsewhere.", "expected": "reject"}
```

Real datasets are larger, and may include unlabeled cases and `metadata` for
segmentation. See [Golden datasets](./datasets.md).

## 3. Validate

`decguard validate` checks the contract, every backend's settings and the dataset,
**without calling any backend**:

```bash
decguard validate decguard.yaml
```

```text
OK  decguard.yaml
    decision  refund_request (choice): refund, reject, review
    backends  default=mock
    dataset   cases.jsonl: 6 cases, 6 labeled
    gates     requirements: 2, warnings: 2
    properties none (add 'properties' to fuzz)
    production segments: none; requirements: 0; segment requirements: 0
    policy     none
    hash      sha256:ab7ab0ad031d6130242da713be280ba3ee50dd6ad14e1665cc9a8e785ff03ecd
```

Validation is strict. A typo is an error that names the field, and the command exits
with code `2`:

```text
error: decguard.yaml: invalid contract:
  requirements.min_acuracy: unknown field (check the spelling)
```

## 4. Test

```bash
decguard test decguard.yaml --output report.json
```

```text
DecGuard 0.1.1 · refund_request (choice) · PASS

  contract  decguard.yaml  sha256:ab7ab0ad031d
  dataset   cases.jsonl  sha256:5cd7ea766986
  backend   default: mock · refund-mock-v1

  Cases        6 total · 6 decided · 0 errored · 6 labeled
  Accuracy     1.000   macro-F1 1.000
  Calibration  ECE 0.138   Brier 0.046   NLL 0.157   (10 bins)
  Selective    confidence >= 0.8: coverage 0.833   abstention 0.167   accuracy 1.000
  Latency ms   mean 0.0   p50 0.0   p95 0.0   max 0.0

  Checks
    PASS  min_accuracy                           accuracy 1 >= 0.9
    PASS  max_ece                                ece 0.1383 <= 0.2
    PASS  max_error_rate                         error_rate 0 <= 0
    PASS  min_coverage                           coverage 0.8333 >= 0.6 (warning)
    PASS  max_latency_p95_ms                     latency_p95_ms 0.007822 <= 500 (warning)

PASS: all gates hold
```

What DecGuard measured:

- **Cases** — every case got a valid answer. A backend failure would count as an error,
  never be dropped.
- **Accuracy / macro-F1** — how often the selected label is the expected one.
- **Calibration** — whether confidence matches reality. The model is always right here but on
  average only 86% confident, so the expected calibration error (ECE) is 0.138: it is
  *under*-confident. ECE, Brier and NLL are explained in
  [Golden tests and metrics](./metrics.md#calibration).
- **Selective** — 5 of 6 decisions (0.833) clear the 0.8 threshold. The sixth, the invoice
  question, got `review` at 0.65: correct, but not confident enough to automate.
- **Latency** — time spent in the backend call. The mock answers in microseconds.
- **Checks** — one line per gate. `max_error_rate` was not configured: it is an
  [implicit requirement](./gates.md#implicit-gates) that no case may error.

`--output` also wrote the complete report, including every decision, to `report.json`.
[`decguard report report.json`](./cli.md#decguard-report) prints it again at any time.

## 5. Check behavior, not only answers

Golden tests check answers to fixed inputs. **Metamorphic properties** check that the
answer does not change when it should not: here, when the options are presented in a
different order, or an irrelevant sentence is added to the message. Append to
`decguard.yaml`:

```yaml
properties:
  option_order:
    max_tv_distance: 0.03
  irrelevant_context:
    max_tv_distance: 0.05
```

`max_tv_distance` is how far the probability distribution may move (total variation
distance, 0–1) on any transformed case. Run the golden gates and the properties together:

```bash
decguard test decguard.yaml --all
```

```text
  Properties   seed 0
    option_order         18 compared · 0 violating (0.0%) · flips 0 (0.0%) · max TV 0.000
    irrelevant_context   11 compared · 0 violating (0.0%) · flips 0 (0.0%) · max TV 0.000

  Checks
    ...
    PASS  option_order.max_error_rate            option_order.error_rate 0 <= 0
    PASS  option_order.max_violation_rate        option_order.violation_rate 0 <= 0 (per case: max_tv_distance 0.03)
    PASS  irrelevant_context.max_error_rate      irrelevant_context.error_rate 0 <= 0
    PASS  irrelevant_context.max_violation_rate  irrelevant_context.violation_rate 0 <= 0 (per case: max_tv_distance 0.05)

PASS: all gates hold
```

Transformations are derived from a seed, so every run checks exactly the same inputs.
[Fuzzing and replay](./fuzzing.md) shows a model that fails this check.

## 6. PASS, WARN and FAIL

Every run ends in one status, and the exit code follows from it:

| Status | Meaning | Exit code |
| --- | --- | --- |
| <span class="dg-status pass">PASS</span> | every requirement and every warning holds | `0` |
| <span class="dg-status warn">WARN</span> | every requirement holds, at least one warning does not | `0` (`1` with `--fail-on-warn`) |
| <span class="dg-status fail">FAIL</span> | at least one requirement does not hold | `1` |
| error | the run could not be evaluated (invalid contract, unreachable backend, ...) | `2` |

**A warning.** Raise the coverage warning to `min_coverage: 0.9` and run
`decguard test decguard.yaml` again. Coverage is 0.833, so:

```text
    WARN  min_coverage                           coverage 0.8333 violates >= 0.9 (warning)

WARN: requirements hold, some warning gates do not
```

The exit code is still `0`, so a pipeline continues; add `--fail-on-warn` where
warnings must block.

**A failure.** Put `min_coverage` back to `0.6` and add a case the mock gets wrong — the
customer mentions damage but wants a replacement, which should go to review:

```json
{"id": "r7", "input": "The lid was damaged, but I just want a replacement lid.", "expected": "review"}
```

```text
  Checks
    FAIL  min_accuracy                           accuracy 0.8571 violates >= 0.9
    FAIL  max_ece                                ece 0.2329 violates <= 0.2
    PASS  max_error_rate                         error_rate 0 <= 0
    PASS  min_coverage                           coverage 0.8571 >= 0.6 (warning)
    PASS  max_latency_p95_ms                     latency_p95_ms 0.007859 <= 500 (warning)

  Failures (1 of 1)
    r7           expected review, got refund (0.96)
                 input: The lid was damaged, but I just want a replacement lid.

FAIL: at least one requirement does not hold
```

The model is wrong **and** 96% confident, so accuracy drops and calibration fails with
it. The failing example is printed with its input, and the command exits `1`. This is the
signal a CI job gates on.

## 7. Connect a real model

Only the `backend` section changes. For example, to ask TypeSafe's Jev through
OpenRouter's Decisions API:

```yaml
backend:
  provider: systemone
  model: typesafe/jev-1.13
  url: https://openrouter.ai/api/alpha/decisions
  bearer_token_env: OPENROUTER_API_KEY

evaluation:
  confidence_threshold: 0.8
  probability_tolerance: 0.02   # Jev rounds probabilities to two decimals
```

```bash
export OPENROUTER_API_KEY=...   # the key stays in the environment, never in the contract
decguard test decguard.yaml
```

You can also keep the mock as the default and add real models under
[`backends`](./contracts.md#backend-and-backends), then choose one with
`decguard test decguard.yaml --backend NAME`. See [Backends](./backends.md) for Kev,
HTTP endpoints and your own Python code.

## Next steps

- Understand the building blocks: [Decisions and results](./decisions.md),
  [Golden datasets](./datasets.md), [Requirements and warnings](./gates.md).
- Explore the complete refund example in the repository,
  [`examples/refund`](https://github.com/suffro/decguard/tree/main/examples/refund): an
  order-sensitive model, regression limits, production records and a routing policy.
- Find what golden tests miss with [metamorphic properties](./properties.md) and
  [fuzzing](./fuzzing.md).
- Compare model versions with [regression diffs](./regression.md).
- Check deployed models with [production checks](./production.md), and route live
  decisions with [policies](./policy.md).
- Gate pull requests with [GitHub Actions](./ci.md).
