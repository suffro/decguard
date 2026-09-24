"""Contract sections for metamorphic properties (``properties``, ``fuzz``) and model
comparison (``regression``)."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from decguard._validation import StrictModel

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegative = Annotated[float, Field(ge=0.0)]
Level = Literal["requirement", "warning"]
Relation = Literal["invariant", "swapped", "monotonic"]

PropertyName = Literal[
    "option_order",
    "label_format",
    "irrelevant_context",
    "repeated_context",
    "whitespace",
    "paraphrase",
    "inversion",
    "monotonic",
]

LabelStyle = Literal["upper", "lower", "capitalized", "lettered", "numbered", "quoted", "bracketed"]
LABEL_STYLES: tuple[LabelStyle, ...] = (
    "upper",
    "lower",
    "capitalized",
    "lettered",
    "numbered",
    "quoted",
    "bracketed",
)

DEFAULT_FRAGMENTS: tuple[str, ...] = (
    "The weather was mild that day.",
    "This note was written on a Tuesday.",
    "The office is on the third floor.",
    "The meeting room has a large window.",
    "There is a small plant on the desk.",
    "The train was on time this morning.",
    "The corridor lights were repainted last year.",
    "A colleague brought biscuits to share.",
)

TOLERANCES = ("max_tv_distance", "max_js_divergence", "max_abs_delta", "max_confidence_delta")


class _Property(StrictModel):
    """Settings shared by every property."""

    relation: ClassVar[Relation] = "invariant"
    types: ClassVar[tuple[str, ...]] = ("choice", "noul", "score")
    reducible: ClassVar[bool] = False

    enabled: bool = True
    level: Level = "requirement"
    """``requirement`` fails the run on violation; ``warning`` turns PASS into WARN."""
    max_flip_rate: Probability | None = None
    """Largest allowed share of transformed cases whose selected label changes."""
    max_violation_rate: Probability = 0.0
    """Largest allowed share of transformed cases breaking a per-case tolerance."""

    def tolerances(self) -> dict[str, float]:
        return {}


class _Distribution(_Property):
    """Properties compared through the probability distributions before and after."""

    max_tv_distance: Probability | None = None
    """Total variation distance: half the L1 distance between the distributions."""
    max_js_divergence: Probability | None = None
    """Jensen-Shannon divergence in bits (0-1)."""
    max_abs_delta: Probability | None = None
    """Largest change of any single label's probability."""
    max_confidence_delta: Probability | None = None
    """Largest change of the selected label's confidence."""

    @model_validator(mode="after")
    def _needs_a_limit(self) -> _Distribution:
        if self.max_flip_rate is None and not self.tolerances():
            raise ValueError(f"set at least one of {', '.join(TOLERANCES)} or max_flip_rate")
        return self

    def tolerances(self) -> dict[str, float]:
        return {key: value for key in TOLERANCES if (value := getattr(self, key)) is not None}


class OptionOrder(_Distribution):
    """Present the options in a different order."""

    types: ClassVar[tuple[str, ...]] = ("choice", "noul")
    reducible: ClassVar[bool] = True

    samples: int = Field(default=3, ge=1, le=100)


