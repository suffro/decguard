"""Controlled, replayable input transformations.

A transformation is a list of JSON-serializable *steps* applied to an original case.
``apply(original, steps)`` is pure, so a stored failure can be regenerated from its seed
and replayed, and reducible transformations can be shrunk by trying smaller step lists.

Option presentation is separate from the input: ``presentation`` lists
``(shown label, contract label)`` pairs in the order the backend sees them. Backends answer
in shown labels; the engine maps them back to contract labels before comparing.
"""

from __future__ import annotations

import itertools
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, TypeVar

from decguard.contracts.properties import (
    Fuzz,
    Inversion,
    IrrelevantContext,
    LabelFormat,
    LabelStyle,
    Monotonic,
    OptionOrder,
    Paraphrase,
    PropertyConfig,
    PropertyName,
    RepeatedContext,
    Whitespace,
)
from decguard.datasets import Case
from decguard.decisions import DecisionInput, DecisionSpec
from decguard.fuzz.paraphrase import Paraphraser
from decguard.fuzz.rng import Rng

Step = dict[str, Any]
Steps = tuple[Step, ...]
Presentation = tuple[tuple[str, str], ...]
"""``(shown label, contract label)`` pairs, in the order the backend sees them."""

ConfigT = TypeVar("ConfigT", bound=PropertyConfig)


@dataclass(frozen=True)
class Mutation:
    steps: Steps
    input: DecisionInput
    presentation: Presentation | None = None
    """``None`` means the contract labels in canonical order."""
    provenance: dict[str, Any] = field(default_factory=dict)


class NotApplicable(Exception):
    """The property cannot transform this case; the message says why."""


# --- text targets ----------------------------------------------------------------------


def get_text(value: DecisionInput, text_field: str | None) -> str:
    if isinstance(value, str):
        return value
    if text_field is None:
        raise NotApplicable("object input has no text to transform (set fuzz.text_field)")
    text = value.get(text_field)
    if not isinstance(text, str):
        raise NotApplicable(f"input field {text_field!r} is missing or not a string")
    return text


def set_text(value: DecisionInput, text_field: str | None, text: str) -> DecisionInput:
    if isinstance(value, str):
        return text
    assert text_field is not None
    return {**value, text_field: text}


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])(\s+)")


def insert_fragments(text: str, steps: Sequence[Step]) -> str:
    """Insert ``step["text"]`` before sentence ``step["at"]`` (or at the end when ``at`` is
    the sentence count), keeping the original text byte-for-byte otherwise."""
    parts = _SENTENCE_BREAK.split(text)
    sentences, separators = parts[0::2], parts[1::2]
    out: list[str] = []
    for index, sentence in enumerate(sentences):
        out.extend(step["text"] + " " for step in steps if step["at"] == index)
        out.append(sentence)
        if index < len(separators):
            out.append(separators[index])
    out.extend(" " + step["text"] for step in steps if step["at"] == len(sentences))
    return "".join(out)


def sentence_count(text: str) -> int:
    return len(_SENTENCE_BREAK.split(text)[0::2])


_WHITESPACE = re.compile(r"\s+")
_RUN_VARIANTS = ("  ", "\n", "\t", " \n")
_EDGE_VARIANTS = {"start": (" ", "\n"), "end": (" ", "\n", "  \n")}


def replace_whitespace(text: str, steps: Sequence[Step]) -> str:
    """Replace whitespace run ``step["at"]`` (or add at ``"start"``/``"end"``) with
    ``step["ws"]``."""
    replacements: dict[int | str, str] = {step["at"]: step["ws"] for step in steps}
    pieces, position = [], 0
    for index, match in enumerate(_WHITESPACE.finditer(text)):
        pieces.append(text[position : match.start()])
        pieces.append(replacements.get(index, match.group()))
        position = match.end()
    pieces.append(text[position:])
    return replacements.get("start", "") + "".join(pieces) + replacements.get("end", "")


