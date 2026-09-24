"""Wire translation and normalization of the System One backend (Jev, Kev, OpenRouter).

These use an in-memory transport; tests/integration/test_real_backends.py runs the same
backend against the real services.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from decguard.backends import (
    SystemOneBackend,
    SystemOneSettings,
    available_providers,
    create_backend,
)
from decguard.contracts import BackendConfig
from decguard.decisions import DecisionRequest, DecisionSpec, DecisionType
from decguard.errors import BackendError, BackendUnavailable, ContractError, InvalidResponse

URL = "https://openrouter.test/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
SERVED = "typesafe/jev-1.13-20260917"
SECRET = "sk-or-v1-s3cr3t-token-value"

CHOICE = DecisionSpec(
    name="team",
    type=DecisionType.CHOICE,
    labels=("billing", "shipping", "technical"),
    description="Which team should handle this ticket?",
)
NOUL = DecisionSpec(
    name="urgent", type=DecisionType.NOUL, labels=("yes", "no"), description="Is it urgent?"
)
SCORE = DecisionSpec(
    name="frustration",
    type=DecisionType.SCORE,
    labels=("calm", "frustrated", "very angry"),
    description="How frustrated is the customer?",
)

Handler = Callable[[httpx.Request], httpx.Response]


def backend(spec: DecisionSpec, handler: Handler, **settings: Any) -> SystemOneBackend:
    return SystemOneBackend(
        SystemOneSettings(url=URL, retry_backoff_s=0.0, **settings),
        decision=spec,
        name="jev",
        model=MODEL,
        transport=httpx.MockTransport(handler),
    )


def envelope(name: str, answer: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "id": "gen-dec-1",
        "model": SERVED,
        "provider": "TypeSafe",
        "answers": {name: answer},
        "usage": {"input_tokens": 476, "output_tokens": 70, "cost": 0.00002},
        **extra,
    }


def answering(
    name: str, answer: dict[str, Any], seen: list[dict[str, Any]] | None = None
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json=envelope(name, answer))

    return handler


def ask(spec: DecisionSpec, shown: tuple[str, ...] | None = None) -> DecisionRequest:
    decision = spec if shown is None else spec.model_copy(update={"labels": shown})
    return DecisionRequest(case_id="c1", decision=decision, input="I was charged twice.")


def test_choice_request_and_normalized_result() -> None:
    seen: list[dict[str, Any]] = []
    answer = {
        "type": "choice",
        "choice": "billing",
        "confidence": 0.67,
        "probabilities": {"technical": 0.0, "billing": 0.78, "shipping": 0.22},
    }
    instance = backend(CHOICE, answering("team", answer, seen))
    result = instance.decide(ask(CHOICE), tolerance=0.02)
    assert seen == [
        {
            "model": MODEL,
            "state": "I was charged twice.",
            "questions": {
                "team": {
                    "type": "choice",
                    "instructions": "Which team should handle this ticket?",
                    "criteria": {"billing": None, "shipping": None, "technical": None},
                }
            },
        }
    ]
    assert result.probabilities == {"billing": 0.78, "shipping": 0.22, "technical": 0.0}
    assert list(result.probabilities) == list(CHOICE.labels)
    assert (result.selected, result.confidence) == ("billing", 0.78)  # not the provider's 0.67
    assert (result.provider, result.model, result.model_version) == ("systemone", MODEL, SERVED)
    assert result.metadata == {
        "request_id": "gen-dec-1",
        "upstream_provider": "TypeSafe",
        "usage": {"input_tokens": 476, "output_tokens": 70, "cost": 0.00002},
    }
    metadata = instance.metadata()
    assert (metadata.provider, metadata.model, metadata.model_version) == (
        "systemone",
        MODEL,
        SERVED,
    )
    assert metadata.details == {
        "url": URL,
        "protocol": "typesafe.systemone/v1",
        "served_models": [SERVED],
        "upstream_providers": ["TypeSafe"],
    }


def test_choice_follows_the_order_and_form_shown() -> None:
    seen: list[dict[str, Any]] = []
    shown = ("technical", "billing", "shipping")
    answer = {
        "type": "choice",
        "choice": "billing",
        "probabilities": {"technical": 0.1, "billing": 0.6, "shipping": 0.3},
    }
    result = backend(CHOICE, answering("team", answer, seen)).decide(ask(CHOICE, shown))
    assert list(seen[0]["questions"]["team"]["criteria"]) == list(shown)
    assert result.probabilities == {"technical": 0.1, "billing": 0.6, "shipping": 0.3}


def test_choice_label_map_translates_both_ways() -> None:
    seen: list[dict[str, Any]] = []
    answer = {
        "type": "choice",
        "choice": "payments",
        "probabilities": {"payments": 0.7, "delivery": 0.2, "bugs": 0.1},
    }
    label_map = {"payments": "billing", "delivery": "shipping", "bugs": "technical"}
    instance = backend(CHOICE, answering("team", answer, seen), label_map=label_map)
    result = instance.decide(ask(CHOICE))
    assert list(seen[0]["questions"]["team"]["criteria"]) == ["payments", "delivery", "bugs"]
    assert result.probabilities == {"billing": 0.7, "shipping": 0.2, "technical": 0.1}


def test_noul_probability_of_yes_maps_to_the_positive_label() -> None:
    seen: list[dict[str, Any]] = []
    instance = backend(NOUL, answering("urgent", {"type": "noul", "noul": 0.96}, seen))
    result = instance.decide(ask(NOUL))
    assert seen[0]["questions"] == {"urgent": {"type": "noul", "instructions": "Is it urgent?"}}
    assert result.probabilities == pytest.approx({"yes": 0.96, "no": 0.04})
    assert result.selected == "yes"


@pytest.mark.parametrize(
    ("shown", "expected"),
    [
        (("no", "yes"), {"no": 0.2, "yes": 0.8}),  # option_order: mapped by name
        (("YES", "NO"), {"YES": 0.8, "NO": 0.2}),  # label_format: contract order kept
    ],
)
def test_noul_under_fuzzed_presentation(shown: tuple[str, str], expected: dict[str, float]) -> None:
    instance = backend(NOUL, answering("urgent", {"type": "noul", "noul": 0.8}))
    result = instance.decide(ask(NOUL, shown))
    assert result.probabilities == pytest.approx(expected)


def test_score_levels_are_ordered_criteria_and_indices_map_back() -> None:
    seen: list[dict[str, Any]] = []
    answer = {
        "type": "score",
        "score": 1.99,
        "confidence": 0.99,
        "legend": {"0": "calm", "1": "frustrated", "2": "very angry"},
        "probabilities": {"0": 0.0, "1": 0.01, "2": 0.99},
    }
    result = backend(SCORE, answering("frustration", answer, seen)).decide(ask(SCORE))
    question = seen[0]["questions"]["frustration"]
    assert question["criteria"] == ["calm", "frustrated", "very angry"]
    assert result.probabilities == {"calm": 0.0, "frustrated": 0.01, "very angry": 0.99}
    assert result.selected == "very angry"


def test_instructions_setting_overrides_the_description() -> None:
    seen: list[dict[str, Any]] = []
    handler = answering("urgent", {"type": "noul", "noul": 0.5}, seen)
    backend(NOUL, handler, instructions="Must a human act today?").decide(ask(NOUL))
    assert seen[0]["questions"]["urgent"]["instructions"] == "Must a human act today?"


def test_kev_style_response_uses_the_request_id_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "model": "kev-latest",
            "answers": {"urgent": {"type": "noul", "noul": 0.864}},
            "usage": {"input_tokens": 61, "output_tokens": 20},
            "latency_ms": 2491.5,
        }
        return httpx.Response(200, json=body, headers={"x-typesafe-request-id": "fd24"})

    result = backend(NOUL, handler).decide(ask(NOUL))
    assert result.model_version == "kev-latest"
    assert result.metadata == {
        "request_id": "fd24",
        "usage": {"input_tokens": 61, "output_tokens": 20},
    }


CHOICE_OK = {
    "type": "choice",
    "choice": "billing",
    "probabilities": {"billing": 0.5, "shipping": 0.3, "technical": 0.2},
}


@pytest.mark.parametrize(
    ("spec", "body", "message"),
    [
        (CHOICE, {"model": SERVED}, "no 'answers' object"),
        (CHOICE, {"model": SERVED, "answers": {}}, "exactly the question 'team'"),
        (
            CHOICE,
            {"model": SERVED, "answers": {"team": CHOICE_OK, "other": CHOICE_OK}},
            "exactly the question 'team'",
        ),
        (CHOICE, {"answers": {"team": CHOICE_OK}}, "'model' must be a non-empty string"),
        (CHOICE, envelope("team", {**CHOICE_OK, "type": "score"}), "expected a choice answer"),
        (CHOICE, envelope("team", {"type": "choice", "choice": "billing"}), "no 'probabilities'"),
        (CHOICE, envelope("team", {**CHOICE_OK, "choice": "sales"}), "not one of the options"),
        (CHOICE, envelope("team", {**CHOICE_OK, "choice": "shipping"}), "not the most probable"),
        (
            CHOICE,
            envelope(
                "team",
                {**CHOICE_OK, "probabilities": {"billing": 0.9, "shipping": 0.3, "technical": 0.2}},
            ),
            "sum to 1.4",
        ),
        (
            CHOICE,
            envelope("team", {**CHOICE_OK, "probabilities": {"billing": 0.6, "shipping": 0.4}}),
            "missing labels \\['technical'\\]",
        ),
        (NOUL, envelope("urgent", {"type": "noul", "noul": 1.2}), "probability in \\[0, 1\\]"),
        (NOUL, envelope("urgent", {"type": "noul", "noul": True}), "probability in \\[0, 1\\]"),
        (NOUL, envelope("urgent", {"type": "noul"}), "probability in \\[0, 1\\]"),
        (
            SCORE,
            envelope(
                "frustration",
                {"type": "score", "probabilities": {"0": 0.2, "01": 0.3, "2": 0.5}},
            ),
            "'01' is not a level index",
        ),
        (
            SCORE,
            envelope(
                "frustration",
                {"type": "score", "probabilities": {"0": 0.2, "1": 0.3, "3": 0.5}},
            ),
            "'3' is not a level index",
        ),
        (
            SCORE,
            envelope(
                "frustration",
                {
                    "type": "score",
                    "legend": {"0": "very angry", "1": "frustrated", "2": "calm"},
                    "probabilities": {"0": 0.2, "1": 0.3, "2": 0.5},
                },
            ),
            "legend does not match",
        ),
    ],
)
def test_malformed_answers_are_invalid_responses(
    spec: DecisionSpec, body: dict[str, Any], message: str
) -> None:
    instance = backend(spec, lambda request: httpx.Response(200, json=body))
    with pytest.raises(InvalidResponse, match=message):
        instance.decide(ask(spec))


def test_non_json_is_an_invalid_response() -> None:
    instance = backend(NOUL, lambda request: httpx.Response(200, text="<html>"))
    with pytest.raises(InvalidResponse, match="invalid JSON"):
        instance.decide(ask(NOUL))


def test_credentials_come_from_the_environment_and_never_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(401, json={"error": {"code": 401, "message": f"bad key {SECRET}"}})

    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    instance = backend(NOUL, handler, bearer_token_env="OPENROUTER_API_KEY")
    with pytest.raises(BackendError, match="HTTP 401") as caught:
        instance.decide(ask(NOUL))
    assert seen[0].headers["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in str(caught.value)
    assert SECRET not in instance.metadata().model_dump_json()


def test_missing_credential_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    instance = backend(
        NOUL,
        answering("urgent", {"type": "noul", "noul": 0.5}),
        bearer_token_env="OPENROUTER_API_KEY",
    )
    with pytest.raises(ContractError, match="OPENROUTER_API_KEY is not set"):
        instance.decide(ask(NOUL))


def test_rate_limits_and_overload_are_retried() -> None:
    statuses = [429, 529]

    def handler(request: httpx.Request) -> httpx.Response:
        if statuses:
            return httpx.Response(statuses.pop(0))
        return httpx.Response(200, json=envelope("urgent", {"type": "noul", "noul": 0.7}))

    result = backend(NOUL, handler, max_retries=2).decide(ask(NOUL))
    assert result.selected == "yes"
    with pytest.raises(BackendUnavailable, match="HTTP 529"):
        backend(NOUL, lambda request: httpx.Response(529), max_retries=1).decide(ask(NOUL))


@pytest.mark.parametrize(
    ("spec", "settings", "message"),
    [
        (CHOICE, {"model": None}, "'model' is required"),
        (
            CHOICE.model_copy(update={"description": None}),
            {},
            "set decision.description or the backend's 'instructions'",
        ),
        (NOUL, {"label_map": {"true": "yes"}}, "label_map does not apply to noul"),
        (CHOICE, {"label_map": {"pay": "sales"}}, "not contract labels"),
        (CHOICE, {"label_map": {"a": "billing", "b": "billing"}}, "maps two labels to one"),
        (CHOICE, {"url": "https://user:pw@openrouter.test/x"}, "must not embed credentials"),
    ],
)
def test_configuration_is_validated_offline(
    spec: DecisionSpec, settings: dict[str, Any], message: str
) -> None:
    config = BackendConfig(**{"provider": "systemone", "model": MODEL, "url": URL, **settings})
    with pytest.raises(ContractError, match=message):
        create_backend(config, decision=spec)


def test_systemone_is_a_builtin_provider() -> None:
    assert "systemone" in available_providers()
