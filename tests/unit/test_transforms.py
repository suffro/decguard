from __future__ import annotations

from typing import Any

import pytest

from decguard.backends.mock import semantic_label
from decguard.contracts.properties import (
    Fuzz,
    Inversion,
    IrrelevantContext,
    LabelFormat,
    Monotonic,
    OptionOrder,
    RepeatedContext,
    Rewrite,
    Whitespace,
)
from decguard.datasets import Case
from decguard.decisions import DecisionSpec, DecisionType
from decguard.fuzz.rng import Rng
from decguard.fuzz.transforms import (
    InversionTransform,
    IrrelevantContextTransform,
    LabelFormatTransform,
    MonotonicTransform,
    NotApplicable,
    OptionOrderTransform,
    RepeatedContextTransform,
    WhitespaceTransform,
    format_label,
    insert_fragments,
    replace_whitespace,
)

CHOICE = DecisionSpec(name="d", type=DecisionType.CHOICE, labels=("refund", "reject", "review"))
FUZZ = Fuzz()
CASE = Case(id="c1", input="The box arrived. It was damaged! Please help?")


def test_rng_is_deterministic_and_samples_distinct() -> None:
    a, b = Rng(1, "p", "c"), Rng(1, "p", "c")
    assert [a.below(10) for _ in range(20)] == [b.below(10) for _ in range(20)]
    assert Rng(1, "p", "c").below(1_000_000) != Rng(2, "p", "c").below(1_000_000)
    drawn = Rng(0).sample(range(10), 4)
    assert len(set(drawn)) == 4
    assert sorted(Rng(0).sample(range(5), 99)) == [0, 1, 2, 3, 4]
    # Pinned: stored fuzz runs must regenerate identically across Python versions.
    rng = Rng(0, "x")
    assert [rng.below(100) for _ in range(5)] == [59, 95, 9, 90, 31]
    assert Rng(0, "x").sample("abcdef", 3) == ["f", "b", "d"]


def test_insert_fragments_keeps_the_original_text() -> None:
    text = "One.  Two!\nThree"
    assert insert_fragments(text, []) == text
    assert insert_fragments(text, [{"at": 0, "text": "X."}]) == "X. One.  Two!\nThree"
    assert insert_fragments(text, [{"at": 1, "text": "X."}]) == "One.  X. Two!\nThree"
    assert insert_fragments(text, [{"at": 3, "text": "X."}]) == "One.  Two!\nThree X."


def test_replace_whitespace() -> None:
    text = "a b  c"
    assert replace_whitespace(text, []) == text
    steps: list[dict[str, Any]] = [
        {"at": 1, "ws": "\n"},
        {"at": "start", "ws": " "},
        {"at": "end", "ws": "\t"},
    ]
    assert replace_whitespace(text, steps) == " a b\nc\t"


def test_option_order_generates_distinct_non_identity_permutations() -> None:
    transform = OptionOrderTransform(OptionOrder(samples=3, max_tv_distance=0.1), CHOICE, FUZZ)
    mutations = transform.generate(CASE, Rng(0, "option_order", "c1"))
    assert len(mutations) == 3
    presentations = [m.presentation for m in mutations]
    assert len(set(presentations)) == 3
    for p in presentations:
        assert p is not None
        assert sorted(label for _, label in p) == sorted(CHOICE.labels)
        assert all(shown == label for shown, label in p)
    again = transform.generate(CASE, Rng(0, "option_order", "c1"))
    assert again == mutations


def test_option_order_takes_all_permutations_when_fewer_than_samples() -> None:
    transform = OptionOrderTransform(OptionOrder(samples=50, max_tv_distance=0.1), CHOICE, FUZZ)
    assert len(transform.generate(CASE, Rng(0))) == 5  # 3! - identity


def test_option_order_reductions_move_toward_the_canonical_order() -> None:
    transform = OptionOrderTransform(OptionOrder(max_tv_distance=0.1), CHOICE, FUZZ)
    reductions = list(transform.reductions(({"order": [2, 1, 0]},)))
    assert reductions == [({"order": [1, 2, 0]},), ({"order": [2, 0, 1]},)]
    assert list(transform.reductions(({"order": [1, 0, 2]},))) == []  # next step is identity


@pytest.mark.parametrize(
    ("style", "shown"),
    [
        ("upper", "REFUND"),
        ("capitalized", "Refund"),
        ("lettered", "B) refund"),
        ("numbered", "2. refund"),
        ("quoted", '"refund"'),
        ("bracketed", "[refund]"),
    ],
)
def test_label_styles_are_understood_by_the_mock(style: Any, shown: str) -> None:
    assert format_label("refund", style, 1) == shown
    assert semantic_label(shown) == "refund"


