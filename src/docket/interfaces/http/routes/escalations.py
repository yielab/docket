"""``GET /escalations`` and ``POST /escalations/<id>``: the pauses a task waits on, and settling one."""

from __future__ import annotations

import json
import re
import urllib.parse as _urlparse

from docket.interfaces.http.exchange import HttpExchange
from docket.kernel.errors import DocketError
from docket.operator import escalation_page, escalation_view
from docket.tasks.application.escalations import resolve

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


def post_escalation(h: HttpExchange, escalation_id: str) -> None:
    """`POST /escalations/<id>`; body `{"optionId"?, "content"?, "actor"?}`. The channel is always
    `"http"`; `actor` is a label only."""
    body = h._read_json_object()
    if body is None:
        return
    option, content, actor = body.get("optionId"), body.get("content"), body.get("actor")
    if option is not None and not isinstance(option, str):
        h._send_json_error("optionId must be a string", 400)
        return
    if content is not None and not isinstance(content, dict):
        h._send_json_error("content must be an object", 400)
        return
    if actor is not None and not isinstance(actor, str):
        h._send_json_error("actor must be a string", 400)
        return
    try:
        resolved = resolve(escalation_id, option, content, by=actor or "http", channel="http")
    except DocketError as exc:
        h._send_refusal(exc)
        return
    view = escalation_view(resolved.escalation).model_dump(by_alias=True, mode="json")
    if resolved.note:
        view["note"] = resolved.note
    h._send(json.dumps(view).encode("utf-8"), "application/json")
