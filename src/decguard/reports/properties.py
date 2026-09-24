"""The ``properties`` section of a report: every transformed case, per-property summaries
and the checks derived from them."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from decguard.contracts.properties import Fuzz, Properties, PropertyConfig, PropertyName
from decguard.decisions import DecisionInput, DecisionResult
from decguard.fuzz.compare import Comparison, compare, judge
from decguard.metrics.core import mean
from decguard.reports.gates import Check, make_check
from decguard.runner import CaseError, CaseRecord

ORIGINAL_ERROR = "original_error"
"""Error kind of a transformed case whose original case could not be decided."""

Presentation = tuple[tuple[str, str], ...]


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReducedExample(_Section):
    """A smaller transformation that still breaks the property."""

    steps: tuple[dict[str, Any], ...]
    input: DecisionInput
    presentation: Presentation | None = None
    result: DecisionResult
    comparison: Comparison
    violations: tuple[str, ...]
    backend_calls: int
    """Backend calls spent while minimizing."""


class PropertyPair(_Section):
    """One transformed case: what was sent, what came back, how it compares."""

    id: str
    """``<property>/<case id>/<sample>``: also the ``case_id`` sent to the backend."""
    property: PropertyName
    case_id: str
    sample: int
    steps: tuple[dict[str, Any], ...]
    """The transformation, replayable with ``apply(original input, steps)``."""
    provenance: dict[str, Any] = {}
    """Generator details (e.g. paraphrase provider and model)."""
    input: DecisionInput
    presentation: Presentation | None = None
    """``(shown label, contract label)`` in the order the backend saw; ``None`` means the
    contract labels in canonical order."""
    result: DecisionResult | None = None
    """The transformed decision, mapped back to contract labels."""
    error: CaseError | None = None
    comparison: Comparison | None = None
    violations: tuple[str, ...] = ()
    reduced: ReducedExample | None = None

    @model_validator(mode="after")
    def _consistent(self) -> PropertyPair:
        if (self.result is None) == (self.error is None):
            raise ValueError("a transformed case must have exactly one of 'result' or 'error'")
        if (self.result is None) != (self.comparison is None):
            raise ValueError("'comparison' must be present exactly when 'result' is")
        if self.error is not None and (self.violations or self.reduced is not None):
            raise ValueError("an errored transformed case cannot have violations")
        if self.result is not None and self.result.case_id != self.id:
            raise ValueError(
                f"result.case_id {self.result.case_id!r} does not match id {self.id!r}"
            )
        if self.reduced is not None and not self.violations:
            raise ValueError("only failing transformed cases can have a reduced example")
        return self

    def failed(self) -> bool:
        return bool(self.violations) or (
            self.error is not None and self.error.kind != ORIGINAL_ERROR
        )


class Skip(_Section):
    """A case a property could not transform. Recorded, never dropped silently."""

    property: PropertyName
    case_id: str
    reason: str


class PropertySummary(_Section):
    property: PropertyName
    level: str
    relation: str
    n_cases: int
    n_transformed: int
    """Transformed cases generated (errored ones included)."""
    n_skipped: int
    n_errors: int
    errors_by_kind: dict[str, int]
    n_evaluated: int
    n_violations: int
    """Evaluated cases breaking a per-case tolerance."""
    violation_rate: float | None
    n_flips: int
    flip_rate: float | None
    mean_tv_distance: float | None
    max_tv_distance: float | None
    max_js_divergence: float | None
    max_abs_delta: float | None
    max_abs_confidence_delta: float | None
    max_level_decrease: float | None = None
    """Monotonic only: largest move of the expected level against the direction."""
    n_reduced: int


class PropertyRun(_Section):
    seed: int
    fuzz: Fuzz
    config: Properties
    """The property settings the pairs were judged with."""
    summaries: tuple[PropertySummary, ...]
    pairs: tuple[PropertyPair, ...]
    skipped: tuple[Skip, ...] = ()

    def failures(self) -> list[PropertyPair]:
        return [pair for pair in self.pairs if pair.failed()]


def property_config(config: Properties, name: str) -> PropertyConfig:
    found = getattr(config, name)
    assert found is not None, name
    return found  # type: ignore[no-any-return]


def comparison_for(
    config: PropertyConfig, before: DecisionResult, after: DecisionResult
) -> Comparison:
    return compare(
        before, after, config.relation, direction=getattr(config, "direction", "increasing")
    )


def _max(values: Sequence[float]) -> float | None:
    return max(values) if values else None


def summarize(
    name: PropertyName,
    config: PropertyConfig,
    pairs: Sequence[PropertyPair],
    skipped: Sequence[Skip],
    n_cases: int,
) -> PropertySummary:
    mine = [pair for pair in pairs if pair.property == name]
    evaluated = [pair.comparison for pair in mine if pair.comparison is not None]
    errors = Counter(pair.error.kind for pair in mine if pair.error is not None)
    n_violations = sum(
        1
        for pair in mine
        if pair.comparison is not None and judge(config, pair.comparison).tolerance
    )
    flips = sum(1 for c in evaluated if c.flipped)
    level_decrease = None
    direction = getattr(config, "direction", None)
    if direction is not None:
        sign = 1.0 if direction == "increasing" else -1.0
        level_decrease = _max([max(0.0, -sign * (c.level_delta or 0.0)) for c in evaluated])
    return PropertySummary(
        property=name,
        level=config.level,
        relation=config.relation,
        n_cases=n_cases,
        n_transformed=len(mine),
        n_skipped=sum(1 for skip in skipped if skip.property == name),
        n_errors=sum(errors.values()),
        errors_by_kind=dict(sorted(errors.items())),
        n_evaluated=len(evaluated),
        n_violations=n_violations,
        violation_rate=n_violations / len(evaluated) if evaluated else None,
        n_flips=flips,
        flip_rate=flips / len(evaluated) if evaluated else None,
        mean_tv_distance=mean([c.tv_distance for c in evaluated]),
        max_tv_distance=_max([c.tv_distance for c in evaluated]),
        max_js_divergence=_max([c.js_divergence for c in evaluated]),
        max_abs_delta=_max([c.max_abs_delta for c in evaluated]),
        max_abs_confidence_delta=_max([abs(c.confidence_delta) for c in evaluated]),
        max_level_decrease=level_decrease,
        n_reduced=sum(1 for pair in mine if pair.reduced is not None),
    )


def assemble_run(
    *,
    seed: int,
    fuzz: Fuzz,
    config: Properties,
    pairs: Sequence[PropertyPair],
    skipped: Sequence[Skip],
    n_cases: int,
) -> PropertyRun:
    summaries = [
        summarize(name, prop, pairs, skipped, n_cases) for name, prop in config.configured().items()
    ]
    return PropertyRun(
        seed=seed,
        fuzz=fuzz,
        config=config,
        summaries=tuple(summaries),
        pairs=tuple(pairs),
        skipped=tuple(skipped),
    )


def property_checks(run: PropertyRun, config: Properties) -> list[Check]:
    """Checks for every property the contract enables. A property that was not run, or
    that could not evaluate a single case, fails: it was not demonstrated."""
    summaries = {summary.property: summary for summary in run.summaries}
    checks = []
    for name, prop in config.configured().items():
        summary = summaries.get(name)
        missing = "the property was not run" if summary is None else "no case could be transformed"
        n_transformed = summary.n_transformed if summary else 0
        checks.append(
            make_check(
                f"{name}.max_error_rate",
                f"{name}.error_rate",
                "<=",
                0.0,
                (summary.n_errors / n_transformed if n_transformed else None) if summary else None,
                level="requirement",
                missing=missing,
            )
        )
        if prop.tolerances():
            checks.append(
                make_check(
                    f"{name}.max_violation_rate",
                    f"{name}.violation_rate",
                    "<=",
                    prop.max_violation_rate,
                    summary.violation_rate if summary else None,
                    level=prop.level,
                    missing=missing,
                    detail=_limits(prop),
                )
            )
        if prop.max_flip_rate is not None:
            checks.append(
                make_check(
                    f"{name}.max_flip_rate",
                    f"{name}.flip_rate",
                    "<=",
                    prop.max_flip_rate,
                    summary.flip_rate if summary else None,
                    level=prop.level,
                    missing=missing,
                )
            )
    return checks


def _limits(prop: PropertyConfig) -> str:
    return "per case: " + ", ".join(f"{key} {value:g}" for key, value in prop.tolerances().items())


def rejudge(run: PropertyRun, config: Properties, records: Mapping[str, CaseRecord]) -> PropertyRun:
    """Re-apply (possibly edited) property settings to stored transformed cases.

    Transformations are not regenerated: pairs of properties the new settings no longer
    enable are dropped, and newly enabled properties have no pairs (their checks fail)."""
    enabled = config.configured()
    pairs = []
    for pair in run.pairs:
        prop = enabled.get(pair.property)
        if prop is None:
            continue
        pairs.append(_rejudge_pair(pair, prop, records))
    skipped = [skip for skip in run.skipped if skip.property in enabled]
    return PropertyRun(
        seed=run.seed,
        fuzz=run.fuzz,
        config=config,
        summaries=tuple(
            summarize(name, prop, pairs, skipped, _n_cases(run))
            for name, prop in enabled.items()
            if any(s.property == name for s in run.summaries)
        ),
        pairs=tuple(pairs),
        skipped=tuple(skipped),
    )


def _n_cases(run: PropertyRun) -> int:
    return run.summaries[0].n_cases if run.summaries else 0


def _rejudge_pair(
    pair: PropertyPair, prop: PropertyConfig, records: Mapping[str, CaseRecord]
) -> PropertyPair:
    before = records[pair.case_id].result
    if pair.result is None or before is None:
        return pair
    comparison = comparison_for(prop, before, pair.result)
    violations = tuple(judge(prop, comparison).violations)
    reduced = pair.reduced
    if reduced is not None:
        if violations:
            reduced_comparison = comparison_for(prop, before, reduced.result)
            reduced = reduced.model_copy(
                update={
                    "comparison": reduced_comparison,
                    "violations": tuple(judge(prop, reduced_comparison).violations),
                }
            )
        else:
            reduced = None
    return pair.model_copy(
        update={"comparison": comparison, "violations": violations, "reduced": reduced}
    )


def verify_run(run: PropertyRun, records: Mapping[str, CaseRecord]) -> None:
    """Raise ValueError when a stored transformed case is inconsistent with its original
    or with the recorded property settings (tampered or corrupted report)."""
    enabled = run.config.configured()
    for index, pair in enumerate(run.pairs):
        where = f"properties.pairs.{index} ({pair.id})"
        prop = enabled.get(pair.property)
        if prop is None:
            raise ValueError(f"{where}: property {pair.property!r} is not in properties.config")
        record = records.get(pair.case_id)
        if record is None:
            raise ValueError(f"{where}: case {pair.case_id!r} is not in results")
        if record.result is None:
            if pair.error is None or pair.error.kind != ORIGINAL_ERROR:
                raise ValueError(f"{where}: the original case errored, so this one must too")
            continue
        if pair.result is None:
            continue
        expected = comparison_for(prop, record.result, pair.result)
        if pair.comparison != expected:
            raise ValueError(f"{where}: comparison does not match the stored results")
        if pair.violations != tuple(judge(prop, expected).violations):
            raise ValueError(f"{where}: violations do not match the property settings")
        if pair.reduced is not None:
            reduced = comparison_for(prop, record.result, pair.reduced.result)
            if pair.reduced.comparison != reduced or pair.reduced.violations != tuple(
                judge(prop, reduced).violations
            ):
                raise ValueError(f"{where}: reduced example does not match its result")
            if pair.reduced.result.case_id != pair.id:
                raise ValueError(f"{where}: reduced result.case_id does not match id")
