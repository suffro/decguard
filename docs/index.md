---
layout: home
title: DecGuard
titleTemplate: Reliability testing for probabilistic AI decisions

hero:
  name: DecGuard
  text: Reliability testing for probabilistic AI decisions.
  tagline: Define decision contracts, test behavioral invariants, detect regressions, and gate unreliable model versions before production.
  actions:
    - theme: brand
      text: Get Started
      link: /quickstart
    - theme: alt
      text: View on GitHub
      link: https://github.com/suffro/decguard

features:
  - title: Decision Contracts
    details: Define typed Choice, Noul and Score decisions once, with their gates, properties and policies, in one versioned YAML file.
    link: /decisions
    linkText: Decisions and results
  - title: Reliability Testing
    details: Measure accuracy, calibration, confidence, coverage, latency and error rate on a golden dataset, with PASS / WARN / FAIL gates.
    link: /metrics
    linkText: Metrics
  - title: Metamorphic Fuzzing
    details: Stress option order, label format, irrelevant context, whitespace, paraphrases, noul inversion and score monotonicity. Seeded, minimized, replayable.
    link: /properties
    linkText: Properties
  - title: Regression Gates
    details: Compare two model or backend versions case by case and fail CI on answer flips, calibration loss, new errors or segment regressions.
    link: /regression
    linkText: Regression diffs
  - title: Production Checks
    details: Analyze decision records your application already collected, offline, with baseline drift and per-segment gates.
    link: /production
    linkText: Production checks
  - title: Backend Neutral
    details: Run the same contract against mock, HTTP, System One (Kev, Jev through OpenRouter) or your own plugin backends.
    link: /backends
    linkText: Backends
---

## One contract, every check

A Decision Contract describes the decision and what "reliable" means for it. Every
command reads the same file.

```yaml
schema_version: "0.1"

decision:
  name: refund_request
  description: How should this customer refund request be handled?
  type: choice
  options: [refund, reject, review]

backend:                   # Jev through OpenRouter; or mock, http, a plugin
  provider: systemone
  model: typesafe/jev-1.13
  url: https://openrouter.ai/api/alpha/decisions
  bearer_token_env: OPENROUTER_API_KEY

dataset: cases.jsonl

evaluation:
  probability_tolerance: 0.02   # Jev rounds probabilities to two decimals

requirements:              # violated -> FAIL, exit 1
  min_accuracy: 0.9
  max_ece: 0.1

properties:                # decguard fuzz / decguard test --all
  option_order:
    max_tv_distance: 0.03
```

| Command | Question it answers |
| --- | --- |
| [`decguard test`](./cli.md#decguard-test) | Does the model meet its accuracy, calibration and coverage gates on the golden dataset? |
| [`decguard fuzz`](./cli.md#decguard-fuzz) | Does the answer stay stable when irrelevant details of the input change? |
| [`decguard diff`](./cli.md#decguard-diff) | Is the candidate version worse than the one it replaces? |
| [`decguard check`](./cli.md#decguard-check) | Is the deployed model still calibrated on real traffic, in every segment? |
| [`decguard run`](./cli.md#decguard-run) | Given this confidence, should the application accept, abstain, fall back or ask a human? |

Exit codes are the interface: `0` pass, `1` a reliability gate failed, `2` the run could not
be evaluated. Start with the [quickstart](./quickstart.md), or read
[what DecGuard is](./introduction.md) first.
