"""Acting on one task: cancel, retry, pre-grant a command."""

from __future__ import annotations

import json

from docket.hops.application import interruptions as _interruptions
from docket.interfaces.http.exchange import HttpExchange
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


def post_task_pregrant(h: HttpExchange, task_id: str) -> None:
    """`POST /tasks/<id>/pregrants` -- the HTTP counterpart of `docket task pregrant`.
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
