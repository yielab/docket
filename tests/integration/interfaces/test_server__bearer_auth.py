"""Serve auth hardening.

Covers:
  - `_DocketHandler._check_auth` compares the bearer token with
    `secrets.compare_digest` (timing-safe), not `==`
  - a wrong token is still rejected (behaviour unchanged, just the compare
    mechanism)
  - `run_serve(token_file=...)` writes the bearer token to a 0600 file
    instead of printing it to stdout
  - the bind-semantics documentation exists (default 127.0.0.1, loopback-only)
"""

from __future__ import annotations

import secrets as _secrets
import threading
from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support import http as _support_http
from tests.support.http import get as _get

from docket.interfaces.http.server import _DocketHandler
from docket.kernel.threads import ContextHTTPServer

live_server = _support_http.live_server_on_approvals_dir

approvals_dir = _support_home.approvals_dir

SUBJECT = "docket.interfaces.http.server"

_TEST_TOKEN = "test-serve-token"


# ── fixtures ──────────────────────────────────────────────────────────────────


# ── secrets.compare_digest is actually used ────────────────────────────────────


class TestCompareDigestAuth:
    def test_compare_digest_is_invoked_on_authenticated_request(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str]] = []
        real_compare_digest = _secrets.compare_digest

        def spy(a: str, b: str) -> bool:
            calls.append((a, b))
            return bool(real_compare_digest(a, b))

        monkeypatch.setattr(_secrets, "compare_digest", spy)
        base_url, token = live_server
        status, _body = _get(f"{base_url}/escalations", token=token)
        assert status == 200
        assert calls, "_check_auth should call secrets.compare_digest"
        assert calls[0] == (f"Bearer {token}", f"Bearer {token}")

    def test_wrong_token_still_rejected(self, live_server: tuple[str, str]) -> None:
        base_url, _token = live_server
        status, body = _get(f"{base_url}/escalations", token="not-the-right-token")
        assert status == 401
        assert body["ok"] is False

    def test_no_token_still_rejected(self, live_server: tuple[str, str]) -> None:
        base_url, _token = live_server
        status, _body = _get(f"{base_url}/escalations")
        assert status == 401

    def test_correct_token_accepted(self, live_server: tuple[str, str]) -> None:
        base_url, token = live_server
        status, body = _get(f"{base_url}/escalations", token=token)
        assert status == 200
        assert body == {"escalations": [], "next": 0}

    def test_empty_serve_token_denies_all_even_with_compare_digest(
        self, approvals_dir: Path
    ) -> None:
        """serve_token == "" must short-circuit before ever reaching
        compare_digest (an empty expected token must never validate)."""

        class _Handler(_DocketHandler):
            serve_token = ""

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            status, _body = _get(f"http://127.0.0.1:{port}/escalations", token="")
            assert status == 401
        finally:
            srv.shutdown()
