"""Cache-hit ratio and tokens per accepted task (observability/figures.py)."""

from __future__ import annotations

from typing import Any

from docket.observability import figures

SUBJECT = "docket.observability.figures"


def _call(role: str, task: str | None, input_tokens: Any, cached: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "agent_role": role,
        "event_type": "llm_call",
        "payload": {"inputTokens": input_tokens, "cachedTokens": cached, "outputTokens": 5},
    }
    if task is not None:
        record["task_id"] = task
    return record


class TestCacheHit:
    def test_is_cached_over_input(self) -> None:
        assert figures.cache_hit({"inputTokens": 180, "cachedTokens": 45}) == 0.25

    def test_a_backend_reporting_no_cache_reads_zero(self) -> None:
        assert figures.cache_hit({"inputTokens": 120, "cachedTokens": 0}) == 0.0
        assert figures.cache_hit({"inputTokens": 120}) == 0.0

    def test_has_no_ratio_without_a_positive_integer_input(self) -> None:
        assert figures.cache_hit({}) is None
        assert figures.cache_hit({"inputTokens": 0, "cachedTokens": 0}) is None
        assert figures.cache_hit({"inputTokens": "12", "cachedTokens": 3}) is None
        assert figures.cache_hit({"inputTokens": True, "cachedTokens": 1}) is None


class TestFoldCacheHits:
    def test_sums_per_task_and_per_role_then_divides(self) -> None:
        records = [
            _call("implementer", "t1", 100, 0),
            _call("implementer", "t1", 300, 200),
            _call("lead", "t1", 100, 50),
            _call("implementer", "t2", 600, 0),
        ]

        folded = figures.fold_cache_hits(records)

        assert folded.by_task["t1"].ratio == 250 / 500
        assert folded.by_task["t2"].ratio == 0.0
        assert folded.by_role["implementer"].ratio == 200 / 1000
        assert folded.by_role["lead"].ratio == 0.5
        assert folded.total.ratio == 250 / 1100

    def test_a_record_without_a_task_counts_for_its_role_only(self) -> None:
        folded = figures.fold_cache_hits([_call("reviewer", None, 100, 10)])

        assert folded.by_task == {}
        assert folded.by_role["reviewer"].ratio == 0.1

    def test_skips_other_events_and_malformed_payloads(self) -> None:
        records: list[dict[str, Any]] = [
            {"agent_role": "lead", "event_type": "tool_call", "payload": {"inputTokens": 9}},
            {"agent_role": "lead", "event_type": "llm_call", "payload": "oops"},
            _call("lead", "t1", "many", 1),
        ]

        folded = figures.fold_cache_hits(records)

        assert folded.by_role == {} and folded.by_task == {}

    def test_a_role_with_no_input_has_no_ratio(self) -> None:
        folded = figures.fold_cache_hits([_call("lead", "t1", 0, 0)])

        assert folded.by_role["lead"].ratio is None


class TestTokensPerAcceptedTask:
    def test_is_the_mean_of_the_counted_tokens(self) -> None:
        assert figures.tokens_per_accepted_task([100, 300, 200]) == 200.0

    def test_has_no_figure_without_an_accepted_task(self) -> None:
        assert figures.tokens_per_accepted_task([]) is None


T0 = 1_800_000_000.0
IN = "2027-01-15T08:00:00Z"
OUT = "2026-12-01T08:00:00Z"
SINCE = T0 - 3600 * 24 * 30


def _outcome(pod: str, role: str, done: bool, verdicts: tuple[tuple[str, str], ...] = ()) -> Any:
    return figures.TaskOutcome(pod, role, done, T0, verdicts)


def _ev(event: str, role: str, ts: str = IN, **payload: Any) -> dict[str, Any]:
    return {
        "ts": ts,
        "project": "p",
        "agent_role": role,
        "event_type": event,
        "payload": payload,
    }


def _audit(action: str, detail: str, ts: str = IN) -> dict[str, Any]:
    return {"ts": ts, "action": action, "detail": detail}


def _ask(role: str = "implementer", pod: str = "p", ts: str = IN) -> dict[str, Any]:
    detail = f"tool=bash agent=a role={role} project={pod} policy_id='' policy_action='': x"
    return _audit("tool.ask", detail, ts)


