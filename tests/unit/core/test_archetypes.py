"""``core/archetypes.py``'s pure, non-registry pieces: ``hop_instruction``'s wire
round-trip, ``resolve_hop_instruction``'s gateContract-derived fallback, and that
every built-in/starter role's generated prose agrees with the live runtime contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core.archetypes import (
    BUILTIN_ARCHETYPES,
    STARTER_ARCHETYPES,
    ArchetypeError,
    GateContract,
    RoleArchetype,
    add_user_archetype,
    find_overlay_problems,
    from_wire,
    normalize_role,
    registry_for_role,
    render,
    resolve_hop_instruction,
)
from docket.core.memory import HEARTBEAT_FILE
from docket.core.pod import member_id as _pod_member_id
from docket.core.tools import builtin_registry
from docket.edges import store as _store

SUBJECT = "docket.core.archetypes"


def _archetype(gate: GateContract, hop_instruction: str = "") -> RoleArchetype:
    return RoleArchetype(
        name="custom-role",
        version=1,
        scope="pod",
        model_class="cheap",
        soul_template="You are ${role}.",
        agents_template="Session for ${role}.",
        gate_contract=gate,
        tool_profile="read-only",
        hop_instruction=hop_instruction,
    )


class TestResolveHopInstruction:
    def test_declared_hop_instruction_wins_outright(self) -> None:
        arch = _archetype(GateContract(kind="none"), hop_instruction="Do the thing.")
        assert resolve_hop_instruction(arch) == "Do the thing."

    def test_verdict_gate_generates_marker_instruction(self) -> None:
        arch = _archetype(GateContract(kind="verdict", regexes=("APPROVE", "REQUEST-CHANGES")))
        instruction = resolve_hop_instruction(arch)
        assert "APPROVE or REQUEST-CHANGES" in instruction
        assert "one output line" in instruction

    def test_mechanical_gate_generates_an_instruction(self) -> None:
        arch = _archetype(GateContract(kind="mechanical"))
        assert resolve_hop_instruction(arch) != ""

    def test_approval_gate_generates_an_instruction(self) -> None:
        arch = _archetype(GateContract(kind="approval"))
        assert resolve_hop_instruction(arch) != ""

    def test_none_gate_generates_no_instruction(self) -> None:
        arch = _archetype(GateContract(kind="none"))
        assert resolve_hop_instruction(arch) == ""

    def test_declared_instruction_overrides_generated_one(self) -> None:
        arch = _archetype(
            GateContract(kind="verdict", regexes=("APPROVE", "REJECT")),
            hop_instruction="Custom review note.",
        )
        assert resolve_hop_instruction(arch) == "Custom review note."


class TestHopInstructionWireFormat:
    def test_to_wire_omits_empty_hop_instruction(self) -> None:
        arch = _archetype(GateContract(kind="none"))
        assert "hopInstruction" not in arch.to_wire()

    def test_to_wire_includes_declared_hop_instruction(self) -> None:
        arch = _archetype(GateContract(kind="none"), hop_instruction="Do the thing.")
        assert arch.to_wire()["hopInstruction"] == "Do the thing."

    def test_from_wire_round_trips_hop_instruction(self) -> None:
        doc = {
            "name": "custom-role",
            "version": 1,
            "scope": "pod",
            "modelClass": "cheap",
            "soulTemplate": "x",
            "agentsTemplate": "y",
            "gateContract": {"kind": "none"},
            "editRights": "read-only",
            "toolProfile": "read-only",
            "hopInstruction": "Do the thing.",
        }
        arch = from_wire("custom-role", doc)
        assert arch.hop_instruction == "Do the thing."

    def test_from_wire_defaults_hop_instruction_to_empty(self) -> None:
        doc = {
            "name": "custom-role",
            "version": 1,
            "scope": "pod",
            "modelClass": "cheap",
            "soulTemplate": "x",
            "agentsTemplate": "y",
            "gateContract": {"kind": "none"},
            "editRights": "read-only",
            "toolProfile": "read-only",
        }
        arch = from_wire("custom-role", doc)
        assert arch.hop_instruction == ""


class TestEditRightsRetired:
    """`editRights` is retired (ADR 0012 §2 rule 7): accepted on read, never written --
    `deniedTools` is the only capability statement left."""

    def _doc(self) -> dict[str, object]:
        return {
            "name": "custom-role",
            "version": 1,
            "scope": "pod",
            "modelClass": "cheap",
            "soulTemplate": "x",
            "agentsTemplate": "y",
            "gateContract": {"kind": "none"},
            "editRights": "write",
            "toolProfile": "read-only",
        }

    def test_a_document_carrying_edit_rights_loads_and_drops_it(self) -> None:
        arch = from_wire("custom-role", self._doc())
        assert "editRights" not in arch.to_wire()

    def test_pod_overlay_written_by_roles_add_carries_no_edit_rights(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repoint_docket_home(monkeypatch, tmp_path / ".docket")

        add_user_archetype(self._doc(), project="acme")

        overlay_path = _cfg.pod_config_dir("acme") / "roles.json"
        written = json.loads(overlay_path.read_text(encoding="utf-8"))
        assert "editRights" not in written["roles"]["custom-role"]


#: Sample render() variables covering every placeholder any built-in/starter
#: template references (role-archetypes.spec.md "Template rendering").
_SAMPLE_VARIABLES = {
    "project": "demo",
    "role": "sample-role",
    "memberId": "demo-sample-role",
    "sessionKey": "agent:demo:default",
    "objective": "Demo project",
    "codebase": "/src/demo",
    "codebaseOrConfigured": "/src/demo",
    "codebaseOrIt": "/src/demo",
    "stack": "Python",
    "workDir": "/src/demo",
    "requiredStartupFile": "WORKFLOW_AUTO.md",
}


def _instructs_a_private_write(prompt: str) -> str:
    """Offending line if *prompt* asks the model to write HEARTBEAT.md/memory/
    itself, else ``""`` -- a check over the rendered prompt, not a source grep."""
    for line in prompt.lower().splitlines():
        if "write" not in line:
            continue
        if HEARTBEAT_FILE.lower() in line or "memory/" in line:
            return line
    return ""


class TestGeneratedInstructionsAgreeWithRuntimeContract:
    """No built-in/starter archetype's rendered SOUL.md + AGENTS.md may instruct the
    model to write HEARTBEAT.md or memory/ itself -- that contradicts
    `core/identity.py`'s live runtime contract, composed into the same turn."""

    def test_no_archetype_instructs_a_private_write(self) -> None:
        offenders: dict[str, str] = {}
        for name, arch in {**BUILTIN_ARCHETYPES, **STARTER_ARCHETYPES}.items():
            variables = {**_SAMPLE_VARIABLES, "role": name, "memberId": f"demo-{name}"}
            prompt = "\n".join(
                (
                    render(arch.soul_template, variables),
                    render(arch.agents_template, variables),
                )
            )
            offense = _instructs_a_private_write(prompt)
            if offense:
                offenders[name] = offense
        assert offenders == {}


