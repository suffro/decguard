"""End-to-end test runs, shared by the CLI and the Python API."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from decguard.backends.base import DecisionBackend
from decguard.backends.registry import create_backend
from decguard.contracts.loader import LoadedContract, load_contract
from decguard.contracts.models import DEFAULT_BACKEND
from decguard.datasets import Dataset, load_dataset
from decguard.errors import ContractError, DecGuardError
from decguard.fuzz.engine import run_properties, select_properties
from decguard.fuzz.paraphrase import Paraphraser
from decguard.reports.model import DatasetInfo, Mode, Report, build_report
from decguard.runner import run_cases


def resolve_dataset(loaded: LoadedContract, dataset: str | Path | None) -> Dataset:
    """Load ``dataset`` if given, else the contract's own ``dataset`` reference."""
    if dataset is not None:
        path = Path(dataset)
    elif loaded.contract.dataset is not None:
        path = loaded.resolve(loaded.contract.dataset)
    else:
        raise ContractError(
            f"{loaded.path}: no dataset given; set 'dataset' in the contract or pass --dataset"
        )
    return load_dataset(path, loaded.contract.spec())


def run_test(
    contract: LoadedContract | str | Path,
    *,
    dataset: str | Path | None = None,
    backend: str | DecisionBackend | None = None,
    max_concurrency: int | None = None,
    check_health: bool = True,
    mode: Mode = "test",
    seed: int | None = None,
    properties: Sequence[str] | None = None,
    minimize: bool | None = None,
    paraphraser: Paraphraser | None = None,
) -> Report:
    """Run a contract's golden dataset against a backend and evaluate it.

    ``mode``: ``test`` checks the golden gates, ``fuzz`` the metamorphic properties (on top
    of the same golden decisions), ``all`` both. ``seed``, ``properties`` (names to run)
    and ``minimize`` override the contract's ``fuzz`` settings.

    ``backend`` is a backend name from the contract (default: the top-level ``backend``) or
    a ready :class:`DecisionBackend` instance. Raises :class:`DecGuardError` for
    configuration/runtime problems; gate failures are reported, not raised.
    """
    loaded = contract if isinstance(contract, LoadedContract) else load_contract(contract)
    spec = loaded.contract.spec()
    if mode != "test":
        select_properties(loaded.contract.properties, properties)  # fail before any call
    data = resolve_dataset(loaded, dataset)
    concurrency = max_concurrency or loaded.contract.evaluation.max_concurrency

    if isinstance(backend, DecisionBackend):
        instance, owned = backend, False
    else:
        instance = create_backend(
            loaded.contract.backend_config(backend),
            decision=spec,
            name=backend or DEFAULT_BACKEND,
        )
        owned = True
    try:
        health = instance.healthcheck() if check_health else None
        if health is not None and health.status == "unhealthy":
            raise DecGuardError(f"backend {instance.name!r} is unhealthy: {health.detail}")
        records = run_cases(
            instance,
            spec,
            data.cases,
            max_concurrency=concurrency,
            tolerance=loaded.contract.evaluation.probability_tolerance,
        )
        if records and all(record.error is not None for record in records):
            first = records[0].error
            assert first is not None
            raise DecGuardError(
                f"backend {instance.name!r} failed on every case; first error: "
                f"{first.kind}: {first.message}"
            )
        run = None
        if mode != "test":
            run = run_properties(
                instance,
                loaded,
                data.cases,
                records,
                max_concurrency=concurrency,
                seed=seed,
                only=properties,
                minimize=minimize,
                paraphraser=paraphraser,
            )
        metadata = instance.metadata()
    finally:
        if owned:
            instance.close()

    return build_report(
        loaded,
        DatasetInfo(
            path=str(data.path),
            hash=data.hash,
            n_cases=len(data.cases),
            n_labeled=data.n_labeled,
        ),
        metadata,
        records,
        health=health,
        mode=mode,
        properties=run,
    )
