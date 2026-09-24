"""Backend adapters: one interface, many decision-model providers."""

from decguard.backends.base import (
    BackendMetadata,
    DecisionBackend,
    HealthStatus,
    validate_settings,
)
from decguard.backends.http import HttpBackend, HttpSettings
from decguard.backends.mock import MockBackend, MockRule, MockSettings
from decguard.backends.python import CallableBackend
from decguard.backends.registry import (
    BUILTIN_BACKENDS,
    ENTRY_POINT_GROUP,
    available_providers,
    backend_class,
    create_backend,
)

__all__ = [
    "BUILTIN_BACKENDS",
    "ENTRY_POINT_GROUP",
    "BackendMetadata",
    "CallableBackend",
    "DecisionBackend",
    "HealthStatus",
    "HttpBackend",
    "HttpSettings",
    "MockBackend",
    "MockRule",
    "MockSettings",
    "available_providers",
    "backend_class",
    "create_backend",
    "validate_settings",
]
