"""In-place ephemeral pods: run one recipe against one codebase, for one task.

``run_recipe_task`` provisions a throwaway pod whose Implementer works in the codebase itself
(no git worktree), applies a recipe the way ``docket pod <p> apply`` does, pins every member to
one model, sets the pod's approval mode and ``requireVerify`` through the typed ``PodSettings``
writer, then dispatches exactly that one task. When the task parks on an operator question and
the caller supplies a ``next_answer`` source, the answer is resolved through
``core.answers.answer_task`` and the task is re-dispatched from its own route. Core only: no
printing, no subprocess, no ``ui`` import.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from docket.core import answers as _answers
from docket.core import blueprints as _bp
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import harness, pod
from docket.core import pod_apply as _pod_apply
from docket.core import pod_provisioning as _pp
from docket.core import provisioning as _prov

AnswerSource = Callable[[dict[str, Any]], harness.Answer | None]


class RecipeRunError(RuntimeError):
    """The in-place run was refused before any pod was provisioned."""


@dataclass(frozen=True)
class RecipeRun:
    """The persisted outcome of one in-place run: the pod id, the task's record as
    stored after the last dispatch, and one serialized record per hop that ran."""

    project: str
    task: dict[str, Any]
    hops: list[dict[str, Any]] = field(default_factory=list)


def _new_project_id() -> str:
    return _prov.validate_project_id(f"h-{uuid.uuid4().hex[:8]}")


def _pin_members(project: str, model: str) -> None:
    for member_id in _pp.pod_member_ids(project):
        _fleet.set_model_both(member_id, model)


def _task_record(project: str, task_id: str) -> dict[str, Any]:
    return next(t for t in _dispatch.read_tasks(project) if t["id"] == task_id)


def run_recipe_task(
    workspace: Path,
    recipe: str,
    task: str,
    *,
    model: str,
    approval_mode: Literal["wait", "park", "refuse"],
    timeout: int,
    verify_cmd: str = "",
    next_answer: AnswerSource | None = None,
) -> RecipeRun:
    """Provision an in-place pod on *workspace*, apply *recipe*, and run *task* to settled."""
    # Bad inputs refuse before any pod exists (RecipeRunError, PodSettingsError,
    # PodApplyError, VerifyCmdError); a pod that fails later is left in place for inspection.
    if not workspace.is_dir():
        raise RecipeRunError(f"workspace is not a directory: {workspace}")
    approval_value = pod.PodSettings.coerce("approvalMode", approval_mode)
    verify = _pp.validate_verify_cmd(verify_cmd) if verify_cmd else ""
    recipe_dir = _pod_apply.resolve_recipe(recipe)

    project = _new_project_id()
    _pp.provision_pod(
        project,
        _bp.DEFAULT_BLUEPRINT,
        location=str(workspace),
        source="in-place",
        in_place=True,
        verify_cmd=verify,
    )
    _pod_apply.apply(_pod_apply.plan_apply(project, recipe_dir))
    _pin_members(project, model)

    lead_id = pod.member_id(project, "lead")
    _fleet.meta_set(lead_id, "approvalMode", approval_value)
    _fleet.meta_set(lead_id, "requireVerify", pod.PodSettings.coerce("requireVerify", "true"))

    queued = _dispatch.enqueue_task(project, task)
    task_id = str(queued["id"])
    _dispatch.dispatch_pod(project, turn_timeout=timeout, max_tasks=1)
    record = _task_record(project, task_id)
    while next_answer is not None and record.get("status") == "waiting_input":
        answer = next_answer(record.get("question") or {})
        if answer is None:
            break
        try:
            _answers.answer_task(
                project, task_id, answer.action, answer.content, channel="harness", actor="harness"
            )
        except (_answers.AnswerError, _answers.AnswerRejected):
            break
        _dispatch.dispatch_pod(project, turn_timeout=timeout, max_tasks=1)
        record = _task_record(project, task_id)
    hops = [dict(h) for h in record.get("hops", [])]
    return RecipeRun(project=project, task=record, hops=hops)
