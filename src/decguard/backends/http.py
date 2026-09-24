"""Generic HTTP backend for decision endpoints (System One APIs: see ``systemone.py``).

Protocol ``decguard.http/0.1`` (see docs/backends.md)::

    POST <url>
    {"protocol": "decguard.http/0.1", "case_id": "...", "model": "..." | null,
     "decision": {"name": "...", "type": "choice", "labels": ["...", ...]},
     "input": "..." | {...}}

    200 OK
    {"probabilities": {"<label>": <float>, ...},
     "model": "..."?, "model_version": "..."?, "metadata": {...}?}

Credentials come only from environment variables and never appear in reports, errors
or metadata.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, ClassVar, Self

import httpx
from pydantic import Field, field_validator, model_validator

from decguard import __version__
from decguard._validation import StrictModel
from decguard.backends.base import BackendMetadata, DecisionBackend, HealthStatus, validate_settings
from decguard.contracts.models import BackendConfig
from decguard.decisions import DecisionRequest, DecisionSpec, Prediction
from decguard.errors import (
    BackendError,
    BackendTimeout,
    BackendUnavailable,
    ContractError,
    InvalidResponse,
)

PROTOCOL = "decguard.http/0.1"
_RETRYABLE_STATUS = frozenset({502, 503, 504})
_SECRET_HEADERS = frozenset({"authorization", "proxy-authorization", "x-api-key", "api-key"})
_SECRET_QUERY_KEYS = frozenset(
    {"api_key", "apikey", "access_token", "token", "key", "signature", "auth", "password"}
)


def _check_url(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL as exc:
        raise ValueError("invalid URL") from exc
    if url.scheme not in {"http", "https"} or not url.host:
        raise ValueError("must be an absolute http:// or https:// URL")
    if url.userinfo:
        raise ValueError("must not embed credentials; use bearer_token_env or headers_from_env")
    secret_query = next(
        (key for key, _ in url.params.multi_items() if key.lower() in _SECRET_QUERY_KEYS), None
    )
    if secret_query is not None:
        raise ValueError(
            f"query parameter {secret_query!r} looks like a credential; use an environment "
            "variable and a request header"
        )
    return value


class HttpSettings(StrictModel):
    url: str
    health_url: str | None = None
    """Optional GET endpoint; any 2xx answer means healthy."""
    timeout_s: float = Field(default=30.0, gt=0.0, le=600.0)
    max_retries: int = Field(default=0, ge=0, le=5)
    """Retries for connection failures and HTTP 502/503/504 only."""
    retry_backoff_s: float = Field(default=0.5, ge=0.0, le=60.0)
    headers: dict[str, str] = {}
    """Static, non-secret headers."""
    headers_from_env: dict[str, str] = {}
    """Header name -> environment variable holding its value."""
    bearer_token_env: str | None = None
    """Environment variable holding a token sent as ``Authorization: Bearer <token>``."""
    label_map: dict[str, str] = {}
    """Backend label -> contract label, for endpoints that name labels differently."""

    _check_urls = field_validator("url", "health_url")(_check_url)

    @field_validator("headers")
    @classmethod
    def _no_literal_secrets(cls, value: dict[str, str]) -> dict[str, str]:
        for header in value:
            if header.lower() in _SECRET_HEADERS:
                raise ValueError(
                    f"{header!r} looks like a credential; put it in an environment variable "
                    "and use headers_from_env or bearer_token_env"
                )
        return value

    @model_validator(mode="after")
    def _one_authorization_source(self) -> HttpSettings:
        from_env = {header.lower() for header in self.headers_from_env}
        if self.bearer_token_env and "authorization" in from_env:
            raise ValueError("set either bearer_token_env or an Authorization header, not both")
        if self.health_url is not None and (self.bearer_token_env or self.headers_from_env):
            target = httpx.URL(self.url)
            health = httpx.URL(self.health_url)
            if (target.scheme, target.host, target.port) != (
                health.scheme,
                health.host,
                health.port,
            ):
                raise ValueError(
                    "health_url must use the backend URL's origin when environment headers "
                    "are configured"
                )
        return self


class HttpBackend(DecisionBackend):
    provider = "http"
    protocol: ClassVar[str] = PROTOCOL
    retryable_status: ClassVar[frozenset[int]] = _RETRYABLE_STATUS
    """Statuses retried (up to ``max_retries``) and reported as ``unavailable``."""

    def __init__(
        self,
        settings: HttpSettings,
        *,
        name: str = "default",
        model: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(name=name, model=model)
        self.settings = settings
        self._reverse_labels = {v: k for k, v in settings.label_map.items()}
        self._transport = transport
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config: BackendConfig, *, name: str, decision: DecisionSpec) -> Self:
        settings = validate_settings(HttpSettings, config, name=name)
        targets = list(settings.label_map.values())
        unknown = sorted(set(targets) - set(decision.labels))
        if unknown:
            raise ContractError(
                f"http backend {name!r}: label_map targets {unknown} are not contract labels"
            )
        if len(set(targets)) != len(targets):
            raise ContractError(f"http backend {name!r}: label_map maps two labels to one")
        return cls(settings, name=name, model=config.model)

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": f"decguard/{__version__}", **self.settings.headers}
        wanted = dict(self.settings.headers_from_env)
        if self.settings.bearer_token_env:
            wanted["Authorization"] = self.settings.bearer_token_env
        for header, variable in wanted.items():
            value = os.environ.get(variable)
            if not value:
                raise ContractError(
                    f"http backend {self.name!r}: environment variable {variable} is not set"
                )
            if header == "Authorization" and variable == self.settings.bearer_token_env:
                value = f"Bearer {value}"
            headers[header] = value
        return headers

    def _get_client(self) -> httpx.Client:
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(
                    headers=self._headers(),
                    timeout=self.settings.timeout_s,
                    follow_redirects=False,
                    transport=self._transport,
                )
            return self._client

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = self._get_client()
        attempts = self.settings.max_retries + 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = client.request(method, url, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # Nothing reached the server, so retrying is always safe.
                if last:
                    timed_out = isinstance(exc, httpx.ConnectTimeout)
                    raise (BackendTimeout if timed_out else BackendUnavailable)(
                        f"cannot connect to backend {self.name!r}: {type(exc).__name__}"
                    ) from exc
            except httpx.TimeoutException as exc:
                raise BackendTimeout(
                    f"backend {self.name!r} timed out after {self.settings.timeout_s:g}s"
                ) from exc
            except httpx.TransportError as exc:
                raise BackendUnavailable(
                    f"transport error from backend {self.name!r}: {type(exc).__name__}"
                ) from exc
            else:
                if response.status_code not in self.retryable_status or last:
                    return response
            time.sleep(self.settings.retry_backoff_s * (2**attempt))
        raise AssertionError("unreachable")  # pragma: no cover

    def predict(self, request: DecisionRequest) -> Prediction:
        labels = [self._reverse_labels.get(label, label) for label in request.decision.labels]
        payload = {
            "protocol": PROTOCOL,
            "case_id": request.case_id,
            "model": self.model,
            "decision": {
                "name": request.decision.name,
                "type": request.decision.type.value,
                "labels": labels,
            },
            "input": request.input,
        }
        return self._parse(self._post(payload))

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        """POST ``payload`` to the decision URL; any non-2xx answer becomes a case error."""
        response = self._send("POST", self.settings.url, json=payload)
        if response.status_code in self.retryable_status:
            raise BackendUnavailable(f"backend {self.name!r} returned HTTP {response.status_code}")
        if not response.is_success:
            # Response bodies are untrusted and can echo credentials or private input.
            # Keep case errors useful without persisting arbitrary server text in reports.
            raise BackendError(f"backend {self.name!r} returned HTTP {response.status_code}")
        return response

    def _json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise InvalidResponse(f"backend {self.name!r} returned invalid JSON") from exc

    def _parse(self, response: httpx.Response) -> Prediction:
        body = self._json(response)
        if not isinstance(body, dict) or not isinstance(body.get("probabilities"), dict):
            raise InvalidResponse(f"backend {self.name!r} response has no 'probabilities' object")
        probabilities: dict[str, Any] = {}
        for label, value in body["probabilities"].items():
            mapped = self.settings.label_map.get(label, label)
            if mapped in probabilities:
                raise InvalidResponse(f"backend {self.name!r} returned label {mapped!r} twice")
            probabilities[mapped] = value
        model, version, metadata = (
            body.get("model"),
            body.get("model_version"),
            body.get("metadata"),
        )
        if model is not None and not isinstance(model, str):
            raise InvalidResponse("'model' must be a string")
        if version is not None and not isinstance(version, str):
            raise InvalidResponse("'model_version' must be a string")
        if metadata is not None and not isinstance(metadata, dict):
            raise InvalidResponse("'metadata' must be an object")
        return Prediction(
            probabilities=probabilities,
            model=model,
            model_version=version,
            metadata=metadata or {},
        )

    def healthcheck(self) -> HealthStatus:
        if self.settings.health_url is None:
            return HealthStatus(status="unknown", detail="no health_url configured")
        try:
            response = self._send("GET", self.settings.health_url)
        except BackendError as exc:
            return HealthStatus(status="unhealthy", detail=str(exc))
        if response.is_success:
            return HealthStatus(status="ok", detail=f"HTTP {response.status_code}")
        return HealthStatus(status="unhealthy", detail=f"HTTP {response.status_code}")

    def metadata(self) -> BackendMetadata:
        return BackendMetadata(
            name=self.name,
            provider=self.provider,
            model=self.model,
            details={"url": _redact(self.settings.url), "protocol": self.protocol},
        )

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None


def _redact(url: str) -> str:
    """Drop the query string, which may carry tokens."""
    return str(httpx.URL(url).copy_with(query=None, fragment=None))
