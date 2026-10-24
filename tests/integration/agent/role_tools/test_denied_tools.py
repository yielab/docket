"""Per-role tool sets: denied tools are data and a reviewer cannot dispatch a write."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from tests.support.llm import final as _final
from tests.support.role_tools_harness import (
    _ScriptedBackend,
)

from docket.agent import loop as _loop
from docket.agent.ports import ChatResponse, TokenUsage, ToolCall, assistant
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry, dispatch_tool
from docket.hops.application.builtin_tools import builtin_registry
from docket.kernel.home import current_home, use_home
from docket.teams import builtin_roles as _builtin_roles
from docket.teams import role_schema as _role_schema
from docket.teams import roles as _archetypes

SUBJECT = "docket.agent.tools.registry"


def _call(name: str, args: dict[str, object]) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=json.dumps(args))


def _tool_call_response(call: ToolCall) -> ChatResponse:
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(10, 5),
    )


class TestArchetypeDeniedToolsAreData:
    """`denied_tools` on the built-in archetypes matches each role's
    documented SOUL.md contract. This is the data layer only -- the
    dispatch-level proof is `TestReviewerCannotDispatchAWrite` below."""

    def test_reviewer_denies_write_edit_bash(self) -> None:
        assert _builtin_roles.BUILTIN_ARCHETYPES["reviewer"].denied_tools == (
            "write",
            "edit",
            "bash",
        )

    def test_tester_denies_write_edit_but_keeps_bash(self) -> None:
        tester = _builtin_roles.BUILTIN_ARCHETYPES["tester"]
        assert "bash" not in tester.denied_tools
        assert "write" in tester.denied_tools and "edit" in tester.denied_tools

    def test_lead_denies_write_edit_bash(self) -> None:
        assert _builtin_roles.BUILTIN_ARCHETYPES["lead"].denied_tools == ("write", "edit", "bash")

    def test_implementer_has_full_access(self) -> None:
        assert _builtin_roles.BUILTIN_ARCHETYPES["implementer"].denied_tools == ()

    def test_starter_read_only_roles_match_the_reviewer_pattern(self) -> None:
        for name in ("critic", "monitor"):
            assert _builtin_roles.STARTER_ARCHETYPES[name].denied_tools == ("write", "edit", "bash")

    def test_starter_write_roles_have_full_access(self) -> None:
        for name in ("researcher", "analyst", "writer", "operator"):
            assert _builtin_roles.STARTER_ARCHETYPES[name].denied_tools == ()

    def test_denied_tools_round_trips_through_wire_format(self) -> None:
        reviewer = _builtin_roles.BUILTIN_ARCHETYPES["reviewer"]
        wire = reviewer.to_wire()
        assert wire["deniedTools"] == ["write", "edit", "bash"]
        reparsed = _role_schema.from_wire("reviewer", wire)
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
            "toolProfile": "observer",
            "deniedTools": ["write", "edit", "bash"],
        }
        arch = _archetypes.add_user_archetype(doc, "demo")
        assert arch.denied_tools == ("write", "edit", "bash")
        assert _archetypes.load_registry("demo").get("custom-observer").denied_tools == (
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


class TestRegistryForRoleExcludesByKindToo:
    """A namespaced tool (e.g. `mcp__<server>__<tool>`) never equals `"write"`/`"edit"`/`"bash"`,
    so `.without(*denied_tools)` alone can't remove it; `registry_for_role` also removes by
    `Tool.kind`, computed from the kinds the role's own `denied_tools` already imply."""

    def _registry_with_a_write_kind_extra(self) -> ToolRegistry:
        base = builtin_registry()
        base.register(
            Tool(
                name="mcp__weather__overwrite_config",
                description="a write-capable tool registered under a namespaced name",
                parameters={"type": "object", "properties": {}},
                handler=lambda args, ctx: ToolOutcome(True, content="ran"),
                kind="write",
            )
        )
        return base

    def test_reviewer_loses_the_namespaced_write_kind_tool_too(self) -> None:
        base = self._registry_with_a_write_kind_extra()
        narrowed = _archetypes.registry_for_role(base, "reviewer")
        assert "mcp__weather__overwrite_config" not in narrowed
        assert "read" in narrowed and "glob" in narrowed  # read-kind untouched

    def test_lead_loses_it_too_same_denied_kind_set_as_reviewer(self) -> None:
        base = self._registry_with_a_write_kind_extra()
        narrowed = _archetypes.registry_for_role(base, "lead")
        assert "mcp__weather__overwrite_config" not in narrowed

    def test_tester_loses_it_but_keeps_bash(self) -> None:
        """Tester denies write/edit (kind `write`) but not bash (kind
        `exec`) -- the kind-based exclusion only removes what that role's
        own denied kinds cover, not every non-read tool."""
        base = self._registry_with_a_write_kind_extra()
        narrowed = _archetypes.registry_for_role(base, "tester")
        assert "mcp__weather__overwrite_config" not in narrowed
        assert "bash" in narrowed

    def test_implementer_keeps_the_namespaced_tool(self) -> None:
        """Contrast case: implementer denies nothing, so nothing is excluded
        by kind either -- the mechanism narrows, it does not blanket-deny."""
        base = self._registry_with_a_write_kind_extra()
        narrowed = _archetypes.registry_for_role(base, "implementer")
        assert "mcp__weather__overwrite_config" in narrowed

    def test_a_read_kind_namespaced_tool_survives_reviewer_narrowing(self) -> None:
        """Kind, not the `mcp__` prefix, is what's being keyed on -- a
        read-kind extra tool is not swept up by write/exec exclusion."""
        base = builtin_registry()
        base.register(
            Tool(
                name="mcp__docs__lookup",
                description="a read-only tool, hypothetically",
                parameters={"type": "object", "properties": {}},
                handler=lambda args, ctx: ToolOutcome(True, content="ok"),
                kind="read",
            )
        )
        narrowed = _archetypes.registry_for_role(base, "reviewer")
        assert "mcp__docs__lookup" in narrowed

    def test_denied_kinds_do_not_depend_on_the_incoming_registry(self) -> None:
        """Denial must come from the ROLE's data, never from what `base` happens to contain:
        looking up denied kinds *in base* makes exclusion conditional on the built-in still being
        present there, and a narrower injected base (a supported shape) would then yield an empty
        denied-kind set -- handing a Reviewer back the write-capable tool this mechanism exists to
        keep away. `BUILTIN_TOOL_KINDS` is a static map for this reason."""
        base = ToolRegistry()
        base.register(
            Tool(
                name="read",
                description="read a file",
                parameters={"type": "object", "properties": {}},
                handler=lambda args, ctx: ToolOutcome(True, content="ok"),
                kind="read",
            )
        )
        base.register(
            Tool(
                name="mcp__fs__write_file",
                description="write-capable, arriving through MCP",
                parameters={"type": "object", "properties": {}},
                handler=lambda args, ctx: ToolOutcome(True, content="wrote"),
                kind="write",
            )
        )
        # No built-in write/edit/bash in `base` at all.
        narrowed = _archetypes.registry_for_role(base, "reviewer")
        assert "mcp__fs__write_file" not in narrowed
        assert "read" in narrowed

    def test_builtin_tool_kinds_matches_the_real_builtin_registry(self) -> None:
        """Drift guard: a new built-in must gain a capability entry; fetch needs an allowlist."""
        with use_home(
            dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
        ):
            real = builtin_registry()
            actual = {name: real.get(name).kind for name in real.names()}  # type: ignore[union-attr]
            assert actual == _archetypes.BUILTIN_TOOL_KINDS


class TestReviewerCannotDispatchAWrite:
    """A Reviewer registry genuinely lacks `write`/`edit`: proven by dispatching a call and
    getting a tool-not-found denial, not by inspecting a dict or set of names."""

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
        """Drives a full `run_agent_turn` with the full, unnarrowed `builtin_registry()` handed
        in (exactly like a real caller) and shows the loop itself narrows by `ctx.role` before
        ever reaching `dispatch_tool`."""
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
