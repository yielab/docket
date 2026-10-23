"""``teams/roles.py``'s pure, non-registry pieces: ``hop_instruction``'s wire
round-trip, ``resolve_hop_instruction``'s gateContract-derived fallback, and that
every built-in/starter role's generated prose agrees with the live runtime contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.pods import write_security_vetter_md as _write_security_vetter_md

from docket.agent.memory import HEARTBEAT_FILE
from docket.teams.builtin_roles import BUILTIN_ARCHETYPES, STARTER_ARCHETYPES
from docket.teams.role_schema import (
    ArchetypeError,
    GateContract,
    RoleArchetype,
    from_wire,
    render,
    resolve_hop_instruction,
)
from docket.teams.roles import normalize_role

SUBJECT = "docket.teams.role_schema"


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
    `agent/identity.py`'s live runtime contract, composed into the same turn."""

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


class TestTemplatesCarryNoPathAndNoDeadSignals:
    """The layered prompt: templates name no path, no private file and no completion promise,
    and every AGENTS template carries the one shared method block."""

    @staticmethod
    def _rendered() -> dict[str, tuple[str, str]]:
        out: dict[str, tuple[str, str]] = {}
        for name, arch in {**BUILTIN_ARCHETYPES, **STARTER_ARCHETYPES}.items():
            variables = {
                **_SAMPLE_VARIABLES,
                "role": name,
                "memberId": f"demo-{name}",
                "codebaseOrConfigured": "/srv/sample-codebase",
                "codebaseOrIt": "/srv/sample-codebase",
                "workDir": "/srv/sample-workdir",
            }
            out[name] = (
                render(arch.soul_template, variables),
                render(arch.agents_template, variables),
            )
        return out

    def test_no_template_names_a_private_file_a_promise_or_a_path(self) -> None:
        offenders = {
            name: word
            for name, texts in self._rendered().items()
            for text in texts
            for word in ("HEARTBEAT", "memory/", "promise", "/srv/", "/tmp/")
            if word in text
        }
        assert offenders == {}

    def test_every_agents_template_carries_the_shared_method(self) -> None:
        for name, (_soul, agents) in self._rendered().items():
            assert "## Method" in agents, name
            assert "grep" in agents and "never list the whole tree" in agents.lower(), name

    def test_the_method_block_names_the_memory_section_grammar(self) -> None:
        for name, (_soul, agents) in self._rendered().items():
            assert "`## Memory`" in agents, name
            assert "- <kind>: <path or command> -- <fact>" in agents, name

    def test_the_method_block_is_short(self) -> None:
        agents = self._rendered()["implementer"][1]
        method = agents.split("## Method", 1)[1].split("## Red Lines", 1)[0]
        assert len(method) < 520


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


class TestPolicyRoleRefused:
    def test_a_canonical_document_with_policy_role_is_refused_naming_the_key(self) -> None:
        doc = {
            "name": "scribe",
            "scope": "pod",
            "modelClass": "cheap",
            "soulTemplate": "s",
            "agentsTemplate": "a",
            "policyRole": "manager",
        }
        with pytest.raises(ArchetypeError, match="policyRole"):
            from_wire("scribe", doc)

    def test_a_short_form_file_with_policy_role_is_refused_naming_the_key(
        self, tmp_path: Path
    ) -> None:
        from docket.teams import roles as _arch

        (tmp_path / "scribe.md").write_text("You are a scribe.\n", encoding="utf-8")
        path = tmp_path / "scribe.yaml"
        path.write_text(
            json.dumps({"kind": "role", "name": "scribe", "model": "cheap", "policyRole": "x"}),
            encoding="utf-8",
        )
        with pytest.raises(ArchetypeError, match="policyRole"):
            _arch.load_role_file(str(path))


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
