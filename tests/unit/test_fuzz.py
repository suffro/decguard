"""The metamorphic engine through the Python API (``run_test(mode="fuzz"|"all")``)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from decguard.backends import CallableBackend, MockBackend, MockSettings
from decguard.contracts import load_contract
from decguard.decisions import DecisionRequest
from decguard.engine import run_test
from decguard.errors import ContractError, InvalidResponse, ReportError
from decguard.fuzz.paraphrase import OpenAIParaphraser, OpenAISettings
from decguard.reports import Report, load_report, reevaluate, write_report
from decguard.reports.gates import Status
from tests.conftest import ContractFactory, write_jsonl, write_yaml

ORDER = {"option_order": {"samples": 5, "max_tv_distance": 0.03, "max_flip_rate": 0}}
BASE = {"refund": 0.5, "reject": 0.3, "review": 0.2}


def stable(request: DecisionRequest) -> dict[str, float]:
    return {label: BASE[label] for label in request.decision.labels}


def first_option_bias(request: DecisionRequest) -> dict[str, float]:
    """Moves 40% of the mass to whichever option is listed first."""
    first = request.decision.labels[0]
    return {
        label: 0.6 * BASE[label] + (0.4 if label == first else 0.0)
        for label in request.decision.labels
    }


def check(report: Report, gate: str) -> Status:
    (found,) = [c for c in report.checks if c.gate == gate]
    return found.status


def fuzz(contract: Path, fn: Callable[[DecisionRequest], Mapping[str, float]], **kw: Any) -> Report:
    return run_test(contract, backend=CallableBackend(fn), mode=kw.pop("mode", "fuzz"), **kw)


# --- acceptance: option order ---------------------------------------------------------


def test_option_permutation_catches_an_order_sensitive_backend(
    make_contract: ContractFactory,
) -> None:
    report = fuzz(make_contract({"properties": ORDER}), first_option_bias)
    assert report.status is Status.FAIL
    assert report.exit_code == 1
    assert check(report, "option_order.max_violation_rate") is Status.FAIL
    assert check(report, "option_order.max_flip_rate") is Status.FAIL
    assert report.properties is not None
    failure = report.properties.failures()[0]
    assert failure.presentation is not None
    assert failure.result is not None
    # The transformed decision is mapped back to the canonical label order.
    assert list(failure.result.probabilities) == ["refund", "reject", "review"]
    first_shown = failure.presentation[0][1]
    assert failure.result.probabilities[first_shown] == pytest.approx(0.6 * BASE[first_shown] + 0.4)


def test_a_stable_backend_passes_the_same_test(make_contract: ContractFactory) -> None:
    report = fuzz(make_contract({"properties": ORDER}), stable)
    assert report.status is Status.PASS
    assert report.properties is not None
    (summary,) = report.properties.summaries
    assert summary.n_transformed == 5 * 5  # 5 cases x all 5 non-identity orders
    assert summary.n_violations == 0
    assert summary.max_tv_distance == 0.0


def test_probability_drift_is_measured(make_contract: ContractFactory) -> None:
    report = fuzz(make_contract({"properties": ORDER}), first_option_bias)
    assert report.properties is not None
    for pair in report.properties.pairs:
        assert pair.comparison is not None
        assert pair.presentation is not None
        moved = pair.presentation[0][1] != "refund"
        # The biased mass moves from the canonical first option to the shown first one.
        assert pair.comparison.tv_distance == pytest.approx(0.4 if moved else 0.0)
        assert pair.comparison.max_abs_delta == pytest.approx(0.4 if moved else 0.0)
        assert (pair.violations != ()) == moved


def test_mock_backend_position_bias(make_contract: ContractFactory) -> None:
    path = make_contract({"properties": ORDER})
    biased = MockBackend(MockSettings(default=BASE, position_bias=0.3))
    report = run_test(path, backend=biased, mode="fuzz")
    assert report.status is Status.FAIL
    assert (
        run_test(path, backend=MockBackend(MockSettings(default=BASE)), mode="fuzz").status
        is Status.PASS
    )


# --- determinism ----------------------------------------------------------------------


def _fingerprint(report: Report) -> list[Any]:
    assert report.properties is not None
    return [
        (p.id, p.steps, p.input, p.presentation, p.result and p.result.probabilities, p.comparison)
        for p in report.properties.pairs
    ]


ALL_TEXT = {
    "irrelevant_context": {"insertions": 2, "max_tv_distance": 0.05},
    "repeated_context": {"max_tv_distance": 0.05},
    "whitespace": {"max_tv_distance": 0.05},
    "label_format": {"max_tv_distance": 0.05},
    **ORDER,
}


def test_fuzzing_is_deterministic_under_a_fixed_seed(make_contract: ContractFactory) -> None:
    path = make_contract({"properties": ALL_TEXT, "fuzz": {"seed": 11}})
    first = run_test(path, mode="fuzz")
    second = run_test(path, mode="fuzz", max_concurrency=8)
    assert _fingerprint(first) == _fingerprint(second)
    other = run_test(path, mode="fuzz", seed=12)
    assert other.properties is not None
    assert other.properties.seed == 12
    assert _fingerprint(other) != _fingerprint(first)


# --- mapping labels, errors, skips ----------------------------------------------------


def test_label_format_sends_shown_labels_and_maps_back(make_contract: ContractFactory) -> None:
    seen: list[tuple[str, ...]] = []

    def backend(request: DecisionRequest) -> dict[str, float]:
        seen.append(request.decision.labels)
        # Answer by meaning, keyed exactly as shown.
        return {
            label: BASE[label.strip('"[]').lower().split(" ")[-1]]
            for label in request.decision.labels
        }

    props = {"label_format": {"styles": ["upper", "quoted"], "samples": 2, "max_tv_distance": 0.0}}
    report = fuzz(make_contract({"properties": props}), backend)
    assert report.status is Status.PASS, report.checks
    assert ("REFUND", "REJECT", "REVIEW") in seen
    assert ('"refund"', '"reject"', '"review"') in seen


def test_backend_errors_on_transformed_cases_are_counted(make_contract: ContractFactory) -> None:
    def backend(request: DecisionRequest) -> dict[str, float]:
        if request.decision.labels[0] == "review":
            raise InvalidResponse("boom")
        return stable(request)

    report = fuzz(make_contract({"properties": ORDER}), backend)
    assert report.properties is not None
    (summary,) = report.properties.summaries
    assert summary.n_errors == 2 * 5
    assert summary.errors_by_kind == {"invalid_response": 10}
    assert check(report, "option_order.max_error_rate") is Status.FAIL
    assert report.status is Status.FAIL


def test_an_errored_original_is_recorded_not_dropped(make_contract: ContractFactory) -> None:
    def backend(request: DecisionRequest) -> dict[str, float]:
        if request.case_id == "c3":
            raise InvalidResponse("boom")
        return stable(request)

    report = fuzz(make_contract({"properties": ORDER}), backend)
    assert report.properties is not None
    errored = [p for p in report.properties.pairs if p.error is not None]
    assert {p.case_id for p in errored} == {"c3"}
    assert {p.error.kind for p in errored if p.error} == {"original_error"}


def test_untransformable_cases_are_skipped_visibly(make_contract: ContractFactory) -> None:
    cases = [{"id": "o1", "input": {"text": "hi there."}}, {"id": "o2", "input": {"text": "yo."}}]
    path = make_contract(
        {"properties": {"irrelevant_context": {"max_tv_distance": 0.1}}}, cases=cases
    )
    report = fuzz(path, stable)
    assert report.properties is not None
    assert [(s.case_id, s.reason) for s in report.properties.skipped] == [
        ("o1", "object input has no text to transform (set fuzz.text_field)"),
        ("o2", "object input has no text to transform (set fuzz.text_field)"),
    ]
    assert report.status is Status.FAIL  # nothing demonstrated
    assert (
        "no case could be transformed"
        in {c.gate: c.message for c in report.checks}["irrelevant_context.max_violation_rate"]
    )
    with_field = make_contract(
        {
            "properties": {"irrelevant_context": {"max_tv_distance": 0.1}},
            "fuzz": {"text_field": "text"},
        },
        cases=cases,
    )
    assert fuzz(with_field, stable).status is Status.PASS


def test_unknown_or_missing_properties_are_configuration_errors(
    make_contract: ContractFactory,
) -> None:
    with pytest.raises(ContractError, match="enables no properties"):
        fuzz(make_contract(), stable)
    with pytest.raises(ContractError, match="'whitespace' is not enabled"):
        fuzz(make_contract({"properties": ORDER}), stable, properties=["whitespace"])


def test_only_selected_properties_run(make_contract: ContractFactory) -> None:
    report = fuzz(make_contract({"properties": ALL_TEXT}), stable, properties=["whitespace"])
    assert report.properties is not None
    assert [s.property for s in report.properties.summaries] == ["whitespace"]
    assert {c.gate.split(".")[0] for c in report.checks} == {"whitespace"}


# --- minimization ---------------------------------------------------------------------


def test_failures_are_minimized_to_the_offending_fragment(make_contract: ContractFactory) -> None:
    def backend(request: DecisionRequest) -> dict[str, float]:
        text = str(request.input)
        if "TRIGGER" in text:
            return {"refund": 0.1, "reject": 0.1, "review": 0.8}
        return stable(request)

    props = {
        "irrelevant_context": {
            "fragments": ["Calm A.", "Calm B.", "TRIGGER here."],
            "insertions": 4,
            "samples": 4,
            "max_tv_distance": 0.05,
        }
    }
    report = fuzz(make_contract({"properties": props}), backend)
    assert report.properties is not None
    failing = report.properties.failures()
    assert failing
    for pair in failing:
        if len(pair.steps) > 1:
            assert pair.reduced is not None
            assert [step["text"] for step in pair.reduced.steps] == ["TRIGGER here."]
            assert pair.reduced.violations
            assert 0 < pair.reduced.backend_calls <= 32
    no_min = fuzz(make_contract({"properties": props}), backend, minimize=False)
    assert no_min.properties is not None
    assert all(p.reduced is None for p in no_min.properties.pairs)


# --- noul inversion, score monotonicity -----------------------------------------------


def _noul(make_contract: ContractFactory) -> Path:
    return make_contract(
        {
            "decision": {"name": "is_positive", "type": "noul"},
            "backend": {"provider": "mock"},
            "requirements": None,
            "properties": {
                "inversion": {
                    "rewrites": [{"find": " is ", "replace": " is not "}],
                    "max_tv_distance": 0.1,
                    "max_flip_rate": 0,
                },
                "irrelevant_context": {"max_tv_distance": 0.05},
            },
        },
        cases=[
            {"id": "n1", "input": "The service is good.", "expected": "yes"},
            {"id": "n2", "input": "The food is great.", "expected": "yes"},
            {"id": "n3", "input": "Nothing to negate here."},
        ],
    )


def negation_aware(request: DecisionRequest) -> dict[str, float]:
    negated = " not " in str(request.input)
    return {"yes": 0.1, "no": 0.9} if negated else {"yes": 0.9, "no": 0.1}


def test_noul_inversion_expects_the_answer_to_swap(make_contract: ContractFactory) -> None:
    path = _noul(make_contract)
    good = fuzz(path, negation_aware)
    assert good.status is Status.PASS, good.checks
    assert good.properties is not None
    assert [s.case_id for s in good.properties.skipped] == ["n3"]
    inversion = next(s for s in good.properties.summaries if s.property == "inversion")
    assert inversion.relation == "swapped"
    assert inversion.n_evaluated == 2

    bad = fuzz(path, lambda request: {"yes": 0.9, "no": 0.1})
    assert check(bad, "inversion.max_flip_rate") is Status.FAIL
    assert check(bad, "irrelevant_context.max_violation_rate") is Status.PASS


def _score(make_contract: ContractFactory) -> Path:
    return make_contract(
        {
            "decision": {"name": "severity", "type": "score", "levels": [1, 2, 3]},
            "backend": {"provider": "mock"},
            "requirements": None,
            "properties": {
                "monotonic": {"field": "users", "deltas": [10, 1000], "max_flip_rate": 0},
                "irrelevant_context": {"max_tv_distance": 0.05},
            },
            "fuzz": {"text_field": "text"},
        },
        cases=[
            {"id": "s1", "input": {"text": "Login is slow.", "users": 5}, "expected": 1},
            {"id": "s2", "input": {"text": "Checkout fails.", "users": 500}, "expected": 2},
        ],
    )


def by_users(increasing: bool) -> Callable[[DecisionRequest], dict[str, float]]:
    def backend(request: DecisionRequest) -> dict[str, float]:
        assert isinstance(request.input, dict)
        high = request.input["users"] >= 100
        if not increasing:
            high = not high
        return {"1": 0.1, "2": 0.2, "3": 0.7} if high else {"1": 0.7, "2": 0.2, "3": 0.1}

    return backend


def test_score_monotonicity(make_contract: ContractFactory) -> None:
    path = _score(make_contract)
    good = fuzz(path, by_users(increasing=True))
    assert good.status is Status.PASS, good.checks
    bad = fuzz(path, by_users(increasing=False))
    assert check(bad, "monotonic.max_violation_rate") is Status.FAIL
    assert check(bad, "monotonic.max_flip_rate") is Status.FAIL
    assert bad.properties is not None
    monotonic = next(s for s in bad.properties.summaries if s.property == "monotonic")
    assert monotonic.max_level_decrease == pytest.approx(1.2)
    failure = next(p for p in bad.properties.failures() if p.property == "monotonic")
    assert any("against 'increasing'" in v for v in failure.violations)


# --- paraphrase providers -------------------------------------------------------------


def test_identity_paraphrase_catches_a_nondeterministic_backend(
    make_contract: ContractFactory,
) -> None:
    path = make_contract({"properties": {"paraphrase": {"max_tv_distance": 0.0}}})
    assert fuzz(path, stable).status is Status.PASS
    calls = iter(range(10_000))

    def flaky(request: DecisionRequest) -> dict[str, float]:
        return (
            {"refund": 0.5, "reject": 0.3, "review": 0.2}
            if next(calls) % 2
            else BASE
            | {
                "refund": 0.4,
                "reject": 0.4,
            }
        )

    assert fuzz(path, flaky).status is Status.FAIL


def test_file_paraphrases(make_contract: ContractFactory, tmp_path: Path) -> None:
    write_jsonl(
        tmp_path / "paraphrases.jsonl",
        [
            {"id": "c1", "paraphrases": ["it came broken", "arrived in pieces"]},
            {"input": "I changed my mind", "paraphrases": ["I no longer want it"]},
        ],
    )
    props = {
        "paraphrase": {
            "source": {"provider": "file", "path": "paraphrases.jsonl"},
            "samples": 2,
            "max_flip_rate": 0,
        }
    }
    report = run_test(make_contract({"properties": props}), mode="fuzz")
    assert report.properties is not None
    inputs = {p.id: p.input for p in report.properties.pairs}
    assert inputs == {
        "paraphrase/c1/0": "it came broken",
        "paraphrase/c1/1": "arrived in pieces",
        "paraphrase/c2/0": "I no longer want it",
    }
    assert {s.case_id for s in report.properties.skipped} == {"c3", "c4", "c5"}
    provenance = report.properties.pairs[0].provenance
    assert provenance["provider"] == "file"
    assert provenance["hash"].startswith("sha256:")
    # The mock's "damaged" rule no longer matches the paraphrase: a flip.
    assert check(report, "paraphrase.max_flip_rate") is Status.FAIL


def test_openai_paraphraser_parses_and_records_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append({"auth": request.headers.get("authorization"), **json.loads(request.content)})
        content = '```json\n["first wording", "second wording"]\n```'
        return httpx.Response(
            200,
            json={"model": "gpt-x-2025", "choices": [{"message": {"content": content}}]},
        )

    monkeypatch.setenv("PARA_KEY", "secret-token")
    paraphraser = OpenAIParaphraser(
        OpenAISettings(model="gpt-x", url="https://llm.example/v1", api_key_env="PARA_KEY"),
        transport=httpx.MockTransport(handler),
    )
    assert paraphraser.paraphrase("original", case_id="c", n=2, seed=5) == [
        "first wording",
        "second wording",
    ]
    assert sent[0]["auth"] == "Bearer secret-token"
    assert sent[0]["seed"] == 5
    assert sent[0]["temperature"] == 0.0
    provenance = paraphraser.provenance()
    assert provenance["response_model"] == "gpt-x-2025"
    assert "secret-token" not in json.dumps(provenance)


def test_openai_paraphraser_failures_become_case_errors(
    make_contract: ContractFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    paraphraser = OpenAIParaphraser(
        OpenAISettings(model="m", api_key_env=None),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []})),
    )
    path = make_contract({"properties": {"paraphrase": {"max_flip_rate": 0}}})
    report = run_test(path, mode="fuzz", paraphraser=paraphraser)
    assert report.properties is not None
    assert {p.error.kind for p in report.properties.pairs if p.error} == {"paraphrase_error"}
    assert report.status is Status.FAIL


# --- reports --------------------------------------------------------------------------


def test_all_mode_combines_golden_and_property_checks(make_contract: ContractFactory) -> None:
    report = run_test(make_contract({"properties": ORDER}), mode="all")
    gates = [c.gate for c in report.checks]
    assert "min_accuracy" in gates
    assert "option_order.max_violation_rate" in gates
    assert report.mode == "all"


def test_fuzz_report_round_trips_and_detects_tampering(
    make_contract: ContractFactory, tmp_path: Path
) -> None:
    report = fuzz(make_contract({"properties": ORDER}), first_option_bias)
    path = tmp_path / "fuzz.json"
    write_report(report, path)
    loaded = load_report(path)
    assert loaded.properties == report.properties

    def tampered(edit: Callable[[dict[str, Any]], None]) -> Path:
        data = json.loads(path.read_text())
        edit(data)
        out = tmp_path / "tampered.json"
        out.write_text(json.dumps(data))
        return out

    def hide_violation(data: dict[str, Any]) -> None:
        pair = next(p for p in data["properties"]["pairs"] if p["violations"])
        pair["violations"] = []
        pair["reduced"] = None

    def shrink_distance(data: dict[str, Any]) -> None:
        pair = next(p for p in data["properties"]["pairs"] if p["violations"])
        pair["comparison"]["tv_distance"] = 0.0

    def drop_mode(data: dict[str, Any]) -> None:
        data["mode"] = "test"

    for edit, message in [
        (hide_violation, "violations do not match the property settings"),
        (shrink_distance, "comparison does not match the stored results"),
        (drop_mode, "'properties' must be present exactly in 'fuzz' and 'all' reports"),
    ]:
        with pytest.raises(ReportError, match=re.escape(message)):
            load_report(tampered(edit))


def test_reevaluate_reapplies_property_tolerances(
    make_contract: ContractFactory, tmp_path: Path
) -> None:
    report = fuzz(make_contract({"properties": ORDER}), first_option_bias)
    assert report.status is Status.FAIL
    loose = {"option_order": {"max_tv_distance": 0.5}}
    relaxed = reevaluate(
        report, load_contract(make_contract({"properties": loose}, name="loose.yaml"))
    )
    assert relaxed.status is Status.PASS
    assert relaxed.properties is not None
    assert not relaxed.properties.failures()
    # Newly enabled properties were not run, so they cannot pass.
    more = {**loose, "whitespace": {"max_tv_distance": 0.1}}
    extended = reevaluate(
        report, load_contract(make_contract({"properties": more}, name="more.yaml"))
    )
    assert (
        "the property was not run"
        in {c.gate: c.message for c in extended.checks}["whitespace.max_violation_rate"]
    )
    write_report(extended, tmp_path / "extended.json")
    assert load_report(tmp_path / "extended.json").status is Status.FAIL


def test_contract_file_with_properties_validates(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path / "c.yaml",
        {
            "schema_version": "0.1",
            "decision": {"name": "d", "type": "choice", "options": ["a", "b"]},
            "backend": {"provider": "mock"},
            "properties": {"paraphrase": {"source": {"provider": "nope"}, "max_flip_rate": 0}},
        },
    )
    write_jsonl(tmp_path / "cases.jsonl", [{"input": "x"}])
    with pytest.raises(ContractError, match="unknown paraphrase provider 'nope'"):
        run_test(path, dataset=tmp_path / "cases.jsonl", mode="fuzz")
