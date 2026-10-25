"""The tool step: dispatching one assistant message's batch of tool calls.

``ToolStep`` sends every call through ``dispatch_tool`` (the single chokepoint), persists the
assistant message and all its tool results as one atomic unit, and ends the turn on a
cancelled batch, an unanswerable or parked approval, the consecutive-denial ceiling, a
no-progress streak, or a successful call of an ``ends_turn`` tool.
"""

from __future__ import annotations

import hashlib
import json

from docket.agent.loop_state import TurnState
from docket.agent.loop_trace import _trace_tool_call, _trace_tool_result
from docket.agent.loop_types import AgentLoopResult
from docket.agent.ports import ChatMessage, TokenUsage, ToolCall, tool_result
from docket.agent.session import append_messages
from docket.agent.tools.registry import ToolResult, dispatch_tool
from docket.kernel.gate import ToolDenialKind


# Quoted key=value pairs, because TurnResult carries no structured field to hold these. A
# function rather than an inline string so a test can drive the real format.
def approval_unavailable_error(result: ToolResult) -> str:
    """Render a refused-approval denial as quoted key=value pairs."""
    return (
        f"approval_unavailable: tool={result.tool!r} call_id={result.call_id!r} "
        f"policy_id={result.policy_id!r} reason={result.reason!r}"
    )


def approval_parked_error(result: ToolResult) -> str:
    """Render a parked-approval stop in the same key=value shape
    ``approval_unavailable_error`` uses, so one function owns the format."""
    return (
        f"approval_parked: tool={result.tool!r} call_id={result.call_id!r} "
        f"policy_id={result.policy_id!r} reason={result.reason!r} "
        f"approval_token={result.approval_token!r}"
    )


