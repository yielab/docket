"""Pod blueprints: objective-scoped provisioning.

A *blueprint* is a named, versioned pod shape: an archetype roster (role names
resolved against ``teams/roles.py``'s registry), a default pipeline
(``pipeline/domain/spec.py``'s format, resolved and executed by
``hops/application/steps.py::effective_pipeline`` through the Lead's ``blueprint`` meta whenever a
dispatch runs with no caller-supplied spec), a workspace kind
(``codebase`` — a git-tracked project directory — or ``workdir`` — a plain
working directory with no codebase assumption), and an optional default
per-pod spend cap. Where a blueprint's default pipeline gates a step
(mechanical/verdict/approval), that gate always matches the gated role's own
archetype ``gateContract`` exactly — there is no separate "default gates"
field to drift from it.

Built-ins (``BUILTIN_BLUEPRINTS``) are the four pipeline shapes behind every department:

- ``build`` — Lead, Implementer, Reviewer (codebase): ``pipeline.domain.spec.default_pipeline()``
  verbatim, so provisioning through it is the plain default `docket init`; the lean pod `init`
  provisions is this roster without the Reviewer, whose step a pod without the role never reaches.
- ``respond`` — Lead, Researcher, Writer, Reviewer, Actor (workdir): intake -> research -> draft ->
  review (APPROVE/REQUEST-CHANGES, bounded rework back to draft) -> act. Only the Actor can act
  outside the machine.
- ``operate`` — Lead, Monitor, Operator, Reviewer (workdir): watch -> propose (a person approves
  first) -> act (mechanical check, deferring to the Operator's own ``verifyCmd``) -> review.
- ``routine`` — Lead, Analyst, Writer, Reviewer (workdir): compile -> draft -> review (bounded
  rework back to draft). The ``records`` recipe adds its set, pipeline and schedule.

``workspace_kind`` is a closed enum (``WORKSPACE_KINDS``) — same discipline
as ``teams/roles.py``'s ``scope``/``modelClass``/``gateContract.kind``,
avoiding an open-ended set of workspace shapes that would otherwise need
special-casing elsewhere. A blueprint's *roster* references
the archetype registry by name (open — any built-in,
starter-library, or user-defined archetype), exactly like ``teams/pod.py``'s
pre-existing ``DEFAULT_POD_ROLES``/``FULL_POD_ROLES`` tuples already do; this
module does not re-validate role names against that registry itself —
``teams/pod.py``'s ``plan_pod``/``normalize_role`` already does, the first time
a blueprint's roster is actually provisioned.

Blueprints are Python literals in this module (the same "workspace prose is
generated inline in Python" convention ``teams/roles.py`` follows for its
own built-ins) — there is no user-authored blueprint YAML format yet (unlike
``docket pod update``); the four built-ins are the whole registry today.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from docket.kernel.errors import InvalidInput
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.teams import pod as _pod

WORKSPACE_KINDS: frozenset[str] = frozenset({"codebase", "workdir"})

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class BlueprintError(InvalidInput):
    """Invalid blueprint definition or unknown blueprint name."""


@dataclass(frozen=True)
class PodBlueprint:
    """A named, versioned pod shape — archetype roster + default pipeline.

    ``roles`` is ordered and its first entry MUST be ``"lead"`` — a pod has
    exactly one orchestrator (``teams/pod.py``'s ``_SINGLETON_POD_ROLES``
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


_VERDICT = r"^\s*(APPROVE|REQUEST-CHANGES)\b"


def _review_gate(rework_to: str | None) -> _gates.VerdictGate:
    """The Reviewer's APPROVE/REQUEST-CHANGES gate, with a bounded rework edge back to *rework_to*
    when one is named."""
    rework = (
        _gates.ReworkEdge(to=rework_to, when=["request-changes"], max_cycles=1)
        if rework_to
        else None
    )
    return _gates.VerdictGate(pattern=_VERDICT, pass_values=["approve"], rework=rework)


def _respond_pipeline() -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="respond-default",
        description=(
            "Lead -> Researcher -> Writer -> Reviewer (APPROVE or REQUEST-CHANGES, one rework back "
            "to the Writer) -> Actor, the only role that acts outside the machine."
        ),
        steps=[
            _step.Step(
                id="intake",
                role="lead",
                instructions=(
                    "You are the pod Lead. Decompose this task into a concrete plan for "
                    "the Researcher (you never research, draft or send anything yourself):"
                ),
            ),
            _step.Step(
                id="research",
                role="researcher",
                instructions=(
                    "Gather what the task needs from the sources you can read: the working "
                    "directory and any server you are offered. Reply with the facts you found "
                    "and where each came from. You cannot send anything."
                ),
            ),
            _step.Step(
                id="draft",
                role="writer",
                instructions=(
                    "Write the message the task asks for into draft.md in the working directory, "
                    "using the Researcher's findings. Say who it goes to on the first line. "
                    "Do not send it."
                ),
            ),
            _step.Step(
                id="review",
                role="reviewer",
                gate=_review_gate("draft"),
                instructions=(
                    "Read draft.md as its recipient would. APPROVE only a draft that is accurate, "
                    "says what the task asked, and is safe to leave the machine; otherwise "
                    "REQUEST-CHANGES and say what to change."
                ),
            ),
            _step.Step(id="act", role="actor"),
        ],
    )


