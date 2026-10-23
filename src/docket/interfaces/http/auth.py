"""The Bearer check for every authenticated route, written once.

A random token (``DOCKET_SERVE_TOKEN`` pins a fixed one) gates every route the route table marks
``auth``. An empty ``serve_token`` denies everything -- never an accidental pass-through."""

from __future__ import annotations

import secrets

from docket.interfaces.http.exchange import HttpExchange


def bearer_matches(authorization: str, token: str) -> bool:
    """True when *authorization* is exactly ``Bearer <token>`` and *token* is non-empty."""
    if not token:
        return False
    # Timing-safe compare — a plain `==` short-circuits on
    # the first mismatched byte, leaking token-length/prefix information
    # to an attacker who can measure response latency.
    return secrets.compare_digest(authorization, f"Bearer {token}")


def authorize(exchange: HttpExchange) -> bool:
    """True when the request carries the serve token; otherwise answer `401` and return False."""
    if bearer_matches(exchange.headers.get("Authorization", ""), exchange.serve_token):
        return True
    exchange._send_json_error("Unauthorized", 401)
    return False
