from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict

from docket.agent import ports as _ports
from docket.agent.loop_state import TurnState
from docket.agent.loop_trace import _trace_request_retry
from docket.agent.ports import (
    BudgetStop,
    ChatBackend,
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolSpec,
    assistant,
    user,
)
from docket.kernel.home import current_home

# Only these failure kinds are a transient hiccup worth sending the same request again; a response
# that arrived (invalid_output, a refusal) is an answer (agent-loop.spec.md requirement 110).
_RETRYABLE_REQUEST_KINDS = frozenset({"timeout", "daemon_error"})


def _retry_wait(attempt: int, response: ChatResponse) -> float:
    """The sleep before retry *attempt*: linear backoff or the endpoint's ``Retry-After``, whichever
    asks for longer, never past ``DISPATCH_RETRY_MAX_WAIT_S``."""
    home = current_home()
    return min(
        max(home.dispatch_retry_backoff_s * attempt, response.retry_after_s or 0.0),
        home.dispatch_retry_max_wait_s,
    )


def send_request(
    state: TurnState,
    complete: Callable[[int], ChatResponse],
    timeout: int,
    *,
    next_timeout: Callable[[], int],
    clock_cut: Callable[[int], bool],
) -> tuple[ChatResponse, int]:
    """Send a request, retrying a transient failure (agent-loop.spec.md requirements 109-111).
    *timeout* is the first request's, *next_timeout* the retry's. Returns the last response and
    the timeout it was sent with."""
    cfg = state.cfg
    retries = 0
    while True:
        response = complete(timeout)
        kind = response.failure_kind or "daemon_error"
        if (
            response.ok
            or kind not in _RETRYABLE_REQUEST_KINDS
            or retries >= cfg.request_retries
            or state.cancellation_requested()
            or (kind == "timeout" and clock_cut(timeout))
        ):
            return response, timeout
        wait = _retry_wait(retries + 1, response)
        if wait >= cfg.wall_clock_timeout_s - (state.clock() - state.started):
            return response, timeout
        retries += 1
        state.request_retries += 1
        _trace_request_retry(
            state.project,
            state.trace_key,
            state.ctx.role,
            attempt=retries,
            retries=cfg.request_retries,
            response=response,
            task_id=state.trace_task_id,
        )
        state.sleep(wait)
        timeout = next_timeout()


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


# What a request costs beyond its messages and tools in the fallback estimate: the envelope.
_REQUEST_ENVELOPE_TOKENS = 16


def _message_tokens(messages: list[ChatMessage]) -> int:
    """*messages* alone, counted as the fallback request estimate counts them: the size a unit
    takes in the request, comparable with an overflow measured on the same estimate."""
    return _fallback_input_estimate(messages, [], None, None) - _REQUEST_ENVELOPE_TOKENS


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
    return (
        max(1, _ports.estimate_tokens(json.dumps(payload, ensure_ascii=False)))
        + _REQUEST_ENVELOPE_TOKENS
    )


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
) -> list[tuple[str, tuple[int, int], int]]:
    """Suffix-then-prefix compaction candidates; mutates ``protected_segments`` for a
    stale checkpoint that no longer matches durable history."""
    candidate_ranges: list[tuple[str, tuple[int, int], int]] = []
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
            candidate_ranges.append(("suffix", (suffix_start, len(durable)), prior_protected_count))
    if task_index > 0:
        prefix = durable[:task_index]
        checkpoint = protected_segments.get("prefix")
        if checkpoint is None or checkpoint != (len(prefix), _segment_revision(prefix)):
            candidate_ranges.append(("prefix", (0, task_index), 0))
    return candidate_ranges


_LANDING_ASK = (
    " Return the truthful terminal response now: what is done, what is left and whether the "
    "checks ran, using only the work already completed and the tool results above. Do not "
    "request any tools. If the task is incomplete, say so explicitly."
)
_FINALIZATION_INSTRUCTION = (
    "The remaining cumulative token budget cannot safely fund another tool-enabled round."
    + _LANDING_ASK
)
_LANDING_UNITS = {"rounds": "rounds", "toolCalls": "tool calls", "time": "seconds of time"}


def _finalization_instruction(stop: BudgetStop) -> str:
    """The landing's ask, naming the bound the turn reached (agent-loop.spec.md requirement 51)."""
    if stop.bound == "tokens":
        return _FINALIZATION_INSTRUCTION
    unit = _LANDING_UNITS[stop.bound]
    return f"This step has used all of its {unit} ({stop.limit})." + _LANDING_ASK


def _finalization_messages(current: list[ChatMessage], stop: BudgetStop) -> list[ChatMessage]:
    # A trailing user message keeps every earlier message byte-identical to the previous
    # request, so the cached prefix is reused. Request-only; never written to durable history.
    return [*current, user(_finalization_instruction(stop))]


def _notice_messages(current: list[ChatMessage], notice: str) -> list[ChatMessage]:
    # Request-only, like the landing's ask: the budget notice trails the persisted history and
    # is never stored, so the history a later turn loads does not carry it (requirement 108).
    return [*current, user(notice)]


def _closing_messages(current: list[ChatMessage], reply: str, tool: str) -> list[ChatMessage]:
    # Request-only, like the finalization instruction: the reply and the instruction trail the
    # persisted history, so the closing call's own message is the one that is stored.
    instruction = user(f"Record your outcome now by calling `{tool}`.")
    return [*current, *([assistant(reply)] if reply else []), instruction]
