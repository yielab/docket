"""``teams/roles.py``'s pure, non-registry pieces: ``hop_instruction``'s wire
round-trip, ``resolve_hop_instruction``'s gateContract-derived fallback, and that
every built-in/starter role's generated prose agrees with the live runtime contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.pods import write_security_vetter_md as _write_security_vetter_md
from tests.support.roles import write_vetter_overlay

from docket.kernel.home import Home, current_home, use_home
from docket.teams.role_schema import (
    ArchetypeError,
)
from docket.teams.roles import find_overlay_problems

SUBJECT = "docket.teams.roles"


class TestFindOverlayProblems:
    """`find_overlay_problems`: what `docket setup` surfaces for a malformed
    pod `roles.json` entry that `load_registry` silently skips."""

    def test_no_file_has_no_problems(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            assert find_overlay_problems("acme") == []

    def test_well_formed_overlay_has_no_problems(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            write_vetter_overlay(current_home().pod_config_dir("acme") / "roles.json", [])
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
