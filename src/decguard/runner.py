"""Execute a dataset against one backend with bounded concurrency."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

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

T = TypeVar("T")
R = TypeVar("R")


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

    @model_validator(mode="after")
    def _result_xor_error(self) -> CaseRecord:
        if (self.result is None) == (self.error is None):
            raise ValueError("a case record must have exactly one of 'result' or 'error'")
        if self.result is not None and self.result.case_id != self.case_id:
            raise ValueError(
                f"result.case_id {self.result.case_id!r} does not match case_id {self.case_id!r}"
            )
        return self


def decide_safely(
    backend: DecisionBackend, request: DecisionRequest, tolerance: float
) -> DecisionResult | CaseError:
    """Decide one request; per-request failures become a :class:`CaseError`."""
    try:
        return backend.decide(request, tolerance=tolerance)
    except BackendError as exc:
        return CaseError(kind=exc.kind, message=str(exc))
    except DecGuardError:
        raise  # configuration problems abort the run
    except Exception as exc:  # a buggy plugin must not silently drop cases
        return CaseError(kind="exception", message=f"{type(exc).__name__}: {exc}")


def map_ordered(fn: Callable[[T], R], items: Sequence[T], *, max_concurrency: int) -> list[R]:
    """``[fn(item) for item in items]`` on at most ``max_concurrency`` threads, in order."""
    if max_concurrency <= 1 or len(items) <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures: list[Future[R]] = [pool.submit(fn, item) for item in items]
        try:
            return [future.result() for future in futures]
        except BaseException:
            for future in futures:
                future.cancel()
            raise


def _run_one(
    backend: DecisionBackend, spec: DecisionSpec, case: Case, tolerance: float
) -> CaseRecord:
    request = DecisionRequest(case_id=case.id, decision=spec, input=case.input)
    outcome = decide_safely(backend, request, tolerance)
    base = {
        "case_id": case.id,
        "input": case.input,
        "expected": case.expected,
        "metadata": case.metadata,
    }
    if isinstance(outcome, CaseError):
        return CaseRecord(**base, error=outcome)
    return CaseRecord(**base, result=outcome)


def run_cases(
    backend: DecisionBackend,
    spec: DecisionSpec,
    cases: Sequence[Case],
    *,
    max_concurrency: int = 1,
    tolerance: float = DEFAULT_PROBABILITY_TOLERANCE,
) -> list[CaseRecord]:
    """Decide every case. Records come back in dataset order whatever the concurrency."""
    return map_ordered(
        lambda case: _run_one(backend, spec, case, tolerance),
        cases,
        max_concurrency=max_concurrency,
    )
