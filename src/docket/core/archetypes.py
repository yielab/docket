"""Role archetypes: versioned, declarative role definitions (ROADMAP Phase 16 W-6).

A *role archetype* is data, not code: a name, a scope, a model class, SOUL/AGENTS
prose templates, a gate contract, edit rights, and a tool profile. `core/pod.py`'s
`normalize_role`/`member_id`/`policy_role_for` resolve pod roles against the
registry this module builds instead of a hardcoded 4-tuple, so a fifth (sixth,
...) role is data, never a new hardcoded string in `core/pod.py`/`cli/_pod.py`.

Built-in archetypes (`BUILTIN_ARCHETYPES`) reproduce today's four pod roles —
lead, implementer, reviewer, tester — byte-identical to the pre-W-6 hand-written
SOUL.md/AGENTS.md generators that used to live in `cli/_pod.py` (golden-tested;
see `tests/python/test_w6_archetypes.py`). A starter library ships six more:
researcher, analyst, writer, critic, operator, monitor (`STARTER_ARCHETYPES`).

Closed vs. open (ROADMAP Phase 16, quoted verbatim): "no fifth role ever lands
as a hardcoded string; archetype prose and rosters are user-extensible, but
gate contracts, edit rights, and scope stay closed typed sets docket can
reason about." So here: `scope`, `model_class`, `gate_contract.kind`, and
`edit_rights` are closed enums validated against a fixed set (`SCOPES`,
`MODEL_CLASSES`, `GATE_KINDS`, `EDIT_RIGHTS`); `name`, `soul_template`,
`agents_template`, `description`, `tool_profile` are open prose a user
archetype is free to set to anything.

`modelClass` (cheap|strong) slots into the *existing* role→model policy
(`core/models_policy.py`) rather than replacing it: the four legacy archetypes
carry a `policy_role` override (`manager`/`programmer`/`reviewer`/`tester`) so
their model resolves exactly as it did before this module existed — same
named policy row, same `docket models set <role>` behavior. An archetype with
no override (every starter-library/user role) resolves through its own
`model_class` against the live rank anchors instead
(`models_policy.resolve_role_model`'s archetype fallback) — no new hardcoded
`ALL_ROLES` entry is needed per role.

User archetypes overlay built-ins via `~/.openclaw/docket-roles.json` (the
same overlay pattern as `docket-models.json`; see `core/models_policy.py`) —
tolerant on load (a malformed entry is skipped, never crashes a live fleet;
`docket roles validate` is how an operator finds out why). The *authoring*
format for a new archetype is a standalone YAML file (`docket roles add
<file.yaml>`) — "a role becomes a versioned YAML definition" — which is
parsed, validated, and merged into the JSON-backed overlay (the project's
existing docket-owned-JSON-through-`edges/store.py` convention; see D-12 in
ROADMAP.md). Docket's own built-in/starter archetypes remain Python literals
in this module, matching the project's standing convention that workspace
prose is generated inline in Python, not loaded from shipped template files
(see CLAUDE.md's `templates/` note).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from string import Template
from typing import Any

import docket.config as cfg
from docket.core import memory as _mem
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
    """Closed typed union over the four gate-contract kinds.

    `kind` is one of `"none" | "verdict" | "mechanical" | "approval"`. `regexes`
    is only meaningful for `kind == "verdict"` — e.g. the reviewer's
    `("APPROVE", "REQUEST-CHANGES")` or the tester's `("PASS", "FAIL")` first-line
    markers (mirroring `core/dispatch.py`'s real `_REVIEWER_VERDICT_RE`/
    `_TESTER_VERDICT_RE` patterns exactly, for the day W-8 wires this contract
    into the dispatch executor). This is DATA — `core/dispatch.py`'s actual gate
    parsing/enforcement is untouched by this module (W-8, out of scope for W-6).
    """

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
    """A versioned, declarative role definition.

    Field names below are Python (snake_case); the wire/YAML format uses the
    card's camelCase names (`modelClass`, `soulTemplate`, `agentsTemplate`,
    `gateContract`, `editRights`, `toolProfile`) — see `from_wire`/`to_wire`.
    """

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
        }
        if self.policy_role:
            doc["policyRole"] = self.policy_role
        if self.description:
            doc["description"] = self.description
        return doc


def from_wire(name: str, doc: dict[str, Any]) -> RoleArchetype:
    """Parse one archetype from its camelCase wire form (overlay JSON or a user YAML file).

    Raises `ArchetypeError` on any missing/invalid field — callers decide whether
    to propagate (`docket roles add/validate`) or skip-and-continue (`load_registry`
    tolerating a malformed overlay entry, matching `core/models_policy.py`'s
    tolerance for a malformed `docket-models.json`).
    """
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
    )


def render(template: str, variables: dict[str, str]) -> str:
    """Substitute a `${var}`-style template against `variables` (strict).

    Strict (not `safe_substitute`): a template referencing a variable docket
    doesn't provide is a real authoring bug — surfacing it as a clear
    `ArchetypeError` at provisioning/validate time beats silently writing a
    literal `${typo}` into an agent's SOUL.md.
    """
    try:
        return Template(template).substitute(variables)
    except KeyError as exc:
        raise ArchetypeError(f"template references unknown variable: {exc}") from exc
    except ValueError as exc:
        raise ArchetypeError(f"template is malformed: {exc}") from exc


# ── Built-in archetypes: byte-identical to the pre-W-6 cli/_pod.py generators ──

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

_TESTER_BODY = (
    "## Role — Tester\n"
    "- You run the test suite and reproduction steps and report a binary "
    "**PASS/FAIL** with evidence.\n"
    "- Observe behaviour only — do not read or critique the implementation.\n"
    "- **Marker convention:** the first non-blank line of your reply must be "
    "exactly `PASS` or `FAIL` (case-insensitive) — dispatch parses this line "
    "to gate the pipeline. Evidence goes on the lines after it. Anything else "
    "on that first line blocks the pipeline the same as a FAIL.\n"
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
    f"- Before starting multi-step work, write it to {_mem.HEARTBEAT_FILE} — an unwritten\n"
    "  task does not survive a context reset.\n"
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
    ),
}

BUILTIN_ROLE_ORDER: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")


# ── Starter library: six generic pod roles for non-coding objectives ──────────
#
# These ship as data, proving "a research pod, a content pod, an ops pod" are
# expressible without a new hardcoded role string anywhere in core/pod.py or
# cli/_pod.py. They participate in `docket roles`/`normalize_role`/`member_id`
# today; wiring them into pod *composition presets* (rosters/blueprints) is
# W-7, and wiring `gate_contract` into the dispatch executor is W-8 — both
# explicitly out of scope here.

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
    f"- Before starting multi-step work, write it to {_mem.HEARTBEAT_FILE} — an unwritten\n"
    "  task does not survive a context reset.\n"
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
    "- **Marker convention:** the first non-blank line of your reply must be "
    "exactly `APPROVE` or `REJECT` (case-insensitive). Reasons go on the lines "
    "after it. Anything else on that first line is unparseable and blocks the "
    "pipeline the same as a rejection.\n"
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
    """Built-ins + starter library, overlaid by `~/.openclaw/docket-roles.json`.

    Not cached — read fresh every call (mirrors `models_policy.load_registry`),
    so a CLI process that reads the registry more than once (or a test that
    monkeypatches `cfg.ARCHETYPE_REGISTRY_FILE` mid-session) always sees the
    live file. A malformed overlay entry is silently skipped here (never
    crashes a live fleet); `docket roles validate` surfaces exactly why.
    """
    archetypes: dict[str, RoleArchetype] = dict(BUILTIN_ARCHETYPES)
    archetypes.update(STARTER_ARCHETYPES)

    raw = _read_overlay_raw()
    for name, doc in raw.get("roles", {}).items():
        try:
            archetypes[name] = from_wire(name, doc)
        except ArchetypeError:
            continue
    return ArchetypeRegistry(archetypes)


def validate_archetype_dict(name: str, doc: dict[str, Any]) -> list[str]:
    """Validate a candidate archetype definition without raising.

    Returns a list of human-readable error strings (empty = valid). Used by
    `docket roles validate` (both for the live registry's user overlay
    entries and for a standalone file passed on the command line) and by
    `docket roles add` to give a full error report instead of stopping at the
    first problem.
    """
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
    """Validate `doc` and merge it into the user overlay (`docket-roles.json`).

    `doc` must carry a top-level `name`. Overlays (and may override) a
    built-in or starter archetype by name — the same "user wins" contract
    `docket-models.json` uses for per-role model overrides.
    """
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
