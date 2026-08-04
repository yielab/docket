"""Chat-completion port.

The typed boundary between docket's own turn loop and whatever speaks
inference. This module is the *port*; ``edges/adapters/llm.py`` is the one
shipped adapter (OpenAI-compatible ``/v1/chat/completions``).

**Why this exists.** docket owns the loop, the tool registry and every gate;
it rents only *protocols*. Inference is a protocol — an HTTP POST with a JSON
body — so it is rented. Nothing in this file knows what that JSON looks
like: the shapes below are docket's own vocabulary, and the adapter
translates in both directions. That is the same split
``core/runtime_driver.py`` (pure typing) / ``edges/adapters/`` (all format
knowledge) already uses, and it is what keeps a future second endpoint dialect
from leaking wire fields into ``core/``.

**Deliberately absent:** streaming, and any notion of "an agent". A
``ChatBackend`` performs exactly one request/response exchange. Multi-step
behaviour — feeding tool results back, deciding when a turn is over — belongs
to ``core/agent_loop.py``, because those are the decisions docket refuses to
delegate.
"""

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
    """A model emitted tool-call arguments that are not a JSON object.

    Raised by ``ToolCall.parsed_arguments`` rather than papering over the
    problem with an empty dict, because the arguments are exactly what
    ``pre_tool_call`` inspects: a command's *arguments* are what make it
    dangerous, not its name. A caller that cannot read them cannot gate them,
    so ``core/tools.py``'s ``dispatch_tool`` treats this as a denial (fail
    closed) instead of executing a tool call it could not evaluate.
    """


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation requested by the model.

    ``arguments`` is kept as the **raw string the model emitted**, not a parsed
    dict. Two reasons, both about honesty: the audit/trace record should show
    what was actually asked for (including malformed JSON), and parsing is a
    fallible step whose failure the gate must see rather than inherit as
    silently-empty arguments.
    """

    id: str
    name: str
    arguments: str = "{}"

    def parsed_arguments(self) -> dict[str, Any]:
        """Decode ``arguments`` as a JSON object.

        Raises ``ToolCallArgumentsError`` for anything that is not a JSON
        object — invalid JSON, or valid JSON of the wrong shape (a bare list,
        string or number). An empty/blank string decodes to ``{}``: some models
        emit that for a zero-argument tool, and it is unambiguous.
        """
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
    """A tool advertised to the model.

    ``parameters`` is a JSON Schema object. It is stored as a plain dict rather
    than a modelled type because it is passed through to the endpoint verbatim
    and docket never reasons about its internals — ``core/tools.py`` owns
    what a valid tool looks like on docket's side.
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    """One message in a conversation, in docket's vocabulary.

    ``tool_calls`` is only ever populated on an ``assistant`` message;
    ``tool_call_id``/``name`` only on a ``tool`` message. The dataclass does not
    enforce that — the adapter encodes whatever is set, and the loop is what
    constructs these — but the ``system``/``user``/``assistant``/``tool_result``
    helpers below build each variant correctly, so prefer them to a bare
    constructor.
    """

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
    """The result of executing *call*, addressed back to the model.

    Takes the ``ToolCall`` rather than a loose id/name pair so a result can
    never be attributed to the wrong call — an endpoint that receives a
    ``tool_call_id`` it did not issue rejects the whole request.
    """
    return ChatMessage(role="tool", content=content, tool_call_id=call.id, name=call.name)


@dataclass(frozen=True)
class TokenUsage:
    """Token counts **as reported by the endpoint** for one exchange.

    Unlike ``config.CONTEXT_BYTES_PER_TOKEN``-based estimates used elsewhere in
    docket (``core/context.py``'s budgets, ``maintain check``'s guards), these
    are real counts off the response body. Keep the distinction in any
    user-facing wording: everything docket measured before this port existed
    was an approximation, and this is not.

    ``cached_tokens`` is a subset of ``input_tokens`` where the endpoint
    reports one, and 0 where it does not — a zero here means "not reported",
    never "definitely no cache hit".
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ChatResponse:
    """Outcome of one exchange. Never an exception for ordinary failures.

    Mirrors ``TurnResult``'s contract deliberately: ``core/dispatch.py`` already
    has a retry policy keyed on ``FailureKind``, and reusing that vocabulary is
    what lets ``core/agent_loop.py``'s driver slot in underneath the existing
    state machine with no changes to it.

    ``failure_kind`` is ``None`` exactly when ``ok`` is True.
    """

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
        """True when the endpoint stopped for length, not because it was done.

        Worth checking explicitly: a length-truncated reply can carry a
        *partial* tool call, which is exactly the kind of malformed input the
        gate must not wave through.
        """
        return self.finish_reason == "length"


@dataclass(frozen=True)
class Endpoint:
    """Where to send an exchange, and as whom.

    ``api_key`` is empty for endpoints that do not authenticate (a local
    llama.cpp/vLLM server). It is deliberately *not* logged or included in any
    ``repr`` docket writes — see the adapter's error paths, which quote the URL
    but never the key.
    """

    base_url: str
    model_id: str
    api_key: str = ""
    provider: str = ""

    @property
    def is_local(self) -> bool:
        """True for a loopback endpoint (no credential is expected)."""
        return "127.0.0.1" in self.base_url or "localhost" in self.base_url


@runtime_checkable
class ChatBackend(Protocol):
    """The port ``core/agent_loop.py`` programs against.

    One method, one exchange. Implementations must not raise for transport,
    protocol or endpoint errors — those come back as ``ChatResponse(ok=False,
    failure_kind=...)`` so the caller's retry policy, not an exception handler,
    decides what happens next.
    """

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
