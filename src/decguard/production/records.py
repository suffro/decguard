"""Backend-neutral production records and JSONL/JSON loading."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, ValidationError, field_validator

from decguard._validation import StrictModel, format_validation_error, reject_duplicate_json_keys
from decguard.contracts.policy import PolicyAction
from decguard.decisions import (
    DecisionInput,
    DecisionSpec,
    select_label,
    validate_probabilities,
)
from decguard.errors import DatasetError, InvalidResponse

NonNegative = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
SegmentValue = str | int | float | bool | None


class ProductionRecord(StrictModel):
    """One decision observed after deployment.

    Outcomes and routing fields are optional because they are commonly joined later. The
    loader derives ``confidence`` and ``outcome_correct`` when enough information exists.
    """

    id: str = Field(min_length=1)
    timestamp: str | None = None
    decision: str
    input: DecisionInput | None = None
    probabilities: dict[str, float]
    selected: str
    confidence: Probability
    backend: str | None = None
    model: str | None = None
    model_version: str | None = None
    outcome: str | None = None
    outcome_correct: bool | None = None
    latency_ms: NonNegative | None = None
    cost: NonNegative | None = None
    action: PolicyAction | None = None
    fallback: bool | None = None
    metadata: dict[str, Any] = {}

    @field_validator("selected", "outcome", mode="before")
    @classmethod
    def _int_label_to_str(cls, value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return value

    @field_validator("timestamp")
    @classmethod
    def _timestamp_is_iso8601(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("must be an ISO 8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError("must include a timezone")
        return value


@dataclass(frozen=True)
class ProductionDataset:
    path: Path
    hash: str
    """``sha256:<hex>`` of the raw file bytes."""
    records: tuple[ProductionRecord, ...]

    @property
    def n_outcomes(self) -> int:
        return sum(record.outcome is not None for record in self.records)

    @property
    def n_correctness(self) -> int:
        return sum(record.outcome_correct is not None for record in self.records)


def _json_items(path: Path, raw: bytes) -> list[tuple[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetError(f"{path}: production dataset is not valid UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_json_keys)
    except ValueError as exc:
        raise DatasetError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, list):
        raise DatasetError(f"{path}: a JSON production dataset must be a list of records")
    return [(f"record {index}", item) for index, item in enumerate(value, start=1)]


def _jsonl_items(path: Path, digest: Any) -> Iterator[tuple[str, Any]]:
    """Parse JSONL incrementally while hashing the exact source bytes."""
    try:
        with path.open("rb") as stream:
            for lineno, raw_line in enumerate(stream, start=1):
                digest.update(raw_line)
                if not raw_line.strip():
                    continue
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise DatasetError(
                        f"{path}: line {lineno}: production dataset is not valid UTF-8"
                    ) from exc
                try:
                    value = json.loads(line, object_pairs_hook=reject_duplicate_json_keys)
                except ValueError as exc:
                    raise DatasetError(f"{path}: line {lineno}: invalid JSON: {exc}") from exc
                yield f"line {lineno}", value
    except OSError as exc:
        raise DatasetError(
            f"{path}: cannot read production dataset: {exc.strerror or exc}"
        ) from exc


def normalize_record(
    record: ProductionRecord,
    spec: DecisionSpec,
    *,
    tolerance: float,
    source: str,
) -> ProductionRecord:
    """Check contract-dependent invariants and return canonical probabilities/derived fields."""
    if record.decision != spec.name:
        raise DatasetError(
            f"{source}: decision {record.decision!r} does not match contract decision {spec.name!r}"
        )
    try:
        probabilities = validate_probabilities(
            spec.labels, record.probabilities, tolerance=tolerance
        )
    except InvalidResponse as exc:
        raise DatasetError(f"{source}: {exc}") from exc
    selected = select_label(spec.labels, probabilities)
    if record.selected != selected:
        raise DatasetError(
            f"{source}: selected {record.selected!r} is not the most probable label {selected!r}"
        )
    confidence = probabilities[selected]
    if record.confidence != confidence:
        raise DatasetError(
            f"{source}: confidence {record.confidence!r} does not equal the probability of "
            f"{selected!r} ({confidence!r})"
        )
    if record.outcome is not None and record.outcome not in spec.labels:
        raise DatasetError(
            f"{source}: outcome {record.outcome!r} is not one of the contract labels "
            f"{list(spec.labels)}"
        )
    derived_correct = record.outcome == selected if record.outcome is not None else None
    if (
        derived_correct is not None
        and record.outcome_correct is not None
        and record.outcome_correct is not derived_correct
    ):
        raise DatasetError(
            f"{source}: outcome_correct {record.outcome_correct!r} disagrees with selected/outcome"
        )
    if record.action == "fallback" and record.fallback is False:
        raise DatasetError(f"{source}: action 'fallback' conflicts with fallback=false")
    if record.action not in (None, "fallback") and record.fallback is True:
        raise DatasetError(f"{source}: fallback=true conflicts with action {record.action!r}")
    return record.model_copy(
        update={
            "probabilities": probabilities,
            "outcome_correct": (
                derived_correct if record.outcome_correct is None else record.outcome_correct
            ),
        }
    )


def _prepare_item(item: Any, position: int) -> Any:
    if not isinstance(item, dict):
        return item
    prepared = dict(item)
    prepared.setdefault("id", f"record-{position}")
    probabilities = prepared.get("probabilities")
    selected = prepared.get("selected")
    if (
        "confidence" not in prepared
        and isinstance(probabilities, dict)
        and selected in probabilities
    ):
        prepared["confidence"] = probabilities[selected]
    return prepared


def load_production_dataset(
    path: str | Path, spec: DecisionSpec, *, tolerance: float
) -> ProductionDataset:
    """Load every production record. Invalid records are errors and are never skipped."""
    path = Path(path)
    digest = hashlib.sha256()
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        items: Iterator[tuple[str, Any]] = _jsonl_items(path, digest)
    elif suffix == ".json":
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise DatasetError(
                f"{path}: cannot read production dataset: {exc.strerror or exc}"
            ) from exc
        digest.update(raw)
        items = iter(_json_items(path, raw))
    else:
        raise DatasetError(f"{path}: unsupported production dataset format (use .jsonl or .json)")

    records: list[ProductionRecord] = []
    seen: dict[str, str] = {}
    for position, (location, raw_record) in enumerate(items, start=1):
        try:
            parsed = ProductionRecord.model_validate(_prepare_item(raw_record, position))
        except ValidationError as exc:
            raise DatasetError(
                f"{path}: {location}: invalid production record:\n{format_validation_error(exc)}"
            ) from exc
        source = f"{path}: {location}"
        record = normalize_record(parsed, spec, tolerance=tolerance, source=source)
        if record.id in seen:
            raise DatasetError(
                f"{path}: {location}: duplicate record id {record.id!r} "
                f"(first at {seen[record.id]})"
            )
        seen[record.id] = location
        records.append(record)

    if not records:
        raise DatasetError(f"{path}: production dataset contains no records")
    return ProductionDataset(
        path=path,
        hash="sha256:" + digest.hexdigest(),
        records=tuple(records),
    )


def segment_value(record: ProductionRecord, key: str) -> SegmentValue:
    """Return one scalar metadata value for segmentation; missing values form a group."""
    value = record.metadata.get(key)
    if isinstance(value, float) and not math.isfinite(value):
        raise DatasetError(f"record {record.id!r}: metadata.{key} must be finite")
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise DatasetError(
        f"record {record.id!r}: metadata.{key} must be a string, number, boolean or null "
        "when used as a segment"
    )
