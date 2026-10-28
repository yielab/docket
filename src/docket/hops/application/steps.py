from __future__ import annotations

import datetime as _dt
import hashlib as _hashlib
import json as _json
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import ValidationError as _ValidationError

import docket.kernel.templates as _templates
from docket.governance import secrets as _secrets
from docket.governance import security as _sec
from docket.hops.application.compose import _brief_from_step, _brief_questions_schema, _gate_report
from docket.hops.application.runner import when_cwd
from docket.hops.gates.post_hop import _match_on_route, _run_in_envelope, _task_command_env
from docket.hops.gates.pre_hop import _gate_pre_hop_approval, _unpriced
from docket.kernel import clock as _clock
from docket.kernel import operator_contract as _oc
from docket.kernel.errors import DispatchError, InvalidInput
from docket.kernel.home import current_home
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import escalations as _escalations
from docket.tasks.application.record import UnitContext, UnitOutcome, trace_locked
from docket.tasks.domain import state as _state
from docket.tasks.domain.task import HopResult, TaskRecord, TaskRunRefusal
from docket.teams import autonomy as _autonomy
from docket.teams import blueprints as _blueprints
from docket.teams import fleet as _fleet
from docket.teams import model_selection as _models_policy
from docket.teams import pod as _pod
from docket.teams.pod import TASK_PIPELINE_NAME
from docket.teams.settings import (
    load_pod_settings,
    pod_approval_mode,
    pod_budget,
    pod_max_rework_cycles,
)

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
    settings = load_pod_settings(project)
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
    "Pipeline order and participation"). Public so ``interfaces/cli/commands/pod_config.py`` renders
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


def _task_pipeline_file(project: str, name: str) -> tuple[Path, str] | None:
    """The file and source label *name* resolves to: the first of ``Home.scopes("pipelines")``
    (the pod overlay, then the operator's ``config/pipelines``) holding it, then a recipe (the
    operator's before the shipped ones) holding a ``pipeline.yaml``."""
    labels = ("pod", "operator", "shipped")
    for label, directory in zip(labels, current_home().scopes("pipelines", project), strict=False):
        for suffix in (".yaml", ".yml"):
            if (directory / f"{name}{suffix}").is_file():
                return directory / f"{name}{suffix}", f"{label}:{name}"
    for root in (current_home().user_recipes_dir, _templates.RECIPES_DIR):
        if (root / name / "pipeline.yaml").is_file():
            return root / name / "pipeline.yaml", f"recipe:{name}"
    return None


def _task_pipeline(
    project: str,
    task: TaskRecord,
    default_spec: _pipeline.PipelineSpec,
    default_source: str = "default",
) -> tuple[_pipeline.PipelineSpec, str]:
    """The (spec, source) a claimed task runs: its named pipeline, else the caller's file, else
    the ``pipelineSpec`` it kept at an earlier claim, else the pod's *default_spec*. Raises
    ``TaskRunRefusal`` for one that resolves to nothing valid."""
    name = task.pipeline
    if name is None or name == "":
        kept = task.pipeline_spec
        if kept is None or default_source == "file":
            return default_spec, default_source
        try:
            return _pipeline.PipelineSpec.model_validate(kept), "file"
        except ValueError as exc:
            raise TaskRunRefusal(f"the task's kept pipeline does not validate: {exc}") from exc
    if not TASK_PIPELINE_NAME.match(name):
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


def _task_gate(task: TaskRecord) -> _gates.ExternalGate | None:
    """The ``ExternalGate`` a task's ``gate`` object describes, or ``None`` for no gate. ``map``
    moves the named exit codes onto their label over the default 0/1/2 mapping."""
    raw = task.gate
    if raw is None:
        return None
    exit_map: dict[str, list[int]] = {"pass": [0], "fail": [1], "needs_human": [2]}
    try:
        for code_text, label in (raw.exit_map or {}).items():
            if label not in exit_map:
                raise InvalidInput(f"unknown label {label!r}")
            code = int(code_text)
            for codes in exit_map.values():
                if code in codes:
                    codes.remove(code)
            exit_map[label].append(code)
        return _gates.ExternalGate(command=raw.command, timeout=raw.timeout_s, exit_map=exit_map)
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
    ctx: UnitContext,
    node: _orch.PlannedUnit,
    prior: list[HopResult],
    index_for_context: int,
) -> UnitOutcome:
    """Run *node*'s ``run`` command directly -- no agent turn, no session. Classified like
    any shell-out first: ``allow`` runs it, anything else gates like an ``approval`` step
    (or fails outright under ``approvalMode: refuse``). See pod-dispatch.spec.md."""
    # `park` gates the same non-blocking way `wait` does here -- a command step never
    # reaches the in-turn tool chokepoint a park-mode call would need to record, so there
    # is nothing to park.
    assert node.run is not None
    role = node.step_id
    cmd = node.run
    settings = load_pod_settings(ctx.project)
    verdict = _sec.classify_command(cmd, extra_bins=frozenset(settings.allow_commands))
    if verdict.action != "allow":
        level = _autonomy.effective_level(ctx.project, ctx.task.autonomy)
        by_level = _autonomy.table_denies_approval(ctx.project, level)
        if by_level or (
            pod_approval_mode(ctx.project, caller_default=ctx.approval_default) == "refuse"
        ):
            if by_level:
                _escalations.decided_approval(
                    pod=ctx.project,
                    role=role,
                    task_id=ctx.task_id,
                    caused_by=node.step_id,
                    prompt=f"command step {node.step_id!r}: {cmd}",
                    step=node.step_id,
                )
            trace_locked(
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
            return UnitOutcome(
                kind="failed",
                hops=[hop],
                reason=f"command step {node.step_id!r} refused: {verdict.reason}",
                failure_kind=_state.FailureKind.needs_human if by_level else "",
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

    cwd = when_cwd(ctx, prior)
    timeout = node.timeout or ctx.resolved_verify_timeout
    code, raw_output = _run_in_envelope(
        ctx.project, "run", cmd, cwd, timeout, env=_task_command_env(ctx, prior, node.env)
    )
    passed = code == 0
    redacted = _secrets.redact(raw_output)
    trace_locked(
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
        return UnitOutcome(kind="routed", hops=[hop], label=label)
    if not passed:
        return UnitOutcome(
            kind="failed",
            hops=[hop],
            reason=f"command step {node.step_id!r} failed: {cmd!r}",
            label=label,
        )
    return UnitOutcome(kind="advance", hops=[hop], label=label)


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
    ctx: UnitContext,
    node: _orch.PlannedUnit,
    prior: list[HopResult],
    index_for_context: int,
) -> UnitOutcome:
    """Park the task for an operator question minted from *node.input* -- its ``input`` escalation
    -- and stop ``waiting_input``; no hop is persisted for this attempt. The answer is applied by
    the next claim (``hops.application.resolutions``). See pod-dispatch.spec.md."""
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
    escalation = _escalations.open_for_question(
        question, kind="input", role="", caused_by=node.step_id
    )
    return UnitOutcome(
        kind="waiting_input",
        reason=f"awaiting operator answer for step {node.step_id!r} (escalation={escalation.id})",
    )
