"""``teams/roles.py``'s pure, non-registry pieces: ``hop_instruction``'s wire
round-trip, ``resolve_hop_instruction``'s gateContract-derived fallback, and that
every built-in/starter role's generated prose agrees with the live runtime contract.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from docket.agent.tools.registry import Tool, ToolOutcome, builtin_registry
from docket.kernel.home import Home, current_home, use_home
from docket.platform import store as _store
from docket.teams.pod import member_id as _pod_member_id
from docket.teams.role_schema import (
    ArchetypeError,
    from_wire,
)
from docket.teams.roles import find_overlay_problems, registry_for_role

SUBJECT = "docket.teams.roles"


class TestFindOverlayProblems:
    """`find_overlay_problems`: what `docket setup` surfaces for a malformed
    pod `roles.json` entry that `load_registry` silently skips."""

    def test_no_file_has_no_problems(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            assert find_overlay_problems("acme") == []

    def test_well_formed_overlay_has_no_problems(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            _write_vetter_overlay(current_home().pod_config_dir("acme") / "roles.json", [])
            assert find_overlay_problems("acme") == []

    def test_malformed_entry_is_named_by_role(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            path = current_home().pod_config_dir("acme") / "roles.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"roles": {"broken-role": {"name": "broken-role"}}}))
            problems = find_overlay_problems("acme")
            assert len(problems) == 1
            assert problems[0][0] == "broken-role"

    def test_malformed_json_is_reported_by_file(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            path = current_home().pod_config_dir("acme") / "roles.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json")
            problems = find_overlay_problems("acme")
            assert len(problems) == 1
            assert problems[0][0] == str(path)


def _write_vetter_overlay(path: Path, denied_tools: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "roles": {
                    "vetter": {
                        "name": "vetter",
                        "version": 1,
                        "scope": "pod",
                        "modelClass": "cheap",
                        "soulTemplate": "x",
                        "agentsTemplate": "y",
                        "gateContract": {"kind": "none"},
                        "toolProfile": "read-only",
                        "deniedTools": denied_tools,
                    }
                }
            }
        )
    )


class TestPodRoleOverlay:
    """A pod's own role overlay (`pod_config_dir(project)/roles.json`) narrows that pod's
    roles, exercised via `registry_for_role`'s `project` parameter."""

    def test_pod_overlay_narrows_the_role_it_defines(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            _write_vetter_overlay(current_home().pod_config_dir("acme") / "roles.json", ["write"])

            narrowed = registry_for_role(builtin_registry(), "vetter", project="acme")

            assert "write" not in narrowed.names()

    def test_no_project_does_not_see_the_pod_overlay(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            _write_vetter_overlay(current_home().pod_config_dir("acme") / "roles.json", ["write"])

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


_SECURITY_VETTER_LONG: dict[str, object] = {
    "name": "security-vetter",
    "scope": "pod",
    "modelClass": "strong",
    "description": "read-only security pass over the implementer's change",
    "tokenBudget": 6000,
    "deniedTools": ["write", "edit", "bash"],
    "gateContract": {"kind": "verdict", "regexes": ["APPROVE", "REQUEST-CHANGES"]},
    "soulTemplate": (
        "# SOUL.md — ${project} · ${role}\n\n"
        "You are the **${role}** of the **${project}** pod.\n"
        "Codebase: ${codebaseOrConfigured} (stack: ${stack}).\n"
    ),
    "agentsTemplate": (
        "# AGENTS.md — ${project} · ${role}\n\n## Red Lines\n\nStay within the `${project}` pod.\n"
    ),
}

_SECURITY_VETTER_SHORT: dict[str, object] = {
    "kind": "role",
    "name": "security-vetter",
    "description": "read-only security pass over the implementer's change",
    "model": "strong",
    "cannot": ["write", "edit", "bash"],
    "verdict": ["APPROVE", "REQUEST-CHANGES"],
}


def _write_security_vetter_md(directory: Path) -> None:
    (directory / "security-vetter.md").write_text(
        _SECURITY_VETTER_LONG["soulTemplate"]  # type: ignore[operator]
        + "\n## AGENTS\n\n"
        + _SECURITY_VETTER_LONG["agentsTemplate"],  # type: ignore[operator]
        encoding="utf-8",
    )


class TestLoadRoleFile:
    """`kind: role` names a document's kind, not its form: a canonical document keeps its
    canonical fields, and a document mixing both forms is refused naming the clash."""

    def test_canonical_document_with_kind_role_passes_through(self, tmp_path: Path) -> None:
        from docket.teams import roles as _arch

        path = tmp_path / "security-vetter.yaml"
        path.write_text(json.dumps({"kind": "role", **_SECURITY_VETTER_LONG}), encoding="utf-8")

        loaded = _arch.load_role_file(str(path))

        assert from_wire("security-vetter", loaded) == from_wire(
            "security-vetter", _SECURITY_VETTER_LONG
        )

    def test_mixed_short_and_canonical_keys_are_refused(self, tmp_path: Path) -> None:
        from docket.teams import roles as _arch

        _write_security_vetter_md(tmp_path)
        path = tmp_path / "security-vetter.yaml"
        path.write_text(
            json.dumps({**_SECURITY_VETTER_SHORT, "deniedTools": ["write"]}), encoding="utf-8"
        )

        with pytest.raises(ArchetypeError, match="deniedTools"):
            _arch.load_role_file(str(path))
