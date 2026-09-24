"""Golden datasets: JSONL (one case per line) or JSON (a list of cases).

Each case is ``{"id"?, "input", "expected"?, "metadata"?}``. ``expected`` is optional
because several reliability checks (coverage, latency, error rate, later invariance
tests) need no gold answer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError, field_validator

from decguard._validation import StrictModel, format_validation_error, reject_duplicate_json_keys
from decguard.decisions import DecisionInput, DecisionSpec
from decguard.errors import DatasetError


class Case(StrictModel):
    id: str = Field(min_length=1)
    input: DecisionInput
    expected: str | None = None
    metadata: dict[str, Any] = {}

    @field_validator("expected", mode="before")
    @classmethod
    def _int_to_str(cls, value: Any) -> Any:
        # Score levels are often written as numbers; labels are always strings.
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return value


@dataclass(frozen=True)
class Dataset:
    path: Path
    hash: str
    """``sha256:<hex>`` of the raw file bytes."""
    cases: tuple[Case, ...]

    @property
    def n_labeled(self) -> int:
        return sum(1 for case in self.cases if case.expected is not None)


def _raw_items(path: Path, text: str) -> list[tuple[str, Any]]:
    """Return ``(location, raw case)`` pairs."""
    if path.suffix.lower() == ".jsonl":
        items = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                items.append(
                    (
                        f"line {lineno}",
                        json.loads(line, object_pairs_hook=reject_duplicate_json_keys),
                    )
                )
            except ValueError as exc:
                raise DatasetError(f"{path}: line {lineno}: invalid JSON: {exc}") from exc
        return items
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text, object_pairs_hook=reject_duplicate_json_keys)
        except ValueError as exc:
            raise DatasetError(f"{path}: invalid JSON: {exc}") from exc
        if not isinstance(data, list):
            raise DatasetError(f"{path}: a JSON dataset must be a list of cases")
        return [(f"case {index}", item) for index, item in enumerate(data, start=1)]
    raise DatasetError(f"{path}: unsupported dataset format (use .jsonl or .json)")


def load_dataset(path: str | Path, spec: DecisionSpec) -> Dataset:
    """Load and validate every case against ``spec``. Invalid cases are errors, never skipped."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DatasetError(f"{path}: cannot read dataset: {exc.strerror or exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetError(f"{path}: dataset is not valid UTF-8") from exc

    cases: list[Case] = []
    seen: dict[str, str] = {}
    for position, (location, raw_case) in enumerate(_raw_items(path, text), start=1):
        item = raw_case
        if isinstance(item, dict) and "id" not in item:
            item = {"id": f"case-{position}", **item}
        try:
            case = Case.model_validate(item)
        except ValidationError as exc:
            raise DatasetError(
                f"{path}: {location}: invalid case:\n{format_validation_error(exc)}"
            ) from exc
        if case.expected is not None and case.expected not in spec.labels:
            raise DatasetError(
                f"{path}: {location}: expected {case.expected!r} is not one of the contract "
                f"labels {list(spec.labels)}"
            )
        if case.id in seen:
            raise DatasetError(
                f"{path}: {location}: duplicate case id {case.id!r} (first at {seen[case.id]})"
            )
        seen[case.id] = location
        cases.append(case)

    if not cases:
        raise DatasetError(f"{path}: dataset contains no cases")
    return Dataset(path=path, hash="sha256:" + hashlib.sha256(raw).hexdigest(), cases=tuple(cases))
