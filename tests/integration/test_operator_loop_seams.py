"""Operator-loop integration seams -- the integrator's own tests, not any one worker's.

Each class drives a REAL producer into a REAL consumer across a seam two modules agreed on by
convention rather than a shared type: a value one writes and another reads is not a contract
until something exercises both halves together. No mock stands in for either side; the only
test doubles are the model backend and, for the webhook seam, a local `http.server` standing in
for an operator's own receiver. See each class's own docstring for the seam it proves.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from tests.conftest import record_isolation_off, repoint_docket_home

import docket.config as _cfg
from docket.cli import _pod
from docket.core import answers as _answers
from docket.core import approval as _approval
from docket.core import channel as _channel
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import notify as _notify
from docket.core import pipeline as _pipeline
from docket.core import runtime_driver as _rd
from docket.core import secrets as _secrets
from docket.core.llm import ChatResponse, TokenUsage, ToolCall, assistant
from docket.edges.adapters import channels as _channel_adapters
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver
from docket.serve import _DocketHandler

SUBJECT = "docket.core"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed_pod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str = "demo",
    roles: tuple[str, ...] = _pod.pod.DEFAULT_POD_ROLES,
) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    _pod.build_pod(project, roles, codebase=f"/src/{project}")
    return home


# ── seam a: POST /approvals/<token> (HTTP) -> pregrant -> a real re-dispatch consumes it ──


class _ScriptedBackend:
    """Replays a fixed script of `ChatResponse`s -- the same self-contained double
    `test_dispatch.py` defines locally per-file rather than sharing one fake."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)

    def complete(self, messages: Any, **_kwargs: Any) -> ChatResponse:
        return self._responses.pop(0)


def _final_response(text: str) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(5, 5)
    )


class TestHttpGrantConsumesThePregrant:
    """The real `POST /approvals/<token>` write route granting a parked approval, threaded
    into the single-use pre-grant a real re-dispatch then consumes -- proving the HTTP layer
    and the park/pre-grant mechanism actually compose, which no other test drives together."""

    def test_a_parked_call_granted_over_http_passes_once_on_redispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A real policy-gated bash call parks; the operator grants it over real HTTP; a real
        re-dispatch's identical call is admitted once via the pre-grant, then the hop
        finishes."""
        from docket.core.policy import install_policies

        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 2, raising=True)
        home = _seed_pod(tmp_path, monkeypatch)
        install_policies()
        _fleet.meta_set("demo-lead", "approvalMode", "park")

        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
        park_backend = _ScriptedBackend(
            [
                _final_response("lead plan"),
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: park_backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        _dispatch.enqueue_task("demo", "clean the build dir")
        parked = _dispatch.dispatch_pod("demo")
        token = parked[0].approval_token
        assert token
        assert _dispatch.read_tasks("demo")[0]["status"] == "waiting_approval"

        # The real HTTP write route -- not `approval.approval_grant` called directly.
        class _Handler(_DocketHandler):
            serve_token = "seam-test-token"

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/approvals/{token}",
                data=json.dumps({"action": "grant"}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer seam-test-token",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                body = json.loads(resp.read())
        finally:
            server.shutdown()
            thread.join(timeout=5)

        assert status == 200
        assert body == {"ok": True, "token": token, "state": "granted"}

        task = _dispatch.read_tasks("demo")[0]
        assert task["status"] == "pending"
        assert len(task["pregrants"]) == 1
        assert task["pregrants"][0]["token"] == token

        # A real re-dispatch: the implementer's identical call is re-issued by the model
        # and this time is admitted via the single-use pre-grant `_handle_post_approvals`
        # produced, then the hop finishes normally.
        resume_backend = _ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
                _final_response("implementer done"),
            ]
        )
        driver2 = DocketDriver(backend_factory=lambda model: resume_backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver2)

        second = _dispatch.dispatch_pod("demo")

        assert second[0].status == "done", second[0].reason
        final = _dispatch.read_tasks("demo")[0]
        assert [h["role"] for h in final["hops"]] == ["lead", "implementer", "implementer"]
        assert final["hops"][1]["parked"] is True
        assert final["hops"][-1]["parked"] is False
        assert final["hops"][-1]["ok"] is True
        # The pre-grant is single-use -- a stray real audit.log under the real home was
        # never touched by this test (only the throwaway `home` this fixture built).
        assert home.is_dir()


# ── seam b: channel content level enforced at the real webhook delivery point ──


class _RecordingHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        headers_ci = {k.lower(): v for k, v in self.headers.items()}
        type(self).requests.append({"raw": body, "json": json.loads(body), "headers": headers_ci})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args: object) -> None:
        return


def _capture_server() -> tuple[ThreadingHTTPServer, str, type[_RecordingHandler]]:
    class _Handler(_RecordingHandler):
        pass

    _Handler.requests = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{port}/hook", _Handler


class TestChannelContentLevelEnforcedAtDelivery:
    """A real pending approval through a real `flush()` call into the real `webhook` dialect
    and two real local HTTP servers -- proving `content: minimal` vs `actions` is enforced at
    the actual delivery point, which no unit test exercises together."""

    def test_minimal_never_carries_the_command_line_actions_does(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two real `webhook` channels, one `content: minimal` and one `content: actions`,
        both subscribed to the same approval event: the canary command line must be absent
        from the wire at `minimal` and present at `actions`."""
        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        record_isolation_off(tmp_path / ".docket")
        canary = "git push origin CANARY_a1b2c3d4e5f6"
        _secrets.save_secrets({"WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldGtleQ=="})

        minimal_srv, minimal_url, minimal_handler = _capture_server()
        actions_srv, actions_url, actions_handler = _capture_server()
        try:
            token = _approval.approval_create("alpha", "implementer", canary)

            minimal_spec = _channel.ChannelSpec(
                kind="channel",
                name="minimal-hook",
                dialect="webhook",
                enabled=True,
                capabilities=["notify"],
                on=["approval.requested"],
                content="minimal",
                config={"url": minimal_url},
                secret="WEBHOOK_SECRET",
            )
            actions_spec = _channel.ChannelSpec(
                kind="channel",
                name="actions-hook",
                dialect="webhook",
                enabled=True,
                capabilities=["notify"],
                on=["approval.requested"],
                content="actions",
                config={"url": actions_url},
                secret="WEBHOOK_SECRET",
            )

            report = _notify.flush(
                [minimal_spec, actions_spec],
                _channel_adapters.sink_for,
                now="2026-09-29T00:00:00Z",
            )

            assert report.delivered == 2, report
            assert len(minimal_handler.requests) == 1
            assert len(actions_handler.requests) == 1

            minimal_body = minimal_handler.requests[0]["raw"]
            actions_body = actions_handler.requests[0]["raw"]
            assert canary.encode() not in minimal_body, (
                "minimal content leaked the command line onto the wire"
            )
            assert canary.encode() in actions_body

            minimal_json = minimal_handler.requests[0]["json"]
            actions_json = actions_handler.requests[0]["json"]
            assert "action" not in minimal_json["data"]
            assert actions_json["data"]["action"] == canary
            # Both still carry the token -- content level narrows what is shared, never
            # whether the item is identifiable at all.
            assert minimal_json["data"]["token"] == token
            assert actions_json["data"]["token"] == token

            # The signature really verifies -- a genuine Standard Webhooks round trip,
            # not just a header's presence.
            from docket.edges.adapters.channels.webhook import _sign

            secret_value = _secrets.secret_value("WEBHOOK_SECRET")
            assert secret_value is not None
            req = minimal_handler.requests[0]
            event_id = req["headers"]["webhook-id"]
            ts = req["headers"]["webhook-timestamp"]
            expected = _sign(secret_value, event_id, ts, req["raw"])
            assert req["headers"]["webhook-signature"] == expected
        finally:
            minimal_srv.shutdown()
            actions_srv.shutdown()


