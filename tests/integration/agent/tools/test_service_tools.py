"""A declared service's operations are tools of a live turn: a ``read`` call returns the service's
body carrying the stored token, the token is in neither the trace nor the audit, and a service whose
secret is not stored is left out of the turn naming the header. The oracle is a loopback HTTP
server, the real driver and the files docket wrote."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from tests.support.llm import RecordingScriptedBackend as _ScriptedBackend
from tests.support.llm import final as _final
from tests.support.pods import write_meta_overrides as _write_meta
from tests.support.roles import write_role_overlay
from tests.support.trace import audit_entries, trace_events

from docket.agent.ports import ChatResponse, TokenUsage, ToolCall, assistant
from docket.agent.tools import service_tools as _st
from docket.agent.tools.registry import ToolContext, ToolRegistry, dispatch_tool
from docket.governance import audit as _audit
from docket.governance import secrets as _secrets
from docket.hops.application.driver import DocketDriver
from docket.kernel.home import current_home
from docket.kernel.service import ServiceConfig
from docket.teams import fleet as _fleet
from docket.teams import services as _services
from docket.teams.role_composer import registry_for_role

SUBJECT = "docket.hops.application.driver_support"

_TOKEN = "crm-live-0123456789abcdef"


class _Handler(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, Any]]] = []

    def log_message(self, *args: object) -> None:
        pass

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        type(self).seen.append(
            {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "body": raw.decode(),
            }
        )
        body = json.dumps({"id": 7, "name": "Ana", "echo": self.headers.get("Authorization")})
        payload = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = _handle


@pytest.fixture
def server() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    _Handler.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", _Handler.seen
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _config(base: str, secret: str = "crm") -> ServiceConfig:
    return ServiceConfig.model_validate(
        {
            "name": "crm",
            "baseUrl": base,
            "hosts": ["127.0.0.1"],
            "auth": {"header": "Authorization", "value": "Bearer ${secret:" + secret + "}"},
            "operations": [
                {
                    "name": "get_contact",
                    "method": "GET",
                    "path": "/contacts/{id}",
                    "params": [{"name": "id", "in": "path", "type": "integer"}],
                },
                {
                    "name": "create_contact",
                    "method": "POST",
                    "path": "/contacts",
                    "body": {"type": "object", "properties": {"email": {"type": "string"}}},
                },
            ],
        }
    )


def _call(name: str, arguments: str) -> ChatResponse:
    call = ToolCall(id="c-1", name=name, arguments=arguments)
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


@pytest.fixture
def world(tmp_path: Path) -> None:
    _fleet.disable_sandbox_isolation()
    code = tmp_path / "code"
    code.mkdir()
    _write_meta("impl-1", role="implementer", codebase=str(code))
    _secrets.save_secrets({"crm": _TOKEN})


def _turn(backend: _ScriptedBackend) -> None:
    res = DocketDriver(backend_factory=lambda model: backend).run_turn(
        "impl-1", "agent:impl-1:default", "go", 60
    )
    assert res.ok, res.error


def _replies(backend: _ScriptedBackend) -> list[str]:
    return [m.content for call in backend.calls[1:] for m in call if m.role == "tool"]


def _offered(backend: _ScriptedBackend) -> set[str]:
    return {spec.name for spec in backend.tools_seen[0]}


def _trace_text() -> str:
    return "\n".join(
        p.read_text(errors="replace") for p in current_home().traces_dir.rglob("*.jsonl")
    )


class TestAReadOperationRunsInATurn:
    def test_the_body_comes_back_the_request_carried_the_token_and_no_record_holds_it(
        self, world: None, server: tuple[str, list[dict[str, Any]]]
    ) -> None:
        base, seen = server
        _services.add_service(_config(base))
        backend = _ScriptedBackend([_call("svc__crm__get_contact", '{"id": 7}'), _final("done")])

        _turn(backend)

        assert [(s["method"], s["path"], s["authorization"]) for s in seen] == [
            ("GET", "/contacts/7", f"Bearer {_TOKEN}")
        ]
        (reply,) = _replies(backend)
        assert '"name":"Ana"' in reply and _TOKEN not in reply
        results = [e for e in trace_events("impl-1") if e["event_type"] == "tool_result"]
        assert [(e["payload"]["tool"], e["payload"]["ok"]) for e in results] == [
            ("svc__crm__get_contact", True)
        ]
        assert _TOKEN not in _trace_text()
        assert _TOKEN not in str(_audit.read_audit())
        assert _TOKEN not in current_home().services_file.read_text()

    def test_a_role_without_the_name_is_not_offered_a_send_operation(
        self, world: None, server: tuple[str, list[dict[str, Any]]]
    ) -> None:
        _services.add_service(_config(server[0]))
        backend = _ScriptedBackend([_final("done")])

        _turn(backend)

        assert "svc__crm__get_contact" in _offered(backend)
        assert "svc__crm__create_contact" not in _offered(backend)

    def test_a_role_reaches_the_send_operation_only_by_naming_it(
        self, world: None, server: tuple[str, list[dict[str, Any]]]
    ) -> None:
        registry = ToolRegistry()
        _st.load_service_tools(registry, services=[_st.ResolvedService(_config(server[0]))])
        write_role_overlay("acme", "plain", [], extra="tools: [svc__crm__get_contact]\n")
        write_role_overlay("acme", "actor", [], extra="tools: [svc__crm]\n")

        plain = registry_for_role(registry, "plain", project="acme")
        actor = registry_for_role(registry, "actor", project="acme")

        assert plain.names() == ["svc__crm__get_contact"]
        assert actor.names() == ["svc__crm__create_contact", "svc__crm__get_contact"]


class TestAnUnknownSecretLeavesTheServiceOut:
    def test_the_service_is_not_offered_and_the_audit_names_the_header_not_a_value(
        self, world: None, server: tuple[str, list[dict[str, Any]]]
    ) -> None:
        _services.add_service(_config(server[0], secret="missing"))
        backend = _ScriptedBackend([_final("done")])

        _turn(backend)

        assert not [n for n in _offered(backend) if n.startswith("svc__")]
        (entry,) = audit_entries("service_client.unavailable")
        assert "crm" in entry["detail"] and "Authorization" in entry["detail"]
        assert "missing" in entry["detail"] and _TOKEN not in entry["detail"]


class TestASendCallIsAuditedWithMethodAndHost:
    def test_a_refused_send_names_the_method_and_host_and_nothing_of_the_call(
        self, world: None, server: tuple[str, list[dict[str, Any]]]
    ) -> None:
        base, seen = server
        registry = ToolRegistry()
        _st.load_service_tools(
            registry,
            services=[
                _st.ResolvedService(
                    _config(base), headers={"Authorization": f"Bearer {_TOKEN}"}, secrets=(_TOKEN,)
                )
            ],
        )
        ctx = ToolContext(
            agent_id="impl-1", role="implementer", project="acme", approval_mode="refuse"
        )

        result = dispatch_tool(
            ToolCall(
                id="c-2",
                name="svc__crm__create_contact",
                arguments='{"body": {"email": "a@b.test"}}',
            ),
            ctx,
            registry,
        )

        assert result.denied and seen == []
        (row,) = audit_entries("tool.send")
        assert "decision=deny" in row["detail"]
        assert "method=POST host='127.0.0.1'" in row["detail"]
        assert _TOKEN not in row["detail"]
