"""Reads of the pods: ``GET /pods``, ``GET /pods/<pod>`` and ``GET /pods/<pod>/corrections``."""

from __future__ import annotations

import json
import urllib.parse as _urlparse

from docket.hops.application import report as _pod_report
from docket.interfaces.http.exchange import HttpExchange
from docket.kernel.errors import DispatchError
from docket.tasks.application import corrections as _corrections
from docket.tasks.application import queue as _queue
from docket.teams import pod_settings as _pod_settings


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
