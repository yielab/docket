"""Headless approval channel via serve.

Acceptance criteria:
  - GET /approvals lists pending approvals when authenticated, 401 otherwise
  - POST /approvals/<token> grants/denies when authenticated, 401 (state
    unchanged) otherwise
  - POST /approvals/<token>'s `channel` field: see
    specs/data/serve-read-api.spec.md ("POST /approvals/<token> -- the
    channel field")
  - Expiry sweep still fail-closes
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
from docket.core import audit as _audit
from docket.core.approval import _approval_path
from docket.edges import store as _store
from docket.serve import _DocketHandler

SUBJECT = "docket.core.approval"

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

    def test_deny_after_grant_returns_409_naming_winner(self, live_server: tuple[str, str]) -> None:
        """A resolved token still exists -- the opposite decision is a conflict (409
        naming the winning state), never the missing-token 404. Regression for the bug
        where `core.approval.ApprovalError` covered both cases indistinguishably."""
        url, token = live_server
        apr_token = _approval.approval_create("proj10", "implementer", "x")
        _approval.approval_grant(apr_token)
        status, body = _post(f"{url}/approvals/{apr_token}", {"action": "deny"}, token)
        assert status == 409
        assert body["ok"] is False
        assert "granted" in body["error"]
        assert _approval.approval_get(apr_token)["state"] == "granted"

    def test_post_unknown_path_returns_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _ = _post(f"{url}/unknown", {"action": "grant"}, token)
        assert status == 404

    def test_concurrent_http_grant_and_deny_have_one_terminal_winner(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two real HTTP handlers meeting at a pending record cannot both win."""
        url, token = live_server
        apr_token = _approval.approval_create("proj-race", "implementer", "deploy")
        original = _approval._set_state
        barrier = threading.Barrier(2, timeout=2)

        def synchronized_set_state(record_token: str, state: str) -> dict[str, object]:
            barrier.wait()
            return original(record_token, state)

        monkeypatch.setattr(_approval, "_set_state", synchronized_set_state)
        replies: list[tuple[int, dict]] = []

        def decide(action: str) -> None:
            replies.append(_post(f"{url}/approvals/{apr_token}", {"action": action}, token))

        threads = [threading.Thread(target=decide, args=(action,)) for action in ("grant", "deny")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()

        # Opposite terminal state is a conflict (409 naming the winner), same as a
        # duplicate decision's 409 no-op -- only a missing token is 404.
        assert sorted(status for status, _body in replies) == [200, 409]
        assert _approval.approval_get(apr_token)["state"] in {"granted", "denied"}

    @pytest.mark.parametrize("start_grant_first", [True, False], ids=["grant-first", "deny-first"])
    def test_barrier_forced_grant_vs_cancellation_deny(
        self, approvals_dir: Path, monkeypatch: pytest.MonkeyPatch, start_grant_first: bool
    ) -> None:
        """Analogue of the flaky agent-loop cancellation test: forces a grant to
        collide, via a barrier on ``_set_state``, with the in-turn cancellation
        self-deny at one pending record, in both start orders."""
        original = _approval._set_state
        apr_token = _approval.approval_create("proj-race-cancel", "implementer", "x")
        barrier = threading.Barrier(2, timeout=2)

        def synchronized_set_state(record_token: str, state: str) -> dict[str, object]:
            barrier.wait()
            return original(record_token, state)

        monkeypatch.setattr(_approval, "_set_state", synchronized_set_state)
        outcomes: dict[str, str] = {}

        def grant() -> None:
            try:
                _approval.approval_grant(apr_token, channel="cli")
                outcomes["grant"] = "won"
            except _approval.ApprovalConflict as exc:
                assert exc.winning_state == "denied"
                outcomes["grant"] = "lost"

        def deny() -> None:
            try:
                _approval.approval_deny(apr_token, channel="cancellation")
                outcomes["deny"] = "won"
            except _approval.ApprovalConflict as exc:
                assert exc.winning_state == "granted"
                outcomes["deny"] = "lost"

        first, second = (grant, deny) if start_grant_first else (deny, grant)
        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        assert not t1.is_alive()
        assert not t2.is_alive()

        # Exactly one winner, one loser -- never both, never neither.
        assert sorted(outcomes.values()) == ["lost", "won"]
        final_state = _approval.approval_get(apr_token)["state"]
        assert final_state in {"granted", "denied"}
        winner = "grant" if outcomes["grant"] == "won" else "deny"
        assert (winner == "grant") == (final_state == "granted")


# ── POST /approvals/<token>'s optional `channel` field ─────────────────────────


class TestApprovalChannel:
    def test_absent_channel_defaults_to_http_unchanged(self, live_server: tuple[str, str]) -> None:
        """No `channel` in the body -> every caller before this field existed
        keeps identical behaviour (channel="http", same as before)."""
        url, token = live_server
        apr_token = _approval.approval_create("projT1", "implementer", "deploy")
        status, _body = _post(f"{url}/approvals/{apr_token}", {"action": "grant"}, token)
        assert status == 200
        entries = [e for e in _audit.read_audit() if e.get("action") == "approval.grant"]
        assert entries, "no approval.grant audit entry written"
        assert "channel=http" in entries[-1]["detail"]

    def test_recognised_channel_tack_is_accepted_and_recorded(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("projT2", "implementer", "deploy")
        status, body = _post(
            f"{url}/approvals/{apr_token}", {"action": "grant", "channel": "tack"}, token
        )
        assert status == 200
        assert body["ok"] is True
        assert _approval.approval_get(apr_token)["state"] == "granted"
        entries = [e for e in _audit.read_audit() if e.get("action") == "approval.grant"]
        assert "channel=tack" in entries[-1]["detail"]

    def test_recognised_channel_works_for_deny_too(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("projT3", "implementer", "deploy")
        status, _body = _post(
            f"{url}/approvals/{apr_token}", {"action": "deny", "channel": "tack"}, token
        )
        assert status == 200
        assert _approval.approval_get(apr_token)["state"] == "denied"
        entries = [e for e in _audit.read_audit() if e.get("action") == "approval.deny"]
        assert "channel=tack" in entries[-1]["detail"]

    def test_unrecognised_channel_returns_400_state_unchanged(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("projT4", "implementer", "deploy")
        status, body = _post(
            f"{url}/approvals/{apr_token}",
            {"action": "grant", "channel": "some-made-up-caller"},
            token,
        )
        assert status == 400
        assert body["ok"] is False
        # Rejected before touching approval state -- still pending, not granted.
        assert _approval.approval_get(apr_token)["state"] == "pending"

    def test_non_string_channel_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("projT5", "implementer", "deploy")
        status, _body = _post(
            f"{url}/approvals/{apr_token}", {"action": "grant", "channel": 123}, token
        )
        assert status == 400
        assert _approval.approval_get(apr_token)["state"] == "pending"

    def test_every_http_claimable_channel_is_accepted(self, live_server: tuple[str, str]) -> None:
        """Only the channels the HTTP transport may claim (`http`, `tack`) --
        not every member of core.approval.APPROVAL_CHANNELS, several of which
        (`cli`, `mcp`, `telegram`, `timeout`) belong to other surfaces."""
        url, token = live_server
        for chan in ("http", "tack"):
            apr_token = _approval.approval_create("projT6", "implementer", f"deploy via {chan}")
            status, _body = _post(
                f"{url}/approvals/{apr_token}", {"action": "grant", "channel": chan}, token
            )
            assert status == 200, f"channel {chan!r} should be accepted"
            assert _approval.approval_get(apr_token)["state"] == "granted"

    @pytest.mark.parametrize("chan", ["timeout", "cli", "mcp", "telegram"])
    def test_non_http_channel_is_rejected_over_http(
        self, live_server: tuple[str, str], chan: str
    ) -> None:
        """A Bearer holder over HTTP must not forge a decision as coming from
        another surface's channel (`cli`, `mcp`, `telegram`) or as the
        fail-closed expiry path (`timeout`)."""
        url, token = live_server
        apr_token = _approval.approval_create("projT7", "implementer", f"deploy via {chan}")
        entries_before = [e for e in _audit.read_audit() if e.get("action") == "approval.grant"]
        status, body = _post(
            f"{url}/approvals/{apr_token}", {"action": "grant", "channel": chan}, token
        )
        assert status == 400, f"channel {chan!r} must not be claimable over HTTP"
        assert body["ok"] is False
        assert _approval.approval_get(apr_token)["state"] == "pending"
        entries_after = [e for e in _audit.read_audit() if e.get("action") == "approval.grant"]
        assert entries_after == entries_before, "no approval.grant audit entry must be written"


# ── expiry still fail-closes ──────────────────────────────────────────────────


class TestExpiryStillFailCloses:
    def test_expired_not_in_pending_list(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("projE", "implementer", "x")
        rec = _approval.approval_get(apr_token)
        rec["state"] = "denied"
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
        # The timeout sweep resolves to "denied" (fail-closed), not the
        # prior, read-by-nobody "expired" state.
        assert _approval.approval_get(apr_token)["state"] == "denied"

    def test_sweep_leaves_recent_pending_alone(self, approvals_dir: Path) -> None:
        apr_token = _approval.approval_create("projR", "implementer", "x")
        swept = _approval.approval_sweep_expired()
        assert swept == 0
        assert _approval.approval_get(apr_token)["state"] == "pending"
