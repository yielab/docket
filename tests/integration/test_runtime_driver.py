"""The RuntimeDriver port.

Covers protocol conformance (both ``DocketDriver`` and ``FakeDriver`` satisfy
``agent.ports.RuntimeDriver``, and ``default_driver()``'s singleton contract) and
``FakeDriver`` exercised directly. ``DocketDriver`` backs
onto no OS process and no daemon-shaped file. See test_llm_port.py for response-parsing and
test_docket_driver.py for ``DocketDriver.run_turn`` itself.
"""

from __future__ import annotations

from tests.support.fakes import FakeDriver

from docket.agent import ports as _rd

SUBJECT = "docket.agent.ports"

# ── protocol conformance ──────────────────────────────────────────────────────


class TestProtocolConformance:
    def test_fake_driver_satisfies_runtime_driver(self) -> None:
        assert isinstance(FakeDriver(), _rd.RuntimeDriver)

    def test_docket_driver_satisfies_runtime_driver(self) -> None:
        from docket.hops.application.driver import DocketDriver

        assert isinstance(DocketDriver(), _rd.RuntimeDriver)

    def test_default_driver_is_a_singleton(self) -> None:
        from docket.hops.application import driver as _dr
        from docket.hops.application.driver import DocketDriver

        assert _dr.default_driver() is _dr.default_driver()
        assert isinstance(_dr.default_driver(), DocketDriver)


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

    def test_capabilities(self) -> None:
        fake = FakeDriver(cost=0.0)
        assert fake.capabilities().reports_cost_usd is False
        assert FakeDriver(cost=0.01).capabilities().reports_cost_usd is True
