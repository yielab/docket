"""CD-2: deterministic pre-merge verification gate.

Three layers:
  * TestRunVerifyCmd      — system adapter: pass/fail/timeout/error cases.
  * TestDispatchVerifyGate — dispatch integration: verifyCmd wired into the
    pipeline (pass→done, fail→verification_failed trace + task failed,
    unset→skip log, output redacted in trace).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import dispatch as _dispatch
from docket.core import trace as _trace
from docket.edges.adapters import openclaw as _oc
from docket.edges.adapters import system as _sys

# ── hermetic helpers (mirror test_pod_provisioning.py) ───────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")

    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))

    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", oc_dir / "traces", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = _cfg.PROJECTS_DIR / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.split("-")[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "modelSource": "policy",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-06-25T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _oc.add_agent(member_id, meta["model"], meta["sessionKey"], "default")


def _trace_events(project: str) -> list[dict[str, Any]]:
    """Collect all trace events for *project* from the trace store."""
    events: list[dict[str, Any]] = []
    traces_dir = _cfg.TRACES_DIR / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


# ── pure system adapter tests ─────────────────────────────────────────────────


class TestRunVerifyCmd:
    def test_passing_command_returns_true(self, tmp_path: Path) -> None:
        passed, _ = _sys.run_verify_cmd("true", str(tmp_path))
        assert passed is True

    def test_failing_command_returns_false(self, tmp_path: Path) -> None:
        passed, _ = _sys.run_verify_cmd("false", str(tmp_path))
        assert passed is False

    def test_output_captured_on_pass(self, tmp_path: Path) -> None:
        passed, output = _sys.run_verify_cmd("echo hello", str(tmp_path))
        assert passed is True
        assert "hello" in output

    def test_output_captured_on_fail(self, tmp_path: Path) -> None:
        # Write something to stderr then exit non-zero.
        passed, output = _sys.run_verify_cmd("echo fail-output >&2; exit 1", str(tmp_path))
        assert passed is False
        assert "fail-output" in output

    def test_output_capped_at_max(self, tmp_path: Path) -> None:
        # Generate output beyond the 4 KB cap.
        big = "x" * 10_000
        passed, output = _sys.run_verify_cmd(f"echo '{big}'", str(tmp_path))
        assert passed is True
        assert len(output) <= _sys._VERIFY_MAX_OUTPUT

    def test_timeout_returns_false(self, tmp_path: Path) -> None:
        passed, output = _sys.run_verify_cmd("sleep 10", str(tmp_path), timeout=1)
        assert passed is False
        assert "timed out" in output

    def test_invalid_cwd_returns_false(self) -> None:
        passed, output = _sys.run_verify_cmd("true", "/nonexistent/path/xyz")
        assert passed is False
        assert output  # some error message


# ── dispatch integration tests ────────────────────────────────────────────────


class TestDispatchVerifyGate:
    """Hermetic dispatch tests using a fake runner instead of the real daemon."""

    def _fake_runner(self, output: str = "ok", ok: bool = True) -> _dispatch.Runner:
        def _run(
            member_id: str,
            session_id: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _oc.AgentRunResult:
            return _oc.AgentRunResult(ok=ok, output=output, cost_usd=0.0, raw={})

        return _run

    def test_verify_pass_allows_done(self, tmp_path: Path) -> None:
        # Lead + Implementer with a verifyCmd that passes.
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "true"})

        task: dict[str, Any] = {
            "id": "t1",
            "description": "do work",
            "status": "pending",
        }
        res = _dispatch.dispatch_task("myapp", task, runner=self._fake_runner())
        assert res.status == "done"

    def test_verify_fail_blocks_done(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "false"})

        task: dict[str, Any] = {
            "id": "t2",
            "description": "do work",
            "status": "pending",
        }
        res = _dispatch.dispatch_task("myapp", task, runner=self._fake_runner())
        assert res.status == "failed"
        assert "verifyCmd failed" in res.reason

    def test_verify_fail_emits_trace_event(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "false"})

        task: dict[str, Any] = {"id": "t3", "description": "work", "status": "pending"}
        _dispatch.dispatch_task("myapp", task, runner=self._fake_runner())

        events = _trace_events("myapp")
        types = [e["event_type"] for e in events]
        assert "verification_failed" in types

    def test_verify_fail_trace_contains_cmd(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "false"})

        task: dict[str, Any] = {"id": "t4", "description": "work", "status": "pending"}
        _dispatch.dispatch_task("myapp", task, runner=self._fake_runner())

        events = _trace_events("myapp")
        vf = next(e for e in events if e["event_type"] == "verification_failed")
        assert vf["payload"]["cmd"] == "false"

    def test_verify_output_redacted_in_trace(self, tmp_path: Path) -> None:
        # A verifyCmd that leaks a secret-shaped value (matches _REDACT_PATTERNS).
        # Pattern: SOME_API_KEY=<value> is caught by the third redaction regex.
        secret_output = "MYAPP_API_KEY=sk-ant-1234567890abcdefghijklmnop"
        cmd = f"echo '{secret_output}'; exit 1"
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": cmd})

        task: dict[str, Any] = {"id": "t5", "description": "work", "status": "pending"}
        _dispatch.dispatch_task("myapp", task, runner=self._fake_runner())

        events = _trace_events("myapp")
        vf = next(e for e in events if e["event_type"] == "verification_failed")
        assert secret_output not in vf["payload"].get("output", "")
        assert "[REDACTED]" in vf["payload"].get("output", "")

    def test_verify_unset_skips_with_log(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # No verifyCmd set — skip should print a visible log line.
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")  # no verifyCmd

        task: dict[str, Any] = {"id": "t6", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=self._fake_runner())

        # Task still completes (unset is not a failure).
        assert res.status == "done"
        out = capsys.readouterr().out
        assert "verification skipped" in out
        assert "verifyCmd not set" in out

    def test_verify_fail_stops_pipeline_before_reviewer(self, tmp_path: Path) -> None:
        # Full pod: lead + implementer + reviewer + tester. Verify fails after
        # implementer — reviewer hop must never run.
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "false"})
        _write_meta("myapp-reviewer")
        _write_meta("myapp-tester")

        ran: list[str] = []

        def _runner(
            member_id: str,
            session_id: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _oc.AgentRunResult:
            ran.append(_oc.meta_get(member_id, "role", "") or member_id)
            return _oc.AgentRunResult(ok=True, output="ok", cost_usd=0.0, raw={})

        task: dict[str, Any] = {"id": "t7", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_runner)

        assert res.status == "failed"
        assert "lead" in ran
        assert "implementer" in ran
        assert "reviewer" not in ran
        assert "tester" not in ran

    def test_verify_pass_continues_to_reviewer(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "true"})
        _write_meta("myapp-reviewer")

        ran: list[str] = []

        def _runner(
            member_id: str,
            session_id: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _oc.AgentRunResult:
            ran.append(_oc.meta_get(member_id, "role", "") or member_id)
            return _oc.AgentRunResult(ok=True, output="ok", cost_usd=0.0, raw={})

        task: dict[str, Any] = {"id": "t8", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_runner)

        assert res.status == "done"
        assert "reviewer" in ran

    def test_lead_hop_failure_unaffected_by_verify(self, tmp_path: Path) -> None:
        # If the Lead hop itself fails, the verify gate is never reached.
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "false"})

        task: dict[str, Any] = {"id": "t9", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task(
            "myapp", task, runner=self._fake_runner(ok=False, output="lead error")
        )
        assert res.status == "failed"
        assert "lead hop failed" in res.reason


# ── FD-2: structural Tester PASS/FAIL gate ───────────────────────────────────


class TestDispatchTesterGate:
    """FD-2: the Tester hop's PASS/FAIL first line is parsed and gates the pipeline.

    A successful subprocess call (``run_res.ok``) only means the Tester agent ran —
    it says nothing about what the Tester found. These tests exercise the marker
    parser wired into ``dispatch_task`` for a full pod (lead+implementer+reviewer+
    tester); a pod with no tester member is unaffected (covered by the lean-pod
    verify-gate tests above, which never seat a tester).
    """

    def _runner_with_tester_output(self, tester_output: str) -> _dispatch.Runner:
        def _run(member_id: str, session_id: str, message: str, timeout: int) -> _oc.AgentRunResult:
            role = _oc.meta_get(member_id, "role", "") or member_id
            output = tester_output if role == "tester" else "ok"
            return _oc.AgentRunResult(ok=True, output=output, cost_usd=0.0, raw={})

        return _run

    def _fake_runner(self, output: str = "ok", ok: bool = True) -> _dispatch.Runner:
        def _run(member_id: str, session_id: str, message: str, timeout: int) -> _oc.AgentRunResult:
            return _oc.AgentRunResult(ok=ok, output=output, cost_usd=0.0, raw={})

        return _run

    def _seed_full_pod(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        _write_meta("myapp-reviewer")
        _write_meta("myapp-tester")

    def test_tester_pass_allows_done(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt1", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output("PASS\nall good")
        )
        assert res.status == "done"

    def test_tester_pass_is_case_insensitive(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt1b", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output("pass — looks good")
        )
        assert res.status == "done"

    def test_tester_fail_blocks_pipeline(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt2", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output("FAIL\nrepro steps: ...")
        )
        assert res.status == "failed"
        assert res.reason == "tester reported FAIL"

    def test_tester_fail_emits_distinct_trace_event(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt3", "description": "work", "status": "pending"}
        _dispatch.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output("fail\nbroken")
        )
        events = _trace_events("myapp")
        ev = next(e for e in events if e["event_type"] == "tester_verdict_failed")
        assert ev["payload"]["verdict"] == "fail"

    def test_tester_unparseable_blocks_distinctly_from_fail(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt4", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output("looks fine to me")
        )
        assert res.status == "failed"
        assert res.reason != "tester reported FAIL"
        assert "unparseable" in res.reason

        events = _trace_events("myapp")
        ev = next(e for e in events if e["event_type"] == "tester_verdict_failed")
        assert ev["payload"]["verdict"] == "unparseable"

    def test_tester_empty_output_is_unparseable_not_fail(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt5", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=self._runner_with_tester_output(""))
        assert res.status == "failed"
        assert "unparseable" in res.reason

    def test_pod_without_tester_is_unaffected(self, tmp_path: Path) -> None:
        # Lean pod (lead + implementer only) — the tester gate code path never runs,
        # so output that doesn't look like PASS/FAIL can't block a pod with no tester.
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        task: dict[str, Any] = {"id": "tt6", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task(
            "myapp", task, runner=self._fake_runner(output="no PASS/FAIL marker here")
        )
        assert res.status == "done"

    def test_tester_fail_output_redacted_in_trace(self, tmp_path: Path) -> None:
        secret_output = "FAIL\nMYAPP_API_KEY=sk-ant-1234567890abcdefghijklmnop"
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt7", "description": "work", "status": "pending"}
        _dispatch.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output(secret_output)
        )
        events = _trace_events("myapp")
        ev = next(e for e in events if e["event_type"] == "tester_verdict_failed")
        assert secret_output not in ev["payload"].get("output", "")
        assert "[REDACTED]" in ev["payload"].get("output", "")
