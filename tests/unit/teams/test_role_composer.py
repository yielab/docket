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

from tests.support.roles import write_vetter_overlay

from docket.agent.tools.registry import Tool, ToolOutcome
from docket.hops.application.builtin_tools import builtin_registry
from docket.kernel.home import Home, current_home, use_home
from docket.platform import store as _store
from docket.teams.pod import member_id as _pod_member_id
from docket.teams.role_composer import registry_for_role

SUBJECT = "docket.teams.role_composer"


class TestPodRoleOverlay:
    """A pod's own role overlay (`pod_config_dir(project)/roles.json`) narrows that pod's
    roles, exercised via `registry_for_role`'s `project` parameter."""

    def test_pod_overlay_narrows_the_role_it_defines(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_vetter_overlay(current_home().pod_config_dir("acme") / "roles.json", ["write"])

            narrowed = registry_for_role(builtin_registry(), "vetter", project="acme")

            assert "write" not in narrowed.names()

    def test_no_project_does_not_see_the_pod_overlay(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_vetter_overlay(current_home().pod_config_dir("acme") / "roles.json", ["write"])

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
