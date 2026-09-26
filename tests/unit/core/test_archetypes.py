"""``core/archetypes.py``'s pure, non-registry pieces: ``hop_instruction``'s wire
round-trip and ``resolve_hop_instruction``'s gateContract-derived fallback. See
specs/functional/role-archetypes.spec.md ("Hop instructions").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core.archetypes import (
    GateContract,
    RoleArchetype,
    find_overlay_problems,
    from_wire,
    resolve_hop_instruction,
)

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
        edit_rights="read-only",
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
