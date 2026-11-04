"""Budget honesty — auto-pause, the paused-flag type bug, tokens and no dollar figure.

Covers: ``AgentMeta.coerce_paused`` (typed accessor fixing the string/bool
display bug: a writer stores a real ``bool`` while old code compared it to the string
``"true"``, which ``True`` never equals); the pause writer (per-hop budget gate marks the pod's
Lead ``paused=True, pausedReason="budget"`` at the cap, counted in tokens, so it trips on any
model); claim-time refusal (``claim_next_task`` refuses every claim for a paused
pod outright -- a ``paused_refused`` trace event, no wasted turn -- until resumed); and that
status shows the measured tokens and no dollar figure.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from tests.support.pods import build_pod
from typer.testing import CliRunner

from docket.agent import ports as _rd
from docket.hops.application import executor as _executor_c
from docket.hops.application import sweep as _sweep
from docket.hops.application import usage as _usage
from docket.hops.gates import pre_hop as _pre_hop
from docket.interfaces.cli.app import app as _app
from docket.kernel import clock as _clock
from docket.kernel.home import Home, current_home, use_home
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet
from docket.teams import pod as _podcore
from docket.teams import settings as _settings
from docket.teams.models import AgentMeta

SUBJECT = "docket.hops.application.sweep"

# ── hermetic environment (mirrors test_dispatch.py) ───────────────────────────────


@contextmanager
def _seed_pod(
    tmp_path: Path,
    project: str = "demo",
    roles: tuple[str, ...] = _podcore.DEFAULT_POD_ROLES,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod(project, roles, codebase=f"/src/{project}")
        yield home


class _RecordingRunner:
    """Stub matching agent_run's signature; records calls, returns canned results."""

    def __init__(self, *, ok: bool = True):
        self.calls: list[tuple[str, str, str, int, dict[str, str] | None]] = []
        self.ok = ok

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        self.calls.append((agent_id, session_key, message, timeout, env))
        return _rd.TurnResult(self.ok, f"done by {agent_id}", {"output": "x"})


def _write_session(
    oc_dir: Path, agent_id: str, *, input_tokens: int, output_tokens: int, cached_tokens: int = 0
) -> None:
    """Seeds a docket-native session with real token counts; ``oc_dir`` is unused but kept so
    call sites stay untouched."""
    from urllib.parse import quote

    session_key = f"agent:{agent_id}:default"
    sdir = current_home().sessions_dir / quote(session_key, safe="")
    sdir.mkdir(parents=True, exist_ok=True)
    record = {
        "sessionKey": session_key,
        "created": "2026-07-30T00:00:00Z",
        "updated": "2026-07-30T00:00:00Z",
        "messages": [],
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cachedTokens": cached_tokens,
            "turns": 1,
        },
    }
    (sdir / "session.json").write_text(json.dumps(record))


def _write_dated_session(agent_id: str, tokens_by_day: dict[str, int]) -> None:
    """Seeds a session whose output tokens were spent on the given UTC days (``YYYY-MM-DD``)."""
    from urllib.parse import quote

    session_key = f"agent:{agent_id}:default"
    sdir = current_home().sessions_dir / quote(session_key, safe="")
    sdir.mkdir(parents=True, exist_ok=True)

    def usage(tokens: int) -> dict[str, int]:
        return {
            "inputTokens": 0,
            "outputTokens": tokens,
            "cachedTokens": 0,
            "cacheWriteTokens": 0,
            "turns": 1,
        }

    record = {
        "sessionKey": session_key,
        "created": "2026-07-30T00:00:00Z",
        "updated": "2026-07-30T00:00:00Z",
        "messages": [],
        "usage": usage(sum(tokens_by_day.values())),
        "usageByDay": {day: usage(tokens) for day, tokens in tokens_by_day.items()},
    }
    (sdir / "session.json").write_text(json.dumps(record))


