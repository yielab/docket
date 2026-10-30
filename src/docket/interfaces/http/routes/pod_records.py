"""Reads of a pod's records: ``GET /pods/<pod>/records`` and ``GET /pods/<pod>/records/<set>``.

Both go through the functions ``docket pod records`` calls (``teams.records``), so the read-only
connection, its authorizer and the row and time bounds are the CLI's; a route never writes."""

from __future__ import annotations

import json
import urllib.parse as _urlparse
from typing import Any

from docket.interfaces.http.exchange import HttpExchange
from docket.kernel.errors import InvalidInput
from docket.tasks.application import queue as _queue
from docket.teams import records as _records

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 1000


def _known_pod(h: HttpExchange, project: str) -> bool:
    """True for a dispatchable pod; otherwise a `400` or `404` has been sent."""
    if h._reject_bad_project_id(project):
        return False
    if project not in _queue.dispatchable_pods():
        h._send_json_error(f"no pod '{project}'", 404)
        return False
    return True


def _send(h: HttpExchange, body: dict[str, Any]) -> None:
    h._send(json.dumps(body).encode("utf-8"), "application/json")


def get_pod_records(h: HttpExchange, project: str) -> None:
    """``GET /pods/<pod>/records`` (pod-records.spec.md requirement 50)."""
    if not _known_pod(h, project):
        return
    found, problems = _records.pod_record_sets(project)
    sets = [
        {
            "name": s.name,
            "description": s.description,
            "key": s.key,
            "rows": _records.row_count(project, s),
            "columns": [
                {"name": c.name, "type": c.type, "required": c.required} for c in s.columns
            ],
        }
        for s in found
    ]
    _send(h, {"records": sets, "problems": problems})


def _limit(raw: str) -> int | None:
    if not raw:
        return _DEFAULT_LIMIT
    try:
        limit = int(raw)
    except ValueError:
        return None
    return limit if 1 <= limit <= _MAX_LIMIT else None


def get_pod_record_rows(h: HttpExchange, capture: str) -> None:
    """``GET /pods/<pod>/records/<set>?limit=&sql=`` (pod-records.spec.md requirements 51-52)."""
    project, _, name = capture.partition("/records/")
    if not _known_pod(h, project):
        return
    query = _urlparse.parse_qs(_urlparse.urlsplit(h.path).query)
    limit = _limit((query.get("limit") or [""])[0])
    if limit is None:
        h._send_json_error(f"limit must be an integer from 1 to {_MAX_LIMIT}", 400)
        return
    record_set = _records.find_set(project, name)
    if record_set is None:
        known = ", ".join(s.name for s in _records.pod_record_sets(project)[0]) or "none"
        h._send_json_error(
            f"pod '{project}' declares no record set '{name}' (it declares: {known})", 404
        )
        return
    sql = query["sql"][0] if query.get("sql") else None
    try:
        result = _records.read_rows(project, record_set, sql, limit, newest_first=True)
    except InvalidInput as exc:
        h._send_json_error(str(exc), 400)
        return
    _send(h, _records.rows_payload(record_set, result))
