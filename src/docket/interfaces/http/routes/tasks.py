"""Reads of a pod's task queue: ``GET /tasks/<pod>``, ``/<id>``, ``/<id>/diff`` and ``/<id>/evidence``."""

from __future__ import annotations

import json
import urllib.parse as _urlparse
from typing import Any

from docket.interfaces.http.exchange import HttpExchange
from docket.interfaces.http.routes.health import _with_token_budget
from docket.tasks.application import evidence as _evidence
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.domain import options as _task_options
from docket.tasks.domain import task as _task


def get_tasks(h: HttpExchange, rest: str) -> None:
    """``GET /tasks/<pod>`` lists a pod's tasks (``status`` / ``externalRef`` filter them);
    ``GET /tasks/<pod>/<id>`` answers one. The bare ``/tasks`` is the missing-project `400`."""
    if not rest:
        h._send_json_error("Missing project", 400)
        return
    project, _, task_id = rest.partition("/")
    if h._reject_bad_project_id(project):
        return
    if task_id:
        _send_one_task(h, project, task_id)
        return
    query = _urlparse.parse_qs(_urlparse.urlsplit(h.path).query)
    tasks = _filter_tasks(h, _queue.read_tasks(project), query)
    if tasks is None:
        return
    listed = [_with_token_budget(task) for task in tasks]
    h._send(json.dumps({"tasks": listed}).encode("utf-8"), "application/json")


def get_task_evidence(h: HttpExchange, rest: str) -> None:
    project, _, task_id = rest.partition("/")
    if h._reject_bad_project_id(project):
        return
    try:
        doc = _evidence.task_evidence(project, task_id, "1.1.0")
    except _evidence.EvidenceNotFound as exc:
        h._send_json_error(str(exc), 404)
        return
    h._send(doc.model_dump_json(by_alias=True).encode("utf-8"), "application/json")


def get_task_diff(h: HttpExchange, rest: str) -> None:
    """`GET /tasks/<pod>/<id>/diff` (operator-api.spec.md "Task diff")."""
    project, _, task_id = rest.partition("/")
    if h._reject_bad_project_id(project):
        return
    try:
        doc = _lifecycle.task_diff(project, task_id)
    except _task.TaskNotFoundError as exc:
        h._send_json_error(str(exc), 404)
        return
    except _task.DispatchError as exc:
        h._send_json({"ok": False, "error": str(exc), "reason": str(exc)}, 409)
        return
    h._send_json(doc)


def _send_one_task(h: HttpExchange, project: str, task_id: str) -> None:
    for task in _queue.read_tasks(project):
        if task.get("id") == task_id:
            body = json.dumps(_with_token_budget(task))
            h._send(body.encode("utf-8"), "application/json")
            return
    h._send_json_error(f"no task '{task_id}' in pod '{project}'", 404)


def _filter_tasks(
    h: HttpExchange, tasks: list[dict[str, Any]], query: dict[str, list[str]]
) -> list[dict[str, Any]] | None:
    """Apply ``externalRef`` / ``status``; answers 400 and returns None on an unknown status."""
    status = query.get("status", [""])[0]
    if status and status not in _task_options.TASK_STATUSES:
        h._send_json_error(f"unknown task status '{status}'", 400)
        return None
    ref = query.get("externalRef", [""])[0]
    return [
        t
        for t in tasks
        if (not status or t.get("status") == status) and (not ref or t.get("externalRef") == ref)
    ]
