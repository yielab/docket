"""MCP tools reachable in a live turn (`agent/tools/mcp_tools.py`).

Covers `DocketDriver.run_turn` calling `load_mcp_tools` via its
`mcp_loader` seam before per-turn role narrowing, every MCP-adapted tool
registering its server's declared `kind` (defaulting to `write`) so
`registry_for_role` excludes it by capability from a write-denied role
unless the server declares itself `kind: read`, and a server's `tools`
allow-list narrowing which of its advertised tools get registered at
all. No real subprocess.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from tests.support.roles import write_role_overlay, write_vetter_overlay

from docket.agent.tools.registry import Tool, ToolOutcome, ToolRegistry
from docket.hops.application.builtin_tools import builtin_registry
from docket.kernel.home import Home, current_home, use_home
from docket.platform import store as _store
from docket.teams.pod import member_id as _pod_member_id
from docket.teams.role_composer import registry_for_role

SUBJECT = "docket.teams.role_composer"


class TestPodRoleOverlay:
    """A pod's own role overlay (`pod_config_dir(project)/roles/`) narrows that pod's
    roles, exercised via `registry_for_role`'s `project` parameter."""

    def test_pod_overlay_narrows_the_role_it_defines(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_vetter_overlay("acme", ["write"])

            narrowed = registry_for_role(builtin_registry(), "vetter", project="acme")

            assert "write" not in narrowed.names()

    def test_no_project_does_not_see_the_pod_overlay(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_vetter_overlay("acme", ["write"])

            narrowed = registry_for_role(builtin_registry(), "vetter", project="")

            assert "write" in narrowed.names()


def _write_lead_meta(project: str, denied_tools: str) -> None:
    path = current_home().meta_path(_pod_member_id(project, "lead"))
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(
        path,
        {"schemaVersion": 1, "kind": "project", "scope": "project", "deniedTools": denied_tools},
    )


class TestPodDeniedTools:
    """A pod's own `deniedTools` setting unions with a role's own `denied_tools`,
    so a pod-level denial reaches every role in it."""

    def test_pod_denial_removes_a_tool_the_role_itself_allows(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            # "implementer" denies nothing by default -- a pod-level "fetch" denial
            # must still remove it, proving this is a union, not just the role's own list.
            _write_lead_meta("acme", "fetch")

            narrowed = registry_for_role(builtin_registry(), "implementer", project="acme")

            assert "fetch" not in narrowed.names()
            assert "write" in narrowed.names()  # nothing else the role allows is touched

    def test_denying_one_builtin_removes_that_builtin_alone(self, tmp_path: Path) -> None:
        with use_home(
            dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
        ):
            _write_lead_meta("acme", "fetch")

            narrowed = registry_for_role(builtin_registry(), "implementer", project="acme")

            assert set(builtin_registry().names()) - set(narrowed.names()) == {"fetch"}

    def test_denying_a_builtin_still_removes_an_mcp_tool_of_its_kind(self, tmp_path: Path) -> None:
        _write_lead_meta("acme", "fetch")
        base = builtin_registry()
        base.register(
            Tool(
                name="mcp__fake__lookup",
                description="a namespaced read tool",
                parameters={"type": "object", "properties": {}},
                handler=lambda args, ctx: ToolOutcome(True, content="ran"),
                kind="read",
            )
        )

        narrowed = registry_for_role(base, "implementer", project="acme")

        assert "mcp__fake__lookup" not in narrowed.names()
        assert "read" in narrowed.names()

    def test_no_project_ignores_the_pod_setting(self, tmp_path: Path) -> None:
        with (
            use_home(Home(tmp_path / ".docket")),
            use_home(
                dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
            ),
        ):
            _write_lead_meta("acme", "fetch")

            narrowed = registry_for_role(builtin_registry(), "implementer", project="")

            assert "fetch" in narrowed.names()


def _closing_tool() -> Tool:
    return Tool(
        name="handoff",
        description="close the step",
        parameters={"type": "object", "properties": {}},
        handler=lambda args, ctx: ToolOutcome(ok=True, content="done"),
        ends_turn=True,
    )


def _verify_tool() -> Tool:
    return Tool(
        name="verify",
        description="run the check",
        parameters={"type": "object", "properties": {}},
        handler=lambda args, ctx: ToolOutcome(ok=True, content="ok"),
        kind="exec",
    )


class TestHopTools:
    """What a hop sees: the profile's surface, then the allow-list, then the role's denials."""

    def test_an_allow_list_never_grants_a_denied_tool(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "vetter", ["bash"], extra="tools: [read, bash]\n")

            narrowed = registry_for_role(builtin_registry(), "vetter", project="acme")

            assert narrowed.names() == ["read"]

    def test_a_step_allow_list_replaces_the_archetypes(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "vetter", [], extra="tools: [read, bash]\n")

            narrowed = registry_for_role(
                builtin_registry(), "vetter", project="acme", allow=("grep",)
            )

            assert narrowed.names() == ["grep"]

    def test_no_allow_list_leaves_every_tool_the_role_may_hold(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "vetter", ["write", "edit"])

            narrowed = registry_for_role(builtin_registry(), "vetter", project="acme")

            assert {"read", "grep", "bash"} <= set(narrowed.names())

    def test_the_minimal_surface_keeps_what_finds_reads_changes_runs_and_checks_and_the_closing_tool(
        self,
    ) -> None:
        base = builtin_registry()
        base.register(_verify_tool())
        base.register(_closing_tool())

        narrowed = registry_for_role(base, "implementer", surface="minimal")

        assert sorted(narrowed.names()) == [
            "bash",
            "edit",
            "glob",
            "handoff",
            "read",
            "verify",
            "write",
        ]

    def test_an_allow_list_keeps_the_closing_tool(self) -> None:
        base = builtin_registry()
        base.register(_closing_tool())

        narrowed = registry_for_role(base, "implementer", allow=("read",))

        assert sorted(narrowed.names()) == ["handoff", "read"]

    def test_the_full_surface_returns_the_registry_unchanged(self) -> None:
        base = builtin_registry()

        assert registry_for_role(base, "implementer", surface="full") is base

    def test_the_allow_list_narrows_the_surface_and_never_widens_it(self) -> None:
        narrowed = registry_for_role(
            builtin_registry(), "implementer", surface="minimal", allow=("read", "grep")
        )

        assert narrowed.names() == ["read"]

    def test_a_role_denied_bash_is_not_offered_the_tools_that_serve_a_background_process(
        self,
    ) -> None:
        for role in ("reviewer", "lead"):
            narrowed = registry_for_role(builtin_registry(), role)

            assert not {"bash", "process_output", "process_stop"} & set(narrowed.names())

    def test_a_pod_denying_bash_removes_them_from_every_role_in_it(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            _write_lead_meta("acme", "bash")

            narrowed = registry_for_role(builtin_registry(), "implementer", project="acme")

            assert not {"bash", "process_output", "process_stop"} & set(narrowed.names())

    def test_a_role_that_keeps_bash_keeps_them(self) -> None:
        narrowed = registry_for_role(builtin_registry(), "implementer")

        assert {"bash", "process_output", "process_stop"} <= set(narrowed.names())


def _mcp_tool(name: str, kind: str) -> Tool:
    return Tool(
        name=name,
        description=f"a {kind} tool",
        parameters={"type": "object", "properties": {}},
        handler=lambda args, ctx: ToolOutcome(ok=True, content="ran"),
        kind=kind,  # type: ignore[arg-type]
    )


def _outward_registry() -> ToolRegistry:
    base = builtin_registry()
    for name, kind in (
        ("mcp__mail__send", "send"),
        ("mcp__mail__draft", "send"),
        ("mcp__inbox__list", "read"),
        ("mcp__notes__save", "write"),
    ):
        base.register(_mcp_tool(name, kind))
    return base


class TestSendTools:
    """A `send` tool acts outside the machine: only a role whose own allow-list names it holds it."""

    def test_a_role_with_no_allow_list_is_not_offered_a_send_tool(self) -> None:
        narrowed = registry_for_role(_outward_registry(), "implementer")

        assert "mcp__mail__send" not in narrowed.names()
        assert {"mcp__inbox__list", "mcp__notes__save", "read"} <= set(narrowed.names())

    def test_a_role_naming_the_tool_is_offered_it_and_only_it(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "actor", [], extra="tools: [read, mcp__mail__send]\n")

            narrowed = registry_for_role(_outward_registry(), "actor", project="acme")

            assert sorted(narrowed.names()) == ["mcp__mail__send", "read"]

    def test_a_role_naming_the_server_is_offered_every_tool_of_it(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "actor", [], extra="tools: [mcp__mail]\n")

            narrowed = registry_for_role(_outward_registry(), "actor", project="acme")

            assert sorted(narrowed.names()) == ["mcp__mail__draft", "mcp__mail__send"]

    def test_a_step_allow_list_never_grants_a_send_tool_the_role_does_not_name(
        self, tmp_path: Path
    ) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "actor", [], extra="tools: [read]\n")

            narrowed = registry_for_role(
                _outward_registry(), "actor", project="acme", allow=("read", "mcp__mail__send")
            )

            assert narrowed.names() == ["read"]

    def test_a_step_allow_list_can_narrow_a_role_that_names_it(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "actor", [], extra="tools: [read, mcp__mail__send]\n")

            narrowed = registry_for_role(
                _outward_registry(), "actor", project="acme", allow=("read",)
            )

            assert narrowed.names() == ["read"]

    def test_denying_write_leaves_a_send_tool_alone(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay(
                "acme", "actor", ["write"], extra="tools: [mcp__mail__send, mcp__notes__save]\n"
            )

            narrowed = registry_for_role(_outward_registry(), "actor", project="acme")

            assert narrowed.names() == ["mcp__mail__send"]

    def test_cannot_send_removes_the_send_tools_of_a_role_that_names_them(
        self, tmp_path: Path
    ) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "actor", ["send"], extra="tools: [read, mcp__mail__send]\n")

            narrowed = registry_for_role(_outward_registry(), "actor", project="acme")

            assert narrowed.names() == ["read"]

    def test_a_non_pod_caller_is_offered_no_send_tool(self) -> None:
        narrowed = registry_for_role(_outward_registry(), "")

        assert not [n for n in narrowed.names() if n.startswith("mcp__mail")]


class TestMinimalSurfaceKeepsWhatTheRoleNames:
    """Under `minimal` the allow-list in force still keeps the tools it names."""

    def test_a_role_naming_an_mcp_tool_keeps_it(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "actor", [], extra="tools: [read, mcp__mail__send]\n")

            narrowed = registry_for_role(
                _outward_registry(), "actor", project="acme", surface="minimal"
            )

            assert sorted(narrowed.names()) == ["mcp__mail__send", "read"]

    def test_a_role_naming_the_server_keeps_every_tool_of_it(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "actor", [], extra="tools: [read, mcp__notes]\n")

            narrowed = registry_for_role(
                _outward_registry(), "actor", project="acme", surface="minimal"
            )

            assert sorted(narrowed.names()) == ["mcp__notes__save", "read"]

    def test_a_role_with_no_allow_list_keeps_no_mcp_tool(self) -> None:
        narrowed = registry_for_role(_outward_registry(), "implementer", surface="minimal")

        assert not [n for n in narrowed.names() if n.startswith("mcp__")]
        assert {"bash", "read", "edit", "write"} <= set(narrowed.names())

    def test_a_tool_the_role_does_not_name_is_still_dropped(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "actor", [], extra="tools: [read, mcp__notes__save]\n")

            narrowed = registry_for_role(
                _outward_registry(), "actor", project="acme", surface="minimal"
            )

            assert "mcp__inbox__list" not in narrowed.names()
            assert "bash" not in narrowed.names()

    def test_a_step_allow_list_replaces_the_role_s_for_the_surface(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "actor", [], extra="tools: [read, mcp__notes__save]\n")

            narrowed = registry_for_role(
                _outward_registry(),
                "actor",
                project="acme",
                surface="minimal",
                allow=("read", "mcp__inbox__list"),
            )

            assert sorted(narrowed.names()) == ["mcp__inbox__list", "read"]

    def test_a_send_tool_still_needs_the_role_s_own_list(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay("acme", "actor", [], extra="tools: [read]\n")

            narrowed = registry_for_role(
                _outward_registry(),
                "actor",
                project="acme",
                surface="minimal",
                allow=("read", "mcp__mail__send"),
            )

            assert narrowed.names() == ["read"]

    def test_a_denied_tool_is_not_kept_by_being_named(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_role_overlay(
                "acme", "actor", ["write"], extra="tools: [read, mcp__notes__save]\n"
            )

            narrowed = registry_for_role(
                _outward_registry(), "actor", project="acme", surface="minimal"
            )

            assert narrowed.names() == ["read"]
