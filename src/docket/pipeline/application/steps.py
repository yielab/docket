from __future__ import annotations

import datetime as _dt
import hashlib as _hashlib
import json as _json
import re as _re
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import ValidationError as _ValidationError

import docket.kernel.templates as _templates
from docket.governance import security as _sec
from docket.hops.application.compose import _brief_from_step, _brief_questions_schema, _gate_report
from docket.hops.application.record import _trace_locked, _UnitContext, _UnitOutcome
from docket.hops.application.runner import _when_cwd
from docket.hops.gates.post_hop import _match_on_route, _run_in_envelope, _task_command_env
from docket.hops.gates.pre_hop import _gate_pre_hop_approval, _unpriced
from docket.kernel import clock as _clock
from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.models import selection as _models_policy
from docket.observability import trace as _trace
from docket.operator import contract as _oc
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.domain.task import DispatchError, HopResult, TaskRunRefusal
from docket.teams import blueprints as _blueprints
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams.settings import (
    _pod_settings,
    pod_approval_mode,
    pod_budget,
    pod_max_rework_cycles,
)

# Only roles the pod actually has run — lean pod (lead + implementer) = 2 hops; full pod = 4.
PIPELINE_ORDER: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")


def pod_pipeline(project: str) -> list[tuple[str, str]]:
    """Present pod roles in pipeline order, as ``(role, member_id)``; raises DispatchError
    with no Lead. Duplicate implementers collapse to the first (one doer per role).
    """
    all_ids = [a.id for a in _fleet.list_agents()]
    members = _pod.members_of(all_ids, project)
    if not members:
        raise DispatchError(f"no pod found for '{project}'")
    by_role: dict[str, str] = {}
    for mid, role, _idx in members:
        by_role.setdefault(role, mid)  # first member of each role wins
    if "lead" not in by_role:
        raise DispatchError(f"pod '{project}' has no lead — cannot dispatch")
    return [(role, by_role[role]) for role in PIPELINE_ORDER if role in by_role]


_BOUND_PIPELINE_SOURCE_PREFIX = "bound pipeline"


# Fails loud on a missing/unreadable copy, a hash mismatch (the copy changed on disk since
# it was bound), or a copy that no longer validates -- never a silent fall back to the
# blueprint/built-in pipeline (see pod-dispatch.spec.md, "Pipeline order and participation").
def _bound_pipeline(project: str, pipeline_hash: str) -> _pipeline.PipelineSpec:
    """Load this pod's bound pipeline copy, verified against *pipeline_hash*
    (the Lead's stored ``PodSettings.pipeline`` digest)."""
    path = _pod.bound_pipeline_path(project)
    rebind_hint = f"rebind with 'docket pod set pipeline <file> --pod {project}'"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DispatchError(
            f"pod '{project}' has a bound pipeline (hash {pipeline_hash[:12]}...) but its "
            f"stored copy at {path} is unreadable ({exc}) -- {rebind_hint}"
        ) from exc
    actual_hash = _hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual_hash != pipeline_hash:
        raise DispatchError(
            f"pod '{project}'s bound pipeline copy at {path} no longer matches its recorded "
            f"hash (expected {pipeline_hash[:12]}..., found {actual_hash[:12]}...) -- {rebind_hint}"
        )
    result = _pipeline.load_pipeline(text)
    if result.spec is None:
        raise DispatchError(
            f"pod '{project}'s bound pipeline copy at {path} no longer validates: "
            f"{'; '.join(result.errors)} -- {rebind_hint}"
        )
    return result.spec


