"""Compare a decision before and after a transformation, and judge it against a property."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from decguard.contracts.properties import Monotonic, PropertyConfig, Relation
from decguard.decisions import DecisionResult, DecisionType, select_label
from decguard.metrics import distribution


class Comparison(BaseModel):
    """Distribution-aware difference between the original and the transformed decision.

    For ``swapped`` (inversion) properties the transformed distribution is compared with
    its two labels exchanged, so all fields measure distance from the *expected* answer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tv_distance: float
    js_divergence: float
    max_abs_delta: float
    confidence_delta: float
    """Transformed confidence minus original confidence."""
    selected_before: str
    selected_after: str
    flipped: bool
    """The selected label changed (monotonic: the level moved against the direction)."""
    rank_changed: bool
    """The order of labels by probability changed."""
    level_delta: float | None = None
    """Score decisions: expected level after minus before, in scale steps."""


def compare(
    before: DecisionResult,
    after: DecisionResult,
    relation: Relation,
    *,
    direction: str = "increasing",
) -> Comparison:
    labels = before.labels
    p = before.probabilities
    if relation == "swapped":
        first, second = labels
        swap = {first: second, second: first}
        q = {label: after.probabilities[swap[label]] for label in labels}
    else:
        q = dict(after.probabilities)
    selected_after = select_label(labels, q)

    level_delta = None
    if before.decision_type is DecisionType.SCORE:
        level_delta = distribution.expected_level(q, labels) - distribution.expected_level(
            p, labels
        )
    if relation == "monotonic":
        moved = labels.index(selected_after) - labels.index(before.selected)
        flipped = moved < 0 if direction == "increasing" else moved > 0
    else:
        flipped = selected_after != before.selected

    return Comparison(
        tv_distance=distribution.tv_distance(p, q, labels),
        js_divergence=distribution.js_divergence(p, q, labels),
        max_abs_delta=distribution.max_abs_delta(p, q, labels),
        confidence_delta=q[selected_after] - p[before.selected],
        selected_before=before.selected,
        selected_after=selected_after,
        flipped=flipped,
        rank_changed=distribution.ranking(p, labels) != distribution.ranking(q, labels),
        level_delta=level_delta,
    )


@dataclass(frozen=True)
class Verdict:
    tolerance: tuple[str, ...]
    """Per-case tolerances that were exceeded."""
    flip: str | None
    """Set when the answer flipped and the property limits flips."""

    @property
    def violations(self) -> list[str]:
        return [*self.tolerance, *([self.flip] if self.flip else [])]


_VALUES: dict[str, tuple[str, Callable[[Comparison], float]]] = {
    "max_tv_distance": ("tv_distance", lambda c: c.tv_distance),
    "max_js_divergence": ("js_divergence", lambda c: c.js_divergence),
    "max_abs_delta": ("max_abs_delta", lambda c: c.max_abs_delta),
    "max_confidence_delta": ("confidence_delta", lambda c: abs(c.confidence_delta)),
}


def judge(config: PropertyConfig, comparison: Comparison) -> Verdict:
    """Which of the property's per-case limits does this comparison break?"""
    tolerance: list[str] = []
    if isinstance(config, Monotonic):
        assert comparison.level_delta is not None
        sign = 1.0 if config.direction == "increasing" else -1.0
        if sign * comparison.level_delta < -config.max_level_decrease:
            tolerance.append(
                f"expected level moved {comparison.level_delta:+.4g} against "
                f"'{config.direction}' (allowed {config.max_level_decrease:g})"
            )
    else:
        for key, limit in config.tolerances().items():
            metric, value_of = _VALUES[key]
            value = value_of(comparison)
            if value > limit:
                tolerance.append(f"{metric} {value:.4g} > {limit:g}")

    flip = None
    if config.max_flip_rate is not None and comparison.flipped:
        before, after = comparison.selected_before, comparison.selected_after
        if isinstance(config, Monotonic):
            flip = f"selected level moved against '{config.direction}': {before} -> {after}"
        elif config.relation == "swapped":
            flip = f"answer did not invert: {before!r} was selected before and after negation"
        else:
            flip = f"selected label changed: {before!r} -> {after!r}"
    return Verdict(tuple(tolerance), flip)
