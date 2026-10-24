"""The approval store: the grant and deny paths, channels, deadlines, pruning and audit fields."""

from __future__ import annotations

import datetime as _dt
import json
import os as _os
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support import http as _support_http
from tests.support.http import get_2 as _get
from tests.support.http import post as _post

from docket.governance import approval as _approval
from docket.governance import audit as _audit
from docket.governance.approval import _approval_path
from docket.kernel.home import current_home
from docket.kernel.threads import new_thread
from docket.platform import store as _store

SUBJECT = "docket.governance.approval"


live_server = _support_http.live_server_2


approvals_dir = _support_home.approvals_dir


_isolate_gates = _support_home.isolate_gates


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

    def test_deny_with_reason_records_in_audit(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        apr_token = _approval.approval_create("proj-http-reason", "implementer", "deploy")
        status, body = _post(
            f"{url}/approvals/{apr_token}", {"action": "deny", "reason": "not ready"}, token
        )
        assert status == 200
        assert body["ok"] is True
        assert _approval.approval_get(apr_token)["state"] == "denied"

        # Check audit log contains reason
        audit_lines = _audit.read_audit()
        deny_lines = [line for line in audit_lines if line.get("action") == "approval.deny"]
        assert len(deny_lines) > 0
        last_line = deny_lines[-1]
        assert "reason=" in last_line["detail"]

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
        where `governance.approval.ApprovalError` covered both cases indistinguishably."""
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

        threads = [new_thread(target=decide, args=(action,)) for action in ("grant", "deny")]
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
        t1 = new_thread(target=first)
        t2 = new_thread(target=second)
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
        not every member of governance.approval.APPROVAL_CHANNELS, several of which
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


class TestApprovalTokenIsNotAPath:
    """Every channel hands caller text to `_approval_path`; only a minted `apr-<uuid4>` token
    may name a record, so caller text can never leave the approvals directory."""

    @pytest.mark.parametrize("token", ["../../x", "/etc/passwd", "apr-1", "", "apr-" + "z" * 36])
    def test_a_malformed_token_is_not_found(self, approvals_dir: Path, token: str) -> None:
        with pytest.raises(_approval.ApprovalError):
            _approval.approval_get(token)
        with pytest.raises(_approval.ApprovalError):
            _approval.approval_grant(token, channel="cli")

    def test_a_minted_token_still_resolves(self, approvals_dir: Path) -> None:
        token = _approval.approval_create("pod", "implementer", "tool call 'bash'", context={})
        assert _approval.approval_get(token)["state"] == "pending"

    def test_the_http_route_cannot_reach_a_file_outside_the_directory(
        self, live_server: tuple[str, str], approvals_dir: Path
    ) -> None:
        url, token = live_server
        outside = approvals_dir.parent / "outside"
        outside.mkdir()
        victim = outside / "victim.json"
        victim.write_text('{"state": "pending", "project": "demo", "role": "implementer"}')
        before = victim.read_text()
        status, body = _post(f"{url}/approvals/../outside/victim", {"action": "grant"}, token)
        assert status == 404, body
        assert victim.read_text() == before
        assert not (outside / "victim.json.bak").exists()

    def test_a_non_object_body_is_a_400_not_a_dropped_connection(
        self, live_server: tuple[str, str], approvals_dir: Path
    ) -> None:
        url, token = live_server
        pending = _approval.approval_create("pod", "implementer", "tool call 'bash'", context={})
        data = b"[]"
        req = urllib.request.Request(f"{url}/approvals/{pending}", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {token}")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 400
        assert _approval.approval_get(pending)["state"] == "pending"


class TestEveryApprovalRecordsItsDeadline:
    def test_default_deadline_is_created_plus_timeout(self, approvals_dir: Path) -> None:
        """A creator that names no deadline still gets created + APPROVAL_TIMEOUT."""
        rec = _approval.approval_get(_approval.approval_create("projX", "implementer", "x"))
        created = _dt.datetime.strptime(rec["created"][:19], "%Y-%m-%dT%H:%M:%S")
        expires = _dt.datetime.strptime(rec["expiresAt"][:19], "%Y-%m-%dT%H:%M:%S")
        assert expires - created == _dt.timedelta(seconds=current_home().approval_timeout)

    def test_given_deadline_is_kept(self, approvals_dir: Path) -> None:
        """An explicit expires_at is stored verbatim."""
        token = _approval.approval_create(
            "projX", "implementer", "x", expires_at="2031-01-01T00:00:00Z"
        )
        assert _approval.approval_get(token)["expiresAt"] == "2031-01-01T00:00:00Z"

    def test_approvals_view_carries_the_deadline(self, live_server: tuple[str, str]) -> None:
        """GET /approvals shows the same expiresAt the record holds."""
        url, token = live_server
        apr = _approval.approval_create("projV", "implementer", "x")
        _, body = _get(f"{url}/approvals", token)
        row = next(r for r in body["pending"] if r["token"] == apr)
        assert row["expiresAt"] == _approval.approval_get(apr)["expiresAt"]


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
        old = _dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=current_home().approval_timeout + 1)
        rec["created"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        rec["expiresAt"] = rec["created"]
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

    def test_a_records_own_expires_at_wins_over_the_default_timeout(
        self, approvals_dir: Path
    ) -> None:
        """A parked call may carry a short ``expiresAt`` well inside APPROVAL_TIMEOUT;
        the sweep must honour that record's own deadline, not fall back to the default."""
        apr_token = _approval.approval_create(
            "projP", "implementer", "x", expires_at="2000-01-01T00:00:00Z"
        )
        swept = _approval.approval_sweep_expired()
        assert swept == 1
        assert _approval.approval_get(apr_token)["state"] == "denied"


class TestPruneResolved:
    def _age_by(self, path: Path, seconds: float) -> None:
        old = path.stat().st_mtime - seconds
        _os.utime(path, (old, old))

    def test_prune_removes_old_resolved_keeps_recent_and_pending(self, approvals_dir: Path) -> None:
        old_granted = _approval.approval_create("proj", "implementer", "x")
        _approval.approval_grant(old_granted, channel="cli")
        self._age_by(_approval_path(old_granted), current_home().trace_retention_s + 3600)

        recent_denied = _approval.approval_create("proj", "implementer", "x")
        _approval.approval_deny(recent_denied, channel="cli")

        still_pending = _approval.approval_create("proj", "implementer", "x")
        self._age_by(_approval_path(still_pending), current_home().trace_retention_s + 3600)

        removed = _approval.prune_resolved()

        assert removed == 1
        assert not _approval_path(old_granted).exists()
        assert _approval.approval_get(recent_denied)["state"] == "denied"
        assert _approval.approval_get(still_pending)["state"] == "pending"

    def test_prune_dry_run_reports_without_deleting(self, approvals_dir: Path) -> None:
        token = _approval.approval_create("proj", "implementer", "x")
        _approval.approval_grant(token, channel="cli")
        self._age_by(_approval_path(token), current_home().trace_retention_s + 3600)

        removed = _approval.prune_resolved(dry_run=True)

        assert removed == 1
        assert _approval_path(token).exists()

    def test_prune_respects_custom_retention_window(self, approvals_dir: Path) -> None:
        token = _approval.approval_create("proj", "implementer", "x")
        _approval.approval_grant(token, channel="cli")

        removed = _approval.prune_resolved(retention_s=0)

        assert removed == 1
        assert not _approval_path(token).exists()


class TestApprovalReasonAndActor:
    """Test reason and actor parameters for grant/deny."""

    def test_deny_with_reason_and_actor(self, approvals_dir: Path) -> None:
        """A deny with reason and actor writes them to the audit log."""
        token = _approval.approval_create("proj", "implementer", "action")

        _approval.approval_deny(token, channel="cli", actor="testuser", reason="not ready")

        rec = _approval.approval_get(token)
        assert rec["state"] == "denied"

        # Check audit log contains reason and actor
        audit_lines = _audit.read_audit()
        deny_lines = [line for line in audit_lines if line.get("action") == "approval.deny"]
        assert len(deny_lines) > 0
        last_line = deny_lines[-1]
        assert "actor=testuser" in last_line["detail"]
        assert "reason=" in last_line["detail"]

    def test_deny_without_reason_matches_original_format(self, approvals_dir: Path) -> None:
        """A deny without reason is byte-identical to the original format."""
        token = _approval.approval_create("proj", "implementer", "action")

        _approval.approval_deny(token, channel="cli")

        # Check audit log format (should NOT include actor or reason)
        audit_lines = _audit.read_audit()
        deny_lines = [line for line in audit_lines if line.get("action") == "approval.deny"]
        assert len(deny_lines) > 0
        last_line = deny_lines[-1]
        # The detail should have the exact format without actor/reason
        assert last_line["detail"] == f"token={token} project=proj channel=cli"

    def test_deny_with_blocked_reason_leaves_pending(self, approvals_dir: Path) -> None:
        """A deny with a reason that trips a pre_input block leaves the approval pending."""
        token = _approval.approval_create("proj", "implementer", "action")

        # Create a blocking policy
        current_home().policies_dir.mkdir(parents=True, exist_ok=True)
        policy_doc = {
            "id": "block-test",
            "description": "Block test patterns",
            "applies_to": ["*"],
            "hook": "pre_input",
            "match": {"type": "regex", "pattern": "DELETE PROD"},
            "action": "block",
            "message": "Blocked.",
        }
        (current_home().policies_dir / "block-test.json").write_text(
            json.dumps(policy_doc), encoding="utf-8"
        )

        # Try to deny with a blocked reason
        with pytest.raises(_approval.ApprovalError, match="Reason blocked by policy"):
            _approval.approval_deny(token, channel="cli", reason="DELETE PROD")

        # Check that the approval is still pending
        rec = _approval.approval_get(token)
        assert rec["state"] == "pending"

    def test_grant_with_reason_and_actor(self, approvals_dir: Path) -> None:
        """A grant with reason and actor writes them to the audit log."""
        token = _approval.approval_create("proj", "implementer", "action")

        _approval.approval_grant(token, channel="cli", actor="testuser", reason="looks good")

        rec = _approval.approval_get(token)
        assert rec["state"] == "granted"

        # Check audit log contains reason and actor
        audit_lines = _audit.read_audit()
        grant_lines = [line for line in audit_lines if line.get("action") == "approval.grant"]
        assert len(grant_lines) > 0
        last_line = grant_lines[-1]
        assert "actor=testuser" in last_line["detail"]
        assert "reason=" in last_line["detail"]

    def test_grant_without_reason_matches_original_format(self, approvals_dir: Path) -> None:
        """A grant without reason is byte-identical to the original format."""
        token = _approval.approval_create("proj", "implementer", "action")

        _approval.approval_grant(token, channel="cli")

        # Check audit log format (should NOT include actor or reason)
        audit_lines = _audit.read_audit()
        grant_lines = [line for line in audit_lines if line.get("action") == "approval.grant"]
        assert len(grant_lines) > 0
        last_line = grant_lines[-1]
        # The detail should have the exact format without actor/reason
        assert last_line["detail"] == f"token={token} project=proj channel=cli"


class TestAuditFieldsAreBounded:
    """Free-text approval fields reach the audit line capped at 512 characters."""

    def test_a_long_deny_reason_is_capped_in_the_audit_detail(self) -> None:
        token = _approval.approval_create("proj-cap-reason", "implementer", "deploy")
        _approval.approval_deny(token, "cli", reason="r" * 50_000)
        detail = str(_audit.read_audit()[-1]["detail"])
        assert len(detail) < 700
        assert "…" in detail

    def test_a_long_actor_is_capped_in_the_audit_detail(self) -> None:
        token = _approval.approval_create("proj-cap-actor", "implementer", "deploy")
        _approval.approval_grant(token, "cli", actor="a" * 5_000)
        detail = str(_audit.read_audit()[-1]["detail"])
        assert len(detail) < 700
        assert "…" in detail

    def test_a_reason_under_the_cap_is_recorded_whole(self) -> None:
        token = _approval.approval_create("proj-cap-short", "implementer", "deploy")
        _approval.approval_deny(token, "cli", reason="not ready")
        assert "reason=not ready" in str(_audit.read_audit()[-1]["detail"])