def _operate_pipeline() -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="operate-default",
        description=(
            "Lead -> Monitor (a person approves first) -> Operator (mechanical check, deferring to "
            "its own verifyCmd) -> Reviewer."
        ),
        steps=[
            _step.Step(
                id="watch",
                role="lead",
                instructions=(
                    "You are the pod Lead. Read the signals this task names and decide what the "
                    "Monitor should look at (you never act on them yourself):"
                ),
            ),
            _step.Step(
                id="propose",
                role="monitor",
                gate=_gates.ApprovalGate(
                    message="Approve before the Monitor proposes and the Operator acts."
                ),
                instructions=(
                    "Propose the smallest corrective action the signals call for, and say how to "
                    "check that it worked. Do not act."
                ),
            ),
            _step.Step(id="act", role="operator", gate=_gates.MechanicalGate(command=None)),
            _step.Step(
                id="review",
                role="reviewer",
                gate=_review_gate(None),
                instructions=(
                    "Check that the Operator did what the proposal said and nothing else. "
                    "APPROVE or REQUEST-CHANGES, and say why."
                ),
            ),
        ],
    )


def _routine_pipeline() -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="routine-default",
        description=(
            "Analyst compiles -> Writer drafts -> Reviewer (APPROVE or REQUEST-CHANGES, one rework "
            "back to the Writer)."
        ),
        steps=[
            _step.Step(
                id="compile",
                role="analyst",
                instructions=(
                    "Compile what the task asks for from the working directory: the figures, "
                    "the facts and where each came from. Reply with the compilation; do not "
                    "draft the deliverable."
                ),
            ),
            _step.Step(id="draft", role="writer"),
            _step.Step(id="review", role="reviewer", gate=_review_gate("draft")),
        ],
    )


BUILTIN_BLUEPRINTS: dict[str, PodBlueprint] = {
    "build": PodBlueprint(
        name="build",
        version=1,
        workspace_kind="codebase",
        roles=_pod.FULL_POD_ROLES,
        default_pipeline=_pipeline.default_pipeline(),
        default_budget_usd=None,
        description="Lead, Implementer and Reviewer against a codebase (the default pod)",
    ),
    "respond": PodBlueprint(
        name="respond",
        version=1,
        workspace_kind="workdir",
        roles=("lead", "researcher", "writer", "reviewer", "actor"),
        default_pipeline=_respond_pipeline(),
        default_budget_usd=20.0,
        description="researches, drafts and vets a message, then acts on it outside the machine",
    ),
    "operate": PodBlueprint(
        name="operate",
        version=1,
        workspace_kind="workdir",
        roles=("lead", "monitor", "operator", "reviewer"),
        default_pipeline=_operate_pipeline(),
        default_budget_usd=30.0,
        description="watches signals, proposes an action a person approves, acts, and reviews it",
    ),
    "routine": PodBlueprint(
        name="routine",
        version=1,
        workspace_kind="workdir",
        roles=("lead", "analyst", "writer", "reviewer"),
        default_pipeline=_routine_pipeline(),
        default_budget_usd=15.0,
        description="compiles, drafts and reviews a recurring deliverable",
    ),
}

#: `docket init` with no `--blueprint` resolves to this — today's default pod.
DEFAULT_BLUEPRINT = "build"


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
