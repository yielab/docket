"""A refusal puts its status by error kind and its stable code on the wire."""

from __future__ import annotations

import json

import pytest

from docket.interfaces.http.exchange import HttpExchange
from docket.kernel.errors import Conflict, DocketError, InvalidInput, NotFound

SUBJECT = "docket.interfaces.http.exchange"


class _Coded(Conflict):
    code = "stale_rev"


class _Recorder(HttpExchange):
    """An exchange with no socket: it keeps what `_send` was asked to write."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, dict[str, object]]] = []

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.sent.append((status, json.loads(body)))


@pytest.mark.parametrize(
    ("exc", "status"),
    [(NotFound("gone"), 404), (Conflict("moved"), 409), (InvalidInput("bad"), 422)],
)
def test_refusal_status_follows_the_kind_of_error(exc: DocketError, status: int) -> None:
    out = _Recorder()
    out._send_refusal(exc)
    assert out.sent == [(status, {"ok": False, "error": exc.message})]


def test_refusal_carries_the_code_an_error_names() -> None:
    out = _Recorder()
    out._send_refusal(_Coded("rev moved"))
    assert out.sent == [(409, {"ok": False, "error": "rev moved", "code": "stale_rev"})]
