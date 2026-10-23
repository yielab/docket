from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from docket.agent import context as _context
from docket.agent.llm import ChatBackend, ChatMessage, TokenUsage, ToolSpec, system


def _accumulate(current: TokenUsage, delta: TokenUsage) -> TokenUsage:
    """Fold one exchange's real ``TokenUsage`` into the turn's running total.

    Mirrors ``agent.session._add_usage``'s shape exactly (a separate function,
    not an import of that private helper, since the two accumulate into
    different record types — a session's lifetime total vs. one turn's).
    """
    return TokenUsage(
        input_tokens=current.input_tokens + delta.input_tokens,
        output_tokens=current.output_tokens + delta.output_tokens,
        cached_tokens=current.cached_tokens + delta.cached_tokens,
        cache_write_tokens=current.cache_write_tokens + delta.cache_write_tokens,
    )


def _usage_delta(current: TokenUsage, previous: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=current.input_tokens - previous.input_tokens,
        output_tokens=current.output_tokens - previous.output_tokens,
        cached_tokens=current.cached_tokens - previous.cached_tokens,
        cache_write_tokens=current.cache_write_tokens - previous.cache_write_tokens,
    )


def _fallback_input_estimate(
    messages: list[ChatMessage],
    tools: list[ToolSpec],
    max_tokens: int | None,
    temperature: float | None,
) -> int:
    """Estimate all model-visible components for a non-wire-aware backend."""
    payload = {
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "tool_calls": [
                    {"id": call.id, "name": call.name, "arguments": call.arguments}
                    for call in message.tool_calls
                ],
                "tool_call_id": message.tool_call_id,
                "name": message.name,
            }
            for message in messages
        ],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in tools
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    return max(1, _context.estimate_tokens(json.dumps(payload, ensure_ascii=False))) + 16


def _estimate_input_tokens(
    backend: ChatBackend,
    messages: list[ChatMessage],
    tools: list[ToolSpec],
    max_tokens: int | None,
    temperature: float | None,
) -> int:
    estimator = getattr(backend, "estimate_input_tokens", None)
    if callable(estimator):
        estimated = estimator(
            messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return max(1, int(estimated))
    return _fallback_input_estimate(messages, tools, max_tokens, temperature)


def _selected_estimate(selected: list[ChatMessage]) -> int:
    return max(1, _fallback_input_estimate(selected, [], None, None) - 16)


def _segment_revision(selected: list[ChatMessage]) -> str:
    encoded = json.dumps(
        [asdict(message) for message in selected],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _build_reduction_candidates(
    durable: list[ChatMessage],
    task_index: int,
    protected_segments: dict[str, tuple[int, str]],
) -> list[tuple[str, tuple[int, int], bool, int]]:
    """Suffix-then-prefix compaction candidates; mutates ``protected_segments`` for a
    stale checkpoint that no longer matches durable history."""
    candidate_ranges: list[tuple[str, tuple[int, int], bool, int]] = []
    if task_index + 1 < len(durable):
        suffix_start = task_index + 1
        prior_protected_count = 0
        checkpoint = protected_segments.get("suffix")
        if checkpoint is not None:
            protected_count, protected_revision = checkpoint
            suffix = durable[suffix_start:]
            protected = suffix[:protected_count]
            if (
                len(protected) == protected_count
                and _segment_revision(protected) == protected_revision
            ):
                suffix_start += protected_count
                prior_protected_count = protected_count
            else:
                protected_segments.pop("suffix", None)
        if suffix_start < len(durable):
            candidate_ranges.append(
                ("suffix", (suffix_start, len(durable)), False, prior_protected_count)
            )
    if task_index > 0:
        prefix = durable[:task_index]
        checkpoint = protected_segments.get("prefix")
        if checkpoint is None or checkpoint != (len(prefix), _segment_revision(prefix)):
            candidate_ranges.append(("prefix", (0, task_index), True, 0))
    return candidate_ranges


_FINALIZATION_INSTRUCTION = (
    "The remaining cumulative turn budget cannot safely fund another tool-enabled round. "
    "Return the truthful terminal response now using only the work already completed and the "
    "tool results above. Do not request any tools. If the task is incomplete, say so explicitly."
)


def _finalization_messages(current: list[ChatMessage]) -> list[ChatMessage]:
    # Keep the instruction in the leading system slot for adapters/models
    # that require system messages before conversation history. This copy
    # is request-only and is never written to durable history.
    if current and current[0].role == "system":
        terminal_system = system(f"{current[0].content}\n\n{_FINALIZATION_INSTRUCTION}")
        return [terminal_system, *current[1:]]
    return [system(_FINALIZATION_INSTRUCTION), *current]
