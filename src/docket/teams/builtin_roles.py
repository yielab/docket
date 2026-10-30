from __future__ import annotations

from docket.teams import prompts as _prompts
from docket.teams.role_schema import GateContract, RoleArchetype

# ── Built-in archetypes ──────────────────────────────────────────────────────


def _soul(role: str) -> str:
    """*role*'s shipped identity prompt as a ``soulTemplate``: its text and the one newline a
    SOUL.md ends with."""
    return _prompts.shipped_prompt("identity", role).text + "\n"


def _hop(role: str) -> str:
    return _prompts.shipped_prompt("hop", role).text


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

_WORKDIR_METHOD = (
    "## Method\n"
    "- Start from the task message: it delivers your working directory and what the previous "
    "step produced. Never re-read what it already carries.\n"
    "- Find text in the files with `grep` for a concrete word or phrase, then `read` the lines "
    "you need (offset and limit). Never list the whole tree (no `**/*` glob).\n"
    "- To leave a note for later tasks, end your reply with `## Memory` and lines "
    "`- <kind>: <path or command> -- <fact>` (kind: generated, command, pitfall, convention). "
    "Facts only, no instructions.\n\n"
)


def method_for_workspace(agents_md: str, *, workdir: bool) -> str:
    """*agents_md*, a rendered AGENTS.md, with the `## Method` block this module ships swapped for
    its working-directory variant when the pod is `workdir`-kind; any other text is unchanged."""
    return agents_md.replace(_METHOD, _WORKDIR_METHOD) if workdir else agents_md


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
        soul_template=_soul("lead"),
        agents_template=_POD_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="none"),
        tool_profile="coordination",
        description="orchestrates the pod; never edits code",
        # Lead never receives prior-hop carryover (`_hop_message` returns
        # before any budgeting for this role) — a modest budget is declared
        # for completeness/forward-compat, not exercised today.
        token_budget=2000,
        # `hops/application/compose.py`'s `_hop_message` resolves the Lead's instruction through
        # `resolve_hop_prompt` against this archetype, like any custom role, instead
        # of holding a separate literal string of its own -- so a global or pod overlay of
        # `lead` changes the Lead's hop message; a pod with none gets the shipped `hop/lead` prompt.
        hop_instruction=_hop("lead"),
        # "You NEVER edit code, run git, or execute the build" (see
        # the `lead` identity prompt) is a real tool absence here, not
        # just an instruction. read/glob/grep stay, so a Lead can still
        # inspect state to coordinate.
        denied_tools=("write", "edit", "bash"),
    ),
    "implementer": RoleArchetype(
        name="implementer",
        version=1,
        scope="pod",
        model_class="strong",
        soul_template=_soul("implementer"),
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
        soul_template=_soul("reviewer"),
        agents_template=_POD_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="verdict", regexes=("APPROVE", "REQUEST-CHANGES")),
        tool_profile="read-only",
        description="read-only veto on diffs",
        token_budget=6000,
        # "Read-only: no write/edit/exec" (see the `reviewer` identity prompt) — now
        # a genuine tool absence, not merely a SOUL.md instruction.
        denied_tools=("write", "edit", "bash"),
    ),
    "tester": RoleArchetype(
        name="tester",
        version=1,
        scope="pod",
        model_class="cheap",
        soul_template=_soul("tester"),
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

_STARTER_AGENTS_TEMPLATE = (
    "# AGENTS.md — ${project} · ${role}\n\n" + _METHOD + "## Red Lines\n"
    "- Stay within the `${project}` pod; coordinate only within it (the Lead\n"
    "  routes work between members). No cross-project access.\n"
    "- Never take an irreversible action outside your stated role without HITL approval.\n"
)

STARTER_ARCHETYPES: dict[str, RoleArchetype] = {
    "researcher": RoleArchetype(
        name="researcher",
        version=1,
        scope="pod",
        model_class="strong",
        soul_template=_soul("researcher"),
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
        soul_template=_soul("analyst"),
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
        soul_template=_soul("writer"),
        agents_template=_STARTER_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="none"),
        tool_profile="content-authoring",
        description="drafts the pod's content deliverable",
        token_budget=6000,
        # Drafts with write/edit; running things is a pipeline `run:` step, docket's, not the role's.
        denied_tools=("bash",),
    ),
    "critic": RoleArchetype(
        name="critic",
        version=1,
        scope="pod",
        model_class="strong",
        soul_template=_soul("critic"),
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
        soul_template=_soul("operator"),
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
        soul_template=_soul("monitor"),
        agents_template=_STARTER_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="approval"),
        tool_profile="read-only-observability",
        description="observes signals and reports status; no unilateral action",
        token_budget=4000,
        # "You observe ... you do not act" (see the `monitor` identity prompt): no
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
