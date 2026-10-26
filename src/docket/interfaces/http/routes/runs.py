"""``GET /runs`` and ``GET /runs/<id>`` -- the run registry."""

from __future__ import annotations

import json
import urllib.parse as _urlparse

from docket.interfaces.http.exchange import HttpExchange
from docket.tasks.application import runs as _runs


def get_runs(h: HttpExchange, _arg: str) -> None:
    query = _urlparse.parse_qs(_urlparse.urlsplit(h.path).query)
    project_values = query.get("project")
    project = project_values[0] if project_values else None
    body = json.dumps({"runs": _runs.list_runs(project)}).encode("utf-8")
    h._send(body, "application/json")


def get_run(h: HttpExchange, run_id: str) -> None:
    if not run_id:
        h._send_json_error("Missing run id", 400)
        return
    rec = _runs.get_run(run_id)
    if rec is None:
        h._send_json_error(f"Unknown run: {run_id}", 404)
        return
    h._send(json.dumps(rec).encode("utf-8"), "application/json")
