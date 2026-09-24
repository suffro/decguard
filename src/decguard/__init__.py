"""DecGuard: test, verify and gate probabilistic AI decision models."""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from decguard.sdk import DecGuard

try:
    __version__ = version("decguard")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0+unknown"


def __getattr__(name: str) -> Any:
    if name == "DecGuard":
        return import_module("decguard.sdk").DecGuard
    raise AttributeError(name)


__all__ = ["DecGuard", "__version__"]
