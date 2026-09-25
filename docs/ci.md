---
description: Use DecGuard as a reliability gate in GitHub Actions - golden tests and properties on pull requests, regression diffs for model upgrades, and scheduled production checks.
---

# CI with GitHub Actions

Exit codes are the interface between DecGuard and CI:

| Code | CI outcome |
| --- | --- |
| `0` | pass (or warn) — the step succeeds |
| `1` | a reliability gate or property failed — the model broke the contract |
| `2` | the run could not be evaluated — the configuration, data or backend is broken |

A job therefore fails whenever the model breaks the contract, and fails *differently* when
the check itself is broken. No wrapper script is needed.

## Gate every pull request

The smallest useful workflow validates the contract, runs the golden gates and properties
together, and keeps the report even when the gate fails:

```yaml
name: decision-model

on:
  pull_request:

jobs:
  decguard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install decguard==0.1.1

      - name: Validate the contract (offline)
        run: decguard validate decguard.yaml

      - name: Golden gates and metamorphic properties
        run: decguard test decguard.yaml --all --output decguard-report.json

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: decguard-report
          path: decguard-report.json
```

With the offline [`mock`](./backends.md#mock) backend this needs no secrets; with a real
backend, add its credential as below.

## Credentials

Contracts name environment variables; the workflow maps them from repository secrets.
Scope a secret to the step that needs it:

```yaml
      - name: Golden gates against Jev
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}   # bearer_token_env in the contract
        run: decguard test decguard.yaml --all --backend jev --output jev.json
```

DecGuard never writes credentials into reports, errors or logs. A missing variable is a
configuration error (exit `2`), not a gate failure.

## Regression gate for a model upgrade

When a pull request changes the model — a new checkpoint, version or backend — test both
the current and the candidate model on the same golden dataset and diff them:

```yaml
name: model-upgrade

on:
  pull_request:

jobs:
  regression:
    runs-on: ubuntu-latest
    env:
      DECISIONS_TOKEN: ${{ secrets.DECISIONS_TOKEN }}   # referenced by bearer_token_env
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install decguard==0.1.1

      - name: Candidate - golden gates and properties
        run: decguard test decguard.yaml --all --backend candidate --output candidate.json

      - name: Baseline - the model in production
        if: always()
        run: decguard test decguard.yaml --backend production --output baseline.json

      - name: Regression limits
        if: always()
        run: decguard diff baseline.json candidate.json --contract decguard.yaml --output diff.json

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: decguard
          path: |
            candidate.json
            baseline.json
            diff.json
```

`if: always()` keeps the later steps running after a failed gate, so one run shows every
problem. The contract declares both backends:

```yaml
backend:
  provider: http
  url: https://decisions.internal/v1/decide
  model: refund-v3
  bearer_token_env: DECISIONS_TOKEN

backends:
  production:
    provider: http
    url: https://decisions.internal/v1/decide
    model: refund-v3
    bearer_token_env: DECISIONS_TOKEN
  candidate:
    provider: http
    url: https://decisions.internal/v1/decide
    model: refund-v4
    bearer_token_env: DECISIONS_TOKEN

regression:
  max_answer_flip_rate: 0.02
  max_accuracy_drop: 0.01
  max_ece_increase: 0.02
```

To avoid re-running the baseline on every pull request, store the production model's
report once and diff against it.

## Scheduled production check

[`decguard check`](./production.md) is offline, so it runs after whatever job exports your
decision records. A nightly workflow:

```yaml
name: production-reliability

on:
  schedule:
    - cron: "0 5 * * *"
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install decguard==0.1.1

      - name: Export yesterday's decisions
        run: ./scripts/export-decisions.sh > production.jsonl   # your own export

      - name: Post-deployment gates
        run: |
          decguard check decguard.yaml \
            --dataset production.jsonl \
            --baseline reference/production.jsonl \
            --output production-report.json

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: production-report
          path: production-report.json
```

The baseline can be a reference batch kept in the repository, as here, or a previous
production report. DecGuard does not ingest telemetry or need access to the model.

## Tips

- **Pin versions.** Pin the DecGuard version, and pin model versions in the contract (for
  example `typesafe/jev-1.13` rather than an alias), so a change is always a reviewed diff.
- **Pin the seed.** Set `fuzz.seed` in the contract so every run checks the same
  transformations; change it deliberately to explore new ones.
- **Keep reports as artifacts.** A failure can then be inspected with
  `decguard report`, replayed with `decguard replay`, or re-gated with
  `decguard report --contract`.
- **Stricter main branch.** Add `--fail-on-warn` where warnings must block.
- **Cost.** With a billed backend, every golden case and every transformed case is a
  request. Keep property `samples` small in pull-request workflows and run broader fuzzing
  on a schedule.
- **Concurrency.** Lower `evaluation.max_concurrency` (or `--max-concurrency`) for
  rate-limited backends; `systemone` backends also retry HTTP 429 when `max_retries` is set.

## Real-backend compatibility (this repository)

DecGuard's own `Real backends` workflow makes genuine decisions through a Kev server
started on the runner and through Jev on OpenRouter, on Ubuntu and macOS. It is manual
(`workflow_dispatch`, or the `real-backends` label on a pull request) and passes
`OPENROUTER_API_KEY` to the Jev test step only. See
[Real-backend validation](./systemone.md#real-backend-validation).