def _utc_day(days_ago: int = 0) -> str:
    return (_clock.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _budget_events(home: Path) -> list[dict[str, object]]:
    trace_files = list((home / "state" / "traces" / "demo").glob("*.jsonl"))
    events = [json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()]
    return [e for e in events if e["event_type"] == "budget_exceeded"]


# ── AgentMeta.coerce_paused ────────────────────────────────────────────


class TestCoercePaused:
    def test_real_bool_true(self) -> None:
        assert AgentMeta.coerce_paused(True) is True

    def test_real_bool_false(self) -> None:
        assert AgentMeta.coerce_paused(False) is False

    def test_legacy_string_true_titlecase(self) -> None:
        # str(True) in Python is "True" — this is exactly what a real bool
        # round-trips to through meta_get's str() coercion.
        assert AgentMeta.coerce_paused("True") is True

    def test_legacy_string_false(self) -> None:
        assert AgentMeta.coerce_paused("false") is False
        assert AgentMeta.coerce_paused("False") is False

    def test_absent_defaults_false(self) -> None:
        assert AgentMeta.coerce_paused("") is False

    def test_unrelated_string_is_false_not_an_error(self) -> None:
        assert AgentMeta.coerce_paused("yes") is False


# ── dispatch: pause on cap breach + claim-time refusal ────────────────────────────


class TestAutoPauseDispatch:
    def test_cap_breach_pauses_lead_and_blocks_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "Too expensive", channel="cli")
            monkeypatch.setattr(_settings, "pod_budget", lambda _p: 1)
            monkeypatch.setattr(_executor_c, "pod_budget", lambda _p: 1)
            monkeypatch.setattr(_usage, "pod_counted_tokens", lambda _p, since=None: 5)
            monkeypatch.setattr(_pre_hop, "pod_counted_tokens", lambda _p, since=None: 5)

            results = _sweep.dispatch_pod("demo", runner=_RecordingRunner())
            assert results[0].status == "blocked"

            lead_id = _podcore.member_id("demo", "lead")
            assert AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")) is True
            assert _fleet.meta_get(lead_id, "pausedReason") == "budget"

    def test_paused_pod_refuses_claim_at_next_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            _queue.enqueue_task_once("demo", "One", channel="cli")
            _queue.enqueue_task_once("demo", "Two", channel="cli")
            monkeypatch.setattr(_settings, "pod_budget", lambda _p: 1)
            monkeypatch.setattr(_executor_c, "pod_budget", lambda _p: 1)
            monkeypatch.setattr(_usage, "pod_counted_tokens", lambda _p, since=None: 5)
            monkeypatch.setattr(_pre_hop, "pod_counted_tokens", lambda _p, since=None: 5)
            _sweep.dispatch_pod("demo", runner=_RecordingRunner())

            # Second dispatch: the pod is now paused — nothing should even be
            # claimed (task "Two" stays exactly "pending", untouched), and no
            # further agent turn should run (no wasted cost).
            runner = _RecordingRunner()
            results = _sweep.dispatch_pod("demo", runner=runner)
            assert results == []
            assert runner.calls == []
            tasks = {t.description: t.status for t in TaskRepository.for_pod("demo").list()}
            assert tasks["Two"] == "pending"

            trace_files = list((oc_dir / "state" / "traces" / "demo").glob("*.jsonl"))
            events = [
                json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()
            ]
            assert any(e["event_type"] == "paused_refused" for e in events)


