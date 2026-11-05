"""The RuntimeDriver port.

Covers protocol conformance (both ``DocketDriver`` and ``FakeDriver`` satisfy
``agent.ports.RuntimeDriver``, and ``default_driver()``'s singleton contract) and
``FakeDriver`` exercised directly. ``DocketDriver`` backs
onto no OS process and no daemon-shaped file. See test_llm_port.py for response-parsing and
test_docket_driver.py for ``DocketDriver.run_turn`` itself.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from tests.support.fakes import FakeDriver
from tests.support.home import record_isolation_off

from docket.agent import ports as _rd
from docket.hops.application.driver import DocketDriver
from docket.kernel.home import Home, current_home, use_home
from docket.models import catalog as _catalog
from docket.models.application import endpoint as _endpoint
from docket.platform import store as _store

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
        fake = FakeDriver()
        result = fake("demo-implementer", "agent:demo:t1", "do it", 30)
        assert result == _rd.TurnResult(True, "done by demo-implementer", {"output": "x"})
        assert fake.calls == [("demo-implementer", "agent:demo:t1", "do it", 30, None)]

    def test_fail_role_matches_by_agent_id_suffix(self) -> None:
        fake = FakeDriver(fail_role="reviewer", error="reviewer down")
        ok_result = fake.run_turn("demo-implementer", "s", "m", 30)
        assert ok_result.ok is True
        fail_result = fake.run_turn("demo-reviewer", "s", "m", 30)
        assert fail_result == _rd.TurnResult(False, "", {}, "reviewer down", failure_kind=None)

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
        caps = FakeDriver().capabilities()
        assert (caps.driver_name, caps.supports_sessions) == ("fake", True)


# ── the first request of a turn is estimated with the ratio the model showed last time ──

_AGENT = "ratio-agent"
_RAW_ESTIMATE = 1_000


class _MeasuringBackend:
    """A backend whose raw estimate is fixed and whose endpoint measures *measured* input tokens;
    its window, cap and ``estimate_ratio`` are what the resolved endpoint reports for the model, as
    a real client does."""

    def __init__(self, model: str, measured: int) -> None:
        resolved = _endpoint.resolve_endpoint(model)
        assert resolved is not None
        self.estimate_ratio = resolved.estimate_ratio
        self.context_window_tokens = resolved.context_window_tokens
        self.max_output_tokens = resolved.max_output_tokens
        self.measured = measured
        self.calls = 0

    def estimate_input_tokens(self, *args: object, **kwargs: object) -> int:
        return _RAW_ESTIMATE

    def complete(
        self,
        messages: Sequence[_rd.ChatMessage],
        *,
        tools: Sequence[_rd.ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        tool_choice: str | None = None,
        timeout: int = 120,
    ) -> _rd.ChatResponse:
        self.calls += 1
        return _rd.ChatResponse(
            ok=True,
            message=_rd.assistant("done"),
            finish_reason="stop",
            usage=_rd.TokenUsage(self.measured, 5),
        )


class TestEstimateRatioIsLearnedPerModel:
    @pytest.fixture(autouse=True)
    def _home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        with use_home(Home(tmp_path / "docket")):
            record_isolation_off(tmp_path / "docket")
            with use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)):
                current_home().workspace_dir(_AGENT).mkdir(parents=True, exist_ok=True)
                _store.write_json(
                    current_home().meta_path(_AGENT),
                    {"kind": "project", "role": "implementer", "model": "gw/m"},
                )
                _catalog.save_provider(
                    _catalog.ProviderSpec(
                        name="gw",
                        baseUrl="http://127.0.0.1:1/v1",
                        auth=_catalog.AuthSpec(type="none"),
                        models=[
                            _catalog.ModelRow(id="m", contextWindow=32768, maxTokens=1024),
                            _catalog.ModelRow(id="tiny", contextWindow=100, maxTokens=50),
                        ],
                    )
                )
                yield

    @staticmethod
    def _turn(model: str, measured: int) -> tuple[_rd.TurnResult, _MeasuringBackend]:
        backend = _MeasuringBackend(model, measured)
        result = DocketDriver(backend_factory=lambda _model: backend).run_turn(
            _AGENT, f"agent:{_AGENT}:default", "go", 30, trace_project="p", model=model
        )
        return result, backend

    @staticmethod
    def _stored() -> dict[str, object]:
        document = json.loads(current_home().provider_models_file.read_text(encoding="utf-8"))
        models: dict[str, dict[str, object]] = document["providers"]["gw"]["models"]
        return models["m"]

    @staticmethod
    def _latest_fit(session_key: str) -> int:
        trace = current_home().traces_dir / "p" / f"{session_key}.jsonl"
        fits = [
            record["payload"]
            for record in map(json.loads, trace.read_text().splitlines())
            if record["event_type"] == "request_fit"
        ]
        return int(fits[-1]["estimatedInputTokens"])

    def test_a_turn_records_the_ratio_its_first_call_measured_and_the_next_turn_starts_there(
        self,
    ) -> None:
        first, backend = self._turn("gw/m", measured=1_600)
        assert first.ok, first.error
        assert backend.estimate_ratio is None
        assert self._latest_fit(f"agent:{_AGENT}:default") == _RAW_ESTIMATE
        stored = self._stored()
        assert stored["estimateRatio"] == 1.6
        assert str(stored["estimateRatioAt"]).count("-") == 2

        second, backend = self._turn("gw/m", measured=1_000)
        assert second.ok, second.error
        assert backend.estimate_ratio == 1.6
        assert self._latest_fit(f"agent:{_AGENT}:default") == 1_600
        assert self._stored()["estimateRatio"] == 1.0

    def test_a_turn_that_made_no_call_records_nothing(self) -> None:
        result, backend = self._turn("gw/tiny", measured=1_600)
        assert result.stop_reason == "context_fit"
        assert backend.calls == 0
        assert not current_home().provider_models_file.exists()
