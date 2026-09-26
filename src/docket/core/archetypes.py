"""Role archetypes: versioned, declarative role definitions.

A role archetype is data, not code: name, scope, model class, SOUL/AGENTS prose
templates, a gate contract, edit rights, a tool profile, and an enforced tool
denylist. `core/pod.py` resolves pod roles against this registry instead of a
hardcoded 4-tuple, so a new role is data, never a hardcoded string in
`core/pod.py`/`cli/_pod.py`.

`tool_profile` is prose -- descriptive, never enforced (a real gap: a Reviewer
was once *told* "read-only" in SOUL.md but handed the full tool registry
anyway). `denied_tools` closes that gap as data: built-in tool names a role
may never call. `registry_for_role` is the sole consumer -- it removes exactly
those names via `ToolRegistry.without()`, called once per turn by
`core/agent_loop.py` before advertising tools or dispatching a call. No caller
ever branches on a role's name.

Built-in archetypes (`BUILTIN_ARCHETYPES`) reproduce today's four pod roles --
lead, implementer, reviewer, tester (golden-tested; see
`tests/integration/test_archetypes.py`). `STARTER_ARCHETYPES` ships six more:
researcher, analyst, writer, critic, operator, monitor.

`model_class` (cheap|strong) slots into the existing role->model policy
(`core/models_policy.py`) rather than replacing it: the four legacy archetypes
carry a `policy_role` override so their model resolves exactly as before (same
named policy row, same `docket models set <role>` behavior); an archetype with
no override resolves through its own `model_class` against the live rank
anchors instead.

`token_budget` is the role's context-compiler budget -- how many approximate
tokens of prior-hop carryover `core/context.py` may thread into that role's
hop prompt. It lives on the archetype, not a second registry, so identity and
resource budget cannot drift apart; defaults to 6000 when unset.

User archetypes overlay built-ins via `~/.docket/docket-roles.json` (same
pattern as `docket-models.json`), tolerant on load (a malformed entry is
skipped, never crashes a live fleet; `docket roles validate` explains why).
The authoring format is a standalone YAML file (`docket roles add
<file.yaml>`), merged into the JSON overlay. Built-in/starter archetypes stay
Python literals here, matching the project's convention of generating
workspace prose inline rather than loading shipped template files.

See specs/functional/role-archetypes.spec.md for the full schema (closed vs.
open fields), the built-in/starter tables, and the user-overlay contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from string import Template
from typing import Any

import docket.config as cfg
from docket.core import memory as _mem
from docket.core.tools import ToolKind, ToolRegistry
from docket.edges import store as _store

SCOPES: frozenset[str] = frozenset({"org", "pod"})
MODEL_CLASSES: frozenset[str] = frozenset({"cheap", "strong"})
EDIT_RIGHTS: frozenset[str] = frozenset({"none", "read-only", "write"})
GATE_KINDS: frozenset[str] = frozenset({"none", "verdict", "mechanical", "approval"})

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class ArchetypeError(ValueError):
    """Invalid archetype definition, reference, or template."""


@dataclass(frozen=True)
class GateContract:
    """Closed typed union over the four gate-contract kinds; `regexes` applies only to
    `kind == "verdict"` (e.g. reviewer APPROVE/REQUEST-CHANGES, tester PASS/FAIL). Real,
    consumed data: `core.orchestrator.resolve_gate` falls back to it when a step omits its own."""

    kind: str
    regexes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in GATE_KINDS:
            raise ArchetypeError(
                f"unknown gate contract kind {self.kind!r}; valid: {sorted(GATE_KINDS)}"
            )
        for pattern in self.regexes:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ArchetypeError(
                    f"gate contract regex {pattern!r} does not compile: {exc}"
                ) from exc

    def to_wire(self) -> dict[str, Any]:
        doc: dict[str, Any] = {"kind": self.kind}
        if self.regexes:
            doc["regexes"] = list(self.regexes)
        return doc


@dataclass(frozen=True)
class RoleArchetype:
    """A versioned, declarative role definition. Field names below are Python
    (snake_case); the wire/YAML format uses camelCase (`modelClass`, `soulTemplate`,
    `agentsTemplate`, `gateContract`, `editRights`, `toolProfile`) — see `from_wire`/`to_wire`."""

    name: str
    version: int
    scope: str  # closed: "org" | "pod"
    model_class: str  # closed: "cheap" | "strong"
    soul_template: str  # open prose; $-style variables, see `render`
    agents_template: str  # open prose; $-style variables, see `render`
    gate_contract: GateContract  # closed kind, see GateContract
    edit_rights: str  # closed: "none" | "read-only" | "write"
    tool_profile: str  # open prose (not enforced; descriptive only)
    # "" = policy role name == this archetype's own name (the extensible case).
    # Non-empty only for the four legacy archetypes, preserving their existing
    # named row in core/models_policy.py's ALL_ROLES/ROLE_CLASS untouched.
    policy_role: str = ""
    description: str = ""  # open one-line prose, shown by `docket roles list/show`
    # This role's context-compiler token budget — see
    # the module docstring's "token_budget" paragraph and `core/context.py`.
    token_budget: int = 6000
    # Built-in tool names this role may never call —
    # see the module docstring's "Per-role tool sets" section. Open (like
    # `tool_profile`), not validated against the live tool registry: a name
    # that does not exist in a given registry is simply a no-op removal for
    # `ToolRegistry.without()`. Empty (the default) means "no narrower than
    # whatever registry the caller hands in" — today's behavior, preserved
    # for any archetype that does not opt in.
    denied_tools: tuple[str, ...] = ()
    # This role's own hop-message instruction footer (see
    # `resolve_hop_instruction` below and `core/dispatch.py`'s hop-message
    # builder). Open prose, like `tool_profile`/`description` — "" (the
    # default) means "no declared instruction", not "no instruction at all":
    # a gated role still gets one generated from `gate_contract`.
    hop_instruction: str = ""

    def __post_init__(self) -> None:
        if not self.name or not _NAME_RE.match(self.name):
            raise ArchetypeError(
                f"invalid archetype name {self.name!r} "
                "(lowercase letters/digits/hyphens, starting with a letter)"
            )
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ArchetypeError(f"archetype {self.name!r}: version must be a positive integer")
        if self.scope not in SCOPES:
            raise ArchetypeError(
                f"archetype {self.name!r}: unknown scope {self.scope!r}; valid: {sorted(SCOPES)}"
            )
        if self.model_class not in MODEL_CLASSES:
            raise ArchetypeError(
                f"archetype {self.name!r}: unknown modelClass {self.model_class!r}; "
                f"valid: {sorted(MODEL_CLASSES)}"
            )
        if self.edit_rights not in EDIT_RIGHTS:
            raise ArchetypeError(
                f"archetype {self.name!r}: unknown editRights {self.edit_rights!r}; "
                f"valid: {sorted(EDIT_RIGHTS)}"
            )
        if not self.soul_template.strip():
            raise ArchetypeError(f"archetype {self.name!r}: soulTemplate must not be blank")
        if not self.agents_template.strip():
            raise ArchetypeError(f"archetype {self.name!r}: agentsTemplate must not be blank")
        if (
            not isinstance(self.token_budget, int)
            or isinstance(self.token_budget, bool)
            or self.token_budget <= 0
        ):
            raise ArchetypeError(f"archetype {self.name!r}: tokenBudget must be a positive integer")

    @property
    def resolved_policy_role(self) -> str:
        """The role→model policy key this archetype resolves through (see module docstring)."""
        return self.policy_role or self.name

    def to_wire(self) -> dict[str, Any]:
        """Serialize to the camelCase wire format (`docket roles show`, overlay persistence)."""
        doc: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "scope": self.scope,
            "modelClass": self.model_class,
            "soulTemplate": self.soul_template,
            "agentsTemplate": self.agents_template,
            "gateContract": self.gate_contract.to_wire(),
            "editRights": self.edit_rights,
            "toolProfile": self.tool_profile,
            "tokenBudget": self.token_budget,
        }
        if self.policy_role:
            doc["policyRole"] = self.policy_role
        if self.description:
            doc["description"] = self.description
        if self.denied_tools:
            doc["deniedTools"] = list(self.denied_tools)
        if self.hop_instruction:
            doc["hopInstruction"] = self.hop_instruction
        return doc


def from_wire(name: str, doc: dict[str, Any]) -> RoleArchetype:
    """Parse one archetype from its camelCase wire form (overlay JSON or a user YAML file).
    Raises `ArchetypeError` on any missing/invalid field — callers decide whether to
    propagate (`docket roles add/validate`) or skip-and-continue (`load_registry`)."""
    if not isinstance(doc, dict):
        raise ArchetypeError(f"archetype {name!r}: definition must be a mapping")

    doc_name = doc.get("name", name)
    if doc_name != name:
        raise ArchetypeError(
            f"archetype key {name!r} does not match its own name field {doc_name!r}"
        )

    gate_doc = doc.get("gateContract", {})
    if not isinstance(gate_doc, dict):
        raise ArchetypeError(f"archetype {name!r}: gateContract must be a mapping")
    gate = GateContract(
        kind=str(gate_doc.get("kind", "none")),
        regexes=tuple(str(r) for r in gate_doc.get("regexes", [])),
    )

    try:
        version = int(doc.get("version", 1))
    except (TypeError, ValueError) as exc:
        raise ArchetypeError(f"archetype {name!r}: version must be an integer") from exc

    try:
        # 6000 = RoleArchetype.token_budget's own default — a legacy overlay
        # entry (or any doc that never set one) still parses instead of
        # crashing (see the module docstring's "token_budget" paragraph).
        token_budget = int(doc.get("tokenBudget", 6000))
    except (TypeError, ValueError) as exc:
        raise ArchetypeError(f"archetype {name!r}: tokenBudget must be an integer") from exc

    return RoleArchetype(
        name=name,
        version=version,
        scope=str(doc.get("scope", "")),
        model_class=str(doc.get("modelClass", "")),
        soul_template=str(doc.get("soulTemplate", "")),
        agents_template=str(doc.get("agentsTemplate", "")),
        gate_contract=gate,
        edit_rights=str(doc.get("editRights", "")),
        tool_profile=str(doc.get("toolProfile", "")),
        policy_role=str(doc.get("policyRole", "")),
        description=str(doc.get("description", "")),
        token_budget=token_budget,
        denied_tools=tuple(str(t) for t in doc.get("deniedTools", [])),
        hop_instruction=str(doc.get("hopInstruction", "")),
    )


def resolve_hop_instruction(archetype: RoleArchetype) -> str:
    """*archetype*'s own `hop_instruction` if declared, else one generated from its
    `gate_contract` (verdict/mechanical/approval); a `none`-kind gate generates none. See
    specs/functional/role-archetypes.spec.md ("Hop instructions")."""
    # The four built-in roles never reach this: `core/dispatch.py`'s hop-message
    # builder keeps their pre-existing hardcoded text unconditionally.
    if archetype.hop_instruction:
        return archetype.hop_instruction
    gc = archetype.gate_contract
    if gc.kind == "verdict" and gc.regexes:
        markers = " or ".join(gc.regexes)
        return (
            f"Start exactly one output line with {markers} (case-insensitive); "
            "reasons may come before or after that marker line."
        )
    if gc.kind == "mechanical":
        return "Complete the task; your work is verified mechanically before the pipeline advances."
    if gc.kind == "approval":
        return "Complete the task; a human must approve before the pipeline advances."
    return ""


def render(template: str, variables: dict[str, str]) -> str:
    """Substitute a `${var}`-style template against `variables` (strict, not
    `safe_substitute`): an unprovided variable is a real authoring bug, raised as
    `ArchetypeError` rather than silently writing a literal `${typo}`."""
    try:
        return Template(template).substitute(variables)
    except KeyError as exc:
        raise ArchetypeError(f"template references unknown variable: {exc}") from exc
    except ValueError as exc:
        raise ArchetypeError(f"template is malformed: {exc}") from exc


# ── Built-in archetypes ──────────────────────────────────────────────────────

_SOUL_HEAD = (
    "# SOUL.md — ${project} · ${role}\n\n"
    "## Identity\n"
    "You are the **${role}** of the **${project}** pod (agent id `${memberId}`).\n\n"
    "**Session Key:** `${sessionKey}`\n\n"
    "You belong to one project only. Respect the pod session-key boundary — "
    "no cross-project access.\n\n"
    "## Project\n${objective}\n\n"
    "## Codebase\n${codebaseOrConfigured}\n\n"
    "## Stack\n${stack}\n\n"
)

_LEAD_BODY = (
    "## Role — Lead / Orchestrator\n"
    "- You own the pod's context, memory, and human communication.\n"
    "- Decompose work and dispatch it to the pod's workers "
    "(implementer → reviewer → tester).\n"
    "- **You NEVER edit code, run git, or execute the build.** If you are "
    "about to, STOP and delegate to the implementer.\n"
    "- Surface architectural decisions and risky actions to the human (HITL).\n"
)

_IMPLEMENTER_BODY = (
    "## Role — Implementer\n"
    "- You run **inside** this project's workspace and know ${codebaseOrIt} "
    "deeply. Read files before changing them.\n"
    "- You implement the tasks the Lead assigns: read/write/edit the codebase.\n"
    "- Signal completion with `<promise>DONE</promise>`.\n"
    "- Never push to main/master without HITL approval; never delete files "
    "without explicit instruction.\n"
)

_REVIEWER_BODY = (
    "## Role — Reviewer (veto power)\n"
    "- You review diffs for correctness, security, and requirement fit.\n"
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

_LEGACY_AGENTS_TEMPLATE = (
    "# AGENTS.md — ${project} · ${role}\n\n"
    "## Session Startup\n"
    "_Lean — re-sent every turn._\n"
    "1. Read ${requiredStartupFile} — startup protocol + your codebase\n"
    "   path (the runtime requires this after every context reset).\n"
    f"2. Read {_mem.HEARTBEAT_FILE} — active tasks/decisions (small; always). Unchecked\n"
    "   items mean you were interrupted mid-task: resume them, don't greet idle.\n"
    "3. Read memory/YYYY-MM-DD.md only when the task needs prior context;\n"
    "   don't slurp the whole memory/ dir — what you read is re-sent every\n"
    "   later turn.\n\n"
    "## Red Lines\n"
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
        agents_template=_LEGACY_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="none"),
        edit_rights="none",
        tool_profile="coordination",
        policy_role="manager",
        description="orchestrates the pod; never edits code",
        # Lead never receives prior-hop carryover (`_hop_message` returns
        # before any budgeting for this role) — a modest budget is declared
        # for completeness/forward-compat, not exercised today.
        token_budget=2000,
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
        agents_template=_LEGACY_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="mechanical"),
        edit_rights="write",
        tool_profile="full-repo",
        policy_role="programmer",
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
        agents_template=_LEGACY_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="verdict", regexes=("APPROVE", "REQUEST-CHANGES")),
        edit_rights="read-only",
        tool_profile="read-only",
        policy_role="reviewer",
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
        agents_template=_LEGACY_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="verdict", regexes=("PASS", "FAIL")),
        edit_rights="read-only",
        tool_profile="read-only-exec",
        policy_role="tester",
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
# expressible without a new hardcoded role string anywhere in core/pod.py or
# cli/_pod.py. They participate in `docket roles`/`normalize_role`/`member_id`,
# in pod composition presets (`core/blueprints.py`'s research/content/ops
# blueprints), and — via `gate_contract` — in the dispatch executor's gate
# resolution (`core/orchestrator.py`).

_STARTER_SOUL_HEAD = (
    "# SOUL.md — ${project} · ${role}\n\n"
    "## Identity\n"
    "You are the **${role}** of the **${project}** pod (agent id `${memberId}`).\n\n"
    "**Session Key:** `${sessionKey}`\n\n"
    "You belong to one project only. Respect the pod session-key boundary — "
    "no cross-project access.\n\n"
    "## Objective\n${objective}\n\n"
    "## Working Directory\n${workDir}\n\n"
    "## Codebase\n${codebaseOrConfigured}\n\n"
)

_STARTER_AGENTS_TEMPLATE = (
    "# AGENTS.md — ${project} · ${role}\n\n"
    "## Session Startup\n"
    "_Lean — re-sent every turn._\n"
    "1. Read ${requiredStartupFile} — startup protocol + your working directory\n"
    "   (the runtime requires this after every context reset).\n"
    f"2. Read {_mem.HEARTBEAT_FILE} — active tasks/decisions (small; always). Unchecked\n"
    "   items mean you were interrupted mid-task: resume them, don't greet idle.\n"
    "3. Read memory/YYYY-MM-DD.md only when the task needs prior context;\n"
    "   don't slurp the whole memory/ dir — what you read is re-sent every\n"
    "   later turn.\n\n"
    "## Red Lines\n"
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
    "- Signal completion with `<promise>DONE</promise>`.\n"
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
        edit_rights="write",
        tool_profile="research-read-write",
        description="gathers and synthesizes source material",
        token_budget=8000,
        denied_tools=(),
    ),
    "analyst": RoleArchetype(
        name="analyst",
        version=1,
        scope="pod",
        model_class="strong",
        soul_template=_STARTER_SOUL_HEAD + _ANALYST_BODY,
        agents_template=_STARTER_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="none"),
        edit_rights="write",
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
        edit_rights="write",
        tool_profile="content-authoring",
        description="drafts the pod's content deliverable",
        token_budget=6000,
        denied_tools=(),
    ),
    "critic": RoleArchetype(
        name="critic",
        version=1,
        scope="pod",
        model_class="cheap",
        soul_template=_STARTER_SOUL_HEAD + _CRITIC_BODY,
        agents_template=_STARTER_AGENTS_TEMPLATE,
        gate_contract=GateContract(kind="verdict", regexes=("APPROVE", "REJECT")),
        edit_rights="read-only",
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
        edit_rights="write",
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
        edit_rights="read-only",
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


@dataclass(frozen=True)
class ArchetypeRegistry:
    """Built-ins + starter library + user overlay, merged (user wins by name)."""

    archetypes: dict[str, RoleArchetype] = field(default_factory=dict)

    def get(self, name: str) -> RoleArchetype | None:
        return self.archetypes.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self.archetypes

    def role_names(self) -> tuple[str, ...]:
        return tuple(self.archetypes.keys())

    def items(self) -> list[tuple[str, RoleArchetype]]:
        return list(self.archetypes.items())

    def source_of(self, name: str) -> str:
        """'built-in' | 'starter' | 'user' | '' (unknown) — for `docket roles list`."""
        if name not in self.archetypes:
            return ""
        path = cfg.ARCHETYPE_REGISTRY_FILE
        if path.exists():
            raw = _store.read_json(path)
            if name in raw.get("roles", {}):
                return "user"
        if name in BUILTIN_ARCHETYPES:
            return "built-in"
        if name in STARTER_ARCHETYPES:
            return "starter"
        return "user"


def _read_overlay_raw() -> dict[str, Any]:
    path = cfg.ARCHETYPE_REGISTRY_FILE
    if not path.exists():
        return {}
    try:
        return _store.read_json(path)
    except Exception:
        return {}


def load_registry() -> ArchetypeRegistry:
    """Built-ins + starter library, overlaid by `~/.docket/docket-roles.json`. Not cached
    -- read fresh every call, so a live file edit or mid-session monkeypatch is always
    seen. A malformed overlay entry is silently skipped, never crashing a live fleet."""
    archetypes: dict[str, RoleArchetype] = dict(BUILTIN_ARCHETYPES)
    archetypes.update(STARTER_ARCHETYPES)

    raw = _read_overlay_raw()
    for name, doc in raw.get("roles", {}).items():
        try:
            archetypes[name] = from_wire(name, doc)
        except ArchetypeError:
            continue
    return ArchetypeRegistry(archetypes)


# The capability each built-in tool name represents. `registry_for_role` maps a
# role's `denied_tools` through this to decide which *kinds* that role may not
# hold, so a capability denial survives arriving under an unfamiliar name (an
# MCP-adapted tool is namespaced `mcp__<server>__<tool>`, which no denylist can
# spell out in advance).
#
# Deliberately a static map rather than a lookup into the registry being
# narrowed. Deriving the kind from `base` would make the denial conditional on
# the denied built-in still being *present* there — so a caller that narrowed
# the registry first (`DocketDriver.registry_factory` exists precisely to inject
# a narrower tool set) would silently stop deriving `write`, and a Reviewer
# would regain a write-capable MCP tool. The denial must depend only on the
# role's own data, never on what the incoming registry happens to contain.
#
# `test_role_tools_and_identity.py` pins this against `builtin_registry()` so
# the two cannot drift.
BUILTIN_TOOL_KINDS: dict[str, ToolKind] = {
    "read": "read",
    "glob": "read",
    "grep": "read",
    "fetch": "read",
    "write": "write",
    "edit": "write",
    "bash": "exec",
}


def registry_for_role(base: ToolRegistry, role: str) -> ToolRegistry:
    """Narrow *base* to exactly what *role* may call.

    Looks *role* up in the live archetype registry and removes every name in its
    `denied_tools` via the public `ToolRegistry.without()` API -- data-driven, not a
    per-role branch (`core/agent_loop.py` is the one caller, once per turn). A
    Reviewer's registry genuinely lacks `write`/`edit`, so a call to either is
    refused by `dispatch_tool` as an *unknown tool* -- stronger than a SOUL.md
    instruction telling it not to use them. An unrecognized *role* or one with an
    empty `denied_tools` returns *base* unchanged.

    **Also removes by capability, not only by name.** `denied_tools` is a list of
    literal built-in names, but `base` may also carry MCP-adapted tools registered
    under a namespaced name (`mcp__<server>__<tool>`) no denylist could ever spell
    out in advance -- and every adapted tool is registered `kind="write"`
    unconditionally, since nothing can prove a remote tool is actually read-only.
    So after the name-based removal, this also computes the set of `Tool.kind`s
    implied by the denied names still present in *base* and removes every
    remaining tool of those kinds via `ToolRegistry.without_kind()`. A no-op
    against a builtins-only registry (today's shipped archetypes already name all
    the built-ins of the kinds they deny); it only starts removing something new
    once an MCP tool is actually present -- exactly the case a name-only denylist
    cannot reach, so a role denied `write` can never regain a write-capable tool
    just because it arrived through MCP instead of `core.tools.builtin_registry()`.
    """
    archetype = load_registry().get(role)
    if archetype is None or not archetype.denied_tools:
        return base
    narrowed = base.without(*archetype.denied_tools)
    denied_kinds = {
        kind for name in archetype.denied_tools if (kind := BUILTIN_TOOL_KINDS.get(name))
    }
    if denied_kinds:
        narrowed = narrowed.without_kind(*denied_kinds)
    return narrowed


def validate_archetype_dict(name: str, doc: dict[str, Any]) -> list[str]:
    """Validate a candidate archetype definition without raising. Returns a list of
    human-readable error strings (empty = valid). Used by `docket roles validate`/`add`
    to give a full error report instead of stopping at the first problem."""
    errors: list[str] = []
    try:
        arch = from_wire(name, doc)
    except ArchetypeError as exc:
        return [str(exc)]

    sample_variables = {
        "project": "sample-project",
        "role": arch.name,
        "memberId": f"sample-project-{arch.name}",
        "sessionKey": "agent:sample-project:default",
        "objective": "sample objective",
        "codebase": "",
        "codebaseOrConfigured": "(no codebase configured)",
        "codebaseOrIt": "it",
        "stack": "",
        "workDir": "/tmp/sample-project",
        "requiredStartupFile": "WORKFLOW_AUTO.md",
    }
    try:
        render(arch.soul_template, sample_variables)
    except ArchetypeError as exc:
        errors.append(f"soulTemplate: {exc}")
    try:
        render(arch.agents_template, sample_variables)
    except ArchetypeError as exc:
        errors.append(f"agentsTemplate: {exc}")
    return errors


def parse_yaml_file(path: str) -> dict[str, Any]:
    """Parse a standalone archetype YAML file (the `docket roles add <file>` input)."""
    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        raise ArchetypeError("PyYAML not installed — run: pip install pyyaml") from None
    from pathlib import Path as _Path

    p = _Path(path)
    if not p.is_file():
        raise ArchetypeError(f"file not found: {path}")
    try:
        doc = _yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ArchetypeError(f"YAML parse error: {exc}") from exc
    if not isinstance(doc, dict):
        raise ArchetypeError(f"archetype file must be a mapping (got {type(doc).__name__})")
    return doc


def add_user_archetype(doc: dict[str, Any]) -> RoleArchetype:
    """Validate `doc` and merge it into the user overlay (`docket-roles.json`). `doc`
    must carry a top-level `name`. Overlays (and may override) a built-in or starter
    archetype by name -- the same "user wins" contract `docket-models.json` uses."""
    name = str(doc.get("name", "")).strip()
    if not name:
        raise ArchetypeError("archetype definition must have a top-level 'name'")
    arch = from_wire(name, doc)  # raises ArchetypeError on any invalid field

    path = cfg.ARCHETYPE_REGISTRY_FILE

    def _fn(current: dict[str, Any]) -> dict[str, Any]:
        current.setdefault("roles", {})[name] = arch.to_wire()
        return current

    path.parent.mkdir(parents=True, exist_ok=True)
    _store.read_modify_write(path, _fn)
    return arch