class TestPodTokenBudget:
    """A pod's ``budgetTokens`` gates on counted tokens, whatever the model."""

    def test_counted_tokens_over_the_cap_block_the_next_task_on_any_model(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _fleet.set_model_both(lead_id, "ai-gateway/acme/model-x")
            _fleet.meta_set(lead_id, "budgetTokens", 1000)
            _write_session(oc_dir, lead_id, input_tokens=800, output_tokens=400)
            _queue.enqueue_task_once("demo", "Too many tokens", channel="cli")
            runner = _RecordingRunner()

            results = _sweep.dispatch_pod("demo", runner=runner)

            assert results[0].status == "blocked"
            assert "1200" in results[0].reason and "1000" in results[0].reason
            assert runner.calls == []
            assert AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")) is True
            assert _fleet.meta_get(lead_id, "pausedReason") == "budget"
            (task,) = TaskRepository.for_pod("demo").list()
            assert task.failure_kind == "pod_budget"

    def test_cached_input_is_not_counted_against_the_cap(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _fleet.meta_set(lead_id, "budgetTokens", 1000)
            _write_session(
                oc_dir, lead_id, input_tokens=5000, output_tokens=100, cached_tokens=4500
            )
            _queue.enqueue_task_once("demo", "Mostly cached", channel="cli")

            results = _sweep.dispatch_pod("demo", runner=_RecordingRunner())

            assert results[0].status == "done"

    def test_a_pod_without_a_cap_is_never_blocked_by_tokens(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _write_session(oc_dir, lead_id, input_tokens=9_000_000, output_tokens=9_000_000)
            _queue.enqueue_task_once("demo", "No cap", channel="cli")

            results = _sweep.dispatch_pod("demo", runner=_RecordingRunner())

            assert results[0].status == "done"


class TestBudgetWindow:
    """A pod's ``budgetWindow`` counts the cap from the day the tokens were spent."""

    def _seed(self, lead_id: str, window: str, today_tokens: int) -> None:
        _fleet.meta_set(lead_id, "budgetTokens", 1000)
        if window != "none":
            _fleet.meta_set(lead_id, "budgetWindow", window)
        _write_dated_session(lead_id, {_utc_day(1): 2000, _utc_day(): today_tokens})
        _queue.enqueue_task_once("demo", "Windowed", channel="cli")

    def test_yesterdays_tokens_do_not_pause_a_pod_on_a_daily_window(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            lead_id = _podcore.member_id("demo", "lead")
            self._seed(lead_id, "day", today_tokens=100)

            results = _sweep.dispatch_pod("demo", runner=_RecordingRunner())

            assert results[0].status == "done"
            assert AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")) is False

    def test_the_same_tokens_pause_a_pod_with_no_window(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            lead_id = _podcore.member_id("demo", "lead")
            self._seed(lead_id, "none", today_tokens=100)

            results = _sweep.dispatch_pod("demo", runner=_RecordingRunner())

            assert results[0].status == "blocked"
            assert AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")) is True

    def test_todays_tokens_at_the_cap_pause_it_and_the_event_names_the_window(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path) as home:
            lead_id = _podcore.member_id("demo", "lead")
            self._seed(lead_id, "day", today_tokens=1000)

            results = _sweep.dispatch_pod("demo", runner=_RecordingRunner())

            assert results[0].status == "blocked"
            assert "1000 of 1000" in results[0].reason
            assert AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")) is True
            (event,) = _budget_events(home)
            detail = event.get("payload", event)
            assert detail["window"] == "day"  # type: ignore[index]
            assert detail["windowStart"] == f"{_utc_day()}T00:00:00Z"  # type: ignore[index]

    def test_an_unwindowed_event_carries_window_none_and_no_start(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as home:
            lead_id = _podcore.member_id("demo", "lead")
            self._seed(lead_id, "none", today_tokens=100)

            _sweep.dispatch_pod("demo", runner=_RecordingRunner())

            (event,) = _budget_events(home)
            detail = event.get("payload", event)
            assert detail["window"] == "none"  # type: ignore[index]
            assert detail["windowStart"] is None  # type: ignore[index]

    def test_a_session_without_day_buckets_counts_toward_no_window_only(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path) as home:
            lead_id = _podcore.member_id("demo", "lead")
            _fleet.meta_set(lead_id, "budgetTokens", 1000)
            _fleet.meta_set(lead_id, "budgetWindow", "day")
            _write_session(home, lead_id, input_tokens=5000, output_tokens=5000)
            _queue.enqueue_task_once("demo", "Old session", channel="cli")

            results = _sweep.dispatch_pod("demo", runner=_RecordingRunner())

            assert results[0].status == "done"

    def test_setting_the_window_lifts_the_pause_and_requeues_the_blocked_task(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            lead_id = _podcore.member_id("demo", "lead")
            self._seed(lead_id, "none", today_tokens=100)
            _sweep.dispatch_pod("demo", runner=_RecordingRunner())
            assert AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")) is True

            result = CliRunner().invoke(
                _app, ["pod", "set", "budgetWindow", "day", "--pod", "demo"]
            )

            assert result.exit_code == 0, result.output
            assert "Unblocked 1 blocked task(s)" in result.output
            assert AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")) is False
            assert _fleet.meta_get(lead_id, "pausedReason") == ""
            (task,) = TaskRepository.for_pod("demo").list()
            assert task.status == "pending"
            assert _sweep.dispatch_pod("demo", runner=_RecordingRunner())[0].status == "done"

    def test_unsetting_the_window_lifts_the_pause_too(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            lead_id = _podcore.member_id("demo", "lead")
            self._seed(lead_id, "none", today_tokens=100)
            _sweep.dispatch_pod("demo", runner=_RecordingRunner())

            result = CliRunner().invoke(_app, ["pod", "unset", "budgetWindow", "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")) is False

    def test_a_window_other_than_day_week_or_none_is_refused_naming_the_three(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            lead_id = _podcore.member_id("demo", "lead")

            result = CliRunner().invoke(
                _app, ["pod", "set", "budgetWindow", "month", "--pod", "demo"]
            )

            assert result.exit_code == 1
            assert "day" in result.output and "week" in result.output and "none" in result.output
            assert _fleet.meta_get(lead_id, "budgetWindow", "") == ""


# ── status shows the measured tokens and no dollar figure ──────────────────────────


class TestStatusShowsTokensOnly:
    def test_the_human_status_shows_the_tokens_and_no_dollar(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)

            result = CliRunner().invoke(_app, ["status", "--pod", "demo"])

            assert result.exit_code == 0, result.output
            row = next(ln for ln in result.output.splitlines() if ln.lstrip().startswith("Tokens"))
            assert "1.0M in / 1.0M out" in row
            assert "$" not in row and "est." not in row

    def test_status_all_json_names_no_cost_key_on_any_agent(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)

            result = CliRunner().invoke(_app, ["status", "--all", "--json"])

            assert result.exit_code == 0, result.output
            data = json.loads(result.stdout)
            agent_row = next(a for a in data["agents"] if a["id"] == lead_id)
            assert not [k for k in {*data, *agent_row} if "cost" in k.lower() or "usd" in k.lower()]
