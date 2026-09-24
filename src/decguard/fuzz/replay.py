"""Replay stored property failures against a backend.

Each replayed transformed case is re-sent exactly as stored (input, option presentation),
together with its original, and judged again. The transformation is also regenerated from
the stored seed to confirm the failure is reproducible from the contract alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from decguard import __version__
from decguard.backends.base import BackendMetadata, DecisionBackend
from decguard.backends.registry import create_backend
from decguard.contracts.loader import LoadedContract, load_contract
from decguard.contracts.properties import PropertyConfig
from decguard.datasets import Case
from decguard.decisions import DecisionInput, DecisionRequest, DecisionResult
from decguard.errors import ContractError, ReportError
from decguard.fuzz.compare import Comparison, judge
from decguard.fuzz.engine import case_rng, decide_mutation
from decguard.fuzz.transforms import Mutation, NotApplicable, make_transform
from decguard.reports.gates import Status
from decguard.reports.model import Report, ensure_same_decision, load_report
from decguard.reports.properties import PropertyPair, comparison_for, property_config
from decguard.reports.render import describe_example
from decguard.runner import CaseError, decide_safely

REPLAY_VERSION: Final = "0.1"


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReplayedExample(_Section):
    kind: Literal["transformed", "reduced"]
    input: DecisionInput
    presentation: tuple[tuple[str, str], ...] | None = None
    stored_violations: tuple[str, ...]
    result: DecisionResult | None = None
    error: CaseError | None = None
    comparison: Comparison | None = None
    violations: tuple[str, ...] = ()
    reproduced: bool


class ReplayOutcome(_Section):
    id: str
    property: str
    case_id: str
    regenerated: bool | None
    """The seed regenerates exactly the stored transformation (``None``: the generator is
    not deterministic, e.g. an LLM paraphraser, so the stored text is used)."""
    original: DecisionResult | None = None
    original_error: CaseError | None = None
    examples: tuple[ReplayedExample, ...]
    reproduced: bool
    """At least one example still breaks the property."""


class ReplayReport(_Section):
    replay_version: Literal["0.1"] = REPLAY_VERSION
    decguard_version: str
    created_at: str
    source: str
    """The report whose failures were replayed."""
    contract_path: str
    contract_hash: str
    contract_changed: bool
    """The contract differs from the one the report was produced with."""
    backend: BackendMetadata
    status: Status
    """``fail`` when a failure reproduced, ``pass`` when none did."""
    exit_code: int
    outcomes: tuple[ReplayOutcome, ...]


def _select(stored: Report, ids: Sequence[str] | None) -> list[PropertyPair]:
    assert stored.properties is not None
    pairs = stored.properties.pairs
    if not ids:
        return [pair for pair in pairs if pair.failed()]
    by_id = {pair.id: pair for pair in pairs}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ReportError(
            f"no transformed case {missing[0]!r} in the report; ids look like "
            f"'<property>/<case id>/<sample>', e.g. {pairs[0].id!r}"
            if pairs
            else f"no transformed case {missing[0]!r}: the report has none"
        )
    return [by_id[i] for i in ids]


def _regenerated(
    pair: PropertyPair, prop: PropertyConfig, stored: Report, loaded: LoadedContract, case: Case
) -> bool | None:
    assert stored.properties is not None
    if pair.property == "paraphrase":
        return None
    transform = make_transform(pair.property, prop, loaded.contract.spec(), stored.properties.fuzz)
    try:
        mutations = transform.generate(
            case, case_rng(stored.properties.seed, pair.property, case.id)
        )
    except NotApplicable:
        return False
    if pair.sample >= len(mutations):
        return False
    mutation = mutations[pair.sample]
    return (mutation.steps, mutation.input, mutation.presentation) == (
        pair.steps,
        pair.input,
        pair.presentation,
    )


def replay(
    report: str | Path,
    *,
    ids: Sequence[str] | None = None,
    contract: str | Path | None = None,
    backend: str | DecisionBackend | None = None,
) -> ReplayReport:
    """Replay the failing transformed cases of a stored ``fuzz``/``all`` report (or the
    cases named by ``ids``). The contract defaults to the one recorded in the report."""
    stored = load_report(report)
    if stored.properties is None:
        raise ReportError(f"{report}: a '{stored.mode}' report has no property results to replay")
    loaded = load_contract(contract if contract is not None else stored.contract.path)
    ensure_same_decision(stored, loaded)
    spec = loaded.contract.spec()
    tolerance = loaded.contract.evaluation.probability_tolerance
    selected = _select(stored, ids)
    records = stored.records_by_id()

    if isinstance(backend, DecisionBackend):
        instance, owned = backend, False
    else:
        name = backend or stored.backend.name
        try:
            config = loaded.contract.backend_config(name)
        except ContractError as exc:
            raise ContractError(f"{exc}; pass --backend to choose one") from exc
        instance, owned = create_backend(config, decision=spec, name=name), True

    outcomes = []
    try:
        for pair in selected:
            enabled = loaded.contract.properties.configured()
            prop = enabled.get(pair.property) or property_config(
                stored.properties.config, pair.property
            )
            record = records[pair.case_id]
            case = Case(
                id=record.case_id,
                input=record.input,
                expected=record.expected,
                metadata=record.metadata,
            )
            original = decide_safely(
                instance,
                DecisionRequest(case_id=case.id, decision=spec, input=case.input),
                tolerance,
            )
            examples = [
                (
                    "transformed",
                    Mutation(pair.steps, pair.input, pair.presentation),
                    pair.violations,
                )
            ]
            if pair.reduced is not None:
                reduced = pair.reduced
                examples.append(
                    (
                        "reduced",
                        Mutation(reduced.steps, reduced.input, reduced.presentation),
                        reduced.violations,
                    )
                )
            replayed = []
            for kind, mutation, stored_violations in examples:
                outcome = decide_mutation(instance, spec, pair.id, mutation, tolerance)
                fields: dict[str, object] = {
                    "kind": kind,
                    "input": mutation.input,
                    "presentation": mutation.presentation,
                    "stored_violations": stored_violations,
                }
                if isinstance(outcome, CaseError):
                    replayed.append(ReplayedExample(**fields, error=outcome, reproduced=False))
                    continue
                comparison = None
                violations: tuple[str, ...] = ()
                if isinstance(original, DecisionResult):
                    comparison = comparison_for(prop, original, outcome)
                    violations = tuple(judge(prop, comparison).violations)
                replayed.append(
                    ReplayedExample(
                        **fields,
                        result=outcome,
                        comparison=comparison,
                        violations=violations,
                        reproduced=bool(violations),
                    )
                )
            outcomes.append(
                ReplayOutcome(
                    id=pair.id,
                    property=pair.property,
                    case_id=pair.case_id,
                    regenerated=_regenerated(pair, prop, stored, loaded, case),
                    original=original if isinstance(original, DecisionResult) else None,
                    original_error=original if isinstance(original, CaseError) else None,
                    examples=tuple(replayed),
                    reproduced=any(example.reproduced for example in replayed),
                )
            )
        metadata = instance.metadata()
    finally:
        if owned:
            instance.close()

    status = Status.FAIL if any(outcome.reproduced for outcome in outcomes) else Status.PASS
    return ReplayReport(
        decguard_version=__version__,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        source=str(report),
        contract_path=str(loaded.path),
        contract_hash=loaded.hash,
        contract_changed=loaded.hash != stored.contract.hash,
        backend=metadata,
        status=status,
        exit_code=1 if status is Status.FAIL else 0,
        outcomes=tuple(outcomes),
    )


def render_replay_text(report: ReplayReport) -> str:
    lines = [
        f"DecGuard {report.decguard_version} · replay {report.source}"
        f" · {len(report.outcomes)} case(s)",
        f"  backend   {report.backend.name}: {report.backend.provider}",
        f"  contract  {report.contract_path}"
        + ("  (changed since the report was made)" if report.contract_changed else ""),
    ]
    if not report.outcomes:
        lines += ["", "Nothing to replay: the report has no property failures."]
    for outcome in report.outcomes:
        state = "REPRODUCED" if outcome.reproduced else "not reproduced"
        regen = {True: "yes", False: "NO", None: "n/a (stored text used)"}[outcome.regenerated]
        lines += ["", f"  {outcome.id}: {state} · regenerated from seed: {regen}"]
        if outcome.original_error is not None:
            lines.append(f"    original errored: {outcome.original_error.message}")
        for example in outcome.examples:
            lines.append(
                f"    {example.kind}: {describe_example(example.presentation, example.input)}"
            )
            if example.error is not None:
                lines.append(f"      error: {example.error.kind}: {example.error.message}")
            elif example.violations:
                lines.append(f"      {'; '.join(example.violations)}")
            else:
                lines.append("      holds now")
    lines += [
        "",
        "FAIL: at least one failure reproduced"
        if report.status is Status.FAIL
        else "PASS: no failure reproduced",
    ]
    return "\n".join(lines)
