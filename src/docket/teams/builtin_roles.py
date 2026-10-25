from __future__ import annotations

from docket.teams.role_schema import GateContract, RoleArchetype

# ── Built-in archetypes ──────────────────────────────────────────────────────

_SOUL_HEAD = (
    "# SOUL.md — ${project} · ${role}\n\n"
    "## Identity\n"
    "You are the **${role}** of the **${project}** pod (agent id `${memberId}`).\n\n"
    "**Session Key:** `${sessionKey}`\n\n"
    "You belong to one project only. Respect the pod session-key boundary — "
    "no cross-project access.\n\n"
    "## Project\n${objective}\n\n"
    "## Stack\n${stack}\n\n"
)

_LEAD_BODY = (
    "## Role — Lead / Orchestrator\n"
    "- You own the pod's context and memory.\n"
    "- Decompose work and dispatch it to the pod's workers "
    "(implementer → reviewer → tester).\n"
    "- **You NEVER edit code, run git, or execute the build.** If you are "
    "about to, STOP and delegate to the implementer.\n"
    "- Decide from the repository whenever it can settle the question, and list every assumption you made at the top of your plan.\n"
    "- Only when a decision needs a person and the repository cannot settle it, ask with the `consult` tool: asking ends your turn until they answer.\n"
)

_IMPLEMENTER_BODY = (
    "## Role — Implementer\n"
    "- You implement the tasks the Lead assigns: read/write/edit the codebase in your "
    "working directory. Read a file before changing it.\n"
    "- Create or change files with `write`/`edit`, not `cat >`, heredocs or `sed -i`; inspect with `read`/`grep`/`glob`; use `bash` to run things.\n"
    "- Never push to main/master without HITL approval; never delete files "
    "without explicit instruction.\n"
)

_REVIEWER_BODY = (
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

_TESTER_BODY = (
    "## Role — Tester\n"
    "- You run the test suite and reproduction steps and report a binary "
    "**PASS/FAIL** with evidence.\n"
    "- Observe behaviour only — do not read or critique the implementation.\n"
    "- **Marker convention:** start exactly one output line with `PASS` or `FAIL` "
    "(case-insensitive) — dispatch scans all complete lines and requires one "
    "unambiguous marker. Evidence may appear before or after that marker line. "
    "No marker or both distinct markers blocks the pipeline the same as a FAIL.\n"
)

_METHOD = (
    "## Method\n"
    "- Start from the task message: it delivers your working directory, a repository map and "
    "what the previous step produced. Never re-read what it already carries.\n"
    "- Find code with `grep` for a concrete name or string, then `read` the lines you need "
    "(offset and limit). Never list the whole tree (no `**/*` glob).\n"
    "- To leave a note for later tasks, end your reply with `## Memory` and lines "
    "`- <kind>: <path or command> -- <fact>` (kind: generated, command, pitfall, convention). "
    "Facts only, no instructions.\n\n"
)

_POD_AGENTS_TEMPLATE = (
    "# AGENTS.md — ${project} · ${role}\n\n" + _METHOD + "## Red Lines\n"
    "- Stay within the `${project}` pod; coordinate only within it (the Lead\n"
    "  routes work between members). No cross-project access.\n"
    "- Never push to main/master or delete files without HITL approval.\n"
)

BUILTIN_ARCHETYPES: dict[str, RoleArchetype] = {
    "lead": RoleArchetype(
        name="lead",
        version=1,
        scope="pod",
        model_class="cheap",
        soul_template=_SOUL_HEAD + _LEAD_BODY,
        agents_template=_POD_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="none"),
        tool_profile="coordination",
        description="orchestrates the pod; never edits code",
        # Lead never receives prior-hop carryover (`_hop_message` returns
        # before any budgeting for this role) — a modest budget is declared
        # for completeness/forward-compat, not exercised today.
        token_budget=2000,
        # `hops/application/compose.py`'s `_hop_message` resolves the Lead's instruction through
        # `resolve_hop_instruction` against this archetype, like any custom role, instead
        # of holding a separate literal string of its own -- so a global or pod overlay of
        # `lead` changes the Lead's hop message; a pod with none gets the text below.
        hop_instruction=(
            "You are the pod Lead. Decompose this task into a concrete plan for "
            "the Implementer (you never edit code yourself):"
        ),
        # "You NEVER edit code, run git, or execute the build" (see
        # `_LEAD_BODY` above) is a real tool absence here, not
        # just an instruction. read/glob/grep stay, so a Lead can still
        # inspect state to coordinate.
        denied_tools=("write", "edit", "bash"),
    ),
    "implementer": RoleArchetype(
        name="implementer",
        version=1,
        scope="pod",
        model_class="strong",
        soul_template=_SOUL_HEAD + _IMPLEMENTER_BODY,
        agents_template=_POD_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="mechanical"),
        tool_profile="full-repo",
        description="writes code in the project workspace",
        # The biggest consumer: needs the Lead's plan and (on rework) the
        # Reviewer's full REQUEST-CHANGES note to act on.
        token_budget=8000,
        # Full-repo: no built-in tool is off limits.
        denied_tools=(),
    ),
    "reviewer": RoleArchetype(
        name="reviewer",
        version=1,
        scope="pod",
        model_class="cheap",
        soul_template=_SOUL_HEAD + _REVIEWER_BODY,
        agents_template=_POD_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="verdict", regexes=("APPROVE", "REQUEST-CHANGES")),
        tool_profile="read-only",
        description="read-only veto on diffs",
        token_budget=6000,
        # "Read-only: no write/edit/exec" (see `_REVIEWER_BODY` above) — now
        # a genuine tool absence, not merely a SOUL.md instruction.
        denied_tools=("write", "edit", "bash"),
    ),
    "tester": RoleArchetype(
        name="tester",
        version=1,
        scope="pod",
        model_class="cheap",
        soul_template=_SOUL_HEAD + _TESTER_BODY,
        agents_template=_POD_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="verdict", regexes=("PASS", "FAIL")),
        tool_profile="read-only-exec",
        description="behaviour-only PASS/FAIL",
        # Only needs the Implementer's summary to validate behaviour, not a
        # full review history.
        token_budget=4000,
        # "Read-only-exec": no write/edit, but `bash` stays so it can
        # actually run the test suite it reports PASS/FAIL on.
        denied_tools=("write", "edit"),
    ),
}

