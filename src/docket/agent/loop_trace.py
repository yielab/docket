from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Sequence
from typing import Any

from docket.agent.llm import ChatMessage, ChatResponse
from docket.agent.ports import PromptSectionReport
from docket.agent.session_compaction import CompactionResult
from docket.agent.tools.registry import ToolDenialKind
from docket.kernel import text as _text
from docket.kernel.home import current_home
from docket.observability import telemetry as _telemetry
from docket.observability.trace import trace_event

# On-disk bound for one captured text/argument/response part (ADR 0015 §2 rule 5). The
# per-exporter cut applied at projection time is a separate, narrower bound.
_CONTENT_MAX_CHARS_ON_DISK = 4000

# The last system-instructions SHA-256 recorded per trace key, so `_capture_llm_call_content`
# writes the text again only when it changes (ADR 0015 §2 rule 5).
_INSTRUCTIONS_HASH_LOCK = threading.Lock()
_LAST_INSTRUCTIONS_HASH: dict[str, str] = {}


def _messages_to_otel(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """*messages* in the OTel GenAI ``{"role", "parts"}`` shape (ADR 0015 §1): a ``tool``
    turn becomes one ``tool_call_response`` part, an assistant's requested tool calls become
    ``tool_call`` parts, and text becomes a ``text`` part."""
    out: list[dict[str, Any]] = []
    for message in messages:
        parts: list[dict[str, Any]] = []
        if message.role == "tool":
            parts.append(
                {
                    "type": "tool_call_response",
                    "id": message.tool_call_id,
                    "response": _text.cut_chars(message.content, _CONTENT_MAX_CHARS_ON_DISK),
                }
            )
        else:
            if message.content:
                parts.append(
                    {
                        "type": "text",
                        "content": _text.cut_chars(message.content, _CONTENT_MAX_CHARS_ON_DISK),
                    }
                )
            for call in message.tool_calls:
                parts.append(
                    {
                        "type": "tool_call",
                        "id": call.id,
                        "name": call.name,
                        "arguments": _text.cut_chars(call.arguments, _CONTENT_MAX_CHARS_ON_DISK),
                    }
                )
        out.append({"role": message.role, "parts": parts})
    return out


def _capture_llm_call_content(
    payload: dict[str, Any],
    trace_key: str,
    messages: Sequence[ChatMessage],
    response: ChatResponse,
) -> None:
    """Add ``inputMessages``/``outputMessages``/``systemInstructions`` to *payload* for the
    classes an enabled exporter was granted (ADR 0015 §2 rule 4); a no-op when nothing is
    granted, so the payload stays exactly what it was before this capture existed."""
    granted = _telemetry.capture_classes()
    if not granted:
        return
    if "prompts" in granted:
        payload["inputMessages"] = _messages_to_otel([m for m in messages if m.role != "system"])
    if "completions" in granted:
        payload["outputMessages"] = _messages_to_otel([response.message])
    if "instructions" not in granted:
        return
    system_text = next((m.content for m in messages if m.role == "system"), None)
    if system_text is None:
        return
    digest = hashlib.sha256(system_text.encode()).hexdigest()
    with _INSTRUCTIONS_HASH_LOCK:
        if _LAST_INSTRUCTIONS_HASH.get(trace_key) != digest:
            payload["systemInstructions"] = _text.cut_chars(system_text, _CONTENT_MAX_CHARS_ON_DISK)
            _LAST_INSTRUCTIONS_HASH[trace_key] = digest
    payload["systemInstructionsSha256"] = digest


def _trace_llm_call(
    project: str,
    session_key: str,
    role: str,
    response: ChatResponse,
    iteration: int | None = None,
    *,
    purpose: str = "",
    task_id: str = "",
    messages: Sequence[ChatMessage] | None = None,
) -> None:
    """One backend chat-completions exchange, measured -- never a cost figure. ``request`` is the
    adapter's own byte count of the body it sent; the content of *messages* is captured only for
    classes an enabled exporter asked for."""
    payload: dict[str, Any] = {
        "model": response.model,
        "provider": response.provider,
        "ok": response.ok,
        "finishReason": response.finish_reason,
        "failureKind": response.failure_kind,
        "inputTokens": response.usage.input_tokens,
        "outputTokens": response.usage.output_tokens,
        "cachedTokens": response.usage.cached_tokens,
    }
    if response.usage.cache_write_tokens > 0:
        payload["cacheWriteTokens"] = response.usage.cache_write_tokens
    if iteration is not None:
        payload["iteration"] = iteration
    if purpose:
        payload["purpose"] = purpose
    if response.request_bytes:
        payload["request"] = {
            part: {"bytes": size, "estTokens": size // current_home().context_bytes_per_token}
            for part, size in response.request_bytes.items()
        }
    if messages is not None:
        _capture_llm_call_content(payload, session_key, messages, response)
    trace_event(
        project,
        session_key,
        role,
        "llm_call",
        json.dumps(payload),
        duration_ms=response.latency_ms,
        task_id=task_id,
    )


def _trace_request_fit(
    project: str,
    session_key: str,
    role: str,
    *,
    purpose: str,
    status: str,
    estimated_input_tokens: int,
    output_reserve_tokens: int,
    context_window_tokens: int | None,
    task_id: str = "",
) -> None:
    trace_event(
        project,
        session_key,
        role,
        "request_fit",
        json.dumps(
            {
                "purpose": purpose,
                "status": status,
                "estimatedInputTokens": estimated_input_tokens,
                "outputReserveTokens": output_reserve_tokens,
                "contextWindowTokens": context_window_tokens,
                "estimate": True,
            }
        ),
        task_id=task_id,
    )


def _trace_tool_call(
    project: str,
    session_key: str,
    role: str,
    tool: str,
    call_id: str,
    arguments: str,
    task_id: str = "",
) -> None:
    trace_event(
        project,
        session_key,
        role,
        "tool_call",
        json.dumps({"tool": tool, "callId": call_id, "arguments": arguments}),
        task_id=task_id,
    )


def _trace_tool_result(
    project: str,
    session_key: str,
    role: str,
    tool: str,
    call_id: str,
    decision: str,
    ok: bool,
    executed: bool,
    denial_kind: ToolDenialKind | None,
    policy_id: str = "",
    reason: str = "",
    task_id: str = "",
    output: str | None = None,
) -> None:
    """One tool outcome; *output*, the text fed back to the model, is recorded as ``text``
    only when an enabled exporter grants ``toolResults``."""
    payload: dict[str, Any] = {
        "tool": tool,
        "callId": call_id,
        "decision": decision,
        "ok": ok,
        "executed": executed,
    }
    if denial_kind is not None:
        payload["denialKind"] = denial_kind
    if policy_id:
        payload["policyId"] = policy_id
    if reason:
        payload["reason"] = reason
    if output is not None and "toolResults" in _telemetry.capture_classes():
        payload["text"] = _text.cut_chars(output, _CONTENT_MAX_CHARS_ON_DISK)
    trace_event(
        project,
        session_key,
        role,
        "tool_result",
        json.dumps(payload),
        task_id=task_id,
    )


def _trace_compaction(
    project: str,
    session_key: str,
    role: str,
    result: CompactionResult,
    task_id: str = "",
) -> None:
    status = "failed" if not result.ok else "succeeded" if result.compacted else "no_op"
    trace_event(
        project,
        session_key,
        role,
        "session_compaction",
        json.dumps(
            {
                "status": status,
                "beforeMessageCount": result.before_message_count,
                "afterMessageCount": result.after_message_count,
                "beforeEstimatedTokens": result.before_estimated_tokens,
                "afterEstimatedTokens": result.after_estimated_tokens,
                "groupsSummarized": result.groups_summarized,
                "summaryRounds": result.summary_rounds,
                "maxSummaryPromptEstimatedTokens": (result.max_summary_prompt_estimated_tokens),
            }
        ),
        task_id=task_id,
    )


def _trace_terminal_finalization(
    project: str,
    session_key: str,
    role: str,
    *,
    status: str,
    reason: str,
    token_budget: int,
    measured_tokens_used: int,
    normal_estimated_input_tokens: int,
    finalization_estimated_input_tokens: int,
    output_reserve_tokens: int,
    task_id: str = "",
) -> None:
    remaining = max(0, token_budget - measured_tokens_used)
    trace_event(
        project,
        session_key,
        role,
        "budget_warning",
        json.dumps(
            {
                "action": "terminal_finalization",
                "status": status,
                "reason": reason,
                "tokenBudget": token_budget,
                "measuredTokensUsed": measured_tokens_used,
                "remainingMeasuredTokens": remaining,
                "normalEstimatedInputTokens": normal_estimated_input_tokens,
                "finalizationEstimatedInputTokens": finalization_estimated_input_tokens,
                "outputReserveTokens": output_reserve_tokens,
                "normalProspectiveTokens": normal_estimated_input_tokens + output_reserve_tokens,
                "finalizationProspectiveTokens": finalization_estimated_input_tokens
                + output_reserve_tokens,
                "estimate": True,
            }
        ),
        task_id=task_id,
    )


def _trace_prompt_composed(
    project: str,
    session_key: str,
    role: str,
    sections: tuple[PromptSectionReport, ...],
    budget_tokens: int,
    budget_source: str,
    task_id: str = "",
) -> None:
    trace_event(
        project,
        session_key,
        role,
        "prompt_composed",
        json.dumps(
            {
                "sections": [
                    {"name": s.name, "bytes": s.bytes, "status": s.status} for s in sections
                ],
                "budgetTokens": budget_tokens,
                "budgetSource": budget_source,
            }
        ),
        task_id=task_id,
    )
