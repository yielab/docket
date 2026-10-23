"""Budget honesty — auto-pause, the paused-flag type bug, labelled estimates.

Covers: ``AgentMeta.coerce_paused`` (typed accessor fixing the string/bool
display bug: a writer stores a real ``bool`` while old code compared it to the string
``"true"``, which ``True`` never equals); the pause writer (per-hop budget gate marks the pod's
Lead ``paused=True, pausedReason="budget"`` at the cap); claim-time refusal
(``_claim_next_task`` refuses every claim for a paused pod outright -- a ``paused_refused``
trace event, no wasted turn -- until resumed); and the token-based estimate
fallback (``core/utils.estimate_cost_usd``/``core/dispatch.pod_gating_cost``) that lets gating
trip even when the driver reports no USD cost -- always labelled, never contaminating spend.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.pods import build_pod
from typer.testing import CliRunner

from docket.cli import app as _app
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import models_policy as _mp
from docket.core import pod as _podcore
from docket.core import runtime_driver as _rd
from docket.core import utils as _utils
from docket.core.models import AgentMeta
from docket.kernel.home import Home, current_home, use_home

SUBJECT = "docket.core"

# ── hermetic environment (mirrors test_dispatch.py) ───────────────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@contextmanager
def _seed_pod(
    tmp_path: Path,
    project: str = "demo",
    roles: tuple[str, ...] = _podcore.DEFAULT_POD_ROLES,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
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


def _write_session(oc_dir: Path, agent_id: str, *, input_tokens: int, output_tokens: int) -> None:
    """Seeds a docket-native session with real token counts and no cost -- ``DocketDriver``
    never reports a USD cost (see ``core/runtime_driver.py``'s ``TurnResult.cost_usd``), so
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
            "cachedTokens": 0,
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

    def test_legacy_string_true_lowercase(self) -> None:
        assert AgentMeta.coerce_paused("true") is True

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
            _dispatch.enqueue_task_once("demo", "Too expensive", channel="cli")
            monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)

            results = _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
            assert results[0].status == "blocked"

            lead_id = _podcore.member_id("demo", "lead")
            assert AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")) is True
            assert _fleet.meta_get(lead_id, "pausedReason") == "budget"

    def test_paused_pod_refuses_claim_at_next_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            _dispatch.enqueue_task_once("demo", "One", channel="cli")
            _dispatch.enqueue_task_once("demo", "Two", channel="cli")
            monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)
            _dispatch.dispatch_pod("demo", runner=_RecordingRunner())

            # Second dispatch: the pod is now paused — nothing should even be
            # claimed (task "Two" stays exactly "pending", untouched), and no
            # further agent turn should run (no wasted cost).
            runner = _RecordingRunner()
            results = _dispatch.dispatch_pod("demo", runner=runner)
            assert results == []
            assert runner.calls == []
            tasks = {t["description"]: t["status"] for t in _dispatch.read_tasks("demo")}
            assert tasks["Two"] == "pending"

            trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
            events = [
                json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()
            ]
            assert any(e["event_type"] == "paused_refused" for e in events)


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
            monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 3.5)
            spent, estimated = _dispatch.pod_gating_cost("demo")
            assert spent == 3.5
            assert estimated is False

    def test_pod_gating_cost_falls_back_to_estimate_when_recorded_is_zero(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _fleet.meta_set(lead_id, "model", "anthropic/claude-haiku-4-5")
            _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)

            spent, estimated = _dispatch.pod_gating_cost("demo")
            assert estimated is True
            assert spent == pytest.approx(4.8)  # 1M*$0.80/M + 1M*$4.00/M

    def test_dispatch_pauses_pod_using_estimate_when_nothing_recorded_a_cost(
        self, tmp_path: Path
    ) -> None:
        """The bug this closes: with real (unmocked) cost
        aggregation, a driver that never records usage.cost.total leaves
        recorded spend at 0 forever — the cap must still trip, from tokens."""
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _fleet.meta_set(lead_id, "model", "anthropic/claude-haiku-4-5")
            _fleet.meta_set(lead_id, "budgetUsd", "1")
            _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)
            _dispatch.enqueue_task_once("demo", "Too expensive", channel="cli")

            results = _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
            assert results[0].status == "blocked"
            assert "estimated" in results[0].reason
            assert AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")) is True


# ── recorded spend is never contaminated by an estimate ───────────────────────────


class TestRecordedSpendNeverContaminated:
    def test_aggregate_cost_stays_zero_when_nothing_was_recorded(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            lead_id = _podcore.member_id("demo", "lead")
            _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)
            # aggregate_cost (what `docket status` reports) must stay exactly the
            # driver's own recorded figure — 0.0 here — never the estimate, even
            # though plenty of tokens (and a known price) exist to estimate from.
            assert _utils.aggregate_cost(lead_id).cost_usd == 0.0

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


class TestUnpricedModelSurfaces:
    """A budgeted pod running a model with no price says so where the operator looks."""

    @contextmanager
    def _budgeted_pod(
        self,
        tmp_path: Path,
    ) -> Iterator[str]:
        with _seed_pod(tmp_path):
            model = "ai-gateway/acme/model-x"
            _fleet.set_model_both("demo-implementer", model)
            result = CliRunner().invoke(_app, ["pod", "set", "budgetUsd", "3", "--pod", "demo"])
            assert result.exit_code == 0, result.output
            yield model

    def test_the_pod_report_names_the_unpriced_model(self, tmp_path: Path) -> None:
        from docket.core import pod_report

        with self._budgeted_pod(tmp_path) as model:
            assert pod_report.pod_report("demo")["budgetUnpriced"] == [model]

    def test_status_json_and_text_name_the_unpriced_model(self, tmp_path: Path) -> None:
        with self._budgeted_pod(tmp_path) as model:
            as_json = CliRunner().invoke(_app, ["status", "--pod", "demo", "--json"])
            assert json.loads(as_json.output)["budgetUnpriced"] == [model]
            as_text = CliRunner().invoke(_app, ["status", "--pod", "demo"], env={"COLUMNS": "200"})
            assert f"cannot stop spend on {model}" in as_text.output