BUILTIN_ROLE_ORDER: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")


# ── Starter library: six generic pod roles for non-coding objectives ──────────
#
# These ship as data, proving "a research pod, a content pod, an ops pod" are
# expressible without a new hardcoded role string anywhere in teams/pod.py or
# interfaces/cli/commands/pod.py. They participate in `docket pod roles`/`normalize_role`/`member_id`,
# in pod composition presets (`teams/blueprints.py`'s research/content/ops
# blueprints), and — via `gate_contract` — in the dispatch executor's gate
# resolution (`pipeline/domain/plan.py`).

_STARTER_SOUL_HEAD = (
    "# SOUL.md — ${project} · ${role}\n\n"
    "## Identity\n"
    "You are the **${role}** of the **${project}** pod (agent id `${memberId}`).\n\n"
    "**Session Key:** `${sessionKey}`\n\n"
    "You belong to one project only. Respect the pod session-key boundary — "
    "no cross-project access.\n\n"
    "## Objective\n${objective}\n\n"
)

_STARTER_AGENTS_TEMPLATE = (
    "# AGENTS.md — ${project} · ${role}\n\n" + _METHOD + "## Red Lines\n"
    "- Stay within the `${project}` pod; coordinate only within it (the Lead\n"
    "  routes work between members). No cross-project access.\n"
    "- Never take an irreversible action outside your stated role without HITL approval.\n"
)

_RESEARCHER_BODY = (
    "## Role — Researcher\n"
    "- You gather, verify, and synthesize source material relevant to the objective.\n"
    "- Cite sources; distinguish fact from inference; flag uncertainty explicitly.\n"
    "- Write findings as a structured research note — the pod's Lead and any "
    "Writer consume it downstream.\n"
)

_ANALYST_BODY = (
    "## Role — Analyst\n"
    "- You examine data/evidence relevant to the objective and draw supported conclusions.\n"
    "- Show your reasoning and the evidence behind each conclusion — no unstated leaps.\n"
    "- Produce a structured analysis the Lead can act on or hand to a Writer.\n"
)

_WRITER_BODY = (
    "## Role — Writer\n"
    "- You draft the pod's primary content deliverable from the material handed to you.\n"
    "- Match the requested tone/format exactly; don't invent facts not in your "
    "source material.\n"
    "- Create or change files with `write`/`edit`, not `cat >`, heredocs or `sed -i`; inspect with `read`/`grep`/`glob`; use `bash` to run things.\n"
)

