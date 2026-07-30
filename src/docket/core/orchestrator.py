"""The pipeline executor (ROADMAP Phase 16 W-2) and generalized gates (W-8).

Before this card, ``core/pipeline.py`` (W-1) defined the docket-native pipeline
*format* with no executor, and ``core/archetypes.py`` (W-6) defined a role's
``gateContract`` as descriptive data only — ``core/dispatch.py`` kept its own,
independently hardcoded Reviewer/Tester verdict parsing and Implementer
``verifyCmd`` gate, unaware of either. This module is what makes both of those
load-bearing: it resolves a :class:`~docket.core.pipeline.PipelineSpec` against
a pod's live roster into a concrete, deterministic :class:`ExecutionPlan`, and
gate execution (:mod:`docket.core.dispatch`) now reads a step's *resolved* gate
— its own declared ``gate``, or (only when the step omits one) its archetype's
``gateContract`` — instead of branching on a hardcoded role name.

This module is deliberately **pure and dispatch-independent** — no filesystem
I/O, no subprocess, no import of ``core/dispatch.py``. ``core/dispatch.py``
imports *this* module (a one-way dependency); the reverse would be a cycle,
since ``dispatch.py``'s hop loop is what actually calls back into this
module's :func:`resolve_plan`/:func:`resolve_gate`/:func:`parse_verdict`/
:func:`run_group` to walk a spec. ``docket pipeline plan`` renders directly
from :func:`resolve_plan` too — the same function the real executor calls,
per ROADMAP's explicit ban on a second, drift-prone pretty-printer.

Determinism contract (test-pinned, see ``tests/python/test_w2_orchestrator.py``):
:func:`resolve_plan` is a pure function of ``(spec, roster, registry)`` — same
spec + same roster + same registry always produces a byte-identical
:class:`ExecutionPlan`, independent of wall-clock time, dict-iteration order
(insertion-ordered by construction), or which thread calls it.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import dataclass
from typing import TypeVar

from docket.core import archetypes as _archetypes
from docket.core import pipeline as _pipeline

# ── Planning (pure, deterministic) ───────────────────────────────────────────


@dataclass(frozen=True)
class PlannedUnit:
    """One resolved, runnable step target — a role/agent, its gate, and overrides.

    ``member_id`` is the concrete agent id this step will run against, or
    ``None`` when the step targets a ``role`` the pod doesn't have (mirrors
    ``core/dispatch.py``'s existing ``pod_pipeline``, which already skips
    absent roles) — ``skipped`` is ``True`` in that case. A step targeting a
    specific ``agent`` id is never skipped by planning (whether that id
    actually belongs to this pod is an execution-time, no-cross-pod-dispatch
    concern, not a planning one).
    """

    step_id: str
    role: str | None
    agent: str | None
    archetype: str | None
    member_id: str | None
    gate: _pipeline.Gate | None
    retries: int | None
    timeout: int | None
    skipped: bool = False


@dataclass(frozen=True)
class PlannedGroup:
    """A ``parallel`` step: children run concurrently, joined before advancing."""

    step_id: str
    children: tuple[PlannedUnit, ...]


PlannedNode = PlannedUnit | PlannedGroup


def step_id_of(node: PlannedNode) -> str:
    """The step id of either node kind — the common key both share."""
    return node.step_id


@dataclass(frozen=True)
class ExecutionPlan:
    """The fully resolved, ready-to-run shape of a pipeline against one pod.

    ``nodes`` is top-level order (``parallel`` groups included as a single
    node); a role-targeted unit the pod doesn't have still appears, marked
    ``skipped`` — this is what lets ``docket pipeline plan`` show an operator
    *why* a step won't run, rather than silently omitting it.
    """

    pipeline_name: str
    nodes: tuple[PlannedNode, ...]

    def runnable_nodes(self) -> tuple[PlannedNode, ...]:
        """``nodes`` with skipped (role-absent) unit steps filtered out.

        This is the executor's actual walk order — a skipped unit consumes no
        pipeline position, exactly like ``pod_pipeline``'s pre-existing
        skip-absent-roles behavior.
        """
        return tuple(n for n in self.nodes if not (isinstance(n, PlannedUnit) and n.skipped))


def _gate_from_contract(gc: _archetypes.GateContract) -> _pipeline.Gate | None:
    """Translate an archetype's descriptive ``gateContract`` into a real Gate.

    ``verdict``'s marker order is the convention documented in
    ``role-archetypes.spec.md``: the first regex is the passing value, every
    other one just fails the step (no rework — a step wanting a bounded
    rework loop must declare its own ``VerdictGate`` with an explicit
    ``rework`` edge; an archetype's gate contract carries no rework data).
    """
    if gc.kind == "none":
        return None
    if gc.kind == "mechanical":
        return _pipeline.MechanicalGate(command=None)
    if gc.kind == "approval":
        return _pipeline.ApprovalGate()
    if gc.kind == "verdict":
        if not gc.regexes:
            return None
        pattern = r"^\s*(" + "|".join(gc.regexes) + r")\b"
        return _pipeline.VerdictGate(
            pattern=pattern,
            pass_values=[gc.regexes[0]],
            case_sensitive=False,
            rework=None,
        )
    return None  # pragma: no cover - GateContract's own __post_init__ forbids this


def resolve_gate(
    step: _pipeline.Step, registry: _archetypes.ArchetypeRegistry
) -> _pipeline.Gate | None:
    """The gate a step actually runs under (W-8's generalization point).

    A step's own declared ``gate`` always wins. Only when it omits one does
    this fall back to the resolved archetype's ``gateContract`` — looked up
    by ``step.archetype`` if set, else ``step.role`` (every built-in
    archetype's name equals its pod role name, so a plain ``role:
    implementer`` step with no ``gate``/``archetype`` of its own still
    resolves the implementer archetype's ``mechanical`` contract). No
    resolvable archetype (an unknown name, or a bare ``agent``-targeted step
    with neither ``role`` nor ``archetype`` set) means no gate — the step
    always advances, same as a plain hop today.
    """
    if step.gate is not None:
        return step.gate
    name = step.archetype or step.role
    if not name:
        return None
    arch = registry.get(name)
    if arch is None:
        return None
    return _gate_from_contract(arch.gate_contract)


def _resolve_unit(
    step: _pipeline.Step, roster: dict[str, str], registry: _archetypes.ArchetypeRegistry
) -> PlannedUnit:
    if step.agent is not None:
        member_id: str | None = step.agent
        skipped = False
    else:
        assert step.role is not None  # PipelineSpec's own validator guarantees this
        member_id = roster.get(step.role)
        skipped = member_id is None
    return PlannedUnit(
        step_id=step.id,
        role=step.role,
        agent=step.agent,
        archetype=step.archetype,
        member_id=member_id,
        gate=resolve_gate(step, registry),
        retries=step.retries,
        timeout=step.timeout,
        skipped=skipped,
    )


def resolve_plan(
    spec: _pipeline.PipelineSpec,
    roster: dict[str, str],
    *,
    registry: _archetypes.ArchetypeRegistry | None = None,
) -> ExecutionPlan:
    """Resolve *spec* against a pod's ``{role: member_id}`` roster.

    Pure and deterministic (see module docstring): no filesystem access, no
    wall-clock dependency, no sensitivity to which thread calls it. *roster*
    should already be role-order-stable (``core/dispatch.py``'s
    ``pod_pipeline`` already returns one first-member-per-role, in pipeline
    order) — this function does not itself impose an order beyond the
    spec's own ``steps`` order, which is fixed at parse time.
    """
    reg = registry if registry is not None else _archetypes.load_registry()
    nodes: list[PlannedNode] = []
    for step in spec.steps:
        if step.parallel:
            children = tuple(_resolve_unit(c, roster, reg) for c in step.parallel)
            nodes.append(PlannedGroup(step_id=step.id, children=children))
        else:
            nodes.append(_resolve_unit(step, roster, reg))
    return ExecutionPlan(pipeline_name=spec.name, nodes=tuple(nodes))


def render_plan(plan: ExecutionPlan) -> str:
    """Human-readable rendering of *plan* — the one and only ``docket pipeline
    plan`` renderer (no second pretty-printer; the CLI just prints this)."""
    lines = [f"Pipeline: {plan.pipeline_name}"]
    for node in plan.nodes:
        if isinstance(node, PlannedGroup):
            lines.append(f"  [{node.step_id}] parallel:")
            for child in node.children:
                lines.append(f"    - {_render_unit(child)}")
        else:
            prefix = "  (skipped — role not in pod) " if node.skipped else "  "
            lines.append(f"{prefix}[{node.step_id}] {_render_unit(node)}")
    return "\n".join(lines)


def _render_unit(unit: PlannedUnit) -> str:
    target = unit.agent if unit.agent is not None else f"role={unit.role}"
    who = unit.member_id or "(unresolved)"
    gate_label = _gate_label(unit.gate)
    return f"{target} -> {who} [gate: {gate_label}]"


def _gate_label(gate: _pipeline.Gate | None) -> str:
    if gate is None:
        return "none"
    if isinstance(gate, _pipeline.MechanicalGate):
        return f"mechanical({gate.command or 'verifyCmd'})"
    if isinstance(gate, _pipeline.VerdictGate):
        rework = f", rework->{gate.rework.to}" if gate.rework else ""
        return f"verdict({'|'.join(gate.pass_values)}{rework})"
    if isinstance(gate, _pipeline.ApprovalGate):
        return "approval"
    return "unknown"  # pragma: no cover - Gate is a closed discriminated union


# ── Verdict parsing (generic — any archetype's marker vocabulary) ───────────


def normalize_values(values: list[str], case_sensitive: bool) -> frozenset[str]:
    """Case-normalize a verdict gate's ``pass_values``/``rework.when`` list for
    membership testing, matching :func:`parse_verdict`'s own normalization."""
    return frozenset(values) if case_sensitive else frozenset(v.lower() for v in values)


def parse_verdict(gate: _pipeline.VerdictGate, output: str) -> str | None:
    """First non-blank line of *output* matched against *gate*.pattern.

    Returns the normalized (lowercased unless ``case_sensitive``) marker
    value on a match, or ``None`` if unparseable — generalizes
    ``core/dispatch.py``'s pre-W-8 ``_parse_reviewer_verdict``/
    ``_parse_tester_verdict`` to an arbitrary pattern/marker vocabulary.
    Exactly one line is ever consulted (the first non-blank one); a
    non-match there is unparseable, never a reason to keep scanning.
    """
    flags = 0 if gate.case_sensitive else re.IGNORECASE
    compiled = re.compile(gate.pattern, flags)
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = compiled.match(stripped)
        if not match:
            return None
        value = match.group(1)
        return value if gate.case_sensitive else value.lower()
    return None


# ── Parallel group execution: bounded pool, join semantics ──────────────────

T = TypeVar("T")

#: Default cap on concurrently-running children of one ``parallel`` group.
#: Hops are subprocess-bound (each is a real agent-turn subprocess), so this
#: is a real resource bound, not just a code-tidiness knob.
DEFAULT_MAX_PARALLEL_WORKERS = 4

# Trace writes from concurrent group children land on the same per-task
# tracefile (one session id per task) — core/trace.py's append is not itself
# filelocked (it is exempt from edges/store.py's D-12 rule as an append-only
# log), so concurrent same-file writers need this to stay non-interleaved.
trace_write_lock = threading.Lock()


def run_group(
    children: tuple[PlannedUnit, ...],
    run_one: Callable[[PlannedUnit], T],
    *,
    max_workers: int = DEFAULT_MAX_PARALLEL_WORKERS,
) -> list[T]:
    """Run *children* concurrently via a bounded thread pool; join before returning.

    Returns results in *children*'s declaration order (not completion order)
    — callers fold them back into a task's persisted ``hops[]`` in a
    deterministic order regardless of which child happened to finish first.
    ``contextvars.copy_context()`` is propagated into each worker explicitly
    (``ThreadPoolExecutor.submit`` does not do this on its own) so a
    context-local like "which run id is this dispatch executing under" (see
    ``core/runs.py``'s cancellation support) still applies inside a fan-out.

    If any child raises, every other child is still joined (never leaving a
    sibling's subprocess orphaned mid-run) before the first exception is
    re-raised.
    """
    if not children:
        return []
    ctx = copy_context()
    results: list[T | None] = [None] * len(children)
    errors: list[BaseException] = []
    workers = max(1, min(max_workers, len(children)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_index = {pool.submit(ctx.run, run_one, c): i for i, c in enumerate(children)}
        for fut in as_completed(future_to_index):
            i = future_to_index[fut]
            try:
                results[i] = fut.result()
            except BaseException as exc:  # re-raised below, after every child is joined
                errors.append(exc)
    if errors:
        raise errors[0]
    return list(results)  # type: ignore[arg-type]  # every slot filled, or an error was raised
