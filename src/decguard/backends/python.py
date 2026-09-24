"""Wrap a plain Python function as a backend (SDK use, not configurable from contracts)."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from decguard.backends.base import DecisionBackend
from decguard.decisions import DecisionRequest, Prediction

DecideFn = Callable[[DecisionRequest], Mapping[str, float] | Prediction]


class CallableBackend(DecisionBackend):
    """Backend backed by ``fn(request) -> {label: probability}`` (or a ``Prediction``).

    Contracts cannot reference arbitrary Python code; to use a Python provider from the CLI,
    package it as a ``decguard.backends`` entry point (see docs/backends.md).
    """

    provider = "python"

    def __init__(self, fn: DecideFn, *, name: str = "python", model: str | None = None) -> None:
        super().__init__(name=name, model=model)
        self._fn = fn

    def predict(self, request: DecisionRequest) -> Prediction:
        answer = self._fn(request)
        if isinstance(answer, Prediction):
            return answer
        return Prediction(probabilities=answer)
