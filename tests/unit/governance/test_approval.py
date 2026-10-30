"""The approval store: the grant and deny paths, channels, deadlines, pruning and audit fields."""

from __future__ import annotations

import datetime as _dt
import json
import os as _os
import threading
from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support import http as _support_http

from docket.governance import approval as _approval
from docket.governance import audit as _audit
from docket.governance.approval import _approval_path
from docket.kernel.home import current_home
from docket.kernel.threads import new_thread

SUBJECT = "docket.governance.approval"


live_server = _support_http.live_server_on_approvals_dir


approvals_dir = _support_home.approvals_dir


_isolate_gates = _support_home.isolate_gates


class TestGrantAgainstCancellation:
    @pytest.mark.parametrize("start_grant_first", [True, False], ids=["grant-first", "deny-first"])
    def test_barrier_forced_grant_vs_cancellation_deny(
        self, approvals_dir: Path, monkeypatch: pytest.MonkeyPatch, start_grant_first: bool
    ) -> None:
        """Analogue of the flaky agent-loop cancellation test: forces a grant to
        collide, via a barrier on ``set_state``, with the in-turn cancellation
        self-deny at one pending record, in both start orders."""
        original = _approval.set_state
        apr_token = _approval.approval_create("proj-race-cancel", "implementer", "x")
        barrier = threading.Barrier(2, timeout=2)

        def synchronized_set_state(record_token: str, state: str) -> dict[str, object]:
            barrier.wait()
            return original(record_token, state)

        monkeypatch.setattr(_approval, "set_state", synchronized_set_state)
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
            "kind": "policy",
            "name": "block-test",
            "description": "Block test patterns",
            "appliesTo": ["*"],
            "on": "input",
            "when": {"matches": "DELETE PROD"},
            "then": "block",
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


class TestACallLivesOnlyWhilePending:
    CALL = "mcp__outbox__send to=\"ana@example.com\" body=\"hi\""

    def _pending(self, approvals_dir: Path) -> str:
        token = _approval.approval_create("proj", "actor", "summary", call=self.CALL)
        assert _approval.approval_get(token)["call"] == self.CALL
        return token

    def test_a_grant_removes_it(self, approvals_dir: Path) -> None:
        token = self._pending(approvals_dir)
        _approval.approval_grant(token, channel="cli")
        record = _approval.approval_get(token)
        assert record["state"] == "granted" and "call" not in record

    def test_a_deny_removes_it(self, approvals_dir: Path) -> None:
        token = self._pending(approvals_dir)
        _approval.approval_deny(token, channel="cli")
        record = _approval.approval_get(token)
        assert record["state"] == "denied" and "call" not in record

    def test_an_expiry_removes_it(self, approvals_dir: Path) -> None:
        token = self._pending(approvals_dir)
        assert _approval.expire_approval(token)
        assert "call" not in _approval.approval_get(token)

    def test_an_approval_without_a_call_has_no_key(self, approvals_dir: Path) -> None:
        token = _approval.approval_create("proj", "actor", "summary")
        assert "call" not in _approval.approval_get(token)
