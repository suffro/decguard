---
description: Use the built-in systemone backend with a self-hosted Kev server, Jev through OpenRouter's Decisions API, or a compatible TypeSafe System One endpoint.
---

# System One: Kev and Jev

The built-in `systemone` backend speaks the **System One** decision wire format: an input
(`state`), typed `questions`, and typed `answers` with probabilities. One adapter covers
every service that uses it:

- **Kev** — a [Kev](https://github.com/jaredpalmer/kev) server you run yourself;
- **Jev through OpenRouter** — TypeSafe's Jev via OpenRouter's Decisions API;
- **TypeSafe** — compatible TypeSafe System One endpoints, directly.

The adapter has been validated with real inference against a self-hosted Kev-0.8B server
and against Jev (`typesafe/jev-1.13`) through OpenRouter, on Linux and macOS, for
`choice`, `noul` and `score` decisions. See [Real-backend validation](#real-backend-validation).

## The question

System One models answer a question about the input, so the question must be stated.
DecGuard uses the decision's `description`, or the backend's `instructions` setting when
it is set. One of the two is required.

```yaml
decision:
  name: support_team
  type: choice
  description: Which team should handle this customer support ticket?
  options: [billing, shipping, technical]
```

Put guidance about the options into the description (or `instructions`): for `choice`
decisions, option names are sent without descriptions.

## Jev through OpenRouter

```yaml
backend:
  provider: systemone
  model: typesafe/jev-1.13
  url: https://openrouter.ai/api/alpha/decisions
  bearer_token_env: OPENROUTER_API_KEY
  timeout_s: 60
  max_retries: 2

evaluation:
  probability_tolerance: 0.02   # Jev rounds probabilities to two decimals
```

The only credential is an OpenRouter API key, and it belongs in the
**`OPENROUTER_API_KEY`** environment variable — never in the contract:

```bash
export OPENROUTER_API_KEY=...
decguard test decguard.yaml
```

- **Pin a model version** (`typesafe/jev-1.13`), not a moving alias. Each result records
  the dated snapshot that actually answered as `model_version` (for example
  `typesafe/jev-1.13-20260917`), so a silent upstream change shows up in
  [regression diffs](./regression.md).
- **Probability tolerance.** Jev returns probabilities rounded to two decimals, so K
  labels can sum to 1 ± K × 0.005. Set `evaluation.probability_tolerance` to cover it
  (`0.02` for up to four labels). The sum is still checked and never rescaled.
- **Cost.** Every case is one billed request, as is every transformed case during
  fuzzing. Token usage and cost are recorded per result (see [below](#what-gets-recorded)).

## Self-hosted Kev

Run a Kev server, then point the backend at its System One endpoint. Kev serves
`/v1/systemone` for decisions and `/v1/models` for the loaded model, which works as a
healthcheck:

```yaml
backend:
  provider: systemone
  model: kev-latest
  url: http://127.0.0.1:8009/v1/systemone
  health_url: http://127.0.0.1:8009/v1/models
  timeout_s: 300          # CPU inference; the first request also warms the model up
```

This is the flow DecGuard validates in CI, with upstream Kev at a pinned commit serving
Kev-0.8B, the smallest current checkpoint (a LoRA adapter and pointer head on
`Qwen/Qwen3.5-0.8B-Base`). Kev needs Python 3.12 or 3.13 and `uv`. It runs on CPU (fp32)
without a GPU, and on MLX (bf16) on Apple Silicon. The first start downloads about 1.8 GB
of weights.

```bash
git clone https://github.com/jaredpalmer/kev.git && cd kev
git checkout 09ff745d52a0f23954e3b0f5a608bf4c7c6aebb4
uv sync --locked --extra serve
uv run --locked --extra serve python -m kev.serve \
  --run jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e --port 8009
```

Once `curl -s 127.0.0.1:8009/v1/models` answers, `decguard test` can use it. Kev rounds
probabilities to four decimals, so the default tolerance is usually enough.

A local Kev server needs no credential. To require one, set `KEV_API_KEY` on the server
and `bearer_token_env` (naming a variable that holds the same key) in the contract.

## TypeSafe endpoints

A TypeSafe System One endpoint uses the same adapter with its own URL, model name and key
variable:

```yaml
backends:
  typesafe:
    provider: systemone
    model: jev-1.13.0
    url: https://api.typesafe.ai/v1/systemone
    bearer_token_env: TYPESAFE_API_KEY
```

The real-backend validation covers Kev and Jev through OpenRouter; direct TypeSafe
endpoints share the wire format but are not part of that validation.

## Comparing backends

Declare several System One backends in one contract and run the same dataset through
each, then [diff](./regression.md) them:

```yaml
backend:                                   # a local Kev server
  provider: systemone
  model: kev-latest
  url: http://127.0.0.1:8009/v1/systemone
  health_url: http://127.0.0.1:8009/v1/models
  timeout_s: 300

backends:
  jev:                                     # Jev through OpenRouter
    provider: systemone
    model: typesafe/jev-1.13
    url: https://openrouter.ai/api/alpha/decisions
    bearer_token_env: OPENROUTER_API_KEY
    timeout_s: 60
    max_retries: 2

evaluation:
  probability_tolerance: 0.02
```

```bash
decguard test decguard.yaml -o kev.json
decguard test decguard.yaml --backend jev -o jev.json
decguard diff kev.json jev.json --contract decguard.yaml
```

## Settings

`systemone` accepts every [`http` setting](./http.md#settings) — URL checks, `health_url`,
timeouts, retries, environment credentials, `label_map` — plus:

| Setting | Default | Meaning |
| --- | --- | --- |
| `model` | required | the model to ask; sent with every request |
| `instructions` | `decision.description` | the question asked about every input |

Differences from `http`:

- retries (`max_retries`) also cover HTTP **429** and **529**, which TypeSafe and
  OpenRouter ask clients to retry, besides connection failures and 502–504;
- `label_map` applies to `choice` and `score` decisions only, since no labels are sent
  for `noul`.

## Wire format

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

| Decision | Sent | Answer used |
| --- | --- | --- |
| `choice` | options as `criteria` keys, descriptions `null`, in the order shown | `probabilities` by option; `choice` must be the most probable option |
| `noul` | no labels (a yes/no question) | `noul` is the probability of the first (positive) contract label; the second gets `1 − noul` |
| `score` | levels as the ordered `criteria` list, lowest first | `probabilities` by level index (`"0"` = lowest); `legend`, when present, must echo the levels sent |

During fuzzing, options and levels are sent in the order and form shown and mapped back
to the contract labels. A `noul` question has no labels, so `option_order` and
`label_format` send the same request for it.

Answers are checked, never repaired. The response must answer exactly this question with
the same type; a missing or malformed answer is an `invalid_response` for that case. The
provider's own `confidence` field measures something else, so DecGuard ignores it: its
confidence is the selected label's probability, as for every backend.

## What gets recorded

Per result, DecGuard records the model that answered as `model_version` and adds to
`metadata`:

- `request_id`;
- `upstream_provider` — OpenRouter's `provider` field;
- `usage` — `input_tokens`, `output_tokens` and `cost`.

The report's backend section lists the `served_models` and `upstream_providers` seen during
the run. API keys never appear in reports, errors or terminal output.

## Real-backend validation

The DecGuard repository runs genuine inference through the `systemone` backend on three
small contracts in
[`tests/integration/real/`](https://github.com/suffro/decguard/tree/main/tests/integration/real)
— one `choice`, one `noul` and one `score` decision. Nothing is mocked. These tests are
opt-in: a default `pytest` run skips them, and once selected they fail rather than skip
when the server, checkpoint or credential is missing.

**Kev** (`-m real_kev`), with a Kev server started as [above](#self-hosted-kev):

```bash
DECGUARD_KEV_RUN=jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e \
  uv run pytest -m real_kev
```

`DECGUARD_KEV_RUN` is optional: when set, the test fails unless the server's
`GET /v1/models` reports that checkpoint.

**Jev through OpenRouter** (`-m real_jev`):

```bash
export OPENROUTER_API_KEY=...
uv run pytest -m real_jev
```

This makes three billed Jev calls (about $0.00004 in total at the time of writing) and one
call with a deliberately invalid key, which OpenRouter rejects with HTTP 401 and does not
bill. The tests check that neither key appears in any output, error or report.

**GitHub Actions.** The repository's manual `Real backends` workflow
([`.github/workflows/real-backends.yml`](https://github.com/suffro/decguard/blob/main/.github/workflows/real-backends.yml))
runs both groups on `ubuntu-latest` and `macos-latest` with Python 3.13. It is started
from the Actions tab or by adding the `real-backends` label to a pull request, never on
ordinary commits. Only the Jev test step receives the `OPENROUTER_API_KEY` secret.

**Any other backend** (`-m external`) runs `decguard test` on your own contract, which
must use a non-`mock` backend and produce at least one valid decision:

```bash
DECGUARD_EXTERNAL_CONTRACT=/absolute/path/to/real-decguard.yaml \
  uv run pytest -m external
```
