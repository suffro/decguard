---
description: The JSON reports DecGuard writes - test/fuzz reports, diff, replay and production reports - their integrity checks, and every input format at a glance.
---

# Reports and formats

Every command that evaluates something produces a versioned JSON document. The terminal
output is a summary of the same data: `--format json` prints the full document to stdout,
and `--output FILE` writes it.

| Document | Written by | Version field |
| --- | --- | --- |
| [Report](#report) | `test`, `fuzz`, `test --all`, `report` | `report_version: "0.1"` |
| [Diff report](#diff-report) | `diff` | `diff_version: "0.1"` |
| [Replay report](#replay-report) | `replay --format json` | `replay_version: "0.1"` |
| [Production report](#production-report) | `check` | `check_version: "0.1"` |

All of them carry `decguard_version`, `created_at`, `status` (`pass`, `warn` or `fail`)
and `exit_code`. Their formats are versioned independently of the package: a change in
meaning comes with a version bump and a changelog entry.

## Report

The report of `decguard test` and `decguard fuzz`.

| Field | Content |
| --- | --- |
| `report_version`, `decguard_version`, `created_at` | format and tool provenance |
| `mode` | `test` (golden gates), `fuzz` (properties) or `all` (both) |
| `status`, `exit_code` | `pass` / `warn` / `fail`, and `0` / `0` / `1` |
| `contract` | `name`, `type`, `labels`, `schema_version`, `hash` (`sha256:`), `path` |
| `dataset` | `path`, `hash` (`sha256:` of the file bytes), `n_cases`, `n_labeled` |
| `backend` | `name`, `provider`, `model`, `model_version`, `details` (redacted provider details) |
| `health` | healthcheck `status` (`ok` / `unhealthy` / `unknown`) and `detail` |
| `evaluation`, `requirements`, `warnings` | the settings and gates used |
| `metrics` | `counts`, `classification`, `calibration` (with `reliability` bins), `selective`, `latency` |
| `checks` | one entry per gate: `gate`, `level`, `metric`, `comparison`, `threshold`, `value`, `status`, `message` |
| `failures` | failing examples (errors and wrong answers) with their inputs |
| `results` | every case: `case_id`, `input`, `expected`, `metadata`, and either a `result` or an `error` |
| `properties` | `fuzz`/`all` only: see below |

A check entry:

```json
{
  "gate": "min_accuracy",
  "level": "requirement",
  "metric": "accuracy",
  "comparison": ">=",
  "threshold": 0.9,
  "value": 1.0,
  "status": "pass",
  "message": "accuracy 1 >= 0.9"
}
```

A result entry holds the normalized
[`DecisionResult`](./decisions.md#the-normalized-decisionresult); an error entry holds its
`kind` and message.

### `properties`

Present in `fuzz` and `all` reports:

| Field | Content |
| --- | --- |
| `seed` | the transformation seed used |
| `fuzz`, `config` | the fuzz settings and every property's settings |
| `summaries` | per property: counts of transformed, skipped, errored and evaluated cases; violations and flips with their rates; max TV, JS and deltas |
| `pairs` | every transformed case: `id` (`<property>/<case id>/<sample>`), `steps`, `input`, `presentation` (option shown → contract label), `result` or `error`, `comparison`, `violations`, and a `reduced` minimal example when minimized |
| `skipped` | cases a property could not transform, with the reason |

### Integrity on load

Loading a report — with `report`, `diff` or `replay` — re-verifies it completely:

- every stored result has probabilities over exactly the contract labels, in canonical
  order, summing to 1 within the recorded `probability_tolerance`; `selected` is the
  argmax (ties to the first label) and `confidence` its probability;
- each case has exactly one of `result` or `error`;
- transformed cases are checked the same way, and their comparisons and violations must
  match what their results and the recorded property settings imply;
- dataset counts, aggregate metrics, failure examples, property summaries, checks, status
  and exit code are recomputed and must agree with the stored values.

A tampered or corrupted report is rejected with exit code `2`.

### Re-evaluation

Because `results` holds every normalized decision,
`decguard report report.json --contract edited.yaml` recomputes metrics and re-applies the
edited gates offline. Recomputation from the same results is bit-identical. For `fuzz` and
`all` reports it also re-applies edited property limits and levels to the stored
transformed cases; transformations are not regenerated.

## Diff report

Written by [`decguard diff`](./regression.md).

| Field | Content |
| --- | --- |
| `contract` | the decision compared |
| `baseline`, `candidate` | provenance of each run: `path`, `created_at`, `mode`, `contract_hash`, `dataset`, `backend` |
| `same_dataset` | whether both runs used the same dataset file (by hash) |
| `evaluation` | settings used to recompute metrics on matched cases |
| `counts` | cases per run, matched, only in one run, compared; answer flips, newly wrong/correct; newly errored, recovered, still errored |
| `shift` | answer flip rate; mean and max TV distance; mean JS divergence; mean, mean absolute and max absolute confidence delta |
| `metrics` | per metric: `baseline`, `candidate`, `delta` |
| `segments` | per segment: key, value, size, accuracy before and after, flip rate |
| `checks` | regression gates, same shape as report checks |
| `changes` | each flipped, newly errored or recovered case with its input, answers and confidences |

## Replay report

Printed by `decguard replay --format json`.

| Field | Content |
| --- | --- |
| `source` | the report replayed |
| `contract_path`, `contract_hash`, `contract_changed` | the contract used, and whether it differs from the one recorded |
| `backend` | the backend replayed against |
| `outcomes` | per replayed failure: `id`, `property`, `case_id`; `regenerated` (the seed regenerates the stored transformation; `null` for non-deterministic paraphrase providers); the new `original` result or `original_error`; the re-judged `examples` (transformed and reduced); and `reproduced` |

## Production report

Written by [`decguard check`](./production.md).

| Field | Content |
| --- | --- |
| `contract`, `evaluation` | the decision and settings used |
| `config` | the `production` section: segments and gates |
| `dataset` | `path`, `hash`, `n_records`, `n_outcomes`, `n_correctness` |
| `baseline` | `source` (`dataset` or `report`), `path`, `hash`, `n_records` and `metrics`, or `null` |
| `metrics` | `counts`, `outcomes`, `calibration`, `confidence` (with histogram), `threshold`, `routing`, `latency_ms`, `cost` |
| `drift` | `confidence_tv_distance`, `confidence_mean_delta`, `accuracy_drop`, `ece_increase` (`null` without a baseline) |
| `segments` | per metadata group: key, value, metrics, checks |
| `checks` | aggregate and segment checks |
| `records` | every normalized record |

A production report can be passed back as `--baseline` to the next `decguard check`; its
records are validated again against the contract when it is loaded.

## Input formats

| Format | Used by | Reference |
| --- | --- | --- |
| Decision Contract (YAML/JSON) | every command | [Decision Contract](./contracts.md) |
| Golden dataset (JSONL/JSON) | `validate`, `test`, `fuzz` | [Golden datasets](./datasets.md#format) |
| Production records (JSONL/JSON) | `check` | [Record schema](./production.md#record-schema) |
| Paraphrase file (JSONL) | `paraphrase` with `provider: file` | [Paraphrase providers](./properties.md#paraphrase) |
| `decguard.http/0.1` request/response | `http` backend | [HTTP protocol](./http.md#protocol-decguard-http-0-1) |
| System One request/answer | `systemone` backend | [Wire format](./systemone.md#wire-format) |

Status semantics and exit codes are described in
[Requirements and warnings](./gates.md#exit-codes) and the
[CLI reference](./cli.md#exit-codes).
