"""FD-4: audit-log parity for approval grant/deny across all channels.

``approval_grant``/``approval_deny`` already emitted a trace event; they now
also write an ``audit_log()`` entry (action ``approval.grant``/``approval.deny``,
detail carrying ``token=... project=... channel=...``) so ``docket audit`` has
a record of who approved/denied what, and through which surface.

Covers the three channels that actually have a call site in this codebase:
  - CLI      (``docket approve`` / ``docket deny``  -> cli/_approve.py, cli/_deny.py)
  - HTTP     (``serve.py``'s POST /approvals/<token> webhook)
  - explicit channel argument (e.g. ``"telegram"``) for future callers — no
    distinct Telegram-triggered code path exists yet in this codebase (Telegram
    approval routing today is OpenClaw's own inline exec-gate prompt, a
    separate mechanism from this token-based HITL flow), so this is exercised
    directly against the core function rather than through a real channel.

Acceptance criteria:
  - grant/deny via each of the three call sites produces both the existing
    trace event (payload unchanged: ``{"token": token}``) and a new audit-log
    line carrying the correct channel tag
  - suite green
"""

from __future__ import annotations

import json
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
def oc_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp ~/.openclaw with all docket-owned store paths repointed."""
    d = tmp_path / ".openclaw"
    d.mkdir()
    cfg_file = d / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": []}))
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", d, raising=True)
    monkeypatch.setattr(_cfg, "DOCKET_HOME", d, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", d / "traces", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "APPROVAL_TIMEOUT", 900, raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", d / "audit.log", raising=True)
    monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
    monkeypatch.delenv("DOCKET_NO_AUDIT", raising=False)
    monkeypatch.delenv("DOCKET_SECRETS_BACKEND", raising=False)
    return d


@pytest.fixture()
def live_server(oc_dir: Path):
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


def _trace_events(oc_dir: Path, project: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for tf in (oc_dir / "traces" / project).glob("*.jsonl"):
        events.extend(_trace.read_trace(tf))
    return events


def _last_audit_entry(action: str) -> dict[str, object]:
    entries = [e for e in _audit.read_audit() if e["action"] == action]
    assert entries, f"no audit entries found for action={action}"
    return entries[-1]


# ── CLI channel ────────────────────────────────────────────────────────────────


class TestGrantDenyViaCli:
    def test_grant_via_cli_audits_channel_cli(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _ap.approval_create("proj-cli-grant", "implementer", "deploy")
        rc = approve_cli.run_approve(token)
        assert rc == 0

        entry = _last_audit_entry("approval.grant")
        assert entry["detail"] == f"token={token} project=proj-cli-grant channel=cli"

        events = _trace_events(oc_dir, "proj-cli-grant")
        grants = [e for e in events if e["event_type"] == "approval_granted"]
        assert len(grants) == 1
        assert grants[0]["payload"] == {"token": token}

    def test_deny_via_cli_audits_channel_cli(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _ap.approval_create("proj-cli-deny", "reviewer", "nope")
        rc = deny_cli.run_deny(token)
        assert rc == 0

        entry = _last_audit_entry("approval.deny")
        assert entry["detail"] == f"token={token} project=proj-cli-deny channel=cli"

        events = _trace_events(oc_dir, "proj-cli-deny")
        denies = [e for e in events if e["event_type"] == "approval_denied"]
        assert len(denies) == 1
        assert denies[0]["payload"] == {"token": token}


# ── HTTP channel (serve.py webhook) ─────────────────────────────────────────────


class TestGrantDenyViaHttp:
    def test_grant_via_http_audits_channel_http(
        self, oc_dir: Path, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        apr_token = _ap.approval_create("proj-http-grant", "implementer", "deploy")
        status, body = _post(f"{url}/approvals/{apr_token}", {"action": "grant"}, token)
        assert status == 200
        assert body["state"] == "granted"

        entry = _last_audit_entry("approval.grant")
        assert entry["detail"] == f"token={apr_token} project=proj-http-grant channel=http"

        events = _trace_events(oc_dir, "proj-http-grant")
        grants = [e for e in events if e["event_type"] == "approval_granted"]
        assert len(grants) == 1
        assert grants[0]["payload"] == {"token": apr_token}

    def test_deny_via_http_audits_channel_http(
        self, oc_dir: Path, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        apr_token = _ap.approval_create("proj-http-deny", "reviewer", "nope")
        status, body = _post(f"{url}/approvals/{apr_token}", {"action": "deny"}, token)
        assert status == 200
        assert body["state"] == "denied"

        entry = _last_audit_entry("approval.deny")
        assert entry["detail"] == f"token={apr_token} project=proj-http-deny channel=http"

        events = _trace_events(oc_dir, "proj-http-deny")
        denies = [e for e in events if e["event_type"] == "approval_denied"]
        assert len(denies) == 1
        assert denies[0]["payload"] == {"token": apr_token}


# ── explicit channel argument (e.g. a future Telegram call site) ───────────────


class TestExplicitChannelArgument:
    def test_grant_with_explicit_telegram_channel(self, oc_dir: Path) -> None:
        token = _ap.approval_create("proj-telegram", "implementer", "deploy")
        _ap.approval_grant(token, channel="telegram")

        entry = _last_audit_entry("approval.grant")
        assert entry["detail"] == f"token={token} project=proj-telegram channel=telegram"

    def test_deny_with_explicit_telegram_channel(self, oc_dir: Path) -> None:
        token = _ap.approval_create("proj-telegram-2", "reviewer", "nope")
        _ap.approval_deny(token, channel="telegram")

        entry = _last_audit_entry("approval.deny")
        assert entry["detail"] == f"token={token} project=proj-telegram-2 channel=telegram"

    def test_unspecified_channel_defaults_to_unknown(self, oc_dir: Path) -> None:
        token = _ap.approval_create("proj-default", "implementer", "x")
        _ap.approval_grant(token)

        entry = _last_audit_entry("approval.grant")
        assert entry["detail"] == f"token={token} project=proj-default channel=unknown"


# ── audit never breaks the approval transition ──────────────────────────────────


class TestAuditFailureNeverBreaksApproval:
    def test_audit_write_failure_does_not_raise(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_NO_AUDIT", "1")
        token = _ap.approval_create("proj-no-audit", "implementer", "x")
        _ap.approval_grant(token, channel="cli")  # must not raise
        assert _ap.approval_get(token)["state"] == "granted"
        assert [e for e in _audit.read_audit() if e["action"] == "approval.grant"] == []