class _ProgressDetector:
    """Counts consecutive tool rounds whose fingerprint was already seen this turn."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._seen: set[frozenset[tuple[str, str, bool, str]]] = set()
        self._repeats = 0
        self._names: list[str] = []

    @staticmethod
    def entry(call: ToolCall, ok: bool, output: str) -> tuple[str, str, bool, str]:
        try:
            args = json.dumps(json.loads(call.arguments), sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            args = str(call.arguments)
        return (call.name, args, ok, hashlib.sha256(output.encode("utf-8")).hexdigest())

    def observe(self, entries: list[tuple[str, str, bool, str]]) -> bool:
        """Record one round; True when the repeat count has reached the limit."""
        if self.limit <= 0 or not entries:
            return False
        fingerprint = frozenset(entries)
        if fingerprint in self._seen:
            self._repeats += 1
            self._names = sorted({e[0] for e in entries})
        else:
            self._seen.add(fingerprint)
            self._repeats = 0
        return self._repeats >= self.limit

    def error(self) -> str:
        return (
            f"no progress: {self._repeats} consecutive tool rounds repeated earlier "
            f"results; repeated tool(s)={','.join(self._names)}"
        )


class ToolStep:
    """Dispatches a tool batch and owns the denial and no-progress counters."""

    def __init__(self, state: TurnState) -> None:
        self.state = state
        self.consecutive_denial_kinds: list[ToolDenialKind] = []
        self.progress: _ProgressDetector | None = None

    # Persists the assistant message and every tool result as one atomic unit
    # through dispatch_tool. Returns None to keep looping.
    def dispatch_tool_batch(
        self,
        messages: list[ChatMessage],
        assistant_msg: ChatMessage,
        response_usage: TokenUsage,
    ) -> AgentLoopResult | None:
        """Gate the batch size, dispatch every call, then apply the denial ceiling."""
        if (
            self.state.tool_calls_executed + len(assistant_msg.tool_calls)
            > self.state.cfg.max_tool_calls
        ):
            return self.state.done(
                ok=False,
                stop_reason="max_tool_calls",
                error=(
                    f"model requested {len(assistant_msg.tool_calls)} tool call(s), which would "
                    f"exceed max_tool_calls={self.state.cfg.max_tool_calls} (already used "
                    f"{self.state.tool_calls_executed}); none of this batch was executed"
                ),
                failure_kind="invalid_output",
            )

        tool_msgs: list[ChatMessage] = []
        batch_cancelled = False
        approval_unavailable: ToolResult | None = None
        approval_parked: ToolResult | None = None
        round_entries: list[tuple[str, str, bool, str]] = []
        closing_output: str | None = None
        self.state.ctx.rationale = assistant_msg.content or ""
        for call in assistant_msg.tool_calls:
            _trace_tool_call(
                self.state.project,
                self.state.trace_key,
                self.state.ctx.role,
                call.name,
                call.id,
                call.arguments,
                task_id=self.state.trace_task_id,
            )
            result = dispatch_tool(call, self.state.ctx, self.state.registry)
            if result.denial_kind != "run_cancelled":
                self.state.tool_calls_executed += 1
            tool_output = result.as_tool_output()
            if result.ok and result.executed and self._ends_turn(call.name):
                closing_output = result.content
            _trace_tool_result(
                self.state.project,
                self.state.trace_key,
                self.state.ctx.role,
                call.name,
                call.id,
                result.decision,
                result.ok,
                result.executed,
                result.denial_kind,
                result.policy_id,
                result.reason,
                task_id=self.state.trace_task_id,
                output=tool_output,
            )
            if result.denial_kind is not None and not result.executed:
                self.consecutive_denial_kinds.append(result.denial_kind)
            elif result.decision == "allow" and result.executed:
                self.consecutive_denial_kinds.clear()
            tool_msgs.append(tool_result(call, tool_output))
            round_entries.append(_ProgressDetector.entry(call, result.ok, tool_output))
            if result.denial_kind == "run_cancelled" or self.state.cancellation_requested():
                batch_cancelled = True
            if result.denial_kind == "approval_unavailable" and approval_unavailable is None:
                approval_unavailable = result
            if result.denial_kind == "approval_parked" and approval_parked is None:
                approval_parked = result

        messages.append(assistant_msg)
        messages.extend(tool_msgs)
        # One append per iteration, the whole atomic unit at once — never the
        # assistant message and its tool results in separate calls, which
        # would let a crash between them persist an orphaned tool_calls entry.
        append_messages(self.state.session_key, [assistant_msg, *tool_msgs], usage=response_usage)
        if batch_cancelled:
            return self.state.cancelled()
        if approval_unavailable is not None:
            # Terminal on its own, unlike gate_denied/invalid_call: there is
            # nobody left to ask, so no further retry of this batch or another
            # can change the outcome. Named specifically so a caller does not
            # have to grep a generic denial-limit error for which rule fired.
            #
            # The error is written as quoted key=value pairs because TurnResult has no
            # structured field to carry these through.
            return self.state.done(
                ok=False,
                stop_reason="approval_unavailable",
                error=approval_unavailable_error(approval_unavailable),
                failure_kind="invalid_output",
            )
        if approval_parked is not None:
            # Terminal exactly like approval_unavailable above: nobody on
            # this thread can answer, whether or not somebody elsewhere
            # eventually does.
            return self.state.done(
                ok=False,
                stop_reason="approval_parked",
                error=approval_parked_error(approval_parked),
                failure_kind="invalid_output",
            )
        denial_limit = self.state.cfg.max_consecutive_tool_denials
        if denial_limit > 0 and len(self.consecutive_denial_kinds) >= denial_limit:
            reported_kinds = self.consecutive_denial_kinds[-denial_limit:]
            return self.state.done(
                ok=False,
                stop_reason="tool_denials",
                error=(
                    "consecutive tool denials reached configured limit: "
                    f"count={len(self.consecutive_denial_kinds)}; "
                    f"kinds={','.join(reported_kinds)}; no further model request was made"
                ),
                failure_kind="invalid_output",
            )
        if closing_output is not None:
            text = "\n".join(part for part in (assistant_msg.content, closing_output) if part)
            return self.state.done(ok=True, stop_reason="final_message", output=text)
        return self.stop_if_no_progress(round_entries)

    def _ends_turn(self, tool_name: str) -> bool:
        tool = self.state.registry.get(tool_name)
        return tool is not None and tool.ends_turn

    def stop_if_no_progress(
        self, round_entries: list[tuple[str, str, bool, str]]
    ) -> AgentLoopResult | None:
        """Stop once enough consecutive rounds repeat already-seen results."""
        if self.progress is None:
            self.progress = _ProgressDetector(self.state.cfg.no_progress_rounds)
        if not self.progress.observe(round_entries):
            return None
        return self.state.done(
            ok=False,
            stop_reason="no_progress",
            error=self.progress.error(),
            failure_kind="invalid_output",
        )
