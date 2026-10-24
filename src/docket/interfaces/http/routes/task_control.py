"""Acting on one task: cancel, retry, answer a parked question, pre-grant a command."""

from __future__ import annotations

import json

from docket.hops.application import answers as _answers
from docket.hops.application import interruptions as _interruptions
from docket.interfaces.http.exchange import HttpExchange
from docket.operator import task_view
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import task as _task


def post_task_cancel(h: HttpExchange, rest: str) -> None:
    """`POST /tasks/<pod>/<id>/cancel`; body optional `{"reason"?, "actor"?}`."""
    project, _, task_id = rest.partition("/")
    if h._reject_bad_project_id(project):
        return
    body = h._read_json_object()
    if body is None:
        return
    reason, actor = body.get("reason"), body.get("actor")
    try:
        outcome = _lifecycle.cancel_task(
            project,
            task_id,
            channel="http",
            actor=actor if isinstance(actor, str) and actor else "http",
            reason=reason if isinstance(reason, str) else "",
        )
    except _task.TaskNotFoundError as exc:
        h._send_json_error(str(exc), 404)
        return
    if not outcome.cancelled:
        h._send_json_error(f"task {task_id} is {outcome.status}; nothing to cancel", 409)
        return
    h._send_json({"ok": True, "task": task_id, "status": outcome.status})


def post_task_retry(h: HttpExchange, rest: str) -> None:
    """`POST /tasks/<pod>/<id>/retry`: a `blocked` or `failed` task flips to `pending`."""
    project, _, task_id = rest.partition("/")
    if h._reject_bad_project_id(project):
        return
    task = next((t for t in TaskRepository.for_pod(project).list() if t.id == task_id), None)
    if task is None:
        h._send_json_error(f"task {task_id!r} not found in pod {project!r}", 404)
        return
    if not _lifecycle.retry_task(project, task_id):
        h._send_json_error(
            f"task {task_id} is {task.status}; only failed or blocked tasks retry", 409
        )
        return
    h._send_json({"ok": True, "task": task_id, "status": "pending"})


def post_task_answer(h: HttpExchange, task_id: str) -> None:
    """`POST /tasks/<id>/answer` -- the HTTP counterpart of `docket task answer`.
    Body: `{"pod", "action", "content"?, "actor"?}`; `actor` is a label only, and the
    channel is always `"http"`."""
    if not task_id:
        h._send_json_error("Missing task id", 400)
        return
    body = h._read_json_object()
    if body is None:
        return

    project = body.get("pod")
    if not isinstance(project, str) or not project:
        h._send_json_error("pod is required", 400)
        return
    if h._reject_bad_project_id(project):
        return
    action = body.get("action")
    if not isinstance(action, str) or not action:
        h._send_json_error("action is required", 400)
        return
    content = body.get("content")
    if content is not None and not isinstance(content, dict):
        h._send_json_error("content must be an object", 400)
        return
    actor_raw = body.get("actor")
    actor = actor_raw if isinstance(actor_raw, str) and actor_raw else "http"

    try:
        _answers.answer_task(project, task_id, action, content, channel="http", actor=actor)
    except _answers.AnswerRejected as exc:
        h._send_json_error(f"blocked by policy '{exc.policy_id}'", 422)
        return
    except _answers.AnswerError as exc:
        msg = str(exc)
        if "not found in pod" in msg:
            h._send_json_error(msg, 404)
        elif "is not waiting_input" in msg or "is not parked at step" in msg:
            h._send_json_error(msg, 409)
        else:
            h._send_json_error(msg, 422)
        return

    task = next((t for t in TaskRepository.for_pod(project).list() if t.id == task_id), None)
    if task is None:
        # Answered, then vanished from its own pod's queue before this read — not
        # expected in practice (nothing deletes a task), but report it honestly
        # rather than crash rendering a view for it.
        h._send_json_error(f"task {task_id!r} not found after answering", 500)
        return
    view = task_view(project, task.model_dump(by_alias=True, mode="json")).model_dump(
        by_alias=True, mode="json"
    )
    h._send(json.dumps(view).encode(), "application/json")


def post_task_pregrant(h: HttpExchange, task_id: str) -> None:
    """`POST /tasks/<id>/pregrants` -- the HTTP counterpart of `docket task approve --for`.
    Body: `{"pod", "command", "tool"?, "actor"?}`; the channel is always `"http"`."""
    if not task_id:
        h._send_json_error("Missing task id", 400)
        return
    body = h._read_json_object()
    if body is None:
        return

    project = body.get("pod")
    if not isinstance(project, str) or not project:
        h._send_json_error("pod is required", 400)
        return
    if h._reject_bad_project_id(project):
        return
    command = body.get("command")
    if not isinstance(command, str) or not command.strip():
        h._send_json_error("command is required", 400)
        return
    tool_raw = body.get("tool")
    tool = tool_raw if isinstance(tool_raw, str) and tool_raw else "bash"
    actor_raw = body.get("actor")
    actor = actor_raw if isinstance(actor_raw, str) and actor_raw else "http"

    try:
        token = _interruptions.record_pregrant(
            project, task_id, command, tool=tool, channel="http", actor=actor
        )
    except _interruptions.InterruptionsError as exc:
        h._send_json_error(str(exc), 404)
        return

    resp = {"ok": True, "token": token, "task": task_id, "pod": project}
    h._send(json.dumps(resp).encode(), "application/json")
