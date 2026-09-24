"""Shared pydantic base model and error formatting."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class StrictModel(BaseModel):
    """Immutable model that rejects unknown keys, so typos never pass silently."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def format_validation_error(exc: ValidationError, *, prefix: str = "", limit: int = 20) -> str:
    """Render a pydantic error as one ``location: message`` line per problem."""
    lines = []
    errors = exc.errors(include_url=False)
    for error in errors[:limit]:
        parts = [prefix] if prefix else []
        parts.extend(str(part) for part in error["loc"])
        location = ".".join(parts) or "(root)"
        message = error["msg"]
        if error["type"] == "extra_forbidden":
            message = "unknown field (check the spelling)"
        elif error["type"] == "missing":
            message = "required field is missing"
        elif message.startswith("Value error, "):
            message = message.removeprefix("Value error, ")
        lines.append(f"  {location}: {message}")
    if len(errors) > limit:
        lines.append(f"  ... and {len(errors) - limit} more")
    return "\n".join(lines)


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``json.loads`` ``object_pairs_hook`` that fails on duplicate keys instead of keeping
    the last one."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result