def format_label(label: str, style: LabelStyle, index: int) -> str:
    if style == "upper":
        return label.upper()
    if style == "lower":
        return label.lower()
    if style == "capitalized":
        return label[:1].upper() + label[1:]
    if style == "lettered":
        return f"{chr(ord('A') + index) if index < 26 else index + 1}) {label}"
    if style == "numbered":
        return f"{index + 1}. {label}"
    if style == "quoted":
        return f'"{label}"'
    return f"[{label}]"


# --- transformations -------------------------------------------------------------------


class Transform(ABC, Generic[ConfigT]):
    name: ClassVar[PropertyName]
    keeps_no_ops: ClassVar[bool] = False
    """Keep transformations that leave the case unchanged (identity paraphrases test
    determinism)."""

    def __init__(self, config: ConfigT, spec: DecisionSpec, fuzz: Fuzz) -> None:
        self.config = config
        self.spec = spec
        self.fuzz = fuzz

    @abstractmethod
    def candidates(self, case: Case, rng: Rng) -> list[Steps]:
        """Step lists for this case, at most ``samples``; raise NotApplicable if none."""

    @abstractmethod
    def apply(self, original: DecisionInput, steps: Steps) -> Mutation: ...

    def reductions(self, steps: Steps) -> Iterator[Steps]:
        """Smaller variants of ``steps`` to try while minimizing (default: none)."""
        return iter(())

    def generate(self, case: Case, rng: Rng) -> list[Mutation]:
        """Distinct transformations of ``case``, skipping ones that change nothing."""
        mutations: list[Mutation] = []
        for steps in self.candidates(case, rng):
            mutation = self.apply(case.input, steps)
            if not self.keeps_no_ops and is_no_op(case.input, mutation):
                continue
            if all(
                (m.input, m.presentation) != (mutation.input, mutation.presentation)
                for m in mutations
            ):
                mutations.append(mutation)
        if not mutations:
            raise NotApplicable("no transformation changes this case")
        return mutations

    def _text(self, value: DecisionInput) -> str:
        return get_text(value, self.fuzz.text_field)

    def _with_text(self, value: DecisionInput, text: str) -> DecisionInput:
        return set_text(value, self.fuzz.text_field, text)


def is_no_op(original: DecisionInput, mutation: Mutation) -> bool:
    return mutation.input == original and mutation.presentation is None


def _drop_one(steps: Steps) -> Iterator[Steps]:
    if len(steps) > 1:
        for index in range(len(steps)):
            yield steps[:index] + steps[index + 1 :]


def canonical_presentation(
    presentation: Presentation, labels: Sequence[str]
) -> Presentation | None:
    identity = tuple((label, label) for label in labels)
    return None if presentation == identity else presentation


class OptionOrderTransform(Transform[OptionOrder]):
    name = "option_order"
    _ENUMERATE_UP_TO = 6

    def candidates(self, case: Case, rng: Rng) -> list[Steps]:
        n = len(self.spec.labels)
        identity = tuple(range(n))
        if n <= self._ENUMERATE_UP_TO:
            orders = [p for p in itertools.permutations(identity) if p != identity]
            chosen = rng.sample(orders, self.config.samples)
        else:
            chosen, attempts = [], 0
            while len(chosen) < self.config.samples and attempts < 1000:
                attempts += 1
                order = tuple(rng.shuffled(identity))
                if order != identity and order not in chosen:
                    chosen.append(order)
        return [({"order": list(order)},) for order in chosen]

    def apply(self, original: DecisionInput, steps: Steps) -> Mutation:
        labels = self.spec.labels
        order = steps[0]["order"]
        presentation = tuple((labels[i], labels[i]) for i in order)
        return Mutation(steps, original, canonical_presentation(presentation, labels))

    def reductions(self, steps: Steps) -> Iterator[Steps]:
        """Undo one adjacent inversion at a time: permutations closer to the original."""
        order = list(steps[0]["order"])
        for j in range(len(order) - 1):
            if order[j] > order[j + 1]:
                smaller = order.copy()
                smaller[j], smaller[j + 1] = smaller[j + 1], smaller[j]
                if smaller != sorted(smaller):
                    yield ({"order": smaller},)


