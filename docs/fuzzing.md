---
description: Run metamorphic fuzzing, read property failures, reproduce them from the seed, minimize them, and replay stored failures against any backend.
---

# Fuzzing and replay

`decguard fuzz` checks the contract's [metamorphic properties](./properties.md). It is
deterministic: the same seed always generates the same transformed inputs, failures are
shrunk to minimal examples, and every failure can be replayed from the stored report.

```bash
decguard fuzz decguard.yaml                                  # every enabled property
decguard test decguard.yaml --all                            # golden gates + properties
decguard fuzz decguard.yaml -p option_order --seed 7 -o fuzz.json
```

| Option | Meaning |
| --- | --- |
| `--property`, `-p NAME` | run only this property (repeatable); default: all enabled |
| `--seed N` | transformation seed; default: `fuzz.seed` in the contract, else `0` |
| `--minimize` / `--no-minimize` | shrink failing transformations; default: `fuzz.minimize` (`true`) |
| `--backend`, `-b NAME` | run against a named backend |
| `--output`, `-o FILE` | write the JSON report, needed for `replay` |

`fuzz` and `test --all` accept the same options as `test`; see the [CLI reference](./cli.md#decguard-fuzz).

## Catching an order-sensitive model

The repository's
[refund example](https://github.com/suffro/decguard/blob/main/examples/refund/decguard.yaml)
defines a second backend, `order_sensitive`, that quietly moves 10% of the probability
mass to whichever option is shown first. Its answers never change, so golden accuracy
still looks perfect. The `option_order` property catches it:

```bash
decguard fuzz examples/refund/decguard.yaml -b order_sensitive -p option_order -o fuzz.json
```

```text
DecGuard 0.1.1 · refund_request (choice) · FAIL
  ...
  Properties   seed 42
    option_order         33 compared · 27 violating (81.8%) · flips 0 (0.0%) · max TV 0.100

  Checks
    PASS  option_order.max_error_rate            option_order.error_rate 0 <= 0
    FAIL  option_order.max_violation_rate        option_order.violation_rate 0.8182 violates <= 0 (per case: max_tv_distance 0.03)
    PASS  option_order.max_flip_rate             option_order.flip_rate 0 <= 0

  Property failures (10 of 27; replay with `decguard replay`)
    option_order/r1/1
      tv_distance 0.1 > 0.03
      sent: options [review, refund, reject] · The blender arrived damaged and won't turn on.
    option_order/r1/2
      tv_distance 0.1 > 0.03
      sent: options [review, reject, refund] · The blender arrived damaged and won't turn on.
      minimal: options [reject, refund, review] · The blender arrived damaged and won't turn on. (tv_distance 0.1 > 0.03)
    ...

FAIL: at least one requirement does not hold
```

How to read it:

- **33 compared** — 11 cases × 3 permutations. **27 violating** broke the per-case limit
  `max_tv_distance: 0.03`; the violation rate 0.8182 exceeds the allowed `0`.
- **flips 0** — the selected answer never changed. Only the distribution check reveals
  the bias, which is why limits are distribution-aware.
- **`option_order/r1/2`** — the id of one transformed case: property, case id, sample
  index. Use it with `decguard replay --id`.
- **`sent`** — exactly what the backend received. **`minimal`** — the smallest version of
  the transformation that still fails (see [minimization](#minimization)): a single swap of
  the first two options is enough.

The run exits `1`.

## Seeds and reproducibility

Transformations draw from a SHA-256-based random stream keyed by
`(seed, property, case id)`. As a result:

- the same seed gives the same transformations on every platform and Python version;
- adding cases or properties does not change the transformations of the others;
- a failure seen in CI is reproduced locally by running the same command with the same seed.

Pin `fuzz.seed` in the contract so every CI run checks the same inputs, and change it
deliberately (or pass `--seed`) to explore new ones. Reports record the seed, the fuzz and
property settings, the contract and dataset hashes, the backend metadata, and every
transformed case with its steps and any paraphrase provenance.

## Minimization

For `option_order`, `label_format`, `irrelevant_context`, `repeated_context` and
`whitespace`, a failing transformation is shrunk greedily until no smaller version still
fails, or until `fuzz.max_minimize_calls` backend calls (default 32 per failing case) are
spent:

- inserted fragments and whitespace edits are removed one at a time;
- reformatted labels are reverted one at a time;
- permutations are moved toward the original order one adjacent swap at a time.

The smallest failing version is stored as `reduced` next to the full one and printed as
`minimal`. Turn minimization off with `fuzz.minimize: false` or `--no-minimize`.

## Replay

`decguard replay` re-sends stored property failures to a backend and checks whether they
still fail:

```bash
decguard replay fuzz.json                          # every stored failure
decguard replay fuzz.json --id option_order/r1/2   # one of them
decguard replay fuzz.json --backend candidate      # against another backend
```

For each failure, replay:

1. re-sends the original case and the stored transformed case, including the reduced one,
   **exactly as stored**;
2. judges them again with the recorded limits;
3. regenerates the transformation from the seed and confirms it matches the stored one.

```text
DecGuard 0.1.1 · replay fuzz.json · 1 case(s)
  backend   order_sensitive: mock
  contract  examples/refund/decguard.yaml

  option_order/r1/2: REPRODUCED · regenerated from seed: yes
    transformed: options [review, reject, refund] · The blender arrived damaged and won't turn on.
      tv_distance 0.1 > 0.03
    reduced: options [reject, refund, review] · The blender arrived damaged and won't turn on.
      tv_distance 0.1 > 0.03

FAIL: at least one failure reproduced
```

By default replay uses the backend recorded in the report. Replay exits `1` if any failure still reproduces and `0` if none does, so it doubles as a
check that a fix works: replay the failures of the old model against the new one with
`--backend`. `--format json` prints a replay report (`replay_version` 0.1). Use
`--contract` to replay with a different contract than the one recorded in the report.

## Re-judging without the model

`decguard report fuzz.json --contract edited.yaml` re-applies edited property limits and
levels to the stored transformed cases without calling the backend. Transformations are
not regenerated. This is the fastest way to tune tolerances against real results.

## In CI

- Pin the seed; keep the JSON report as a build artifact.
- A failing CI run is then reproducible locally with `decguard replay report.json`.
- Use `level: warning` for properties you are still calibrating, and `requirement` once
  they are stable.

See [CI with GitHub Actions](./ci.md).
