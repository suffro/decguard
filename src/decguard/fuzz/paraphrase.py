"""Paraphrase providers for the ``paraphrase`` property.

Built-in providers:

- ``identity``: returns the text unchanged. Needs nothing and checks that a backend gives
  the same answer to the same input twice.
- ``file``: curated paraphrases from a JSONL file (deterministic, reviewable).
- ``openai``: an OpenAI-compatible chat-completions endpoint (optional; the API key comes
  from an environment variable).

Third-party providers are ``Paraphraser`` subclasses exposed under the
``decguard.paraphrasers`` entry-point group.
"""

from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, ClassVar, Self

import httpx
from pydantic import Field, ValidationError, field_validator

from decguard import __version__
from decguard._validation import StrictModel, format_validation_error, reject_duplicate_json_keys
from decguard.backends.http import _check_url, _redact
from decguard.contracts.properties import ParaphraseSource
from decguard.errors import BackendTimeout, BackendUnavailable, ContractError, ParaphraseError

ENTRY_POINT_GROUP = "decguard.paraphrasers"


class Paraphraser(ABC):
    provider: ClassVar[str]

    @classmethod
    def from_config(cls, source: ParaphraseSource, *, base_dir: Path) -> Self:
        """Build from ``properties.paraphrase.source``; paths are relative to ``base_dir``
        (the contract's directory). Must not call remote services."""
        raise ContractError(f"paraphraser {cls.provider!r} cannot be configured from a contract")

    @abstractmethod
    def paraphrase(self, text: str, *, case_id: str, n: int, seed: int) -> list[str]:
        """Up to ``n`` paraphrases of ``text``. Raise :class:`ParaphraseError` on failure."""

    def provenance(self) -> dict[str, Any]:
        """Recorded with every generated transformation. Must never contain secrets."""
        return {"provider": self.provider}

    def close(self) -> None:  # noqa: B027 - optional hook
        pass


def _settings(model: type[StrictModel], source: ParaphraseSource) -> Any:
    try:
        return model.model_validate(source.settings)
    except ValidationError as exc:
        raise ContractError(
            f"invalid settings for paraphraser {source.provider!r}:\n"
            + format_validation_error(exc, prefix="properties.paraphrase.source")
        ) from exc


class _NoSettings(StrictModel):
    pass


class IdentityParaphraser(Paraphraser):
    provider = "identity"

    @classmethod
    def from_config(cls, source: ParaphraseSource, *, base_dir: Path) -> Self:
        _settings(_NoSettings, source)
        return cls()

    def paraphrase(self, text: str, *, case_id: str, n: int, seed: int) -> list[str]:
        return [text]


class FileSettings(StrictModel):
    path: str = Field(min_length=1)


class FileParaphraser(Paraphraser):
    """JSONL rows ``{"id": <case id>, "paraphrases": [...]}`` or
    ``{"input": <text>, "paraphrases": [...]}``; ids take precedence."""

    provider = "file"

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ContractError(f"{path}: cannot read paraphrases: {exc.strerror or exc}") from exc
        self.hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        self.by_id: dict[str, list[str]] = {}
        self.by_text: dict[str, list[str]] = {}
        for lineno, line in enumerate(raw.decode("utf-8", errors="strict").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line, object_pairs_hook=reject_duplicate_json_keys)
            except ValueError as exc:
                raise ContractError(f"{path}: line {lineno}: invalid JSON: {exc}") from exc
            paraphrases = row.get("paraphrases") if isinstance(row, dict) else None
            if not isinstance(paraphrases, list) or not all(
                isinstance(p, str) and p for p in paraphrases
            ):
                raise ContractError(
                    f"{path}: line {lineno}: 'paraphrases' must be a list of non-empty strings"
                )
            if isinstance(row.get("id"), str):
                self.by_id[row["id"]] = paraphrases
            elif isinstance(row.get("input"), str):
                self.by_text[row["input"]] = paraphrases
            else:
                raise ContractError(f"{path}: line {lineno}: needs a string 'id' or 'input'")

    @classmethod
    def from_config(cls, source: ParaphraseSource, *, base_dir: Path) -> Self:
        settings: FileSettings = _settings(FileSettings, source)
        return cls(base_dir / settings.path)

    def paraphrase(self, text: str, *, case_id: str, n: int, seed: int) -> list[str]:
        found = self.by_id.get(case_id, self.by_text.get(text, []))
        return found[:n]

    def provenance(self) -> dict[str, Any]:
        return {"provider": self.provider, "path": str(self.path), "hash": self.hash}


