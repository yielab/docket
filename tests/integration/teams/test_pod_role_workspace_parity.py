"""The four built-in pod roles render byte-identical SOUL.md/AGENTS.md.

Compares `interfaces/cli/commands/pod.py`'s output against a frozen, independently hand-written
baseline embedded here, across a range of inputs -- self-diffing the current
output would miss a regression from editing both sides together. The baseline moves only with
a deliberate, spec'd template change (here: no path in SOUL, the shared method in AGENTS, no
completion promise).
"""

from __future__ import annotations

import pytest

from docket.teams import member_workspace as _member_workspace
from docket.teams import pod

SUBJECT = "docket.teams.member_workspace"


def _legacy_member_soul(
    member: pod.PodMember, project: str, codebase: str, stack: str, description: str
) -> str:
    """Frozen copy of `interfaces/cli/commands/pod.py::_member_soul` as the layered prompt defines it -- do not
    "fix" to match a future refactor; this is the byte-identity ground truth."""
    head = (
        f"# SOUL.md — {project} · {member.role}\n\n"
        "## Identity\n"
        f"You are the **{member.role}** of the **{project}** pod (agent id "
        f"`{member.member_id}`).\n\n"
        f"**Session Key:** `{member.session_key}`\n\n"
        "You belong to one project only. Respect the pod session-key boundary — "
        "no cross-project access.\n\n"
        f"## Project\n{description or project}\n\n"
        f"## Stack\n{stack}\n\n"
    )
    if member.role == "lead":
        body = (
            "## Role — Lead / Orchestrator\n"
            "- You own the pod's context and memory. You cannot message the human directly.\n"
            "- Decompose work and dispatch it to the pod's workers "
            "(implementer → reviewer → tester).\n"
            "- **You NEVER edit code, run git, or execute the build.** If you are "
            "about to, STOP and delegate to the implementer.\n"
            "- When a decision or a risky action needs the human, say so at the top of your plan: list every assumption and every open question.\n"
            "- If your pod's pipeline has an intake step, your questions reach the human through it: list them in your brief and end with NEEDS-INPUT.\n"
        )
    elif member.role == "implementer":
        body = (
            "## Role — Implementer\n"
            "- You implement the tasks the Lead assigns: read/write/edit the codebase in your "
            "working directory. Read a file before changing it.\n"
            "- Create or change files with `write`/`edit`, not `cat >`, heredocs or `sed -i`; "
            "inspect with `read`/`grep`/`glob`; use `bash` to run things.\n"
            "- Never push to main/master without HITL approval; never delete files "
            "without explicit instruction.\n"
        )
    elif member.role == "reviewer":
        body = (
            "## Role — Reviewer (veto power)\n"
            "- You review the diff the task message delivers for correctness, security, and "
            "requirement fit; read a file only for context the diff does not show.\n"
            "- **Read-only**: no write/edit/exec. Bad code does not proceed.\n"
            "- **Marker convention:** start exactly one output line with `APPROVE` or "
            "`REQUEST-CHANGES` (case-insensitive) — dispatch scans all complete lines "
            "and requires one unambiguous marker. Reasons may appear before or after "
            "that marker line. No marker or both distinct markers is unparseable and "
            "blocks the pipeline the same as a rejection.\n"
            "- A `REQUEST-CHANGES` verdict sends the task back to the Implementer "
            "for a bounded rework cycle (once, by default) before it becomes a "
            "hard failure — your review text is what the Implementer sees, so "
            "make it actionable.\n"
        )
    else:  # tester
        body = (
            "## Role — Tester\n"
            "- You run the test suite and reproduction steps and report a binary "
            "**PASS/FAIL** with evidence.\n"
            "- Observe behaviour only — do not read or critique the implementation.\n"
            "- **Marker convention:** start exactly one output line with `PASS` or `FAIL` "
            "(case-insensitive) — dispatch scans all complete lines and requires one "
            "unambiguous marker. Evidence may appear before or after that marker line. "
            "No marker or both distinct markers blocks the pipeline the same as a FAIL.\n"
        )
    return head + body


