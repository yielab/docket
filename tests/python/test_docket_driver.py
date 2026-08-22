"""`DocketDriver`, the daemon-free `RuntimeDriver`
(`edges/adapters/docket_runtime.py`).

`DocketDriver` implements the 7-method `RuntimeDriver` Protocol on top of
`core/agent_loop.py` with no external daemon underneath. Covers:

* **`run_turn`** maps `AgentLoopResult` onto `TurnResult` honestly: `cost_usd`
  stays `0.0` always, real tool calls actually execute end-to-end (through
  the real gated dispatcher, not a stub), and an ordinary failure (missing
  meta, unresolvable model) comes back as `TurnResult(ok=False, ...)`,
  never an exception.
* **Root resolution precedence** for the tool-containment boundary --
  worktree > codebase > work_dir > bare workspace dir -- proven with the
  real `read` tool against real marker files, not just by inspecting the
  helper's logic.
* **`provision`/`teardown`** are honest no-ops (no daemon to register or
  unregister with), and `capabilities()` says so.
* **`list_sessions`/`read_new_turns`/`usage`** read real, durable
  `core/session.py` storage, scoped correctly to one agent's own sessions.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _gates
from docket.core import fleet as _fleet
from docket.core.audit import read_audit
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.core.runtime_driver import PIPELINE_WORKTREE_ENV
from docket.core.tools import Tool, ToolContext, ToolRegistry
from docket.edges import store as _store
from docket.edges.adapters import system as _system
from docket.edges.adapters.docket_runtime import DocketDriver
from docket.edges.adapters.system import SandboxAvailability
from docket.edges.adapters.toolbox import ToolOutcome


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", tmp_path / "docket", raising=True)
    monkeypatch.setattr(
        _cfg, "PROJECTS_DIR", tmp_path / "docket" / "workspaces" / "projects", raising=True
    )
    monkeypatch.setattr(_cfg, "SESSIONS_DIR", tmp_path / "sessions", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", tmp_path / "traces", raising=True)
    monkeypatch.setattr(_cfg, "POLICIES_DIR", tmp_path / "policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", tmp_path / "docket" / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)
    # DOCKET_SANDBOX_BACKEND leaking in from the real dev/CI environment would
    # make TestIsolationWiring's "no backend available" cases flaky -- start
    # every test from the same clean slate and let individual tests opt in.
    monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)


def _write_meta(agent_id: str, **overrides: object) -> Path:
    """Write a real `.docket-meta.json` for *agent_id* and return its workspace dir."""
    ws = _cfg.workspace_dir(agent_id)
    ws.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"kind": "project", "role": "implementer", "model": "test/model"}
    data.update(overrides)
    _store.write_json(_cfg.meta_path(agent_id), data)
    return ws


class _ScriptedBackend:
    """Replays a fixed script of `ChatResponse`s -- see test_agent_loop.py
    for the identical pattern; redefined locally per this suite's convention
    of self-contained per-file test doubles rather than a shared fake."""

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []
        self.max_tokens_seen: list[int | None] = []

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        self.max_tokens_seen.append(max_tokens)
        return self._responses.pop(0)


def _final_response(text: str, usage: TokenUsage | None = None) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=usage or TokenUsage(5, 5)
    )


def _read_call_response(path: str, usage: TokenUsage | None = None) -> ChatResponse:
    call = ToolCall(id="c1", name="read", arguments=json.dumps({"path": path}))
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=usage or TokenUsage(10, 5),
    )


def _never_called(model: str):  # pragma: no cover - only exercised on a real bug
    raise AssertionError(f"backend_factory should not have been called for model {model!r}")


# ── run_turn ─────────────────────────────────────────────────────────────────


class TestRunTurn:
    def test_registered_limits_reach_the_loop_and_transport(self) -> None:
        _write_meta("bounded-agent")
        backend = _ScriptedBackend([_final_response("bounded")])
        backend.context_window_tokens = 4096  # type: ignore[attr-defined]
        backend.max_output_tokens = 64  # type: ignore[attr-defined]
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn("bounded-agent", "agent:bounded-agent:default", "hi", 60)

        assert result.ok
        assert backend.max_tokens_seen == [64]

    def test_irreducible_registered_window_fails_before_transport(self) -> None:
        _write_meta("tiny-window-agent")
        backend = _ScriptedBackend([_final_response("must not be called")])
        backend.context_window_tokens = 1  # type: ignore[attr-defined]
        backend.max_output_tokens = 1  # type: ignore[attr-defined]
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn(
            "tiny-window-agent", "agent:tiny-window-agent:default", "keep this exact", 60
        )

        assert not result.ok
        assert result.failure_kind == "invalid_output"
        assert "registered context window 1" in result.error
        assert backend.calls == []

    def test_happy_path_final_message_costs_nothing(self) -> None:
        _write_meta("solo-agent")
        backend = _ScriptedBackend([_final_response("hello there", TokenUsage(12, 4))])
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "hi", 60)

        assert result.ok is True
        assert result.output == "hello there"
        assert result.cost_usd == 0.0
        assert result.error == ""
        assert result.failure_kind is None

    def test_missing_meta_fails_without_raising(self) -> None:
        driver = DocketDriver(backend_factory=_never_called)

        result = driver.run_turn("ghost-agent", "agent:ghost-agent:default", "hi", 60)

        assert result.ok is False
        assert result.failure_kind == "invalid_output"
        assert "ghost-agent" in result.error

    def test_unresolvable_model_reports_daemon_error(self) -> None:
        _write_meta("solo-agent", model="nowhere/model")
        driver = DocketDriver(backend_factory=lambda model: None)

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "hi", 60)

        assert result.ok is False
        assert result.failure_kind == "daemon_error"
        assert "nowhere/model" in result.error

    def test_a_real_tool_call_executes_end_to_end_through_the_gate(self) -> None:
        ws = _write_meta("reader-agent")
        (ws / "notes.txt").write_text("top secret\n")
        backend = _ScriptedBackend(
            [_read_call_response("notes.txt"), _final_response("here it is")]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn("reader-agent", "agent:reader-agent:default", "read notes.txt", 60)

        assert result.ok is True
        assert result.output == "here it is"
        assert result.cost_usd == 0.0
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert "top secret" in tool_msg.content

    def test_env_flows_into_the_tool_context(self) -> None:
        # "env" (not "echo") is on core.security.SAFE_BINS' curated allowlist,
        # so this runs unattended instead of tripping the approval gate.
        _write_meta("env-agent")
        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "env"}))
        backend = _ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
                _final_response("ran it"),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn(
            "env-agent",
            "agent:env-agent:default",
            "run it",
            30,
            env={"DOCKET_TEST_VAR": "hello-from-env"},
        )

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert "DOCKET_TEST_VAR=hello-from-env" in tool_msg.content

    def test_on_spawn_is_accepted_and_ignored(self) -> None:
        """No real OS process backs this driver -- on_spawn must not raise or
        be required, matching the Protocol's own "may simply ignore it"."""
        _write_meta("solo-agent")
        backend = _ScriptedBackend([_final_response("ok")])
        driver = DocketDriver(backend_factory=lambda model: backend)
        spawned: list[int] = []

        result = driver.run_turn(
            "solo-agent", "agent:solo-agent:default", "hi", 30, on_spawn=spawned.append
        )

        assert result.ok is True
        assert spawned == []


