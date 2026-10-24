"""The approval listing served over a real loopback HTTP server."""

from __future__ import annotations

import threading
from pathlib import Path

from tests.support import home as _support_home
from tests.support import http as _support_http
from tests.support.http import get_2 as _get

from docket.governance import approval as _approval
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.threads import ContextHTTPServer

SUBJECT = "docket.governance.approval"


live_server = _support_http.live_server_2


approvals_dir = _support_home.approvals_dir


_isolate_gates = _support_home.isolate_gates


class TestListApprovals:
    def test_empty_list_authenticated(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _get(f"{url}/approvals", token)
        assert status == 200
        assert body == {"pending": []}

    def test_pending_approval_appears(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("proj1", "implementer", "run tests")
        status, body = _get(f"{url}/approvals", token)
        assert status == 200
        assert len(body["pending"]) == 1
        rec = body["pending"][0]
        assert rec["token"] == apr_token
        assert rec["state"] == "pending"
        assert rec["project"] == "proj1"

    def test_no_token_returns_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, body = _get(f"{url}/approvals")
        assert status == 401
        assert body["ok"] is False

    def test_wrong_token_returns_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, _ = _get(f"{url}/approvals", token="wrong-token")
        assert status == 401

    def test_granted_approval_not_in_pending(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("proj2", "implementer", "deploy")
        _approval.approval_grant(apr_token)
        status, body = _get(f"{url}/approvals", token)
        assert status == 200
        assert all(r["token"] != apr_token for r in body["pending"])

    def test_empty_serve_token_denies_all(self, approvals_dir: Path) -> None:
        class _Handler(_DocketHandler):
            serve_token = ""

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            status, _ = _get(f"http://127.0.0.1:{port}/approvals", "")
            assert status == 401
        finally:
            srv.shutdown()
