"""DocketDriver.run_turn: the happy path, refusals and the gate end to end."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from tests.support.driver_harness import (
    _final_response,
    _never_called,
    _probe_call_response,
    _read_call_response,
    _ScriptedBackend,
)
from tests.support.pods import write_meta_overrides as _write_meta

from docket.agent.ports import (
    ChatResponse,
    TokenUsage,
    ToolCall,
    assistant,
)
from docket.agent.session import load_session
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry
from docket.governance import approval as _approval
from docket.hops.application.driver import DocketDriver
from docket.kernel.home import current_home, use_home
from docket.platform import store as _store
from docket.teams import agent_memory as _memory
from docket.teams import fleet as _fleet

SUBJECT = "docket.hops.application.driver"


def _consult_park_probe_registry() -> ToolRegistry:
    """A one-tool registry reporting the `consult_park` and `task_id` `run_turn` built."""
    registry = ToolRegistry()

    def _probe(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(True, content=f"park={ctx.consult_park} task={ctx.task_id}")

    registry.register(
        Tool(
            name="probe",
            description="reports ctx.consult_park",
            parameters={"type": "object", "properties": {}},
            handler=_probe,
            kind="read",
        )
    )
    return registry


class TestRunTurn:
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

    def test_runtime_prompt_projects_startup_state_without_private_file_commands(
        self, tmp_path: Path
    ) -> None:
        codebase = tmp_path / "runtime-project"
        codebase.mkdir()
        ws = _write_meta(
            "runtime-prompt-agent",
            role="reviewer",
            codebase=str(codebase),
        )
        (ws / "SOUL.md").write_text("# SOUL\nREVIEWER-ROLE-RULE\n", encoding="utf-8")
        _memory.seed_contract(ws, project="runtime-project", codebase=str(codebase))
        (ws / "AGENTS.md").write_text(
            "# AGENTS\n\n"
            "## Session Startup\n"
            "LEGACY-OPEN-PRIVATE\n\n"
            "## Red Lines\n"
            "SAFE-RED-LINE\n\n"
            "## Custom Operator Rules\n"
            "CUSTOM-RUNTIME-RULE\n",
            encoding="utf-8",
        )
        (ws / "HEARTBEAT.md").write_text(
            _memory.heartbeat_seed("runtime-prompt-agent").replace(
                "_none yet_", "CURRENT-ACTIVE-STATE"
            ),
            encoding="utf-8",
        )
        (ws / "TOOLS.md").write_text("README-VALIDATION-RULE\n", encoding="utf-8")
        (ws / "MEMORY.md").write_text("CURRENT-DURABLE-DECISION\n", encoding="utf-8")
        source_bytes = {
            path.name: path.read_bytes()
            for path in (
                ws / "WORKFLOW_AUTO.md",
                ws / "AGENTS.md",
                ws / "HEARTBEAT.md",
                ws / "TOOLS.md",
                ws / "MEMORY.md",
            )
        }
        backend = _ScriptedBackend([_final_response("PASS")])

        result = DocketDriver(backend_factory=lambda model: backend).run_turn(
            "runtime-prompt-agent",
            "agent:runtime-prompt-agent:default",
            "validate the repaired behavior",
            60,
        )

        assert result.ok is True
        system = backend.calls[0][0]
        assert system.role == "system"
        assert str(codebase) not in system.content
        assert "REVIEWER-ROLE-RULE" in system.content
        assert "CURRENT-ACTIVE-STATE" not in system.content
        assert "SAFE-RED-LINE" in system.content
        assert "CUSTOM-RUNTIME-RULE" in system.content
        assert "README-VALIDATION-RULE" not in system.content
        assert "CURRENT-DURABLE-DECISION" in system.content
        assert "LEGACY-OPEN-PRIVATE" not in system.content
        assert "open `HEARTBEAT.md`" not in system.content
        assert "write it to `HEARTBEAT.md`" not in system.content
        assert "`MEMORY.md` — what this project" not in system.content
        assert "Read it first every session" not in system.content
        assert "record it here" not in system.content
        assert system.content.count("Never access Docket private control files") == 1
        assert {
            path.name: path.read_bytes()
            for path in (
                ws / "WORKFLOW_AUTO.md",
                ws / "AGENTS.md",
                ws / "HEARTBEAT.md",
                ws / "TOOLS.md",
                ws / "MEMORY.md",
            )
        } == source_bytes
        stored = load_session("agent:runtime-prompt-agent:default")
        assert all(message.role != "system" for message in stored.messages)
        assert not any("CURRENT-DURABLE-DECISION" in message.content for message in stored.messages)

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

    def test_default_driver_stops_after_three_explicit_tool_approval_denials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_meta("denial-agent")
        _store.write_json(
            current_home().policies_dir / "approve-validation.json",
            {
                "kind": "policy",
                "name": "approve-validation",
                "description": "require an operator for validation",
                "appliesTo": ["*"],
                "on": "toolCall",
                "when": {"matches": "^validate\\b"},
                "then": "ask",
                "message": "operator validation required",
            },
        )
        with use_home(dataclasses.replace(current_home(), tool_approval_timeout=10)):

            def deny_pending(_seconds: float) -> None:
                pending = _approval.list_pending()
                assert len(pending) == 1
                _approval.approval_deny(str(pending[0]["token"]))

            monkeypatch.setattr(_approval, "pause", deny_pending)
            handler_calls: list[str] = []
            registry = ToolRegistry()
            registry.register(
                Tool(
                    name="validate",
                    description="operator-gated validation",
                    parameters={"type": "object", "properties": {}},
                    handler=lambda args, ctx: (
                        handler_calls.append("executed") or ToolOutcome(ok=True, content="ran")
                    ),
                    kind="read",
                )
            )
            responses = [
                ChatResponse(
                    ok=True,
                    message=assistant(
                        "",
                        tool_calls=[ToolCall(id=f"deny-{index}", name="validate", arguments="{}")],
                    ),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                )
                for index in range(1, 4)
            ]
            responses.append(_final_response("must not be requested"))
            backend = _ScriptedBackend(responses)
            driver = DocketDriver(
                backend_factory=lambda model: backend,
                registry_factory=lambda: registry,
            )
            session_key = "agent:denial-agent:default"

            result = driver.run_turn(
                "denial-agent",
                session_key,
                "validate without bypassing approval",
                60,
                trace_project="denial-project",
            )

            assert result.ok is False
            assert result.failure_kind == "invalid_output"
            assert "count=3" in result.error
            assert "approval_denied,approval_denied,approval_denied" in result.error
            assert len(backend.calls) == 3
            assert handler_calls == []
            record = load_session(session_key)
            assert [message.role for message in record.messages] == [
                "user",
                "assistant",
                "tool",
                "assistant",
                "tool",
                "assistant",
                "tool",
            ]
            assert record.usage.input_tokens + record.usage.output_tokens == 45
            approval_states = [
                json.loads(path.read_text(encoding="utf-8"))["state"]
                for path in current_home().approvals_dir.glob("*.json")
            ]
            assert approval_states == ["denied", "denied", "denied"]
            trace_path = current_home().traces_dir / "denial-project" / f"{session_key}.jsonl"
            denial_kinds = [
                json.loads(line)["payload"].get("denialKind")
                for line in trace_path.read_text(encoding="utf-8").splitlines()
                if json.loads(line)["event_type"] == "tool_result"
            ]
            assert denial_kinds == ["approval_denied", "approval_denied", "approval_denied"]
            # The approval record's own approval_denied trace events
            # (governance/approval.py's _emit_trace) must land under the pod (trace_project),
            # not under the agent id -- a separate file from the tool_result trace above.
            assert not (current_home().traces_dir / "denial-agent").exists()
            approval_trace_files = list(
                (current_home().traces_dir / "denial-project").glob("*-approval*.jsonl")
            )
            assert approval_trace_files, "expected an approval trace file filed under the pod"
            approval_event_types: list[str] = []
            for f in approval_trace_files:
                approval_event_types += [
                    json.loads(line)["event_type"]
                    for line in f.read_text(encoding="utf-8").splitlines()
                ]
            assert "approval_requested" not in approval_event_types
            assert approval_event_types.count("approval_denied") == 3

    def test_env_flows_into_the_tool_context(self) -> None:
        # "env" (not "echo") is on governance.security.SAFE_BINS' curated allowlist,
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


class TestConsultParkWiring:
    """Only a non-empty `trace_task_id` marks the turn as a pod dispatch hop."""

    @pytest.mark.parametrize(
        ("trace_task_id", "expected"),
        [(None, "park=False task="), ("", "park=False task="), ("t-1", "park=True task=t-1")],
    )
    def test_consult_park_follows_a_non_empty_task_id(
        self, trace_task_id: str | None, expected: str
    ) -> None:
        _write_meta("solo-agent")
        _fleet.disable_sandbox_isolation()
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_consult_park_probe_registry
        )

        result = driver.run_turn(
            "solo-agent", "agent:solo-agent:default", "go", 30, trace_task_id=trace_task_id
        )

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == expected
