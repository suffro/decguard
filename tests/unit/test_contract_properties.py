from __future__ import annotations

from typing import Any

import pytest

from decguard.contracts import parse_contract
from decguard.errors import ContractError
from tests.conftest import CHOICE_CONTRACT


def contract(**sections: Any) -> dict[str, Any]:
    return {**CHOICE_CONTRACT, **sections}


def test_properties_fuzz_and_regression_parse() -> None:
    parsed = parse_contract(
        contract(
            fuzz={"seed": 3, "text_field": "text"},
            properties={
                "option_order": {"max_tv_distance": 0.03, "max_flip_rate": 0},
                "paraphrase": {
                    "source": {"provider": "file", "path": "p.jsonl"},
                    "max_flip_rate": 0,
                },
                "whitespace": {"enabled": False, "max_tv_distance": 0.1},
            },
            regression={"max_answer_flip_rate": 0.01, "warnings": {"max_ece_increase": 0.02}},
        )
    )
    assert list(parsed.properties.configured()) == ["option_order", "paraphrase"]
    assert parsed.fuzz.seed == 3
    assert parsed.regression.configured() == {"max_answer_flip_rate": 0.01}
    assert parsed.regression.warnings.configured() == {"max_ece_increase": 0.02}
    assert parsed.properties.paraphrase is not None
    assert parsed.properties.paraphrase.source.settings == {"path": "p.jsonl"}


@pytest.mark.parametrize(
    ("sections", "message"),
    [
        ({"properties": {"option_order": {}}}, "set at least one of max_tv_distance"),
        ({"properties": {"option_order": {"max_tv_distnce": 0.1}}}, "unknown field"),
        ({"properties": {"shuffle": {}}}, "properties.shuffle: unknown field"),
        (
            {
                "properties": {
                    "inversion": {"rewrites": [{"find": "a", "replace": "b"}], "max_flip_rate": 0}
                }
            },
            "properties.inversion applies to noul decisions, not choice",
        ),
        (
            {"properties": {"monotonic": {"field": "n"}}},
            "properties.monotonic applies to score decisions, not choice",
        ),
        (
            {"properties": {"label_format": {"aliases": {"refnd": ["x"]}, "max_tv_distance": 0.1}}},
            "unknown labels ['refnd']",
        ),
        ({"properties": {"option_order": {"max_tv_distance": 2}}}, "less than or equal to 1"),
        ({"regression": {"max_segment_accuracy_drop": 0.1}}, "needs segment_by"),
        ({"fuzz": {"seed": -1}}, "fuzz.seed"),
    ],
)
def test_invalid_sections_are_rejected(sections: dict[str, Any], message: str) -> None:
    with pytest.raises(ContractError, match=message.replace("[", r"\[").replace("]", r"\]")):
        parse_contract(contract(**sections))


def test_score_and_noul_properties() -> None:
    score = parse_contract(
        contract(
            decision={"name": "s", "type": "score", "levels": [1, 2, 3]},
            backend={"provider": "mock"},
            properties={"monotonic": {"field": "n", "deltas": [1, 5]}, "option_order": None},
        )
    )
    assert list(score.properties.configured()) == ["monotonic"]
    with pytest.raises(ContractError, match="option_order applies to choice and noul"):
        parse_contract(
            contract(
                decision={"name": "s", "type": "score", "levels": [1, 2, 3]},
                backend={"provider": "mock"},
                properties={"option_order": {"max_flip_rate": 0}},
            )
        )
    noul = parse_contract(
        contract(
            decision={"name": "n", "type": "noul"},
            backend={"provider": "mock"},
            properties={
                "inversion": {
                    "rewrites": [{"find": " is ", "replace": " is not "}],
                    "max_flip_rate": 0,
                },
                "option_order": {"max_flip_rate": 0},
            },
        )
    )
    assert list(noul.properties.configured()) == ["option_order", "inversion"]
