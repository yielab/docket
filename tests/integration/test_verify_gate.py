"""Deterministic pre-merge verification gate.

Three layers:
  * TestRunVerifyCmd      — system adapter: pass/fail/timeout/error cases.
  * TestDispatchVerifyGate — dispatch integration: verifyCmd wired into the
    pipeline (pass→done, fail→verification_failed trace + task failed,
    unset→a traced skip plus the hop's own ``verification_skipped`` flag,
    never a bare ``print()``, output redacted in trace).
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from typing import Any

import pytest
from tests.support import home as _support_home
from tests.support.pods import write_meta_3 as _write_meta
from tests.support.trace import trace_events as _trace_events

from docket.agent import ports as _rd
from docket.hops.application import record as _record
from docket.kernel.ports import jail as _jail
from docket.pipeline.application import executor as _executor
from docket.sandbox.launch import _VERIFY_MAX_OUTPUT
from docket.teams import fleet as _fleet

_hermetic = _support_home.hermetic_3

SUBJECT = "docket.agent"

# ── hermetic helpers (mirror test_pod_provisioning.py) ───────────────────────


# ── pure system adapter tests ─────────────────────────────────────────────────


class TestRunCommand:
    def test_passing_command_exits_zero(self, tmp_path: Path) -> None:
        code, _ = _jail.run_command("true", str(tmp_path))
        assert code == 0

    def test_failing_command_exits_nonzero(self, tmp_path: Path) -> None:
        code, _ = _jail.run_command("false", str(tmp_path))
        assert code == 1

    def test_output_captured_on_pass(self, tmp_path: Path) -> None:
        code, output = _jail.run_command("echo hello", str(tmp_path))
        assert code == 0
        assert "hello" in output

    def test_output_captured_on_fail(self, tmp_path: Path) -> None:
        # Write something to stderr then exit non-zero.
        code, output = _jail.run_command("echo fail-output >&2; exit 1", str(tmp_path))
        assert code == 1
        assert "fail-output" in output

    def test_output_capped_at_max(self, tmp_path: Path) -> None:
        # Generate output beyond the 4 KB cap.
        big = "x" * 10_000
        code, output = _jail.run_command(f"echo '{big}'", str(tmp_path))
        assert code == 0
        assert len(output) <= _VERIFY_MAX_OUTPUT

    def test_timeout_has_no_exit_status(self, tmp_path: Path) -> None:
        code, output = _jail.run_command("sleep 10", str(tmp_path), timeout=1)
        assert code is None
        assert "timed out" in output

    @pytest.mark.skipif(os.name != "posix", reason="process groups are a POSIX concept")
    def test_timeout_leaves_no_orphan_grandchild(self, tmp_path: Path) -> None:
        # The shell backgrounds a grandchild that writes its own pid to a unique marker
        # file, then the outer shell itself waits — so only the grandchild survives a
        # `timeout=1` past the deadline. On the base, `subprocess.run(shell=True, ...)`
        # kills only the immediate `sh` child on TimeoutExpired, leaving this orphan alive.
        pid_file = tmp_path / "grandchild.pid"
        cmd = f"(sleep 30 & echo $! > {pid_file}) & wait"
        code, output = _jail.run_command(cmd, str(tmp_path), timeout=1)
        assert code is None
        assert "timed out" in output

        deadline = time.monotonic() + 2
        pid: int | None = None
        while time.monotonic() < deadline:
            if pid_file.exists() and pid_file.read_text().strip():
                pid = int(pid_file.read_text().strip())
                break
            time.sleep(0.05)
        assert pid is not None, "grandchild never reported its pid"

        try:
            deadline = time.monotonic() + 2
            gone = False
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    gone = True
                    break
                time.sleep(0.05)
            assert gone, f"grandchild pid {pid} is still alive after verify timed out"
        finally:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, 9)

    def test_invalid_cwd_has_no_exit_status(self) -> None:
        code, output = _jail.run_command("true", "/nonexistent/path/xyz")
        assert code is None
        assert output  # some error message

    def test_env_is_merged_over_the_inherited_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_INHERITED_PROBE", "kept")
        code, output = _jail.run_command(
            'echo "$DOCKET_TASK_ID/$DOCKET_INHERITED_PROBE"',
            str(tmp_path),
            env={"DOCKET_TASK_ID": "t-123"},
        )
        assert code == 0
        assert output.strip() == "t-123/kept"

    def test_without_env_the_command_inherits_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_INHERITED_PROBE", "kept")
        code, output = _jail.run_command('echo "$DOCKET_INHERITED_PROBE"', str(tmp_path))
        assert code == 0
        assert output.strip() == "kept"


# ── dispatch integration tests ────────────────────────────────────────────────


class TestDispatchVerifyGate:
    """Hermetic dispatch tests using a fake runner instead of the real daemon."""

    def _fake_runner(self, output: str = "ok", ok: bool = True) -> _record.Runner:
        def _run(
            member_id: str,
            session_id: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            return _rd.TurnResult(ok=ok, output=output, cost_usd=0.0, raw={})

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
        res = _executor.dispatch_task("myapp", task, runner=self._fake_runner())
        assert res.status == "done"

    def test_verify_fail_blocks_done(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "false"})

        task: dict[str, Any] = {
            "id": "t2",
            "description": "do work",
            "status": "pending",
        }
        res = _executor.dispatch_task("myapp", task, runner=self._fake_runner())
        assert res.status == "failed"
        assert "verifyCmd failed" in res.reason

    def test_verify_fail_emits_trace_event(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "false"})

        task: dict[str, Any] = {"id": "t3", "description": "work", "status": "pending"}
        _executor.dispatch_task("myapp", task, runner=self._fake_runner())

        events = _trace_events("myapp")
        types = [e["event_type"] for e in events]
        assert "verification_failed" in types

    def test_verify_fail_trace_contains_cmd(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "false"})

        task: dict[str, Any] = {"id": "t4", "description": "work", "status": "pending"}
        _executor.dispatch_task("myapp", task, runner=self._fake_runner())

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
        _executor.dispatch_task("myapp", task, runner=self._fake_runner())

        events = _trace_events("myapp")
        vf = next(e for e in events if e["event_type"] == "verification_failed")
        assert secret_output not in vf["payload"].get("output", "")
        assert "[REDACTED]" in vf["payload"].get("output", "")

    def test_verify_unset_skips_with_log(self, tmp_path: Path) -> None:
        # No verifyCmd set — the skip must be visible, but that
        # signal was moved out of a bare print() (core/ never prints): it is the
        # hop's own `verification_skipped` flag (rendered by `interfaces/cli/commands/pod.py`)
        # plus a `tool_result` trace event carrying the same fact.
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")  # no verifyCmd

        task: dict[str, Any] = {"id": "t6", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("myapp", task, runner=self._fake_runner())

        # Task still completes (unset is not a failure).
        assert res.status == "done"
        impl_hop = next(h for h in res.hops if h.role == "implementer")
        assert impl_hop.verification_skipped is True

        events = _trace_events("myapp")
        skipped = [
            e
            for e in events
            if e["event_type"] == "tool_result" and e["payload"].get("verification") == "skipped"
        ]
        assert len(skipped) == 1
        assert skipped[0]["payload"]["member"] == "myapp-implementer"

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
        ) -> _rd.TurnResult:
            ran.append(_fleet.meta_get(member_id, "role", "") or member_id)
            return _rd.TurnResult(ok=True, output="ok", cost_usd=0.0, raw={})

        task: dict[str, Any] = {"id": "t7", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("myapp", task, runner=_runner)

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
        ) -> _rd.TurnResult:
            role = _fleet.meta_get(member_id, "role", "") or member_id
            ran.append(role)
            # The reviewer gate requires one line-anchored marker — a real
            # pod-completing run needs a real APPROVE verdict, not just an
            # ok=True subprocess call.
            output = "APPROVE - looks good" if role == "reviewer" else "ok"
            return _rd.TurnResult(ok=True, output=output, cost_usd=0.0, raw={})

        task: dict[str, Any] = {"id": "t8", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("myapp", task, runner=_runner)

        assert res.status == "done"
        assert "reviewer" in ran

    def test_lead_hop_failure_unaffected_by_verify(self, tmp_path: Path) -> None:
        # If the Lead hop itself fails, the verify gate is never reached.
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer", {"verifyCmd": "false"})

        task: dict[str, Any] = {"id": "t9", "description": "work", "status": "pending"}
        res = _executor.dispatch_task(
            "myapp", task, runner=self._fake_runner(ok=False, output="lead error")
        )
        assert res.status == "failed"
        assert "lead hop failed" in res.reason


# ── structural Tester PASS/FAIL gate ──────────────────────────────────────────


class TestDispatchTesterGate:
    """The Tester hop's unambiguous PASS/FAIL marker gates the pipeline: a successful subprocess
    call (``run_res.ok``) only means the Tester ran, not what it found. Exercises the marker
    parser wired into ``dispatch_task`` for a full pod; a pod with no tester is unaffected."""

    def _runner_with_tester_output(self, tester_output: str) -> _record.Runner:
        def _run(
            member_id: str,
            session_id: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            role = _fleet.meta_get(member_id, "role", "") or member_id
            if role == "tester":
                output = tester_output
            elif role == "reviewer":
                # The reviewer gate needs a real APPROVE to reach the Tester
                # hop at all — these tests exercise the Tester gate, not the
                # Reviewer's, so the Reviewer always approves cleanly.
                output = "APPROVE - looks good"
            else:
                output = "ok"
            return _rd.TurnResult(ok=True, output=output, cost_usd=0.0, raw={})

        return _run

    def _fake_runner(self, output: str = "ok", ok: bool = True) -> _record.Runner:
        def _run(
            member_id: str,
            session_id: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            return _rd.TurnResult(ok=ok, output=output, cost_usd=0.0, raw={})

        return _run

    def _seed_full_pod(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        _write_meta("myapp-reviewer")
        _write_meta("myapp-tester")

    def test_tester_pass_allows_done(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt1", "description": "work", "status": "pending"}
        res = _executor.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output("PASS\nall good")
        )
        assert res.status == "done"

    def test_tester_pass_is_case_insensitive(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt1b", "description": "work", "status": "pending"}
        res = _executor.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output("pass — looks good")
        )
        assert res.status == "done"

    def test_tester_fail_blocks_pipeline(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt2", "description": "work", "status": "pending"}
        res = _executor.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output("FAIL\nrepro steps: ...")
        )
        assert res.status == "failed"
        assert res.reason == "tester reported FAIL"

    def test_tester_fail_emits_distinct_trace_event(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt3", "description": "work", "status": "pending"}
        _executor.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output("fail\nbroken")
        )
        events = _trace_events("myapp")
        ev = next(e for e in events if e["event_type"] == "tester_verdict_failed")
        assert ev["payload"]["verdict"] == "fail"

    def test_tester_unparseable_blocks_distinctly_from_fail(self, tmp_path: Path) -> None:
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt4", "description": "work", "status": "pending"}
        res = _executor.dispatch_task(
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
        res = _executor.dispatch_task("myapp", task, runner=self._runner_with_tester_output(""))
        assert res.status == "failed"
        assert "unparseable" in res.reason

    def test_pod_without_tester_is_unaffected(self, tmp_path: Path) -> None:
        # Lean pod (lead + implementer only) — the tester gate code path never runs,
        # so output that doesn't look like PASS/FAIL can't block a pod with no tester.
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        task: dict[str, Any] = {"id": "tt6", "description": "work", "status": "pending"}
        res = _executor.dispatch_task(
            "myapp", task, runner=self._fake_runner(output="no PASS/FAIL marker here")
        )
        assert res.status == "done"

    def test_tester_fail_output_redacted_in_trace(self, tmp_path: Path) -> None:
        secret_output = "FAIL\nMYAPP_API_KEY=sk-ant-1234567890abcdefghijklmnop"
        self._seed_full_pod()
        task: dict[str, Any] = {"id": "tt7", "description": "work", "status": "pending"}
        _executor.dispatch_task(
            "myapp", task, runner=self._runner_with_tester_output(secret_output)
        )
        events = _trace_events("myapp")
        ev = next(e for e in events if e["event_type"] == "tester_verdict_failed")
        assert secret_output not in ev["payload"].get("output", "")
        assert "[REDACTED]" in ev["payload"].get("output", "")
