"""Exception hierarchy.

Every error DecGuard raises on purpose derives from :class:`DecGuardError`. The CLI maps
these to exit code 2 (configuration/runtime error); exit code 1 is reserved for failed
reliability gates.
"""

from __future__ import annotations

from typing import ClassVar


class DecGuardError(Exception):
    """Base class for all DecGuard errors."""


class ContractError(DecGuardError):
    """A contract, or backend configuration derived from it, is invalid."""


class DatasetError(DecGuardError):
    """A dataset file is missing, malformed or inconsistent with its contract."""


class ReportError(DecGuardError):
    """A stored report cannot be read or is inconsistent with a contract."""


class BackendError(DecGuardError):
    """A backend failed to produce a decision for one case.

    The runner records these per case (they count as errored cases) instead of aborting
    the whole run. ``kind`` is the stable machine-readable category used in reports.
    """

    kind: ClassVar[str] = "backend_error"


class BackendTimeout(BackendError):
    kind: ClassVar[str] = "timeout"


class BackendUnavailable(BackendError):
    kind: ClassVar[str] = "unavailable"


class InvalidResponse(BackendError):
    """The backend answered, but the answer is not a valid probability distribution."""

    kind: ClassVar[str] = "invalid_response"