class LabelFormatTransform(Transform[LabelFormat]):
    name = "label_format"

    def _variants(self) -> list[Steps]:
        labels = self.spec.labels
        variants: list[Steps] = []
        for style in self.config.styles:
            steps = tuple(
                {"label": label, "style": style}
                for index, label in enumerate(labels)
                if format_label(label, style, index) != label
            )
            if steps:
                variants.append(steps)
        aliases = self.config.aliases
        for k in range(max((len(forms) for forms in aliases.values()), default=0)):
            steps = tuple(
                {"label": label, "alias": aliases[label][k]}
                for label in labels
                if label in aliases and len(aliases[label]) > k
            )
            variants.append(steps)
        return [steps for steps in variants if self._distinct(steps)]

    def _shown(self, steps: Steps) -> dict[str, str]:
        labels = self.spec.labels
        shown = {label: label for label in labels}
        for step in steps:
            label = step["label"]
            if "alias" in step:
                shown[label] = step["alias"]
            else:
                shown[label] = format_label(label, step["style"], labels.index(label))
        return shown

    def _distinct(self, steps: Steps) -> bool:
        values = list(self._shown(steps).values())
        return len(set(values)) == len(values)

    def candidates(self, case: Case, rng: Rng) -> list[Steps]:
        return rng.sample(self._variants(), self.config.samples)

    def apply(self, original: DecisionInput, steps: Steps) -> Mutation:
        shown = self._shown(steps)
        presentation = tuple((shown[label], label) for label in self.spec.labels)
        return Mutation(steps, original, canonical_presentation(presentation, self.spec.labels))

    def reductions(self, steps: Steps) -> Iterator[Steps]:
        return (smaller for smaller in _drop_one(steps) if self._distinct(smaller))


InsertionT = TypeVar("InsertionT", IrrelevantContext, RepeatedContext)


class _InsertionTransform(Transform[InsertionT]):
    """Sentences inserted at sentence boundaries; each insertion is one removable step."""

    def candidates(self, case: Case, rng: Rng) -> list[Steps]:
        text = self._text(case.input)
        if not text.strip():
            raise NotApplicable("text is empty")
        boundaries = sentence_count(text) + 1
        chosen: list[Steps] = []
        for _ in range(self.config.samples):
            steps = [
                {"at": rng.below(boundaries), "text": fragment} for fragment in self._fragments(rng)
            ]
            chosen.append(tuple(sorted(steps, key=lambda step: step["at"])))
        return chosen

    @abstractmethod
    def _fragments(self, rng: Rng) -> list[str]: ...

    def apply(self, original: DecisionInput, steps: Steps) -> Mutation:
        text = insert_fragments(self._text(original), steps)
        return Mutation(steps, self._with_text(original, text))

    def reductions(self, steps: Steps) -> Iterator[Steps]:
        return _drop_one(steps)


class IrrelevantContextTransform(_InsertionTransform[IrrelevantContext]):
    name = "irrelevant_context"

    def _fragments(self, rng: Rng) -> list[str]:
        return [rng.choice(self.config.fragments) for _ in range(self.config.insertions)]


class RepeatedContextTransform(_InsertionTransform[RepeatedContext]):
    name = "repeated_context"

    def _fragments(self, rng: Rng) -> list[str]:
        return [rng.choice(self.config.fragments)] * self.config.repeats


class WhitespaceTransform(Transform[Whitespace]):
    name = "whitespace"

    def candidates(self, case: Case, rng: Rng) -> list[Steps]:
        text = self._text(case.input)
        runs = [match.group() for match in _WHITESPACE.finditer(text)]
        targets: list[int | str] = ["start", *range(len(runs)), "end"]
        chosen: list[Steps] = []
        for _ in range(self.config.samples):
            steps = []
            for target in rng.sample(targets, self.config.edits):
                if isinstance(target, str):
                    variants: Sequence[str] = _EDGE_VARIANTS[target]
                else:
                    variants = [v for v in _RUN_VARIANTS if v != runs[target]]
                steps.append({"at": target, "ws": rng.choice(variants)})
            chosen.append(tuple(sorted(steps, key=_whitespace_order)))
        return chosen

    def apply(self, original: DecisionInput, steps: Steps) -> Mutation:
        text = replace_whitespace(self._text(original), steps)
        return Mutation(steps, self._with_text(original, text))

    def reductions(self, steps: Steps) -> Iterator[Steps]:
        return _drop_one(steps)


