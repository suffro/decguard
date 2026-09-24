"""Deterministic offline backend for tests, examples and CI."""

from __future__ import annotations

import hashlib
import json
import math
import re
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
    """Substring of the input, ignoring case and whitespace differences (objects are
    matched on their JSON form)."""
    probabilities: dict[str, float]


class MockSettings(StrictModel):
    rules: tuple[MockRule, ...] = ()
    """Checked in order; the first matching rule answers."""
    default: dict[str, float] | None = None
    """Answer when no rule matches. Without it, a seeded hash of the input decides."""
    seed: int = 0
    model_version: str | None = None
    position_bias: float = Field(default=0.0, ge=0.0, le=1.0)
    """Deliberate defect for demos and tests: move this share of probability mass to the
    option shown first, making the backend sensitive to option order."""


def input_text(value: DecisionInput) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


_ENUMERATOR = re.compile(r"^(?:[A-Za-z]|\d{1,3})[).:]\s+")


def semantic_label(shown: str) -> str:
    """The label behind a surface form: ``"B) Refund"``, ``'"refund"'``, ``"REFUND"`` and
    ``"[refund]"`` all mean ``refund``. Used by the mock to read transformed options."""
    text = _ENUMERATOR.sub("", shown.strip())
    return text.strip("\"'[]").strip().casefold()


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
        shown = request.decision.labels
        normalized = _normalize(text)
        answer = None
        for rule in self.settings.rules:
            if _normalize(rule.contains) in normalized:
                answer = rule.probabilities
                break
        else:
            answer = self.settings.default
        if answer is None:
            # Hash the meaning of each label, so reformatted options get the same answer.
            meanings = tuple(semantic_label(label) for label in shown)
            if len(set(meanings)) != len(meanings):
                meanings = shown
            hashed = hashed_distribution(text, meanings, self.settings.seed)
            probabilities = {label: hashed[m] for label, m in zip(shown, meanings, strict=True)}
        else:
            probabilities = self._map_labels(answer, shown)
        return Prediction(
            probabilities=self._bias(probabilities, shown),
            model_version=self.settings.model_version,
        )

    @staticmethod
    def _map_labels(answer: dict[str, float], shown: tuple[str, ...]) -> dict[str, float]:
        """Key a configured answer by the labels as shown in the request."""
        if set(answer) == set(shown):
            return dict(answer)
        by_meaning: dict[str, str] = {}
        for label in answer:
            by_meaning.setdefault(semantic_label(label), label)
        mapped: dict[str, float] = {}
        used: set[str] = set()
        for label in shown:
            source = label if label in answer else by_meaning.get(semantic_label(label))
            if source is None or source in used:
                return dict(answer)  # cannot map: answer as configured, validation reports it
            used.add(source)
            mapped[label] = answer[source]
        return mapped

    def _bias(self, probabilities: dict[str, float], shown: tuple[str, ...]) -> dict[str, float]:
        bias = self.settings.position_bias
        if not bias or not shown or shown[0] not in probabilities:
            return probabilities
        return {
            label: (1.0 - bias) * p + (bias if label == shown[0] else 0.0)
            for label, p in probabilities.items()
        }

    def metadata(self) -> BackendMetadata:
        return BackendMetadata(
            name=self.name,
            provider=self.provider,
            model=self.model,
            model_version=self.settings.model_version,
            details={
                "rules": len(self.settings.rules),
                "seed": self.settings.seed,
                **(
                    {"position_bias": self.settings.position_bias}
                    if self.settings.position_bias
                    else {}
                ),
            },
        )

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(status="ok", detail="mock backend")
