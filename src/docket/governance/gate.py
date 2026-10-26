"""The tool-call gate: whether one call may run, and what a human is asked when it may not yet.

``agent.tools.registry.dispatch_tool`` reaches this through the ``ToolGate`` port
(``agent.ports.tool_gate``), bound to this module by ``bootstrap.bind_adapters`` and by the
runtime package's ``_bind``. ``govern`` is the one entry: it combines the argument-aware command
classifier with the ``pre_tool_call`` policy hook (most restrictive wins), audits every non-allow
decision here and never in a caller, and settles an ``ask`` by pre-grant, refusal, parking or an
in-turn approval wait. The decisions themselves are the pure functions of ``gate_rules``; the
order of operations is pinned in ``specs/functional/security-gates.spec.md``.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Any

from docket.governance import approval as _approval
from docket.governance import approval_pregrant as _approval_pregrant
from docket.governance import gate_rules as _rules
from docket.governance import policy as _policy
from docket.governance import ports as _ports
from docket.governance.audit import audit_log
from docket.governance.gate_rules import AskRoute
from docket.governance.secrets import redact as _redact
from docket.governance.security import classify_command
from docket.kernel.gate import (
    Decision,
    GateCall,
    GateContext,
    GateDecision,
    GatedTool,
    Screened,
)
from docket.kernel.operator_contract import canonical_args_digest
from docket.kernel.ports import git as _git


@dataclass(frozen=True)
class ToolVerdict:
    """The gate's answer for one call. ``policy_action``/``policy_id`` carry the *raw*
    ``pre_tool_call`` hit, independent of what decided ``decision`` -- so a caller can
    see a ``warn``/``redact`` fired even when the overall decision is ``allow``.
    ``policy_action`` is ``""`` when no policy matched, ``"allow"`` when one matched
    but allowed."""

    decision: Decision
    reason: str = ""
    policy_id: str = ""
    policy_action: str = ""


def render_tool_call(name: str, args: dict[str, Any]) -> str:
    """Render one tool call as the text a ``pre_tool_call`` regex policy matches.
    Pinned contract: ``"<name> <key>=<json-value> ..."``, keys in ``args``' own order,
    each value ``json.dumps``-encoded; a no-argument call renders as just ``name``.
    Putting the name first keeps a command-shaped regex (``rm\\s+-[rf]``) matching
    this render the same way it matches the bare command -- it is *not* symmetric, so
    a pattern assuming an argument appears *before* its verb will not match. See
    specs/functional/security-gates.spec.md item 1."""
    parts = [name]
    for key, value in args.items():
        parts.append(f"{key}={json.dumps(value)}")
    return " ".join(parts)


def evaluate_tool_call(tool: GatedTool, args: dict[str, Any], ctx: GateContext) -> ToolVerdict:
    """Decide whether this call may proceed. **The** decision point: combines the
    argument-aware command classifier (``exec`` tools only, not a ``pregranted`` one) and the ``pre_tool_call``
    policy hook in this one function so "what gates a call" has a single answer,
    most-restrictive-wins (deny beats ask beats allow) -- see
    specs/functional/security-gates.spec.md items 1-3 for why argument-awareness
    matters (``git`` is allowlisted, ``git push origin production`` is not). Never audits or
    traces, that is ``govern``'s job."""
    command: tuple[Decision, str] = ("allow", "")
    if tool.kind == "exec" and not tool.pregranted:
        cmd_verdict = classify_command(
            str(args.get("command") or ""),
            extra_bins=frozenset(ctx.allow_commands),
            roots=tuple(ctx.roots),
            jailed=ctx.sandbox == "auto",
        )
        if cmd_verdict.action != "allow":
            command = (_rules.decision_for_command_action(cmd_verdict.action), cmd_verdict.reason)

    call = _policy.ToolCallFacts(
        tool=tool.name,
        args=args,
        branch_of=lambda: _git.git_current_branch(str(ctx.roots[0])) if ctx.roots else "",
        worktree_root=str(ctx.roots[0]) if ctx.roots else "",
    )
    hit = _policy.policy_eval_detail(
        ctx.role, "pre_tool_call", render_tool_call(tool.name, args), project=ctx.project, call=call
    )
    policy = (
        _rules.decision_for_policy_action(hit.action),
        f"policy {hit.policy_id!r}: {hit.message}" if hit.policy_id else "",
    )
    decision, reason = _rules.combine_verdicts(tool.name, command, policy)
    return ToolVerdict(decision, reason, policy_id=hit.policy_id, policy_action=hit.action)


def audit_tool_decision(
    action: str,
    tool_name: str,
    ctx: GateContext,
    detail: str,
    *,
    policy_id: str = "",
    policy_action: str = "",
) -> None:
    """Write one audit entry for a non-``allow`` (or ``warn``/``redact``) gate decision.
    Centralized so every gated call is recorded exactly once regardless of which check
    decided it; arguments are redacted first since they can carry a secret (a token in a
    ``write`` call, a credential in a ``bash`` command). Records ``policy_id``/
    ``policy_action`` as a fixed, ``repr``-quoted pair so a reader can attribute a hit
    without parsing free-text ``detail``."""
    audit_log(
        action,
        f"tool={tool_name} agent={ctx.agent_id or '?'} role={ctx.role or '?'} "
        f"project={ctx.project or '?'} policy_id={policy_id!r} policy_action={policy_action!r}: "
        f"{_redact(detail)}",
    )


