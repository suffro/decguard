from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from decguard.backends import HttpBackend, HttpSettings, create_backend
from decguard.contracts import BackendConfig
from decguard.decisions import DecisionRequest, DecisionSpec, DecisionType
from decguard.errors import (
    BackendError,
    BackendTimeout,
    BackendUnavailable,
    ContractError,
    InvalidResponse,
)

SPEC = DecisionSpec(name="flag", type=DecisionType.NOUL, labels=("yes", "no"))
REQUEST = DecisionRequest(case_id="c1", decision=SPEC, input="is this ok?")
URL = "https://decide.example.test/v1/decide"
SECRET = "s3cr3t-token-value"

Handler = Callable[[httpx.Request], httpx.Response]


def backend(handler: Handler, **settings: Any) -> HttpBackend:
    return HttpBackend(
        HttpSettings(url=URL, retry_backoff_s=0.0, **settings),
        name="remote",
        model="open-jev-2b",
        transport=httpx.MockTransport(handler),
    )


def ok(body: dict[str, Any]) -> Handler:
    return lambda request: httpx.Response(200, json=body)


def test_request_payload_and_normalized_result() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "probabilities": {"no": 0.3, "yes": 0.7},
                "model": "open-jev-2b",
                "model_version": "2026-09-01",
                "metadata": {"tokens": 12},
            },
        )

    result = backend(handler).decide(REQUEST)
    payload = json.loads(seen[0].content)
    assert payload == {
        "protocol": "decguard.http/0.1",
        "case_id": "c1",
        "model": "open-jev-2b",
        "decision": {"name": "flag", "type": "noul", "labels": ["yes", "no"]},
        "input": "is this ok?",
    }
    assert seen[0].method == "POST"
    assert result.probabilities == {"yes": 0.7, "no": 0.3}
    assert (result.selected, result.model_version, result.provider) == ("yes", "2026-09-01", "http")
    assert result.metadata == {"tokens": 12}


def test_label_map_translates_both_ways() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"probabilities": {"true": 0.1, "false": 0.9}})

    result = backend(handler, label_map={"true": "yes", "false": "no"}).decide(REQUEST)
    assert seen[0]["decision"]["labels"] == ["true", "false"]
    assert result.selected == "no"


def test_label_map_must_target_contract_labels() -> None:
    config = BackendConfig(provider="http", url=URL, label_map={"true": "maybe"})
    with pytest.raises(ContractError, match="not contract labels"):
        create_backend(config, decision=SPEC)


@pytest.mark.parametrize(
    ("response", "error", "message"),
    [
        (httpx.Response(200, text="not json"), InvalidResponse, "invalid JSON"),
        (httpx.Response(200, json={"probs": {}}), InvalidResponse, "no 'probabilities'"),
        (httpx.Response(200, json=["yes"]), InvalidResponse, "no 'probabilities'"),
        (
            httpx.Response(200, text='{"probabilities": {"yes": NaN, "no": 0.5}}'),
            InvalidResponse,
            "not finite",
        ),
        (
            httpx.Response(200, json={"probabilities": {"yes": 0.9, "no": 0.9}}),
            InvalidResponse,
            "sum to 1.8",
        ),
        (
            httpx.Response(200, json={"probabilities": {"yes": 1.0, "no": 0.0}, "model": 3}),
            InvalidResponse,
            "'model' must be a string",
        ),
        (httpx.Response(400, text="bad request"), BackendError, "HTTP 400: bad request"),
        (httpx.Response(503), BackendUnavailable, "HTTP 503"),
        (httpx.Response(302, headers={"Location": "https://evil.test"}), BackendError, "HTTP 302"),
    ],
)
def test_bad_responses_become_typed_case_errors(
    response: httpx.Response, error: type[BackendError], message: str
) -> None:
    with pytest.raises(error, match=message):
        backend(lambda request: response).decide(REQUEST)


def test_timeouts_are_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(BackendTimeout, match="timed out"):
        backend(handler, max_retries=3).decide(REQUEST)
    assert calls == 1


def test_connection_errors_and_503_are_retried() -> None:
    answers: list[Any] = [
        httpx.ConnectError("refused"),
        httpx.Response(503),
        httpx.Response(200, json={"probabilities": {"yes": 0.6, "no": 0.4}}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[no-any-return]

    assert backend(handler, max_retries=2).decide(REQUEST).selected == "yes"
    assert answers == []


def test_connection_error_after_retries_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(BackendUnavailable, match="cannot connect"):
        backend(handler, max_retries=1).decide(REQUEST)


def test_bearer_token_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"probabilities": {"yes": 1.0, "no": 0.0}})

    monkeypatch.setenv("DG_TOKEN", SECRET)
    monkeypatch.setenv("DG_TENANT", "acme")
    http = backend(handler, bearer_token_env="DG_TOKEN", headers_from_env={"X-Tenant": "DG_TENANT"})
    http.decide(REQUEST)
    assert seen[0].headers["Authorization"] == f"Bearer {SECRET}"
    assert seen[0].headers["X-Tenant"] == "acme"
    assert SECRET not in http.metadata().model_dump_json()


def test_missing_credential_env_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DG_TOKEN", raising=False)
    http = backend(ok({"probabilities": {"yes": 1.0, "no": 0.0}}), bearer_token_env="DG_TOKEN")
    with pytest.raises(ContractError, match="environment variable DG_TOKEN is not set"):
        http.decide(REQUEST)


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"url": URL, "headers": {"Authorization": "Bearer x"}}, "looks like a credential"),
        ({"url": URL, "headers": {"X-API-Key": "x"}}, "looks like a credential"),
        ({"url": "https://user:pw@host.test/decide"}, "must not embed credentials"),
        ({"url": "ftp://host.test/decide"}, "http:// or https://"),
        ({"url": "/relative"}, "http:// or https://"),
        ({"url": URL, "timeout_s": 0}, "timeout_s"),
        ({"url": URL, "max_retries": 9}, "max_retries"),
        (
            {"url": URL, "bearer_token_env": "A", "headers_from_env": {"Authorization": "B"}},
            "not both",
        ),
    ],
)
def test_settings_validation(settings: dict[str, Any], message: str) -> None:
    with pytest.raises(ContractError, match=message):
        create_backend(BackendConfig(provider="http", **settings), decision=SPEC)


def test_metadata_redacts_query_string() -> None:
    http = HttpBackend(HttpSettings(url=URL + "?api_key=" + SECRET), model="m")
    details = http.metadata().details
    assert details["url"] == URL
    assert SECRET not in json.dumps(details)


def test_healthcheck() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if request.url.path == "/healthz" else 500)

    assert backend(handler).healthcheck().status == "unknown"
    healthy = backend(handler, health_url="https://decide.example.test/healthz")
    assert healthy.healthcheck().status == "ok"
    sick = backend(handler, health_url="https://decide.example.test/broken")
    assert sick.healthcheck().status == "unhealthy"

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    unreachable = backend(down, health_url="https://decide.example.test/healthz")
    assert unreachable.healthcheck().status == "unhealthy"