DEFAULT_INSTRUCTIONS = (
    "Paraphrase the user's text {n} times. Keep every fact, name, number, negation and the "
    "meaning exactly the same; change only the wording. Answer with a JSON array of {n} "
    "strings and nothing else."
)


class OpenAISettings(StrictModel):
    model: str = Field(min_length=1)
    url: str = "https://api.openai.com/v1"
    """Base URL of an OpenAI-compatible API; ``/chat/completions`` is appended."""
    api_key_env: str | None = "OPENAI_API_KEY"
    """Environment variable holding the API key; ``null`` for local servers without auth."""
    timeout_s: float = Field(default=60.0, gt=0.0, le=600.0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    instructions: str = DEFAULT_INSTRUCTIONS

    _check = field_validator("url")(_check_url)


class OpenAIParaphraser(Paraphraser):
    provider = "openai"

    def __init__(
        self, settings: OpenAISettings, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._client: httpx.Client | None = None
        self._seen: dict[str, Any] = {}

    @classmethod
    def from_config(cls, source: ParaphraseSource, *, base_dir: Path) -> Self:
        return cls(_settings(OpenAISettings, source))

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            headers = {"User-Agent": f"decguard/{__version__}"}
            variable = self.settings.api_key_env
            if variable is not None:
                key = os.environ.get(variable)
                if not key:
                    raise ContractError(
                        f"paraphraser 'openai': environment variable {variable} is not set"
                    )
                headers["Authorization"] = f"Bearer {key}"
            self._client = httpx.Client(
                headers=headers, timeout=self.settings.timeout_s, transport=self._transport
            )
        return self._client

    def paraphrase(self, text: str, *, case_id: str, n: int, seed: int) -> list[str]:
        payload = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "seed": seed,
            "messages": [
                {"role": "system", "content": self.settings.instructions.format(n=n)},
                {"role": "user", "content": text},
            ],
        }
        url = self.settings.url.rstrip("/") + "/chat/completions"
        try:
            response = self._get_client().post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise BackendTimeout(
                f"paraphraser timed out after {self.settings.timeout_s:g}s"
            ) from exc
        except httpx.TransportError as exc:
            raise BackendUnavailable(f"paraphraser unreachable: {type(exc).__name__}") from exc
        if not response.is_success:
            raise ParaphraseError(f"paraphraser returned HTTP {response.status_code}")
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ParaphraseError("paraphraser response has no message content") from exc
        self._seen = {
            key: body[key]
            for key in ("model", "system_fingerprint")
            if isinstance(body.get(key), str)
        }
        return _parse_list(content)[:n]

    def provenance(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.settings.model,
            "url": _redact(self.settings.url),
            "temperature": self.settings.temperature,
            **{f"response_{key}": value for key, value in self._seen.items()},
        }

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def _parse_list(content: Any) -> list[str]:
    if not isinstance(content, str):
        raise ParaphraseError("paraphraser message content is not text")
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        items = json.loads(text)
    except ValueError as exc:
        raise ParaphraseError("paraphraser did not answer with a JSON array") from exc
    if not isinstance(items, list) or not all(isinstance(i, str) and i.strip() for i in items):
        raise ParaphraseError("paraphraser did not answer with a JSON array of strings")
    return [item.strip() for item in items]


BUILTIN_PARAPHRASERS: dict[str, type[Paraphraser]] = {
    IdentityParaphraser.provider: IdentityParaphraser,
    FileParaphraser.provider: FileParaphraser,
    OpenAIParaphraser.provider: OpenAIParaphraser,
}


def create_paraphraser(source: ParaphraseSource, *, base_dir: Path) -> Paraphraser:
    provider = source.provider
    cls = BUILTIN_PARAPHRASERS.get(provider)
    if cls is None:
        matches = entry_points(group=ENTRY_POINT_GROUP, name=provider)
        if not matches:
            available = sorted(
                set(BUILTIN_PARAPHRASERS)
                | {ep.name for ep in entry_points(group=ENTRY_POINT_GROUP)}
            )
            raise ContractError(
                f"unknown paraphrase provider {provider!r}; available: {', '.join(available)}"
            )
        (entry_point, *_) = tuple(matches)
        try:
            loaded = entry_point.load()
        except Exception as exc:
            raise ContractError(f"cannot load paraphraser {provider!r}: {exc}") from exc
        if not (isinstance(loaded, type) and issubclass(loaded, Paraphraser)):
            raise ContractError(
                f"paraphraser {provider!r} ({entry_point.value}) is not a Paraphraser"
            )
        cls = loaded
    return cls.from_config(source, base_dir=base_dir)
