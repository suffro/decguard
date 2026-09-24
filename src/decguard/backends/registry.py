"""Resolve a contract's ``provider`` to a backend class.

Built-in providers come first and cannot be shadowed. Third-party providers are installed
Python packages exposing a :class:`DecisionBackend` subclass under the
``decguard.backends`` entry-point group; contracts never name import paths directly.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from decguard.backends.base import DecisionBackend
from decguard.backends.http import HttpBackend
from decguard.backends.mock import MockBackend
from decguard.contracts.models import BackendConfig
from decguard.decisions import DecisionSpec
from decguard.errors import ContractError

ENTRY_POINT_GROUP = "decguard.backends"

BUILTIN_BACKENDS: dict[str, type[DecisionBackend]] = {
    MockBackend.provider: MockBackend,
    HttpBackend.provider: HttpBackend,
}


def available_providers() -> list[str]:
    plugins = {ep.name for ep in entry_points(group=ENTRY_POINT_GROUP)}
    return sorted(set(BUILTIN_BACKENDS) | plugins)


def backend_class(provider: str) -> type[DecisionBackend]:
    if provider in BUILTIN_BACKENDS:
        return BUILTIN_BACKENDS[provider]
    matches = entry_points(group=ENTRY_POINT_GROUP, name=provider)
    if not matches:
        raise ContractError(
            f"unknown backend provider {provider!r}; available: {', '.join(available_providers())}"
        )
    (entry_point, *_) = tuple(matches)
    try:
        loaded = entry_point.load()
    except Exception as exc:
        raise ContractError(
            f"cannot load backend provider {provider!r} from {entry_point.value}: {exc}"
        ) from exc
    if not (isinstance(loaded, type) and issubclass(loaded, DecisionBackend)):
        raise ContractError(
            f"backend provider {provider!r} ({entry_point.value}) is not a DecisionBackend"
        )
    return loaded


def create_backend(
    config: BackendConfig, *, decision: DecisionSpec, name: str = "default"
) -> DecisionBackend:
    """Build a backend from contract configuration. Performs no network I/O."""
    return backend_class(config.provider).from_config(config, name=name, decision=decision)
