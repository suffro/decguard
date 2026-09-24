from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

CHOICE_CONTRACT: dict[str, Any] = {
    "schema_version": "0.1",
    "decision": {
        "name": "refund_request",
        "type": "choice",
        "options": ["refund", "reject", "review"],
    },
    "backend": {
        "provider": "mock",
        "model": "unit-mock",
        "rules": [
            {
                "contains": "damaged",
                "probabilities": {"refund": 0.9, "reject": 0.05, "review": 0.05},
            },
            {
                "contains": "changed",
                "probabilities": {"refund": 0.1, "reject": 0.8, "review": 0.1},
            },
        ],
        "default": {"refund": 0.2, "reject": 0.2, "review": 0.6},
    },
    "dataset": "cases.jsonl",
    "requirements": {"min_accuracy": 0.75},
}

CHOICE_CASES: list[dict[str, Any]] = [
    {"id": "c1", "input": "arrived damaged", "expected": "refund"},
    {"id": "c2", "input": "I changed my mind", "expected": "reject"},
    {"id": "c3", "input": "wrong invoice", "expected": "review"},
    {"id": "c4", "input": "damaged box but fine", "expected": "review"},
    {"id": "c5", "input": "unlabeled question"},
]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def write_yaml(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


ContractFactory = Callable[..., Path]


@pytest.fixture
def make_contract(tmp_path: Path) -> ContractFactory:
    """Write a contract (CHOICE_CONTRACT with overrides) plus its dataset into tmp_path."""

    def factory(
        overrides: dict[str, Any] | None = None,
        cases: list[dict[str, Any]] | None = None,
        name: str = "decguard.yaml",
    ) -> Path:
        data = copy.deepcopy(CHOICE_CONTRACT)
        for key, value in (overrides or {}).items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        write_jsonl(tmp_path / "cases.jsonl", CHOICE_CASES if cases is None else cases)
        return write_yaml(tmp_path / name, data)

    return factory
