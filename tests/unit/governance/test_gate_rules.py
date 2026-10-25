"""Each tool-gate decision as a table of cases over plain facts: no disk, no process, no patch."""

from __future__ import annotations

import pytest

from docket.governance import gate_rules as _r
from docket.kernel.gate import Decision

SUBJECT = "docket.governance.gate_rules"


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("block", "deny"),
        ("require_approval", "ask"),
        ("warn", "allow"),
        ("redact", "allow"),
        ("allow", "allow"),
        ("", "allow"),
        ("something-new", "allow"),
    ],
)
def test_policy_action_to_decision(action: str, expected: Decision) -> None:
    assert _r.decision_for_policy_action(action) == expected


@pytest.mark.parametrize(
    ("action", "expected"),
    [("allow", "allow"), ("ask", "ask"), ("deny", "deny"), ("anything-else", "deny")],
)
def test_command_action_to_decision(action: str, expected: Decision) -> None:
    assert _r.decision_for_command_action(action) == expected


@pytest.mark.parametrize(
    ("tool", "command", "policy", "expected"),
    [
        # most restrictive wins
        ("bash", ("deny", "c"), ("allow", ""), ("deny", "c")),
        ("bash", ("allow", ""), ("deny", "p"), ("deny", "p")),
        ("bash", ("ask", "c"), ("allow", ""), ("ask", "c")),
        ("bash", ("allow", ""), ("ask", "p"), ("ask", "p")),
        ("bash", ("deny", "c"), ("ask", "p"), ("deny", "c")),
        ("bash", ("ask", "c"), ("deny", "p"), ("deny", "p")),
        # a tie goes to the command's reason
        ("bash", ("ask", "c"), ("ask", "p"), ("ask", "c")),
        ("bash", ("deny", "c"), ("deny", "p"), ("deny", "c")),
        ("bash", ("allow", ""), ("allow", ""), ("allow", "")),
        # consult: the consultation is the human's decision, so ask becomes allow; deny still denies
        ("consult", ("allow", ""), ("ask", "p"), ("allow", "p")),
        ("consult", ("allow", ""), ("deny", "p"), ("deny", "p")),
        ("consult", ("allow", ""), ("allow", ""), ("allow", "")),
    ],
)
def test_combine_verdicts(
    tool: str,
    command: tuple[Decision, str],
    policy: tuple[Decision, str],
    expected: tuple[Decision, str],
) -> None:
    assert _r.combine_verdicts(tool, command, policy) == expected


@pytest.mark.parametrize(
    ("mode", "pregranted", "expected"),
    [
        ("wait", False, "wait"),
        ("park", False, "park"),
        ("refuse", False, "refuse"),
        ("wait", True, "pregrant"),
        ("park", True, "pregrant"),
        ("refuse", True, "pregrant"),
        ("unknown", False, "wait"),
    ],
)
def test_ask_route(mode: str, pregranted: bool, expected: str) -> None:
    assert _r.ask_route(mode, pregranted) == expected


@pytest.mark.parametrize(
    ("granted", "cancelled", "timed_out", "cancel_requested", "kind", "reason"),
    [
        (True, False, False, False, None, ""),
        (False, False, False, False, "approval_denied", "why; approval denied"),
        (False, False, True, False, "approval_timeout", "why; approval timed out and was denied"),
        (False, True, False, False, "run_cancelled", _r.CANCELLED_REASON),
        # a cancellation requested while waiting beats a grant that arrived with it
        (True, False, False, True, "run_cancelled", _r.CANCELLED_REASON),
        (False, False, True, True, "run_cancelled", _r.CANCELLED_REASON),
        # cancelled is checked before timed out
        (False, True, True, False, "run_cancelled", _r.CANCELLED_REASON),
    ],
)
def test_settle_wait(
    granted: bool,
    cancelled: bool,
    timed_out: bool,
    cancel_requested: bool,
    kind: str | None,
    reason: str,
) -> None:
    assert _r.settle_wait(
        granted=granted,
        cancelled=cancelled,
        timed_out=timed_out,
        cancel_requested=cancel_requested,
        asked_because="why",
    ) == (kind, reason)
