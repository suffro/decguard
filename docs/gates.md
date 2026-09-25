---
description: How requirements and warnings turn metrics into PASS, WARN and FAIL, the implicit gates, and the exit codes CI relies on.
---

# Requirements and warnings

A **gate** is a threshold on one metric: `min_accuracy: 0.9` holds when accuracy is at
least 0.9. The contract sorts gates into two levels:

- **`requirements`** — hard gates. A violated requirement **fails** the run.
- **`warnings`** — soft gates. A violated warning turns PASS into **WARN**, but the run
  still succeeds.

```yaml
requirements:
  min_accuracy: 0.95
  max_ece: 0.05

warnings:
  max_latency_p95_ms: 300
```

Both sections accept the same gates. Gates that are not set are not checked. The same
pattern is used everywhere DecGuard gates something:

| Where | Requirements | Warnings | Reference |
| --- | --- | --- | --- |
| Golden tests (`test`, `report`) | `requirements` | `warnings` | [gates](./contracts.md#requirements-and-warnings) |
| Properties (`fuzz`, `test --all`) | `level: requirement` (default) | `level: warning` | [properties](./properties.md#limits) |
| Regression (`diff`) | top-level `regression` gates | `regression.warnings` | [regression](./regression.md#gates) |
| Production (`check`) | `production.requirements`, `segment_requirements` | `production.warnings`, `segment_warnings` | [production](./production.md#metrics-drift-and-gates) |

## Status

Each gate produces one **check**. The run's status is the worst check:

| Status | When | Exit code |
| --- | --- | --- |
| <span class="dg-status pass">PASS</span> | every check holds | `0` |
| <span class="dg-status warn">WARN</span> | every requirement holds; at least one warning does not | `0`, or `1` with `--fail-on-warn` |
| <span class="dg-status fail">FAIL</span> | at least one requirement does not hold | `1` |

Every check line shows the gate, the measured value and the threshold, and says whether
it is a warning:

```text
    PASS  min_accuracy                           accuracy 1 >= 0.9
    FAIL  max_ece                                ece 0.2329 violates <= 0.2
    WARN  min_coverage                           coverage 0.8333 violates >= 0.9 (warning)
```

## Implicit gates

Some requirements apply even when the contract does not set them, because a run that
silently loses decisions has not demonstrated anything:

- **`max_error_rate: 0`** for golden tests. Any case the backend could not decide fails the
  run, unless you set `requirements.max_error_rate` to tolerate some.
- **`<property>.max_error_rate: 0`** for every enabled property. A transformed case the
  backend fails on (or whose original case failed) means the property was not checked.
  This one cannot be relaxed.
- **`max_error_rate_increase: 0`** for regression diffs. A candidate that errors on cases
  the baseline decided fails, even without `--contract`.

## Missing values

A gate whose metric **cannot be computed** does not hold: `min_accuracy` with no labeled
cases, `max_segment_accuracy_drop` with no segment large enough, drift gates without a
baseline. The check message says why (`accuracy could not be computed (no eligible
cases)`). At requirement level the run fails; at warning level it warns.

## Exit codes

Exit codes are part of DecGuard's public interface and are the same for every command:

| Code | Meaning |
| --- | --- |
| `0` | PASS, or WARN without `--fail-on-warn` |
| `1` | a reliability gate failed (or WARN with `--fail-on-warn`); `replay`: a stored failure still reproduces |
| `2` | the run could not be evaluated: invalid contract, dataset or report; unknown backend; missing credential; unhealthy backend; every case failed; invalid command-line usage; or an internal error |

Code `1` always means "the model broke the contract" and code `2` always means "the check
itself could not run". Unexpected exceptions map to `2`, never to `1`, so a crash can never
be mistaken for a model regression. Set `DECGUARD_DEBUG=1` to print a traceback for
internal errors.

## Choosing thresholds

- **Start from a measured baseline.** Run `decguard test` on the current model, then set
  requirements slightly below what it achieves, so the gate catches regressions without
  failing on noise.
- **Use warnings for trends.** Latency and coverage often belong in `warnings` first, then
  move to `requirements` once they are stable.
- **Tighten on the main branch.** `--fail-on-warn` turns every warning into a failure where
  you want the strictest gate.
- **Re-evaluate without re-running.** [`decguard report --contract`](./cli.md#decguard-report)
  applies edited thresholds to a stored report instantly, so you can tune gates against
  real results without calling the model again.