def govern(call: GateCall, ctx: GateContext) -> GateDecision:
    """Decide *call*: ``allow`` it, or ``deny`` it with the kind and reason to report.

    Audits every ``warn``/``redact`` hit, denial and ask; an ``ask`` is settled here (see
    ``_settle_ask``), so the answer is never ``ask``."""
    tool, args = call.tool, call.args
    verdict = evaluate_tool_call(tool, args, ctx)
    policy_id = verdict.policy_id if verdict.decision != "allow" else ""

    if verdict.policy_action in ("warn", "redact"):
        # Allowed to proceed, but a policy still flagged it -- silently
        # letting this through would waste the policy.
        audit_tool_decision(
            f"tool.{verdict.policy_action}",
            tool.name,
            ctx,
            f"call={render_tool_call(tool.name, args)}",
            policy_id=verdict.policy_id,
            policy_action=verdict.policy_action,
        )

    if verdict.decision == "deny":
        audit_tool_decision(
            "tool.deny",
            tool.name,
            ctx,
            f"{verdict.reason} call={render_tool_call(tool.name, args)}",
            policy_id=verdict.policy_id,
            policy_action=verdict.policy_action,
        )
        return GateDecision(
            "deny",
            verdict.reason,
            policy_id=policy_id,
            denial_kind="gate_denied",
            error=verdict.reason,
        )

    if verdict.decision == "ask":
        return _settle_ask(call, ctx, verdict)
    return GateDecision("allow", verdict.reason, policy_id=policy_id)


def _settle_ask(call: GateCall, ctx: GateContext, verdict: ToolVerdict) -> GateDecision:
    """An ``ask`` verdict: a matching pre-grant, ``refuse``, ``park``, or ``wait``."""
    tool, args = call.tool, call.args
    rendered = render_tool_call(tool.name, args)
    audit_tool_decision(
        "tool.ask",
        tool.name,
        ctx,
        f"{verdict.reason} call={rendered}",
        policy_id=verdict.policy_id,
        policy_action=verdict.policy_action,
    )
    digest = canonical_args_digest(tool.name, args)
    pregrant_token = consume_matching_pregrant(ctx, tool.name, digest)
    route: AskRoute = _rules.ask_route(ctx.approval_mode, pregrant_token is not None)

    if route == "pregrant":
        # A human already approved this exact call, ahead of time, by its canonical argument
        # digest -- consumed once, above, so it falls straight through to execution.
        return GateDecision(
            "allow",
            f"pre-granted (token={pregrant_token})",
            policy_id=verdict.policy_id,
            approval_token=pregrant_token or "",
        )
    summary = (f"tool call {tool.name!r}: {verdict.reason}; call={rendered}")[:1000]
    if route == "refuse":
        # No approval record, no wait: the pod's posture says nobody will answer. Reported
        # distinctly from a timeout or an explicit denial ("nobody was asked").
        _ports.approval_refused(
            project=ctx.project,
            role=ctx.role,
            task_id=ctx.task_id,
            caused_by=call.call_id,
            prompt=summary,
        )
        return GateDecision(
            "deny",
            verdict.reason,
            policy_id=verdict.policy_id,
            denial_kind="approval_unavailable",
            error=verdict.reason,
        )

    rationale, blocked = _approval.screen_rationale(ctx.rationale, ctx.project)
    if route == "park":
        token = _park(call, ctx, summary, digest, rationale, blocked)
        reason = _rules.parked_reason(verdict.reason, tool.name)
        return GateDecision(
            "deny",
            reason,
            policy_id=verdict.policy_id,
            denial_kind="approval_parked",
            error=reason,
            approval_token=token,
        )

    token = _approval.approval_create(
        ctx.project or "operator",
        ctx.role or "tool",
        summary,
        context={"tool": tool.name, "callId": call.call_id, "argsDigest": digest},
        rationale=rationale,
        rationale_blocked=blocked,
    )
    _ports.approval_opened(token, task_id=ctx.task_id, caused_by=call.call_id)
    return _wait(token, ctx, tool.name, digest, verdict)


def _park(
    call: GateCall, ctx: GateContext, summary: str, digest: str, rationale: str, blocked: bool
) -> str:
    """Record the exact call and return its approval token without waiting -- a later grant
    re-enters the pipeline with a single-use pre-grant for it (tasks/application/actions.py's
    resume path)."""
    park_context: dict[str, Any] = {
        "tool": call.tool.name,
        "callId": call.call_id,
        "argsDigest": digest,
        "parked": True,
    }
    if ctx.project:
        park_context["project"] = ctx.project
    if ctx.role:
        park_context["role"] = ctx.role
    if ctx.task_id:
        park_context["taskId"] = ctx.task_id  # lets the inbox fold this approval into its task
    token = _approval.approval_create(
        ctx.project or "operator",
        ctx.role or "tool",
        summary,
        context=park_context,
        expires_at=ctx.approval_expires_at,
        rationale=rationale,
        rationale_blocked=blocked,
    )
    _ports.approval_opened(token, task_id=ctx.task_id, caused_by=call.call_id)
    return token


