"""R-4: Reviewer verdict gate + bounded rework loop.

Before this card, the Reviewer's documented "APPROVE or REQUEST-CHANGES" veto
was prose only — dispatch never read a Reviewer hop's output, so a
REQUEST-CHANGES review still advanced the pipeline to the Tester and let the
task complete `done`. Separation-of-duties was decorative.

This suite mirrors ``test_cd2_verify.py``'s ``TestDispatchTesterGate`` fixture
pattern (hermetic meta + an injected fake runner) and exercises:

  * TestParseReviewerVerdict     — the pure marker parser in isolation.
  * TestReviewerGateBasic        — APPROVE advances normally; unparseable
    output fails distinctly from a rejection; a pod with no Reviewer is
    completely unaffected (regression guard).
  * TestReviewerReworkLoop       — REQUEST-CHANGES drives exactly one bounded
    rework cycle back to the Implementer (review text carried into its
    brief), a second REQUEST-CHANGES fails the task, every rework hop lands
    in the persisted ``hops[]``, and ``maxReworkCycles: 0`` disables rework
    entirely (the Reviewer becomes a hard gate with no retry).
  * TestReviewerReworkResume     — the integration point that matters most: a
    crash recorded *after* a REQUEST-CHANGES Reviewer hop persists but
    *before* the rework Implementer hop runs resumes into that rework hop,
    not past it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import dispatch as _dispatch
from docket.core import trace as _trace
from docket.edges.adapters import openclaw as _oc

# ── hermetic helpers (mirror test_cd2_verify.py) ─────────────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")

    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))

    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", oc_dir / "traces", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = _cfg.PROJECTS_DIR / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.split("-")[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "modelSource": "policy",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _oc.add_agent(member_id, meta["model"], meta["sessionKey"], "default")


def _seed_full_pod(project: str = "myapp", lead_extra: dict[str, Any] | None = None) -> None:
    _write_meta(f"{project}-lead", lead_extra)
    _write_meta(f"{project}-implementer")
    _write_meta(f"{project}-reviewer")
    _write_meta(f"{project}-tester")


def _trace_events(project: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    traces_dir = _cfg.TRACES_DIR / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


def _role_of(agent_id: str) -> str:
    return _oc.meta_get(agent_id, "role", "") or agent_id


# ── pure parser ───────────────────────────────────────────────────────────────


class TestParseReviewerVerdict:
    def test_approve_is_parsed(self) -> None:
        assert _dispatch._parse_reviewer_verdict("APPROVE\nlooks good") == "approve"

    def test_request_changes_is_parsed(self) -> None:
        assert (
            _dispatch._parse_reviewer_verdict("REQUEST-CHANGES\nfix the widget")
            == "request-changes"
        )

    def test_case_insensitive(self) -> None:
        assert _dispatch._parse_reviewer_verdict("approve — fine") == "approve"
        assert _dispatch._parse_reviewer_verdict("request-changes: nope") == "request-changes"

    def test_leading_blank_lines_skipped(self) -> None:
        assert _dispatch._parse_reviewer_verdict("\n\nAPPROVE\nfine") == "approve"

    def test_unparseable_returns_none(self) -> None:
        assert _dispatch._parse_reviewer_verdict("looks fine to me") is None

    def test_empty_output_returns_none(self) -> None:
        assert _dispatch._parse_reviewer_verdict("") is None


# ── basic gate behaviour ───────────────────────────────────────────────────────


class TestReviewerGateBasic:
    """APPROVE/no-reviewer are unchanged; unparseable output fails distinctly."""

    def _runner(self, reviewer_output: str, tester_output: str = "PASS - fine") -> _dispatch.Runner:
        def _run(
            member_id: str,
            session_id: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _oc.AgentRunResult:
            role = _role_of(member_id)
            if role == "reviewer":
                output = reviewer_output
            elif role == "tester":
                output = tester_output
            else:
                output = "ok"
            return _oc.AgentRunResult(ok=True, output=output, cost_usd=0.0, raw={})

        return _run

    def test_approve_advances_to_done(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t1", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=self._runner("APPROVE - looks good"))
        assert res.status == "done"
        assert [h.role for h in res.hops] == ["lead", "implementer", "reviewer", "tester"]

    def test_approve_case_insensitive(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t1b", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=self._runner("approve, ship it"))
        assert res.status == "done"

    def test_unparseable_reviewer_output_fails(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t2", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=self._runner("this looks fine I guess"))
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
        ) -> _oc.AgentRunResult:
            calls.append(_role_of(member_id))
            output = "no marker here" if _role_of(member_id) == "reviewer" else "ok"
            return _oc.AgentRunResult(ok=True, output=output, cost_usd=0.0, raw={})

        task: dict[str, Any] = {"id": "t3", "description": "work", "status": "pending"}
        _dispatch.dispatch_task("myapp", task, runner=_run)
        assert calls == ["lead", "implementer", "reviewer"]

    def test_unparseable_emits_distinct_trace_event(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t4", "description": "work", "status": "pending"}
        _dispatch.dispatch_task("myapp", task, runner=self._runner("hmm not sure"))
        events = _trace_events("myapp")
        types = [e["event_type"] for e in events]
        assert "reviewer_verdict_unparseable" in types
        assert "review_rejected" not in types

    def test_empty_reviewer_output_is_unparseable_not_rejection(self, tmp_path: Path) -> None:
        _seed_full_pod()
        task: dict[str, Any] = {"id": "t5", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=self._runner(""))
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
        ) -> _oc.AgentRunResult:
            return _oc.AgentRunResult(ok=True, output="ok", cost_usd=0.0, raw={})

        task: dict[str, Any] = {"id": "t6", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("leanapp", task, runner=_run)
        assert res.status == "done"
        assert [h.role for h in res.hops] == ["lead", "implementer"]


# ── bounded rework loop ─────────────────────────────────────────────────────────


class _ReworkRunner:
    """Reviewer REQUEST-CHANGES the first N times it's called, then APPROVEs.

    Tester always PASSes (when reached). Records every ``(role, message)`` call
    so tests can assert on both call order and message content (the rework
    brief carrying the review text).
    """

    def __init__(
        self,
        request_changes_count: int = 1,
        review_text: str = "REQUEST-CHANGES\nRename the helper and add type hints.",
    ) -> None:
        self.calls: list[tuple[str, str]] = []
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
    ) -> _oc.AgentRunResult:
        role = _role_of(member_id)
        self.calls.append((role, message))
        if role == "reviewer":
            self._reviewer_calls += 1
            if self._reviewer_calls <= self.request_changes_count:
                return _oc.AgentRunResult(ok=True, output=self.review_text, cost_usd=0.01, raw={})
            return _oc.AgentRunResult(ok=True, output="APPROVE - fixed", cost_usd=0.01, raw={})
        if role == "tester":
            return _oc.AgentRunResult(ok=True, output="PASS - fine", cost_usd=0.01, raw={})
        return _oc.AgentRunResult(ok=True, output=f"done by {member_id}", cost_usd=0.01, raw={})


class TestReviewerReworkLoop:
    def test_request_changes_triggers_one_rework_then_approves(self, tmp_path: Path) -> None:
        _seed_full_pod()
        runner = _ReworkRunner(request_changes_count=1)
        task: dict[str, Any] = {"id": "r1", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=runner)

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

    def test_rework_brief_carries_the_review_text(self, tmp_path: Path) -> None:
        _seed_full_pod()
        runner = _ReworkRunner(request_changes_count=1)
        task: dict[str, Any] = {"id": "r2", "description": "work", "status": "pending"}
        _dispatch.dispatch_task("myapp", task, runner=runner)

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
        _dispatch.dispatch_task("myapp", task, runner=runner)
        events = _trace_events("myapp")
        rework_events = [e for e in events if e["event_type"] == "rework_started"]
        assert len(rework_events) == 1
        assert rework_events[0]["payload"]["cycle"] == 1

    def test_second_request_changes_fails_the_task(self, tmp_path: Path) -> None:
        _seed_full_pod()  # default maxReworkCycles is 1
        runner = _ReworkRunner(request_changes_count=2)  # always rejects
        task: dict[str, Any] = {"id": "r4", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=runner)

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
        _dispatch.dispatch_task("myapp", task, runner=runner)
        events = _trace_events("myapp")
        ev = next(e for e in events if e["event_type"] == "review_rejected")
        assert ev["payload"]["cycles"] == 1

    def test_rework_hops_appear_in_persisted_queue(self, tmp_path: Path) -> None:
        _seed_full_pod()
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _ReworkRunner(request_changes_count=1)
        results = _dispatch.dispatch_pod("myapp", runner=runner)

        assert results[0].status == "done"
        persisted = _dispatch.read_tasks("myapp")[0]
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
        res = _dispatch.dispatch_task("myapp", task, runner=runner)

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
        assert _dispatch.pod_max_rework_cycles("myapp") == 1

    def test_max_rework_cycles_reads_lead_meta(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead", {"maxReworkCycles": "3"})
        assert _dispatch.pod_max_rework_cycles("myapp") == 3

    def test_max_rework_cycles_invalid_value_falls_back_to_default(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead", {"maxReworkCycles": "not-a-number"})
        assert _dispatch.pod_max_rework_cycles("myapp") == 1


# ── resume mid-rework: the integration point that matters most ─────────────────


class _CrashOnSecondImplementerCallRunner:
    """Simulates a hard crash exactly between a persisted REQUEST-CHANGES
    Reviewer hop and the rework Implementer hop it should drive.

    The first Implementer call and the first Reviewer call succeed normally
    (Reviewer REQUEST-CHANGES, which gets persisted via ``on_hop`` before
    dispatch ever tries to run the rework Implementer hop). The *second*
    Implementer call — the rework hop — raises, matching what a real crash
    looks like: the request went out, but the process died before a result
    (and therefore a persisted hop) came back.
    """

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
    ) -> _oc.AgentRunResult:
        role = _role_of(member_id)
        self.calls.append(role)
        if role == "implementer":
            self._impl_calls += 1
            if self._impl_calls == 2:
                raise RuntimeError("simulated crash mid-rework")
            return _oc.AgentRunResult(ok=True, output=f"done by {member_id}", cost_usd=0.01, raw={})
        if role == "reviewer":
            return _oc.AgentRunResult(
                ok=True, output="REQUEST-CHANGES\nfix the widget", cost_usd=0.01, raw={}
            )
        return _oc.AgentRunResult(ok=True, output=f"done by {member_id}", cost_usd=0.01, raw={})


class TestReviewerReworkResume:
    def test_resume_continues_into_rework_implementer_not_past_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_full_pod()
        _dispatch.enqueue_task("myapp", "Resume me mid-rework")

        crasher = _CrashOnSecondImplementerCallRunner()
        with pytest.raises(RuntimeError, match="simulated crash mid-rework"):
            _dispatch.dispatch_pod("myapp", runner=crasher)

        # lead, implementer, and the REQUEST-CHANGES reviewer hop were all
        # persisted before the crash; the rework implementer's request went
        # out (recorded in crasher.calls) but never came back.
        assert crasher.calls == ["lead", "implementer", "reviewer", "implementer"]
        tasks = _dispatch.read_tasks("myapp")
        assert tasks[0]["status"] == "running"
        assert [h["role"] for h in tasks[0]["hops"]] == ["lead", "implementer", "reviewer"]

        # Force the claim stale, exactly like R-1's own crash-recovery tests.
        monkeypatch.setattr(_cfg, "CLAIM_STALE_TIMEOUT", -1, raising=True)

        resumer = _ReworkRunner(request_changes_count=0)  # approves whenever asked
        results = _dispatch.dispatch_pod("myapp", runner=resumer, resume=True)

        assert len(results) == 1
        assert results[0].status == "done"
        # The critical assertion: resume re-enters at the REWORK IMPLEMENTER
        # hop first — not a second Reviewer call, and not skipping straight to
        # the Tester. A naive role-based "already done" resume (pre-R-4) would
        # have seen "reviewer" already in the persisted hops and skipped
        # straight past it to the Tester, silently dropping the rework.
        roles_resumed = [c[0] for c in resumer.calls]
        assert roles_resumed == ["implementer", "reviewer", "tester"]

        final = _dispatch.read_tasks("myapp")[0]
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rework note must survive a crash+resume, not just a live run."""
        _seed_full_pod()
        _dispatch.enqueue_task("myapp", "Resume me mid-rework")

        crasher = _CrashOnSecondImplementerCallRunner()
        with pytest.raises(RuntimeError):
            _dispatch.dispatch_pod("myapp", runner=crasher)
        monkeypatch.setattr(_cfg, "CLAIM_STALE_TIMEOUT", -1, raising=True)

        resumer = _ReworkRunner(request_changes_count=0)
        _dispatch.dispatch_pod("myapp", runner=resumer, resume=True)

        rework_message = next(msg for role, msg in resumer.calls if role == "implementer")
        assert "REWORK REQUIRED" in rework_message
        assert "fix the widget" in rework_message
