from __future__ import annotations

from pathlib import Path

import pytest

from decguard.datasets import load_dataset
from decguard.decisions import DecisionSpec, DecisionType
from decguard.errors import DatasetError
from tests.conftest import write_jsonl

CHOICE = DecisionSpec(name="d", type=DecisionType.CHOICE, labels=("a", "b"))
SCORE = DecisionSpec(name="s", type=DecisionType.SCORE, labels=("1", "2", "3"))


def test_jsonl_with_default_ids_and_optional_labels(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"input": "one", "expected": "a"}\n\n'
        '{"input": {"text": "two", "amount": 3}, "metadata": {"locale": "it"}}\n'
    )
    dataset = load_dataset(path, CHOICE)
    assert [c.id for c in dataset.cases] == ["case-1", "case-2"]
    assert dataset.cases[1].input == {"text": "two", "amount": 3}
    assert dataset.cases[1].expected is None
    assert dataset.cases[1].metadata == {"locale": "it"}
    assert dataset.n_labeled == 1
    assert dataset.hash.startswith("sha256:")


def test_json_list(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text('[{"id": "x", "input": "one", "expected": "b"}]')
    assert load_dataset(path, CHOICE).cases[0].id == "x"


def test_score_expected_may_be_a_number(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "cases.jsonl", [{"input": "x", "expected": 2}])
    assert load_dataset(path, SCORE).cases[0].expected == "2"


def test_hash_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "cases.jsonl", [{"input": "x"}])
    first = load_dataset(path, CHOICE).hash
    assert load_dataset(path, CHOICE).hash == first
    write_jsonl(path, [{"input": "y"}])
    assert load_dataset(path, CHOICE).hash != first


@pytest.mark.parametrize(
    ("content", "suffix", "message"),
    [
        ('{"input": "x", "expected": "c"}\n', ".jsonl", "'c' is not one of the contract labels"),
        ('{"input": "x"}\n{"input": \n', ".jsonl", "line 2: invalid JSON"),
        ('{"id": "a", "input": "x"}\n{"id": "a", "input": "y"}\n', ".jsonl", "duplicate case id"),
        ('{"inputs": "x"}\n', ".jsonl", "inputs: unknown field"),
        ('{"expected": "a"}\n', ".jsonl", "input: required field is missing"),
        ('{"input": "x", "input": "y"}\n', ".jsonl", "duplicate key 'input'"),
        ("\n\n", ".jsonl", "contains no cases"),
        ('{"cases": []}', ".json", "must be a list of cases"),
        ("input,expected\n", ".csv", "unsupported dataset format"),
    ],
)
def test_invalid_datasets_fail_loudly(
    tmp_path: Path, content: str, suffix: str, message: str
) -> None:
    path = tmp_path / f"cases{suffix}"
    path.write_text(content)
    with pytest.raises(DatasetError, match=message):
        load_dataset(path, CHOICE)


def test_missing_dataset(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="cannot read dataset"):
        load_dataset(tmp_path / "nope.jsonl", CHOICE)
