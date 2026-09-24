"""Execute a dataset against one backend with bounded concurrency."""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from pydantic import BaseModel, ConfigDict

from decguard.backends.base import DecisionBackend
from decguard.datasets import Case
from decguard.decisions import (
    DEFAULT_PROBABILITY_TOLERANCE,
    DecisionInput,
    DecisionRequest,
    DecisionResult,
    DecisionSpec,
)
from decguard.errors import BackendError, DecGuardError


class CaseError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    """``timeout``, ``unavailable``, ``invalid_response``, ``backend_error`` or ``exception``."""
    message: str


class CaseRecord(BaseModel):
    """One dataset case and what the backend made of it: a result or an error, never both."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    input: DecisionInput
    expected: str | None = None
    metadata: dict[str, Any] = {}
    result: DecisionResult | None = None
    error: CaseError | None = None


def _run_one(
    backend: DecisionBackend, spec: DecisionSpec, case: Case, tolerance: float
) -> CaseRecord:
    request = DecisionRequest(case_id=case.id, decision=spec, input=case.input)
    base = {
        "case_id": case.id,
        "input": case.input,
        "expected": case.expected,
        "metadata": case.metadata,
    }
    try:
        result = backend.decide(request, tolerance=tolerance)
    except BackendError as exc:
        return CaseRecord(**base, error=CaseError(kind=exc.kind, message=str(exc)))
    except DecGuardError:
        raise  # configuration problems abort the run
    except Exception as exc:  # a buggy plugin must not silently drop cases
        return CaseRecord(
            **base, error=CaseError(kind="exception", message=f"{type(exc).__name__}: {exc}")
        )
    return CaseRecord(**base, result=result)


def run_cases(
    backend: DecisionBackend,
    spec: DecisionSpec,
    cases: Sequence[Case],
    *,
    max_concurrency: int = 1,
    tolerance: float = DEFAULT_PROBABILITY_TOLERANCE,
) -> list[CaseRecord]:
    """Decide every case. Records come back in dataset order whatever the concurrency."""
    if max_concurrency <= 1:
        return [_run_one(backend, spec, case, tolerance) for case in cases]
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures: list[Future[CaseRecord]] = [
            pool.submit(_run_one, backend, spec, case, tolerance) for case in cases
        ]
        try:
            return [future.result() for future in futures]
        except BaseException:
            for future in futures:
                future.cancel()
            raise