def consume_matching_pregrant(ctx: GateContext, tool_name: str, digest: str) -> str | None:
    """Return the token of the first pre-grant whose ``(tool, args_digest)`` matches and
    that consumed cleanly, or ``None``. A pre-grant past its own expiry, or already
    consumed by a concurrent caller, does not match."""
    for pregrant in ctx.pregrants:
        if (
            pregrant.tool == tool_name
            and pregrant.args_digest == digest
            and _approval_pregrant.consume_pregrant(pregrant.token)
        ):
            return pregrant.token
    return None


def _wait(
    token: str, ctx: GateContext, tool_name: str, digest: str, verdict: ToolVerdict
) -> GateDecision:
    """Block on *token* (the ``wait`` posture, the in-turn gate) and report how it ended."""
    kwargs: dict[str, Any] = {}
    if ctx.approval_timeout is not None:
        kwargs["timeout"] = ctx.approval_timeout
    if ctx.cancellation_check is not None:
        kwargs["cancellation_check"] = ctx.cancellation_check
    # A run without cancellation or a bound keeps the embeddable runtime's one-argument stub.
    outcome = _approval.wait_for_approval(token, **kwargs)
    kind, reason = _rules.settle_wait(
        granted=outcome.state == "granted",
        cancelled=bool(outcome.cancelled),
        timed_out=bool(outcome.timed_out),
        cancel_requested=ctx.cancellation_check is not None and ctx.cancellation_check(),
        asked_because=verdict.reason,
    )
    policy_id = verdict.policy_id
    if kind is not None:
        return GateDecision("deny", reason, policy_id=policy_id, denial_kind=kind, error=reason)
    # Granted: the call is now allowed, and falls through to execute.
    return GateDecision(
        "allow",
        f"approved (token={token})",
        policy_id=policy_id,
        granted=_task_pregrant(token, ctx, tool_name, digest),
    )


def wait_for_answer(token: str, ctx: GateContext) -> GateDecision:
    """Block on the approval record *token* until a person settles it, as a gated call does in
    the turn: ``allow`` when it is granted, else a ``deny`` of kind ``approval_denied``,
    ``approval_timeout`` or ``run_cancelled``. A consult that waits in the turn reuses it."""
    return _wait(token, ctx, "", "", ToolVerdict("ask"))


def _task_pregrant(
    token: str, ctx: GateContext, tool_name: str, digest: str
) -> tuple[str, str, str] | None:
    """``approve_task``: a grant that chose that option also pre-grants one identical call
    for the rest of this turn's context, through the existing ``create_pregrant`` path."""
    if not tool_name or not digest:
        return None
    try:
        record = _approval.approval_get(token)
        if (record.get("context") or {}).get("optionId") != "approve_task":
            return None
        pre = _approval_pregrant.create_pregrant(
            ctx.project or "operator",
            ctx.role or "tool",
            tool_name,
            digest,
            channel="cli",
            actor="approve_task",
        )
    except _approval.ApprovalError:
        return None
    return (pre, tool_name, digest)


def audit_refusal(call: GateCall, ctx: GateContext, kind: str) -> None:
    """Audit a refusal a handler made itself: tool, kind and the attempted path or host only."""
    if kind == "fetch_not_allowed":
        host = urllib.parse.urlsplit(str(call.args.get("url", ""))).hostname or "?"
        target = f"host={host.lower()!r}"
    else:
        target = f"path={str(call.args.get('path', ''))!r}"
    audit_tool_decision("tool.refused", call.tool.name, ctx, f"kind={kind} {target}")


def audit_event(action: str, detail: str) -> None:
    """Append *detail* to the audit log under *action*: an event a tool adapter records itself."""
    audit_log(action, detail)


def screen_untrusted(
    role: str,
    text: str,
    *,
    project: str,
    detail: str,
    blocked_action: str,
    warn_action: str,
) -> Screened:
    """Judge *text* from outside docket (a remote tool's result or description, a skill body) as
    untrusted ``pre_input`` -- the calling pod's policies included -- and audit a non-allow hit
    under the caller's action names, *detail* prefixing the entry."""
    hit = _policy.policy_eval_detail(role, "pre_input", text, trusted=False, project=project)
    audit_detail = f"{detail} policy={hit.policy_id!r} action={hit.action}"
    if hit.action in ("block", "require_approval"):
        audit_log(blocked_action, audit_detail)
    elif hit.action in ("warn", "redact"):
        audit_log(warn_action, audit_detail)
    return Screened(hit.action, hit.policy_id, _redact(text) if hit.action == "redact" else "")
