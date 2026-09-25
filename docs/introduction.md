---
description: What DecGuard is, the problem it solves, and where it fits next to your decision models.
---

# What is DecGuard?

DecGuard tests, verifies and gates **probabilistic AI decision models**: models that
answer a typed question about an input — pick one of several options, say yes or no,
assign a level on a scale — and return a probability for every possible answer.

You describe the decision once in a small YAML file, the **Decision Contract**. DecGuard
runs a dataset through any backend that serves the model, normalizes every answer into the
same shape, and produces one reproducible **reliability report** with PASS / WARN / FAIL
gates and CI-friendly exit codes.

```text
Decision Contract ─┬─> backend (mock, HTTP, System One, plugin) ─> DecisionResult ─> report ─> exit 0 / 1 / 2
golden dataset ────┘
```

## Why test decisions differently?

A decision model is usually wired to an action: refund the customer, escalate the
ticket, block the message. Its probabilities matter as much as its top answer, because
they decide when the application trusts the model and when it asks a human. Accuracy on a
test set does not tell you:

- whether a confidence of 0.9 really means "right nine times out of ten"
  ([calibration](./metrics.md#calibration));
- how many decisions clear your confidence threshold, and how accurate those are
  ([coverage and selective accuracy](./metrics.md#coverage-and-selective-accuracy));
- whether the answer changes when the options are listed in a different order, the labels
  are formatted differently, or an irrelevant sentence is added
  ([metamorphic properties](./properties.md));
- whether a new model version flips answers or loses calibration compared with the one in
  production ([regression diffs](./regression.md));
- whether the deployed model is still calibrated on real traffic, in every locale or
  customer tier ([production checks](./production.md)).

DecGuard answers each of these with a deterministic metric and an explicit gate, so a
reliability regression fails a build the same way a broken unit test does.

## What you get

| Capability | Command | Page |
| --- | --- | --- |
| Validate a contract, its backends and dataset offline | `decguard validate` | [CLI](./cli.md#decguard-validate) |
| Golden-dataset metrics and gates | `decguard test` | [Golden tests and metrics](./metrics.md) |
| Metamorphic fuzzing with seeded, minimized, replayable failures | `decguard fuzz`, `test --all`, `replay` | [Properties](./properties.md), [Fuzzing](./fuzzing.md) |
| Baseline vs candidate comparison with regression gates | `decguard diff` | [Regression diffs](./regression.md) |
| Re-apply edited gates to stored results without re-running the model | `decguard report --contract` | [Reports](./reports.md) |
| Offline checks of collected production records, drift and segments | `decguard check` | [Production checks](./production.md) |
| Deterministic runtime routing: accept, abstain, fallback, human review | `decguard run`, Python SDK | [Policies and SDK](./policy.md) |

## Three decision types

| Type | Question | Example |
| --- | --- | --- |
| `choice` | Which of these options? | `refund`, `reject` or `review` for a refund request |
| `noul` | Yes or no? | Is this message spam? |
| `score` | Which level on an ordered scale? | Incident severity from 1 to 4 |

See [Decisions and results](./decisions.md) for how each type is declared and normalized.

## Backend neutral

DecGuard does not serve models. It calls them through thin adapters that all produce the
same validated `DecisionResult`, so one contract and one dataset can run against:

- the offline, deterministic [`mock`](./backends.md#mock) backend (tests, demos, CI);
- any endpoint speaking DecGuard's small [HTTP protocol](./http.md);
- [System One](./systemone.md) decision APIs: a self-hosted **Kev** server, TypeSafe's
  **Jev** through OpenRouter, or a compatible TypeSafe endpoint. This backend has been
  validated with real Kev and real Jev inference, on Linux and macOS;
- your own Python code, in-process or packaged as a [plugin](./custom-backends.md).

## What DecGuard is not

DecGuard is not a model, a model server, a generic LLM evaluation framework, a red-teaming
suite, an observability platform or a hosted service. It needs no server, database, GPU,
account or telemetry collector. It owns the decision-specific reliability layer — contract,
normalized results, metrics, comparisons, gates and reproducible reports — and leaves
everything else to the tools you already use. See [Architecture](./architecture.md).

## Status

DecGuard `0.1.1` is on PyPI. The contract format (`schema_version: "0.1"`) and the report
formats are versioned independently of the package; changes to their meaning come with a
version bump and a changelog entry. The project is Apache-2.0 licensed.

Next: [install DecGuard](./installation.md), then follow the [quickstart](./quickstart.md).