class LabelFormat(_Distribution):
    """Present the labels with a different surface form (case, enumerators, quotes, aliases)."""

    reducible: ClassVar[bool] = True

    styles: tuple[LabelStyle, ...] = LABEL_STYLES
    aliases: dict[str, tuple[str, ...]] = {}
    """Alternative wordings per label; variant *i* uses every label's *i*-th alias."""
    samples: int = Field(default=2, ge=1, le=100)

    @field_validator("aliases")
    @classmethod
    def _non_empty(cls, value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        for label, forms in value.items():
            if not forms or any(not form or form != form.strip() for form in forms):
                raise ValueError(f"aliases for {label!r} must be non-empty, trimmed strings")
        return value


class IrrelevantContext(_Distribution):
    """Insert sentences that should not affect the decision."""

    reducible: ClassVar[bool] = True

    fragments: tuple[Annotated[str, Field(min_length=1)], ...] = Field(
        default=DEFAULT_FRAGMENTS, min_length=1
    )
    insertions: int = Field(default=1, ge=1, le=10)
    samples: int = Field(default=2, ge=1, le=100)


class RepeatedContext(_Distribution):
    """Insert the same irrelevant sentence several times."""

    reducible: ClassVar[bool] = True

    fragments: tuple[Annotated[str, Field(min_length=1)], ...] = Field(
        default=DEFAULT_FRAGMENTS, min_length=1
    )
    repeats: int = Field(default=3, ge=2, le=20)
    samples: int = Field(default=1, ge=1, le=100)


class Whitespace(_Distribution):
    """Change whitespace: doubled spaces, line breaks, tabs, leading/trailing blanks."""

    reducible: ClassVar[bool] = True

    edits: int = Field(default=3, ge=1, le=20)
    samples: int = Field(default=2, ge=1, le=100)


class ParaphraseSource(BaseModel):
    """Which paraphrase provider to use. Keys besides ``provider`` are its settings."""

    model_config = ConfigDict(extra="allow", frozen=True)

    provider: str = Field(default="identity", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

    @property
    def settings(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class Paraphrase(_Distribution):
    """Replace the text with paraphrases from a provider."""

    source: ParaphraseSource = ParaphraseSource()
    samples: int = Field(default=1, ge=1, le=20)


class Rewrite(StrictModel):
    find: str = Field(min_length=1)
    replace: str


class Inversion(_Distribution):
    """Negate the input with a literal rewrite: the answer must swap (noul only)."""

    relation: ClassVar[Relation] = "swapped"
    types: ClassVar[tuple[str, ...]] = ("noul",)

    rewrites: tuple[Rewrite, ...] = Field(min_length=1)
    """Tried in order; the first occurrence of ``find`` is replaced."""
    samples: int = Field(default=1, ge=1, le=20)
    """How many applicable rewrites to use per case."""


class Monotonic(_Property):
    """Raise a numeric input field: the score must not move against ``direction``."""

    relation: ClassVar[Relation] = "monotonic"
    types: ClassVar[tuple[str, ...]] = ("score",)

    field: str = Field(min_length=1)
    """Top-level numeric key of object inputs."""
    direction: Literal["increasing", "decreasing"] = "increasing"
    """``increasing``: a larger field value must not lower the score."""
    deltas: tuple[Annotated[float, Field(gt=0.0)], ...] = Field(default=(1.0,), min_length=1)
    """Amounts added to the field, one transformed case each."""
    max_level_decrease: NonNegative = 0.0
    """Allowed move of the expected level against ``direction``, in scale steps."""

    def tolerances(self) -> dict[str, float]:
        return {"max_level_decrease": self.max_level_decrease}


PropertyConfig = (
    OptionOrder
    | LabelFormat
    | IrrelevantContext
    | RepeatedContext
    | Whitespace
    | Paraphrase
    | Inversion
    | Monotonic
)


class Properties(StrictModel):
    """Metamorphic properties checked by ``decguard fuzz`` and ``decguard test --all``."""

    option_order: OptionOrder | None = None
    label_format: LabelFormat | None = None
    irrelevant_context: IrrelevantContext | None = None
    repeated_context: RepeatedContext | None = None
    whitespace: Whitespace | None = None
    paraphrase: Paraphrase | None = None
    inversion: Inversion | None = None
    monotonic: Monotonic | None = None

    def configured(self) -> dict[PropertyName, PropertyConfig]:
        """Enabled properties, in a fixed order."""
        found: dict[PropertyName, PropertyConfig] = {}
        for name in type(self).model_fields:
            config = getattr(self, name)
            if config is not None and config.enabled:
                found[name] = config  # type: ignore[index]
        return found


class Fuzz(StrictModel):
    seed: int = Field(default=0, ge=0, lt=2**63)
    """Every generated transformation derives from (seed, property, case id)."""
    text_field: str | None = None
    """For object inputs: the top-level key whose string value text transformations edit."""
    minimize: bool = True
    """Shrink failing transformations to a smaller example that still fails."""
    max_minimize_calls: int = Field(default=32, ge=0, le=1000)
    """Backend calls allowed per failing case while minimizing."""


class RegressionGates(StrictModel):
    """Limits on how much a candidate may degrade relative to a baseline."""

    max_answer_flip_rate: Probability | None = None
    max_accuracy_drop: Probability | None = None
    max_macro_f1_drop: Probability | None = None
    max_ece_increase: Probability | None = None
    max_brier_increase: Annotated[float, Field(ge=0.0, le=2.0)] | None = None
    max_nll_increase: NonNegative | None = None
    max_mean_tv_distance: Probability | None = None
    max_mean_confidence_shift: Probability | None = None
    max_error_rate_increase: Probability | None = None
    max_latency_p95_increase_ms: NonNegative | None = None
    max_segment_accuracy_drop: Probability | None = None
    """Applied to every segment with at least ``min_segment_size`` matched cases."""

    def configured(self) -> dict[str, float]:
        return {
            key: value
            for key in RegressionGates.model_fields
            if (value := getattr(self, key)) is not None
        }


class Regression(RegressionGates):
    """Gates for ``decguard diff``; the top-level gates are requirements."""

    warnings: RegressionGates = RegressionGates()
    segment_by: tuple[Annotated[str, Field(min_length=1)], ...] = ()
    """Case ``metadata`` keys whose values define segments."""
    min_segment_size: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def _segments_for_segment_gate(self) -> Regression:
        wanted = "max_segment_accuracy_drop"
        if wanted in {**self.configured(), **self.warnings.configured()} and not self.segment_by:
            raise ValueError(f"{wanted} needs segment_by (case metadata keys)")
        return self
