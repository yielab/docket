"""Screening what a tool returns: a remote tool's or a skill's text is untrusted input.

The policy judgment and its audit live behind the ``ToolGate`` port; this builds the
``ToolOutcome`` the model reads from the verdict.
"""

from __future__ import annotations

from docket.agent.ports import tool_gate

# ToolOutcome is re-exported: a caller that screens text builds one without a second import.
from docket.agent.tools.registry import ToolOutcome as ToolOutcome


def screen_tool_result(
    role: str,
    outcome: ToolOutcome,
    *,
    source: str,
    detail: str,
    blocked_action: str,
    warn_action: str,
    project: str = "",
) -> ToolOutcome:
    """Screen a remote tool result as untrusted `pre_input` (the calling pod's policies
    included): block refuses, redact strips, warn passes; each non-allow hit is audited under
    the caller's action names; *source* names the origin, *detail* prefixes the audit."""
    text = outcome.content if outcome.ok else outcome.error
    if not text:
        return outcome
    hit = tool_gate.screen_untrusted(
        role,
        text,
        project=project,
        detail=detail,
        blocked_action=blocked_action,
        warn_action=warn_action,
    )
    if hit.action in ("block", "require_approval"):
        return ToolOutcome(
            False,
            error=f"result from {source} blocked by policy {hit.policy_id!r} (action={hit.action})",
            refusal=outcome.refusal,
        )
    if hit.action == "redact":
        if outcome.ok:
            return ToolOutcome(True, content=hit.redacted)
        return ToolOutcome(False, error=hit.redacted, refusal=outcome.refusal)
    return outcome
