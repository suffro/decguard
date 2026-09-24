"""Backend for System One decision APIs: TypeSafe's Jev (directly or through OpenRouter's
Decisions API) and self-hosted Kev servers.

Each DecGuard decision is sent as one typed question about the case input::

    POST <url>                      # .../v1/systemone, or OpenRouter's /api/alpha/decisions
    {"model": "...", "state": <input>,
     "questions": {"<decision name>": {"type": "choice" | "noul" | "score",
                                       "instructions": "...", "criteria": ...}}}

    200 OK
    {"model": "<model that answered>", "answers": {"<decision name>": {...}}, "usage": {...}}

Translation, with labels in the order shown (fuzzing may reorder or reformat them):

* choice: the labels are the ``criteria`` option names (descriptions ``null``); the
  answer's ``probabilities`` are keyed by option.
* noul: no labels are sent; the answer's ``noul`` is the probability of the positive
  (first) contract label, and its complement that of the negative one.
* score: the labels are the ordered ``criteria`` levels, lowest first; the answer's
  ``probabilities`` are keyed by level index (``"0"`` = lowest).

Answers are checked, never repaired: the answer must match the question's type, a choice
must be the most probable option sent, and a score legend must echo the levels sent.
The provider's own ``confidence`` is not DecGuard's: DecGuard derives confidence from the
probabilities like for every backend.
"""

from __future__ import annotations

import math
import threading
from typing import Any, Self, TypeGuard

import httpx

from decguard.backends.base import BackendMetadata, validate_settings
from decguard.backends.http import HttpBackend, HttpSettings
from decguard.contracts.models import BackendConfig
from decguard.decisions import DecisionRequest, DecisionSpec, DecisionType, Prediction
from decguard.errors import ContractError, InvalidResponse

PROTOCOL = "typesafe.systemone/v1"
_USAGE_KEYS = ("input_tokens", "output_tokens", "cost")


class SystemOneSettings(HttpSettings):
    instructions: str | None = None
    """The question asked about every input; defaults to the contract's
    ``decision.description``."""


def _is_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