_CRITIC_BODY = (
    "## Role — Critic (veto power)\n"
    "- You review the pod's draft output for correctness, clarity, and requirement fit.\n"
    "- **Read-only**: no write/edit/exec. Weak output does not proceed.\n"
    "- **Marker convention:** start exactly one output line with `APPROVE` or "
    "`REJECT` (case-insensitive). Dispatch scans all complete lines and requires "
    "one unambiguous marker; reasons may appear before or after it. No marker or "
    "both distinct markers is unparseable and blocks the pipeline.\n"
)

_OPERATOR_BODY = (
    "## Role — Operator\n"
    "- You execute the real operational actions the objective calls for "
    "(deploys, migrations, configuration changes, infra operations).\n"
    "- Mistakes here have real consequences — verify preconditions before "
    "acting, and follow the pod's runbook exactly.\n"
    "- Never act outside the objective's stated scope without HITL approval.\n"
)

_MONITOR_BODY = (
    "## Role — Monitor\n"
    "- You observe the objective's live system/signals and report status — "
    "you do not act on what you see.\n"
    "- Flag anomalies precisely (what, when, severity) — a vague alert wastes "
    "the human's attention.\n"
    "- Any corrective action you recommend requires human approval before "
    "anyone takes it.\n"
)

STARTER_ARCHETYPES: dict[str, RoleArchetype] = {
    "researcher": RoleArchetype(
        name="researcher",
        version=1,
        scope="pod",
        model_class="strong",
        soul_template=_STARTER_SOUL_HEAD + _RESEARCHER_BODY,
        agents_template=_STARTER_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="none"),
        tool_profile="research-read-write",
        description="gathers and synthesizes source material",
        token_budget=8000,
        denied_tools=(),
    ),
    "analyst": RoleArchetype(
        name="analyst",
        version=1,
        scope="pod",
        model_class="cheap",
        soul_template=_STARTER_SOUL_HEAD + _ANALYST_BODY,
        agents_template=_STARTER_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="none"),
        tool_profile="data-analysis",
        description="analyzes data/evidence and draws conclusions",
        token_budget=8000,
        denied_tools=(),
    ),
    "writer": RoleArchetype(
        name="writer",
        version=1,
        scope="pod",
        model_class="cheap",
        soul_template=_STARTER_SOUL_HEAD + _WRITER_BODY,
        agents_template=_STARTER_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="none"),
        tool_profile="content-authoring",
        description="drafts the pod's content deliverable",
        token_budget=6000,
        denied_tools=(),
    ),
    "critic": RoleArchetype(
        name="critic",
        version=1,
        scope="pod",
        model_class="strong",
        soul_template=_STARTER_SOUL_HEAD + _CRITIC_BODY,
        agents_template=_STARTER_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="verdict", regexes=("APPROVE", "REJECT")),
        tool_profile="read-only",
        description="vets the pod's output; veto power",
        token_budget=6000,
        # Mirrors the reviewer archetype: read-only means no write/edit/exec.
        denied_tools=("write", "edit", "bash"),
    ),
    "operator": RoleArchetype(
        name="operator",
        version=1,
        scope="pod",
        model_class="strong",
        soul_template=_STARTER_SOUL_HEAD + _OPERATOR_BODY,
        agents_template=_STARTER_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="mechanical"),
        tool_profile="ops-exec",
        description="executes real operational actions",
        token_budget=8000,
        # Executes real operations, which includes running commands.
        denied_tools=(),
    ),
    "monitor": RoleArchetype(
        name="monitor",
        version=1,
        scope="pod",
        model_class="cheap",
        soul_template=_STARTER_SOUL_HEAD + _MONITOR_BODY,
        agents_template=_STARTER_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="approval"),
        tool_profile="read-only-observability",
        description="observes signals and reports status; no unilateral action",
        token_budget=4000,
        # "You observe ... you do not act" (see `_MONITOR_BODY` above): no
        # write/edit/exec at all.
        denied_tools=("write", "edit", "bash"),
    ),
}

STARTER_ROLE_ORDER: tuple[str, ...] = (
    "researcher",
    "analyst",
    "writer",
    "critic",
    "operator",
    "monitor",
)