# Resolution order: this pod's bound pipeline (PodSettings.pipeline) -> the Lead's
# ``blueprint`` meta's default_pipeline -> the built-in default. *source* is the
# human-readable label ``docket pod plan`` names ("bound pipeline (hash ...)",
# "blueprint '<name>'", or "built-in default" -- see pod-dispatch.spec.md, "Pipeline order
# and participation").
def _blueprint_pipeline(project: str) -> tuple[_pipeline.PipelineSpec, str]:
    """The resolved (spec, source) base pipeline for a caller-supplied-spec-free
    dispatch -- see the comment above for the resolution order."""
    settings = _pod_settings(project)
    if settings.pipeline:
        spec = _bound_pipeline(project, settings.pipeline)
        return spec, f"{_BOUND_PIPELINE_SOURCE_PREFIX} (hash {settings.pipeline[:12]}...)"
    lead_id = _pod.member_id(project, "lead")
    name = _fleet.meta_get(lead_id, "blueprint", "")
    if name:
        try:
            return _blueprints.get_blueprint(name).default_pipeline, f"blueprint '{name}'"
        except _blueprints.BlueprintError:
            pass  # absent/unknown blueprint -- fall through to the built-in default
    builtin = _pipeline.load_pipeline(None).spec
    assert builtin is not None  # load_pipeline(None) always succeeds
    return builtin, "built-in default"


def effective_pipeline_source(project: str) -> str:
    """The source label ``effective_pipeline(project, None)`` would resolve to
    -- see ``_blueprint_pipeline``; a caller-supplied ``--file`` never reaches this."""
    return _blueprint_pipeline(project)[1]


# A caller-supplied *spec* is never patched. A pod's bound pipeline is caller-supplied-like
# and is also never patched -- its own rework config wins, matching today's ``--file``
# semantics, since an operator who hand-wrote a custom rework edge did not ask for the pod's
# ``maxReworkCycles`` to override it. Only the blueprint/built-in default gets the patch.
def effective_pipeline(project: str, spec: _pipeline.PipelineSpec | None) -> _pipeline.PipelineSpec:
    """The PipelineSpec this dispatch actually runs (see pod-dispatch.spec.md,
    "Pipeline order and participation"). Public so ``cli/_pipeline.py`` renders
    this same resolved spec."""
    if spec is not None:
        return spec
    builtin, source = _blueprint_pipeline(project)
    if source.startswith(_BOUND_PIPELINE_SOURCE_PREFIX):
        return builtin
    configured = pod_max_rework_cycles(project)
    new_steps = []
    changed = False
    for step in builtin.steps:
        gate = step.gate
        if (
            isinstance(gate, _gates.VerdictGate)
            and gate.rework is not None
            and gate.rework.max_cycles != configured
        ):
            new_rework = gate.rework.model_copy(update={"max_cycles": configured})
            step = step.model_copy(update={"gate": gate.model_copy(update={"rework": new_rework})})
            changed = True
        new_steps.append(step)
    return builtin.model_copy(update={"steps": new_steps}) if changed else builtin


TASK_PIPELINE_NAME = _re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _task_pipeline_file(project: str, name: str) -> tuple[Path, str] | None:
    """The file and source label *name* resolves to: the pod's ``pipelines/`` directory, then a
    recipe (the operator's before the shipped ones) holding a ``pipeline.yaml``."""
    pod_dir = current_home().pod_config_dir(project) / "pipelines"
    for suffix in (".yaml", ".yml"):
        if (pod_dir / f"{name}{suffix}").is_file():
            return pod_dir / f"{name}{suffix}", f"pod:{name}"
    for root in (current_home().user_recipes_dir, _templates.RECIPES_DIR):
        if (root / name / "pipeline.yaml").is_file():
            return root / name / "pipeline.yaml", f"recipe:{name}"
    return None


