"""DecGuard: test, verify and gate probabilistic AI decision models."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("decguard")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0+unknown"

__all__ = ["__version__"]
