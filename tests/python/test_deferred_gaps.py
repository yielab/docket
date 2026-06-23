"""Tests for the four deferred Bash→Python migration gaps.

GAP 1  approval emits the right trace events (approval_requested / _granted /
       _denied) with the Bash payload keys, and redacts the action.
GAP 2  docket serve runs the trace/approval/drift sweeps at startup.
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
from docket.core import drift as _drift
from docket.core import trace as _trace
from docket.edges.adapters import openclaw as _oc


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
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
    monkeypatch.delenv("DOCKET_SECRETS_BACKEND", raising=False)
    monkeypatch.setattr(_drift, "_DRIFT_STATE_FILE", d / "drift-state.json", raising=True)
    return d


# ── GAP 1: approval trace + redaction ─────────────────────────────────────────


class TestApprovalTrace:
    def _events_for(self, oc_dir: Path, project: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for tf in (oc_dir / "traces" / project).glob("*.jsonl"):
            events.extend(_trace.read_trace(tf))
        return events

    def test_create_emits_approval_requested(self, oc_dir: Path) -> None:
        token = _ap.approval_create("myshop", "programmer", "rm -rf /tmp/x")
        events = self._events_for(oc_dir, "myshop")
        reqs = [e for e in events if e["event_type"] == "approval_requested"]
        assert len(reqs) == 1
        payload = reqs[0]["payload"]
        assert isinstance(payload, dict)
        assert payload["token"] == token
        assert "action" in payload
        assert reqs[0]["agent_role"] == "programmer"
        assert reqs[0]["project"] == "myshop"

    def test_grant_emits_approval_granted(self, oc_dir: Path) -> None:
        token = _ap.approval_create("myshop", "programmer", "ship it")
        _ap.approval_grant(token)
        events = self._events_for(oc_dir, "myshop")
        grants = [e for e in events if e["event_type"] == "approval_granted"]
        assert len(grants) == 1
        assert grants[0]["payload"] == {"token": token}

    def test_deny_emits_approval_denied(self, oc_dir: Path) -> None:
        token = _ap.approval_create("myshop", "reviewer", "nope")
        _ap.approval_deny(token)
        events = self._events_for(oc_dir, "myshop")
        denies = [e for e in events if e["event_type"] == "approval_denied"]
        assert len(denies) == 1
        assert denies[0]["payload"] == {"token": token}

    def test_action_is_redacted_in_record_and_trace(self, oc_dir: Path) -> None:
        action = "deploy with ANTHROPIC_API_KEY=sk-ant-abcdefghijklmnopqrstuvwxyz123456"
        token = _ap.approval_create("myshop", "programmer", action)
        rec = _ap.approval_get(token)
        assert "sk-ant-abcdefghijklmnopqrstuvwxyz123456" not in rec["action"]
        assert "[REDACTED]" in rec["action"]
        events = self._events_for(oc_dir, "myshop")
        req = next(e for e in events if e["event_type"] == "approval_requested")
        payload = req["payload"]
        assert isinstance(payload, dict)
        assert "sk-ant-abcdefghijklmnopqrstuvwxyz123456" not in str(payload["action"])

    def test_trace_failure_never_breaks_approval(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_a: object, **_k: object) -> bool:
            raise RuntimeError("trace store down")

        monkeypatch.setattr(_trace, "trace_event", _boom, raising=True)
        token = _ap.approval_create("myshop", "programmer", "still works")
        assert token.startswith("apr-")
        assert _ap.approval_get(token)["state"] == "pending"


# ── GAP 3: trace redacts stored secret values ─────────────────────────────────


class TestStoredSecretRedaction:
    def test_redacts_stored_secret_value(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # File-backend secrets.json maps KEY -> value.
        secret = "supersecretvalue1234567890"
        (oc_dir / "secrets.json").write_text(json.dumps({"MY_TOKEN": secret}))
        out = _trace.redact(f"the token is {secret} ok")
        assert secret not in out
        assert "[REDACTED]" in out

    def test_short_stored_value_not_redacted(self, oc_dir: Path) -> None:
        # redact.sh only redacts stored values longer than 8 chars.
        (oc_dir / "secrets.json").write_text(json.dumps({"SHORT": "abc123"}))
        assert _trace.redact("value abc123 here") == "value abc123 here"

    def test_redaction_in_trace_event(self, oc_dir: Path) -> None:
        secret = "anothersecretvalue0987654321"
        (oc_dir / "secrets.json").write_text(json.dumps({"K": secret}))
        _trace.trace_event("p", "s", "r", "tool_call", json.dumps({"text": f"x {secret} y"}))
        events = _trace.read_trace(oc_dir / "traces" / "p" / "s.jsonl")
        assert secret not in json.dumps(events)


# ── GAP 2: serve sweeps ───────────────────────────────────────────────────────


class TestServeSweeps:
    def test_run_sweeps_invokes_all_three(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import docket.serve as serve

        called: list[str] = []
        monkeypatch.setattr(_trace, "sweep_all", lambda: called.append("trace"))
        monkeypatch.setattr(_ap, "approval_sweep_expired", lambda: called.append("appr") or 0)
        monkeypatch.setattr(_drift, "drift_check_all", lambda: called.append("drift"))
        serve._run_sweeps()
        assert called == ["trace", "appr", "drift"]

    def test_run_sweeps_best_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import docket.serve as serve

        def _boom() -> None:
            raise RuntimeError("down")

        ok: list[str] = []
        monkeypatch.setattr(_trace, "sweep_all", _boom)
        monkeypatch.setattr(_ap, "approval_sweep_expired", lambda: ok.append("appr") or 0)
        monkeypatch.setattr(_drift, "drift_check_all", lambda: ok.append("drift"))
        # Must not raise despite the first sweep blowing up.
        serve._run_sweeps()
        assert ok == ["appr", "drift"]

    def test_run_serve_runs_sweeps_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import docket.serve as serve

        ran: list[str] = []
        monkeypatch.setattr(serve, "_run_sweeps", lambda: ran.append("startup"))

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


# ── GAP 2b: drift_check_all ───────────────────────────────────────────────────


class TestDriftCheckAll:
    def _seed_sessions(self, oc_dir: Path, role: str, statuses: list[str]) -> None:
        pdir = oc_dir / "traces" / "proj"
        pdir.mkdir(parents=True, exist_ok=True)
        for i, status in enumerate(statuses):
            lines = [
                {"ts": "2026-01-01T00:00:00Z", "agent_role": role, "event_type": "session_start"},
                {
                    "ts": "2026-01-01T00:00:01Z",
                    "agent_role": role,
                    "event_type": "session_end",
                    "payload": {"status": status},
                },
            ]
            (pdir / f"s{i:04d}.jsonl").write_text(
                "\n".join(json.dumps(rec) for rec in lines) + "\n"
            )

    def test_drift_emits_alert(self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_cfg, "METRICS_WINDOW", 5, raising=True)
        monkeypatch.setattr(_cfg, "BASELINE_WINDOW", 5, raising=True)
        monkeypatch.setattr(_cfg, "DRIFT_THRESHOLD", 15.0, raising=True)
        # 5 baseline (all success) then 5 current (all failure) → big drop.
        self._seed_sessions(oc_dir, "programmer", ["success"] * 5 + ["failure"] * 5)
        _drift.drift_check_all()
        events: list[dict[str, object]] = []
        for tf in (oc_dir / "traces" / "programmer").glob("*.jsonl"):
            events.extend(_trace.read_trace(tf))
        alerts = [e for e in events if e["event_type"] == "drift_alert"]
        assert len(alerts) == 1
        payload = alerts[0]["payload"]
        assert isinstance(payload, dict)
        assert payload["role"] == "programmer"
        assert payload["baseline_rate"] == 100.0
        assert payload["current_rate"] == 0.0

    def test_no_drift_when_stable(self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_cfg, "METRICS_WINDOW", 5, raising=True)
        monkeypatch.setattr(_cfg, "BASELINE_WINDOW", 5, raising=True)
        self._seed_sessions(oc_dir, "programmer", ["success"] * 10)
        _drift.drift_check_all()
        events: list[dict[str, object]] = []
        for tf in (oc_dir / "traces" / "programmer").glob("*.jsonl"):
            events.extend(_trace.read_trace(tf))
        assert not [e for e in events if e["event_type"] == "drift_alert"]

    def test_cooldown_suppresses_second_alert(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "METRICS_WINDOW", 5, raising=True)
        monkeypatch.setattr(_cfg, "BASELINE_WINDOW", 5, raising=True)
        self._seed_sessions(oc_dir, "programmer", ["success"] * 5 + ["failure"] * 5)
        first = _drift.drift_check_role("programmer")
        assert first is not None
        second = _drift.drift_check_role("programmer")
        assert second is None  # cooldown active


# ── GAP 4: doctor advisory sections ───────────────────────────────────────────


class TestDoctorAdvisorySections:
    def test_brave_section_no_processes(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.cli import _doctor

        class _Res:
            stdout = "USER 1 0.0 0.0 ? ? bash\n"

        import subprocess as sp

        monkeypatch.setattr(sp, "run", lambda *_a, **_k: _Res())
        rc = _doctor._check_brave_browser()
        out = capsys.readouterr().out
        assert rc == 0
        assert "Brave browser: not running" in out

    def test_brave_section_running(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.cli import _doctor

        def _fake_run(cmd: list[str], **_k: object) -> object:
            class _R:
                stdout = ""

            r = _R()
            if cmd[:2] == ["ps", "aux"]:
                r.stdout = "user 1 0 0 ? ? node openclaw/browser/headless\n"
            elif cmd[:2] == ["ps", "-eo"]:
                r.stdout = "  1  120  node openclaw/browser/headless\n"
            return r

        import subprocess as sp

        monkeypatch.setattr(sp, "run", _fake_run)
        rc = _doctor._check_brave_browser()
        out = capsys.readouterr().out
        assert rc == 0
        assert "Brave browser: 1 processes running" in out

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
