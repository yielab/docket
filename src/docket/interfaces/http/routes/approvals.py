"""``GET /approvals`` and ``POST /approvals/<token>`` -- the approval queue over HTTP."""

from __future__ import annotations

import json

from docket.governance import approval
from docket.interfaces.http.exchange import HttpExchange
from docket.tasks.application import actions as _actions

# The channels the HTTP transport itself may claim on POST /approvals/<token>.
# This is narrower than governance.approval.APPROVAL_CHANNELS: "cli", "mcp" and
# "telegram" belong to their own surfaces, and "timeout" is the fail-closed
# expiry path -- an HTTP Bearer holder must not be able to forge a decision
# as coming from any of those. "tack" is the one named HTTP client (Tack's
# board); "http" is the untagged default.
_HTTP_APPROVAL_CHANNELS: frozenset[str] = frozenset({"http", "tack"})


def get_approvals(h: HttpExchange, _arg: str) -> None:
    body = json.dumps({"pending": approval.list_pending()}).encode("utf-8")
    h._send(body, "application/json")


def post_approval(h: HttpExchange, approval_token: str) -> None:
    if not approval_token:
        h._send_json_error("Missing approval token", 400)
        return
    req_body = h._read_json_object(not_object="Invalid JSON body")
    if req_body is None:
        return
    action = str(req_body.get("action", ""))
    if action not in ("grant", "deny"):
        h._send_json_error('action must be "grant" or "deny"', 400)
        return

    # `channel` identifies the surface this decision came through, tagged
    # onto the hash-chained audit log entry (`governance/approval.py`'s
    # `approval_grant`/`approval_deny`). Default stays "http" (every caller
    # before this field existed keeps identical behaviour). Validated
    # against `_HTTP_APPROVAL_CHANNELS`, not the full `approval.
    # APPROVAL_CHANNELS` -- the HTTP transport may not claim a channel
    # ("cli", "mcp", "telegram", "timeout") that belongs to another
    # surface or to the fail-closed expiry path.
    channel = req_body.get("channel", "http")
    if not isinstance(channel, str) or channel not in _HTTP_APPROVAL_CHANNELS:
        h._send_json_error(f"Unrecognised channel: {channel!r}", 400)
        return

    option = req_body.get("option", "")
    if (action != "grant" and option) or option not in ("", "approve_once", "approve_task"):
        h._send_json_error('option must be "approve_once" or "approve_task" (grant only)', 400)
        return
    decision = "granted" if action == "grant" else "denied"
    reason = req_body.get("reason", "")
    if not isinstance(reason, str):
        reason = ""
    # Only pass actor when there's a reason to record
    actor = channel if reason else ""
    try:
        if action == "grant":
            if option == "approve_task":
                approval.approval_set_option(approval_token, option)
            approval.approval_grant(approval_token, channel=channel, actor=actor, reason=reason)
        else:
            approval.approval_deny(approval_token, channel=channel, actor=actor, reason=reason)
        # If this token gated a dispatch task, genuinely resume
        # (grant) or kill (deny) it — see core/dispatch.py's
        # resolve_waiting_approval. A no-op for any other approval.
        _, note = _actions.resolve_waiting_approval_detail(
            approval_token, decision, channel=channel, actor=actor, reason=reason
        )
        rec = approval.approval_get(approval_token)
        payload: dict[str, object] = {
            "ok": True,
            "token": approval_token,
            "state": rec["state"],
        }
        if note:
            payload["note"] = note
        resp_body = json.dumps(payload).encode()
        h._send(resp_body, "application/json")
    except approval.ApprovalNoop as exc:
        _actions.resolve_waiting_approval(approval_token, decision)
        h._send_json_error(exc.message, 409)
    except approval.ApprovalConflict as exc:
        # The opposite decision already resolved this token (grant-after-deny or
        # deny-after-grant) -- a real conflict over an existing token, not a missing
        # one, so 409 naming the winning state rather than 404.
        h._send_json_error(str(exc), 409)
    except approval.ApprovalError as exc:
        h._send_json_error(str(exc), 404)
