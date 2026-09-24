"""The backend adapter interface every decision provider implements."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any, ClassVar, Literal, Self, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from decguard._validation import format_validation_error
from decguard.contracts.models import BackendConfig
from decguard.decisions import (
    DEFAULT_PROBABILITY_TOLERANCE,
    DecisionRequest,
    DecisionResult,
    DecisionSpec,
    Prediction,
    build_result,
)
from decguard.errors import ContractError

SettingsT = TypeVar("SettingsT", bound=BaseModel)


class BackendMetadata(BaseModel):
    """Provenance recorded in every report. Must never contain secrets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    provider: str
    model: str | None = None
    model_version: str | None = None
    details: dict[str, Any] = {}


class HealthStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok", "unhealthy", "unknown"]
    detail: str = ""


class DecisionBackend(ABC):
    """Base class for decision backends.

    Adapters implement :meth:`predict`, returning raw label probabilities. :meth:`decide`
    measures latency and validates/normalizes the prediction the same way for every
    backend, so adapters stay thin and cannot diverge in result semantics.

    Implementations must be safe to call from several threads at once: the runner calls
    :meth:`decide` concurrently (bounded by ``evaluation.max_concurrency``).
    """

    provider: ClassVar[str]

    def __init__(self, *, name: str = "default", model: str | None = None) -> None:
        self.name = name
        self.model = model

    @classmethod
    def from_config(cls, config: BackendConfig, *, name: str, decision: DecisionSpec) -> Self:
        """Build the backend from a contract's ``backend`` section.

        Must validate settings without doing network I/O, so ``decguard validate`` works
        offline. Override in adapters that can be configured from a contract.
        """
        raise ContractError(f"provider {cls.provider!r} cannot be configured from a contract")

    @abstractmethod
    def predict(self, request: DecisionRequest) -> Prediction:
        """Return label probabilities for one request.

        Raise :class:`decguard.errors.BackendError` (or a subclass) for failures that
        concern this request only; they are recorded as errored cases.
        """

    def decide(
        self,
        request: DecisionRequest,
        *,
        tolerance: float = DEFAULT_PROBABILITY_TOLERANCE,
    ) -> DecisionResult:
        start = time.perf_counter()
        prediction = self.predict(request)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return build_result(
            request,
            prediction,
            backend=self.name,
            provider=self.provider,
            model=self.model,
            latency_ms=latency_ms,
            tolerance=tolerance,
        )

    def metadata(self) -> BackendMetadata:
        return BackendMetadata(name=self.name, provider=self.provider, model=self.model)

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(status="unknown", detail="healthcheck not implemented")

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources such as HTTP connection pools."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def validate_settings(model: type[SettingsT], config: BackendConfig, *, name: str) -> SettingsT:
    """Validate provider-specific settings, reporting errors against the contract path."""
    prefix = "backend" if name == "default" else f"backends.{name}"
    try:
        return model.model_validate(config.settings)
    except ValidationError as exc:
        raise ContractError(
            f"invalid settings for provider {config.provider!r}:\n"
            + format_validation_error(exc, prefix=prefix)
        ) from exc