def _approval(action: str, token: str, channel: str, pod: str = "p") -> dict[str, Any]:
    return _audit(action, f"token={token} project={pod} channel={channel}")


class TestRatio:
    def test_has_no_value_without_a_denominator(self) -> None:
        assert figures.Ratio(0, 0).value is None
        assert figures.Ratio(1, 4).value == 0.25
        assert figures.Ratio(1, 4).per_100 == 25.0


class TestTaskFigures:
    def test_success_is_done_over_terminal_by_pod_and_last_role(self) -> None:
        outcomes = [
            _outcome("p", "reviewer", True),
            _outcome("p", "reviewer", True),
            _outcome("p", "reviewer", False),
            _outcome("p", "implementer", False),
            figures.TaskOutcome("p", "reviewer", True, T0 - 3600 * 24 * 40),
        ]

        folded = figures.fold_work_figures(outcomes=outcomes, since=SINCE)

        assert folded.success[("p", "reviewer")] == figures.Ratio(2, 3)
        assert folded.success[("p", "implementer")] == figures.Ratio(0, 1)

    def test_reviewer_rejection_is_non_approve_over_verdicts(self) -> None:
        verdicts = (("reviewer", "approve"), ("reviewer", "request-changes"))
        outcomes = [
            _outcome("p", "reviewer", True, verdicts),
            _outcome("p", "reviewer", True, (("reviewer", "approve"),)),
            _outcome("p", "implementer", False),
        ]

        folded = figures.fold_work_figures(outcomes=outcomes, since=SINCE)

        assert folded.reviewer_rejection == {("p", "reviewer"): figures.Ratio(1, 3)}


class TestReworkCycles:
    def test_counts_rework_events_over_dispatched_tasks_the_role_took_part_in(self) -> None:
        start = _ev("session_start", "lead", source="dispatch", task="t")
        rework = _ev("rework_started", "reviewer", cycle=1)
        other = _ev("verdict_rework_started", "writer", cycle=1)
        files = [
            [start, _ev("hop_started", "implementer"), rework, other],
            [start, _ev("hop_started", "implementer"), _ev("hop_started", "reviewer")],
            [_ev("session_start", "lead", source="dispatch", resumed=True, ts=OUT)],
            [_ev("session_start", "lead", source="enqueue")],
        ]

        folded = figures.fold_work_figures(trace_files=files, since=SINCE)

        assert folded.rework_cycles[("p", "reviewer")] == figures.Ratio(1, 2)
        assert folded.rework_cycles[("p", "implementer")] == figures.Ratio(0, 2)
        assert folded.rework_cycles[("p", "writer")] == figures.Ratio(1, 1)


class TestAskFigures:
    def test_asks_per_calls_denials_and_grants_per_ask(self) -> None:
        calls = [_ev("tool_result", "implementer", decision="allow") for _ in range(8)]
        calls += [_ev("tool_result", "implementer", decision="ask") for _ in range(2)]
        calls += [_ev("tool_result", "implementer", decision="deferred")]
        calls += [_ev("tool_result", "implementer", decision="allow", ts=OUT)]
        audit = [
            _ask(),
            _ask(),
            _ask(ts=OUT),
            _approval("approval.grant", "a1", "cli"),
            _approval("approval.deny", "a2", "http"),
            _approval("approval.deny", "a3", "timeout"),
        ]
        roles = {"a1": "implementer", "a2": "implementer", "a3": "implementer"}

        folded = figures.fold_work_figures(
            trace_files=[calls], audit=audit, approval_roles=roles, since=SINCE
        )

        assert folded.asks[("p", "implementer")] == figures.Ratio(2, 10)
        assert folded.human_denials[("p", "implementer")] == figures.Ratio(1, 2)
        assert folded.granted[("p", "implementer")] == figures.Ratio(1, 2)

    def test_an_approval_whose_record_is_gone_counts_for_unknown(self) -> None:
        audit = [_ask(role="?"), _approval("approval.grant", "gone", "cli")]

        folded = figures.fold_work_figures(audit=audit, approval_roles={}, since=SINCE)

        assert folded.granted[("p", "unknown")] == figures.Ratio(1, 1)
