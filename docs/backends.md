---
description: How DecGuard reaches decision models - built-in providers, named backends, credentials, healthchecks, error handling and the offline mock backend.
---

# Backends

A **backend** is how DecGuard reaches a decision model. Every backend implements the same
small interface and returns the same validated
[`DecisionResult`](./decisions.md#the-normalized-decisionresult), so one contract and one
dataset run unchanged against any of them.

## Choosing a backend

| Provider | Use it for | Page |
| --- | --- | --- |
| `mock` | offline, deterministic tests, demos and CI; simulating defects | [below](#mock) |
| `systemone` | System One decision APIs: self-hosted **Kev**, **Jev** through OpenRouter, compatible TypeSafe endpoints | [System One](./systemone.md) |
| `http` | any endpoint that speaks DecGuard's small JSON protocol, or a thin proxy in front of your model | [Generic HTTP](./http.md) |
| plugin | a Python package registering a provider under `decguard.backends` | [Custom backends](./custom-backends.md#plugin-backends) |
| `CallableBackend` | a Python function, from the Python API only | [Custom backends](./custom-backends.md#python-callable) |

## Default and named backends

The contract's `backend` is the default. `backends` declares named alternatives: the
model you are replacing, a candidate, a staging endpoint, a fallback target for a
[policy](./policy.md).

```yaml
backend:                       # "default"
  provider: mock
  model: refund-mock-v1
  default: {refund: 0.2, reject: 0.15, review: 0.65}

backends:
  kev:
    provider: systemone
    model: kev-latest
    url: http://127.0.0.1:8009/v1/systemone
  jev:
    provider: systemone
    model: typesafe/jev-1.13
    url: https://openrouter.ai/api/alpha/decisions
    bearer_token_env: OPENROUTER_API_KEY
```

```bash
decguard test decguard.yaml                 # default
decguard test decguard.yaml --backend jev   # named
```

Every backend has `provider` (required) and `model` (optional for most providers,
required for `systemone`). All other keys are provider settings, validated by the
provider: unknown keys are errors. `decguard validate` builds every declared backend
without making network calls, so configuration mistakes surface before a run. The name
`default` is reserved for the top-level backend.

## Credentials

Credentials come **only from environment variables**. A contract names the variable,
never the value:

```yaml
backend:
  provider: systemone
  model: typesafe/jev-1.13
  url: https://openrouter.ai/api/alpha/decisions
  bearer_token_env: OPENROUTER_API_KEY   # sends Authorization: Bearer $OPENROUTER_API_KEY
```

The HTTP-based backends (`http`, `systemone`) enforce this:

- `bearer_token_env` sends `Authorization: Bearer <value>`; `headers_from_env` maps any
  other header to a variable.
- Literal `Authorization` or API-key headers, credentials embedded in the URL, and
  credential-like query parameters (`api_key`, `token`, `key`, ...) are rejected.
- Variables are read when the first request is made. A missing variable stops the run with
  exit code `2`.
- With environment-backed headers, `health_url` must share the backend URL's origin, so a
  healthcheck cannot forward a credential elsewhere.
- Reports store URLs without their query string, redirects are not followed, untrusted
  HTTP error bodies are not recorded, and values under common credential keys in backend
  metadata are redacted.

In CI, map the variable from a secret; see [CI](./ci.md#credentials).

## Healthchecks

Before a run, `test`, `fuzz` and `run` call the backend's healthcheck (disable with
`--no-healthcheck`). The result is `ok`, `unhealthy` or `unknown`; only `unhealthy` stops
the run (exit code `2`). HTTP backends are `unknown` unless `health_url` is set, in which
case any 2xx answer to a `GET` is healthy. The result is stored in the report's `health`.

## Validation and errors

Adapters only return raw label probabilities. DecGuard measures latency and validates the
answer: exactly the contract's labels, finite, non-negative, summing to 1 within
`evaluation.probability_tolerance`. Anything else is an `invalid_response` error for that
case — counted and reported, never repaired. Per-case failures are typed (`timeout`,
`unavailable`, `invalid_response`, `backend_error`, `exception`); see
[Errors are results too](./decisions.md#errors-are-results-too).

If every case fails, or the healthcheck reports `unhealthy`, the run stops with exit code
`2`.

Backends are called from up to `evaluation.max_concurrency` threads at once (default 4).

## `mock`

A deterministic, offline backend for tests, examples and CI. It needs no network and
always gives the same answer for the same input.

```yaml
backend:
  provider: mock
  model: refund-mock-v1
  rules:                       # first match wins, ignoring case and whitespace
    - contains: "damaged"
      probabilities: {refund: 0.96, reject: 0.01, review: 0.03}
  default: {refund: 0.2, reject: 0.15, review: 0.65}   # when no rule matches
  seed: 0                      # without `default`: a seeded hash of the input decides
  model_version: "1"
  position_bias: 0.0           # deliberate defect: mass moved to the option shown first
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `rules` | `[]` | checked in order; a rule matches when `contains` appears in the input (case- and whitespace-insensitive; object inputs are matched on their JSON form) |
| `default` | none | distribution when no rule matches |
| `seed` | `0` | without `default`, unmatched inputs get a pseudo-random distribution from a seeded hash of the input, stable across processes |
| `model_version` | none | reported as the result's `model_version` |
| `position_bias` | `0.0` | share of probability mass (0–1) moved to the option presented first |

Rule and default distributions are validated against the contract labels up front. The
mock reads options the way a well-behaved model would: reordered options and reformatted
labels (`REFUND`, `B) refund`, `"refund"`, `[refund]`) get the same answer, so it passes
the [metamorphic properties](./properties.md). Set `position_bias` to simulate an
order-sensitive model; the [fuzzing guide](./fuzzing.md#catching-an-order-sensitive-model)
shows `decguard fuzz` catching it.
