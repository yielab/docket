"""Reads of the pods: ``GET /pods``, ``GET /pods/<pod>``, ``GET /pods/<pod>/corrections`` and
``GET /pods/<pod>/memory``, and ``POST /pods/<pod>/resume`` and ``POST /pods/<pod>/memory/<id>``."""

from __future__ import annotations

import json
import urllib.parse as _urlparse

from docket.hops.application import report as _pod_report
from docket.interfaces.http.exchange import HttpExchange
from docket.kernel.errors import DispatchError
from docket.tasks.application import corrections as _corrections
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.teams import memory as _pod_memory
from docket.teams import pod_settings as _pod_settings

_MEMORY_STATUSES = ("accepted", "pending", "refused")
_MEMORY_DECISIONS = ("approve", "refuse")


def get_pods(h: HttpExchange, _arg: str) -> None:
    """``GET /pods`` (operator-api.spec.md "Pod answers")."""
    pods = [_pod_report.pod_summary(p) for p in _queue.dispatchable_pods()]
    h._send(json.dumps({"pods": pods}).encode("utf-8"), "application/json")


def get_pod(h: HttpExchange, project: str) -> None:
    """``GET /pods/<pod>`` (operator-api.spec.md "Pod answers")."""
    if h._reject_bad_project_id(project):
        return
    if project not in _queue.dispatchable_pods():
        h._send_json_error(f"Unknown pod: {project}", 404)
        return
    try:
        detail = _pod_report.pod_detail(project)
    except (DispatchError, _pod_settings.PodSettingsError) as exc:
        h._send_json_error(str(exc), 500)
        return
    h._send(json.dumps(detail).encode("utf-8"), "application/json")


def post_pod_resume(h: HttpExchange, project: str) -> None:
    """``POST /pods/<pod>/resume``: clear the pod's pause and answer the pod's report with
    ``resumed`` (operator-api.spec.md)."""
    if h._reject_bad_project_id(project):
        return
    if project not in _queue.dispatchable_pods():
        h._send_json_error(f"Unknown pod: {project}", 404)
        return
    try:
        resumed = _lifecycle.resume_pod(project, channel="http").was_paused
        detail = _pod_report.pod_detail(project)
    except (DispatchError, _pod_settings.PodSettingsError) as exc:
        h._send_json_error(str(exc), 500)
        return
    h._send(json.dumps({**detail, "resumed": resumed}).encode("utf-8"), "application/json")


def get_pod_corrections(h: HttpExchange, project: str) -> None:
    if h._reject_bad_project_id(project):
        return
    if project not in _queue.dispatchable_pods():
        h._send_json_error(f"no pod '{project}'", 404)
        return
    query = _urlparse.parse_qs(_urlparse.urlsplit(h.path).query)
    since = (query.get("since") or [""])[0]
    if since:
        try:
            since = _corrections.utc_cursor(since)
        except ValueError:
            h._send_json_error("since must be an ISO-8601 timestamp with an offset", 400)
            return
    records = _corrections.read(project, since)
    next_cursor = _corrections.utc_z(str(records[-1].get("ts", "")) if records else since)
    body = json.dumps({"corrections": records, "next": next_cursor}).encode("utf-8")
    h._send(body, "application/json")


def get_pod_memory(h: HttpExchange, project: str) -> None:
    """``GET /pods/<pod>/memory``: the entries of one status (``accepted`` by default), oldest
    first (operator-api.spec.md)."""
    if h._reject_bad_project_id(project):
        return
    if project not in _queue.dispatchable_pods():
        h._send_json_error(f"no pod '{project}'", 404)
        return
    query = _urlparse.parse_qs(_urlparse.urlsplit(h.path).query)
    status = (query.get("status") or ["accepted"])[0]
    if status not in _MEMORY_STATUSES:
        h._send_json_error(f"status must be one of {', '.join(_MEMORY_STATUSES)}", 400)
        return
    entries = [e.to_dict() for e in _pod_memory.list_entries(project, status=status)]
    h._send(json.dumps({"entries": entries}).encode("utf-8"), "application/json")


def post_pod_memory(h: HttpExchange, capture: str) -> None:
    """``POST /pods/<pod>/memory/<id>``: approve or refuse a pending entry as ``docket pod memory
    approve`` and ``refuse`` do, and answer the entry in its new status (operator-api.spec.md)."""
    project, _, entry_id = capture.partition("/memory/")
    if h._reject_bad_project_id(project):
        return
    if project not in _queue.dispatchable_pods():
        h._send_json_error(f"no pod '{project}'", 404)
        return
    body = h._read_json_object()
    if body is None:
        return
    decision, reason = body.get("decision"), body.get("reason", "")
    if decision not in _MEMORY_DECISIONS:
        h._send_json_error("decision must be approve or refuse", 400)
        return
    if not isinstance(reason, str):
        h._send_json_error("reason must be a string", 400)
        return
    if decision == "refuse" and not reason.strip():
        h._send_json_error("refuse needs a reason", 400)
        return
    try:
        if decision == "approve":
            entry = _pod_memory.approve(project, entry_id, actor="http")
        else:
            entry = _pod_memory.refuse(project, entry_id, reason, actor="http")
    except _pod_memory.PodMemoryError as exc:
        h._send_refusal(exc)
        return
    h._send(json.dumps(entry.to_dict()).encode("utf-8"), "application/json")
