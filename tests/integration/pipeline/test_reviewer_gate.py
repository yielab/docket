"""Reviewer verdict gate + bounded rework loop.

Enforces that a Reviewer's "APPROVE or REQUEST-CHANGES" veto is real: an unread verdict would let
REQUEST-CHANGES still advance to the Tester and complete `done`, making separation-of-duties
decorative. Mirrors ``test_verify_gate.py``'s ``TestDispatchTesterGate`` fixture pattern (hermetic
meta + an injected fake runner). TestParseReviewerVerdict covers the pure marker parser;
TestReviewerGateBasic covers APPROVE advancing normally, unparseable output failing distinctly
from a rejection, and a pod with no Reviewer being unaffected; TestReviewerReworkLoop and
TestReviewerReworkResume cover the bounded rework cycle and its resume-after-crash point. See
specs/functional/pod-dispatch.spec.md Requirements 3-4.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from tests.support import home as _support_home
from tests.support.pods import write_meta as _write_meta
from tests.support.trace import trace_events as _trace_events

from docket.agent import ports as _rd
from docket.hops.application import executor as _executor
from docket.hops.application import sweep as _sweep
from docket.kernel.home import current_home, use_home
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import queue as _queue
from docket.tasks.application import record as _record
from docket.tasks.domain import task as _task
from docket.teams import fleet as _fleet
from docket.teams import settings as _settings

_hermetic = _support_home.hermetic_trace_on

SUBJECT = "docket.hops.application.executor"

# ── hermetic helpers (mirror test_verify_gate.py) ─────────────────────────────


def _seed_full_pod(project: str = "myapp", lead_extra: dict[str, Any] | None = None) -> None:
    _write_meta(f"{project}-lead", lead_extra)
    _write_meta(f"{project}-implementer")
    _write_meta(f"{project}-reviewer")
    _write_meta(f"{project}-tester")


def _role_of(agent_id: str) -> str:
    return _fleet.meta_get(agent_id, "role", "") or agent_id


# ── pure parser ───────────────────────────────────────────────────────────────


class TestParseReviewerVerdict:
    """Reviewer marker parsing is not a dispatch-private regex: gate execution reads
    ``pipeline.domain.plan.parse_verdict`` against a step's ``VerdictGate`` generically. Exercises
    that parser against the reviewer step's gate from the default pipeline, the source of truth."""

    @staticmethod
    def _reviewer_gate() -> _gates.VerdictGate:
        spec = _pipeline.default_pipeline()
        reviewer_step = next(s for s in spec.steps if s.id == "reviewer")
        assert isinstance(reviewer_step.gate, _gates.VerdictGate)
        return reviewer_step.gate

    def test_approve_is_parsed(self) -> None:
        assert _orch.parse_verdict(self._reviewer_gate(), "APPROVE\nlooks good") == "approve"

    def test_request_changes_is_parsed(self) -> None:
        assert (
            _orch.parse_verdict(self._reviewer_gate(), "REQUEST-CHANGES\nfix the widget")
            == "request-changes"
        )

    def test_case_insensitive(self) -> None:
        gate = self._reviewer_gate()
        assert _orch.parse_verdict(gate, "approve — fine") == "approve"
        assert _orch.parse_verdict(gate, "request-changes: nope") == "request-changes"

    def test_leading_blank_lines_skipped(self) -> None:
        assert _orch.parse_verdict(self._reviewer_gate(), "\n\nAPPROVE\nfine") == "approve"

    def test_marker_may_follow_prose_on_a_later_line(self) -> None:
        assert (
            _orch.parse_verdict(
                self._reviewer_gate(),
                "I reviewed the implementation and found no blockers.\nAPPROVE",
            )
            == "approve"
        )

    def test_repeated_identical_markers_normalize_to_one_verdict(self) -> None:
        assert (
            _orch.parse_verdict(self._reviewer_gate(), "APPROVE\nEvidence.\napprove") == "approve"
        )

    def test_conflicting_marker_lines_are_unparseable(self) -> None:
        assert _orch.parse_verdict(self._reviewer_gate(), "APPROVE\nREQUEST-CHANGES") is None

    def test_marker_word_embedded_in_prose_does_not_count(self) -> None:
        assert _orch.parse_verdict(self._reviewer_gate(), "I APPROVE this implementation") is None

    def test_unparseable_returns_none(self) -> None:
        assert _orch.parse_verdict(self._reviewer_gate(), "looks fine to me") is None

    def test_empty_output_returns_none(self) -> None:
        assert _orch.parse_verdict(self._reviewer_gate(), "") is None


