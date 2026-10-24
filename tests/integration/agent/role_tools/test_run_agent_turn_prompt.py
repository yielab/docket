"""run_agent_turn composes the member's system prompt."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.support.llm import final as _final
from tests.support.role_tools_harness import (
    _ScriptedBackend,
    _write_meta,
)

from docket.agent import loop as _loop
from docket.agent.tools.builtin_tools import builtin_registry
from docket.agent.tools.registry import ToolContext
from docket.kernel.home import current_home

SUBJECT = "docket.agent.tools.registry"


class TestRunAgentTurnComposesTheSystemPrompt:
    """Wired into the loop: `run_agent_turn` prepends a `system` message built
    from this agent's real identity files, and never persists it to session
    history."""

    def test_system_message_is_prepended_to_the_backend_call(self, tmp_path: Path) -> None:
        ws = _write_meta("prompted-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nYou are the Implementer.\n")
        (ws / "WORKFLOW_AUTO.md").write_text("# WORKFLOW_AUTO.md\nResume rules live here.\n")
        roots = tmp_path / "code"
        roots.mkdir()
        ctx = ToolContext(
            agent_id="prompted-agent", role="implementer", project="demo", roots=(roots,)
        )
        backend = _ScriptedBackend([_final("hi")])

        _loop.run_agent_turn(
            backend, builtin_registry(), ctx, "agent:prompted-agent:default", "hello"
        )

        sent = backend.calls[0]
        assert sent[0].role == "system"
        assert "You are the Implementer" in sent[0].content
        assert "Docket live runtime contract" in sent[0].content
        assert "Resume rules live here" not in sent[0].content
        assert str(roots) not in sent[0].content
        assert sent[-1].role == "user"

    def test_no_identity_files_means_no_system_message(self, tmp_path: Path) -> None:
        roots = tmp_path / "code2"
        roots.mkdir()
        ctx = ToolContext(agent_id="bare-agent", role="implementer", project="demo", roots=(roots,))
        backend = _ScriptedBackend([_final("hi")])

        _loop.run_agent_turn(backend, builtin_registry(), ctx, "agent:bare-agent:default", "hello")

        sent = backend.calls[0]
        assert all(m.role != "system" for m in sent)

    def test_the_system_message_is_never_persisted_to_session_history(self, tmp_path: Path) -> None:
        from docket.agent.session import load_session

        ws = _write_meta("history-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nsecret identity text\n")
        (ws / "HEARTBEAT.md").write_text("private active checkpoint\n")
        roots = tmp_path / "code3"
        roots.mkdir()
        ctx = ToolContext(
            agent_id="history-agent", role="implementer", project="demo", roots=(roots,)
        )
        backend = _ScriptedBackend([_final("hi")])

        _loop.run_agent_turn(
            backend, builtin_registry(), ctx, "agent:history-agent:default", "hello"
        )

        record = load_session("agent:history-agent:default")
        assert all(m.role != "system" for m in record.messages)
        assert not any("secret identity text" in m.content for m in record.messages)
        assert not any("private active checkpoint" in m.content for m in record.messages)

    def test_composing_the_prompt_emits_one_prompt_composed_event(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        """One `prompt_composed` trace event per turn, naming each section's fit."""
        ws = _write_meta("traced-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")
        (ws / "AGENTS.md").write_text("AGENT-RULE-LINE\n")
        (ws / "MEMORY.md").write_text("## Facts\nDURABLE-MEMORY-LINE\n")
        roots = tmp_path / "code4"
        roots.mkdir()
        ctx = ToolContext(
            agent_id="traced-agent", role="implementer", project="demo", roots=(roots,)
        )
        backend = _ScriptedBackend([_final("hi")])
        events: list[dict[str, object]] = []

        def _trace(
            project: str,
            traced_session: str,
            role: str,
            event_type: str,
            payload: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            if event_type == "prompt_composed":
                events.append(json.loads(payload))
            return "written"

        real_tracer_except(trace_event=_trace)

        _loop.run_agent_turn(backend, builtin_registry(), ctx, "agent:traced-agent:default", "go")

        assert len(events) == 1
        names = {section["name"] for section in events[0]["sections"]}
        assert {"SOUL.md", "AGENTS.md", "MEMORY.md"} <= names
        for section in events[0]["sections"]:
            assert section["status"] in {"full", "truncated", "omitted"}
            assert isinstance(section["bytes"], int)
        assert events[0]["budgetTokens"] == current_home().context_token_budget_default
        assert events[0]["budgetSource"] == "default"

    def test_prompt_composed_names_a_window_share_budget_end_to_end(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        """A large registered window resolves a bigger budget end to end, and the
        trace event names it, without any explicit override."""
        ws = _write_meta("windowed-traced-agent")
        (ws / "SOUL.md").write_text("SOUL-HEAD-MARKER\n" + ("s" * 30_000) + "\nSOUL-TAIL-MARKER\n")
        (ws / "HEARTBEAT.md").write_text("## Ledger\nACTIVE-LEDGER-LINE\n")
        (ws / "TOOLS.md").write_text("VERIFY-GATE-LINE\n")
        roots = tmp_path / "code4b"
        roots.mkdir()
        ctx = ToolContext(
            agent_id="windowed-traced-agent", role="implementer", project="demo", roots=(roots,)
        )
        backend = _ScriptedBackend([_final("hi")])
        events: list[dict[str, object]] = []

        def _trace(
            project: str,
            traced_session: str,
            role: str,
            event_type: str,
            payload: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            if event_type == "prompt_composed":
                events.append(json.loads(payload))
            return "written"

        real_tracer_except(trace_event=_trace)

        _loop.run_agent_turn(
            backend,
            builtin_registry(),
            ctx,
            "agent:windowed-traced-agent:default",
            "go",
            config=_loop.LoopConfig(context_window_tokens=200_000, max_tokens=8_192),
        )

        assert len(events) == 1
        assert events[0]["budgetSource"] == "window"
        assert events[0]["budgetTokens"] > current_home().context_token_budget_default
        soul_section = next(s for s in events[0]["sections"] if s["name"] == "SOUL.md")
        assert soul_section["status"] == "full"

    def test_a_registered_16k_window_pins_todays_behaviour(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        """The only window docket has ever run against live must not change: a
        registered 16k/8k local endpoint resolves the exact same budget as no window
        at all, so an oversized SOUL is still truncated identically."""
        ws = _write_meta("local16k-traced-agent")
        (ws / "SOUL.md").write_text("SOUL-HEAD-MARKER\n" + ("s" * 30_000) + "\nSOUL-TAIL-MARKER\n")
        (ws / "HEARTBEAT.md").write_text("## Ledger\nACTIVE-LEDGER-LINE\n")
        (ws / "TOOLS.md").write_text("VERIFY-GATE-LINE\n")
        roots = tmp_path / "code4c"
        roots.mkdir()
        ctx = ToolContext(
            agent_id="local16k-traced-agent", role="implementer", project="demo", roots=(roots,)
        )
        backend = _ScriptedBackend([_final("hi")])
        events: list[dict[str, object]] = []

        def _trace(
            project: str,
            traced_session: str,
            role: str,
            event_type: str,
            payload: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            if event_type == "prompt_composed":
                events.append(json.loads(payload))
            return "written"

        real_tracer_except(trace_event=_trace)

        _loop.run_agent_turn(
            backend,
            builtin_registry(),
            ctx,
            "agent:local16k-traced-agent:default",
            "go",
            config=_loop.LoopConfig(context_window_tokens=16_384, max_tokens=8_192),
        )

        assert len(events) == 1
        assert events[0]["budgetSource"] == "default"
        assert events[0]["budgetTokens"] == current_home().context_token_budget_default
        soul_section = next(s for s in events[0]["sections"] if s["name"] == "SOUL.md")
        assert soul_section["status"] == "truncated"

    def test_a_runtime_contract_only_composition_still_emits_prompt_composed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        """A workspace holding only the startup contract composes a system prompt, so the
        turn traces it with an empty section list."""
        ws = _write_meta("contract-only-agent")
        (ws / "WORKFLOW_AUTO.md").write_text("# WORKFLOW_AUTO.md\nresume rules\n")
        roots = tmp_path / "code4d"
        roots.mkdir()
        ctx = ToolContext(
            agent_id="contract-only-agent", role="implementer", project="demo", roots=(roots,)
        )
        backend = _ScriptedBackend([_final("hi")])
        events: list[dict[str, object]] = []

        def _trace(
            project: str,
            traced_session: str,
            role: str,
            event_type: str,
            payload: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            if event_type == "prompt_composed":
                events.append(json.loads(payload))
            return "written"

        real_tracer_except(trace_event=_trace)

        _loop.run_agent_turn(
            backend, builtin_registry(), ctx, "agent:contract-only-agent:default", "go"
        )

        assert backend.calls[0][0].role == "system"
        assert len(events) == 1
        assert events[0]["sections"] == []
        assert events[0]["budgetSource"] == "default"

    def test_no_identity_files_means_no_prompt_composed_event(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        """No composed prompt means no `prompt_composed` event either."""
        roots = tmp_path / "code5"
        roots.mkdir()
        ctx = ToolContext(
            agent_id="bare-traced-agent", role="implementer", project="demo", roots=(roots,)
        )
        backend = _ScriptedBackend([_final("hi")])
        events: list[dict[str, object]] = []

        def _trace(
            project: str,
            traced_session: str,
            role: str,
            event_type: str,
            payload: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            if event_type == "prompt_composed":
                events.append(json.loads(payload))
            return "written"

        real_tracer_except(trace_event=_trace)

        _loop.run_agent_turn(
            backend, builtin_registry(), ctx, "agent:bare-traced-agent:default", "go"
        )

        assert events == []
