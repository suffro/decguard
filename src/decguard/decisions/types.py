"""Provider-independent description of a decision."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DecisionType(StrEnum):
    CHOICE = "choice"
    """Pick one of several unordered options."""
    NOUL = "noul"
    """Boolean decision with exactly two labels (positive first)."""
    SCORE = "score"
    """Ordered categorical scale, lowest level first."""


class DecisionSpec(BaseModel):
    """The normalized decision a contract describes.

    ``labels`` is the canonical label order: probabilities, reports and tie-breaking all
    follow it, whatever order a backend used.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type: DecisionType
    labels: tuple[str, ...]
    description: str | None = None
