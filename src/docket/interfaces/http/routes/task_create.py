"""``POST /tasks/<pod>`` -- enqueue one task, exactly once per idempotency key."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from docket.interfaces.http.exchange import HttpExchange
from docket.kernel import brief as _brief
from docket.kernel.errors import DispatchError
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import task as _task
from docket.tasks.domain.state import Status

# POST /tasks body name -> enqueue_task_once option, for the addressable-task fields.
_TASK_OPTION_FIELDS: tuple[tuple[str, str], ...] = (
    ("external_ref", "externalRef"),
    ("idempotency_key", "idempotencyKey"),
    ("base_ref", "baseRef"),
    ("pipeline", "pipeline"),
    ("gate", "gate"),
    ("max_tokens", "maxTokens"),
    ("prepare", "prepare"),
    ("restrictions", "restrictions"),
    ("autonomy", "autonomy"),
)


def post_task(h: HttpExchange, project: str) -> None:
    if not project:
        h._send_json_error("Missing project", 400)
        return
    if h._reject_bad_project_id(project):
        return
    task_body = h._read_json_object()
    if task_body is None:
        return

    description = task_body.get("description", "")
    if not isinstance(description, str) or not description:
        h._send_json_error("description is required", 400)
        return
    priority_raw = task_body.get("priority", "normal")
    priority = str(priority_raw) if priority_raw else "normal"
    # `trusted` (optional) overrides the `pre_input` policy check's trust
    # flag for this enqueue only — see tasks.application.queue.enqueue_task_once. Absent
    # (None) leaves every existing caller's behaviour byte-for-byte
    # unchanged; this is the only place that field is threaded through.
    trusted_raw = task_body.get("trusted")
    trusted = bool(trusted_raw) if trusted_raw is not None else None

    # `brief` (optional): a `TaskBrief` document, the HTTP counterpart of `docket pod
    # <p> delegate --brief`. Validated here regardless, so a malformed one is always
    # `422` before anything is enqueued.
    brief_raw = task_body.get("brief")
    brief: dict[str, Any] | None = None
    if brief_raw is not None:
        if not isinstance(brief_raw, dict):
            h._send_json_error("brief must be an object", 400)
            return
        try:
            _brief.TaskBrief.model_validate(brief_raw)
        except ValidationError as exc:
            h._send_json_error(f"invalid brief: {exc}", 422)
            return
        brief = brief_raw

    options = {key: task_body.get(name) for key, name in _TASK_OPTION_FIELDS if name in task_body}
    try:
        task, created = _queue.enqueue_task_once(
            project,
            description,
            priority,
            channel="http",
            trusted=trusted,
            brief=brief,
            **options,
        )
    except _task.TaskRestrictionError as exc:
        h._send_json_error(str(exc), 422)
        return
    except DispatchError as exc:
        msg = str(exc)
        # DispatchError here is: no pod (404), a wrongly shaped option or a `block`
        # pre_input verdict naming its policy id (400) -- never swallowed into 500.
        status = 404 if msg.startswith("no pod for") else 400
        h._send_json_error(msg, status)
        return

    task_resp: dict[str, Any] = {
        "ok": True,
        "created": created,
        "task": task.id,
        "project": project,
        "status": task.status.value,
    }
    # A `require_approval` pre_input verdict leaves the task itself
    # created but gated — surface its real status and the escalation to resolve rather than
    # a 200 that implies it is queued to run.
    if task.status == Status.waiting_approval:
        stored = TaskRepository.for_pod(project).get(task.id)
        task_resp["escalation"] = stored.escalations[-1] if stored and stored.escalations else ""
    elif created and h.dispatch_on:
        h._submit_sweep(project)
    h._send(json.dumps(task_resp).encode(), "application/json", status=201 if created else 200)
