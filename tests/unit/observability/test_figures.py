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
        folded = figures.fold_cache_hits([_call("tester", None, 100, 10)])

        assert folded.by_task == {}
        assert folded.by_role["tester"].ratio == 0.1

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
