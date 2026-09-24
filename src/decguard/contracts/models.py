"""Decision Contract schema, version 0.1."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from decguard._validation import StrictModel
from decguard.decisions.types import DecisionSpec, DecisionType
from decguard.errors import ContractError

SCHEMA_VERSION = "0.1"
SUPPORTED_SCHEMA_VERSIONS = (SCHEMA_VERSION,)
DEFAULT_BACKEND = "default"

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegative = Annotated[float, Field(ge=0.0)]


def _check_labels(labels: tuple[str, ...]) -> tuple[str, ...]:
    for label in labels:
        if not label or label != label.strip():
            raise ValueError(f"labels must be non-empty and have no surrounding spaces: {label!r}")
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(f"duplicate labels: {duplicates}")
    return labels


def _int_labels_to_str(value: Any) -> Any:
    # Score levels are commonly written as bare numbers (1..5) in YAML.
    if isinstance(value, list | tuple):
        return [str(v) if isinstance(v, int) and not isinstance(v, bool) else v for v in value]
    return value


class _DecisionBase(StrictModel):
    type: str
    name: str = Field(pattern=NAME_PATTERN)
    description: str | None = None

    def label_order(self) -> tuple[str, ...]:
        raise NotImplementedError

    def spec(self) -> DecisionSpec:
        return DecisionSpec(
            name=self.name,
            type=DecisionType(self.type),
            labels=self.label_order(),
            description=self.description,
        )


class ChoiceDecision(_DecisionBase):
    type: Literal["choice"]
    options: tuple[str, ...] = Field(min_length=2)

    _check = field_validator("options")(_check_labels)

    def label_order(self) -> tuple[str, ...]:
        return self.options


class NoulDecision(_DecisionBase):
    type: Literal["noul"]
    labels: tuple[str, str] = ("yes", "no")
    """Positive label first."""

    _check = field_validator("labels")(_check_labels)

    def label_order(self) -> tuple[str, ...]:
        return self.labels


class ScoreDecision(_DecisionBase):
    type: Literal["score"]
    levels: tuple[str, ...] = Field(min_length=2)
    """Ordered from lowest to highest."""

    _coerce = field_validator("levels", mode="before")(_int_labels_to_str)
    _check = field_validator("levels")(_check_labels)

    def label_order(self) -> tuple[str, ...]:
        return self.levels


Decision = Annotated[ChoiceDecision | NoulDecision | ScoreDecision, Field(discriminator="type")]


class BackendConfig(BaseModel):
    """Which backend to call. Keys besides ``provider`` and ``model`` are provider settings,
    validated by the provider itself (see :mod:`decguard.backends`)."""

    model_config = ConfigDict(extra="allow", frozen=True)

    provider: str = Field(pattern=NAME_PATTERN)
    model: str | None = None

    @property
    def settings(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class Evaluation(StrictModel):
    confidence_threshold: Probability | None = None
    """Decisions below this confidence count as abstentions (coverage metrics)."""
    calibration_bins: int = Field(default=10, ge=1, le=1000)
    probability_tolerance: float = Field(default=1e-3, gt=0.0, le=0.1)
    """How far a backend's probabilities may sum away from 1 before the case is an error."""
    max_concurrency: int = Field(default=4, ge=1, le=256)


class Gates(StrictModel):
    """Thresholds on report metrics. Unset gates are not checked."""

    min_accuracy: Probability | None = None
    min_macro_f1: Probability | None = None
    max_nll: NonNegative | None = None
    max_brier: Annotated[float, Field(ge=0.0, le=2.0)] | None = None
    max_ece: Probability | None = None
    min_coverage: Probability | None = None
    max_abstention_rate: Probability | None = None
    min_selective_accuracy: Probability | None = None
    max_error_rate: Probability | None = None
    max_latency_p95_ms: NonNegative | None = None
    max_ordinal_mae: NonNegative | None = None

    def configured(self) -> dict[str, float]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


_NEEDS_THRESHOLD = ("min_coverage", "max_abstention_rate", "min_selective_accuracy")


class Contract(StrictModel):
    schema_version: str
    decision: Decision
    backend: BackendConfig
    backends: dict[Annotated[str, Field(pattern=NAME_PATTERN)], BackendConfig] = {}
    """Alternative named backends, selectable with ``decguard test --backend NAME``."""
    dataset: str | None = None
    """Golden dataset path, relative to the contract file."""
    evaluation: Evaluation = Evaluation()
    requirements: Gates = Gates()
    """Hard gates: any violation fails the run (exit code 1)."""
    warnings: Gates = Gates()
    """Soft gates: violations turn PASS into WARN."""

    @field_validator("schema_version", mode="before")
    @classmethod
    def _check_schema_version(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError(
                f'must be a string such as "{SCHEMA_VERSION}" (quote it in YAML), got {value!r}'
            )
        if value not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"unsupported schema_version {value!r}; this DecGuard supports "
                + ", ".join(repr(v) for v in SUPPORTED_SCHEMA_VERSIONS)
            )
        return value

    @field_validator("backends")
    @classmethod
    def _check_backend_names(cls, value: dict[str, BackendConfig]) -> dict[str, BackendConfig]:
        if DEFAULT_BACKEND in value:
            raise ValueError(f"{DEFAULT_BACKEND!r} is reserved for the top-level 'backend'")
        return value

    @model_validator(mode="after")
    def _check_gates(self) -> Contract:
        for section in ("requirements", "warnings"):
            gates: Gates = getattr(self, section)
            configured = gates.configured()
            if self.evaluation.confidence_threshold is None:
                needing = [key for key in _NEEDS_THRESHOLD if key in configured]
                if needing:
                    raise ValueError(
                        f"{section}.{needing[0]} needs evaluation.confidence_threshold to be set"
                    )
            if "max_ordinal_mae" in configured and self.decision.type != "score":
                raise ValueError(f"{section}.max_ordinal_mae only applies to score decisions")
        return self

    def spec(self) -> DecisionSpec:
        return self.decision.spec()

    def backend_names(self) -> list[str]:
        return [DEFAULT_BACKEND, *self.backends]

    def backend_config(self, name: str | None = None) -> BackendConfig:
        if name is None or name == DEFAULT_BACKEND:
            return self.backend
        try:
            return self.backends[name]
        except KeyError:
            raise ContractError(
                f"unknown backend {name!r}; the contract defines: {', '.join(self.backend_names())}"
            ) from None