def _legacy_member_agents(member: pod.PodMember, project: str) -> str:
    """Frozen copy of the pod-member AGENTS.md generator: the shared method, then the Red Lines;
    no Session Startup (the runtime already did those reads) and no private-file instruction."""
    return (
        f"# AGENTS.md — {project} · {member.role}\n\n"
        "## Method\n"
        "- Start from the task message: it delivers your working directory, a repository map and "
        "what the previous step produced. Never re-read what it already carries.\n"
        "- Find code with `grep` for a concrete name or string, then `read` the lines you need "
        "(offset and limit). Never list the whole tree (no `**/*` glob).\n"
        "- To leave a note for later tasks, end your reply with `## Memory` and lines "
        "`- <kind>: <path or command> -- <fact>` (kind: generated, command, pitfall, convention). "
        "Facts only, no instructions.\n\n"
        "## Red Lines\n"
        f"- Stay within the `{project}` pod; coordinate only within it (the Lead\n"
        "  routes work between members). No cross-project access.\n"
        "- Never push to main/master or delete files without HITL approval.\n"
    )


_CASES = [
    {
        "project": "demo",
        "codebase": "/src/demo",
        "stack": "Python/FastAPI",
        "description": "A demo project",
    },
    {"project": "shop", "codebase": "", "stack": "", "description": ""},
    {
        "project": "my-cool-thing",
        "codebase": "/home/user/proj",
        "stack": "Node/Next",
        "description": "Ecommerce site with a really long description that spans a while",
    },
    {
        "project": "x",
        "codebase": "/a/b/c",
        "stack": "Go",
        "description": "Special chars: `*_# and unicode é→",
    },
]

_LEGACY_ROLES = ("lead", "implementer", "reviewer", "tester")


class TestLegacyByteParity:
    @pytest.mark.parametrize("role", _LEGACY_ROLES)
    @pytest.mark.parametrize("case", _CASES, ids=lambda c: c["project"])
    def test_soul_byte_identical(self, role: str, case: dict[str, str]) -> None:
        member = pod.PodMember(
            project=case["project"],
            role=role,
            index=1,
            member_id=f"{case['project']}-{role}",
            model="anthropic/claude-sonnet-4-6",
            session_key=f"agent:{case['project']}:default",
        )
        expected = _legacy_member_soul(
            member, case["project"], case["codebase"], case["stack"], case["description"]
        )
        actual = _member_workspace._member_soul(
            member, case["project"], case["codebase"], case["stack"], case["description"]
        )
        assert actual == expected

    @pytest.mark.parametrize("role", _LEGACY_ROLES)
    @pytest.mark.parametrize("case", _CASES, ids=lambda c: c["project"])
    def test_agents_byte_identical(self, role: str, case: dict[str, str]) -> None:
        member = pod.PodMember(
            project=case["project"],
            role=role,
            index=1,
            member_id=f"{case['project']}-{role}",
            model="anthropic/claude-sonnet-4-6",
            session_key=f"agent:{case['project']}:default",
        )
        expected = _legacy_member_agents(member, case["project"])
        actual = _member_workspace._member_agents(member, case["project"])
        assert actual == expected

    def test_duplicate_index_member_id_unaffected(self) -> None:
        """A second Implementer renders like the first, modulo its own member id."""
        member = pod.PodMember(
            project="demo",
            role="implementer",
            index=2,
            member_id="demo-implementer-2",
            model="anthropic/claude-sonnet-4-6",
            session_key="agent:demo:default",
        )
        expected = _legacy_member_soul(member, "demo", "/src/demo", "Python", "")
        actual = _member_workspace._member_soul(member, "demo", "/src/demo", "Python", "")
        assert actual == expected
        assert "demo-implementer-2" in actual