# ── basic gate behaviour ───────────────────────────────────────────────────────


class TestReviewerGateBasic:
    """APPROVE/no-reviewer are unchanged; unparseable output fails distinctly."""

    def _runner(self, reviewer_output: str, tester_output: str = "PASS - fine") -> _record.Runner:
        def _run(
            member_id: str,
            session_id: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            role = _role_of(member_id)
            if role == "reviewer":
                output = reviewer_output
            elif role == "tester":
                output = tester_output
            else:
                output = "ok"
            return _rd.TurnResult(ok=True, output=output, cost_usd=0.0, raw={})

        return _run

    def test_approve_advances_to_done(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t1", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("myapp", task, runner=self._runner("APPROVE - looks good"))
        assert res.status == "done"
        assert [h.role for h in res.hops] == ["lead", "implementer", "reviewer", "tester"]

    def test_approve_case_insensitive(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t1b", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("myapp", task, runner=self._runner("approve, ship it"))
        assert res.status == "done"

    def test_reviewer_and_tester_markers_may_follow_evidence(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t1c", "description": "work", "status": "pending"}
        res = _executor.dispatch_task(
            "myapp",
            task,
            runner=self._runner(
                "Reviewed the complete diff; no blockers remain.\nAPPROVE",
                "Ran the required behavior checks successfully.\nPASS",
            ),
        )

        assert res.status == "done"
        reviewer = next(hop for hop in res.hops if hop.role == "reviewer")
        tester = next(hop for hop in res.hops if hop.role == "tester")
        assert reviewer.artifact.verdict == "approve"
        assert tester.artifact.verdict == "pass"

    def test_conflicting_reviewer_markers_fail_as_unparseable(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t1d", "description": "work", "status": "pending"}
        res = _executor.dispatch_task(
            "myapp", task, runner=self._runner("APPROVE\nREQUEST-CHANGES")
        )

        assert res.status == "failed"
        assert "unparseable" in res.reason
        assert "first line" not in res.reason

    def test_unparseable_reviewer_output_fails(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t2", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("myapp", task, runner=self._runner("this looks fine I guess"))
        assert res.status == "failed"
        assert "unparseable" in res.reason
        # Distinct wording from an explicit rejection — never conflated.
        assert "rejected" not in res.reason

    def test_unparseable_stops_before_tester(self, tmp_path: Path) -> None:
        _seed_full_pod()
        calls: list[str] = []

        def _run(
            member_id: str,
            session_id: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            calls.append(_role_of(member_id))
            output = "no marker here" if _role_of(member_id) == "reviewer" else "ok"
            return _rd.TurnResult(ok=True, output=output, cost_usd=0.0, raw={})

        task: dict[str, Any] = {"id": "t3", "description": "work", "status": "pending"}
        _executor.dispatch_task("myapp", task, runner=_run)
        assert calls == ["lead", "implementer", "reviewer"]

    def test_unparseable_emits_distinct_trace_event(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t4", "description": "work", "status": "pending"}
        _executor.dispatch_task("myapp", task, runner=self._runner("hmm not sure"))
        events = _trace_events("myapp")
        types = [e["event_type"] for e in events]
        assert "reviewer_verdict_unparseable" in types
        assert "review_rejected" not in types

    def test_empty_reviewer_output_is_unparseable_not_rejection(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t5", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("myapp", task, runner=self._runner(""))
        assert res.status == "failed"
        assert "unparseable" in res.reason

    def test_pod_without_reviewer_is_completely_unaffected(self, tmp_path: Path) -> None:
        # Lean pod: lead + implementer only. No reviewer hop ever runs, so
        # nothing about the reviewer gate can affect this pod's outcome.
        _write_meta("leanapp-lead")
        _write_meta("leanapp-implementer")

        def _run(
            member_id: str,
            session_id: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            return _rd.TurnResult(ok=True, output="ok", cost_usd=0.0, raw={})

        task: dict[str, Any] = {"id": "t6", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("leanapp", task, runner=_run)
        assert res.status == "done"
        assert [h.role for h in res.hops] == ["lead", "implementer"]


# ── bounded rework loop ─────────────────────────────────────────────────────────


class _ReworkRunner:
    """Reviewer REQUEST-CHANGES the first N times, then APPROVEs; Tester always PASSes when
    reached. Records every ``(role, message)`` call so tests can assert call order and that the
    rework brief carries the review text."""

    def __init__(
        self,
        request_changes_count: int = 1,
        review_text: str = "REQUEST-CHANGES\nRename the helper and add type hints.",
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.session_keys: list[tuple[str, str]] = []
        self.request_changes_count = request_changes_count
        self.review_text = review_text
        self._reviewer_calls = 0

    def __call__(
        self,
        member_id: str,
        session_id: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = _role_of(member_id)
        self.calls.append((role, message))
        self.session_keys.append((role, session_id))
        if role == "reviewer":
            self._reviewer_calls += 1
            if self._reviewer_calls <= self.request_changes_count:
                return _rd.TurnResult(ok=True, output=self.review_text, cost_usd=0.01, raw={})
            return _rd.TurnResult(ok=True, output="APPROVE - fixed", cost_usd=0.01, raw={})
        if role == "tester":
            return _rd.TurnResult(ok=True, output="PASS - fine", cost_usd=0.01, raw={})
        return _rd.TurnResult(ok=True, output=f"done by {member_id}", cost_usd=0.01, raw={})


class TestReviewerReworkLoop:
    def test_request_changes_triggers_one_rework_then_approves(self, tmp_path: Path) -> None:
        _seed_full_pod()
        runner = _ReworkRunner(request_changes_count=1)
        task: dict[str, Any] = {"id": "r1", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("myapp", task, runner=runner)

        assert res.status == "done"
        roles_called = [c[0] for c in runner.calls]
        assert roles_called == [
            "lead",
            "implementer",
            "reviewer",
            "implementer",
            "reviewer",
            "tester",
        ]
        assert [h.role for h in res.hops] == roles_called
        implementer_keys = [key for role, key in runner.session_keys if role == "implementer"]
        reviewer_keys = [key for role, key in runner.session_keys if role == "reviewer"]
        assert len(set(implementer_keys)) == 1
        assert len(set(reviewer_keys)) == 1
        assert implementer_keys[0] != reviewer_keys[0]

    def test_rework_brief_carries_the_review_text(self, tmp_path: Path) -> None:
        _seed_full_pod()
        runner = _ReworkRunner(request_changes_count=1)
        task: dict[str, Any] = {"id": "r2", "description": "work", "status": "pending"}
        _executor.dispatch_task("myapp", task, runner=runner)

        implementer_messages = [msg for role, msg in runner.calls if role == "implementer"]
        assert len(implementer_messages) == 2
        # The rework hop's message must carry the reviewer's exact text, not
        # just a generic "prior hop output" mention.
        first_brief, rework_brief = implementer_messages
        assert "Rename the helper and add type hints." not in first_brief
        assert "REWORK REQUIRED" in rework_brief
        assert "Rename the helper and add type hints." in rework_brief

    def test_rework_started_trace_event(self, tmp_path: Path) -> None:
        _seed_full_pod()
        runner = _ReworkRunner(request_changes_count=1)
        task: dict[str, Any] = {"id": "r3", "description": "work", "status": "pending"}
        _executor.dispatch_task("myapp", task, runner=runner)
        events = _trace_events("myapp")
        rework_events = [e for e in events if e["event_type"] == "rework_started"]
        assert len(rework_events) == 1
        assert rework_events[0]["payload"]["cycle"] == 1

    def test_second_request_changes_fails_the_task(self, tmp_path: Path) -> None:
        _seed_full_pod()  # default maxReworkCycles is 1
        runner = _ReworkRunner(request_changes_count=2)  # always rejects
        task: dict[str, Any] = {"id": "r4", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("myapp", task, runner=runner)

        assert res.status == "failed"
        assert "REQUEST-CHANGES" in res.reason
        assert "1 rework cycle" in res.reason
        roles_called = [c[0] for c in runner.calls]
        # Exactly one rework attempt happened before the second rejection was terminal.
        assert roles_called == ["lead", "implementer", "reviewer", "implementer", "reviewer"]
        assert "tester" not in roles_called

    def test_second_request_changes_emits_review_rejected_trace_event(self, tmp_path: Path) -> None:
        _seed_full_pod()
        runner = _ReworkRunner(request_changes_count=2)
        task: dict[str, Any] = {"id": "r5", "description": "work", "status": "pending"}
        _executor.dispatch_task("myapp", task, runner=runner)
        events = _trace_events("myapp")
        ev = next(e for e in events if e["event_type"] == "review_rejected")
        assert ev["payload"]["cycles"] == 1

    def test_rework_hops_appear_in_persisted_queue(self, tmp_path: Path) -> None:
        _seed_full_pod()
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        runner = _ReworkRunner(request_changes_count=1)
        results = _sweep.dispatch_pod("myapp", runner=runner)

        assert results[0].status == "done"
        persisted = _queue.read_tasks("myapp")[0]
        assert persisted["status"] == "done"
        assert [h["role"] for h in persisted["hops"]] == [
            "lead",
            "implementer",
            "reviewer",
            "implementer",
            "reviewer",
            "tester",
        ]

    def test_max_rework_cycles_zero_disables_rework(self, tmp_path: Path) -> None:
        # A pod whose Lead has maxReworkCycles=0: the Reviewer is a hard gate —
        # a single REQUEST-CHANGES fails immediately, no rework attempted.
        _seed_full_pod(lead_extra={"maxReworkCycles": "0"})
        runner = _ReworkRunner(request_changes_count=1)
        task: dict[str, Any] = {"id": "r6", "description": "work", "status": "pending"}
        res = _executor.dispatch_task("myapp", task, runner=runner)

        assert res.status == "failed"
        assert "0 rework cycle" in res.reason
        roles_called = [c[0] for c in runner.calls]
        # Only ONE implementer call and ONE reviewer call — no rework loop at all.
        assert roles_called == ["lead", "implementer", "reviewer"]

        events = _trace_events("myapp")
        ev = next(e for e in events if e["event_type"] == "review_rejected")
        assert ev["payload"]["cycles"] == 0

    def test_default_max_rework_cycles_is_one(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        assert _settings.pod_max_rework_cycles("myapp") == 1

    def test_max_rework_cycles_reads_lead_meta(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead", {"maxReworkCycles": "3"})
        assert _settings.pod_max_rework_cycles("myapp") == 3

    def test_max_rework_cycles_invalid_value_refuses_instead_of_defaulting(
        self, tmp_path: Path
    ) -> None:
        _write_meta("myapp-lead", {"maxReworkCycles": "not-a-number"})
        with pytest.raises(_task.DispatchError, match="maxReworkCycles"):
            _settings.pod_max_rework_cycles("myapp")


# ── resume mid-rework: the integration point that matters most ─────────────────


class _CrashOnSecondImplementerCallRunner:
    """Simulates a crash between a persisted REQUEST-CHANGES Reviewer hop and the rework
    Implementer hop: the first Implementer and Reviewer calls succeed normally, then the second
    Implementer call (the rework hop) raises -- the request went out but the process died first."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._impl_calls = 0

    def __call__(
        self,
        member_id: str,
        session_id: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = _role_of(member_id)
        self.calls.append(role)
        if role == "implementer":
            self._impl_calls += 1
            if self._impl_calls == 2:
                raise RuntimeError("simulated crash mid-rework")
            return _rd.TurnResult(ok=True, output=f"done by {member_id}", cost_usd=0.01, raw={})
        if role == "reviewer":
            return _rd.TurnResult(
                ok=True, output="REQUEST-CHANGES\nfix the widget", cost_usd=0.01, raw={}
            )
        return _rd.TurnResult(ok=True, output=f"done by {member_id}", cost_usd=0.01, raw={})


class TestReviewerReworkResume:
    def test_resume_continues_into_rework_implementer_not_past_it(self, tmp_path: Path) -> None:
        _seed_full_pod()
        _queue.enqueue_task_once("myapp", "Resume me mid-rework", channel="cli")

        crasher = _CrashOnSecondImplementerCallRunner()
        with pytest.raises(RuntimeError, match="simulated crash mid-rework"):
            _sweep.dispatch_pod("myapp", runner=crasher)

        # lead, implementer, and the REQUEST-CHANGES reviewer hop were all
        # persisted before the crash; the rework implementer's request went
        # out (recorded in crasher.calls) but never came back.
        assert crasher.calls == ["lead", "implementer", "reviewer", "implementer"]
        tasks = _queue.read_tasks("myapp")
        assert tasks[0]["status"] == "running"
        assert [h["role"] for h in tasks[0]["hops"]] == ["lead", "implementer", "reviewer"]

        # Force the claim stale, exactly like test_dispatch.py's own crash-recovery tests.
        with use_home(dataclasses.replace(current_home(), claim_stale_timeout=-1)):
            resumer = _ReworkRunner(request_changes_count=0)  # approves whenever asked
            results = _sweep.dispatch_pod("myapp", runner=resumer, resume=True)

            assert len(results) == 1
            assert results[0].status == "done"
            # The critical assertion: resume re-enters at the REWORK IMPLEMENTER
            # hop first — not a second Reviewer call, and not skipping straight to
            # the Tester. A naive role-based "already done" resume would
            # have seen "reviewer" already in the persisted hops and skipped
            # straight past it to the Tester, silently dropping the rework.
            roles_resumed = [c[0] for c in resumer.calls]
            assert roles_resumed == ["implementer", "reviewer", "tester"]

            final = _queue.read_tasks("myapp")[0]
            assert final["status"] == "done"
            assert [h["role"] for h in final["hops"]] == [
                "lead",
                "implementer",
                "reviewer",
                "implementer",
                "reviewer",
                "tester",
            ]
            assert final["claimId"] is None

    def test_resumed_rework_implementer_message_still_carries_review_text(
        self, tmp_path: Path
    ) -> None:
        """The rework note must survive a crash+resume, not just a live run."""
        _seed_full_pod()
        _queue.enqueue_task_once("myapp", "Resume me mid-rework", channel="cli")

        crasher = _CrashOnSecondImplementerCallRunner()
        with pytest.raises(RuntimeError):
            _sweep.dispatch_pod("myapp", runner=crasher)
        with use_home(dataclasses.replace(current_home(), claim_stale_timeout=-1)):
            resumer = _ReworkRunner(request_changes_count=0)
            _sweep.dispatch_pod("myapp", runner=resumer, resume=True)

            rework_message = next(msg for role, msg in resumer.calls if role == "implementer")
            assert "REWORK REQUIRED" in rework_message
            assert "fix the widget" in rework_message
