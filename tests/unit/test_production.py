from __future__ import annotations

import json
from pathlib import Path

import pytest

from decguard.contracts import Evaluation
from decguard.decisions import DecisionSpec, DecisionType
from decguard.errors import DatasetError
from decguard.production import compute_production_metrics, load_production_dataset
from tests.conftest import write_jsonl

SPEC = DecisionSpec(
    name="refund_request",
    type=DecisionType.CHOICE,
    labels=("refund", "reject", "review"),
)


def record(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "decision": "refund_request",
        "probabilities": {"refund": 0.9, "reject": 0.05, "review": 0.05},
        "selected": "refund",
        "outcome": "refund",
        "metadata": {"locale": "en"},
    }
    data.update(overrides)
    return data


def test_production_records_derive_fields_and_metrics(tmp_path: Path) -> None:
    path = write_jsonl(
        tmp_path / "production.jsonl",
        [
            record(timestamp="2026-09-24T12:00:00Z", action="accept", latency_ms=10, cost=0.01),
            record(
                probabilities={"refund": 0.1, "reject": 0.8, "review": 0.1},
                selected="reject",
                outcome_correct=False,
                outcome=None,
                action="fallback",
                fallback=True,
                metadata={"locale": "it"},
            ),
        ],
    )
    dataset = load_production_dataset(path, SPEC, tolerance=1e-3)
    assert dataset.records[0].id == "record-1"
    assert dataset.records[0].confidence == 0.9
    assert dataset.records[0].outcome_correct is True
    metrics = compute_production_metrics(
        dataset.records,
        Evaluation(confidence_threshold=0.85, calibration_bins=10),
    )
    assert metrics.outcomes.accuracy == 0.5
    assert metrics.outcomes.error_rate == 0.5
    assert metrics.calibration.n == 2
    assert metrics.threshold is not None
    assert metrics.threshold.coverage == 0.5
    assert metrics.routing.fallback_rate == 0.5
    assert metrics.latency_ms.n == 1
    assert metrics.cost.total == 0.01


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"decision": "other"}, "does not match contract decision"),
        ({"selected": "reject"}, "is not the most probable label"),
        ({"confidence": 0.8}, "does not equal the probability"),
        ({"outcome": "unknown"}, "is not one of the contract labels"),
        ({"outcome_correct": False}, "disagrees with selected/outcome"),
        ({"action": "fallback", "fallback": False}, "conflicts"),
    ],
)
def test_invalid_production_records_are_not_silently_repaired(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    path = write_jsonl(tmp_path / "bad.jsonl", [record(**overrides)])
    with pytest.raises(DatasetError, match=message):
        load_production_dataset(path, SPEC, tolerance=1e-3)


def test_duplicate_record_ids_and_json_keys_are_rejected(tmp_path: Path) -> None:
    duplicate = write_jsonl(
        tmp_path / "duplicate.jsonl",
        [record(id="same"), record(id="same")],
    )
    with pytest.raises(DatasetError, match="duplicate record id"):
        load_production_dataset(duplicate, SPEC, tolerance=1e-3)

    raw = json.dumps(record())
    bad = tmp_path / "duplicate-key.jsonl"
    bad.write_text(raw[:-1] + ', "selected": "refund"}\n')
    with pytest.raises(DatasetError, match="duplicate key 'selected'"):
        load_production_dataset(bad, SPEC, tolerance=1e-3)
