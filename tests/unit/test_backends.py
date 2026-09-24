from __future__ import annotations

from importlib.metadata import EntryPoint
from typing import Any

import pytest

from decguard.backends import (
    CallableBackend,
    DecisionBackend,
    MockBackend,
    available_providers,
    backend_class,
    create_backend,
    registry,
)
from decguard.contracts import BackendConfig
from decguard.decisions import DecisionRequest, DecisionSpec, DecisionType, Prediction
from decguard.errors import ContractError, InvalidResponse

SPEC = DecisionSpec(name="d", type=DecisionType.CHOICE, labels=("a", "b", "c"))


def request(text: str, case_id: str = "c1") -> DecisionRequest:
    return DecisionRequest(case_id=case_id, decision=SPEC, input=text)


def test_mock_hash_fallback_is_deterministic_and_seeded() -> None:
    backend = MockBackend()
    first = backend.decide(request("hello"))
    assert backend.decide(request("hello")).probabilities == first.probabilities
    assert MockBackend().decide(request("hello")).probabilities == first.probabilities
    assert backend.decide(request("other")).probabilities != first.probabilities
    seeded = create_backend(BackendConfig(provider="mock", seed=1), decision=SPEC)
    assert seeded.decide(request("hello")).probabilities != first.probabilities


def test_mock_hash_is_pinned_across_versions() -> None:
    # Guards reproducibility of stored reports: this value must never change silently.
    result = MockBackend().decide(request("hello"))
    assert result.selected == "c"
    assert result.probabilities == pytest.approx({"a": 0.0530477, "b": 0.3819792, "c": 0.5649730})


def test_mock_rules_are_case_insensitive_first_match() -> None:
    backend = create_backend(
        BackendConfig(
            provider="mock",
            rules=[
                {"contains": "Refund", "probabilities": {"a": 0.8, "b": 0.1, "c": 0.1}},
                {"contains": "refund", "probabilities": {"a": 0.1, "b": 0.8, "c": 0.1}},
            ],
            default={"a": 0.1, "b": 0.1, "c": 0.8},
        ),
        decision=SPEC,
    )
    assert backend.decide(request("please REFUND me")).selected == "a"
    assert backend.decide(request("nothing")).selected == "c"
    json_input = DecisionRequest(case_id="j", decision=SPEC, input={"text": "refund"})
    assert backend.decide(json_input).selected == "a"


def test_mock_rules_are_checked_against_contract_labels() -> None:
    config = BackendConfig(
        provider="mock", rules=[{"contains": "x", "probabilities": {"a": 1.0, "zzz": 0.0}}]
    )
    with pytest.raises(ContractError, match=r"rules\[0\].*unknown labels \['zzz'\]"):
        create_backend(config, decision=SPEC)


def test_backend_settings_errors_point_at_contract_path() -> None:
    with pytest.raises(ContractError, match=r"backends\.alt\.sede: unknown field"):
        create_backend(BackendConfig(provider="mock", sede=1), decision=SPEC, name="alt")


def test_callable_backend_normalizes_like_any_other() -> None:
    backend = CallableBackend(lambda req: {"c": 0.2, "a": 0.5, "b": 0.3}, model="fn")
    result = backend.decide(request("x"))
    assert list(result.probabilities) == ["a", "b", "c"]
    assert (result.selected, result.provider, result.model) == ("a", "python", "fn")

    bad = CallableBackend(lambda req: {"a": 0.9})
    with pytest.raises(InvalidResponse, match="missing labels"):
        bad.decide(request("x"))

    rich = CallableBackend(
        lambda req: Prediction({"a": 0.1, "b": 0.1, "c": 0.8}, model_version="2")
    )
    assert rich.decide(request("x")).model_version == "2"


def test_callable_backend_cannot_come_from_a_contract() -> None:
    with pytest.raises(ContractError, match="cannot be configured from a contract"):
        CallableBackend.from_config(BackendConfig(provider="python"), name="d", decision=SPEC)


def test_unknown_provider_lists_available() -> None:
    with pytest.raises(ContractError, match=r"unknown backend provider 'nope'; available: .*mock"):
        backend_class("nope")


class PluginBackend(DecisionBackend):
    provider = "plugin"

    @classmethod
    def from_config(cls, config: BackendConfig, *, name: str, decision: DecisionSpec) -> Any:
        return cls(name=name, model=config.model)

    def predict(self, request: DecisionRequest) -> Prediction:
        return Prediction({"a": 1.0, "b": 0.0, "c": 0.0})


def _fake_entry_points(monkeypatch: pytest.MonkeyPatch, *points: EntryPoint) -> None:
    def entry_points(group: str, name: str | None = None) -> list[EntryPoint]:
        assert group == "decguard.backends"
        return [p for p in points if name is None or p.name == name]

    monkeypatch.setattr(registry, "entry_points", entry_points)


def test_plugin_backends_load_from_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_entry_points(
        monkeypatch,
        EntryPoint("plugin", f"{__name__}:PluginBackend", "decguard.backends"),
        EntryPoint("mock", f"{__name__}:PluginBackend", "decguard.backends"),
    )
    assert "plugin" in available_providers()
    backend = create_backend(BackendConfig(provider="plugin", model="p"), decision=SPEC)
    assert backend.decide(request("x")).selected == "a"
    # built-ins cannot be shadowed by plugins
    assert backend_class("mock") is MockBackend


def test_plugin_that_is_not_a_backend_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_entry_points(monkeypatch, EntryPoint("bad", "json:dumps", "decguard.backends"))
    with pytest.raises(ContractError, match="is not a DecisionBackend"):
        backend_class("bad")


def test_plugin_import_failure_is_contract_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_entry_points(monkeypatch, EntryPoint("gone", "no_such_module:X", "decguard.backends"))
    with pytest.raises(ContractError, match="cannot load backend provider 'gone'"):
        backend_class("gone")
