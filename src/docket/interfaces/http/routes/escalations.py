"""``GET /escalations`` -- the pauses a task waits on, one record each, after a cursor."""

from __future__ import annotations

import json
import re
import urllib.parse as _urlparse

from docket.interfaces.http.exchange import HttpExchange
from docket.operator import escalation_page

_SEQ = re.compile(r"[0-9]+")


def get_escalations(h: HttpExchange, _arg: str) -> None:
    query = _urlparse.parse_qs(_urlparse.urlsplit(h.path).query)
    raw = query.get("since", ["0"])[0]
    if not _SEQ.fullmatch(raw):
        h._send_json_error("since must be a non-negative integer", 400)
        return
    page = escalation_page(
        since_seq=int(raw),
        pod=query["pod"][0] if "pod" in query else None,
        task=query["task"][0] if "task" in query else None,
    )
    h._send(
        json.dumps(page.model_dump(by_alias=True, mode="json")).encode("utf-8"), "application/json"
    )
