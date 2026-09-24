"""A real local HTTP decision server (stdlib only) speaking decguard.http/0.1.

It answers with a MockBackend, so the same dataset can run in-process (mock) and over the
network (http) and the results must normalize identically.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from decguard.backends import MockBackend, MockSettings
from decguard.decisions import DecisionRequest, DecisionSpec, DecisionType


class DecisionServer(ThreadingHTTPServer):
    daemon_threads = True
    mock: MockBackend
    requests_seen: list[dict[str, Any]]
    fail_with: int | None = None

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host!s}:{port}"


class Handler(BaseHTTPRequestHandler):
    server: DecisionServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self._send(200 if self.path == "/health" else 404, {"status": "ok"})

    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests_seen.append(payload)
        if self.server.fail_with is not None:
            self._send(self.server.fail_with, {"error": "boom"})
            return
        spec = DecisionSpec(
            name=payload["decision"]["name"],
            type=DecisionType(payload["decision"]["type"]),
            labels=tuple(payload["decision"]["labels"]),
        )
        request = DecisionRequest(case_id=payload["case_id"], decision=spec, input=payload["input"])
        prediction = self.server.mock.predict(request)
        self._send(
            200,
            {
                "probabilities": dict(prediction.probabilities),
                "model": payload["model"],
                "model_version": prediction.model_version,
            },
        )


def start_server(mock: MockBackend) -> DecisionServer:
    server = DecisionServer(("127.0.0.1", 0), Handler)
    server.mock = mock
    server.requests_seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def decision_server() -> Iterator[DecisionServer]:
    server = start_server(MockBackend(MockSettings(model_version="1")))
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


REAL_BACKEND_MARKERS = ("real_kev", "real_jev")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Real-backend tests run only when selected with ``-m``; then nothing skips them."""
    selected = config.getoption("markexpr") or ""
    for item in items:
        for marker in REAL_BACKEND_MARKERS:
            if item.get_closest_marker(marker) is not None and marker not in selected:
                item.add_marker(pytest.mark.skip(reason=f"real backend: select with -m {marker}"))
