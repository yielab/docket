"""Chat-completion port: the typed boundary between docket's turn loop and whatever speaks
inference. This module is the *port*; ``edges/adapters/llm.py`` is the shipped adapter
(OpenAI-compatible ``/v1/chat/completions``). Docket owns the loop, tool registry and every
gate; it rents only protocols, and inference is one (an HTTP POST with a JSON body) — nothing
here knows that JSON shape, the shapes below are docket's own vocabulary, and the adapter
translates in both directions, the same split ``core/runtime_driver.py`` (pure typing) /
``edges/adapters/`` (format knowledge) already uses, keeping a future second endpoint dialect
from leaking wire fields into ``core/``. Deliberately absent: streaming, and any notion of "an
agent" — a ``ChatBackend`` performs exactly one request/response exchange; multi-step behaviour
(feeding tool results back, deciding when a turn is over) belongs to ``core/agent_loop.py``,
because those are the decisions docket refuses to delegate."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from docket.core.runtime_driver import FailureKind

__all__ = [
    "ChatBackend",
    "ChatMessage",
    "ChatResponse",
    "Endpoint",
    "Role",
    "TokenUsage",
    "ToolCall",
    "ToolCallArgumentsError",
    "ToolSpec",
    "assistant",
    "system",
    "tool_result",
    "user",
]

Role = Literal["system", "user", "assistant", "tool"]


class ToolCallArgumentsError(ValueError):
    """A model emitted tool-call arguments that are not a JSON object. Raised by
    ``ToolCall.parsed_arguments`` since arguments are what ``pre_tool_call`` inspects;
    ``dispatch_tool`` fail-closes to denial rather than executing an unreadable call."""


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation requested by the model. ``arguments`` stays the raw string the model
    emitted, not a parsed dict: the audit/trace record shows what was truly asked for (even
    malformed JSON), and a parse failure is one the gate must see, not inherit as empty."""

    id: str
    name: str
    arguments: str = "{}"

    def parsed_arguments(self) -> dict[str, Any]:
        """Decode ``arguments`` as a JSON object. Raises ``ToolCallArgumentsError`` for anything
        that is not a JSON object (invalid JSON, or a bare list/string/number); an empty/blank
        string decodes to ``{}`` since some models emit that for a zero-argument tool."""
        raw = self.arguments.strip()
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as ex:
            raise ToolCallArgumentsError(
                f"tool call {self.name!r} sent unparseable arguments: {ex}"
            ) from ex
        if not isinstance(decoded, dict):
            raise ToolCallArgumentsError(
                f"tool call {self.name!r} sent {type(decoded).__name__} arguments, expected object"
            )
        return dict(decoded)


@dataclass(frozen=True)
class ToolSpec:
    """A tool advertised to the model. ``parameters`` (a JSON Schema object) is a plain dict,
    not a modelled type, because it passes through to the endpoint verbatim and docket never
    reasons about its internals; ``core/tools.py`` owns what a valid tool looks like."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    """One message in a conversation. ``tool_calls`` populates only on an ``assistant`` message;
    ``tool_call_id``/``name`` only on a ``tool`` message — unenforced by the dataclass, so prefer
    the ``system``/``user``/``assistant``/``tool_result`` helpers below to a bare constructor."""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""


def system(content: str) -> ChatMessage:
    """A system/instruction message."""
    return ChatMessage(role="system", content=content)


def user(content: str) -> ChatMessage:
    """A user-turn message."""
    return ChatMessage(role="user", content=content)


def assistant(content: str = "", tool_calls: Sequence[ToolCall] = ()) -> ChatMessage:
    """An assistant message, optionally requesting tool calls."""
    return ChatMessage(role="assistant", content=content, tool_calls=list(tool_calls))


def tool_result(call: ToolCall, content: str) -> ChatMessage:
    """The result of executing *call*, addressed back to the model. Takes the ``ToolCall``
    rather than a loose id/name pair so a result can never be attributed to the wrong call:
    an endpoint that receives a ``tool_call_id`` it did not issue rejects the whole request."""
    return ChatMessage(role="tool", content=content, tool_call_id=call.id, name=call.name)


@dataclass(frozen=True)
class TokenUsage:
    """Token counts **as reported by the endpoint** for one exchange — real counts off the
    response body, unlike the ``config.CONTEXT_BYTES_PER_TOKEN`` estimates used elsewhere
    (``core/context.py``'s budgets, ``maintain check``'s guards). Keep this distinction in any
    user-facing wording: never call an estimate a measurement. ``cached_tokens`` is a subset of
    ``input_tokens`` where the endpoint reports one, and 0 where it does not — meaning "not
    reported", never "definitely no cache hit"."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ChatResponse:
    """Outcome of one exchange, never an exception for ordinary failures. Mirrors ``TurnResult``'s
    contract deliberately (reusing ``FailureKind`` so ``core/agent_loop.py``'s driver slots under
    ``core/dispatch.py``'s retry policy); ``failure_kind`` is ``None`` iff ``ok`` is True."""

    ok: bool
    message: ChatMessage = field(default_factory=lambda: ChatMessage(role="assistant"))
    finish_reason: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    failure_kind: FailureKind | None = None

    @property
    def tool_calls(self) -> list[ToolCall]:
        """Tool calls the model requested, if any (convenience for the loop)."""
        return self.message.tool_calls

    @property
    def truncated(self) -> bool:
        """True when the endpoint stopped for length, not because it was done; worth checking
        explicitly since a length-truncated reply can carry a *partial* tool call, exactly the
        malformed input the gate must not wave through."""
        return self.finish_reason == "length"


@dataclass(frozen=True)
class Endpoint:
    """Where to send an exchange, and as whom. ``api_key`` is empty for endpoints that do not
    authenticate (a local llama.cpp/vLLM server), and is deliberately never logged or included
    in any ``repr`` docket writes — the adapter's error paths quote the URL but never the key."""

    base_url: str
    model_id: str
    api_key: str = ""
    provider: str = ""
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None

    @property
    def is_local(self) -> bool:
        """True for a loopback endpoint (no credential is expected)."""
        return "127.0.0.1" in self.base_url or "localhost" in self.base_url


@runtime_checkable
class ChatBackend(Protocol):
    """The port ``core/agent_loop.py`` programs against: one method, one exchange. Implementations
    must not raise for transport, protocol, or endpoint errors, returning ``ChatResponse(ok=False,
    failure_kind=...)`` instead so the caller's retry policy decides what happens next."""

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        """Send *messages* (plus any advertised *tools*) and return the reply."""
        ...
