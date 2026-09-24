"""Load contracts from YAML/JSON files, treating them as untrusted input."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from decguard._validation import format_validation_error, reject_duplicate_json_keys
from decguard.contracts.models import Contract
from decguard.errors import ContractError

_MAX_CONTRACT_BYTES = 1_000_000


@dataclass(frozen=True)
class LoadedContract:
    contract: Contract
    path: Path
    hash: str
    """``sha256:<hex>`` of the normalized contract, stable across formatting and key order."""

    def resolve(self, relative: str) -> Path:
        """Resolve a path written in the contract relative to the contract's directory."""
        return self.path.parent / relative


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys instead of keeping the last."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def parse_document(text: str, *, source: str, json_only: bool = False) -> Any:
    """Parse YAML (or JSON, which YAML also accepts) with duplicate-key detection."""
    try:
        if json_only:
            return json.loads(text, object_pairs_hook=reject_duplicate_json_keys)
        return yaml.load(text, Loader=_UniqueKeyLoader)
    except (yaml.YAMLError, ValueError) as exc:
        raise ContractError(f"{source}: cannot parse file:\n  {exc}") from exc


def parse_contract(data: Any, *, source: str = "<contract>") -> Contract:
    if not isinstance(data, Mapping):
        raise ContractError(f"{source}: a contract must be a mapping at the top level")
    try:
        return Contract.model_validate(data)
    except ValidationError as exc:
        raise ContractError(f"{source}: invalid contract:\n{format_validation_error(exc)}") from exc


def contract_hash(contract: Contract) -> str:
    canonical = json.dumps(
        contract.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_contract(path: str | Path) -> LoadedContract:
    path = Path(path)
    source = str(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"{source}: cannot read contract: {exc.strerror or exc}") from exc
    if len(raw) > _MAX_CONTRACT_BYTES:
        raise ContractError(f"{source}: contract is larger than {_MAX_CONTRACT_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{source}: contract is not valid UTF-8") from exc
    data = parse_document(text, source=source, json_only=path.suffix.lower() == ".json")
    contract = parse_contract(data, source=source)
    return LoadedContract(contract=contract, path=path, hash=contract_hash(contract))
