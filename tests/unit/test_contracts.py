from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from decguard.contracts import contract_hash, load_contract, parse_contract
from decguard.decisions import DecisionType
from decguard.errors import ContractError
from tests.conftest import CHOICE_CONTRACT


def contract(**overrides: Any) -> dict[str, Any]:
    data = copy.deepcopy(CHOICE_CONTRACT)
    data.update(overrides)
    return data


def test_choice_contract_normalizes_to_spec() -> None:
    spec = parse_contract(contract()).spec()
    assert spec.type is DecisionType.CHOICE
    assert spec.labels == ("refund", "reject", "review")


def test_noul_defaults_to_yes_no() -> None:
    parsed = parse_contract(contract(decision={"name": "flag", "type": "noul"}))
    assert parsed.spec().labels == ("yes", "no")


def test_noul_accepts_custom_labels_positive_first() -> None:
    parsed = parse_contract(
        contract(decision={"name": "spam", "type": "noul", "labels": ["spam", "ham"]})
    )
    assert parsed.spec().labels == ("spam", "ham")


def test_score_levels_keep_order_and_accept_numbers() -> None:
    parsed = parse_contract(
        contract(decision={"name": "sev", "type": "score", "levels": [1, 2, 3]})
    )
    assert parsed.spec().type is DecisionType.SCORE
    assert parsed.spec().labels == ("1", "2", "3")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema_version": None}, "schema_version: required field is missing"),
        ({"schema_version": 0.1}, "quote it in YAML"),
        ({"schema_version": "9.9"}, "unsupported schema_version '9.9'"),
        (
            {"decision": {"name": "x", "type": "choice", "options": ["a"]}},
            "decision.choice.options",
        ),
        (
            {"decision": {"name": "x", "type": "choice", "options": ["a", "a"]}},
            "duplicate labels: ['a']",
        ),
        (
            {"decision": {"name": "x", "type": "choice", "options": ["a", " b"]}},
            "no surrounding spaces",
        ),
        ({"decision": {"name": "x", "type": "ranking", "options": ["a", "b"]}}, "decision"),
        ({"decision": {"name": "bad name!", "type": "noul"}}, "decision.noul.name"),
        ({"requirments": {"min_accuracy": 0.9}}, "requirments: unknown field"),
        ({"requirements": {"min_acuracy": 0.9}}, "requirements.min_acuracy: unknown field"),
        ({"requirements": {"min_accuracy": 1.5}}, "requirements.min_accuracy"),
        (
            {"requirements": {"min_coverage": 0.5}},
            "min_coverage needs evaluation.confidence_threshold",
        ),
        ({"warnings": {"max_ordinal_mae": 0.5}}, "only applies to score decisions"),
        ({"backends": {"default": {"provider": "mock"}}}, "reserved"),
        ({"backend": {"model": "m"}}, "backend.provider: required field is missing"),
    ],
)
def test_invalid_contracts_have_helpful_errors(overrides: dict[str, Any], message: str) -> None:
    data = copy.deepcopy(CHOICE_CONTRACT)
    for key, value in overrides.items():
        if value is None:
            data.pop(key)
        else:
            data[key] = value
    with pytest.raises(ContractError) as info:
        parse_contract(data, source="c.yaml")
    assert message in str(info.value)
    assert str(info.value).startswith("c.yaml: invalid contract")


def test_top_level_must_be_mapping() -> None:
    with pytest.raises(ContractError, match="mapping at the top level"):
        parse_contract(["not", "a", "mapping"])


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(
        'schema_version: "0.1"\nschema_version: "0.1"\n'
        "decision: {name: x, type: noul}\nbackend: {provider: mock}\n"
    )
    with pytest.raises(ContractError, match="duplicate key 'schema_version'"):
        load_contract(path)


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text('{"schema_version": "0.1", "schema_version": "0.1"}')
    with pytest.raises(ContractError, match="duplicate key"):
        load_contract(path)


def test_yaml_cannot_construct_python_objects(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("schema_version: !!python/object/apply:os.getcwd []\n")
    with pytest.raises(ContractError, match="cannot parse"):
        load_contract(path)


def test_missing_file_is_contract_error(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="cannot read contract"):
        load_contract(tmp_path / "missing.yaml")


def test_hash_ignores_formatting_and_key_order(tmp_path: Path) -> None:
    a = tmp_path / "a.yaml"
    a.write_text(
        'schema_version: "0.1"\ndecision: {name: x, type: noul}\nbackend: {provider: mock}\n'
    )
    b = tmp_path / "b.json"
    b.write_text(
        '{"backend": {"provider": "mock"},\n "decision": {"type": "noul", "name": "x"},'
        ' "schema_version": "0.1"}'
    )
    assert load_contract(a).hash == load_contract(b).hash
    assert load_contract(a).hash.startswith("sha256:")


def test_hash_changes_with_thresholds() -> None:
    base = parse_contract(contract())
    stricter = parse_contract(contract(requirements={"min_accuracy": 0.99}))
    assert contract_hash(base) != contract_hash(stricter)


def test_named_backend_lookup() -> None:
    parsed = parse_contract(contract(backends={"candidate": {"provider": "mock", "seed": 3}}))
    assert parsed.backend_names() == ["default", "candidate"]
    assert parsed.backend_config("candidate").settings == {"seed": 3}
    with pytest.raises(ContractError, match="unknown backend 'nope'"):
        parsed.backend_config("nope")
