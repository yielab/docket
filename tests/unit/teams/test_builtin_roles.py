"""``teams/roles.py``'s pure, non-registry pieces: ``hop_instruction``'s wire
round-trip, ``resolve_hop_instruction``'s gateContract-derived fallback, and that
every built-in/starter role's generated prose agrees with the live runtime contract.
"""

from __future__ import annotations

import pytest

from docket.teams.builtin_roles import BUILTIN_ARCHETYPES, STARTER_ARCHETYPES
from docket.teams.role_schema import (
    render,
)

SUBJECT = "docket.teams.builtin_roles"


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


class TestRolesThatWritePreferTheFileTools:
    """The implementer and the writer are told to change files with write/edit, not bash."""

    @pytest.mark.parametrize("name", ["implementer", "writer"])
    def test_rendered_soul_prefers_write_and_edit_over_bash(self, name: str) -> None:
        arch = {**BUILTIN_ARCHETYPES, **STARTER_ARCHETYPES}[name]
        soul = render(arch.soul_template, {**_SAMPLE_VARIABLES, "role": name})

        assert "`write`/`edit`" in soul
        assert "heredocs" in soul
        assert "`read`/`grep`/`glob`" in soul


class TestTheLeadHasOneEscalationChannel:
    """The Lead's SOUL points at `consult` alone and does not deny the human is reachable."""

    def test_rendered_soul_names_consult_and_no_second_channel(self) -> None:
        soul = render(BUILTIN_ARCHETYPES["lead"].soul_template, _SAMPLE_VARIABLES)

        assert "`consult`" in soul
        assert "list every assumption" in soul
        assert "cannot message the human" not in soul
        assert "NEEDS-INPUT" not in soul