def test_label_format_keeps_order_and_skips_colliding_variants() -> None:
    spec = DecisionSpec(name="d", type=DecisionType.NOUL, labels=("Yes", "yes"))
    transform = LabelFormatTransform(
        LabelFormat(styles=("lower", "quoted"), max_tv_distance=0.1), spec, FUZZ
    )
    mutations = transform.generate(Case(id="c", input="x"), Rng(0))
    assert [m.presentation for m in mutations] == [(('"Yes"', "Yes"), ('"yes"', "yes"))]


def test_label_format_aliases() -> None:
    spec = DecisionSpec(name="d", type=DecisionType.NOUL, labels=("yes", "no"))
    config = LabelFormat(
        styles=(), aliases={"yes": ("true",), "no": ("false",)}, max_tv_distance=0.1
    )
    (mutation,) = LabelFormatTransform(config, spec, FUZZ).generate(Case(id="c", input="x"), Rng(0))
    assert mutation.presentation == (("true", "yes"), ("false", "no"))
    assert mutation.input == "x"


def test_irrelevant_context_steps_are_reducible() -> None:
    config = IrrelevantContext(fragments=("F1.", "F2."), insertions=3, max_tv_distance=0.1)
    transform = IrrelevantContextTransform(config, CHOICE, FUZZ)
    (first, *_) = transform.generate(CASE, Rng(0))
    assert len(first.steps) == 3
    assert isinstance(first.input, str)
    for fragment in (step["text"] for step in first.steps):
        assert fragment in first.input
    for smaller in transform.reductions(first.steps):
        assert len(smaller) == 2
        assert transform.apply(CASE.input, smaller).input != first.input


def test_repeated_context_repeats_one_fragment() -> None:
    config = RepeatedContext(fragments=("F1.", "F2."), repeats=4, max_tv_distance=0.1)
    (mutation,) = RepeatedContextTransform(config, CHOICE, FUZZ).generate(CASE, Rng(3))
    fragments = {step["text"] for step in mutation.steps}
    assert len(fragments) == 1
    assert isinstance(mutation.input, str)
    assert mutation.input.count(fragments.pop()) == 4


def test_whitespace_changes_only_whitespace() -> None:
    config = Whitespace(edits=3, samples=4, max_tv_distance=0.1)
    for mutation in WhitespaceTransform(config, CHOICE, FUZZ).generate(CASE, Rng(0)):
        assert isinstance(mutation.input, str)
        assert mutation.input.split() == str(CASE.input).split()
        assert mutation.input != CASE.input


def test_object_inputs_need_a_text_field() -> None:
    case = Case(id="c", input={"text": "Hello there. Bye.", "n": 1})
    config = IrrelevantContext(max_tv_distance=0.1)
    with pytest.raises(NotApplicable, match=r"set fuzz\.text_field"):
        IrrelevantContextTransform(config, CHOICE, FUZZ).generate(case, Rng(0))
    transform = IrrelevantContextTransform(config, CHOICE, Fuzz(text_field="text"))
    (mutation, *_) = transform.generate(case, Rng(0))
    assert isinstance(mutation.input, dict)
    assert mutation.input["n"] == 1
    assert mutation.input["text"] != "Hello there. Bye."
    with pytest.raises(NotApplicable, match="'body' is missing"):
        IrrelevantContextTransform(config, CHOICE, Fuzz(text_field="body")).generate(case, Rng(0))


def test_inversion_uses_matching_rewrites_only() -> None:
    config = Inversion(
        rewrites=(Rewrite(find="is spam", replace="is not spam"), Rewrite(find="zzz", replace="")),
        samples=5,
        max_tv_distance=0.1,
    )
    spec = DecisionSpec(name="d", type=DecisionType.NOUL, labels=("yes", "no"))
    transform = InversionTransform(config, spec, FUZZ)
    (mutation,) = transform.generate(Case(id="c", input="this is spam, is spam"), Rng(0))
    assert mutation.input == "this is not spam, is spam"
    with pytest.raises(NotApplicable, match="no rewrite"):
        transform.generate(Case(id="c", input="hello"), Rng(0))


def test_monotonic_raises_a_numeric_field() -> None:
    spec = DecisionSpec(name="d", type=DecisionType.SCORE, labels=("1", "2"))
    config = Monotonic(field="users", deltas=(10, 0.5))
    transform = MonotonicTransform(config, spec, FUZZ)
    mutations = transform.generate(Case(id="c", input={"users": 5, "t": "x"}), Rng(0))
    assert [m.input for m in mutations] == [{"users": 15, "t": "x"}, {"users": 5.5, "t": "x"}]
    for bad in ("text", {"users": "5"}, {"users": True}, {}):
        with pytest.raises(NotApplicable):
            transform.generate(Case(id="c", input=bad), Rng(0))
