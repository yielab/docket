"""``teams/roles.py``'s pure, non-registry pieces: ``hop_instruction``'s wire
round-trip, ``resolve_hop_prompt``'s gateContract-derived fallback, and that
every built-in/starter role's generated prose agrees with the live runtime contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.pods import write_security_vetter_md as _write_security_vetter_md
from tests.support.roles import write_vetter_overlay

from docket.agent.tools import mcp_tools
from docket.hops.application.handoff_tool import HANDOFF_TOOL
from docket.hops.application.verify_tool import VERIFY_TOOL
from docket.kernel.home import Home, current_home, use_home
from docket.teams.role_schema import (
    ArchetypeError,
)
from docket.teams.roles import (
    MCP_TOOL_PREFIX,
    STEP_TOOL_NAMES,
    allow_list_names,
    find_overlay_problems,
    unknown_allow_list_tools,
)

SUBJECT = "docket.teams.roles"


class TestFindOverlayProblems:
    """`find_overlay_problems`: what `docket setup` surfaces for a malformed
    pod role file that `load_registry` silently skips."""

    def test_no_file_has_no_problems(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            assert find_overlay_problems("acme") == []

    def test_well_formed_overlay_has_no_problems(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_vetter_overlay("acme", [])
            assert find_overlay_problems("acme") == []

    def test_an_invalid_role_file_is_named_by_file(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            roles = current_home().pod_config_dir("acme") / "roles"
            roles.mkdir(parents=True)
            (roles / "broken-role.yaml").write_text("kind: role\nname: broken-role\nmodel: huge\n")
            problems = find_overlay_problems("acme")
            assert len(problems) == 1
            assert problems[0][0] == str(roles / "broken-role.yaml")
            assert "model" in problems[0][1]

    def test_unparseable_yaml_is_reported_by_file(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            roles = current_home().pod_config_dir("acme") / "roles"
            roles.mkdir(parents=True)
            (roles / "vetter.yaml").write_text("{not yaml")
            problems = find_overlay_problems("acme")
            assert len(problems) == 1
            assert problems[0][0] == str(roles / "vetter.yaml")


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


class TestLoadRoleFile:
    """A role file is read in the short form only: a canonical key is refused naming the
    short-form key to write instead, with or without short-form keys beside it."""

    def test_a_canonical_document_is_refused_naming_each_short_form_key(
        self, tmp_path: Path
    ) -> None:
        from docket.teams import roles as _arch

        path = tmp_path / "security-vetter.yaml"
        path.write_text(json.dumps({"kind": "role", **_SECURITY_VETTER_LONG}), encoding="utf-8")

        with pytest.raises(ArchetypeError) as exc_info:
            _arch.load_role_file(str(path))

        message = str(exc_info.value)
        for canonical, short in (
            ("modelClass", "model"),
            ("deniedTools", "cannot"),
            ("gateContract", "verdict, verify or approval"),
            ("soulTemplate", "instructions"),
        ):
            assert f"replace `{canonical}` with `{short}" in message

    def test_mixed_short_and_canonical_keys_are_refused(self, tmp_path: Path) -> None:
        from docket.teams import roles as _arch

        _write_security_vetter_md(tmp_path)
        path = tmp_path / "security-vetter.yaml"
        path.write_text(
            json.dumps({**_SECURITY_VETTER_SHORT, "deniedTools": ["write"]}), encoding="utf-8"
        )

        with pytest.raises(ArchetypeError, match="deniedTools"):
            _arch.load_role_file(str(path))


def _write_role(roles: Path, name: str, hop: str) -> None:
    roles.mkdir(parents=True, exist_ok=True)
    (roles / f"{name}.yaml").write_text(
        f"kind: role\nname: {name}\nmodel: cheap\nhopInstruction: {hop}\n", encoding="utf-8"
    )
    (roles / f"{name}.md").write_text("soul\n", encoding="utf-8")


class TestRoleScopes:
    """`load_registry` reads the role files of `Home.scopes("roles", project)`, nearest first."""

    def test_the_operators_role_overlays_the_built_in_for_every_pod(self) -> None:
        from docket.teams.roles import load_registry

        _write_role(current_home().roles_dir, "lead", "OPERATOR")

        for project in ("", "acme"):
            registry = load_registry(project)
            lead = registry.get("lead")
            assert lead is not None and lead.hop_instruction == "OPERATOR"
            assert registry.source_of("lead") == "operator"

    def test_the_pod_overlay_beats_the_operator_and_stays_with_its_pod(self) -> None:
        from docket.teams.roles import load_registry

        _write_role(current_home().roles_dir, "lead", "OPERATOR")
        _write_role(current_home().pod_config_dir("acme") / "roles", "lead", "POD")

        mine = load_registry("acme")
        theirs = load_registry("beta")
        assert mine.get("lead").hop_instruction == "POD"  # type: ignore[union-attr]
        assert mine.source_of("lead") == "pod:acme"
        assert theirs.get("lead").hop_instruction == "OPERATOR"  # type: ignore[union-attr]

    def test_a_role_no_file_defines_keeps_its_built_in_source(self) -> None:
        from docket.teams.roles import load_registry

        registry = load_registry("acme")

        assert registry.source_of("lead") == "built-in"
        assert registry.source_of("researcher") == "starter"
        assert registry.source_of("ghost") == ""

    def test_a_roles_json_is_not_read(self) -> None:
        from docket.teams.roles import load_registry

        legacy = current_home().pod_config_dir("acme") / "roles.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"roles": {"vetter": {"name": "vetter"}}}))

        assert load_registry("acme").get("vetter") is None


class TestAllowListToolNames:
    """`unknown_allow_list_tools`: the names an allow-list holds that docket ships no tool for."""

    def test_the_step_tools_and_the_mcp_namespace_match_their_producers(self) -> None:
        assert set(STEP_TOOL_NAMES) == {VERIFY_TOOL, HANDOFF_TOOL}
        assert MCP_TOOL_PREFIX == mcp_tools.NAMESPACE_PREFIX

    def test_only_unshipped_names_are_returned_once_each(self) -> None:
        names = ("read", "grpe", "verify", "mcp__a__b", "grpe", "handoff")

        assert unknown_allow_list_tools(names) == ["grpe"]

    def test_a_service_name_is_accepted_like_an_mcp_name(self) -> None:
        assert unknown_allow_list_tools(("svc__crm", "svc__crm__get_contact", "grpe")) == ["grpe"]

    def test_a_service_entry_names_its_operations_and_an_operation_names_itself(self) -> None:
        assert allow_list_names(("svc__crm",), "svc__crm__get_contact")
        assert allow_list_names(("svc__crm__get_contact",), "svc__crm__get_contact")
        assert not allow_list_names(("svc__crm__get_contact",), "svc__crm__get_contact_all")
        assert not allow_list_names(("svc__crm",), "svc__crmx__get_contact")
        assert not allow_list_names(("svc__billing",), "svc__crm__get_contact")