# ── root resolution precedence ───────────────────────────────────────────────


def _tool_reply(backend: _ScriptedBackend) -> str:
    return next(m for m in backend.calls[1] if m.role == "tool").content


class TestRootResolutionPrecedence:
    """worktree > codebase > work_dir > bare workspace dir. Each case proven
    with the real `read` tool against a distinctly-labelled marker file, not
    by inspecting `_resolve_roots`'s logic directly."""

    def test_bare_workspace_is_the_base_fallback(self) -> None:
        ws = _write_meta("prec-a")
        (ws / "marker.txt").write_text("workspace")
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])
        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "prec-a", "agent:prec-a:default", "go", 30
        )
        assert _tool_reply(backend) == "workspace"

    def test_work_dir_wins_over_bare_workspace(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "marker.txt").write_text("workdir")
        _write_meta("prec-b", workDir=str(work_dir))
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])
        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "prec-b", "agent:prec-b:default", "go", 30
        )
        assert _tool_reply(backend) == "workdir"

    def test_codebase_wins_over_work_dir(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "work2"
        work_dir.mkdir()
        (work_dir / "marker.txt").write_text("workdir2")
        codebase = tmp_path / "code"
        codebase.mkdir()
        (codebase / "marker.txt").write_text("codebase")
        _write_meta("prec-c", workDir=str(work_dir), codebase=str(codebase))
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])
        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "prec-c", "agent:prec-c:default", "go", 30
        )
        assert _tool_reply(backend) == "codebase"

    def test_worktree_wins_over_codebase(self, tmp_path: Path) -> None:
        codebase = tmp_path / "code2"
        codebase.mkdir()
        (codebase / "marker.txt").write_text("codebase2")
        worktree = tmp_path / "wt"
        worktree.mkdir()
        (worktree / "marker.txt").write_text("worktree")
        _write_meta("prec-d", codebase=str(codebase), worktreeDir=str(worktree))
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])
        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "prec-d", "agent:prec-d:default", "go", 30
        )
        assert _tool_reply(backend) == "worktree"

    def test_registered_same_pod_worktree_wins_for_reviewer(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        origin.mkdir()
        (origin / "marker.txt").write_text("origin")
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "marker.txt").write_text("implementation")
        _write_meta(
            "demo-implementer",
            role="implementer",
            codebase=str(origin),
            worktreeDir=str(worktree),
        )
        _write_meta("demo-reviewer", role="reviewer", codebase=str(origin))
        _fleet.add_agent("demo-implementer", "test/model", "agent:demo:default", "default")
        _fleet.add_agent("demo-reviewer", "test/model", "agent:demo:default", "default")
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])

        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "demo-reviewer",
            "agent:demo-reviewer:default",
            "go",
            30,
            {PIPELINE_WORKTREE_ENV: str(worktree)},
        )

        assert _tool_reply(backend) == "implementation"


