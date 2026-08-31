"""Audit-log parity for approval grant/deny across all channels.

``approval_grant``/``approval_deny`` already emitted a trace event; they now
also write an ``audit_log()`` entry (action ``approval.grant``/``approval.deny``,
detail carrying ``token=... project=... channel=...``) so ``docket audit`` has
a record of who approved/denied what, and through which surface.

Covers the channel argument and the concrete call sites in this codebase:
  - CLI      (``docket approve`` / ``docket deny``  -> cli/_approve.py, cli/_deny.py)
  - HTTP     (``serve.py``'s POST /approvals/<token> webhook)
  - explicit channel argument (e.g. ``"telegram"``), exercised directly against the core
    function here while the channel adapter has its own integration coverage.

Acceptance criteria:
  - grant/deny via each of the three call sites produces both the existing
    trace event (payload unchanged: ``{"token": token}``) and a new audit-log
    line carrying the correct channel tag
  - suite green
"""

from __future__ import annotations

import json
import stat
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _approve as approve_cli
from docket.cli import _deny as deny_cli
from docket.core import approval as _ap
from docket.core import audit as _audit
from docket.core import trace as _trace
from docket.serve import _DocketHandler

_TEST_TOKEN = "test-serve-token-fd4-xyz789"


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp DOCKET_HOME with all docket-owned store paths repointed."""
    d = tmp_path / ".docket"
    d.mkdir()
    (d / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    monkeypatch.setattr(_cfg, "DOCKET_HOME", d, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", d / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", d / "traces", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "APPROVAL_TIMEOUT", 900, raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", d / "audit.log", raising=True)
    monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
    monkeypatch.delenv("DOCKET_NO_AUDIT", raising=False)
    monkeypatch.delenv("DOCKET_SECRETS_BACKEND", raising=False)
    return d


@pytest.fixture()
def live_server(home: Path):
    """Real ThreadingHTTPServer on a random port, sharing the repointed config."""

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


def _post(url: str, body: dict, token: str | None = None) -> tuple[int, dict]:  # type: ignore[type-arg]
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


def _trace_events(home: Path, project: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for tf in (home / "traces" / project).glob("*.jsonl"):
        events.extend(_trace.read_trace(tf))
    return events


def _last_audit_entry(action: str) -> dict[str, object]:
    entries = [e for e in _audit.read_audit() if e["action"] == action]
    assert entries, f"no audit entries found for action={action}"
    return entries[-1]


def _race_pending_transitions(
    monkeypatch: pytest.MonkeyPatch, *calls: object
) -> list[BaseException | None]:
    """Start two public decisions together at the old read/write seam.

    The barrier is deliberately around ``_set_state``: before W26-C7 both
    callers had already read ``pending`` when they reached it.  The repaired
    implementation keeps that seam but re-checks the state under the store
    lock, so exactly one caller may return normally.
    """
    original = _ap._set_state
    barrier = threading.Barrier(2, timeout=2)

    def synchronized_set_state(token: str, state: str) -> dict[str, object]:
        barrier.wait()
        return original(token, state)

    monkeypatch.setattr(_ap, "_set_state", synchronized_set_state)
    errors: list[BaseException | None] = [None, None]

    def run(index: int, call: object) -> None:
        assert callable(call)
        try:
            call()
        except BaseException as exc:  # the public error/no-op is the oracle
            errors[index] = exc

    threads = [threading.Thread(target=run, args=(index, call)) for index, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    return errors


# ── CLI channel ────────────────────────────────────────────────────────────────


class TestGrantDenyViaCli:
    def test_grant_via_cli_audits_channel_cli(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _ap.approval_create("proj-cli-grant", "implementer", "deploy")
        rc = approve_cli.run_approve(token)
        assert rc == 0

        entry = _last_audit_entry("approval.grant")
        assert entry["detail"] == f"token={token} project=proj-cli-grant channel=cli"

        events = _trace_events(home, "proj-cli-grant")
        grants = [e for e in events if e["event_type"] == "approval_granted"]
        assert len(grants) == 1
        assert grants[0]["payload"] == {"token": token}

    def test_deny_via_cli_audits_channel_cli(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _ap.approval_create("proj-cli-deny", "reviewer", "nope")
        rc = deny_cli.run_deny(token)
        assert rc == 0

        entry = _last_audit_entry("approval.deny")
        assert entry["detail"] == f"token={token} project=proj-cli-deny channel=cli"

        events = _trace_events(home, "proj-cli-deny")
        denies = [e for e in events if e["event_type"] == "approval_denied"]
        assert len(denies) == 1
        assert denies[0]["payload"] == {"token": token}


# ── HTTP channel (serve.py webhook) ─────────────────────────────────────────────


class TestGrantDenyViaHttp:
    def test_grant_via_http_audits_channel_http(
        self, home: Path, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        apr_token = _ap.approval_create("proj-http-grant", "implementer", "deploy")
        status, body = _post(f"{url}/approvals/{apr_token}", {"action": "grant"}, token)
        assert status == 200
        assert body["state"] == "granted"

        entry = _last_audit_entry("approval.grant")
        assert entry["detail"] == f"token={apr_token} project=proj-http-grant channel=http"

        events = _trace_events(home, "proj-http-grant")
        grants = [e for e in events if e["event_type"] == "approval_granted"]
        assert len(grants) == 1
        assert grants[0]["payload"] == {"token": apr_token}

    def test_deny_via_http_audits_channel_http(
        self, home: Path, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        apr_token = _ap.approval_create("proj-http-deny", "reviewer", "nope")
        status, body = _post(f"{url}/approvals/{apr_token}", {"action": "deny"}, token)
        assert status == 200
        assert body["state"] == "denied"

        entry = _last_audit_entry("approval.deny")
        assert entry["detail"] == f"token={apr_token} project=proj-http-deny channel=http"

        events = _trace_events(home, "proj-http-deny")
        denies = [e for e in events if e["event_type"] == "approval_denied"]
        assert len(denies) == 1
        assert denies[0]["payload"] == {"token": apr_token}


# ── explicit channel argument (e.g. a future Telegram call site) ───────────────


class TestExplicitChannelArgument:
    def test_grant_with_explicit_telegram_channel(self, home: Path) -> None:
        token = _ap.approval_create("proj-telegram", "implementer", "deploy")
        _ap.approval_grant(token, channel="telegram")

        entry = _last_audit_entry("approval.grant")
        assert entry["detail"] == f"token={token} project=proj-telegram channel=telegram"

    def test_deny_with_explicit_telegram_channel(self, home: Path) -> None:
        token = _ap.approval_create("proj-telegram-2", "reviewer", "nope")
        _ap.approval_deny(token, channel="telegram")

        entry = _last_audit_entry("approval.deny")
        assert entry["detail"] == f"token={token} project=proj-telegram-2 channel=telegram"

    def test_unspecified_channel_defaults_to_unknown(self, home: Path) -> None:
        token = _ap.approval_create("proj-default", "implementer", "x")
        _ap.approval_grant(token)

        entry = _last_audit_entry("approval.grant")
        assert entry["detail"] == f"token={token} project=proj-default channel=unknown"


# ── atomic terminal decisions ─────────────────────────────────────────────────


class TestAtomicApprovalDecisions:
    def test_grant_deny_race_has_one_winner_and_one_matching_audit_trace_pair(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for iteration in range(12):
            token = _ap.approval_create(f"atomic-opposite-{iteration}", "implementer", "deploy")
            errors = _race_pending_transitions(
                monkeypatch,
                lambda token=token: _ap.approval_grant(token, channel="cli"),
                lambda token=token: _ap.approval_deny(token, channel="cli"),
            )

            assert errors.count(None) == 1
            assert sum(isinstance(error, _ap.ApprovalError) for error in errors) == 1
            assert _ap.approval_get(token)["state"] in {"granted", "denied"}

            events = _trace_events(home, f"atomic-opposite-{iteration}")
            terminal_events = [
                event["event_type"]
                for event in events
                if event["event_type"] in {"approval_granted", "approval_denied"}
            ]
            assert len(terminal_events) == 1
            entries = [
                entry
                for entry in _audit.read_audit()
                if entry["action"] in {"approval.grant", "approval.deny"}
                and f"token={token}" in entry["detail"]
            ]
            assert len(entries) == 1

    def test_grant_grant_race_has_one_winner_and_one_audit_trace_pair(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for iteration in range(12):
            token = _ap.approval_create(f"atomic-grant-{iteration}", "implementer", "deploy")
            errors = _race_pending_transitions(
                monkeypatch,
                lambda token=token: _ap.approval_grant(token, channel="cli"),
                lambda token=token: _ap.approval_grant(token, channel="cli"),
            )

            assert errors.count(None) == 1
            assert sum(isinstance(error, _ap.ApprovalNoop) for error in errors) == 1
            assert _ap.approval_get(token)["state"] == "granted"

            events = _trace_events(home, f"atomic-grant-{iteration}")
            assert [event["event_type"] for event in events].count("approval_granted") == 1
            entries = [
                entry
                for entry in _audit.read_audit()
                if entry["action"] == "approval.grant" and f"token={token}" in entry["detail"]
            ]
            assert len(entries) == 1

    def test_deny_expiry_race_has_one_denial_and_a_stable_sweep_count(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = _ap.approval_create("atomic-expiry", "implementer", "deploy")
        record = _ap.approval_get(token)
        record["created"] = "2000-01-01T00:00:00Z"
        _ap._store.write_json(_ap._approval_path(token), record)
        sweep_counts: list[int] = []
        real_set_state = _ap._set_state

        errors = _race_pending_transitions(
            monkeypatch,
            lambda: _ap.approval_deny(token, channel="cli"),
            lambda: sweep_counts.append(_ap.approval_sweep_expired()),
        )

        assert errors[1] is None
        assert errors[0] is None or isinstance(errors[0], _ap.ApprovalNoop)
        assert sweep_counts in ([0], [1])
        assert _ap.approval_get(token)["state"] == "denied"
        events = _trace_events(home, "atomic-expiry")
        assert [event["event_type"] for event in events].count("approval_denied") == 1
        entries = [
            entry
            for entry in _audit.read_audit()
            if entry["action"] == "approval.deny" and f"token={token}" in entry["detail"]
        ]
        assert len(entries) == 1
        assert stat.S_IMODE(_ap._approval_path(token).stat().st_mode) == 0o600

        # A terminal record is not swept a second time, and an unknown token
        # remains an error with no trace/audit side effect.
        monkeypatch.setattr(_ap, "_set_state", real_set_state)
        assert _ap.approval_sweep_expired() == 0
        with pytest.raises(_ap.ApprovalError):
            _ap.approval_grant("apr-unknown-atomic", channel="cli")
        assert [
            entry for entry in _audit.read_audit() if "token=apr-unknown-atomic" in entry["detail"]
        ] == []


# ── audit never breaks the approval transition ──────────────────────────────────


class TestAuditFailureNeverBreaksApproval:
    def test_audit_kill_switch_removed_still_never_raises(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DOCKET_NO_AUDIT is no longer a kill switch.

        Setting it has no effect — the grant still writes its audit entry.
        What's preserved is best-effort: an audit write failure (missing
        AUDIT_LOG parent dir, see the sibling test below) must never break
        the approval transition itself.
        """
        monkeypatch.setenv("DOCKET_NO_AUDIT", "1")
        token = _ap.approval_create("proj-no-audit", "implementer", "x")
        _ap.approval_grant(token, channel="cli")  # must not raise
        assert _ap.approval_get(token)["state"] == "granted"
        entries = [e for e in _audit.read_audit() if e["action"] == "approval.grant"]
        assert len(entries) == 1
        assert entries[0]["detail"] == f"token={token} project=proj-no-audit channel=cli"

    def test_audit_write_failure_does_not_raise(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing AUDIT_LOG parent dir best-effort creates it rather than
        raising or losing the entry -- nothing external bootstraps
        DOCKET_HOME, so a missing parent just means "first write" (see
        core/audit.py's audit_log() docstring)."""
        monkeypatch.setattr(_cfg, "AUDIT_LOG", home / "nope" / "audit.log", raising=True)
        token = _ap.approval_create("proj-missing-dir", "implementer", "x")
        _ap.approval_grant(token, channel="cli")  # must not raise
        assert _ap.approval_get(token)["state"] == "granted"
        assert (home / "nope" / "audit.log").is_file()
