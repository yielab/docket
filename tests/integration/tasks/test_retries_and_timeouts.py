"""Retries + configurable timeouts (turn vs verify decoupled).

Three layers: TestFailureKindClassification covers ``TurnResult``'s backward-compat default for
callers that construct it positionally without ``failure_kind``; TestOneTurnPerHop drives
``dispatch_task`` directly (no persisted queue) to show a hop runs its turn once whatever its
failure (a transient request failure is retried inside the turn, so the hop's ``attempts`` is
``1 + request_retries``), and that a non-zero exit or an unretryable kind never retries;
TestTimeoutResolution shows turn vs verify timeouts resolve and apply independently.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
from pathlib import Path
from typing import Any

import pytest
from tests.support import home as _support_home
from tests.support.fakes import FakeJail
from tests.support.pods import build_pod
from tests.support.tasks import stored_task, update_task
from tests.support.trace import trace_events as _trace_events

from docket.agent import ports as _rd
from docket.agent import session as _session
from docket.hops.application import driver_support as _driver_support
from docket.hops.application import executor as _executor
from docket.hops.application import sweep as _sweep
from docket.hops.application import usage as _usage
from docket.hops.gates import pre_hop as _pre_hop_c
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel import clock as _clock
from docket.kernel.home import Home, current_home, use_home
from docket.kernel.ports import jail as _jail
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.domain import task as _task
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import settings as _settings

_hermetic = _support_home.hermetic_trace_on

SUBJECT = "docket.hops.application.sweep"

# ── hermetic environment (mirrors test_verify_gate.py / test_hop_carryover.py) ──


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = current_home().projects_dir / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
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


def _seed_pod(tmp_path: Path, project: str = "demo") -> Path:
    """Full pod via ``build_pod`` (a real persisted TASK_LIST.json queue) — used
    only by the ``dispatch_pod``-level integration tests (stale-claim + timeouts
    that read the Lead's meta), not the direct ``dispatch_task`` unit tests."""
    build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return current_home().root


# ── failure_kind classification ────────────────────────────────────────────────
#
# There is no daemon-facing driver and no subprocess-backed `agent_run` to
# classify failures through. `models/adapters/openai_http.py`'s `OpenAIChatClient`
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
        res = _rd.TurnResult(False, "", {}, "boom")
        assert res.failure_kind is None


# ── retry policy: which kinds are retryable ───────────────────────────────────────


class TestRetryPolicy:
    def test_unknown_role_falls_back_to_default_budget(self) -> None:
        assert (
            _settings.retries_for_role("some-future-role")
            == current_home().dispatch_retries_default
        )


# ── dispatch_task: the retry loop itself (direct call, no persisted queue) ────────


class _TimeoutSpy:
    """A runner that records the timeout each turn is given and always succeeds."""

    def __init__(self) -> None:
        self.values: list[int] = []

    def runner(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        self.values.append(timeout)
        return _rd.TurnResult(True, "done", {})


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
        seq = self.script.get(role, [_rd.TurnResult(True, "done", {})])
        idx = min(len([c for c in self.calls if c[0] == role]) - 1, len(seq) - 1)
        return seq[idx]


class TestOneTurnPerHop:
    def test_a_transient_failure_is_not_run_again_by_the_hop(self, tmp_path: Path) -> None:
        """The driver reports the retries it made inside the turn; the hop runs the turn once and
        records ``1 + request_retries`` attempts, with no hop-level retry event."""
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        runner = _ScriptedRunner(
            {
                "implementer": [
                    _rd.TurnResult(
                        False, "", {}, "boom", failure_kind="daemon_error", request_retries=2
                    )
                ]
            }
        )
        task = TaskRecord(id="t1", description="work")
        res = _executor.dispatch_task("myapp", task, runner=runner)
        assert res.status == "failed"
        impl_hop = next(h for h in res.hops if h.role == "implementer")
        assert impl_hop.attempts == 3 and impl_hop.ok is False
        assert len([c for c in runner.calls if c[0] == "implementer"]) == 1
        assert [e for e in _trace_events("myapp") if e["event_type"] == "hop_retry"] == []

    def test_a_turn_that_retried_nothing_records_one_attempt(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        task = TaskRecord(id="t1b", description="work")
        res = _executor.dispatch_task("myapp", task, runner=_ScriptedRunner({}))
        assert res.status == "done"
        assert all(h.attempts == 1 for h in res.hops)

    def test_the_roles_retry_budget_travels_to_the_turn(self, tmp_path: Path) -> None:
        """The loop reads the count from the hop's environment, as it reads the timeout's owner."""
        tuned = dataclasses.replace(current_home(), dispatch_retries_by_role=(("implementer", 5),))
        seen: dict[str, str | None] = {}

        def _runner(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            seen[agent_id.rsplit("-", 1)[-1]] = (env or {}).get(_rd.DOCKET_HOP_REQUEST_RETRIES)
            return _rd.TurnResult(True, "done", {})

        with use_home(tuned):
            _write_meta("myapp-lead")
            _write_meta("myapp-implementer")
            task = TaskRecord(id="t1c", description="work")
            _executor.dispatch_task("myapp", task, runner=_runner)
        assert seen["implementer"] == "5"
        assert seen["lead"] == str(tuned.dispatch_retries_default)

    def test_a_failed_turn_that_grew_the_session_is_not_followed_by_a_continuation(
        self, tmp_path: Path
    ) -> None:
        """A transport retry resends the request; nothing above the loop sends a second turn."""
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        runner = _PersistingRunner(rounds=2)
        task = TaskRecord(id="t9", description="build the widget")
        res = _executor.dispatch_task("myapp", task, runner=runner)
        assert res.status == "failed"
        assert len(runner.messages) == 1 and "build the widget" in runner.messages[0]

    def test_a_loop_wall_clock_stop_is_tried_once(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        calls: list[str] = []
        stop = _rd.BudgetStop("time", 300, 301, "default")

        def _runner(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            calls.append(agent_id)
            if not agent_id.endswith("implementer"):
                return _rd.TurnResult(True, "done", {})
            return _rd.TurnResult(
                False,
                "",
                {},
                "exceeded wall_clock_timeout_s=300",
                failure_kind="budget_exhausted",
                stop_reason="timeout",
                budget_stop=stop,
            )

        task = TaskRecord(id="t2b", description="work")
        res = _executor.dispatch_task("myapp", task, runner=_runner)
        assert res.status == "failed"
        impl_hop = next(h for h in res.hops if h.role == "implementer")
        assert impl_hop.attempts == 1
        assert calls.count("myapp-implementer") == 1
        assert res.failure_kind == "budget"
        assert impl_hop.budget is not None
        assert impl_hop.budget.model_dump(by_alias=True) == {
            "bound": "time",
            "limit": 300,
            "used": 301,
            "source": "default",
            "raise": "AGENT_LOOP_WALL_CLOCK_TIMEOUT_S",
            "treeChanged": False,
        }

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
                return _rd.TurnResult(True, "done", {})
            return _rd.TurnResult(False, "", {}, "exit 1", failure_kind="nonzero_exit")

        task = TaskRecord(id="t3", description="work")
        res = _executor.dispatch_task("myapp", task, runner=_runner)
        assert res.status == "failed"
        impl_hop = next(h for h in res.hops if h.role == "implementer")
        assert impl_hop.attempts == 1
        assert calls.count("myapp-implementer") == 1

    def test_unparseable_reviewer_verdict_is_not_a_retry_case(self, tmp_path: Path) -> None:
        """A bad *verdict* (the structural Reviewer gate) is a real answer too —
        nothing about the retry loop should touch it (ok=True, just a bad verdict)."""
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        _write_meta("myapp-reviewer")
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
            output = "garbage, no verdict" if role == "reviewer" else "done"
            return _rd.TurnResult(True, output, {})

        task = TaskRecord(id="t4", description="work")
        res = _executor.dispatch_task("myapp", task, runner=_runner)
        assert res.status == "failed"
        assert "unparseable" in res.reason
        # The single re-ask for a verdict line is not a retry: one attempt, one extra request.
        assert calls.count("myapp-reviewer") == 2
        assert next(h for h in res.hops if h.role == "reviewer").attempts == 1


# ── timeout resolution: turn vs verify, independently settable and applied ────────


class _PersistingRunner:
    """A fake driver whose implementer turns append *rounds* messages to the step session on the
    first attempt (when it fails with *kind*) and record every message it is sent."""

    def __init__(self, rounds: int, kind: str = "daemon_error"):
        self.rounds = rounds
        self.kind = kind
        self.messages: list[str] = []

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        if not agent_id.endswith("implementer"):
            return _rd.TurnResult(True, "done", {})
        self.messages.append(message)
        if len(self.messages) == 1:
            _session.append_messages(
                session_key,
                [_rd.user(message), _rd.assistant("started")][: self.rounds],
            )
            return _rd.TurnResult(False, "", {}, "dropped", failure_kind=self.kind)
        return _rd.TurnResult(True, "done", {})


class TestTimeoutResolution:
    def test_defaults_to_the_machine_timeout_when_nothing_set(self) -> None:
        _write_meta("myapp-lead")
        assert _settings.resolve_timeout(None, _settings.pod_turn_timeout("myapp")) == 300

    def test_the_machine_timeout_is_the_wall_clock_variable(self) -> None:
        _write_meta("myapp-lead")
        with use_home(dataclasses.replace(current_home(), agent_loop_wall_clock_timeout_s=45.0)):
            assert _settings.resolve_timeout(None, _settings.pod_turn_timeout("myapp")) == 45
            assert _settings.resolve_timeout(None, 7) == 7

    def test_a_hop_with_nothing_declared_gets_the_wall_clock_variable(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        seen = _TimeoutSpy()
        with use_home(dataclasses.replace(current_home(), agent_loop_wall_clock_timeout_s=45.0)):
            task = TaskRecord(id="t45", description="work")
            res = _executor.dispatch_task("myapp", task, runner=seen.runner)
        assert res.status == "done"
        assert seen.values and set(seen.values) == {45}

    def test_a_pod_turn_timeout_wins_whatever_the_environment_holds(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": 900})
        _write_meta("myapp-implementer")
        seen = _TimeoutSpy()
        with use_home(dataclasses.replace(current_home(), agent_loop_wall_clock_timeout_s=45.0)):
            _queue.enqueue_task_once("myapp", "work", channel="http")
            results = _sweep.dispatch_pod("myapp", runner=seen.runner)
        assert [r.status for r in results] == ["done"]
        assert seen.values and set(seen.values) == {900}

    def test_a_step_timeout_wins_over_the_pod(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": 900})
        _write_meta("myapp-implementer")
        seen = _TimeoutSpy()
        spec = _pipeline.PipelineSpec(
            name="solo", steps=[_step.Step(id="build", role="implementer", timeout=1200)]
        )
        task = TaskRecord(id="t12", description="work")
        _executor.dispatch_task("myapp", task, runner=seen.runner, spec=spec)
        assert seen.values == [1200]

    def test_the_server_wide_variables_are_gone(self) -> None:
        home = Home.from_environ({"DISPATCH_TURN_TIMEOUT_S": "5", "DISPATCH_VERIFY_TIMEOUT_S": "6"})
        assert not any(
            "dispatch_turn" in f.name or "dispatch_verify" in f.name
            for f in dataclasses.fields(home)
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
        assert _settings.resolve_timeout(90, _settings.pod_turn_timeout("myapp")) == 90

    def test_invalid_lead_meta_value_refuses_instead_of_defaulting(self) -> None:
        _write_meta("myapp-lead", {"turnTimeoutS": "not-a-number"})
        with pytest.raises(_task.DispatchError, match="turnTimeoutS"):
            _settings.pod_turn_timeout("myapp")

    def test_turn_and_verify_timeouts_independently_applied_to_calls(
        self, tmp_path: Path, fake_jail: FakeJail
    ) -> None:
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
            return _rd.TurnResult(True, "done", {})

        seen_verify_timeouts: list[int] = []
        real_run_command = _jail.run_command

        def _spy_run_command(cmd: str, cwd: str, timeout: int) -> tuple[int | None, str]:
            seen_verify_timeouts.append(timeout)
            return real_run_command(cmd, cwd, timeout)

        import pytest as _pytest  # local import to keep monkeypatch scoped here

        mp = _pytest.MonkeyPatch()
        try:
            fake_jail.run_command = _spy_run_command
            task = TaskRecord(id="t8", description="work")
            res = _executor.dispatch_task("myapp", task, runner=_runner)
        finally:
            mp.undo()

        assert res.status == "done"
        assert all(t == 11 for t in seen_turn_timeouts)
        assert seen_verify_timeouts == [222]


def _age_claim(project: str, task_id: str, seconds: int) -> None:
    claimed = _clock.now() - _dt.timedelta(seconds=seconds)
    update_task(project, task_id, claimed_at=claimed.isoformat())


class TestAProcessStartRefreshesTheClaim:
    def test_a_started_event_moves_claimed_at(self, tmp_path: Path) -> None:
        """A command the model starts is forward progress, so the claim's clock restarts."""
        _seed_pod(tmp_path)
        _queue.enqueue_task_once("demo", "Run a command", channel="cli")
        claim = _queue.claim_next_task("demo", resume=False)
        assert claim is not None
        task_id = claim.record.id
        _age_claim("demo", task_id, 1000)
        aged = stored_task("demo", task_id).claimed_at

        on_process = _driver_support._build_on_process("demo", "agent:demo:s", "lead", task_id)
        on_process("started", {"pgid": 4242})

        assert stored_task("demo", task_id).claimed_at != aged
        refreshed = _clock.parse_iso(stored_task("demo", task_id).claimed_at or "")
        assert refreshed is not None and (_clock.now() - refreshed).total_seconds() < 60

    def test_an_exited_event_leaves_the_claim_alone(self, tmp_path: Path) -> None:
        _seed_pod(tmp_path)
        _queue.enqueue_task_once("demo", "Run a command", channel="cli")
        claim = _queue.claim_next_task("demo", resume=False)
        assert claim is not None
        task_id = claim.record.id
        _age_claim("demo", task_id, 1000)
        aged = stored_task("demo", task_id).claimed_at

        on_process = _driver_support._build_on_process("demo", "agent:demo:s", "lead", task_id)
        on_process("exited", {"pgid": 4242, "exitCode": 0})

        assert stored_task("demo", task_id).claimed_at == aged

    def test_a_turn_without_a_task_touches_nothing(self, tmp_path: Path) -> None:
        _seed_pod(tmp_path)

        on_process = _driver_support._build_on_process("demo", "agent:demo:s", "lead", "")
        on_process("started", {"pgid": 4242})


class TestTheSweepWaitsOutTheLease:
    def test_a_pod_with_a_long_turn_stays_running_inside_its_lease(self, tmp_path: Path) -> None:
        """`turnTimeoutS: 2400` makes a 1,900 s old claim live, though it is past the 1,800 s floor."""
        _seed_pod(tmp_path)
        _write_meta("demo-lead", {"turnTimeoutS": 2400})
        _queue.enqueue_task_once("demo", "Long turn", channel="cli")
        claim = _queue.claim_next_task("demo", resume=False)
        assert claim is not None
        _age_claim("demo", claim.record.id, 1900)

        _lifecycle.sweep_stale_claims("demo")

        assert stored_task("demo", claim.record.id).status == "running"

    def test_a_claim_past_the_lease_is_still_swept(self, tmp_path: Path) -> None:
        _seed_pod(tmp_path)
        _write_meta("demo-lead", {"turnTimeoutS": 2400})
        _queue.enqueue_task_once("demo", "Long turn", channel="cli")
        claim = _queue.claim_next_task("demo", resume=False)
        assert claim is not None
        _age_claim("demo", claim.record.id, 4000)

        _lifecycle.sweep_stale_claims("demo")

        swept = stored_task("demo", claim.record.id)
        assert swept.status == "failed" and swept.failure_kind == "stale_claim"


# ── regression guard: existing state-machine behaviour is untouched ─────────────


class TestExistingStateMachineBehaviourUnaffected:
    def test_blocked_task_still_never_auto_retries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path)
        _queue.enqueue_task_once("demo", "Too expensive", channel="cli")
        monkeypatch.setattr(_settings, "pod_budget", lambda _p: 1)
        monkeypatch.setattr(_executor, "pod_budget", lambda _p: 1)
        monkeypatch.setattr(_usage, "pod_counted_tokens", lambda _p: 5)
        monkeypatch.setattr(_pre_hop_c, "pod_counted_tokens", lambda _p: 5)

        def _runner(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            return _rd.TurnResult(True, "done", {})

        res = _sweep.dispatch_pod("demo", runner=_runner)[0]
        assert res.status == "blocked"
        assert _sweep.dispatch_pod("demo", runner=_runner) == []