# ── provision / teardown / capabilities ──────────────────────────────────────


class TestProvisionTeardownCapabilities:
    def test_provision_is_an_honest_noop(self) -> None:
        result = DocketDriver().provision("some-agent", "/tmp/ws", "test/model")
        assert result.ok is True
        assert "no daemon" in result.message

    def test_teardown_is_an_honest_noop(self) -> None:
        result = DocketDriver().teardown("some-agent")
        assert result.ok is True
        assert "no daemon" in result.message

    def test_capabilities_reports_this_driver_honestly(self) -> None:
        caps = DocketDriver().capabilities()
        assert caps.driver_name == "docket"
        # cost_usd is never populated by this driver -- see run_turn/usage.
        assert caps.reports_cost_usd is False
        # Provision/teardown are no-ops because Docket owns its local state.
        assert caps.supports_provisioning is False
        # list_sessions/read_new_turns/usage are real, unlike a driver with
        # no durable store at all.
        assert caps.supports_sessions is True


# ── list_sessions / read_new_turns / usage ───────────────────────────────────


class TestSessionIntrospection:
    def test_reflect_a_real_turn_with_a_tool_call(self) -> None:
        ws = _write_meta("chat-agent")
        (ws / "x.txt").write_text("hi\n")
        session_key = "agent:chat-agent:default"
        backend = _ScriptedBackend(
            [
                _read_call_response("x.txt", TokenUsage(10, 5)),
                _final_response("done", TokenUsage(6, 2)),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)
        driver.run_turn("chat-agent", session_key, "go", 60)

        sessions = driver.list_sessions("chat-agent")
        assert len(sessions) == 1
        assert sessions[0].session_id == session_key
        assert sessions[0].turns == 4  # user, assistant(tool_calls), tool, assistant(final)

        first_slice = driver.read_new_turns("chat-agent", session_key, 0)
        assert first_slice.had_new_content is True
        assert [t.kind for t in first_slice.turns] == ["other", "tool_call", "tool_result", "other"]
        assert first_slice.next_offset == 4
        assert first_slice.session_start_ts != ""

        second_slice = driver.read_new_turns("chat-agent", session_key, first_slice.next_offset)
        assert second_slice.had_new_content is False

        report = driver.usage("chat-agent")
        assert report.totals.input_tokens == 16
        assert report.totals.output_tokens == 7
        assert report.totals.cost_usd == 0.0
        assert report.by_day == []

    def test_list_sessions_is_scoped_to_the_agent_id_prefix(self) -> None:
        _write_meta("agent-a")
        _write_meta("agent-b")
        DocketDriver(
            backend_factory=lambda model: _ScriptedBackend([_final_response("a")])
        ).run_turn("agent-a", "agent:agent-a:default", "hi", 30)
        DocketDriver(
            backend_factory=lambda model: _ScriptedBackend([_final_response("b")])
        ).run_turn("agent-b", "agent:agent-b:default", "hi", 30)

        sessions_a = DocketDriver().list_sessions("agent-a")
        assert [s.session_id for s in sessions_a] == ["agent:agent-a:default"]

    def test_no_sessions_directory_yet_returns_empty(self) -> None:
        assert DocketDriver().list_sessions("nobody") == []

    def test_read_new_turns_on_an_unknown_session_is_a_no_op_slice(self) -> None:
        sl = DocketDriver().read_new_turns("nobody", "agent:nobody:default", 0)
        assert sl.had_new_content is False
        assert sl.turns == []


# ── isolation wiring (W18-3) ──────────────────────────────────────────────────


def _probe_registry() -> ToolRegistry:
    """A one-tool registry that reports back the exact `ctx.sandbox` value
    `run_turn` built, so a test can observe it without hand-constructing a
    `ToolContext` itself -- the real construction path is the thing under
    test."""
    registry = ToolRegistry()

    def _probe(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(True, content=f"sandbox={ctx.sandbox}")

    registry.register(
        Tool(
            name="probe",
            description="reports ctx.sandbox",
            parameters={"type": "object", "properties": {}},
            handler=_probe,
            kind="read",
        )
    )
    return registry


def _probe_call_response() -> ChatResponse:
    call = ToolCall(id="c1", name="probe", arguments="{}")
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


class TestIsolationWiring:
    """`docket gates isolate on` writes `security.isolationEnabled` to
    fleet.json -- before this wire, nothing on the real turn path ever read
    it back, so isolation ON was silently indistinguishable from isolation
    OFF on every live turn (the reproduction this card was opened against).
    `DocketDriver.run_turn` now resolves it via `_resolve_sandbox`.
    """

    def test_isolation_off_leaves_ctx_sandbox_off(self) -> None:
        # No fleet.json write at all -- the default, overwhelmingly common
        # path (`get_isolation_enabled()` on a missing fleet.json resolves to
        # False). This is the "off stays byte-identical" proof: the
        # `ToolContext` a real turn builds today carries `sandbox="off"`.
        _write_meta("solo-agent")
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_probe_registry
        )

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "sandbox=off"

    def test_isolation_on_with_backend_available_sets_sandbox_auto(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_meta("solo-agent")
        monkeypatch.setattr(
            _system,
            "sandbox_availability",
            lambda: SandboxAvailability(backend="docker", docker=True, bwrap=False),
        )
        _fleet.set_isolation_enabled(True)
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_probe_registry
        )

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "sandbox=auto"

    def test_isolation_on_no_backend_refuses_the_turn_rather_than_running_unsandboxed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The failure mode this card exists to end: isolation is ON but
        # neither docker nor bwrap is usable. The turn must refuse outright
        # -- not silently downgrade to an unsandboxed run -- and the LLM
        # backend must never even be reached (`_never_called` fails the test
        # if it is).
        _write_meta("solo-agent")
        monkeypatch.setattr(
            _system,
            "sandbox_availability",
            lambda: SandboxAvailability(backend="none", docker=False, bwrap=False),
        )
        _fleet.set_isolation_enabled(True)
        driver = DocketDriver(backend_factory=_never_called)

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is False
        assert result.failure_kind == "daemon_error"
        assert "docker" in result.error.lower()
        assert "bwrap" in result.error.lower()

        refusals = [e for e in read_audit() if e["action"] == "isolation.refused"]
        assert len(refusals) == 1
        assert "agent=solo-agent" in refusals[0]["detail"]
        assert "docker=False" in refusals[0]["detail"]
        assert "bwrap=False" in refusals[0]["detail"]

    def test_docket_sandbox_backend_override_still_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Both real backends report usable, but the operator's own override
        # forces "none" -- this wire adds no parallel backend-selection
        # mechanism, it only gates in front of the existing one
        # (`system.sandbox_availability`), so the override must still be the
        # last word, exactly as it already is for `toolbox.run_bash`.
        _write_meta("solo-agent")
        monkeypatch.setattr(_system, "docker_daemon_reachable", lambda: True)
        monkeypatch.setattr(_system, "bwrap_available", lambda: True)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        _fleet.set_isolation_enabled(True)
        driver = DocketDriver(backend_factory=_never_called)

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is False
        assert result.failure_kind == "daemon_error"

    def test_the_flag_docket_gates_isolate_on_writes_is_the_one_the_turn_reads(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # End-to-end through fleet: drive the real `docket gates isolate on`
        # CLI path (not `set_isolation_enabled` directly, and not a
        # hand-built `ToolContext`), then confirm a real turn observes
        # exactly the flag it wrote.
        _write_meta("solo-agent")
        monkeypatch.setattr(_gates.shutil, "which", lambda name, *a, **k: "/usr/bin/docker")
        monkeypatch.setattr(
            _system,
            "sandbox_availability",
            lambda: SandboxAvailability(backend="bwrap", docker=False, bwrap=True),
        )
        rc = _gates.run_gates("isolate", want="on")
        capsys.readouterr()
        assert rc == 0

        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_probe_registry
        )
        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "sandbox=auto"