def _task_pipeline(
    project: str, task: dict[str, Any], default_spec: _pipeline.PipelineSpec
) -> tuple[_pipeline.PipelineSpec, str]:
    """The (spec, source) a claimed task runs: its named pipeline, else *default_spec* with
    source ``default``. Raises ``TaskRunRefusal`` for a name that resolves to nothing valid."""
    name = task.get("pipeline")
    if name is None or name == "":
        return default_spec, "default"
    if not isinstance(name, str) or not TASK_PIPELINE_NAME.match(name):
        raise TaskRunRefusal(f"pipeline {name!r} is not a valid pipeline name")
    found = _task_pipeline_file(project, name)
    if found is None:
        raise TaskRunRefusal(
            f"unknown pipeline {name!r}: pod {project!r} has no pipelines/{name}.yaml "
            "and no recipe of that name carries a pipeline.yaml"
        )
    path, source = found
    try:
        loaded = _pipeline.load_pipeline(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TaskRunRefusal(f"pipeline {name!r} ({source}) is unreadable: {exc}") from exc
    if loaded.spec is None:
        raise TaskRunRefusal(
            f"pipeline {name!r} ({source}) does not validate: {'; '.join(loaded.errors)}"
        )
    return loaded.spec, source


def _task_gate(task: dict[str, Any]) -> _gates.ExternalGate | None:
    """The ``ExternalGate`` a task's ``gate`` object describes, or ``None`` for no gate. ``map``
    moves the named exit codes onto their label over the default 0/1/2 mapping."""
    raw = task.get("gate")
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("command"), str):
        raise TaskRunRefusal("task gate must be an object with a string 'command'")
    exit_map: dict[str, list[int]] = {"pass": [0], "fail": [1], "needs_human": [2]}
    mapping = raw.get("map") or {}
    try:
        for code_text, label in dict(mapping).items():
            if label not in exit_map:
                raise InvalidInput(f"unknown label {label!r}")
            code = int(code_text)
            for codes in exit_map.values():
                if code in codes:
                    codes.remove(code)
            exit_map[label].append(code)
        return _gates.ExternalGate(
            command=raw["command"], timeout=raw.get("timeoutS"), exit_map=exit_map
        )
    except (TypeError, ValueError, _ValidationError) as exc:
        raise TaskRunRefusal(f"task gate is invalid: {exc}") from exc


def _task_gate_step_id(nodes: tuple[_orch.PlannedNode, ...]) -> str | None:
    """The step a task gate follows: the last ``implementer`` unit, else the last unit that runs
    an agent turn (a ``run`` or ``input`` step never takes it)."""
    units = [u for n in nodes for u in (n.children if isinstance(n, _orch.PlannedGroup) else (n,))]
    turns = [u for u in units if u.run is None and u.input is None]
    chosen = [u for u in turns if u.role == "implementer"] or turns
    return chosen[-1].step_id if chosen else None


def unpriced_budget_models(project: str) -> list[str]:
    """The models a budgeted pod runs that its cap cannot price: its members' models and its
    pipeline's step models. Empty when the pod has no budget."""
    if pod_budget(project) <= 0.0:
        return []
    ids = [a.id for a in _fleet.list_agents()]
    models = {
        str(_fleet.meta_get(mid, "model", "") or current_home().default_model)
        for mid, _role, _idx in _pod.members_of(ids, project)
    }
    steps = list(effective_pipeline(project, None).steps)
    while steps:
        step = steps.pop()
        steps.extend(step.parallel or [])
        if step.model:
            try:
                models.add(_models_policy.resolve_step_model(step.model))
            except ValueError:
                models.add(step.model)
    return sorted(m for m in models if _unpriced(m))


