"""Deterministic offline backend for tests, examples and CI."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Self

from pydantic import Field

from decguard._validation import StrictModel
from decguard.backends.base import BackendMetadata, DecisionBackend, HealthStatus, validate_settings
from decguard.contracts.models import BackendConfig
from decguard.decisions import (
    DecisionInput,
    DecisionRequest,
    DecisionSpec,
    Prediction,
    validate_probabilities,
)
from decguard.errors import ContractError, InvalidResponse


class MockRule(StrictModel):
    contains: str = Field(min_length=1)
    """Case-insensitive substring of the input (objects are matched on their JSON form)."""
    probabilities: dict[str, float]


class MockSettings(StrictModel):
    rules: tuple[MockRule, ...] = ()
    """Checked in order; the first matching rule answers."""
    default: dict[str, float] | None = None
    """Answer when no rule matches. Without it, a seeded hash of the input decides."""
    seed: int = 0
    model_version: str | None = None


def input_text(value: DecisionInput) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def hashed_distribution(text: str, labels: tuple[str, ...], seed: int) -> dict[str, float]:
    """A fixed pseudo-random distribution per (seed, input): stable across processes."""
    weights = []
    for label in labels:
        digest = hashlib.sha256(f"{seed}\x1f{text}\x1f{label}".encode()).digest()
        weights.append(int.from_bytes(digest[:8], "big") / 2**64 + 1e-3)
    total = math.fsum(weights)
    return {label: weight / total for label, weight in zip(labels, weights, strict=True)}


class MockBackend(DecisionBackend):
    """Answers from substring rules, a default distribution, or a seeded hash."""

    provider = "mock"

    def __init__(
        self,
        settings: MockSettings | None = None,
        *,
        name: str = "default",
        model: str | None = "mock",
    ) -> None:
        super().__init__(name=name, model=model)
        self.settings = settings or MockSettings()

    @classmethod
    def from_config(cls, config: BackendConfig, *, name: str, decision: DecisionSpec) -> Self:
        settings = validate_settings(MockSettings, config, name=name)
        answers = [(f"rules[{i}]", rule.probabilities) for i, rule in enumerate(settings.rules)]
        if settings.default is not None:
            answers.append(("default", settings.default))
        for where, probabilities in answers:
            try:
                validate_probabilities(decision.labels, probabilities)
            except InvalidResponse as exc:
                raise ContractError(f"mock backend {name!r}: {where}: {exc}") from exc
        return cls(settings, name=name, model=config.model or "mock")

    def predict(self, request: DecisionRequest) -> Prediction:
        text = input_text(request.input)
        lowered = text.lower()
        for rule in self.settings.rules:
            if rule.contains.lower() in lowered:
                return self._prediction(rule.probabilities)
        if self.settings.default is not None:
            return self._prediction(self.settings.default)
        labels = request.decision.labels
        return self._prediction(hashed_distribution(text, labels, self.settings.seed))

    def _prediction(self, probabilities: dict[str, float]) -> Prediction:
        return Prediction(probabilities=probabilities, model_version=self.settings.model_version)

    def metadata(self) -> BackendMetadata:
        return BackendMetadata(
            name=self.name,
            provider=self.provider,
            model=self.model,
            model_version=self.settings.model_version,
            details={"rules": len(self.settings.rules), "seed": self.settings.seed},
        )

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(status="ok", detail="mock backend")