class SystemOneBackend(HttpBackend):
    provider = "systemone"
    protocol = PROTOCOL
    # TypeSafe and OpenRouter ask clients to retry rate limits (429) and overload (529).
    retryable_status = HttpBackend.retryable_status | {429, 529}

    def __init__(
        self,
        settings: SystemOneSettings,
        *,
        decision: DecisionSpec,
        name: str = "default",
        model: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(settings, name=name, model=model, transport=transport)
        instructions = settings.instructions or decision.description
        if not instructions:
            raise ContractError(
                f"systemone backend {name!r}: set decision.description or the backend's "
                "'instructions' (the question asked about every input)"
            )
        self.instructions = instructions
        self.decision = decision
        self._served: set[str] = set()
        self._upstream: set[str] = set()
        self._seen_lock = threading.Lock()

    @classmethod
    def from_config(cls, config: BackendConfig, *, name: str, decision: DecisionSpec) -> Self:
        settings = validate_settings(SystemOneSettings, config, name=name)
        if not config.model:
            raise ContractError(f"systemone backend {name!r}: 'model' is required")
        if settings.label_map:
            if decision.type is DecisionType.NOUL:
                raise ContractError(
                    f"systemone backend {name!r}: label_map does not apply to noul decisions "
                    "(no labels are sent)"
                )
            unknown = sorted(set(settings.label_map.values()) - set(decision.labels))
            if unknown:
                raise ContractError(
                    f"systemone backend {name!r}: label_map targets {unknown} are not "
                    "contract labels"
                )
            if len(set(settings.label_map.values())) != len(settings.label_map):
                raise ContractError(f"systemone backend {name!r}: label_map maps two labels to one")
        return cls(settings, decision=decision, name=name, model=config.model)

    def predict(self, request: DecisionRequest) -> Prediction:
        spec = request.decision
        # Labels as shown (possibly reordered/reformatted), in the backend's names.
        sent = [self._reverse_labels.get(label, label) for label in spec.labels]
        question: dict[str, Any] = {"type": spec.type.value, "instructions": self.instructions}
        if spec.type is DecisionType.CHOICE:
            question["criteria"] = dict.fromkeys(sent)
        elif spec.type is DecisionType.SCORE:
            question["criteria"] = sent
        payload = {"model": self.model, "state": request.input, "questions": {spec.name: question}}
        response = self._post(payload)
        body = self._json(response)
        if not isinstance(body, dict) or not isinstance(body.get("answers"), dict):
            raise InvalidResponse(f"backend {self.name!r} response has no 'answers' object")
        if set(body["answers"]) != {spec.name}:
            raise InvalidResponse(
                f"backend {self.name!r} must answer exactly the question {spec.name!r}, "
                f"got {sorted(map(str, body['answers']))}"
            )
        answer = body["answers"][spec.name]
        if not isinstance(answer, dict) or answer.get("type") != spec.type.value:
            got = answer.get("type") if isinstance(answer, dict) else type(answer).__name__
            raise InvalidResponse(f"expected a {spec.type.value} answer, got {got!r}")
        served = body.get("model")
        if not isinstance(served, str) or not served:
            raise InvalidResponse("'model' must be a non-empty string")

        if spec.type is DecisionType.CHOICE:
            probabilities = self._choice(answer, sent)
        elif spec.type is DecisionType.NOUL:
            probabilities = self._noul(answer, spec.labels)
        else:
            probabilities = self._score(answer, spec.labels, sent)
        return Prediction(
            probabilities=probabilities,
            model_version=served,
            metadata=self._provenance(body, response, served),
        )

    def _choice(self, answer: dict[str, Any], sent: list[str]) -> dict[str, Any]:
        raw = answer.get("probabilities")
        if not isinstance(raw, dict):
            raise InvalidResponse("choice answer has no 'probabilities' object")
        choice = answer.get("choice")
        if not isinstance(choice, str) or choice not in sent or choice not in raw:
            raise InvalidResponse(f"choice {choice!r} is not one of the options sent")
        if all(map(_is_number, raw.values())) and raw[choice] < max(raw.values()):
            raise InvalidResponse(f"choice {choice!r} is not the most probable option")
        probabilities: dict[str, Any] = {}
        for option, value in raw.items():
            label = self.settings.label_map.get(str(option), str(option))
            if label in probabilities:
                raise InvalidResponse(f"backend {self.name!r} returned label {label!r} twice")
            probabilities[label] = value
        return probabilities

    def _noul(self, answer: dict[str, Any], shown: tuple[str, ...]) -> dict[str, Any]:
        value = answer.get("noul")
        if not _is_number(value) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise InvalidResponse(f"noul answer must be a probability in [0, 1], got {value!r}")
        positive, negative = self.decision.labels
        if set(shown) != {positive, negative}:
            # Reformatted labels (label_format) keep the contract order: positive first.
            positive, negative = shown
        return {positive: float(value), negative: 1.0 - float(value)}

    def _score(
        self, answer: dict[str, Any], shown: tuple[str, ...], sent: list[str]
    ) -> dict[str, Any]:
        raw = answer.get("probabilities")
        if not isinstance(raw, dict):
            raise InvalidResponse("score answer has no 'probabilities' object")
        legend = answer.get("legend")
        if legend is not None and legend != {str(i): level for i, level in enumerate(sent)}:
            raise InvalidResponse("score legend does not match the levels sent")
        probabilities: dict[str, Any] = {}
        for key, value in raw.items():
            index = int(key) if isinstance(key, str) and key.isdecimal() else -1
            if str(index) != key or index >= len(shown):
                raise InvalidResponse(f"score probabilities key {key!r} is not a level index")
            probabilities[shown[index]] = value
        return probabilities

    def _provenance(
        self, body: dict[str, Any], response: httpx.Response, served: str
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        request_id = body.get("id") or response.headers.get("x-typesafe-request-id")
        if isinstance(request_id, str):
            metadata["request_id"] = request_id
        upstream = body.get("provider")
        if isinstance(upstream, str):
            metadata["upstream_provider"] = upstream
        usage = body.get("usage")
        if isinstance(usage, dict):
            metadata["usage"] = {k: usage[k] for k in _USAGE_KEYS if _is_number(usage.get(k))}
        with self._seen_lock:
            self._served.add(served)
            if isinstance(upstream, str):
                self._upstream.add(upstream)
        return metadata

    def metadata(self) -> BackendMetadata:
        """Provenance, including the model IDs that actually answered during the run."""
        base = super().metadata()
        with self._seen_lock:
            served, upstream = sorted(self._served), sorted(self._upstream)
        details = dict(base.details)
        if served:
            details["served_models"] = served
        if upstream:
            details["upstream_providers"] = upstream
        return BackendMetadata(
            name=base.name,
            provider=base.provider,
            model=base.model,
            model_version=served[0] if len(served) == 1 else None,
            details=details,
        )
