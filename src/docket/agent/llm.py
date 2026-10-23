"""Chat-completion port: the typed boundary between docket's turn loop and whatever speaks
inference. This module is the *port*; ``models/adapters/openai_http.py`` is the shipped adapter
(OpenAI-compatible ``/v1/chat/completions``). Docket owns the loop, tool registry and every
gate; it rents only protocols, and inference is one (an HTTP POST with a JSON body) — nothing
here knows that JSON shape, the shapes below are docket's own vocabulary, and the adapter
translates in both directions, the same split ``agent/ports.py`` (pure typing) /
``models/adapters/`` (format knowledge) already uses, keeping a future second endpoint dialect
from leaking wire fields into the agent loop. Deliberately absent: streaming, and any notion of "an
agent" — a ``ChatBackend`` performs exactly one request/response exchange; multi-step behaviour
(feeding tool results back, deciding when a turn is over) belongs to ``agent/loop.py``,
because those are the decisions docket refuses to delegate."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from docket.agent.ports import FailureKind
from docket.kernel.errors import InvalidInput

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


class ToolCallArgumentsError(InvalidInput):
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
    reasons about its internals; ``agent/tools/registry.py`` owns what a valid tool looks like."""

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
    response body, unlike the ``Home.context_bytes_per_token`` estimates used elsewhere
    (``agent/context.py``'s budgets). Keep this distinction in any
    user-facing wording: never call an estimate a measurement. ``cached_tokens`` is a subset of
    ``input_tokens`` where the endpoint reports one, and 0 where it does not — meaning "not
    reported", never "definitely no cache hit"; ``cache_write_tokens`` is a subset too."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Input plus output, for display and truthiness only; budgets use ``counted_tokens``."""
        return self.input_tokens + self.output_tokens

    @property
    def counted_tokens(self) -> int:
        """New tokens: input minus cache reads, plus output. What every budget compares."""
        return max(0, self.input_tokens - self.cached_tokens) + self.output_tokens


@dataclass
class ChatResponse:
    """Outcome of one exchange, never an exception for ordinary failures. Mirrors ``TurnResult``'s
    contract deliberately (reusing ``FailureKind`` so ``agent/loop.py``'s driver slots under
    ``hops/application/runner.py``'s retry policy); ``failure_kind`` is ``None`` iff ``ok`` is True."""

    ok: bool
    message: ChatMessage = field(default_factory=lambda: ChatMessage(role="assistant"))
    finish_reason: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    failure_kind: FailureKind | None = None
    retry_after_s: float | None = None
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    #: Bytes of each request part as the adapter encoded them (system, tools, toolResults,
    #: assistant, user); empty when the backend does not measure its request.
    request_bytes: dict[str, int] = field(default_factory=dict)

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
class ModelLimits:
    """One model's context window and output cap as a provider published them; ``None`` is
    unknown, never zero."""

    context_window: int | None = None
    max_output: int | None = None


@dataclass(frozen=True)
class Endpoint:
    """Where to send an exchange, and as whom. ``api_key`` is never logged. ``auth_type``/
    ``auth_header`` say how it rides the wire (bearer, a named header, or none); ``headers``
    are additional static headers sent verbatim, as a tuple of pairs to stay hashable."""

    base_url: str
    model_id: str
    api_key: str = ""
    provider: str = ""
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    auth_type: Literal["bearer", "header", "none"] = "bearer"
    auth_header: str = ""
    headers: tuple[tuple[str, str], ...] = ()


@runtime_checkable
class ChatBackend(Protocol):
    """The port ``agent/loop.py`` programs against: one method, one exchange. Implementations
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
