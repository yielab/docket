"""The four legacy pod roles must render byte-identical SOUL.md/AGENTS.md
after core/pod.py's role model moved from a hardcoded 4-tuple to the
`core/archetypes.py` registry.

The hard requirement: "Today's four roles ship as built-in archetypes
producing byte-identical workspace output." Rather than diffing the current
`cli/_pod.py` output against itself (which would not catch a regression
introduced by editing both sides together), this file embeds a FROZEN,
independent copy of the original hand-written generators
(`_legacy_member_soul`/`_legacy_member_agents`, copied verbatim from the
pre-archetype `cli/_pod.py` implementation) and compares them against
`cli/_pod.py`'s current archetype-driven `_member_soul`/`_member_agents`
across a range of inputs, for every legacy role.
"""

from __future__ import annotations

import pytest

from docket.cli import _pod
from docket.core import memory as _mem
from docket.core import pod

REQUIRED_STARTUP_FILE = _mem.REQUIRED_STARTUP_FILE


def _legacy_member_soul(
    member: pod.PodMember, project: str, codebase: str, stack: str, description: str
) -> str:
    """Frozen copy of the pre-W-6 `cli/_pod.py::_member_soul` — do not "fix" to
    match a future refactor; this is the byte-identity ground truth."""
    head = (
        f"# SOUL.md — {project} · {member.role}\n\n"
        "## Identity\n"
        f"You are the **{member.role}** of the **{project}** pod (agent id "
        f"`{member.member_id}`).\n\n"
        f"**Session Key:** `{member.session_key}`\n\n"
        "You belong to one project only. Respect the pod session-key boundary — "
        "no cross-project access.\n\n"
        f"## Project\n{description or project}\n\n"
        f"## Codebase\n{codebase or '(no codebase configured)'}\n\n"
        f"## Stack\n{stack}\n\n"
    )
    if member.role == "lead":
        body = (
            "## Role — Lead / Orchestrator\n"
            "- You own the pod's context, memory, and human communication.\n"
            "- Decompose work and dispatch it to the pod's workers "
            "(implementer → reviewer → tester).\n"
            "- **You NEVER edit code, run git, or execute the build.** If you are "
            "about to, STOP and delegate to the implementer.\n"
            "- Surface architectural decisions and risky actions to the human (HITL).\n"
        )
    elif member.role == "implementer":
        body = (
            "## Role — Implementer\n"
            f"- You run **inside** this project's workspace and know {codebase or 'it'} "
            "deeply. Read files before changing them.\n"
            "- You implement the tasks the Lead assigns: read/write/edit the codebase.\n"
            "- Signal completion with `<promise>DONE</promise>`.\n"
            "- Never push to main/master without HITL approval; never delete files "
            "without explicit instruction.\n"
        )
    elif member.role == "reviewer":
        body = (
            "## Role — Reviewer (veto power)\n"
            "- You review diffs for correctness, security, and requirement fit.\n"
            "- **Read-only**: no write/edit/exec. Bad code does not proceed.\n"
            "- **Marker convention:** the first non-blank line of your reply must be "
            "exactly `APPROVE` or `REQUEST-CHANGES` (case-insensitive) — dispatch "
            "parses this line to gate the pipeline. Reasons go on the lines after "
            "it. Anything else on that first line is treated as unparseable and "
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
            "- **Marker convention:** the first non-blank line of your reply must be "
            "exactly `PASS` or `FAIL` (case-insensitive) — dispatch parses this line "
            "to gate the pipeline. Evidence goes on the lines after it. Anything else "
            "on that first line blocks the pipeline the same as a FAIL.\n"
        )
    return head + body


def _legacy_member_agents(member: pod.PodMember, project: str) -> str:
    """Frozen copy of the pre-W-6 `cli/_pod.py::_member_agents`."""
    return (
        f"# AGENTS.md — {project} · {member.role}\n\n"
        "## Session Startup\n"
        "_Lean — re-sent every turn._\n"
        f"1. Read {REQUIRED_STARTUP_FILE} — startup protocol + your codebase\n"
        "   path (the runtime requires this after every context reset).\n"
        "2. Read HEARTBEAT.md — active tasks/decisions (small; always). Unchecked\n"
        "   items mean you were interrupted mid-task: resume them, don't greet idle.\n"
        "3. Read memory/YYYY-MM-DD.md only when the task needs prior context;\n"
        "   don't slurp the whole memory/ dir — what you read is re-sent every\n"
        "   later turn.\n\n"
        "## Red Lines\n"
        f"- Stay within the `{project}` pod; coordinate only within it (the Lead\n"
        "  routes work between members). No cross-project access.\n"
        "- Never push to main/master or delete files without HITL approval.\n"
        "- Before starting multi-step work, write it to HEARTBEAT.md — an unwritten\n"
        "  task does not survive a context reset.\n"
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
        actual = _pod._member_soul(
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
        actual = _pod._member_agents(member, case["project"])
        assert actual == expected

    def test_duplicate_index_member_id_unaffected(self) -> None:
        """A second Implementer (`demo-implementer-2`) renders the same as the first,
        modulo its own member id/role text — index doesn't leak into prose."""
        member = pod.PodMember(
            project="demo",
            role="implementer",
            index=2,
            member_id="demo-implementer-2",
            model="anthropic/claude-sonnet-4-6",
            session_key="agent:demo:default",
        )
        expected = _legacy_member_soul(member, "demo", "/src/demo", "Python", "")
        actual = _pod._member_soul(member, "demo", "/src/demo", "Python", "")
        assert actual == expected
        assert "demo-implementer-2" in actual
