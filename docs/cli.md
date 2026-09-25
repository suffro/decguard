---
description: Every decguard command with its arguments, options, examples and exit codes.
---

# CLI reference

```text
decguard [--version] [--help] COMMAND [ARGS]...
```

| Command | Purpose |
| --- | --- |
| [`validate`](#decguard-validate) | check a contract, its backends and dataset, offline |
| [`test`](#decguard-test) | run the golden dataset and apply the gates (`--all`: plus properties) |
| [`fuzz`](#decguard-fuzz) | check the metamorphic properties |
| [`replay`](#decguard-replay) | re-send stored property failures |
| [`diff`](#decguard-diff) | compare a baseline and a candidate report |
| [`report`](#decguard-report) | show a stored report, optionally re-applying edited gates |
| [`check`](#decguard-check) | analyze collected production records offline |
| [`run`](#decguard-run) | make one decision and apply the contract's policy |

`decguard <command> --help` prints the same options. `python -m decguard` is equivalent to
`decguard`.

## Common options

| Option | Commands | Meaning |
| --- | --- | --- |
| `--format`, `-f` `text\|json` | all except `validate` | what is printed to stdout; default `text` |
| `--output`, `-o FILE` | `test`, `fuzz`, `report`, `diff`, `check` | also write the JSON report to `FILE` |
| `--fail-on-warn` | `test`, `fuzz`, `report`, `diff`, `check` | exit `1` when only warnings are violated |
| `--backend`, `-b NAME` | `test`, `fuzz`, `replay`, `run` | named backend from the contract's `backends` (default: `backend`) |
| `--healthcheck` / `--no-healthcheck` | `test`, `fuzz`, `run` | check backend health first; default on |

Paths inside a contract (`dataset`, a paraphrase `file`) are relative to the contract
file, not to the current directory.

## `decguard validate`

Check a contract, every backend's settings and the dataset, **without calling any
backend**. Also builds the paraphrase provider when `paraphrase` is enabled.

```text
decguard validate CONTRACT [--dataset FILE]
```

| Option | Meaning |
| --- | --- |
| `--dataset`, `-d FILE` | validate this dataset instead of the contract's |

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

Exits `0` when valid, `2` otherwise. Credentials are not read (they are read at the first
request), so validation works without secrets.

## `decguard test`

Run the golden dataset through a backend, compute metrics and apply `requirements` and
`warnings`. With `--all`, also check the metamorphic properties into the same report.

```text
decguard test CONTRACT [OPTIONS]
```

| Option | Meaning |
| --- | --- |
| `--dataset`, `-d FILE` | golden dataset; overrides the contract's `dataset` |
| `--backend`, `-b NAME` | named backend |
| `--output`, `-o FILE` | write the JSON report |
| `--format`, `-f text\|json` | stdout format |
| `--max-concurrency N` | parallel backend calls, 1–256 (default: `evaluation.max_concurrency`) |
| `--fail-on-warn` | exit `1` on WARN |
| `--healthcheck` / `--no-healthcheck` | check backend health before running (default on) |
| `--all` | also check the contract's properties (`mode: all`) |
| `--seed N` | with `--all`: transformation seed (default: `fuzz.seed`, else `0`) |
| `--property`, `-p NAME` | with `--all`: run only this property (repeatable) |
| `--minimize` / `--no-minimize` | with `--all`: shrink failing transformations (default: `fuzz.minimize`) |

```bash
decguard test decguard.yaml --output report.json
decguard test decguard.yaml --all --backend candidate --fail-on-warn
```

See [Golden tests and metrics](./metrics.md).

## `decguard fuzz`

Check the contract's metamorphic properties only (`mode: fuzz`). Deterministic for a
given seed.

```text
decguard fuzz CONTRACT [OPTIONS]
```

Options are those of `test` without `--all`: `--dataset`, `--backend`, `--seed`,
`--property`, `--minimize/--no-minimize`, `--output`, `--format`, `--max-concurrency`,
`--fail-on-warn`, `--healthcheck/--no-healthcheck`.

```bash
decguard fuzz decguard.yaml -p option_order --seed 7 -o fuzz.json
```

The contract must enable at least one property, and `--property` must name an enabled
one; otherwise the command exits `2`. The same applies to `test --all`. See
[Metamorphic properties](./properties.md) and [Fuzzing and replay](./fuzzing.md).

## `decguard replay`

Re-send the property failures stored in a `fuzz` or `test --all` report and check whether
they still fail. Also regenerates each transformation from the seed and confirms it
matches the stored one.

```text
decguard replay REPORT [--id ID]... [--contract FILE] [--backend NAME] [--format text|json]
```

| Option | Meaning |
| --- | --- |
| `--id ID` | replay only this transformed case, `<property>/<case id>/<sample>` (repeatable); default: every failure |
| `--contract`, `-c FILE` | contract to use (default: the one recorded in the report) |
| `--backend`, `-b NAME` | backend to replay against (default: the one recorded in the report) |
| `--format`, `-f text\|json` | stdout format; `json` prints a replay report |

```bash
decguard replay fuzz.json --id option_order/r1/2 --backend candidate
```

Exits `1` if any failure reproduces, `0` if none does.

## `decguard diff`

Compare two stored reports of the same decision, case by case, and apply the contract's
`regression` gates.

```text
decguard diff BASELINE CANDIDATE [OPTIONS]
```

| Option | Meaning |
| --- | --- |
| `--contract`, `-c FILE` | apply this contract's `regression` gates and `evaluation` settings |
| `--segment-by`, `-s KEY` | case metadata key to segment by (repeatable); overrides `regression.segment_by` |
| `--output`, `-o FILE` | write the JSON diff |
| `--format`, `-f text\|json` | stdout format |
| `--fail-on-warn` | exit `1` on WARN |

```bash
decguard diff baseline.json candidate.json --contract decguard.yaml --output diff.json
```

Without `--contract`, only the implicit `max_error_rate_increase: 0` applies. See
[Regression diffs](./regression.md).

## `decguard report`

Show a stored report and exit with its status. With `--contract`, recompute metrics and
re-apply the (possibly edited) gates and property limits to the stored results, without
calling the model.

```text
decguard report REPORT [--contract FILE] [--output FILE] [--format text|json] [--fail-on-warn]
```

| Option | Meaning |
| --- | --- |
| `--contract`, `-c FILE` | re-evaluate against this contract's gates |
| `--output`, `-o FILE` | write the (re-evaluated) JSON report |
| `--format`, `-f text\|json` | stdout format |
| `--fail-on-warn` | exit `1` on WARN |

```bash
decguard report report.json --contract decguard.yaml
```

Loading re-verifies the whole report; a tampered or inconsistent report is rejected with
exit code `2`. See [Reports](./reports.md).

## `decguard check`

Analyze production records your application collected, offline, and apply the contract's
`production` gates.

```text
decguard check CONTRACT --dataset FILE [--baseline FILE] [OPTIONS]
```

| Option | Meaning |
| --- | --- |
| `--dataset`, `-d FILE` | collected production records, `.jsonl` or `.json` (**required**) |
| `--baseline FILE` | baseline production dataset, or a previous `decguard check` JSON report |
| `--output`, `-o FILE` | write the production report |
| `--format`, `-f text\|json` | stdout format |
| `--fail-on-warn` | exit `1` on WARN |

```bash
decguard check decguard.yaml -d production.jsonl --baseline last-week.json -o production-report.json
```

No backend is called. See [Production checks](./production.md).

## `decguard run`

Make one decision with the contract's backend and apply its `policy`.

```text
decguard run CONTRACT INPUT [--backend NAME] [--input-json] [--id ID] [--format text|json]
```

| Option | Meaning |
| --- | --- |
| `--backend`, `-b NAME` | backend that makes the decision |
| `--input-json` | parse `INPUT` as a JSON object |
| `--id ID` | case/correlation id recorded in the result (default `runtime`) |
| `--format`, `-f text\|json` | `text`: one line; `json`: the full decision and route |
| `--healthcheck` / `--no-healthcheck` | check backend health first (default on) |

```bash
decguard run decguard.yaml "The parcel never arrived"
```

```text
fallback -> strong_model · selected refund · confidence 0.900 · route 1
```

Exits `0` for every action, `2` if the contract has no `policy` or the decision fails. The
fallback backend is not invoked. See [Policies and Python SDK](./policy.md).

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | PASS; WARN unless `--fail-on-warn`; `replay`: no failure reproduced; `run`: a decision was made; `validate`: the contract is valid |
| `1` | a reliability gate failed (`test`, `fuzz`, `report`, `diff`, `check`); WARN with `--fail-on-warn`; `replay`: a failure still reproduces |
| `2` | configuration or runtime error: invalid contract, dataset, records or report; unknown backend or provider; missing credential; unhealthy backend; every case failed; invalid command-line usage; internal error |

Unexpected exceptions map to `2`, never to `1`. Error messages go to stderr as
`error: ...`; set `DECGUARD_DEBUG=1` to print a traceback for internal errors.

## Environment variables

| Variable | Meaning |
| --- | --- |
| `DECGUARD_DEBUG` | print a traceback for internal errors |
| names in `bearer_token_env`, `headers_from_env`, `api_key_env` | backend and paraphrase-provider credentials; see [Credentials](./backends.md#credentials) |
