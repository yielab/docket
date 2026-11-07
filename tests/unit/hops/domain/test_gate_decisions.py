"""Each gate decision as a table of cases over plain facts: no disk, no process, no patch."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from docket.hops.domain import gate_decisions as _d

SUBJECT = "docket.hops.domain.gate_decisions"


@pytest.mark.parametrize(
    ("verify_cmd", "require_verify", "expected"),
    [
        ("pytest -q", False, "run"),
        ("pytest -q", True, "run"),
        ("", True, "fail_missing"),
        ("", False, "skip"),
    ],
)
def test_verify_precheck(verify_cmd: str, require_verify: bool, expected: str) -> None:
    assert _d.decide_verify_precheck(verify_cmd, require_verify) == expected


@pytest.mark.parametrize(
    ("passed", "routed", "kind", "label", "reason"),
    [
        (True, False, "advance", "pass", ""),
        (True, True, "routed", "pass", ""),
        (False, True, "routed", "fail", ""),
        (False, False, "failed", "", "verifyCmd failed: 'make test'"),
    ],
)
def test_verify_decision(passed: bool, routed: bool, kind: str, label: str, reason: str) -> None:
    decision = _d.decide_verify(passed=passed, routed=routed, cmd="make test")

    assert (decision.kind, decision.label, decision.reason) == (kind, label, reason)


def test_verify_evidence_keeps_the_tail_of_the_redacted_output() -> None:
    assert _d.verify_evidence("c", 1, 1.23456, "abcdef", 3) == {
        "cmd": "c",
        "exitCode": 1,
        "durationS": 1.235,
        "outputTail": "def",
    }


@pytest.mark.parametrize(
    ("label", "routed", "kind", "failure_kind"),
    [
        ("pass", False, "advance", ""),
        ("pass", True, "routed", ""),
        ("needs_human", True, "routed", ""),
        ("fail", False, "failed", "gate_failed"),
        ("needs_human", False, "failed", "gate_needs_human"),
        ("error", False, "failed", "gate_error"),
    ],
)
def test_external_decision(label: str, routed: bool, kind: str, failure_kind: str) -> None:
    decision = _d.decide_external(label=label, routed=routed, cmd="gate.sh")

    assert (decision.kind, decision.failure_kind) == (kind, failure_kind)
    if kind == "failed":
        assert decision.reason == f"external gate {label}: 'gate.sh'"
        assert decision.label == ""
    else:
        assert decision.label == label


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("fail", "gate_failed"),
        ("needs_human", "gate_needs_human"),
        ("error", "gate_error"),
        ("pass", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_external_failure_kind(label: object, expected: str) -> None:
    assert _d.external_failure_kind(label) == expected


@pytest.mark.parametrize(
    ("has_gate", "step", "gate_step", "kind", "label", "expected"),
    [
        (True, "review", "review", "advance", "", True),
        (True, "review", "review", "routed", "pass", True),
        (True, "review", "review", "routed", "fail", False),
        (True, "review", "review", "failed", "", False),
        (True, "review", "review", "rework", "", False),
        (True, "build", "review", "advance", "", False),
        (True, "review", None, "advance", "", False),
        (False, "review", "review", "advance", "", False),
    ],
)
def test_task_gate_runs_only_after_its_step_passed(
    has_gate: bool, step: str, gate_step: str | None, kind: str, label: str, expected: bool
) -> None:
    assert (
        _d.should_run_task_gate(
            has_task_gate=has_gate,
            step_id=step,
            task_gate_step_id=gate_step,
            outcome_kind=kind,
            outcome_label=label,
        )
        is expected
    )


def _screen(text: str) -> str | None:
    return None if "BLOCK" in text else text.strip().upper()


@pytest.mark.parametrize(
    ("doc", "reasons", "invalid"),
    [
        ({"reasons": [{"summary": "a"}]}, [{"summary": "A"}], False),
        (
            {"reasons": [{"summary": "a", "path": "x.py", "line": 3, "ignored": "y"}]},
            [{"summary": "A", "path": "X.PY", "line": 3}],
            False,
        ),
        ({"reasons": [{"summary": "a", "line": True}]}, [{"summary": "A"}], False),
        ({"reasons": [{"summary": "a", "detail": "   "}]}, [{"summary": "A"}], False),
        ({"reasons": []}, [], False),
        ({"reasons": [{"summary": "a"}, {"summary": 3}]}, [], True),
        ({"reasons": [{"id": "only-an-id"}]}, [], True),
        ({"reasons": [{"summary": "   "}]}, [], True),
        ({"reasons": [{"summary": "BLOCK this"}]}, [], True),
        ({"reasons": "text"}, [], True),
        ({"other": 1}, [], True),
        (["reasons"], [], True),
        (None, [], True),
    ],
)
def test_gate_reasons_are_cleaned_screened_or_invalid(
    doc: Any, reasons: list[dict[str, Any]], invalid: bool
) -> None:
    assert _d.clean_gate_reasons(doc, _screen) == (reasons, invalid)


def test_gate_reasons_screen_in_order_and_stop_at_the_first_block() -> None:
    seen: list[str] = []

    def screen(text: str) -> str | None:
        seen.append(text)
        return None if text == "bad" else text

    doc = {"reasons": [{"summary": "ok", "id": "bad", "path": "never"}, {"summary": "later"}]}

    assert _d.clean_gate_reasons(doc, screen) == ([], True)
    assert seen == ["ok", "bad"]


_REWORK = _d.ReworkFacts(when=frozenset({"request-changes"}), max_cycles=2, target_index=0)


def _verdict(verdict: str | None, **kw: Any) -> _d.GateDecision:
    facts: dict[str, Any] = {
        "verdict": verdict,
        "role": "reviewer",
        "pass_values": frozenset({"approve"}),
        "routed": False,
        "rework": _REWORK,
        "cycles_so_far": 0,
    }
    return _d.decide_verdict(**{**facts, **kw})


@pytest.mark.parametrize(
    ("facts", "kind", "label", "event"),
    [
        ({"verdict": "approve"}, "advance", "approve", ""),
        ({"verdict": "approve", "routed": True}, "routed", "approve", ""),
        ({"verdict": "request-changes", "routed": True}, "routed", "request-changes", ""),
        ({"verdict": "reject", "routed": True}, "routed", "reject", ""),
        ({"verdict": "request-changes"}, "rework", "", "rework"),
        ({"verdict": "request-changes", "cycles_so_far": 1}, "rework", "", "rework"),
        ({"verdict": "request-changes", "cycles_so_far": 2}, "failed", "", "rejected"),
        ({"verdict": "request-changes", "rework": None}, "failed", "", "rejected"),
        ({"verdict": "reject"}, "failed", "", "rejected"),
        ({"verdict": None}, "failed", "", "unparseable"),
        ({"verdict": None, "routed": True}, "failed", "", "unparseable"),
    ],
)
def test_verdict_decision(facts: dict[str, Any], kind: str, label: str, event: str) -> None:
    decision = _verdict(**facts)

    assert (decision.kind, decision.label, decision.event) == (kind, label, event)


def test_verdict_rework_names_its_target_cycle_and_the_correction_to_record() -> None:
    decision = _verdict("request-changes", cycles_so_far=1)

    assert decision.rework_target_index == 0
    assert dict(decision.detail) == {"cycle": 2}
    assert decision.record_correction is True
    other = _verdict(
        "fail",
        rework=_d.ReworkFacts(when=frozenset({"fail"}), max_cycles=1, target_index=3),
        pass_values=frozenset({"pass"}),
    )
    assert (other.kind, other.rework_target_index, other.record_correction) == ("rework", 3, False)


def test_verdict_rework_with_no_target_is_terminal() -> None:
    rework = _d.ReworkFacts(when=frozenset({"request-changes"}), max_cycles=2, target_index=None)

    decision = _verdict("request-changes", rework=rework)

    assert decision.kind == "failed"
    assert decision.reason == "reviewer rejected after 0 rework cycle(s): REQUEST-CHANGES"
    assert dict(decision.detail) == {"cycles": 0}


def test_verdict_failure_reasons_and_details() -> None:
    assert _verdict("reject").reason == "reviewer reported REJECT"
    assert dict(_verdict("reject").detail) == {"verdict": "reject"}
    unparseable = _verdict(None)
    assert unparseable.reason.startswith("reviewer output unparseable (expected one unambiguous")
    assert dict(unparseable.detail) == {"verdict": "unparseable"}


@pytest.mark.parametrize(("check_approval", "kind"), [(True, "advance"), (False, "failed")])
def test_approval_gate_after_the_hop(check_approval: bool, kind: str) -> None:
    decision = _d.decide_approval_in_group(check_approval=check_approval, role="reviewer")

    assert decision.kind == kind
    if kind == "failed":
        assert (
            decision.reason
            == "reviewer: an 'approval' gate is not supported inside a parallel group"
        )


@pytest.mark.parametrize(
    ("action", "hop_ok", "trace", "block", "fail_hop"),
    [
        ("allow", True, False, False, False),
        ("warn", True, True, False, False),
        ("redact", True, True, False, False),
        ("block", True, True, True, True),
        ("block", False, True, True, False),
    ],
)
def test_output_guardrail(
    action: str, hop_ok: bool, trace: bool, block: bool, fail_hop: bool
) -> None:
    got = _d.decide_output_guardrail(action=action, policy_id="p1", hop_ok=hop_ok)

    assert (got.action, got.trace_check, got.block, got.fail_hop) == (
        action,
        trace,
        block,
        fail_hop,
    )
    assert got.policy_id == "p1"
    assert got.error == "blocked by guardrail policy 'p1'"


@pytest.mark.parametrize(
    ("pod", "task", "expected"),
    [
        ("open", None, "open"),
        ("open", "none", "none"),
        ("none", None, "none"),
        ("none", "none", "none"),
    ],
)
def test_hop_network_takes_the_narrower(pod: str, task: str | None, expected: str) -> None:
    assert _d.hop_network(pod, task) == expected


@pytest.mark.parametrize(
    ("cap", "usages", "left"),
    [
        (None, [], None),
        (None, [{"input": 5, "output": 5}], None),
        (1000, [], 1000),
        (1000, [{"input": 300, "output": 100}, None], 600),
        (10_000, [{"input": 30_000, "cached": 25_000, "output": 100}] * 2, 10_000 - 2 * 5_100),
        (100, [{"input": 90, "output": 20}], -10),
        (100, [{"input": 5, "cached": 50, "output": 1}], 99),
    ],
)
def test_tokens_left_counts_input_less_cache_plus_output(
    cap: int | None, usages: list[dict[str, int] | None], left: int | None
) -> None:
    assert _d.tokens_left(cap, usages) == left


@pytest.mark.parametrize(
    ("left", "kind"), [(None, "advance"), (1, "advance"), (0, "failed"), (-10, "failed")]
)
def test_task_token_decision(left: int | None, kind: str) -> None:
    decision = _d.decide_task_tokens(left=left, max_tokens=500, role="implementer")

    assert decision.kind == kind
    if kind == "failed":
        assert decision.failure_kind == "budget"
        assert decision.reason == "task token budget reached (maxTokens=500) before implementer"


@pytest.mark.parametrize(
    ("failure_kind", "conversation", "turns", "ends"),
    [
        ("budget", True, 1, True),
        ("budget", True, 0, False),
        ("budget", False, 3, False),
        ("needs_human", True, 2, False),
        ("", True, 2, False),
    ],
)
def test_only_a_conversation_that_answered_ends_on_the_token_budget(
    failure_kind: str, conversation: bool, turns: int, ends: bool
) -> None:
    assert (
        _d.conversation_ends_on_budget(
            failure_kind=failure_kind, conversation=conversation, turns_done=turns
        )
        is ends
    )


@pytest.mark.parametrize(
    ("cap", "spent", "kind", "reason"),
    [
        (None, 99_000, "advance", ""),
        (5000, 1000, "advance", ""),
        (5000, 4999, "advance", ""),
        (
            5000,
            5000,
            "blocked",
            "pod budget reached (5000 of 5000 tokens counted) before implementer",
        ),
        (
            5000,
            6200,
            "blocked",
            "pod budget reached (6200 of 5000 tokens counted) before implementer",
        ),
    ],
)
def test_pod_budget_decision(cap: int | None, spent: int, kind: str, reason: str) -> None:
    decision = _d.decide_pod_budget(cap=cap, spent=spent, role="implementer")

    assert (decision.kind, decision.reason) == (kind, reason)
    if kind == "blocked":
        assert decision.failure_kind == "pod_budget"
        assert decision.event == "budget_exceeded"
        assert dict(decision.detail) == {
            "spent": spent,
            "cap": cap,
            "role": "implementer",
            "window": "none",
            "windowStart": None,
        }


def test_a_windowed_pod_budget_names_the_window_and_where_it_began() -> None:
    start = datetime(2026, 11, 2, tzinfo=UTC)

    decision = _d.decide_pod_budget(cap=1000, spent=1000, role="lead", window="week", since=start)

    assert decision.kind == "blocked"
    assert decision.detail["window"] == "week"
    assert decision.detail["windowStart"] == "2026-11-02T00:00:00Z"


@pytest.mark.parametrize(
    ("window", "now", "expected"),
    [
        ("none", datetime(2026, 11, 4, 15, 0, tzinfo=UTC), None),
        ("day", datetime(2026, 11, 4, 15, 30, 7, tzinfo=UTC), datetime(2026, 11, 4, tzinfo=UTC)),
        ("week", datetime(2026, 11, 4, 15, 0, tzinfo=UTC), datetime(2026, 11, 2, tzinfo=UTC)),
        ("week", datetime(2026, 11, 2, 0, 0, tzinfo=UTC), datetime(2026, 11, 2, tzinfo=UTC)),
        ("week", datetime(2026, 11, 8, 23, 59, tzinfo=UTC), datetime(2026, 11, 2, tzinfo=UTC)),
        ("week", datetime(2026, 11, 9, 0, 0, tzinfo=UTC), datetime(2026, 11, 9, tzinfo=UTC)),
    ],
)
def test_window_start(window: str, now: datetime, expected: datetime | None) -> None:
    assert _d.window_start(window, now) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("task_left", "pod_left", "default", "expected"),
    [
        (None, None, 100_000, None),
        (None, 500_000, 100_000, None),
        (None, 20_000, 100_000, (20_000, "pod_budget")),
        (400_000, None, 100_000, (400_000, "task")),
        (400_000, 500_000, 100_000, (400_000, "task")),
        (400_000, 400_000, 100_000, (400_000, "task")),
        (400_000, 150_000, 100_000, (150_000, "pod_budget")),
    ],
)
def test_turn_token_ceiling_names_the_tighter_owner(
    task_left: int | None, pod_left: int | None, default: int, expected: tuple[int, str] | None
) -> None:
    got = _d.turn_token_ceiling(task_left=task_left, pod_left=pod_left, default=default)

    assert got == expected


@pytest.mark.parametrize(
    ("check", "index", "override", "requires", "expected"),
    [
        (False, 2, 2, True, "proceed"),
        (True, 2, 2, True, "consume_override"),
        (True, 2, 2, False, "consume_override"),
        (True, 2, 7, True, "require"),
        (True, 2, None, True, "require"),
        (True, 2, None, False, "proceed"),
    ],
)
def test_pre_hop_approval(
    check: bool, index: int, override: int | None, requires: bool, expected: str
) -> None:
    got = _d.decide_pre_hop_approval(
        check_approval=check, index=index, override_index=override, requires_approval=requires
    )

    assert got == expected


@pytest.mark.parametrize(
    ("items", "missing"),
    [
        ([], []),
        (["secret:KEY"], []),
        (["secret:NOPE"], ["secret:NOPE"]),
        (["path:/here"], []),
        (["path:/gone"], ["path:/gone"]),
        (["verify"], ["verify"]),
        (["something else"], []),
        (
            ["secret:NOPE", "path:/here", "verify", "path:/gone"],
            ["secret:NOPE", "verify", "path:/gone"],
        ),
    ],
)
def test_missing_resources(items: list[str], missing: list[str]) -> None:
    got = _d.missing_resources(
        items, secrets=frozenset({"KEY"}), existing_paths=frozenset({"/here"}), has_verify_cmd=False
    )

    assert got == missing


def test_a_verify_resource_is_met_by_a_verify_command() -> None:
    got = _d.missing_resources(
        ["verify"], secrets=frozenset(), existing_paths=frozenset(), has_verify_cmd=True
    )

    assert got == []


def test_resources_decision() -> None:
    assert _d.decide_resources([]).kind == "advance"
    blocked = _d.decide_resources(["secret:A", "verify"])
    assert (blocked.kind, blocked.label) == ("blocked", "resources")
    assert blocked.reason == "brief names missing resources: secret:A, verify"


def test_profile_refusal_names_each_unmet_requirement_and_its_fix() -> None:
    assert _d.profile_refusal([]) is None
    got = _d.profile_refusal(
        [("sandbox", "isolation is off", "docket setup sandbox on"), ("gate", "none", "add one")]
    )

    assert got == (
        "sandbox,gate",
        "lights-out profile not met -- sandbox: isolation is off (docket setup sandbox on); "
        "gate: none (add one)",
    )


@pytest.mark.parametrize(
    ("paths", "listed"),
    [
        (["a"], "a"),
        (["a", "b", "c"], "a, b, c"),
        (["a", "b", "c", "d", "e"], "a, b, c and 2 more"),
    ],
)
def test_changed_paths_are_listed_up_to_the_limit(paths: list[str], listed: str) -> None:
    assert _d.describe_changed_paths(paths, 3) == listed
