"""The Bearer check for every authenticated route, written once.

A random token (``DOCKET_SERVE_TOKEN`` pins a fixed one) gates every route the route table marks
``auth``. An empty ``serve_token`` denies everything -- never an accidental pass-through.
``DOCKET_SERVE_READ_TOKEN`` is a second token that may only read."""

from __future__ import annotations

import secrets

from docket.interfaces.http.exchange import HttpExchange

READ_METHODS = frozenset({"GET", "HEAD"})


def bearer_matches(authorization: str, token: str) -> bool:
    """True when *authorization* is exactly ``Bearer <token>`` and *token* is non-empty."""
    if not token:
        return False
    # Timing-safe compare — a plain `==` short-circuits on
    # the first mismatched byte, leaking token-length/prefix information
    # to an attacker who can measure response latency.
    return secrets.compare_digest(authorization, f"Bearer {token}")


def authorize(exchange: HttpExchange, method: str) -> bool:
    """True when the request may run: the serve token for any method, the read token for `GET` and
    `HEAD`. The read token on any other method answers `403 read_scope`, anything else `401`;
    either way False."""
    authorization = exchange.headers.get("Authorization", "")
    if bearer_matches(authorization, exchange.serve_token):
        return True
    if bearer_matches(authorization, exchange.read_token):
        if method in READ_METHODS:
            return True
        exchange._send_json_error("This token may only read", 403, code="read_scope")
        return False
    exchange._send_json_error("Unauthorized", 401)
    return False
