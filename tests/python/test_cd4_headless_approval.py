"""CD-4: Headless approval channel via serve.

Acceptance criteria:
  - GET /approvals lists pending approvals when authenticated
  - GET /approvals returns 401 without token or with wrong token
  - POST /approvals/<token> grants/denies an approval when authenticated
  - POST /approvals/<token> returns 401 without auth (state unchanged)
  - Expiry sweep still fail-closes (unaffected by CD-4)
  - suite green
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import approval as _approval
from docket.core.approval import _approval_path
from docket.edges import store as _store
from docket.serve import _DocketHandler

_TEST_TOKEN = "test-serve-token-cd4-abc123"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def approvals_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "approvals"
    d.mkdir()
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d, raising=True)
    return d


@pytest.fixture()
def live_server(approvals_dir: Path):
    """Real ThreadingHTTPServer on a random port. Yields (base_url, token)."""

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _get(url: str, token: str | None = None) -> tuple[int, dict]:  # type: ignore[type-arg]
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post(
    url: str,
    body: dict,
    token: str | None = None,  # type: ignore[type-arg]
) -> tuple[int, dict]:  # type: ignore[type-arg]
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Length", str(len(data)))
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ── GET /approvals ─────────────────────────────────────────────────────────────


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

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            status, _ = _get(f"http://127.0.0.1:{port}/approvals", "")
            assert status == 401
        finally:
            srv.shutdown()


# ── POST /approvals/<token> ───────────────────────────────────────────────────


class TestGrantDenyViaEndpoint:
    def test_grant_approval(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("proj3", "implementer", "deploy")
        status, body = _post(f"{url}/approvals/{apr_token}", {"action": "grant"}, token)
        assert status == 200
        assert body["ok"] is True
        assert body["state"] == "granted"
        assert body["token"] == apr_token
        assert _approval.approval_get(apr_token)["state"] == "granted"

    def test_deny_approval(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("proj4", "implementer", "deploy")
        status, body = _post(f"{url}/approvals/{apr_token}", {"action": "deny"}, token)
        assert status == 200
        assert body["ok"] is True
        assert body["state"] == "denied"
        assert _approval.approval_get(apr_token)["state"] == "denied"

    def test_no_auth_returns_401_state_unchanged(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        apr_token = _approval.approval_create("proj5", "implementer", "x")
        status, _ = _post(f"{url}/approvals/{apr_token}", {"action": "grant"})
        assert status == 401
        assert _approval.approval_get(apr_token)["state"] == "pending"

    def test_wrong_token_returns_401_state_unchanged(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        apr_token = _approval.approval_create("proj6", "implementer", "x")
        status, _ = _post(f"{url}/approvals/{apr_token}", {"action": "grant"}, "bad-token")
        assert status == 401
        assert _approval.approval_get(apr_token)["state"] == "pending"

    def test_invalid_action_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("proj7", "implementer", "x")
        status, body = _post(f"{url}/approvals/{apr_token}", {"action": "launch"}, token)
        assert status == 400
        assert "action" in body["error"].lower()

    def test_empty_body_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("proj8", "implementer", "x")
        status, _ = _post(f"{url}/approvals/{apr_token}", {}, token)
        assert status == 400

    def test_double_grant_returns_409(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("proj9", "implementer", "x")
        _approval.approval_grant(apr_token)
        status, body = _post(f"{url}/approvals/{apr_token}", {"action": "grant"}, token)
        assert status == 409
        assert body["ok"] is False

    def test_unknown_token_returns_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/approvals/apr-does-not-exist", {"action": "grant"}, token)
        assert status == 404
        assert body["ok"] is False

    def test_post_unknown_path_returns_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _ = _post(f"{url}/unknown", {"action": "grant"}, token)
        assert status == 404


# ── expiry still fail-closes ──────────────────────────────────────────────────


class TestExpiryStillFailCloses:
    def test_expired_not_in_pending_list(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("projE", "implementer", "x")
        rec = _approval.approval_get(apr_token)
        rec["state"] = "expired"
        _store.write_json(_approval_path(apr_token), rec)

        status, body = _get(f"{url}/approvals", token)
        assert status == 200
        assert all(r["token"] != apr_token for r in body["pending"])

    def test_sweep_expires_old_pending(self, approvals_dir: Path) -> None:
        apr_token = _approval.approval_create("projS", "implementer", "x")
        rec = _approval.approval_get(apr_token)
        old = _dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=_cfg.APPROVAL_TIMEOUT + 1)
        rec["created"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        _store.write_json(_approval_path(apr_token), rec)

        swept = _approval.approval_sweep_expired()
        assert swept == 1
        assert _approval.approval_get(apr_token)["state"] == "expired"

    def test_sweep_leaves_recent_pending_alone(self, approvals_dir: Path) -> None:
        apr_token = _approval.approval_create("projR", "implementer", "x")
        swept = _approval.approval_sweep_expired()
        assert swept == 0
        assert _approval.approval_get(apr_token)["state"] == "pending"
