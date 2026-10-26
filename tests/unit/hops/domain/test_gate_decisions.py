"""Each gate decision as a table of cases over plain facts: no disk, no process, no patch."""

from __future__ import annotations

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
    decision = _d.decide_approval_in_group(check_approval=check_approval, role="tester")

    assert decision.kind == kind
    if kind == "failed":
        assert (
            decision.reason == "tester: an 'approval' gate is not supported inside a parallel group"
        )


@pytest.mark.parametrize(
    ("action", "high_risk", "hop_ok", "effective", "trace", "redact", "block", "fail_hop"),
    [
        ("allow", None, True, "allow", False, False, False, False),
        ("allow", "money", True, "warn", True, False, False, False),
        ("warn", "money", True, "warn", True, False, False, False),
        ("redact", "money", True, "redact", True, True, False, False),
        ("block", None, True, "block", True, False, True, True),
        ("block", "money", False, "block", True, False, True, False),
        ("require_approval", None, True, "require_approval", True, False, False, False),
    ],
)
def test_output_guardrail(
    action: str,
    high_risk: str | None,
    hop_ok: bool,
    effective: str,
    trace: bool,
    redact: bool,
    block: bool,
    fail_hop: bool,
) -> None:
    got = _d.decide_output_guardrail(
        action=action, policy_id="p1", high_risk=high_risk, hop_ok=hop_ok
    )

    assert (got.action, got.trace_check, got.redact, got.block, got.fail_hop) == (
        effective,
        trace,
        redact,
        block,
        fail_hop,
    )
    expected_id = "high-risk:money" if effective == "warn" and action == "allow" else "p1"
    assert got.policy_id == expected_id
    assert got.error == f"blocked by guardrail policy '{expected_id}'"


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
    ("cap", "spent", "estimated", "kind", "reason"),
    [
        (0.0, 99.0, False, "advance", ""),
        (5.0, 1.0, False, "advance", ""),
        (5.0, 4.99, True, "advance", ""),
        (5.0, 10.0, False, "blocked", "pod budget reached ($10.00 ≥ $5.00) before implementer"),
        (
            5.0,
            5.0,
            True,
            "blocked",
            "pod budget reached (~$5.00 (estimated — no cost recorded) ≥ $5.00) before implementer",
        ),
    ],
)
def test_pod_budget_decision(
    cap: float, spent: float, estimated: bool, kind: str, reason: str
) -> None:
    decision = _d.decide_pod_budget(cap=cap, spent=spent, estimated=estimated, role="implementer")

    assert (decision.kind, decision.reason) == (kind, reason)
    if kind == "blocked":
        assert decision.event == "budget_exceeded"
        assert dict(decision.detail) == {
            "spent": spent,
            "cap": cap,
            "role": "implementer",
            "estimated": estimated,
        }


@pytest.mark.parametrize(
    ("cap", "unpriced", "warns"),
    [(0.0, True, False), (5.0, False, False), (5.0, True, True)],
)
def test_unpriced_model_warns_only_under_a_budget(cap: float, unpriced: bool, warns: bool) -> None:
    got = _d.unpriced_budget_warning(cap=cap, model="acme/m1", unpriced=unpriced)

    assert (got is not None) is warns
    if warns:
        assert got == "pod budget $5.00 cannot stop this hop: acme/m1 has no price"


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
