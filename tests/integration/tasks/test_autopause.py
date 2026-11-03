"""Budget honesty — auto-pause, the paused-flag type bug, labelled estimates.

Covers: ``AgentMeta.coerce_paused`` (typed accessor fixing the string/bool
display bug: a writer stores a real ``bool`` while old code compared it to the string
``"true"``, which ``True`` never equals); the pause writer (per-hop budget gate marks the pod's
Lead ``paused=True, pausedReason="budget"`` at the cap, counted in tokens, so it trips on a model
with no catalog price); claim-time refusal (``claim_next_task`` refuses every claim for a paused
pod outright -- a ``paused_refused`` trace event, no wasted turn -- until resumed); and the
labelled dollar estimate that status still shows, never contaminating recorded spend.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
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
from docket.kernel.home import Home, current_home, use_home
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet
from docket.teams import model_selection as _mp
from docket.teams import pod as _podcore
from docket.teams import settings as _settings
from docket.teams import utils as _utils
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

    def __init__(self, *, ok: bool = True, cost: float = 0.0):
        self.calls: list[tuple[str, str, str, int, dict[str, str] | None]] = []
        self.ok = ok
        self.cost = cost

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        self.calls.append((agent_id, session_key, message, timeout, env))
        return _rd.TurnResult(self.ok, f"done by {agent_id}", self.cost, {"output": "x"})


def _write_session(
    oc_dir: Path, agent_id: str, *, input_tokens: int, output_tokens: int, cached_tokens: int = 0
) -> None:
    """Seeds a docket-native session with real token counts and no cost -- ``DocketDriver``
    never reports a USD cost (see ``agent/ports.py``'s ``TurnResult.cost_usd``), so
    this is the normal shape; ``oc_dir`` is unused but kept so call sites stay untouched."""
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
            monkeypatch.setattr(_usage, "pod_counted_tokens", lambda _p: 5)
            monkeypatch.setattr(_pre_hop, "pod_counted_tokens", lambda _p: 5)

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
            monkeypatch.setattr(_usage, "pod_counted_tokens", lambda _p: 5)
            monkeypatch.setattr(_pre_hop, "pod_counted_tokens", lambda _p: 5)
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
    """A pod's ``budgetTokens`` gates on counted tokens, whatever the model's catalog price."""

    def test_counted_tokens_over_the_cap_block_the_next_task_on_an_unpriced_model(
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


# ── estimate fallback for gating ───────────────────────────────────────────────────


class TestEstimateFallback:
    def test_estimate_cost_usd_known_model(self) -> None:
        totals = _rd.UsageTotals(input_tokens=1_000_000, output_tokens=1_000_000)
        est = _utils.estimate_cost_usd("anthropic/claude-haiku-4-5", totals)
        price = _mp.price_for("anthropic/claude-haiku-4-5")
        assert price is not None
        in_rate, out_rate, _cr, _cw = price
        assert est == pytest.approx(in_rate + out_rate)

    def test_estimate_cost_usd_does_not_charge_cache_reads_twice(self) -> None:
        totals = _rd.UsageTotals(input_tokens=1_000_000, cache_read=900_000)
        price = _mp.price_for("anthropic/claude-haiku-4-5")
        assert price is not None
        in_rate, _out, cache_read_rate, _cw = price
        est = _utils.estimate_cost_usd("anthropic/claude-haiku-4-5", totals)
        assert est == pytest.approx(0.1 * in_rate + 0.9 * cache_read_rate)

    def test_estimate_cost_usd_does_not_charge_cache_writes_twice(self) -> None:
        """Cache writes are part of input and are priced once, at the cache-write rate."""
        totals = _rd.UsageTotals(input_tokens=1_000_000, cache_read=500_000, cache_write=300_000)
        price = _mp.price_for("anthropic/claude-haiku-4-5")
        assert price is not None
        in_rate, _out, cache_read_rate, cache_write_rate = price
        est = _utils.estimate_cost_usd("anthropic/claude-haiku-4-5", totals)
        assert est == pytest.approx(0.2 * in_rate + 0.5 * cache_read_rate + 0.3 * cache_write_rate)

    def test_estimate_cost_usd_unknown_model_returns_none(self) -> None:
        totals = _rd.UsageTotals(input_tokens=1000, output_tokens=1000)
        assert _utils.estimate_cost_usd("some-vendor/unknown-model", totals) is None

    def test_pod_gating_cost_prefers_recorded_when_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            monkeypatch.setattr(_usage, "pod_recorded_cost", lambda _p: 3.5)
            monkeypatch.setattr(_pre_hop, "pod_recorded_cost", lambda _p: 3.5)
            spent, estimated = _pre_hop.pod_gating_cost("demo")
            assert spent == 3.5
            assert estimated is False

    def test_pod_gating_cost_falls_back_to_estimate_when_recorded_is_zero(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _fleet.meta_set(lead_id, "model", "anthropic/claude-haiku-4-5")
            _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)

            spent, estimated = _pre_hop.pod_gating_cost("demo")
            assert estimated is True
            assert spent == pytest.approx(4.8)  # 1M*$0.80/M + 1M*$4.00/M


# ── recorded spend is never contaminated by an estimate ───────────────────────────


class TestRecordedSpendNeverContaminated:
    def test_aggregate_cost_stays_zero_when_nothing_was_recorded(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)
            # aggregate_cost (what `docket status` reports) must stay exactly the
            # driver's own recorded figure — 0.0 here — never the estimate, even
            # though plenty of tokens (and a known price) exist to estimate from.
            assert _usage.aggregate_cost(lead_id).cost_usd == 0.0

    def test_status_labels_the_dollar_figure_an_estimate(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _fleet.meta_set(lead_id, "model", "anthropic/claude-haiku-4-5")
            _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)

            runner = CliRunner()
            result = runner.invoke(_app, ["status", "--pod", "demo"])
            assert result.exit_code == 0, result.output
            # The estimate ($4.80 for these tokens/model) appears only labelled as one.
            assert "~$4.80 est." in result.output
            assert "recorded" not in result.output

    def test_status_all_json_inventory_cost_field_stays_zero(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _fleet.meta_set(lead_id, "model", "anthropic/claude-haiku-4-5")
            _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)

            runner = CliRunner()
            result = runner.invoke(_app, ["status", "--all", "--json"])
            assert result.exit_code == 0, result.output
            data = json.loads(result.stdout)
            agent_row = next(a for a in data["agents"] if a["id"] == lead_id)
            assert agent_row["costUsd"] == 0.0
            assert data["totalCostUsd"] == 0.0