def _run_command_step(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    prior: list[HopResult],
    index_for_context: int,
) -> _UnitOutcome:
    """Run *node*'s ``run`` command directly -- no agent turn, no session. Classified like
    any shell-out first: ``allow`` runs it, anything else gates like an ``approval`` step
    (or fails outright under ``approvalMode: refuse``). See pod-dispatch.spec.md."""
    # `park` gates the same non-blocking way `wait` does here -- a command step never
    # reaches the in-turn tool chokepoint a park-mode call would need to record, so there
    # is nothing to park.
    assert node.run is not None
    role = node.step_id
    cmd = node.run
    settings = _pod_settings(ctx.project)
    verdict = _sec.classify_command(cmd, extra_bins=frozenset(settings.allow_commands))
    if verdict.action != "allow":
        if pod_approval_mode(ctx.project, caller_default=ctx.approval_default) == "refuse":
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "command_step",
                _json.dumps({"step": node.step_id, "cmd": cmd, "exit": None}),
            )
            hop = HopResult(
                role=role,
                member_id="",
                ok=False,
                output="",
                error=f"command step refused: {verdict.reason}",
                step_id=node.step_id,
            )
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason=f"command step {node.step_id!r} refused: {verdict.reason}",
            )
        # "wait" (the default): gate exactly like a pipeline `approval` step, keyed on
        # this exact pipeline position -- a granted single-use override lets a resumed
        # run fall through here without asking again.
        approval_node = replace(node, gate=_gates.ApprovalGate(message=verdict.reason))
        approval_outcome = _gate_pre_hop_approval(
            ctx, role, approval_node, check_approval=True, index_for_context=index_for_context
        )
        if approval_outcome is not None:
            return approval_outcome

    cwd = _when_cwd(ctx, prior)
    timeout = node.timeout or ctx.resolved_verify_timeout
    code, raw_output = _run_in_envelope(
        ctx.project, "run", cmd, cwd, timeout, env=_task_command_env(ctx, prior, node.env)
    )
    passed = code == 0
    redacted = _trace.redact(raw_output)
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "command_step",
        _json.dumps({"step": node.step_id, "cmd": cmd, "exit": 0 if passed else 1}),
    )
    hop = HopResult(role=role, member_id="", ok=passed, output=redacted, step_id=node.step_id)
    if ctx.on_hop is not None:
        ctx.on_hop(hop)
    label = _command_outcome_label(raw_output, passed)
    if _match_on_route(node.on, label) is not None:
        return _UnitOutcome(kind="routed", hops=[hop], label=label)
    if not passed:
        return _UnitOutcome(
            kind="failed",
            hops=[hop],
            reason=f"command step {node.step_id!r} failed: {cmd!r}",
            label=label,
        )
    return _UnitOutcome(kind="advance", hops=[hop], label=label)


def _command_outcome_label(output: str, passed: bool) -> str:
    """A command step's outcome label for its ``on:`` map: the last output line when it is a
    single upper-case token (``PASS``, ``NEEDS-REVIEW``), else ``pass``/``fail`` by exit."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if lines:
        last = lines[-1]
        if " " not in last and last.upper() == last and any(c.isalpha() for c in last):
            return last
    return "pass" if passed else "fail"


_DEFAULT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def _run_input_step(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    prior: list[HopResult],
    index_for_context: int,
) -> _UnitOutcome:
    """Park the task for an operator question minted from *node.input*, trace
    ``input_requested``, and stop ``waiting_input`` -- no hop persisted for this attempt.
    Resumed only by ``tasks.application.answers.answer_task``. See pod-dispatch.spec.md."""
    assert node.input is not None
    spec = node.input
    # When the `from` step's latest hop carries a Lead intake brief with its own
    # `questions`, the minted question asks those specific questions instead of one
    # generic free-text answer (pod-dispatch.spec.md, "Task brief").
    brief = _brief_from_step(prior, spec.from_)
    if brief is not None and brief.questions:
        message = f"The Lead needs answers before starting: {brief.objective}"
        requested_schema = _brief_questions_schema(brief.questions)
    else:
        message = spec.message.strip() or f"Operator input requested (from step {spec.from_!r})."
        requested_schema = dict(_DEFAULT_INPUT_SCHEMA)
    report = _gate_report(prior, spec.from_)
    if report:
        message = f"{message}\n\nThe gate on step {spec.from_!r} reported:\n{report}"
    expires_at: str | None = None
    if spec.expires_hours is not None:
        expires_at = (_clock.now() + _dt.timedelta(hours=spec.expires_hours)).isoformat()
    question = _oc.Question(
        id=_oc.new_question_id(),
        task_id=ctx.task_id,
        pod=ctx.project,
        step=node.step_id,
        message=message,
        requested_schema=requested_schema,
        created_at=_clock.iso(),
        expires_at=expires_at,
    )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        node.step_id,
        "input_requested",
        _json.dumps({"task": ctx.task_id, "step": node.step_id, "questionId": question.id}),
    )
    return _UnitOutcome(
        kind="waiting_input",
        reason=f"awaiting operator answer for step {node.step_id!r} (question={question.id})",
        question=question.model_dump(by_alias=True),
    )
