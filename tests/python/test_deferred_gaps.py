"""Tests for the four deferred Bash→Python migration gaps.

GAP 1  approval emits the right trace events (approval_requested / _granted /
       _denied) with the Bash payload keys, and redacts the action.
GAP 2  docket serve runs the trace/approval sweeps at startup.
GAP 3  trace.redact strips the VALUE of a stored secret (not just secret-shapes).
GAP 4  doctor prints the Brave + Eval-results advisory sections without moving
       the issue count / exit code.

All subsystems read paths from docket.config at call time, so we repoint the
already-imported config attributes at a temp seed and drive the public surfaces
in-process.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import approval as _ap
from docket.core import secrets as _secrets
from docket.core import trace as _trace


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
    monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
    monkeypatch.delenv("DOCKET_SECRETS_BACKEND", raising=False)
    return d


# ── GAP 1: approval trace + redaction ─────────────────────────────────────────


class TestApprovalTrace:
    def _events_for(self, home: Path, project: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for tf in (home / "traces" / project).glob("*.jsonl"):
            events.extend(_trace.read_trace(tf))
        return events

    def test_create_emits_approval_requested(self, home: Path) -> None:
        token = _ap.approval_create("myshop", "programmer", "rm -rf /tmp/x")
        events = self._events_for(home, "myshop")
        reqs = [e for e in events if e["event_type"] == "approval_requested"]
        assert len(reqs) == 1
        payload = reqs[0]["payload"]
        assert isinstance(payload, dict)
        assert payload["token"] == token
        assert "action" in payload
        assert reqs[0]["agent_role"] == "programmer"
        assert reqs[0]["project"] == "myshop"

    def test_grant_emits_approval_granted(self, home: Path) -> None:
        token = _ap.approval_create("myshop", "programmer", "ship it")
        _ap.approval_grant(token)
        events = self._events_for(home, "myshop")
        grants = [e for e in events if e["event_type"] == "approval_granted"]
        assert len(grants) == 1
        assert grants[0]["payload"] == {"token": token}

    def test_deny_emits_approval_denied(self, home: Path) -> None:
        token = _ap.approval_create("myshop", "reviewer", "nope")
        _ap.approval_deny(token)
        events = self._events_for(home, "myshop")
        denies = [e for e in events if e["event_type"] == "approval_denied"]
        assert len(denies) == 1
        assert denies[0]["payload"] == {"token": token}

    def test_action_is_redacted_in_record_and_trace(self, home: Path) -> None:
        action = "deploy with ANTHROPIC_API_KEY=sk-ant-abcdefghijklmnopqrstuvwxyz123456"
        token = _ap.approval_create("myshop", "programmer", action)
        rec = _ap.approval_get(token)
        assert "sk-ant-abcdefghijklmnopqrstuvwxyz123456" not in rec["action"]
        assert "[REDACTED]" in rec["action"]
        events = self._events_for(home, "myshop")
        req = next(e for e in events if e["event_type"] == "approval_requested")
        payload = req["payload"]
        assert isinstance(payload, dict)
        assert "sk-ant-abcdefghijklmnopqrstuvwxyz123456" not in str(payload["action"])

    def test_trace_failure_never_breaks_approval(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_a: object, **_k: object) -> bool:
            raise RuntimeError("trace store down")

        monkeypatch.setattr(_trace, "trace_event", _boom, raising=True)
        token = _ap.approval_create("myshop", "programmer", "still works")
        assert token.startswith("apr-")
        assert _ap.approval_get(token)["state"] == "pending"


# ── GAP 3: trace redacts stored secret values ─────────────────────────────────


class TestStoredSecretRedaction:
    def test_redacts_stored_secret_value(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # File-backend secrets.json maps KEY -> value.
        monkeypatch.setattr(_secrets, "SECRETS_FILE", home / "secrets.json", raising=True)
        secret = "supersecretvalue1234567890"
        (home / "secrets.json").write_text(json.dumps({"MY_TOKEN": secret}))
        out = _trace.redact(f"the token is {secret} ok")
        assert secret not in out
        assert "[REDACTED]" in out

    def test_short_stored_value_not_redacted(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # redact.sh only redacts stored values longer than 8 chars.
        monkeypatch.setattr(_secrets, "SECRETS_FILE", home / "secrets.json", raising=True)
        (home / "secrets.json").write_text(json.dumps({"SHORT": "abc123"}))
        assert _trace.redact("value abc123 here") == "value abc123 here"

    def test_redaction_in_trace_event(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_secrets, "SECRETS_FILE", home / "secrets.json", raising=True)
        secret = "anothersecretvalue0987654321"
        (home / "secrets.json").write_text(json.dumps({"K": secret}))
        _trace.trace_event("p", "s", "r", "tool_call", json.dumps({"text": f"x {secret} y"}))
        events = _trace.read_trace(home / "traces" / "p" / "s.jsonl")
        assert secret not in json.dumps(events)


# ── GAP 2: serve sweeps ───────────────────────────────────────────────────────


class TestServeSweeps:
    def test_run_sweeps_invokes_both(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import docket.serve as serve

        called: list[str] = []
        monkeypatch.setattr(_trace, "sweep_all", lambda: called.append("trace"))
        monkeypatch.setattr(_ap, "approval_sweep_expired", lambda: called.append("appr") or 0)
        serve._run_sweeps()
        assert called == ["trace", "appr"]

    def test_run_sweeps_best_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import docket.serve as serve

        def _boom() -> None:
            raise RuntimeError("down")

        ok: list[str] = []
        monkeypatch.setattr(_trace, "sweep_all", _boom)
        monkeypatch.setattr(_ap, "approval_sweep_expired", lambda: ok.append("appr") or 0)
        # Must not raise despite the first sweep blowing up.
        serve._run_sweeps()
        assert ok == ["appr"]

    def test_run_serve_runs_sweeps_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import docket.serve as serve

        ran: list[str] = []
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: ran.append("startup"))

        class _FakeServer:
            def __init__(self, *_a: object, **_k: object) -> None:
                pass

            def serve_forever(self) -> None:
                raise KeyboardInterrupt

            def server_close(self) -> None:
                pass

        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        serve.run_serve(port=0, interval=30)
        assert ran == ["startup"]


# ── GAP 4: doctor advisory sections ───────────────────────────────────────────
#
# The Brave-browser advisory (_check_brave_browser) scanned for
# `openclaw/browser` processes spawned by the OpenClaw daemon's headless web
# UI. Phase 19 P19-7b deletes the daemon and every openclaw shell-out; there
# is no longer a browser process for docket to observe, so the check itself
# was deleted from cli/_doctor.py (no successor -- daemon-owned capability,
# honestly gone, not silently dropped). Only the eval-results advisory
# (docket-owned) remains below.


class TestDoctorAdvisorySections:
    def test_eval_results_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.cli import _doctor

        results = tmp_path / "tests" / "evals" / "results"
        results.mkdir(parents=True)
        recs = [
            {"role": "programmer", "tier": "economy", "passed": True, "costUsd": 0.001},
            {"role": "programmer", "tier": "premium", "passed": True, "costUsd": 0.02},
        ]
        (results / "2026-06-23.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        monkeypatch.setenv("DOCKET_CLI_ROOT", str(tmp_path))
        rc = _doctor._check_eval_results()
        out = capsys.readouterr().out
        assert rc == 0
        assert "Eval results (2026-06-23)" in out
        assert "programmer" in out

    def test_eval_results_absent_is_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.cli import _doctor

        monkeypatch.setenv("DOCKET_CLI_ROOT", str(tmp_path))  # no results dir
        rc = _doctor._check_eval_results()
        assert rc == 0
        assert capsys.readouterr().out == ""
