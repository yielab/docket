"""Shared test doubles for the docket Python suite.

``FakeDriver`` is the one test double for
``docket.core.runtime_driver.RuntimeDriver`` — it exists so tests exercising
``core/dispatch.py``'s pipeline (or anything else that takes a
``RuntimeDriver``/``Runner``) don't each hand-roll their own ad-hoc stub
matching ``agent_run``'s signature. Construct one, tune its canned behaviour
via the constructor fields, and either pass the instance directly (it is
callable, matching dispatch.py's ``Runner`` type) or pass its bound
``run_turn`` method explicitly — both work identically.

This is deliberately the *only* fake in the suite for this port (ROADMAP §4.5:
one typed port, one shipped driver, one fake — no test-double framework).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from docket.core.runtime_driver import (
    DriverCapabilities,
    FailureKind,
    ProvisionResult,
    SessionSlice,
    SessionSummary,
    TeardownResult,
    TurnResult,
    UsageReport,
    UsageTotals,
)


@dataclass
class FakeDriver:
    """In-memory ``RuntimeDriver`` double — deterministic, no subprocess, no disk.

    ``ok``/``cost``/``fail_role`` mirror the original ``_RecordingRunner`` shims'
    constructor exactly, so existing call sites port over by substituting the
    class name. ``run_turn`` records every call in ``calls`` for assertions.
    """

    ok: bool = True
    cost: float = 0.02
    fail_role: str | None = None
    error: str = "boom"
    failure_kind: FailureKind | None = None

    provision_ok: bool = True
    teardown_ok: bool = True
    sessions_by_agent: dict[str, list[SessionSummary]] = field(default_factory=dict)
    usage_by_agent: dict[str, UsageReport] = field(default_factory=dict)

    calls: list[tuple[str, str, str, int, dict[str, str] | None]] = field(default_factory=list)
    provision_calls: list[tuple[str, str, str]] = field(default_factory=list)
    teardown_calls: list[str] = field(default_factory=list)

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        """Callable directly as a dispatch.py ``Runner`` — forwards to ``run_turn``."""
        return self.run_turn(agent_id, session_key, message, timeout, env)

    def run_turn(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
        *,
        on_spawn: Callable[[int], None] | None = None,
    ) -> TurnResult:
        """``on_spawn`` is accepted (per the ``RuntimeDriver`` Protocol's own
        signature) and ignored, matching every real driver that backs onto no
        OS process a caller could report a pid for -- this fake never has one
        either. Not recorded in ``calls`` (a 5-tuple, unchanged) since no
        existing assertion needs it; add a field if a test ever does."""
        self.calls.append((agent_id, session_key, message, timeout, env))
        role = agent_id.rsplit("-", 1)[-1]
        if self.fail_role and role == self.fail_role:
            return TurnResult(False, "", 0.0, {}, self.error, failure_kind=self.failure_kind)
        return TurnResult(self.ok, f"done by {agent_id}", self.cost, {"output": "x"})

    def provision(self, agent_id: str, workspace: str, model: str) -> ProvisionResult:
        self.provision_calls.append((agent_id, workspace, model))
        return ProvisionResult(
            ok=self.provision_ok, message="" if self.provision_ok else "provision failed"
        )

    def teardown(self, agent_id: str) -> TeardownResult:
        self.teardown_calls.append(agent_id)
        return TeardownResult(
            ok=self.teardown_ok, message="" if self.teardown_ok else "teardown failed"
        )

    def list_sessions(self, agent_id: str) -> list[SessionSummary]:
        return list(self.sessions_by_agent.get(agent_id, []))

    def read_new_turns(self, agent_id: str, session_id: str, offset: int) -> SessionSlice:
        """No canned session content by default — a no-op slice."""
        return SessionSlice(
            session_id=session_id,
            had_new_content=False,
            session_start_ts="",
            turns=[],
            last_ts=None,
            next_offset=offset,
        )

    def usage(self, agent_id: str) -> UsageReport:
        return self.usage_by_agent.get(agent_id, UsageReport(totals=UsageTotals()))

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            driver_name="fake",
            reports_cost_usd=self.cost > 0,
            supports_provisioning=True,
            supports_sessions=True,
        )
