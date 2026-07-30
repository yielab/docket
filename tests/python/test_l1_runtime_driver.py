"""Phase 18 L-1 (D-14): the RuntimeDriver port.

Covers:
  * Protocol conformance — both OpenClawDriver and FakeDriver satisfy
    core.runtime_driver.RuntimeDriver.
  * OpenClawDriver.usage()/list_sessions()/read_new_turns() — the session-JSONL
    parsing moved out of core/utils.py and core/trace.py (see
    test_ch2_openclaw_acl_guard.py's test_core_has_no_session_format_knowledge
    for the regression guard on the *other* side of this: core/ never doing
    this parsing itself again).
  * OpenClawDriver.run_turn()/provision()/teardown() — thin, behavior-preserving
    delegation to the pre-existing ACL free functions.
  * OpenClawDriver.capabilities() and default_driver()'s singleton contract.
  * FakeDriver — the one test double, exercised directly (dispatch.py's own
    pipeline-semantics coverage of it lives in test_dispatch.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import runtime_driver as _rd
from docket.core import utils as _utils
from docket.edges.adapters import openclaw as _oc

from .fakes import FakeDriver

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def oc_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp ~/.openclaw with config paths repointed (mirrors test_m5_trace_audit)."""
    d = tmp_path / ".openclaw"
    d.mkdir()
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", d, raising=True)
    monkeypatch.setattr(_cfg, "DOCKET_HOME", d, raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", d / "traces", raising=True)
    monkeypatch.setattr(_cfg, "SESSION_TIMEOUT", 3600, raising=True)
    monkeypatch.setenv("DOCKET_NO_COST_INDEX", "1")  # deterministic — no stale cache across tests
    monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
    return d


def _write_session(
    oc_dir: Path, agent_id: str, session: str, lines: list[dict[str, object]]
) -> Path:
    sdir = oc_dir / "agents" / agent_id / "sessions"
    sdir.mkdir(parents=True, exist_ok=True)
    f = sdir / f"{session}.jsonl"
    f.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return f


# ── protocol conformance ──────────────────────────────────────────────────────


class TestProtocolConformance:
    def test_openclaw_driver_satisfies_runtime_driver(self) -> None:
        assert isinstance(_oc.OpenClawDriver(), _rd.RuntimeDriver)

    def test_fake_driver_satisfies_runtime_driver(self) -> None:
        assert isinstance(FakeDriver(), _rd.RuntimeDriver)

    def test_default_driver_is_a_singleton(self) -> None:
        assert _oc.default_driver() is _oc.default_driver()
        assert isinstance(_oc.default_driver(), _oc.OpenClawDriver)


# ── run_turn / provision / teardown: thin, behavior-preserving delegation ────


class TestDelegation:
    def test_run_turn_delegates_to_agent_run(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[object, ...]] = []

        def fake_agent_run(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int = 300,
            env: dict[str, str] | None = None,
        ) -> _oc.AgentRunResult:
            calls.append((agent_id, session_key, message, timeout, env))
            return _oc.AgentRunResult(True, "hi", 0.01, {"output": "hi"})

        monkeypatch.setattr(_oc, "agent_run", fake_agent_run)
        driver = _oc.OpenClawDriver()
        result = driver.run_turn("demo-lead", "agent:demo:t1", "plan it", 30, {"X": "1"})
        assert calls == [("demo-lead", "agent:demo:t1", "plan it", 30, {"X": "1"})]
        assert result == _oc.AgentRunResult(True, "hi", 0.01, {"output": "hi"})

    def test_provision_delegates_to_register_agent_cli(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_oc, "register_agent_cli", lambda a, w, m: (True, ""))
        result = _oc.OpenClawDriver().provision("demo-lead", "/ws/demo-lead", "anthropic/sonnet")
        assert result == _rd.ProvisionResult(ok=True, message="")

    def test_provision_surfaces_failure_message(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_oc, "register_agent_cli", lambda a, w, m: (False, "no daemon"))
        result = _oc.OpenClawDriver().provision("demo-lead", "/ws/demo-lead", "anthropic/sonnet")
        assert result == _rd.ProvisionResult(ok=False, message="no daemon")

    def test_teardown_delegates_to_unregister_agent_cli(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_oc, "unregister_agent_cli", lambda a: (True, ""))
        result = _oc.OpenClawDriver().teardown("demo-lead")
        assert result == _rd.TeardownResult(ok=True, message="")


class TestCapabilities:
    def test_openclaw_driver_capabilities(self) -> None:
        caps = _oc.OpenClawDriver().capabilities()
        assert caps.driver_name == "openclaw"
        assert caps.reports_cost_usd is False  # daemon v2026.2.23: run_turn never reports cost
        assert caps.supports_provisioning is True
        assert caps.supports_sessions is True


# ── list_sessions / usage: the session-JSONL parsing that moved into the driver ──


class TestListSessions:
    def test_empty_when_no_sessions_dir(self, oc_dir: Path) -> None:
        assert _oc.OpenClawDriver().list_sessions("ghost") == []

    def test_enumerates_sorted_session_ids(self, oc_dir: Path) -> None:
        _write_session(oc_dir, "myshop", "b-session", [])
        _write_session(oc_dir, "myshop", "a-session", [])
        summaries = _oc.OpenClawDriver().list_sessions("myshop")
        assert [s.session_id for s in summaries] == ["a-session", "b-session"]


class TestUsage:
    def test_zero_totals_with_no_sessions(self, oc_dir: Path) -> None:
        report = _oc.OpenClawDriver().usage("myshop")
        assert report.totals == _rd.UsageTotals()
        assert report.by_day == []

    def test_aggregates_tokens_and_cost(self, oc_dir: Path) -> None:
        _write_session(
            oc_dir,
            "myshop",
            "session-1",
            [
                {
                    "timestamp": "2024-03-15T10:00:00Z",
                    "message": {
                        "usage": {
                            "input": 1000,
                            "output": 200,
                            "cacheRead": 500,
                            "cacheWrite": 100,
                            "cost": {"total": 0.005},
                        }
                    },
                }
            ],
        )
        totals = _oc.OpenClawDriver().usage("myshop").totals
        assert totals.input_tokens == 1000
        assert totals.output_tokens == 200
        assert totals.cache_read == 500
        assert totals.cache_write == 100
        assert totals.turns == 1
        assert totals.cost_usd == pytest.approx(0.005)

    def test_by_day_breakdown_and_ordering(self, oc_dir: Path) -> None:
        for day in ("2024-01-10", "2024-01-01", "2024-01-02"):
            _write_session(
                oc_dir,
                "myshop",
                day,
                [
                    {
                        "timestamp": f"{day}T10:00:00Z",
                        "message": {"usage": {"input": 1, "output": 1, "cost": {"total": 0.0}}},
                    }
                ],
            )
        by_day = _oc.OpenClawDriver().usage("myshop").by_day
        assert [d.date for d in by_day] == ["2024-01-01", "2024-01-02", "2024-01-10"]

    def test_core_utils_wrappers_translate_the_same_data(self, oc_dir: Path) -> None:
        """aggregate_cost/cost_history (core/utils.py) are pure translations now."""
        _write_session(
            oc_dir,
            "myshop",
            "s",
            [
                {
                    "timestamp": "2024-03-15T10:00:00Z",
                    "message": {"usage": {"input": 7, "output": 3, "cost": {"total": 0.001}}},
                }
            ],
        )
        totals = _utils.aggregate_cost("myshop")
        assert (totals.input_tokens, totals.output_tokens, totals.turns) == (7, 3, 1)
        assert totals.cost_usd == pytest.approx(0.001)
        history = _utils.cost_history("myshop")
        assert len(history) == 1
        assert history[0].date == "2024-03-15"


# ── read_new_turns: the trace_ingest daemon-record decoding that moved in ────


class TestReadNewTurns:
    def test_missing_session_file_reports_no_new_content(self, oc_dir: Path) -> None:
        sl = _oc.OpenClawDriver().read_new_turns("myshop", "nope", 0)
        assert sl.had_new_content is False
        assert sl.next_offset == 0

    def test_decodes_tool_use_and_tool_result_skips_message(self, oc_dir: Path) -> None:
        _write_session(
            oc_dir,
            "myshop",
            "sess1",
            [
                {"type": "message", "timestamp": "2026-01-01T00:00:00Z", "id": "m1"},
                {"type": "tool_use", "timestamp": "2026-01-01T00:00:01Z", "id": "t1"},
                {"type": "tool_result", "timestamp": "2026-01-01T00:00:02Z", "id": "t1"},
            ],
        )
        sl = _oc.OpenClawDriver().read_new_turns("myshop", "sess1", 0)
        assert sl.had_new_content is True
        assert sl.session_start_ts == "2026-01-01T00:00:00Z"
        assert [(t.kind, t.daemon_type, t.record_id) for t in sl.turns] == [
            ("tool_call", "tool_use", "t1"),
            ("tool_result", "tool_result", "t1"),
        ]
        # last_ts tracks every decoded line, including the skipped "message" —
        # here it's the last line's timestamp regardless of kind.
        assert sl.last_ts == "2026-01-01T00:00:02Z"
        assert sl.next_offset == 3

    def test_incremental_offset_only_returns_new_lines(self, oc_dir: Path) -> None:
        driver = _oc.OpenClawDriver()
        src = _write_session(
            oc_dir,
            "myshop",
            "sess1",
            [{"type": "tool_use", "timestamp": "2026-01-01T00:00:00Z", "id": "t1"}],
        )
        first = driver.read_new_turns("myshop", "sess1", 0)
        assert first.next_offset == 1

        # Nothing new yet at the same offset.
        stale = driver.read_new_turns("myshop", "sess1", first.next_offset)
        assert stale.had_new_content is False

        with src.open("a") as f:
            f.write(json.dumps({"type": "tool_result", "timestamp": "2026-01-01T00:00:01Z"}) + "\n")

        second = driver.read_new_turns("myshop", "sess1", first.next_offset)
        assert second.had_new_content is True
        assert [t.kind for t in second.turns] == ["tool_result"]
        assert second.next_offset == 2


# ── trace_ingest end-to-end through the driver (core/trace.py has no format knowledge) ──


class TestTraceIngestThroughDriver:
    def test_ingest_projects_turns_via_driver(self, oc_dir: Path) -> None:
        from docket.core import trace as _trace

        _write_session(
            oc_dir,
            "myshop",
            "sess1",
            [
                {"type": "message", "timestamp": _trace._now_iso(), "id": "m1"},
                {"type": "tool_use", "timestamp": _trace._now_iso(), "id": "t1"},
                {"type": "tool_result", "timestamp": _trace._now_iso(), "id": "t1"},
            ],
        )
        _trace.trace_ingest("myshop")
        tf = oc_dir / "traces" / "myshop" / "sess1.jsonl"
        assert tf.is_file()
        types = [r["event_type"] for r in _trace.read_trace(tf)]
        assert types == ["session_start", "tool_call", "tool_result"]


# ── FakeDriver: the one test double ───────────────────────────────────────────


class TestFakeDriver:
    def test_callable_matches_runner_signature(self) -> None:
        fake = FakeDriver(cost=0.03)
        result = fake("demo-implementer", "agent:demo:t1", "do it", 30)
        assert result == _rd.TurnResult(True, "done by demo-implementer", 0.03, {"output": "x"})
        assert fake.calls == [("demo-implementer", "agent:demo:t1", "do it", 30, None)]

    def test_fail_role_matches_by_agent_id_suffix(self) -> None:
        fake = FakeDriver(fail_role="reviewer", error="reviewer down")
        ok_result = fake.run_turn("demo-implementer", "s", "m", 30)
        assert ok_result.ok is True
        fail_result = fake.run_turn("demo-reviewer", "s", "m", 30)
        assert fail_result == _rd.TurnResult(False, "", 0.0, {}, "reviewer down", failure_kind=None)

    def test_provision_and_teardown_record_calls(self) -> None:
        fake = FakeDriver()
        assert fake.provision("demo-lead", "/ws/demo-lead", "m") == _rd.ProvisionResult(True, "")
        assert fake.teardown("demo-lead") == _rd.TeardownResult(True, "")
        assert fake.provision_calls == [("demo-lead", "/ws/demo-lead", "m")]
        assert fake.teardown_calls == ["demo-lead"]

    def test_list_sessions_and_usage_default_empty(self) -> None:
        fake = FakeDriver()
        assert fake.list_sessions("demo-lead") == []
        assert fake.usage("demo-lead") == _rd.UsageReport(totals=_rd.UsageTotals())

    def test_list_sessions_and_usage_are_configurable(self) -> None:
        fake = FakeDriver(
            sessions_by_agent={"demo-lead": [_rd.SessionSummary(session_id="s1")]},
            usage_by_agent={"demo-lead": _rd.UsageReport(totals=_rd.UsageTotals(turns=3))},
        )
        assert [s.session_id for s in fake.list_sessions("demo-lead")] == ["s1"]
        assert fake.usage("demo-lead").totals.turns == 3

    def test_read_new_turns_default_is_a_no_op_slice(self) -> None:
        fake = FakeDriver()
        sl = fake.read_new_turns("demo-lead", "s1", 5)
        assert sl.had_new_content is False
        assert sl.next_offset == 5

    def test_capabilities(self) -> None:
        fake = FakeDriver(cost=0.0)
        assert fake.capabilities().reports_cost_usd is False
        assert FakeDriver(cost=0.01).capabilities().reports_cost_usd is True
