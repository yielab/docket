"""Framework-neutral governance scenarios shared by both Wave 28 adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PolicyFixture = Literal["none", "block", "require_approval"]
ExpectedDecision = Literal["allow", "invalid_call", "gate_denied", "approval_denied"]
ExpectedStop = Literal["final_message", "token_budget"]

ADVERTISED_TOOLS = ("read_state", "mutate_state")
PLANTED_BYPASSES = ("native_bash", "native_file_editor")
FINAL_SUMMARY = "portable governance proof complete"


@dataclass(frozen=True)
class ReportedUsageFixture:
    """Endpoint-reported token counts, never an estimate."""

    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0


@dataclass(frozen=True)
class GovernanceScenario:
    """One immutable action and its observable governance outcome."""

    name: str
    tool_name: str
    arguments: str
    usage: ReportedUsageFixture
    policy: PolicyFixture = "none"
    approval_response: bool | None = None
    expected_decision: ExpectedDecision = "allow"
    expected_stop: ExpectedStop = "final_message"
    expected_mutations: int = 0


SCENARIOS = (
    GovernanceScenario(
        name="allow_read",
        tool_name="read_state",
        arguments="{}",
        usage=ReportedUsageFixture(1, 1),
    ),
    GovernanceScenario(
        name="unknown_native_bash",
        tool_name="native_bash",
        arguments='{"command":"printf bypass"}',
        usage=ReportedUsageFixture(1, 1),
        expected_decision="invalid_call",
    ),
    GovernanceScenario(
        name="unknown_native_file_editor",
        tool_name="native_file_editor",
        arguments='{"path":"state.txt","value":"bypass"}',
        usage=ReportedUsageFixture(1, 1),
        expected_decision="invalid_call",
    ),
    GovernanceScenario(
        name="policy_denied_mutation",
        tool_name="mutate_state",
        arguments='{"value":"policy denied"}',
        usage=ReportedUsageFixture(1, 1),
        policy="block",
        expected_decision="gate_denied",
    ),
    GovernanceScenario(
        name="approval_denied_mutation",
        tool_name="mutate_state",
        arguments='{"value":"approval denied"}',
        usage=ReportedUsageFixture(1, 1),
        policy="require_approval",
        approval_response=False,
        expected_decision="approval_denied",
    ),
    GovernanceScenario(
        name="approval_granted_mutation",
        tool_name="mutate_state",
        arguments='{"value":"approval granted"}',
        usage=ReportedUsageFixture(1, 1),
        policy="require_approval",
        approval_response=True,
        expected_mutations=1,
    ),
    GovernanceScenario(
        name="reported_token_budget",
        tool_name="mutate_state",
        arguments='{"value":"over budget"}',
        usage=ReportedUsageFixture(8, 3),
        expected_stop="token_budget",
    ),
)