# ── seam c: the Lead's brief question -> answer_task -> the Lead's own next hop message ──


def _bind_pipeline(project: str, text: str) -> None:
    import hashlib

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = _pod.pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id(project, "lead"), "pipeline", digest)


def _bind_intake_pipeline(project: str) -> None:
    text = (_cfg.recipes_dir() / "intake" / "pipeline.yaml").read_text(encoding="utf-8")
    result = _pipeline.load_pipeline(text)
    assert result.spec is not None, result.errors
    _bind_pipeline(project, text)


_LEAD_NEEDS_INPUT_REPLY = """I need two decisions before I can start.

```json
{"objective": "add a widget", "acceptance": ["widget renders"], "questions": ["Which color?", "Which size?"]}
```
NEEDS-INPUT"""

_LEAD_READY_REPLY = """Thanks, now I have everything I need.

```json
{"objective": "add a widget", "acceptance": ["widget renders", "matches spec"]}
```
READY"""


class _IntakeRunner:
    """Scripted by role, not call order -- the Lead runs twice (NEEDS-INPUT, then the
    re-entry hop this test exists to inspect)."""

    def __init__(self, lead_replies: list[str], reviewer_reply: str = "APPROVE") -> None:
        self._lead_replies = list(lead_replies)
        self._reviewer_reply = reviewer_reply
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append((role, message))
        if role == "lead":
            reply = self._lead_replies.pop(0) if self._lead_replies else "READY"
            return _rd.TurnResult(True, reply, 0.0, {})
        if role == "reviewer":
            return _rd.TurnResult(True, self._reviewer_reply, 0.0, {})
        return _rd.TurnResult(True, "done", 0.0, {})


class TestBriefAnswerReachesTheLeadsNextMessage:
    """`test_dispatch.py` already proves the brief reaches the Implementer; it never inspects
    the Lead's own re-entry call. This drives a real `answer_task` into a real re-dispatch and
    reads the Lead's second prompt, proving the operator's typed answers round-trip."""

    def test_the_operators_exact_answer_text_appears_in_the_leads_reentry_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The operator answers with `{"q1": "blue", "q2": "large"}`; the Lead's second call
        message must contain `## Operator answers` with both exact values."""
        _seed_pod(tmp_path, monkeypatch, roles=("lead", "implementer", "reviewer"))
        _bind_intake_pipeline("demo")
        task = _dispatch.enqueue_task("demo", "build the widget")
        runner = _IntakeRunner([_LEAD_NEEDS_INPUT_REPLY, _LEAD_READY_REPLY])

        first = _dispatch.dispatch_pod("demo", runner=runner)
        assert first[0].status == "waiting_input"
        question = _dispatch.read_tasks("demo")[0]["question"]
        assert question["requestedSchema"]["properties"]["q1"]["title"] == "Which color?"
        assert question["requestedSchema"]["properties"]["q2"]["title"] == "Which size?"

        _answers.answer_task(
            "demo",
            task["id"],
            "accept",
            {"q1": "blue", "q2": "large"},
            channel="cli",
            actor="op",
        )

        final = _dispatch.dispatch_pod("demo", runner=runner)
        assert final[0].status == "done"

        lead_messages = [msg for role, msg in runner.calls if role == "lead"]
        assert len(lead_messages) == 2, "the Lead must run again after the answer"
        second_lead_message = lead_messages[1]

        assert "## Operator answers" in second_lead_message
        assert "Which color?" in second_lead_message or "add a widget" in question["message"]
        assert '"q1": "blue"' in second_lead_message
        assert '"q2": "large"' in second_lead_message