class TestFindOverlayProblems:
    """`find_overlay_problems`: what `docket doctor` surfaces for a malformed
    `docket-roles.json` entry that `load_registry` silently skips."""

    def test_no_file_has_no_problems(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        assert find_overlay_problems() == []

    def test_well_formed_overlay_has_no_problems(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        repoint_docket_home(monkeypatch, home)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.ARCHETYPE_REGISTRY_FILE.write_text(
            json.dumps(
                {
                    "roles": {
                        "custom-role": {
                            "name": "custom-role",
                            "version": 1,
                            "scope": "pod",
                            "modelClass": "cheap",
                            "soulTemplate": "x",
                            "agentsTemplate": "y",
                            "gateContract": {"kind": "none"},
                            "editRights": "read-only",
                            "toolProfile": "read-only",
                        }
                    }
                }
            )
        )
        assert find_overlay_problems() == []

    def test_malformed_entry_is_named_by_role(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        repoint_docket_home(monkeypatch, home)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.ARCHETYPE_REGISTRY_FILE.write_text(
            json.dumps({"roles": {"broken-role": {"name": "broken-role"}}})
        )
        problems = find_overlay_problems()
        assert len(problems) == 1
        assert problems[0][0] == "broken-role"

    def test_malformed_json_is_reported_by_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        repoint_docket_home(monkeypatch, home)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.ARCHETYPE_REGISTRY_FILE.write_text("{not json")
        problems = find_overlay_problems()
        assert len(problems) == 1
        assert problems[0][0] == str(_cfg.ARCHETYPE_REGISTRY_FILE)


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
                        "editRights": "read-only",
                        "toolProfile": "read-only",
                        "deniedTools": denied_tools,
                    }
                }
            }
        )
    )


