"""``GET /inbox`` -- the operator's inbox view, optionally since a cursor."""

from __future__ import annotations

import json
import urllib.parse as _urlparse

from docket.interfaces.http.exchange import HttpExchange
from docket.kernel import clock as _clock
from docket.operator import inbox as _inbox


def get_inbox(h: HttpExchange, _arg: str) -> None:
    query = _urlparse.parse_qs(_urlparse.urlsplit(h.path).query)
    since_values = query.get("since")
    since = since_values[0] if since_values else None
    view = _inbox.build_inbox(now=_clock.stamp(), since=since)
    body = json.dumps(view.model_dump(by_alias=True, mode="json")).encode("utf-8")
    h._send(body, "application/json")
