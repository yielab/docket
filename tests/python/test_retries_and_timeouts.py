"""Retries + configurable timeouts (turn vs verify decoupled).

Three layers:
  * TestFailureKindClassification — ``TurnResult``'s own backward-compat
    default for callers that construct it positionally without mentioning
    ``failure_kind`` (see the failure_kind classification note below for
    where the real classifier coverage now lives).
  * TestHopRetryLoop — ``dispatch_task`` driven directly (no persisted queue,
    mirrors test_verify_gate.py's pattern): a retryable failure (timeout/
    daemon_error) retries up to the role's budget with ``attempts`` persisted
    and a ``hop_retry`` trace event per attempt; a non-zero exit or an
    unretryable kind never retries.
  * TestTimeoutResolution / TestDispatchPodRetryIntegration — turn vs verify
    timeouts are independently resolved and applied, and a retrying task never
    trips the stale-claim sweep (the subtle correctness point here).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import runtime_driver as _rd
from docket.core import trace as _trace

# ── hermetic environment (mirrors test_verify_gate.py / test_hop_carryover.py) ──


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")

    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps({"agents": [], "bindings": []}))

    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", fleet_file, raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", home / "traces", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)


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
        "created": "2026-07-29T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member_id, meta["model"], meta["sessionKey"], "default")


def _trace_events(project: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    traces_dir = _cfg.TRACES_DIR / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    """Full pod via ``build_pod`` (a real persisted TASK_LIST.json queue) — used
    only by the ``dispatch_pod``-level integration tests (stale-claim + timeouts
    that read the Lead's meta), not the direct ``dispatch_task`` unit tests."""
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return _cfg.DOCKET_HOME


def _no_sleep(_seconds: float) -> None:
    """Injected in place of time.sleep so retry-loop tests run instantly."""


# ── failure_kind classification ────────────────────────────────────────────────
#
# There is no daemon-facing driver and no subprocess-backed `agent_run` to
# classify failures through. `edges/adapters/llm.py`'s `OpenAIChatClient`
# (the one shipped `ChatBackend` DocketDriver calls through) is the only
# failure_kind classifier now; its coverage
# (timeout / HTTP-status-based daemon_error/nonzero_exit / invalid_output) is
# in test_llm_port.py's `TestFailureKindClassification`. Only the one
# test below with no dependency on the deleted driver (`TurnResult`'s own
# backward-compat default) is kept.


class TestFailureKindClassification:
    def test_positional_construction_still_works_without_failure_kind(self) -> None:
        """Backward compat: every existing call site constructs positionally with
        4-5 args and never mentions failure_kind — it must still default sanely."""
        res = _rd.TurnResult(False, "", 0.0, {}, "boom")
        assert res.failure_kind is None


# ── retry policy: which kinds are retryable ───────────────────────────────────────


class TestRetryPolicy:
    def test_only_timeout_and_daemon_error_are_retryable(self) -> None:
        assert {"timeout", "daemon_error"} == _dispatch._RETRYABLE_FAILURE_KINDS
        assert "nonzero_exit" not in _dispatch._RETRYABLE_FAILURE_KINDS
        assert "invalid_output" not in _dispatch._RETRYABLE_FAILURE_KINDS

    def test_unknown_role_falls_back_to_default_budget(self) -> None:
        assert _dispatch._retries_for_role("some-future-role") == _cfg.DISPATCH_RETRIES_DEFAULT


# ── dispatch_task: the retry loop itself (direct call, no persisted queue) ────────


class _ScriptedRunner:
    """Returns a scripted sequence of TurnResults for one role, one per call;
    the last entry repeats once the script is exhausted."""

    def __init__(self, script: dict[str, list[_rd.TurnResult]]):
        self.script = script
        self.calls: list[tuple[str, int]] = []  # (role, timeout) per call

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append((role, timeout))
        seq = self.script.get(role, [_rd.TurnResult(True, "done", 0.0, {})])
        idx = min(len([c for c in self.calls if c[0] == role]) - 1, len(seq) - 1)
        return seq[idx]


class TestHopRetryLoop:
    def test_timeout_then_success_retries_and_succeeds(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        runner = _ScriptedRunner(
            {
                "implementer": [
                    _rd.TurnResult(False, "", 0.0, {}, "slow", failure_kind="timeout"),
                    _rd.TurnResult(False, "", 0.0, {}, "slow", failure_kind="timeout"),
                    _rd.TurnResult(True, "done", 0.0, {}),
                ]
            }
        )
        task: dict[str, Any] = {"id": "t1", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=runner, sleep=_no_sleep)
        assert res.status == "done"
        impl_hop = next(h for h in res.hops if h.role == "implementer")
        assert impl_hop.attempts == 3
        assert impl_hop.ok is True
        # 3 real calls were made for the implementer's hop alone.
        assert len([c for c in runner.calls if c[0] == "implementer"]) == 3

    def test_retries_exhausted_then_fails_with_attempts_persisted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(_cfg.DISPATCH_RETRIES_PER_ROLE, "implementer", 2)
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")

        def _always_timeout(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            role = agent_id.rsplit("-", 1)[-1]
            if role != "implementer":
                return _rd.TurnResult(True, "done", 0.0, {})
            return _rd.TurnResult(False, "", 0.0, {}, "slow", failure_kind="timeout")

        task: dict[str, Any] = {"id": "t2", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_always_timeout, sleep=_no_sleep)
        assert res.status == "failed"
        impl_hop = next(h for h in res.hops if h.role == "implementer")
        # 2 retries configured => 3 total attempts (1 first try + 2 retries).
        assert impl_hop.attempts == 3
        assert impl_hop.ok is False

    def test_nonzero_exit_never_retries(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        calls: list[str] = []

        def _runner(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            calls.append(agent_id)
            role = agent_id.rsplit("-", 1)[-1]
            if role != "implementer":
                return _rd.TurnResult(True, "done", 0.0, {})
            return _rd.TurnResult(False, "", 0.0, {}, "exit 1", failure_kind="nonzero_exit")

        task: dict[str, Any] = {"id": "t3", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_runner, sleep=_no_sleep)
        assert res.status == "failed"
        impl_hop = next(h for h in res.hops if h.role == "implementer")
        assert impl_hop.attempts == 1
        assert calls.count("myapp-implementer") == 1

    def test_unparseable_tester_verdict_is_not_a_retry_case(self, tmp_path: Path) -> None:
        """A bad *verdict* (the structural Tester gate) is a real answer too —
        nothing about the retry loop should touch it (ok=True, just a bad verdict)."""
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        _write_meta("myapp-tester")
        calls: list[str] = []

        def _runner(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            calls.append(agent_id)
            role = agent_id.rsplit("-", 1)[-1]
            output = "garbage, no verdict" if role == "tester" else "done"
            return _rd.TurnResult(True, output, 0.0, {})

        task: dict[str, Any] = {"id": "t4", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_runner, sleep=_no_sleep)
        assert res.status == "failed"
        assert "unparseable" in res.reason
        assert calls.count("myapp-tester") == 1

    def test_retry_emits_hop_retry_trace_event_with_attempt_history(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        runner = _ScriptedRunner(
            {
                "implementer": [
                    _rd.TurnResult(False, "", 0.0, {}, "boom", failure_kind="daemon_error"),
                    _rd.TurnResult(True, "done", 0.0, {}),
                ]
            }
        )
        task: dict[str, Any] = {"id": "t5", "description": "work", "status": "pending"}
        _dispatch.dispatch_task("myapp", task, runner=runner, sleep=_no_sleep)

        events = _trace_events("myapp")
        retries = [e for e in events if e["event_type"] == "hop_retry"]
        assert len(retries) == 1
        assert retries[0]["payload"]["attempt"] == 1
        assert retries[0]["payload"]["failure_kind"] == "daemon_error"

    def test_on_retry_callback_fires_once_per_retry(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        runner = _ScriptedRunner(
            {
                "implementer": [
                    _rd.TurnResult(False, "", 0.0, {}, "boom", failure_kind="timeout"),
                    _rd.TurnResult(False, "", 0.0, {}, "boom", failure_kind="timeout"),
                    _rd.TurnResult(True, "done", 0.0, {}),
                ]
            }
        )
        touches: list[None] = []
        task: dict[str, Any] = {"id": "t6", "description": "work", "status": "pending"}
        _dispatch.dispatch_task(
            "myapp",
            task,
            runner=runner,
            sleep=_no_sleep,
            on_retry=lambda: touches.append(None),
        )
        assert len(touches) == 2  # one per retryable failure before the eventual success

    def test_linear_backoff_sleeps_increase_per_attempt(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        runner = _ScriptedRunner(
            {
                "implementer": [
                    _rd.TurnResult(False, "", 0.0, {}, "boom", failure_kind="timeout"),
                    _rd.TurnResult(False, "", 0.0, {}, "boom", failure_kind="timeout"),
                    _rd.TurnResult(True, "done", 0.0, {}),
                ]
            }
        )
        sleeps: list[float] = []
        task: dict[str, Any] = {"id": "t7", "description": "work", "status": "pending"}
        _dispatch.dispatch_task("myapp", task, runner=runner, sleep=lambda s: sleeps.append(s))
        assert sleeps == [
            _cfg.DISPATCH_RETRY_BACKOFF_S * 1,
            _cfg.DISPATCH_RETRY_BACKOFF_S * 2,
        ]


# ── timeout resolution: turn vs verify, independently settable and applied ────────


class TestTimeoutResolution:
    def test_defaults_to_default_timeout_when_nothing_set(self) -> None:
        _write_meta("myapp-lead")
        assert _dispatch._resolve_timeout(None, _dispatch.pod_turn_timeout("myapp")) == (
            _dispatch.DEFAULT_TIMEOUT
        )

    def test_lead_meta_turn_timeout_used_when_set(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": 45})
        assert _dispatch.pod_turn_timeout("myapp") == 45
        assert _dispatch.pod_verify_timeout("myapp") is None

    def test_lead_meta_verify_timeout_independent_of_turn_timeout(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": 45, "verifyTimeoutS": 1200})
        assert _dispatch.pod_turn_timeout("myapp") == 45
        assert _dispatch.pod_verify_timeout("myapp") == 1200

    def test_explicit_override_wins_over_lead_meta(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": 45})
        assert _dispatch._resolve_timeout(90, _dispatch.pod_turn_timeout("myapp")) == 90

    def test_invalid_lead_meta_value_is_ignored(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": "not-a-number"})
        assert _dispatch.pod_turn_timeout("myapp") is None

    def test_turn_and_verify_timeouts_independently_applied_to_calls(self, tmp_path: Path) -> None:
        """End-to-end through dispatch_task: the agent-turn call gets
        turn_timeout, the verifyCmd call gets verify_timeout — never each
        other's value, even when both are configured."""
        _write_meta("myapp-lead", {"turnTimeoutS": 11, "verifyTimeoutS": 222})
        _write_meta("myapp-implementer", {"verifyCmd": "true"})

        seen_turn_timeouts: list[int] = []

        def _runner(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            seen_turn_timeouts.append(timeout)
            return _rd.TurnResult(True, "done", 0.0, {})

        seen_verify_timeouts: list[int] = []
        real_run_verify_cmd = _dispatch._sys.run_verify_cmd

        def _spy_run_verify_cmd(cmd: str, cwd: str, timeout: int) -> tuple[bool, str]:
            seen_verify_timeouts.append(timeout)
            return real_run_verify_cmd(cmd, cwd, timeout)

        import pytest as _pytest  # local import to keep monkeypatch scoped here

        mp = _pytest.MonkeyPatch()
        try:
            mp.setattr(_dispatch._sys, "run_verify_cmd", _spy_run_verify_cmd)
            task: dict[str, Any] = {"id": "t8", "description": "work", "status": "pending"}
            res = _dispatch.dispatch_task("myapp", task, runner=_runner, sleep=_no_sleep)
        finally:
            mp.undo()

        assert res.status == "done"
        assert all(t == 11 for t in seen_turn_timeouts)
        assert seen_verify_timeouts == [222]


# ── interaction with the claim mechanism: a retrying hop must never look like a stale claim ──


class TestRetryDoesNotTripStaleClaimSweep:
    def test_retrying_task_survives_a_concurrent_stale_claim_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The subtle correctness point here: `claimedAt` used to be
        set once at claim time and never touched again mid-hop. A retry loop
        adds backoff sleeps + extra agent-turn timeouts on top of whatever
        earlier hops already took, so a long enough retry run could push the
        elapsed time since the *original* `claimedAt` past CLAIM_STALE_TIMEOUT
        even though the dispatcher is very much alive — and a *second*,
        concurrent `dispatch_pod` call on the same pod (the whole scenario
        claims exist to guard against) would sweep it out from under the first one
        mid-retry.

        Proof, using real relative timing (no fake clock — `_sweep_stale_claims`
        compares against real wall-clock time): the first implementer attempt
        deliberately takes longer than CLAIM_STALE_TIMEOUT before failing
        retryably, so the *original* claim timestamp alone would already read
        as stale by the time the retry happens. The retry loop's `on_retry`
        refreshes `claimedAt` before the (faked, instant) backoff sleep; the
        second attempt then simulates a concurrent dispatcher's sweep landing
        exactly there, mid-retry — it must find a *fresh* `claimedAt` (just
        refreshed) and leave the task alone.
        """
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Retry me")
        # Small but real threshold: the deliberate 0.3s sleep below comfortably
        # exceeds it (proving the *unrefreshed* claim would already be stale),
        # while the near-instant gap between an on_retry refresh and the very
        # next line of Python comfortably does not (generous margin for a
        # loaded CI box — a handful of local filelock read-modify-writes, not
        # network I/O).
        monkeypatch.setattr(_cfg, "CLAIM_STALE_TIMEOUT", 0.1, raising=True)

        import time as _real_time

        calls = {"implementer": 0}

        def _flaky_then_ok(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            role = agent_id.rsplit("-", 1)[-1]
            if role != "implementer":
                return _rd.TurnResult(True, "done", 0.0, {})
            calls["implementer"] += 1
            if calls["implementer"] == 1:
                # This attempt alone already outlasts CLAIM_STALE_TIMEOUT — an
                # un-refreshed claimedAt would read as stale from this point on.
                _real_time.sleep(0.3)
                return _rd.TurnResult(False, "", 0.0, {}, "slow", failure_kind="timeout")
            # Second attempt: simulate a concurrent dispatcher's sweep landing
            # here, immediately after on_retry refreshed claimedAt for the
            # failed first attempt and right before this (successful) retry.
            _dispatch._sweep_stale_claims("demo")
            return _rd.TurnResult(True, "done", 0.0, {})

        results = _dispatch.dispatch_pod("demo", runner=_flaky_then_ok, sleep=_no_sleep)
        assert len(results) == 1
        assert results[0].status == "done"
        assert calls["implementer"] == 2

        tasks = _dispatch.read_tasks("demo")
        assert tasks[0]["status"] == "done"
        assert tasks[0].get("failureKind") != "stale_claim"

        # No stale_claim trace event should have fired for this task.
        trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
        events = [json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()]
        assert not any(e["event_type"] == "stale_claim" for e in events)


# ── regression guard: existing state-machine behaviour is untouched ─────────────


class TestExistingStateMachineBehaviourUnaffected:
    def test_blocked_task_still_never_auto_retries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Too expensive")
        monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)

        def _runner(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            return _rd.TurnResult(True, "done", 0.0, {})

        res = _dispatch.dispatch_pod("demo", runner=_runner)[0]
        assert res.status == "blocked"
        assert _dispatch.dispatch_pod("demo", runner=_runner) == []