def _whitespace_order(step: Step) -> tuple[int, int]:
    at = step["at"]
    if at == "start":
        return (0, 0)
    if at == "end":
        return (2, 0)
    return (1, at)


class ParaphraseTransform(Transform[Paraphrase]):
    name = "paraphrase"
    keeps_no_ops = True

    def __init__(
        self, config: Paraphrase, spec: DecisionSpec, fuzz: Fuzz, paraphraser: Paraphraser
    ) -> None:
        super().__init__(config, spec, fuzz)
        self.paraphraser = paraphraser

    def candidates(self, case: Case, rng: Rng) -> list[Steps]:
        text = self._text(case.input)
        paraphrases = self.paraphraser.paraphrase(
            text, case_id=case.id, n=self.config.samples, seed=self.fuzz.seed
        )
        if not paraphrases:
            raise NotApplicable(f"paraphrase provider {self.paraphraser.provider!r} gave none")
        return [({"text": paraphrase},) for paraphrase in paraphrases[: self.config.samples]]

    def apply(self, original: DecisionInput, steps: Steps) -> Mutation:
        text = steps[0]["text"]
        return Mutation(
            steps, self._with_text(original, text), provenance=self.paraphraser.provenance()
        )


class InversionTransform(Transform[Inversion]):
    name = "inversion"

    def candidates(self, case: Case, rng: Rng) -> list[Steps]:
        text = self._text(case.input)
        applicable = [r for r in self.config.rewrites if r.find in text]
        if not applicable:
            raise NotApplicable("no rewrite matches the text")
        return [
            ({"find": r.find, "replace": r.replace},) for r in applicable[: self.config.samples]
        ]

    def apply(self, original: DecisionInput, steps: Steps) -> Mutation:
        step = steps[0]
        text = self._text(original).replace(step["find"], step["replace"], 1)
        return Mutation(steps, self._with_text(original, text))


class MonotonicTransform(Transform[Monotonic]):
    name = "monotonic"

    def _value(self, original: DecisionInput) -> float:
        name = self.config.field
        value = original.get(name) if isinstance(original, dict) else None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise NotApplicable(f"input field {name!r} is missing or not a number")
        if not math.isfinite(value):
            raise NotApplicable(f"input field {name!r} is not finite")
        return value

    def candidates(self, case: Case, rng: Rng) -> list[Steps]:
        self._value(case.input)
        return [({"field": self.config.field, "delta": delta},) for delta in self.config.deltas]

    def apply(self, original: DecisionInput, steps: Steps) -> Mutation:
        value = self._value(original)
        delta = steps[0]["delta"]
        changed = value + delta
        if isinstance(value, int) and float(delta).is_integer():
            changed = int(changed)
        assert isinstance(original, dict)
        return Mutation(steps, {**original, self.config.field: changed})


def make_transform(
    name: PropertyName,
    config: PropertyConfig,
    spec: DecisionSpec,
    fuzz: Fuzz,
    paraphraser: Paraphraser | None = None,
) -> Transform[Any]:
    if isinstance(config, Paraphrase):
        if paraphraser is None:
            raise ValueError("the paraphrase property needs a paraphraser")
        return ParaphraseTransform(config, spec, fuzz, paraphraser)
    classes: dict[str, type[Transform[Any]]] = {
        "option_order": OptionOrderTransform,
        "label_format": LabelFormatTransform,
        "irrelevant_context": IrrelevantContextTransform,
        "repeated_context": RepeatedContextTransform,
        "whitespace": WhitespaceTransform,
        "inversion": InversionTransform,
        "monotonic": MonotonicTransform,
    }
    return classes[name](config, spec, fuzz)
