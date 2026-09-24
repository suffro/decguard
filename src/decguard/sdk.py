"""Minimal embeddable Python API."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Self

from decguard.backends import DecisionBackend, create_backend
from decguard.contracts import DEFAULT_BACKEND, LoadedContract, load_contract
from decguard.decisions import DecisionInput, DecisionRequest
from decguard.errors import ContractError, DecGuardError
from decguard.policy import PolicyDecision, apply_policy


class DecGuard:
    """Run one configured backend and apply the contract's explicit routing policy.

    A ``fallback`` result is a deterministic directive naming the configured fallback
    backend; DecGuard does not invoke it automatically, so the embedding application keeps
    control of side effects and retry/cascade limits.
    """

    def __init__(
        self,
        loaded: LoadedContract,
        backend: DecisionBackend,
        *,
        owned_backend: bool = False,
    ) -> None:
        if loaded.contract.policy is None:
            raise ContractError("the contract has no 'policy' section")
        self.loaded = loaded
        self.backend = backend
        self._owned_backend = owned_backend

    @classmethod
    def from_contract(
        cls,
        contract: LoadedContract | str | Path,
        *,
        backend: str | DecisionBackend | None = None,
        check_health: bool = False,
    ) -> Self:
        loaded = contract if isinstance(contract, LoadedContract) else load_contract(contract)
        if loaded.contract.policy is None:
            raise ContractError("the contract has no 'policy' section")
        if isinstance(backend, DecisionBackend):
            instance, owned = backend, False
        else:
            instance = create_backend(
                loaded.contract.backend_config(backend),
                decision=loaded.contract.spec(),
                name=backend or DEFAULT_BACKEND,
            )
            owned = True
        if check_health:
            try:
                health = instance.healthcheck()
            except BaseException:
                if owned:
                    instance.close()
                raise
            if health.status == "unhealthy":
                if owned:
                    instance.close()
                raise DecGuardError(f"backend {instance.name!r} is unhealthy: {health.detail}")
        return cls(loaded, instance, owned_backend=owned)

    def decide(self, input_data: DecisionInput, *, case_id: str = "sdk") -> PolicyDecision:
        contract = self.loaded.contract
        policy = contract.policy
        assert policy is not None
        result = self.backend.decide(
            DecisionRequest(case_id=case_id, decision=contract.spec(), input=input_data),
            tolerance=contract.evaluation.probability_tolerance,
        )
        return apply_policy(policy, result)

    def close(self) -> None:
        if self._owned_backend:
            self.backend.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
