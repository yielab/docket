"""The observability export pipeline wired into a live turn.

Covers `edges/adapters/docket_runtime.py::DocketDriver.run_turn`'s lazy, idempotent start of
`core.telemetry`'s bounded pipeline, its flush on every return path (bounded even when the
destination hangs), and the `config.EXPORTERS_HEALTH_FILE` write -- see
observability-export.spec.md's "Pipeline" and "The module-level registry and wiring" sections,
and agent-loop.spec.md requirements 72-74. Every HTTP target here is a local server this file
starts and stops; nothing reaches a real vendor host.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time as _time
from collections.abc import Callable, Iterator, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import exporter as _exporter
from docket.core import telemetry as _telemetry
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.edges import store as _store
from docket.edges.adapters.docket_runtime import DocketDriver

SUBJECT = "docket.edges.adapters.docket_runtime"


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repoint_docket_home(monkeypatch, tmp_path / "docket")
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)


@pytest.fixture(autouse=True)
def _reset_telemetry_registry() -> Iterator[None]:
    """`core.telemetry`'s registry is module-global (`_REGISTRY`/`_UNSUBSCRIBE`); reset it
    around every test in this file so one test's enabled exporter never leaks a background
    thread or a live trace subscriber into the next."""
    _telemetry.close()
    yield
    _telemetry.close()


def _write_meta(agent_id: str) -> Path:
    ws = _cfg.workspace_dir(agent_id)
    ws.mkdir(parents=True, exist_ok=True)
    _store.write_json(
        _cfg.meta_path(agent_id), {"kind": "project", "role": "implementer", "model": "test/model"}
    )
    return ws


class _ScriptedBackend:
    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        return self._responses.pop(0)


def _final_response(text: str = "hello") -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(12, 4)
    )


def _read_call_response(path: str) -> ChatResponse:
    call = ToolCall(id="c1", name="read", arguments=json.dumps({"path": path}))
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(10, 5),
    )


def _enable_local_exporter(endpoint: str, privacy: str = "full", **extra: Any) -> None:
    """Write a global `kind: exporter` document named "local" -- not a built-in name, so no
    inheritance kicks in -- straight through `edges/store.py`, the same file `core.exporter`
    reads back."""
    _store.write_json(
        _cfg.EXPORTERS_FILE,
        {
            "exporters": {
                "local": {
                    "kind": "exporter",
                    "name": "local",
                    "dialect": "otlp-http",
                    "endpoint": endpoint,
                    "auth": {"type": "none"},
                    "enabled": True,
                    "privacy": privacy,
                    **extra,
                }
            }
        },
    )


# ── a real, answering local server ──────────────────────────────────────────


class _RecordingHandler(BaseHTTPRequestHandler):
    bodies: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).bodies.append(json.loads(body.decode()))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args: object) -> None:  # keep test output quiet
        return


def _recording_server() -> tuple[ThreadingHTTPServer, str, type[_RecordingHandler]]:
    class _Handler(_RecordingHandler):
        pass

    _Handler.bodies = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{port}/v1/traces", _Handler


# ── a server that accepts the connection and never answers ─────────────────


def _hang_server() -> tuple[str, Callable[[], None]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    sock.settimeout(0.2)
    port = sock.getsockname()[1]
    stop = threading.Event()
    held: list[socket.socket] = []

    def _accept_loop() -> None:
        while not stop.is_set():
            try:
                conn, _addr = sock.accept()
            except OSError:
                continue
            held.append(conn)

    thread = threading.Thread(target=_accept_loop, daemon=True)
    thread.start()

    def _shutdown() -> None:
        stop.set()
        thread.join(timeout=1.0)
        for conn in held:
            with contextlib.suppress(OSError):
                conn.close()
        with contextlib.suppress(OSError):
            sock.close()

    return f"http://127.0.0.1:{port}/v1/traces", _shutdown


class TestRealPost:
    def test_run_turn_exports_a_real_batch_and_records_health(self) -> None:
        _write_meta("solo-agent")
        srv, url, handler_cls = _recording_server()
        try:
            _enable_local_exporter(url)
            backend = _ScriptedBackend([_final_response("hello there")])
            driver = DocketDriver(backend_factory=lambda model: backend)

            result = driver.run_turn("solo-agent", "agent:solo-agent:default", "hi", 60)

            assert result.ok is True
            deadline = _time.monotonic() + 2.0
            while not handler_cls.bodies and _time.monotonic() < deadline:
                _time.sleep(0.02)
        finally:
            srv.shutdown()

        assert handler_cls.bodies, "the server never received a POST"
        spans = [
            span
            for body in handler_cls.bodies
            for span in body["resourceSpans"][0]["scopeSpans"][0]["spans"]
        ]
        chat = next(s for s in spans if s["name"] == "gen_ai.chat")
        attrs = {a["key"]: a["value"] for a in chat["attributes"]}
        assert int(attrs["gen_ai.usage.input_tokens"]["intValue"]) > 0
        assert any(s["name"] == "docket.session" for s in spans)

        health = _exporter.read_health().get("local")
        assert health is not None
        assert health["exported"] >= 2
        assert health["failed"] == 0

    def test_a_second_run_turn_does_not_restart_the_pipeline(self) -> None:
        """`start` is idempotent: a second call never builds a second `Pipeline` or subscribes a
        second fan-out sink for the same still-enabled exporter (checked by registry identity,
        not `threading.active_count()`, which a real server's per-request threads make flaky)."""
        _write_meta("solo-agent")
        srv, url, _handler_cls = _recording_server()
        try:
            _enable_local_exporter(url)
            backend = _ScriptedBackend([_final_response("one"), _final_response("two")])
            driver = DocketDriver(backend_factory=lambda model: backend)

            driver.run_turn("solo-agent", "agent:solo-agent:default", "hi", 60)
            pipeline_after_first = _telemetry._REGISTRY.get("local")
            unsubscribe_after_first = _telemetry._UNSUBSCRIBE
            assert pipeline_after_first is not None

            driver.run_turn("solo-agent", "agent:solo-agent:default", "hi again", 60)
            assert _telemetry._REGISTRY.get("local") is pipeline_after_first
            assert _telemetry._UNSUBSCRIBE is unsubscribe_after_first
        finally:
            srv.shutdown()


class TestExporterPrivacyGatesToolArguments:
    """`ExporterSpec.privacy` wired through `core.telemetry.start` into the started
    `Pipeline`'s policy (observability-export.spec.md requirement 86): `actions` grants
    `toolArguments`; the default `minimal` grants nothing."""

    def _run_a_read_call(self, agent_id: str, privacy: str) -> list[dict[str, Any]]:
        ws = _write_meta(agent_id)
        (ws / "notes.txt").write_text("top secret\n")
        srv, url, handler_cls = _recording_server()
        try:
            _enable_local_exporter(url, privacy=privacy)
            backend = _ScriptedBackend(
                [_read_call_response("notes.txt"), _final_response("here it is")]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)

            result = driver.run_turn(agent_id, f"agent:{agent_id}:default", "read notes.txt", 60)

            assert result.ok is True
            deadline = _time.monotonic() + 2.0
            while not handler_cls.bodies and _time.monotonic() < deadline:
                _time.sleep(0.02)
        finally:
            srv.shutdown()

        assert handler_cls.bodies, "the server never received a POST"
        return [
            span
            for body in handler_cls.bodies
            for span in body["resourceSpans"][0]["scopeSpans"][0]["spans"]
        ]

    def test_privacy_actions_exports_tool_arguments(self) -> None:
        spans = self._run_a_read_call("actions-agent", "actions")
        tool_span = next(s for s in spans if s["name"] == "execute_tool read")
        assert "gen_ai.tool.call.arguments" in {a["key"] for a in tool_span["attributes"]}

    def test_privacy_minimal_omits_tool_arguments(self) -> None:
        """The kept negative twin: the default `minimal` level shares nothing beyond
        structure, so the same tool call's arguments never leave this host."""
        spans = self._run_a_read_call("minimal-agent", "minimal")
        tool_span = next(s for s in spans if s["name"] == "execute_tool read")
        assert "gen_ai.tool.call.arguments" not in {a["key"] for a in tool_span["attributes"]}


class TestCapturedContentReachesTheWire:
    """The seam between the model call's capture and the projection: a real turn's
    `llm_call` records, captured on demand, cross the real projection onto the real wire
    exactly as far as the exporter's own level and `contentMaxChars` allow."""

    def _run(self, agent_id: str, privacy: str) -> tuple[list[dict[str, Any]], str]:
        ws = _write_meta(agent_id)
        (ws / "notes.txt").write_text("CANARY-FILE-" + "x" * 300 + "\n")
        srv, url, handler_cls = _recording_server()
        try:
            _enable_local_exporter(url, privacy=privacy, contentMaxChars=100)
            backend = _ScriptedBackend(
                [_read_call_response("notes.txt"), _final_response("CANARY-REPLY")]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            task = "CANARY-TASK read notes.txt"
            result = driver.run_turn(agent_id, f"agent:{agent_id}:default", task, 60)
            assert result.ok is True
            deadline = _time.monotonic() + 2.0
            while len(handler_cls.bodies) < 1 and _time.monotonic() < deadline:
                _time.sleep(0.02)
        finally:
            srv.shutdown()
        spans = [
            span
            for body in handler_cls.bodies
            for span in body["resourceSpans"][0]["scopeSpans"][0]["spans"]
        ]
        return spans, json.dumps(handler_cls.bodies)

    @staticmethod
    def _attr(span: dict[str, Any], key: str) -> str | None:
        for attribute in span["attributes"]:
            if attribute["key"] == key:
                return str(attribute["value"]["stringValue"])
        return None

    def test_conversation_exports_the_generation_bounded_per_exporter(self) -> None:
        spans, _ = self._run("conversation-agent", "conversation")
        chats = [s for s in spans if s["name"].startswith("gen_ai.chat")]
        second = json.loads(self._attr(chats[-1], "gen_ai.input.messages") or "[]")
        user = next(m for m in second if m["role"] == "user")
        assert "CANARY-TASK" in json.dumps(user)
        tool_part = next(m for m in second if m["role"] == "tool")["parts"][0]
        assert tool_part["response"].startswith("CANARY-FILE-")
        assert len(tool_part["response"].split("…[truncated")[0]) == 100
        output = self._attr(chats[-1], "gen_ai.output.messages") or ""
        assert "CANARY-REPLY" in output
        assert self._attr(chats[-1], "gen_ai.system_instructions") is None

    def test_minimal_sends_no_captured_content(self) -> None:
        _, wire = self._run("minimal-seam-agent", "minimal")
        assert "CANARY-" not in wire


class TestZeroExportersAndNoExport:
    def test_zero_enabled_exporters_starts_no_thread_and_no_subscriber(self) -> None:
        _write_meta("solo-agent")
        backend = _ScriptedBackend([_final_response("hello")])
        driver = DocketDriver(backend_factory=lambda model: backend)
        from docket.core import trace as _trace

        before = threading.active_count()
        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "hi", 60)
        assert result.ok is True
        assert threading.active_count() == before
        assert _trace._SUBSCRIBERS == []
        assert _telemetry.health() == {}

    def test_docket_no_export_suppresses_a_configured_exporter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_meta("solo-agent")
        srv, url, handler_cls = _recording_server()
        try:
            _enable_local_exporter(url)
            monkeypatch.setenv("DOCKET_NO_EXPORT", "1")
            backend = _ScriptedBackend([_final_response("hello")])
            driver = DocketDriver(backend_factory=lambda model: backend)

            result = driver.run_turn("solo-agent", "agent:solo-agent:default", "hi", 60)

            assert result.ok is True
            _time.sleep(0.2)
        finally:
            srv.shutdown()
        assert handler_cls.bodies == []
        assert _telemetry.health() == {}


class TestHungDestination:
    def test_a_hanging_destination_does_not_lengthen_the_turn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The server accepts the connection and never answers; `run_turn` must still return
        promptly (bounded by `config.EXPORT_FLUSH_TIMEOUT_S`) and report the same result as a
        run with no exporter configured at all."""
        monkeypatch.setattr(_cfg, "EXPORT_FLUSH_TIMEOUT_S", 0.2, raising=True)

        _write_meta("baseline-agent")
        backend = _ScriptedBackend([_final_response("hello")])
        driver = DocketDriver(backend_factory=lambda model: backend)
        start = _time.perf_counter()
        baseline = driver.run_turn("baseline-agent", "agent:baseline-agent:default", "hi", 60)
        no_exporter_duration = _time.perf_counter() - start

        _write_meta("hung-agent")
        url, shutdown = _hang_server()
        try:
            _enable_local_exporter(url)
            backend2 = _ScriptedBackend([_final_response("hello")])
            driver2 = DocketDriver(backend_factory=lambda model: backend2)

            start = _time.perf_counter()
            result = driver2.run_turn("hung-agent", "agent:hung-agent:default", "hi", 60)
            with_exporter_duration = _time.perf_counter() - start
        finally:
            shutdown()

        assert result.ok == baseline.ok
        assert result.output == baseline.output
        assert result.failure_kind == baseline.failure_kind
        # The real bound: a hung destination costs at most one bounded flush wait on top of the
        # turn's own (near-zero, fake-backend) time -- never the multi-second span a real socket
        # timeout would otherwise impose. `no_exporter_duration` is dominated by filesystem I/O
        # (session/meta/trace writes) common to both runs, not by anything export-related.
        assert (
            with_exporter_duration
            < _cfg.EXPORT_FLUSH_TIMEOUT_S + max(no_exporter_duration, 0.05) * 2
        )

        # The bounded flush above gave up long before the background sender's own transport
        # timeout could fire, so the eventual failure lands in `core.telemetry.health()` (the
        # live, in-process registry) some time after `run_turn` already returned -- read that
        # directly rather than `config.EXPORTERS_HEALTH_FILE`, which `run_turn` only snapshots
        # once, at the moment `flush` gave up (before the send had failed).
        deadline = _time.monotonic() + 6.0
        health = _telemetry.health().get("local") or {}
        while (
            health.get("failed", 0) + health.get("dropped", 0)
        ) == 0 and _time.monotonic() < deadline:
            _time.sleep(0.02)
            health = _telemetry.health().get("local") or {}
        assert health.get("failed", 0) >= 1 or health.get("dropped", 0) >= 1
