"""``core/archetypes.py``'s pure, non-registry pieces: ``hop_instruction``'s wire
round-trip, ``resolve_hop_instruction``'s gateContract-derived fallback, and that
every built-in/starter role's generated prose agrees with the live runtime contract.
"""

from __future__ import annotations

from docket.core.archetypes import (
    BUILTIN_ARCHETYPES,
    STARTER_ARCHETYPES,
    GateContract,
    RoleArchetype,
    from_wire,
    render,
    resolve_hop_instruction,
)
from docket.core.memory import HEARTBEAT_FILE

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
