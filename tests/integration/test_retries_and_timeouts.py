"""Retries + configurable timeouts (turn vs verify decoupled).

Three layers: TestFailureKindClassification covers ``TurnResult``'s backward-compat default for
callers that construct it positionally without ``failure_kind``; TestHopRetryLoop drives
``dispatch_task`` directly (no persisted queue) to show a retryable failure (timeout/daemon_error)
retries up to the role's budget with ``attempts`` persisted and a ``hop_retry`` trace event per
attempt, while a non-zero exit or an unretryable kind never retries; TestTimeoutResolution /
TestDispatchPodRetryIntegration show turn vs verify timeouts resolve and apply independently, and
that a retrying task never trips the stale-claim sweep.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.pods import build_pod

from docket.agent import ports as _rd
from docket.core import dispatch as _dispatch
from docket.hops.application import runner as _application_runner
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, current_home, use_home
from docket.observability import trace as _trace
from docket.pipeline.application import executor as _executor
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.tasks.domain import task as _task
from docket.teams import fleet as _fleet
from docket.teams import settings as _settings

SUBJECT = "docket.core"

# ── hermetic environment (mirrors test_verify_gate.py / test_hop_carryover.py) ──


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")

    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps({"agents": [], "bindings": []}))

    with use_home(Home(home)):
        yield


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = current_home().projects_dir / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.split("-")[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-29T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member_id)


def _trace_events(project: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    traces_dir = current_home().traces_dir / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


def _seed_pod(tmp_path: Path, project: str = "demo") -> Path:
    """Full pod via ``build_pod`` (a real persisted TASK_LIST.json queue) — used
    only by the ``dispatch_pod``-level integration tests (stale-claim + timeouts
    that read the Lead's meta), not the direct ``dispatch_task`` unit tests."""
    build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return current_home().root


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
        assert {"timeout", "daemon_error"} == _application_runner._RETRYABLE_FAILURE_KINDS
        assert "nonzero_exit" not in _application_runner._RETRYABLE_FAILURE_KINDS
        assert "invalid_output" not in _application_runner._RETRYABLE_FAILURE_KINDS

    def test_unknown_role_falls_back_to_default_budget(self) -> None:
        assert (
            _settings._retries_for_role("some-future-role")
            == current_home().dispatch_retries_default
        )


# ── dispatch_task: the retry loop itself (direct call, no persisted queue) ────────


class _ScriptedRunner:
    """Returns a scripted sequence of TurnResults for one role, one per call;
    the last entry repeats once the script is exhausted."""

    def __init__(self, script: dict[str, list[_rd.TurnResult]]):
        self.script = script
        self.calls: list[tuple[str, int]] = []  # (role, timeout) per call
        self.session_keys: list[tuple[str, str]] = []  # (role, durable history key)

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
        self.session_keys.append((role, session_key))
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
        res = _executor.dispatch_task("myapp", task, runner=runner, sleep=_no_sleep)
        assert res.status == "done"
        impl_hop = next(h for h in res.hops if h.role == "implementer")
        assert impl_hop.attempts == 3
        assert impl_hop.ok is True
        # 3 real calls were made for the implementer's hop alone.
        assert len([c for c in runner.calls if c[0] == "implementer"]) == 3
        implementer_keys = [key for role, key in runner.session_keys if role == "implementer"]
        lead_key = next(key for role, key in runner.session_keys if role == "lead")
        assert len(set(implementer_keys)) == 1
        assert implementer_keys[0] != lead_key

    def test_retries_exhausted_then_fails_with_attempts_persisted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(current_home().dispatch_retries_per_role, "implementer", 2)
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
        res = _executor.dispatch_task("myapp", task, runner=_always_timeout, sleep=_no_sleep)
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
        res = _executor.dispatch_task("myapp", task, runner=_runner, sleep=_no_sleep)
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
        res = _executor.dispatch_task("myapp", task, runner=_runner, sleep=_no_sleep)
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
        _executor.dispatch_task("myapp", task, runner=runner, sleep=_no_sleep)

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
        _executor.dispatch_task(
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
        _executor.dispatch_task("myapp", task, runner=runner, sleep=lambda s: sleeps.append(s))
        assert sleeps == [
            current_home().dispatch_retry_backoff_s * 1,
            current_home().dispatch_retry_backoff_s * 2,
        ]

    def test_retry_after_wins_over_backoff_when_longer(self, tmp_path: Path) -> None:
        """A daemon_error carrying retry_after_s=7 (e.g. a 429 with Retry-After: 7) waits
        the full 7s even though the linear backoff for attempt 1 would only be 2s."""
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        runner = _ScriptedRunner(
            {
                "implementer": [
                    _rd.TurnResult(
                        False, "", 0.0, {}, "boom", failure_kind="daemon_error", retry_after_s=7.0
                    ),
                    _rd.TurnResult(True, "done", 0.0, {}),
                ]
            }
        )
        sleeps: list[float] = []
        task: dict[str, Any] = {"id": "t9", "description": "work", "status": "pending"}
        res = _executor.dispatch_task(
            "myapp", task, runner=runner, sleep=lambda s: sleeps.append(s)
        )
        assert res.status == "done"
        assert sleeps == [7.0]

        events = _trace_events("myapp")
        retries = [e for e in events if e["event_type"] == "hop_retry"]
        assert retries[0]["payload"]["retry_after_s"] == 7.0

    def test_retry_after_is_capped_at_the_max_wait_ceiling(self, tmp_path: Path) -> None:
        """A retry_after_s far past the ceiling (e.g. a 429 asking for an hour) never
        stalls a hop past DISPATCH_RETRY_MAX_WAIT_S."""
        with use_home(dataclasses.replace(current_home(), dispatch_retry_max_wait_s=60.0)):
            _write_meta("myapp-lead")
            _write_meta("myapp-implementer")
            runner = _ScriptedRunner(
                {
                    "implementer": [
                        _rd.TurnResult(
                            False,
                            "",
                            0.0,
                            {},
                            "boom",
                            failure_kind="daemon_error",
                            retry_after_s=3600.0,
                        ),
                        _rd.TurnResult(True, "done", 0.0, {}),
                    ]
                }
            )
            sleeps: list[float] = []
            task: dict[str, Any] = {"id": "t10", "description": "work", "status": "pending"}
            res = _executor.dispatch_task(
                "myapp", task, runner=runner, sleep=lambda s: sleeps.append(s)
            )
            assert res.status == "done"
            assert sleeps == [60.0]


# ── timeout resolution: turn vs verify, independently settable and applied ────────


class TestTimeoutResolution:
    def test_defaults_to_default_timeout_when_nothing_set(self) -> None:
        _write_meta("myapp-lead")
        assert _settings._resolve_timeout(None, _settings.pod_turn_timeout("myapp")) == (
            _settings.DEFAULT_TIMEOUT
        )

    def test_lead_meta_turn_timeout_used_when_set(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": 45})
        assert _settings.pod_turn_timeout("myapp") == 45
        assert _settings.pod_verify_timeout("myapp") is None

    def test_lead_meta_verify_timeout_independent_of_turn_timeout(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": 45, "verifyTimeoutS": 1200})
        assert _settings.pod_turn_timeout("myapp") == 45
        assert _settings.pod_verify_timeout("myapp") == 1200

    def test_explicit_override_wins_over_lead_meta(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": 45})
        assert _settings._resolve_timeout(90, _settings.pod_turn_timeout("myapp")) == 90

    def test_invalid_lead_meta_value_refuses_instead_of_defaulting(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": "not-a-number"})
        with pytest.raises(_task.DispatchError, match="turnTimeoutS"):
            _settings.pod_turn_timeout("myapp")

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
        real_run_command = _dispatch._sys.run_command

        def _spy_run_command(cmd: str, cwd: str, timeout: int) -> tuple[int | None, str]:
            seen_verify_timeouts.append(timeout)
            return real_run_command(cmd, cwd, timeout)

        import pytest as _pytest  # local import to keep monkeypatch scoped here

        mp = _pytest.MonkeyPatch()
        try:
            mp.setattr(_dispatch._sys, "run_command", _spy_run_command)
            task: dict[str, Any] = {"id": "t8", "description": "work", "status": "pending"}
            res = _executor.dispatch_task("myapp", task, runner=_runner, sleep=_no_sleep)
        finally:
            mp.undo()

        assert res.status == "done"
        assert all(t == 11 for t in seen_turn_timeouts)
        assert seen_verify_timeouts == [222]


# ── interaction with the claim mechanism: a retrying hop must never look like a stale claim ──


class TestRetryDoesNotTripStaleClaimSweep:
    def test_retrying_task_survives_a_concurrent_stale_claim_sweep(self, tmp_path: Path) -> None:
        """Proves `on_retry` refreshes `claimedAt` mid-hop: without it, stacked backoff sleeps
        and agent-turn timeouts could push time since the *original* claim past
        CLAIM_STALE_TIMEOUT even though the dispatcher is alive, letting a concurrent
        `dispatch_pod` call sweep the task out from under a live retry. Verified with real
        wall-clock timing: the first implementer attempt is made to outlast
        CLAIM_STALE_TIMEOUT before failing retryably, so only a refreshed `claimedAt` lets the
        second attempt's simulated concurrent sweep leave the task alone."""
        oc_dir = _seed_pod(tmp_path)
        _queue.enqueue_task_once("demo", "Retry me", channel="cli")
        # Small but real threshold: the deliberate 0.3s sleep below comfortably
        # exceeds it (proving the *unrefreshed* claim would already be stale),
        # while the near-instant gap between an on_retry refresh and the very
        # next line of Python comfortably does not (generous margin for a
        # loaded CI box — a handful of local filelock read-modify-writes, not
        # network I/O).
        with use_home(dataclasses.replace(current_home(), claim_stale_timeout=0.1)):
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
                _lifecycle._sweep_stale_claims("demo")
                return _rd.TurnResult(True, "done", 0.0, {})

            results = _sweep.dispatch_pod("demo", runner=_flaky_then_ok, sleep=_no_sleep)
            assert len(results) == 1
            assert results[0].status == "done"
            assert calls["implementer"] == 2

            tasks = _queue.read_tasks("demo")
            assert tasks[0]["status"] == "done"
            assert tasks[0].get("failureKind") != "stale_claim"

            # No stale_claim trace event should have fired for this task.
            trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
            events = [
                json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()
            ]
            assert not any(e["event_type"] == "stale_claim" for e in events)


# ── regression guard: existing state-machine behaviour is untouched ─────────────


class TestExistingStateMachineBehaviourUnaffected:
    def test_blocked_task_still_never_auto_retries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path)
        _queue.enqueue_task_once("demo", "Too expensive", channel="cli")
        monkeypatch.setattr(_settings, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_settings, "pod_recorded_cost", lambda _p: 5.0)

        def _runner(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            return _rd.TurnResult(True, "done", 0.0, {})

        res = _sweep.dispatch_pod("demo", runner=_runner)[0]
        assert res.status == "blocked"
        assert _sweep.dispatch_pod("demo", runner=_runner) == []
