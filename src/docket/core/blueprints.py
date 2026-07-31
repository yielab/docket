"""Pod blueprints: objective-scoped provisioning (ROADMAP Phase 16 W-7).

A *blueprint* is a named, versioned pod shape: an archetype roster (role names
resolved against ``core/archetypes.py``'s registry — W-6), a default pipeline
(``core/pipeline.py``'s format — W-1, attached but not executed; the executor
is W-2), a workspace kind (``codebase`` — a git-tracked project directory —
or ``workdir`` — a plain working directory with no codebase assumption), and
an optional default per-pod spend cap. Where a blueprint's default pipeline
gates a step (mechanical/verdict/approval), that gate always matches the
gated role's own archetype ``gateContract`` exactly — there is no separate
"default gates" field to drift from it.

Built-ins (``BUILTIN_BLUEPRINTS``):

- ``software`` — today's pod, unchanged: Lead + Implementer against a
  codebase. Its ``default_pipeline`` is exactly ``core.pipeline.default_pipeline()``
  (the same object dispatch.py's hardcoded order already matches) and it sets
  no default budget cap — provisioning through this blueprint is behaviorally
  identical to the pre-W-7 default `docket add`.
- ``research`` — Lead, Researcher, Analyst, Writer, Critic (workdir): gathers
  and analyzes source material, drafts a deliverable, and gates it on the
  Critic's APPROVE/REJECT verdict (bounded rework back to the Writer).
- ``content`` — Lead, Writer, Critic (workdir): drafts a content deliverable
  and gates it the same way as ``research``, without the gather/analyze steps.
- ``ops`` — Lead, Operator, Monitor (workdir): executes operational actions
  behind a mechanical check (deferring to the Operator's own ``verifyCmd``,
  mirroring the Implementer's convention), then requires human approval
  before the Monitor's findings are considered actioned.

Per ROADMAP Phase 16's anti-overengineering rule, ``workspace_kind`` is a
closed enum (``WORKSPACE_KINDS``) — same discipline as ``core/archetypes.py``'s
``scope``/``modelClass``/``gateContract.kind``/``editRights``. A blueprint's
*roster* references the archetype registry by name (open — any built-in,
starter-library, or user-defined archetype), exactly like ``core/pod.py``'s
pre-existing ``DEFAULT_POD_ROLES``/``FULL_POD_ROLES`` tuples already do; this
module does not re-validate role names against that registry itself —
``core/pod.py``'s ``plan_pod``/``normalize_role`` already does, the first time
a blueprint's roster is actually provisioned.

Blueprints are Python literals in this module (the same "workspace prose is
generated inline in Python" convention ``core/archetypes.py`` follows for its
own built-ins) — there is no user-authored blueprint YAML format yet (unlike
``docket roles add``); the four built-ins are the whole registry today.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from docket.core import pipeline as _pipeline
from docket.core import pod as _pod

WORKSPACE_KINDS: frozenset[str] = frozenset({"codebase", "workdir"})

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class BlueprintError(ValueError):
    """Invalid blueprint definition or unknown blueprint name."""


@dataclass(frozen=True)
class PodBlueprint:
    """A named, versioned pod shape — archetype roster + default pipeline.

    ``roles`` is ordered and its first entry MUST be ``"lead"`` — a pod has
    exactly one orchestrator (``core/pod.py``'s ``_SINGLETON_POD_ROLES``
    invariant, unchanged by this module). Per-role org-vs-pod scope is
    whatever each referenced archetype's own ``scope`` field says (inherited,
    not re-declared here) — every built-in/starter archetype today is
    ``"pod"``-scoped, so no built-in blueprint introduces an org-scoped role
    yet (same reserved-for-later state ``role-archetypes.spec.md`` documents
    for archetypes themselves).
    """

    name: str
    version: int
    workspace_kind: str  # closed: "codebase" | "workdir"
    roles: tuple[str, ...]
    default_pipeline: _pipeline.PipelineSpec
    default_budget_usd: float | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name or not _NAME_RE.match(self.name):
            raise BlueprintError(
                f"invalid blueprint name {self.name!r} "
                "(lowercase letters/digits/hyphens, starting with a letter)"
            )
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise BlueprintError(f"blueprint {self.name!r}: version must be a positive integer")
        if self.workspace_kind not in WORKSPACE_KINDS:
            raise BlueprintError(
                f"blueprint {self.name!r}: unknown workspaceKind {self.workspace_kind!r}; "
                f"valid: {sorted(WORKSPACE_KINDS)}"
            )
        if not self.roles:
            raise BlueprintError(f"blueprint {self.name!r}: roles must not be empty")
        if self.roles[0] != "lead":
            raise BlueprintError(
                f"blueprint {self.name!r}: first role must be 'lead' "
                "(a pod has exactly one orchestrator)"
            )
        if self.roles.count("lead") > 1:
            raise BlueprintError(f"blueprint {self.name!r}: a pod may have only one lead")
        if self.default_budget_usd is not None and self.default_budget_usd < 0:
            raise BlueprintError(f"blueprint {self.name!r}: default_budget_usd must be >= 0")


def _research_pipeline() -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="research-default",
        description=(
            "Lead -> Researcher -> Analyst -> Writer -> Critic, gated on an "
            "APPROVE/REJECT verdict (bounded rework back to the Writer)."
        ),
        steps=[
            _pipeline.Step(id="lead", role="lead"),
            _pipeline.Step(id="researcher", role="researcher"),
            _pipeline.Step(id="analyst", role="analyst"),
            _pipeline.Step(id="writer", role="writer"),
            _pipeline.Step(
                id="critic",
                role="critic",
                gate=_pipeline.VerdictGate(
                    pattern=r"^\s*(APPROVE|REJECT)\b",
                    pass_values=["approve"],
                    rework=_pipeline.ReworkEdge(to="writer", when=["reject"], max_cycles=1),
                ),
            ),
        ],
    )


def _content_pipeline() -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="content-default",
        description="Lead -> Writer -> Critic, gated on an APPROVE/REJECT verdict.",
        steps=[
            _pipeline.Step(id="lead", role="lead"),
            _pipeline.Step(id="writer", role="writer"),
            _pipeline.Step(
                id="critic",
                role="critic",
                gate=_pipeline.VerdictGate(
                    pattern=r"^\s*(APPROVE|REJECT)\b",
                    pass_values=["approve"],
                    rework=_pipeline.ReworkEdge(to="writer", when=["reject"], max_cycles=1),
                ),
            ),
        ],
    )


def _ops_pipeline() -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="ops-default",
        description=(
            "Lead -> Operator (mechanical check, deferring to its own verifyCmd) -> "
            "Monitor (requires human approval before findings are considered actioned)."
        ),
        steps=[
            _pipeline.Step(id="lead", role="lead"),
            _pipeline.Step(
                id="operator", role="operator", gate=_pipeline.MechanicalGate(command=None)
            ),
            _pipeline.Step(
                id="monitor",
                role="monitor",
                gate=_pipeline.ApprovalGate(message="Operator action awaiting sign-off."),
            ),
        ],
    )


BUILTIN_BLUEPRINTS: dict[str, PodBlueprint] = {
    "software": PodBlueprint(
        name="software",
        version=1,
        workspace_kind="codebase",
        roles=_pod.DEFAULT_POD_ROLES,
        default_pipeline=_pipeline.default_pipeline(),
        default_budget_usd=None,
        description="today's pod: Lead + Implementer against a codebase (unchanged default)",
    ),
    "research": PodBlueprint(
        name="research",
        version=1,
        workspace_kind="workdir",
        roles=("lead", "researcher", "analyst", "writer", "critic"),
        default_pipeline=_research_pipeline(),
        default_budget_usd=20.0,
        description="gathers and analyzes sources, drafts a deliverable, gates it on veto",
    ),
    "content": PodBlueprint(
        name="content",
        version=1,
        workspace_kind="workdir",
        roles=("lead", "writer", "critic"),
        default_pipeline=_content_pipeline(),
        default_budget_usd=15.0,
        description="drafts and vets a content deliverable",
    ),
    "ops": PodBlueprint(
        name="ops",
        version=1,
        workspace_kind="workdir",
        roles=("lead", "operator", "monitor"),
        default_pipeline=_ops_pipeline(),
        default_budget_usd=30.0,
        description="executes operational actions with a mechanical check and human sign-off",
    ),
}

#: `docket add` with no `--blueprint` resolves to this — today's default pod.
DEFAULT_BLUEPRINT = "software"


@dataclass(frozen=True)
class BlueprintRegistry:
    """Built-in blueprints (no user overlay yet — see module docstring)."""

    blueprints: dict[str, PodBlueprint] = field(default_factory=dict)

    def get(self, name: str) -> PodBlueprint | None:
        return self.blueprints.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self.blueprints.keys())


def load_registry() -> BlueprintRegistry:
    """The live blueprint registry (built-ins only, today)."""
    return BlueprintRegistry(dict(BUILTIN_BLUEPRINTS))


def get_blueprint(name: str) -> PodBlueprint:
    """Look up a blueprint by name; raises ``BlueprintError`` naming the valid set."""
    registry = load_registry()
    found = registry.get(name)
    if found is None:
        valid = ", ".join(registry.names())
        raise BlueprintError(f"unknown blueprint {name!r}; valid blueprints: {valid}")
    return found
