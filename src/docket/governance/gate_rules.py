"""The tool-call gate's decisions as pure functions over facts: no audit, no approval store.

``governance.gate`` gathers the facts (the command classifier's verdict, the policy hit, whether a
pre-grant matched, how an approval wait ended) and calls these; the table tests in
``tests/unit/governance/test_gate_rules.py`` pin every row.
"""

from __future__ import annotations

from typing import Literal

from docket.kernel.gate import CONSULT_TOOL, Decision, ToolDenialKind

# Most-restrictive-wins ranking over the three-valued tool decision (policy.py ranks five actions).
DECISION_RANK: dict[str, int] = {"deny": 2, "ask": 1, "allow": 0}

# governance/policy.py action -> tool decision. `warn`/`redact` do not block execution -- they are
# recorded but never change what a call may do, since neither implies a human must decide first.
POLICY_ACTION_TO_DECISION: dict[str, Decision] = {
    "block": "deny",
    "require_approval": "ask",
    "warn": "allow",
    "redact": "allow",
    "allow": "allow",
}

CANCELLED_REASON = "run cancellation requested before execution"

AskRoute = Literal["pregrant", "refuse", "park", "wait"]


def decision_for_policy_action(action: str) -> Decision:
    """The tool decision a ``pre_tool_call`` policy action implies; an unknown action allows."""
    return POLICY_ACTION_TO_DECISION.get(action, "allow")


def decision_for_command_action(action: str) -> Decision:
    """The tool decision the command classifier's action implies: ``ask`` asks, else it denies."""
    if action == "allow":
        return "allow"
    return "ask" if action == "ask" else "deny"


def combine_verdicts(
    tool_name: str,
    command: tuple[Decision, str],
    policy: tuple[Decision, str],
) -> tuple[Decision, str]:
    """Most restrictive wins (deny beats ask beats allow); the command's reason wins a tie.

    ``consult`` is the exception for ``ask``: the consultation is itself the human's decision, so
    asking approval to ask would put the same question to the operator twice. A ``deny`` still
    denies."""
    command_decision, command_reason = command
    policy_decision, policy_reason = policy
    if DECISION_RANK[command_decision] >= DECISION_RANK[policy_decision]:
        decision, reason = command_decision, command_reason
    else:
        decision, reason = policy_decision, policy_reason
    if tool_name == CONSULT_TOOL and decision == "ask":
        decision = "allow"
    return decision, reason


def ask_route(approval_mode: str, pregranted: bool) -> AskRoute:
    """What an ``ask`` verdict turns into: a matching pre-grant first, then the posture."""
    if pregranted:
        return "pregrant"
    if approval_mode == "refuse":
        return "refuse"
    if approval_mode == "park":
        return "park"
    return "wait"


def settle_wait(
    *, granted: bool, cancelled: bool, timed_out: bool, cancel_requested: bool
) -> tuple[ToolDenialKind | None, str]:
    """How an in-turn approval wait ends: ``(None, "")`` when the call may run, else the denial.

    A cancellation requested while waiting beats a grant that arrived with it."""
    if cancel_requested:
        return "run_cancelled", CANCELLED_REASON
    if granted:
        return None, ""
    if cancelled:
        return "run_cancelled", CANCELLED_REASON
    if timed_out:
        return "approval_timeout", "approval timed out and was denied"
    return "approval_denied", "approval denied"
