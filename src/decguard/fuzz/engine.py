"""Run a contract's metamorphic properties against a backend.

original decision -> controlled transformation -> new decision -> property comparison.
The original decisions are the golden run's results; every transformed case is recorded
with its steps, seed-derived sample index, result (mapped back to contract labels),
comparison and violations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from decguard.backends.base import DecisionBackend
from decguard.contracts.loader import LoadedContract
from decguard.contracts.properties import Fuzz, Properties, PropertyConfig, PropertyName
from decguard.datasets import Case
from decguard.decisions import (
    TOLERANCE_CONTEXT_KEY,
    DecisionRequest,
    DecisionResult,
    DecisionSpec,
    select_label,
)
from decguard.errors import BackendError, ContractError, DecGuardError
from decguard.fuzz.compare import judge
from decguard.fuzz.paraphrase import Paraphraser, create_paraphraser
from decguard.fuzz.rng import Rng
from decguard.fuzz.transforms import Mutation, NotApplicable, Transform, is_no_op, make_transform
from decguard.reports.properties import (
    ORIGINAL_ERROR,
    PropertyPair,
    PropertyRun,
    ReducedExample,
    Skip,
    assemble_run,
    comparison_for,
)
from decguard.runner import CaseError, CaseRecord, decide_safely, map_ordered


def pair_id(name: str, case_id: str, sample: int) -> str:
    return f"{name}/{case_id}/{sample}"


def case_rng(seed: int, name: str, case_id: str) -> Rng:
    """Each (property, case) draws from its own stream, so adding cases or properties never
    changes the transformations generated for the others."""
    return Rng(seed, name, case_id)


def select_properties(config: Properties, only: Sequence[str] | None) -> Properties:
    enabled = config.configured()
    if only:
        unknown = [name for name in only if name not in enabled]
        if unknown:
            raise ContractError(
                f"property {unknown[0]!r} is not enabled in the contract; enabled: "
                + (", ".join(enabled) or "none")
            )
        config = Properties(**{name: getattr(config, name) for name in only})
    if not config.configured():
        raise ContractError("the contract enables no properties; add a 'properties' section")
    return config


def to_contract_labels(
    result: DecisionResult,
    presentation: Sequence[tuple[str, str]],
    spec: DecisionSpec,
    tolerance: float,
) -> DecisionResult:
    """Map a decision over shown labels back to the contract labels in canonical order."""
    by_label = {label: result.probabilities[shown] for shown, label in presentation}
    probabilities = {label: by_label[label] for label in spec.labels}
    selected = select_label(spec.labels, probabilities)
    return DecisionResult.model_validate(
        {
            **result.model_dump(),
            "decision": spec.name,
            "labels": spec.labels,
            "probabilities": probabilities,
            "selected": selected,
            "confidence": probabilities[selected],
        },
        context={TOLERANCE_CONTEXT_KEY: tolerance},
    )


def decide_mutation(
    backend: DecisionBackend,
    spec: DecisionSpec,
    request_id: str,
    mutation: Mutation,
    tolerance: float,
) -> DecisionResult | CaseError:
    presentation = mutation.presentation or tuple((label, label) for label in spec.labels)
    shown = spec.model_copy(update={"labels": tuple(shown for shown, _ in presentation)})
    request = DecisionRequest(case_id=request_id, decision=shown, input=mutation.input)
    outcome = decide_safely(backend, request, tolerance)
    if isinstance(outcome, CaseError) or mutation.presentation is None:
        return outcome
    return to_contract_labels(outcome, presentation, spec, tolerance)


@dataclass(frozen=True)
class _Planned:
    name: PropertyName
    config: PropertyConfig
    transform: Transform[Any]
    case: Case
    sample: int
    mutation: Mutation | None
    error: CaseError | None = None

    @property
    def id(self) -> str:
        return pair_id(self.name, self.case.id, self.sample)


class PropertyRunner:
    def __init__(
        self,
        backend: DecisionBackend,
        loaded: LoadedContract,
        *,
        max_concurrency: int,
        seed: int | None = None,
        only: Sequence[str] | None = None,
        minimize: bool | None = None,
        paraphraser: Paraphraser | None = None,
    ) -> None:
        contract = loaded.contract
        self.backend = backend
        self.spec = contract.spec()
        self.tolerance = contract.evaluation.probability_tolerance
        self.max_concurrency = max_concurrency
        updates: dict[str, Any] = {}
        if seed is not None:
            updates["seed"] = seed
        if minimize is not None:
            updates["minimize"] = minimize
        self.fuzz: Fuzz = contract.fuzz.model_copy(update=updates)
        self.config = select_properties(contract.properties, only)
        self._owned_paraphraser = False
        paraphrase = self.config.paraphrase
        if paraphrase is not None and paraphrase.enabled and paraphraser is None:
            paraphraser = create_paraphraser(paraphrase.source, base_dir=loaded.path.parent)
            self._owned_paraphraser = True
        self.paraphraser = paraphraser
        self.transforms = {
            name: make_transform(name, prop, self.spec, self.fuzz, paraphraser)
            for name, prop in self.config.configured().items()
        }

    def close(self) -> None:
        if self._owned_paraphraser and self.paraphraser is not None:
            self.paraphraser.close()

    def plan(self, cases: Sequence[Case]) -> tuple[list[_Planned], list[Skip]]:
        planned: list[_Planned] = []
        skipped: list[Skip] = []
        for name, prop in self.config.configured().items():
            transform = self.transforms[name]
            for case in cases:
                try:
                    mutations = transform.generate(case, case_rng(self.fuzz.seed, name, case.id))
                except NotApplicable as exc:
                    skipped.append(Skip(property=name, case_id=case.id, reason=str(exc)))
                    continue
                except BackendError as exc:  # e.g. the paraphrase provider failed
                    error = CaseError(kind=exc.kind, message=str(exc))
                    planned.append(_Planned(name, prop, transform, case, 0, None, error))
                    continue
                except DecGuardError:
                    raise
                except Exception as exc:  # a buggy paraphrase plugin must not drop cases
                    error = CaseError(kind="exception", message=f"{type(exc).__name__}: {exc}")
                    planned.append(_Planned(name, prop, transform, case, 0, None, error))
                    continue
                planned += [
                    _Planned(name, prop, transform, case, k, mutation)
                    for k, mutation in enumerate(mutations)
                ]
        return planned, skipped

    def run(self, cases: Sequence[Case], records: Sequence[CaseRecord]) -> PropertyRun:
        originals = {record.case_id: record for record in records}
        planned, skipped = self.plan(cases)

        def execute(item: _Planned) -> PropertyPair:
            return self._evaluate(item, originals[item.case.id])

        pairs = map_ordered(execute, planned, max_concurrency=self.max_concurrency)

        if self.fuzz.minimize and self.fuzz.max_minimize_calls > 0:
            failing = [
                index
                for index, (item, pair) in enumerate(zip(planned, pairs, strict=True))
                if pair.violations and item.config.reducible
            ]

            def reduce(index: int) -> ReducedExample | None:
                before = originals[planned[index].case.id].result
                assert before is not None
                return self._minimize(planned[index], before)

            for index, reduced in zip(
                failing,
                map_ordered(reduce, failing, max_concurrency=self.max_concurrency),
                strict=True,
            ):
                if reduced is not None:
                    pairs[index] = pairs[index].model_copy(update={"reduced": reduced})

        return assemble_run(
            seed=self.fuzz.seed,
            fuzz=self.fuzz,
            config=self.config,
            pairs=pairs,
            skipped=skipped,
            n_cases=len(cases),
        )

    def _evaluate(self, item: _Planned, original: CaseRecord) -> PropertyPair:
        base: dict[str, Any] = {
            "id": item.id,
            "property": item.name,
            "case_id": item.case.id,
            "sample": item.sample,
            "steps": item.mutation.steps if item.mutation else (),
            "provenance": item.mutation.provenance if item.mutation else {},
            "input": item.mutation.input if item.mutation else item.case.input,
            "presentation": item.mutation.presentation if item.mutation else None,
        }
        if item.error is not None:
            return PropertyPair(**base, error=item.error)
        before = original.result
        if before is None:
            assert original.error is not None
            error = CaseError(
                kind=ORIGINAL_ERROR,
                message=f"the original case errored ({original.error.kind}), nothing to compare",
            )
            return PropertyPair(**base, error=error)
        assert item.mutation is not None
        outcome = decide_mutation(self.backend, self.spec, item.id, item.mutation, self.tolerance)
        if isinstance(outcome, CaseError):
            return PropertyPair(**base, error=outcome)
        comparison = comparison_for(item.config, before, outcome)
        return PropertyPair(
            **base,
            result=outcome,
            comparison=comparison,
            violations=tuple(judge(item.config, comparison).violations),
        )

    def _minimize(self, item: _Planned, before: DecisionResult) -> ReducedExample | None:
        """Greedy shrinking: take the first smaller transformation that still fails, repeat
        until none does or the call budget is spent."""
        assert item.mutation is not None
        budget = self.fuzz.max_minimize_calls
        calls = 0
        steps = item.mutation.steps
        best: ReducedExample | None = None
        improved = True
        while improved and calls < budget:
            improved = False
            for candidate in item.transform.reductions(steps):
                if calls >= budget:
                    break
                mutation = item.transform.apply(item.case.input, candidate)
                if is_no_op(item.case.input, mutation):
                    continue
                calls += 1
                outcome = decide_mutation(
                    self.backend, self.spec, item.id, mutation, self.tolerance
                )
                if isinstance(outcome, CaseError):
                    continue
                comparison = comparison_for(item.config, before, outcome)
                violations = judge(item.config, comparison).violations
                if violations:
                    steps = candidate
                    best = ReducedExample(
                        steps=candidate,
                        input=mutation.input,
                        presentation=mutation.presentation,
                        result=outcome,
                        comparison=comparison,
                        violations=tuple(violations),
                        backend_calls=calls,
                    )
                    improved = True
                    break
        if best is not None and best.backend_calls != calls:
            best = best.model_copy(update={"backend_calls": calls})
        return best


def run_properties(
    backend: DecisionBackend,
    loaded: LoadedContract,
    cases: Sequence[Case],
    records: Sequence[CaseRecord],
    *,
    max_concurrency: int,
    seed: int | None = None,
    only: Sequence[str] | None = None,
    minimize: bool | None = None,
    paraphraser: Paraphraser | None = None,
) -> PropertyRun:
    runner = PropertyRunner(
        backend,
        loaded,
        max_concurrency=max_concurrency,
        seed=seed,
        only=only,
        minimize=minimize,
        paraphraser=paraphraser,
    )
    try:
        return runner.run(cases, records)
    finally:
        runner.close()
