"""Post-deployment analysis settings in a Decision Contract."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator

from decguard._validation import StrictModel

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegative = Annotated[float, Field(ge=0.0)]


class ProductionGates(StrictModel):
    """Gates for a complete production dataset and its optional baseline."""

    min_accuracy: Probability | None = None
    max_error_rate: Probability | None = None
    max_ece: Probability | None = None
    max_brier: Annotated[float, Field(ge=0.0, le=2.0)] | None = None
    max_nll: NonNegative | None = None
    min_threshold_coverage: Probability | None = None
    max_abstention_rate: Probability | None = None
    max_fallback_rate: Probability | None = None
    max_confidence_tv_distance: Probability | None = None
    max_accuracy_drop: Probability | None = None
    max_ece_increase: Probability | None = None

    def configured(self) -> dict[str, float]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


class SegmentGates(StrictModel):
    """Gates applied independently to every configured metadata segment."""

    min_accuracy: Probability | None = None
    max_error_rate: Probability | None = None
    max_ece: Probability | None = None
    max_brier: Annotated[float, Field(ge=0.0, le=2.0)] | None = None
    max_nll: NonNegative | None = None
    min_threshold_coverage: Probability | None = None
    max_abstention_rate: Probability | None = None
    max_fallback_rate: Probability | None = None

    def configured(self) -> dict[str, float]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


class Production(StrictModel):
    segments: tuple[str, ...] = ()
    requirements: ProductionGates = ProductionGates()
    warnings: ProductionGates = ProductionGates()
    segment_requirements: SegmentGates = SegmentGates()
    segment_warnings: SegmentGates = SegmentGates()

    @field_validator("segments")
    @classmethod
    def _check_segments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not key or key != key.strip() for key in value):
            raise ValueError("segment keys must be non-empty and have no surrounding spaces")
        if len(set(value)) != len(value):
            raise ValueError("segment keys must be unique")
        return value
