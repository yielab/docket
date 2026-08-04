"""The RuntimeDriver port.

Covers:
  * Protocol conformance — both ``DocketDriver`` and ``FakeDriver`` satisfy
    ``core.runtime_driver.RuntimeDriver``, and
    ``edges.adapters.docket_runtime.default_driver()``'s singleton contract.
  * ``trace_ingest`` through the real production ``DocketDriver`` — a
    pod-dispatch hop's turns live in ``core/session.py``'s own storage, so
    this is the path that must work for ``docket trace`` to show anything
    real.
  * ``FakeDriver`` — the one test double, exercised directly (dispatch.py's
    own pipeline-semantics coverage of it lives in test_dispatch.py).

``DocketDriver`` backs onto no OS process and no daemon-shaped file at all.
See ``edges/adapters/llm.py``'s test coverage (test_llm_port.py) for
the driver's own response-parsing half, and test_docket_driver.py for
``DocketDriver.run_turn`` itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.core import runtime_driver as _rd

from .fakes import FakeDriver

# ── protocol conformance ──────────────────────────────────────────────────────


class TestProtocolConformance:
    def test_fake_driver_satisfies_runtime_driver(self) -> None:
        assert isinstance(FakeDriver(), _rd.RuntimeDriver)

    def test_docket_driver_satisfies_runtime_driver(self) -> None:
        from docket.edges.adapters.docket_runtime import DocketDriver

        assert isinstance(DocketDriver(), _rd.RuntimeDriver)

    def test_default_driver_is_a_singleton(self) -> None:
        from docket.edges.adapters import docket_runtime as _dr
        from docket.edges.adapters.docket_runtime import DocketDriver

        assert _dr.default_driver() is _dr.default_driver()
        assert isinstance(_dr.default_driver(), DocketDriver)


# ── trace_ingest through DocketDriver -- what production actually resolves.
# A pod-dispatch hop's turns live in core/session.py's own storage, not
# daemon JSONL, so this is the path that must work for `docket trace` to
# show anything real. ─────────────────────────────────────────────────────


class TestTraceIngestThroughDocketDriver:
    def test_ingest_projects_turns_from_a_real_docket_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import docket.config as _cfg
        from docket.core import session as _session
        from docket.core import trace as _trace
        from docket.core.llm import ToolCall, assistant, tool_result, user
        from docket.edges.adapters.docket_runtime import DocketDriver

        traces_dir = tmp_path / "traces"
        monkeypatch.setattr(_cfg, "TRACES_DIR", traces_dir, raising=True)
        monkeypatch.setattr(_cfg, "SESSIONS_DIR", tmp_path / "sessions", raising=True)
        monkeypatch.setenv("DOCKET_NO_COST_INDEX", "1")
        monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)

        session_key = "agent:myshop:default"
        call = ToolCall(id="t1", name="read", arguments="{}")
        _session.append_messages(
            session_key,
            [user("go"), assistant(tool_calls=[call]), tool_result(call, "ok")],
        )

        driver = DocketDriver()
        monkeypatch.setattr("docket.edges.adapters.docket_runtime.default_driver", lambda: driver)
        _trace.trace_ingest("myshop")

        tf = traces_dir / "myshop" / f"{session_key}.jsonl"
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
