---
description: The generic http backend, its settings, and the decguard.http/0.1 JSON protocol for connecting any decision endpoint.
---

# Generic HTTP

The `http` backend calls any endpoint that speaks DecGuard's small JSON protocol,
`decguard.http/0.1`: one `POST` per decision, returning a probability per label. Use it
for your own model servers, or put a thin proxy in front of an endpoint with a different
shape. (System One APIs such as Kev and Jev have their own
[built-in backend](./systemone.md).)

```yaml
backend:
  provider: http
  url: https://decisions.internal/v1/decide
  health_url: https://decisions.internal/healthz
  model: refund-v3
  timeout_s: 30
  max_retries: 2
  bearer_token_env: DECISIONS_TOKEN
```

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `url` | required | absolute `http://` or `https://` decision endpoint |
| `model` | none | sent as `model` in every request |
| `health_url` | none | optional `GET` endpoint; any 2xx answer means healthy |
| `timeout_s` | `30` | per-request timeout in seconds (up to 600) |
| `max_retries` | `0` | retries (0–5) for connection failures and HTTP 502/503/504 only |
| `retry_backoff_s` | `0.5` | wait before the first retry, doubled after each one |
| `bearer_token_env` | none | environment variable sent as `Authorization: Bearer <value>` |
| `headers_from_env` | `{}` | header name → environment variable holding its value |
| `headers` | `{}` | static, **non-secret** headers |
| `label_map` | `{}` | backend label → contract label, for endpoints that name labels differently |

```yaml
backend:
  provider: http
  url: https://decisions.internal/v1/decide
  headers_from_env: {X-Tenant: DECISIONS_TENANT}
  headers: {X-Client: decguard}
  label_map: {"true": "yes", "false": "no"}
```

Security rules:

- Credentials come from environment variables only. Literal `Authorization`, `X-Api-Key`
  or `Api-Key` headers, credentials in the URL, and credential-like query parameters are
  rejected when the contract is loaded. Set either `bearer_token_env` or an
  `Authorization` entry in `headers_from_env`, not both.
- When environment-backed headers are configured, `health_url` must have the same origin
  as `url`, so a healthcheck cannot forward credentials elsewhere.
- Redirects are not followed. Retries happen only when the request never reached the
  server (connection failures) or the server answered 502/503/504.
- HTTP error bodies are not recorded (they are untrusted and can echo private input), and
  reports store the URL without its query string.

## Protocol `decguard.http/0.1`

### Request

```http
POST /v1/decide
Content-Type: application/json
```

```json
{
  "protocol": "decguard.http/0.1",
  "case_id": "r1",
  "model": "refund-v3",
  "decision": {"name": "refund_request", "type": "choice", "labels": ["refund", "reject", "review"]},
  "input": "The blender arrived damaged."
}
```

| Field | Meaning |
| --- | --- |
| `protocol` | always `decguard.http/0.1` |
| `case_id` | dataset case id, or the id given to `run` / the SDK |
| `model` | the backend's `model` setting, or `null` |
| `decision.name`, `decision.type` | from the contract |
| `decision.labels` | the labels to present, in order, in the backend's names (after `label_map`) |
| `input` | the case input: a string or a JSON object |

`decision.labels` is not always the contract order. During fuzzing, `option_order` and
`label_format` reorder or reformat them (`["review", "refund", "reject"]`,
`["REFUND", "REJECT", "REVIEW"]`, ...). Present them to the model as given, and key the
answer by the labels **exactly as sent**; DecGuard maps them back to the contract labels.

### Response

```json
{
  "probabilities": {"refund": 0.91, "reject": 0.02, "review": 0.07},
  "model": "refund-v3",
  "model_version": "2026-09-01",
  "metadata": {"tokens": 41}
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `probabilities` | yes | one probability per label sent: finite, non-negative, summing to 1 within `evaluation.probability_tolerance` |
| `model` | no | the model that answered (string) |
| `model_version` | no | its version (string) |
| `metadata` | no | an object stored with the result; common credential keys are redacted |

Status handling:

| Answer | Result for the case |
| --- | --- |
| `200` with a valid body | a `DecisionResult` |
| `200` with invalid JSON, missing or malformed `probabilities` | `invalid_response` |
| `502`, `503`, `504` (after retries) or connection failure | `unavailable` |
| any other non-2xx status | `backend_error` |
| no answer within `timeout_s` | `timeout` |

## A minimal endpoint

A complete endpoint using only the Python standard library. Replace `my_model` with a
call to your model:

```python
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def my_model(text, options):
    """Replace with your model: one probability per option, keyed exactly as given."""
    return {option: 1 / len(options) for option in options}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        labels = request["decision"]["labels"]  # in the order and form to present
        body = json.dumps(
            {
                "probabilities": my_model(request["input"], labels),
                "model": "refund-rules",
                "model_version": "2026-09-01",
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
```

```yaml
backend:
  provider: http
  url: http://127.0.0.1:8080/decide
  model: refund-rules
```

If your model runs in the same Python process as DecGuard, you can skip HTTP entirely with
a [custom backend](./custom-backends.md).
