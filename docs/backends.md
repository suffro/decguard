# Backends

Every backend implements the same interface and returns the same normalized
`DecisionResult`, so one dataset can run against any of them.

```python
class DecisionBackend:
    def predict(self, request: DecisionRequest) -> Prediction: ...  # adapters implement
    def decide(self, request) -> DecisionResult: ...  # timing + validation, shared
    def metadata(self) -> BackendMetadata: ...  # provenance for reports
    def healthcheck(self) -> HealthStatus: ...  # ok / unhealthy / unknown
    def close(self) -> None: ...
```

Adapters only return raw label probabilities. `decide` measures latency and validates
them: exactly the contract's labels, finite, non-negative, summing to 1 within
`evaluation.probability_tolerance`. Anything else is an `invalid_response` error for that
case: it is counted and reported, never repaired.

Per-case failures are typed: `timeout`, `unavailable`, `invalid_response`,
`backend_error`, or `exception` (an unexpected error from a plugin). If every case fails,
or the healthcheck reports `unhealthy`, the run stops with exit code 2.

## `mock`

Deterministic and offline, for tests, examples and CI.

```yaml
backend:
  provider: mock
  model: refund-mock-v1
  rules:                       # first match wins, ignoring case and whitespace
    - contains: "damaged"
      probabilities: {refund: 0.96, reject: 0.01, review: 0.03}
  default: {refund: 0.2, reject: 0.15, review: 0.65}   # when no rule matches
  seed: 0                      # without `default`: seeded hash of the input
  model_version: "1"
  position_bias: 0.0           # deliberate defect: mass moved to the option shown first
```

Rule and default distributions are validated against the contract labels up front. The
mock reads options as a well-behaved model would: reordered options and reformatted
labels (`REFUND`, `B) refund`, `"refund"`, `[refund]`) get the same answer. Set
`position_bias` to simulate an order-sensitive model; `decguard fuzz` should catch it.

## `http`

For System-One/Jev-style endpoints and anything that can speak a small JSON protocol.

```yaml
backend:
  provider: http
  url: https://decisions.internal/v1/decide
  health_url: https://decisions.internal/healthz   # optional GET, 2xx = healthy
  model: open-jev-2b
  timeout_s: 30
  max_retries: 0              # retries only connection failures and HTTP 502/503/504
  retry_backoff_s: 0.5        # doubled after each retry
  bearer_token_env: DECISIONS_TOKEN        # Authorization: Bearer $DECISIONS_TOKEN
  headers_from_env: {X-Tenant: DECISIONS_TENANT}
  headers: {X-Client: decguard}            # static, non-secret only
  label_map: {"true": "yes", "false": "no"}   # backend label -> contract label
```

Credentials are read from environment variables when the first request is made. Literal
`Authorization`/API-key headers, URL userinfo and credential-like query parameters are
rejected. When environment-backed headers are configured, `health_url` must have the same
origin as `url`, so a healthcheck cannot forward credentials elsewhere. Reports store the
URL without its query string. Redirects are not followed, untrusted HTTP error bodies are
not recorded, and values under common credential keys in backend metadata are redacted.

### Protocol `decguard.http/0.1`

Request (`POST url`):

```json
{
  "protocol": "decguard.http/0.1",
  "case_id": "r1",
  "model": "open-jev-2b",
  "decision": {"name": "refund_request", "type": "choice", "labels": ["refund", "reject", "review"]},
  "input": "The blender arrived damaged."
}
```

`labels` are the backend's names (after `label_map`), in the order the options should be
presented. During fuzzing (`option_order`, `label_format`) they may be reordered or
reformatted; answer with probabilities keyed by the labels exactly as sent, and DecGuard
maps them back to the contract labels. Response (`200`):

```json
{
  "probabilities": {"refund": 0.91, "reject": 0.02, "review": 0.07},
  "model": "open-jev-2b",
  "model_version": "2026-09-01",
  "metadata": {"tokens": 41}
}
```

Only `probabilities` is required. Endpoints with a different shape need a thin proxy or a
plugin backend (below).

## Python code

From Python, wrap any function:

```python
from decguard.backends import CallableBackend
from decguard.engine import run_test


def decide(request):
    return {"refund": 0.7, "reject": 0.1, "review": 0.2}


report = run_test("decguard.yaml", backend=CallableBackend(decide, model="rules-v2"))
print(report.status, report.metrics.classification.accuracy)
```

Contracts never reference import paths (a contract must not be able to run arbitrary
code). To make a Python backend usable from contracts and the CLI, package it and register
it under the `decguard.backends` entry-point group:

```toml
# your package's pyproject.toml
[project.entry-points."decguard.backends"]
openjev = "decguard_openjev:OpenJevBackend"
```

```python
from typing import Self
from pydantic import BaseModel, ConfigDict
from decguard.backends import DecisionBackend, validate_settings
from decguard.decisions import Prediction


class OpenJevSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject typos in contracts
    device: str = "cpu"


class OpenJevBackend(DecisionBackend):
    provider = "openjev"

    def __init__(self, settings, *, name, model):
        super().__init__(name=name, model=model)
        self.settings = settings

    @classmethod
    def from_config(cls, config, *, name, decision) -> Self:
        # validate settings only; no network or model loading here
        return cls(
            validate_settings(OpenJevSettings, config, name=name), name=name, model=config.model
        )

    def predict(self, request):
        ...  # compute {label: probability} for request.decision.labels
        return Prediction(probabilities=..., model_version="...")
```

Then `provider: openjev` works in any contract. Built-in provider names cannot be
shadowed by plugins. Backends are called from several threads at once (up to
`evaluation.max_concurrency`), so `predict` must be thread-safe.

## Opt-in real-backend validation

The release suite includes an opt-in test that must call a real, non-`mock` backend and
produce at least one valid decision:

```bash
DECGUARD_EXTERNAL_CONTRACT=/absolute/path/to/real-decguard.yaml \
  uv run pytest -m external
```

The contract must reference a reachable endpoint implementing `decguard.http/0.1` (or an
installed backend plugin), include a real dataset, and name credentials only through
environment variables. TypeSafe/Kev-style `POST /v1/systemone` servers use a different
`state`/`questions`/`answers` wire format and therefore require a separately operated
adapter or proxy; pointing the built-in `http` backend directly at one is not compatible.