class TestPodRoleOverlay:
    """A pod's own role overlay (`pod_config_dir(project)/roles.json`) resolves above
    the global overlay, exercised via `registry_for_role`'s `project` parameter."""

    def test_pod_overlay_wins_over_global_overlay_by_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        repoint_docket_home(monkeypatch, home)
        home.mkdir(parents=True, exist_ok=True)
        _write_vetter_overlay(_cfg.ARCHETYPE_REGISTRY_FILE, [])
        _write_vetter_overlay(_cfg.pod_config_dir("acme") / "roles.json", ["write"])

        narrowed = registry_for_role(builtin_registry(), "vetter", project="acme")

        assert "write" not in narrowed.names()

    def test_no_project_keeps_the_global_overlay_definition(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        repoint_docket_home(monkeypatch, home)
        home.mkdir(parents=True, exist_ok=True)
        _write_vetter_overlay(_cfg.ARCHETYPE_REGISTRY_FILE, [])
        _write_vetter_overlay(_cfg.pod_config_dir("acme") / "roles.json", ["write"])

        narrowed = registry_for_role(builtin_registry(), "vetter", project="")

        assert "write" in narrowed.names()


def _write_lead_meta(project: str, denied_tools: str) -> None:
    path = _cfg.meta_path(_pod_member_id(project, "lead"))
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(
        path,
        {"schemaVersion": 1, "kind": "project", "scope": "project", "deniedTools": denied_tools},
    )


class TestPodDeniedTools:
    """A pod's own `deniedTools` setting unions with a role's own `denied_tools`,
    so a pod-level denial reaches every role in it."""

    def test_pod_denial_removes_a_tool_the_role_itself_allows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        # "implementer" denies nothing by default -- a pod-level "fetch" denial
        # must still remove it, proving this is a union, not just the role's own list.
        _write_lead_meta("acme", "fetch")

        narrowed = registry_for_role(builtin_registry(), "implementer", project="acme")

        assert "fetch" not in narrowed.names()
        assert "write" in narrowed.names()  # nothing else the role allows is touched

    def test_no_project_ignores_the_pod_setting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        _write_lead_meta("acme", "fetch")

        narrowed = registry_for_role(builtin_registry(), "implementer", project="")

        assert "fetch" in narrowed.names()


_SECURITY_VETTER_LONG: dict[str, object] = {
    "name": "security-vetter",
    "scope": "pod",
    "modelClass": "strong",
    "editRights": "read-only",
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


class TestNormalizeRole:
    """The short role form (`kind: role`, `cannot:`, one gate key, `instructions: <file.md>`)
    normalizes into the exact canonical dict `from_wire` already accepts -- see
    specs/functional/role-archetypes.spec.md ("Wire format")."""

    def test_short_form_round_trips_to_the_same_archetype_as_the_long_form(
        self, tmp_path: Path
    ) -> None:
        _write_security_vetter_md(tmp_path)

        normalized = normalize_role(dict(_SECURITY_VETTER_SHORT), tmp_path)

        assert from_wire("security-vetter", normalized) == from_wire(
            "security-vetter", _SECURITY_VETTER_LONG
        )

    def test_verdict_and_verify_together_is_rejected(self, tmp_path: Path) -> None:
        _write_security_vetter_md(tmp_path)
        short = dict(_SECURITY_VETTER_SHORT)
        short["verify"] = True

        with pytest.raises(ArchetypeError):
            normalize_role(short, tmp_path)
