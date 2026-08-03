"""ROADMAP Phase 19 P19-12: per-role tool sets + identity composition.

Two omissions P19-5 recorded honestly rather than papering over:

1. **`ToolRegistry.without()` existed and was tested, but nothing composed it
   per role.** A Reviewer was *told* not to edit code (SOUL.md prose); it is
   now *unable* to. `core/archetypes.py`'s `denied_tools` (data) plus
   `registry_for_role` (the one composing function) close the gap;
   `core/agent_loop.py` calls it once per turn.
2. **The loop composed no system prompt at all.** `core/identity.py`'s
   `system_prompt_for_agent` reads SOUL.md, the live persona, and
   WORKFLOW_AUTO.md's resume/durability contract and folds them into one
   prompt, wired into `run_agent_turn`.

The load-bearing test in this file is
`TestReviewerCannotDispatchAWrite.test_reviewer_write_is_a_dispatch_level_denial`:
it proves the guarantee by dispatching a real `write` tool call through a
real (role-narrowed) registry and asserting `dispatch_tool` returns an
"unknown tool" denial -- not by inspecting `RoleArchetype.denied_tools` or
`ToolRegistry.names()` as a set.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import agent_loop as _loop
from docket.core import archetypes as _archetypes
from docket.core import identity as _identity
from docket.core.llm import (
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
    assistant,
)
from docket.core.models import AgentMeta, Persona
from docket.core.tools import ToolContext, builtin_registry, dispatch_tool
from docket.edges import store as _store

# ── fixtures ─────────────────────────────────────────────────────────────────


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
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)
    monkeypatch.setattr(
        _cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json", raising=True
    )


def _write_meta(agent_id: str, **overrides: object) -> Path:
    ws = _cfg.workspace_dir(agent_id)
    ws.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"kind": "project", "role": "implementer"}
    data.update(overrides)
    _store.write_json(_cfg.meta_path(agent_id), data)
    return ws


def _call(name: str, args: dict[str, object]) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=json.dumps(args))


class _ScriptedBackend:
    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

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
        return self._responses.pop(0)


def _final(text: str) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(5, 5)
    )


def _tool_call_response(call: ToolCall) -> ChatResponse:
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(10, 5),
    )


# ── (1) role -> toolset is data, and it is enforced ─────────────────────────


class TestArchetypeDeniedToolsAreData:
    """`denied_tools` on the built-in archetypes matches each role's
    documented SOUL.md contract. This is the data layer only -- the
    dispatch-level proof is `TestReviewerCannotDispatchAWrite` below."""

    def test_reviewer_denies_write_edit_bash(self) -> None:
        assert _archetypes.BUILTIN_ARCHETYPES["reviewer"].denied_tools == ("write", "edit", "bash")

    def test_tester_denies_write_edit_but_keeps_bash(self) -> None:
        tester = _archetypes.BUILTIN_ARCHETYPES["tester"]
        assert "bash" not in tester.denied_tools
        assert "write" in tester.denied_tools and "edit" in tester.denied_tools

    def test_lead_denies_write_edit_bash(self) -> None:
        assert _archetypes.BUILTIN_ARCHETYPES["lead"].denied_tools == ("write", "edit", "bash")

    def test_implementer_has_full_access(self) -> None:
        assert _archetypes.BUILTIN_ARCHETYPES["implementer"].denied_tools == ()

    def test_starter_read_only_roles_match_the_reviewer_pattern(self) -> None:
        for name in ("critic", "monitor"):
            assert _archetypes.STARTER_ARCHETYPES[name].denied_tools == ("write", "edit", "bash")

    def test_starter_write_roles_have_full_access(self) -> None:
        for name in ("researcher", "analyst", "writer", "operator"):
            assert _archetypes.STARTER_ARCHETYPES[name].denied_tools == ()

    def test_denied_tools_round_trips_through_wire_format(self) -> None:
        reviewer = _archetypes.BUILTIN_ARCHETYPES["reviewer"]
        wire = reviewer.to_wire()
        assert wire["deniedTools"] == ["write", "edit", "bash"]
        reparsed = _archetypes.from_wire("reviewer", wire)
        assert reparsed.denied_tools == ("write", "edit", "bash")

    def test_a_user_archetype_can_declare_its_own_denylist(self) -> None:
        doc = {
            "name": "custom-observer",
            "version": 1,
            "scope": "pod",
            "modelClass": "cheap",
            "soulTemplate": "hi ${project}",
            "agentsTemplate": "hi ${project}",
            "gateContract": {"kind": "none"},
            "editRights": "read-only",
            "toolProfile": "observer",
            "deniedTools": ["write", "edit", "bash"],
        }
        arch = _archetypes.add_user_archetype(doc)
        assert arch.denied_tools == ("write", "edit", "bash")
        assert _archetypes.load_registry().get("custom-observer").denied_tools == (
            "write",
            "edit",
            "bash",
        )


class TestRegistryForRole:
    """`registry_for_role` is the one function that turns the archetype data
    above into an actually-narrowed `ToolRegistry`, via the public
    `ToolRegistry.without()` API -- no per-role branch anywhere."""

    def test_reviewer_registry_lacks_write_and_edit(self) -> None:
        narrowed = _archetypes.registry_for_role(builtin_registry(), "reviewer")
        assert "write" not in narrowed
        assert "edit" not in narrowed
        assert "bash" not in narrowed
        assert "read" in narrowed and "glob" in narrowed and "grep" in narrowed

    def test_implementer_registry_is_unchanged(self) -> None:
        base = builtin_registry()
        narrowed = _archetypes.registry_for_role(base, "implementer")
        assert narrowed.names() == base.names()

    def test_unknown_role_leaves_the_registry_unchanged(self) -> None:
        base = builtin_registry()
        assert _archetypes.registry_for_role(base, "not-a-real-role").names() == base.names()
        assert _archetypes.registry_for_role(base, "").names() == base.names()


class TestReviewerCannotDispatchAWrite:
    """**The card's acceptance criterion.** A Reviewer registry genuinely
    lacks `write`/`edit` -- proven by dispatching a call and getting a
    tool-not-found denial, not by inspecting a dict or a set of names.
    """

    def test_reviewer_write_is_a_dispatch_level_denial(self, tmp_path: Path) -> None:
        ws = tmp_path / "rev-ws"
        ws.mkdir()
        reviewer_registry = _archetypes.registry_for_role(builtin_registry(), "reviewer")
        ctx = ToolContext(agent_id="rev-1", role="reviewer", project="demo", roots=(ws,))

        result = dispatch_tool(
            _call("write", {"path": "x.txt", "content": "should never land"}),
            ctx,
            reviewer_registry,
        )

        assert result.denied
        assert not result.executed
        assert "unknown tool" in result.reason
        assert not (ws / "x.txt").exists()

    def test_the_same_call_is_allowed_for_an_implementer(self, tmp_path: Path) -> None:
        """Contrast case: the denial above is role-specific, not a blanket
        policy against `write` -- an Implementer's registry still has it."""
        ws = tmp_path / "impl-ws"
        ws.mkdir()
        impl_registry = _archetypes.registry_for_role(builtin_registry(), "implementer")
        ctx = ToolContext(agent_id="impl-1", role="implementer", project="demo", roots=(ws,))

        result = dispatch_tool(
            _call("write", {"path": "x.txt", "content": "written by the implementer"}),
            ctx,
            impl_registry,
        )

        assert result.ok and result.executed and not result.denied
        assert (ws / "x.txt").read_text() == "written by the implementer"

    def test_run_agent_turn_actually_narrows_by_role_not_just_the_library_function(
        self, tmp_path: Path
    ) -> None:
        """The gap this card closes was that `without()` existed but nothing
        in the loop called it. This drives a full `run_agent_turn` (the full,
        unnarrowed `builtin_registry()` handed in, exactly like a real caller
        would) and shows the loop itself narrows by `ctx.role` before ever
        reaching `dispatch_tool`."""
        ws = tmp_path / "rev-ws2"
        ws.mkdir()
        ctx = ToolContext(
            agent_id="rev-2", role="reviewer", project="demo", roots=(ws,), timeout=10
        )
        call = _call("write", {"path": "x.txt", "content": "nope"})
        backend = _ScriptedBackend([_tool_call_response(call), _final("noted, no changes made")])

        result = _loop.run_agent_turn(
            backend, builtin_registry(), ctx, "agent:rev-2:default", "edit it"
        )

        assert result.ok is True
        assert result.stop_reason == "final_message"
        tool_msgs = [m for m in backend.calls[1] if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "REFUSED" in tool_msgs[0].content
        assert "unknown tool" in tool_msgs[0].content
        assert not (ws / "x.txt").exists()


# ── (2) the turn's system prompt ────────────────────────────────────────────


class TestComposeSystemPrompt:
    """Pure composition -- `core.identity.compose_system_prompt`."""

    def test_empty_everything_composes_to_empty(self) -> None:
        assert _identity.compose_system_prompt("", "", None) == ""

    def test_soul_and_workflow_are_both_present(self) -> None:
        prompt = _identity.compose_system_prompt(
            "# SOUL\nbody", "# WORKFLOW_AUTO\nresume rules", None
        )
        assert "# SOUL" in prompt
        assert "# WORKFLOW_AUTO" in prompt
        assert prompt.index("# SOUL") < prompt.index("# WORKFLOW_AUTO")

    def test_persona_is_folded_into_the_soul_text_even_without_a_block_yet(self) -> None:
        prompt = _identity.compose_system_prompt(
            "# SOUL\nbody", "", Persona(name="Orion", emoji="🔭")
        )
        assert "Orion" in prompt
        assert "🔭" in prompt

    def test_persona_overrides_a_stale_block_already_on_disk(self) -> None:
        stale_soul = (
            "# SOUL\nbody\n\n"
            f"{_identity.PERSONA_BEGIN}\n## Persona\nYou may present yourself as **Old Name**.\n"
            f"{_identity.PERSONA_END}\n"
        )
        prompt = _identity.compose_system_prompt(stale_soul, "", Persona(name="New Name"))
        assert "New Name" in prompt
        assert "Old Name" not in prompt

    def test_no_persona_set_renders_no_persona_section(self) -> None:
        prompt = _identity.compose_system_prompt("# SOUL\nbody", "# WORKFLOW_AUTO\nrules", None)
        assert "## Persona" not in prompt


class TestSystemPromptForAgent:
    """The I/O entry point -- reads a real workspace's SOUL.md/WORKFLOW_AUTO.md
    and this agent's live persona."""

    def test_composes_from_real_workspace_files(self) -> None:
        ws = _write_meta("id-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nYou are the Lead.\n")
        (ws / "WORKFLOW_AUTO.md").write_text("# WORKFLOW_AUTO.md\nResume before you greet.\n")

        prompt = _identity.system_prompt_for_agent("id-agent")

        assert "You are the Lead" in prompt
        assert "Resume before you greet" in prompt

    def test_persona_reaches_the_prompt(self) -> None:
        ws = _write_meta("persona-agent", persona={"name": "Orion", "emoji": "🔭"})
        (ws / "SOUL.md").write_text("# SOUL.md\nbody\n")

        prompt = _identity.system_prompt_for_agent("persona-agent")

        assert "Orion" in prompt and "🔭" in prompt

    def test_persona_reflects_the_live_meta_even_if_soul_never_had_it_upserted(self) -> None:
        """AgentMeta.display_name() is the one source of truth for a display
        name -- the prompt must not depend on SOUL.md having been re-rendered
        after a `docket persona set`."""
        ws = _write_meta("lagging-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nbody, no persona block\n")
        meta = AgentMeta.model_validate(_store.read_json(_cfg.meta_path("lagging-agent")))
        meta.persona = Persona(name="Freshly Set")
        _store.write_json(_cfg.meta_path("lagging-agent"), meta)

        prompt = _identity.system_prompt_for_agent("lagging-agent")

        assert "Freshly Set" in prompt

    def test_unprovisioned_agent_composes_to_empty(self) -> None:
        assert _identity.system_prompt_for_agent("nobody-here") == ""

    def test_empty_agent_id_composes_to_empty(self) -> None:
        assert _identity.system_prompt_for_agent("") == ""


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
        assert "Resume rules live here" in sent[0].content
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
        from docket.core.session import load_session

        ws = _write_meta("history-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nsecret identity text\n")
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
