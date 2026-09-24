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

## `systemone`

For System One decision APIs: [Kev](https://github.com/jaredpalmer/kev) servers you run
yourself, TypeSafe's Jev, and Jev through OpenRouter. They share one wire format (`state`,
typed `questions`, typed `answers`), so one adapter covers all of them.

```yaml
decision:
  name: support_team
  type: choice
  description: Which team should handle this customer support ticket?   # the question asked
  options: [billing, shipping, technical]

backend:                                      # Jev through OpenRouter's Decisions API
  provider: systemone
  model: typesafe/jev-1.13                    # required; pin a version, not an alias
  url: https://openrouter.ai/api/alpha/decisions
  bearer_token_env: OPENROUTER_API_KEY
  timeout_s: 60
  max_retries: 2              # connection failures, HTTP 429, 502-504 and 529 only

backends:
  kev:                                        # a local Kev server
    provider: systemone
    model: kev-latest
    url: http://127.0.0.1:8009/v1/systemone
    health_url: http://127.0.0.1:8009/v1/models
  typesafe:                                   # TypeSafe's own API
    provider: systemone
    model: jev-1.13.0
    url: https://api.typesafe.ai/v1/systemone
    bearer_token_env: TYPESAFE_API_KEY

evaluation:
  probability_tolerance: 0.02   # Jev rounds probabilities to two decimals (see below)
```

Settings are those of `http` (URL checks, `health_url`, timeouts, retries, environment
credentials, `label_map` for choice and score) plus `instructions`, the question asked about
every input. It defaults to the decision's `description`; one of the two is required.

Each case is sent as one question about the case input, keyed by the decision name:

```json
{
  "model": "typesafe/jev-1.13",
  "state": "I was charged twice for order #4411.",
  "questions": {
    "support_team": {
      "type": "choice",
      "instructions": "Which team should handle this customer support ticket?",
      "criteria": {"billing": null, "shipping": null, "technical": null}
    }
  }
}
```

| decision | sent | answer used |
| --- | --- | --- |
| `choice` | options as `criteria` keys, descriptions `null`, in the order shown | `probabilities` by option; `choice` must be the most probable option |
| `noul` | no labels (a yes/no question) | `noul` is the probability of the first (positive) contract label; the second gets `1 − noul` |
| `score` | levels as the ordered `criteria` list, lowest first | `probabilities` by level index (`"0"` = lowest); `legend`, when present, must echo the levels sent |

Put guidance for the options into `description` or `instructions`. During fuzzing, options
and levels are sent in the order and form shown and mapped back to the contract labels,
as with `http`. A noul question has no labels, so `option_order` and `label_format` send the
same request for it.

Answers are checked, never repaired: the response must answer exactly this question with the
same type, and a missing or malformed answer is an `invalid_response` for that case. The
provider's `confidence` field measures something else, so DecGuard ignores it: its
confidence is the selected label's probability, as for every backend. Per result, DecGuard
records the model that answered as `model_version` (for Jev the dated snapshot, e.g.
`typesafe/jev-1.13-20260917`) and adds `request_id`, `upstream_provider` (OpenRouter's
`provider`) and `usage` (`input_tokens`, `output_tokens`, `cost`) to `metadata`. The
report's backend lists the `served_models` and `upstream_providers` seen during the run.

Jev returns probabilities rounded to two decimals, so K options can sum to 1 ± K × 0.005.
Set `evaluation.probability_tolerance` to cover that (0.02 for up to four options); the sum
is still checked and never rescaled. Kev rounds to four decimals.

## `http`

For endpoints that speak DecGuard's own small JSON protocol.

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

## Real-backend validation

Two opt-in test groups run genuine inference through the `systemone` backend on the
contracts in `tests/integration/real/` (one choice, one noul and one score case each). Nothing
is mocked. A default `pytest` run skips them. Selected with `-m`, they fail rather than skip
when the server, checkpoint or credential is missing.

### Kev (`-m real_kev`)

Upstream Kev, pinned to commit `09ff745d52a0f23954e3b0f5a608bf4c7c6aebb4`, serving Kev-0.8B,
the smallest current checkpoint (a LoRA adapter and pointer head on
`Qwen/Qwen3.5-0.8B-Base`), at Hub revision `9a45d25eb2ab761841196625383fa1dff0e56c1e`. Kev
needs Python 3.12 or 3.13 and `uv`. It runs on CPU (fp32) without a GPU, and on MLX (bf16)
on Apple Silicon. The first start downloads about 1.8 GB of weights.

```bash
git clone https://github.com/jaredpalmer/kev.git && cd kev
git checkout 09ff745d52a0f23954e3b0f5a608bf4c7c6aebb4
uv sync --locked --extra serve
uv run --locked --extra serve python -m kev.serve \
  --run jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e --port 8009
```

Then, in the DecGuard checkout, once `curl -s 127.0.0.1:8009/v1/models` answers:

```bash
DECGUARD_KEV_RUN=jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e \
  uv run pytest -m real_kev
```

`DECGUARD_KEV_RUN` is optional: when set, the test fails unless the server's
`GET /v1/models` reports that checkpoint. The Kev server needs no credential (set
`KEV_API_KEY` on the server and `bearer_token_env` in the contract to require one).

### Jev through OpenRouter (`-m real_jev`)

`typesafe/jev-1.13` through OpenRouter's Decisions API
(`POST https://openrouter.ai/api/alpha/decisions`). The only credential is an OpenRouter API
key in the environment:

```bash
export OPENROUTER_API_KEY=...        # never commit it or put it in a contract
uv run pytest -m real_jev
```

This makes three billed Jev calls (about $0.00004 in total at the current price) and one
call with a deliberately invalid key, which OpenRouter rejects with HTTP 401 and does not
bill. The tests check that neither key appears in any output, error or report.

### GitHub Actions

`.github/workflows/real-backends.yml` runs both groups on `ubuntu-latest` and `macos-latest`
with Python 3.13, as four jobs: `REAL KEV` and `REAL JEV` on each OS. It never runs on
ordinary commits. Start it from the Actions tab (`workflow_dispatch`), or add the
`real-backends` label to a pull request from this repository. It needs the repository secret
`OPENROUTER_API_KEY`, which only the Jev test step receives. The Kev weights are cached by
pinned revision. The JSON reports, Kev's model card and server log are kept as artifacts.

### Any other backend (`-m external`)

```bash
DECGUARD_EXTERNAL_CONTRACT=/absolute/path/to/real-decguard.yaml \
  uv run pytest -m external
```

This runs `decguard test` on your own contract and requires a non-`mock` backend with at
least one valid decision.
