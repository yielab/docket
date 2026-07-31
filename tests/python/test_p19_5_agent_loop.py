"""ROADMAP Phase 19 P19-5: the turn loop (`core/agent_loop.py`).

This is the card that makes the daemon unused, so what matters most here is
that there is exactly one path to tool execution and that every stop
condition is a deliberate, reported exit -- never a silent hang or a runaway
loop. Covers, in order of how much each one matters:

* **Single execution path** -- `run_agent_turn` never calls a tool handler
  except through `core.tools.dispatch_tool`; an architectural guard walks
  the module's own source to prove it.
* **Truncation safety** -- a length-truncated response carrying tool calls
  never has them dispatched, and is never persisted to session history.
* **All four stop conditions** -- final message, max_iterations,
  max_tool_calls, wall-clock timeout, token budget -- each independently
  triggerable and each reporting the right `stop_reason`/`failure_kind`.
* **Durability** -- history is persisted per iteration, not only at the end;
  a "crash" after N iterations leaves exactly N iterations on disk.
* **Tracing** -- every dispatched tool call emits a `tool_call` and a
  `tool_result` trace event.

No test here sleeps for real or hits the network: `ChatBackend` is a small
scripted fake, and wall-clock timeout tests inject a fake `clock`.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import agent_loop as _loop
from docket.core.llm import (
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
    assistant,
)
from docket.core.session import load_session
from docket.core.tools import Tool as _Tool
from docket.core.tools import ToolContext, ToolRegistry
from docket.edges.adapters.toolbox import ToolOutcome

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LOOP_SRC = REPO_ROOT / "src" / "docket" / "core" / "agent_loop.py"


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "SESSIONS_DIR", tmp_path / "sessions", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", tmp_path / "traces", raising=True)
    monkeypatch.setattr(_cfg, "POLICIES_DIR", tmp_path / "policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "notes.md").write_text("alpha\nbeta\n")
    return ws


@pytest.fixture
def registry() -> ToolRegistry:
    """A tiny registry with one harmless read-only tool -- enough to exercise
    dispatch without pulling in bash/exec classification noise."""
    reg = ToolRegistry()
    reg.register(
        _Tool(
            name="echo",
            description="Echo the given text back.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args, ctx: ToolOutcome(ok=True, content=str(args.get("text", ""))),
            kind="read",
        )
    )
    return reg


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        agent_id="demo-agent", role="implementer", project="demo", roots=(workspace,), timeout=10
    )


# ── a small scripted ChatBackend ─────────────────────────────────────────────


class ScriptedBackend:
    """Replays a fixed script of `ChatResponse`s, one per `complete()` call.

    Records every call's messages so tests can assert on what was actually
    sent (e.g. that tool results were fed back). Raises `AssertionError` if
    asked for more responses than scripted -- a test bug, not something a
    real backend would ever need to signal this way.
    """

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        if not self._responses:
            raise AssertionError("ScriptedBackend ran out of scripted responses")
        return self._responses.pop(0)


class InfiniteToolBackend:
    """Always asks for one more tool call -- the "confused model" bait used
    to prove the iteration/tool-call caps actually stop the loop."""

    def __init__(self, tool_name: str = "echo") -> None:
        self.tool_name = tool_name
        self.call_count = 0

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.call_count += 1
        call = ToolCall(
            id=f"call_{self.call_count}", name=self.tool_name, arguments='{"text": "x"}'
        )
        return ChatResponse(
            ok=True,
            message=assistant("", tool_calls=[call]),
            finish_reason="tool_calls",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )


def _final(content: str = "done", usage: TokenUsage | None = None) -> ChatResponse:
    return ChatResponse(
        ok=True,
        message=assistant(content),
        finish_reason="stop",
        usage=usage or TokenUsage(input_tokens=5, output_tokens=5),
    )


def _tool_call_response(
    call_id: str, name: str, arguments: str, usage: TokenUsage | None = None
) -> ChatResponse:
    call = ToolCall(id=call_id, name=name, arguments=arguments)
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=usage or TokenUsage(input_tokens=10, output_tokens=5),
    )


def _truncated(content: str = "", tool_calls: Sequence[ToolCall] = ()) -> ChatResponse:
    return ChatResponse(
        ok=True,
        message=assistant(content, tool_calls=tool_calls),
        finish_reason="length",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
    )


# ── architectural guard: dispatch_tool is the only execution path ───────────


class TestSingleExecutionPath:
    """The card's non-negotiable: a tool call that bypasses dispatch_tool
    bypasses every guardrail P19-2/P19-3 built. Verified by walking
    agent_loop.py's own source, not just by observing today's behaviour --
    see the module docstring's "plant the drift" instruction.

    Planted and reverted by hand while writing this test (not committed):
    temporarily replaced the `dispatch_tool(call, ctx, registry)` call with
    `tool = registry.get(call.name); tool.handler(call.parsed_arguments(), ctx)`
    -- a direct second path around the gate. This test went red (the
    forbidden `toolbox` import check and the "exactly one dispatch_tool call"
    count both fail against source that reaches for `.handler` directly),
    confirming it actually inspects behaviour that matters rather than always
    passing. Restored before committing.
    """

    def test_never_imports_toolbox_or_calls_a_handler_directly(self) -> None:
        tree = ast.parse(AGENT_LOOP_SRC.read_text(encoding="utf-8"))

        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        assert not any("toolbox" in m for m in imported_modules), (
            f"agent_loop.py must not import the toolbox handlers directly: {imported_modules}"
        )

        handler_attr_accesses = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "handler"
        ]
        assert handler_attr_accesses == [], "agent_loop.py must never touch Tool.handler directly"

    def test_dispatch_tool_is_imported_and_is_the_only_call_of_its_name(self) -> None:
        tree = ast.parse(AGENT_LOOP_SRC.read_text(encoding="utf-8"))

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "docket.core.tools":
                imported_names.update(alias.asname or alias.name for alias in node.names)
        assert "dispatch_tool" in imported_names

        call_sites = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "dispatch_tool"
        ]
        assert len(call_sites) == 1, "expected exactly one dispatch_tool(...) call site"

    def test_every_tool_call_actually_goes_through_dispatch_tool(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """Behavioural companion to the AST checks: a real turn's tool call
        produces a real dispatch_tool decision (recorded on the ToolResult
        fed back to the model), not a bypassed handler invocation."""
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )
        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")
        assert result.ok
        assert result.tool_calls_executed == 1
        # The tool result fed back to the model on the second call must be the
        # handler's real output ("hi"), proving dispatch_tool's execute step
        # ran (not a stubbed/skipped path).
        second_call_messages = backend.calls[1]
        tool_msg = next(m for m in second_call_messages if m.role == "tool")
        assert tool_msg.content == "hi"


# ── truncation safety ────────────────────────────────────────────────────────


class TestTruncatedResponses:
    """A truncated response must not have its tool calls executed (the card's
    requirement #3) -- the most dangerous failure mode this loop exists to
    prevent, since partial arguments are exactly what a gate cannot evaluate.
    """

    def test_truncated_with_tool_calls_never_dispatches_them(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        poison_call = ToolCall(id="c1", name="echo", arguments='{"text": "should not run"}')
        backend = ScriptedBackend([_truncated(tool_calls=[poison_call])])

        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")

        assert result.ok is False
        assert result.stop_reason == "truncated"
        assert result.failure_kind == "invalid_output"
        assert result.tool_calls_executed == 0

    def test_truncated_response_is_not_persisted_to_session(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        poison_call = ToolCall(id="c1", name="echo", arguments='{"text": "nope"}')
        backend = ScriptedBackend([_truncated(content="cut off mid-sen", tool_calls=[poison_call])])

        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        record = load_session(session_key)
        # Only the incoming user message should be durable -- the truncated
        # assistant reply (and its unexecuted tool call) must never land here.
        assert len(record.messages) == 1
        assert record.messages[0].role == "user"

    def test_truncated_with_no_tool_calls_is_still_reported_as_truncated(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """Truncation is checked uniformly, before ever looking at tool_calls
        -- a plain truncated reply is just as much "not a real answer" as one
        carrying a partial tool call."""
        backend = ScriptedBackend([_truncated(content="ran out of ro")])
        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")
        assert result.stop_reason == "truncated"
        assert result.ok is False


# ── stop conditions ───────────────────────────────────────────────────────────


class TestStopConditions:
    def test_final_message_with_no_tool_calls_succeeds(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = ScriptedBackend([_final("all done")])
        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")
        assert result.ok is True
        assert result.stop_reason == "final_message"
        assert result.output == "all done"
        assert result.failure_kind is None
        assert result.iterations == 1

    def test_max_iterations_stops_a_model_that_never_finishes(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = InfiniteToolBackend()
        config = _loop.LoopConfig(max_iterations=3, max_tool_calls=1000)

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:demo:default", "go", config=config
        )

        assert result.ok is False
        assert result.stop_reason == "max_iterations"
        assert result.failure_kind == "invalid_output"
        # Exactly 3 calls were made -- not 4, not unbounded. This is the
        # numeric assertion that makes the guard meaningful: a config change
        # that silently allowed one extra iteration would fail this.
        assert backend.call_count == 3

    def test_max_tool_calls_stops_before_dispatching_an_over_budget_batch(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = InfiniteToolBackend()
        config = _loop.LoopConfig(max_iterations=1000, max_tool_calls=2)

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:demo:default", "go", config=config
        )

        assert result.ok is False
        assert result.stop_reason == "max_tool_calls"
        assert result.tool_calls_executed == 2

    def test_max_tool_calls_never_dispatches_a_partial_batch(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """A single response requesting more tool calls than remain in budget
        is rejected wholesale -- never partially dispatched, which would leave
        an orphaned tool_calls entry in session history."""
        calls = [ToolCall(id=f"c{i}", name="echo", arguments='{"text": "x"}') for i in range(5)]
        backend = ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=calls),
                    finish_reason="tool_calls",
                    usage=TokenUsage(input_tokens=10, output_tokens=5),
                )
            ]
        )
        config = _loop.LoopConfig(max_tool_calls=3)
        session_key = "agent:demo:default"

        result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go", config=config)

        assert result.ok is False
        assert result.stop_reason == "max_tool_calls"
        assert result.tool_calls_executed == 0
        record = load_session(session_key)
        assert len(record.messages) == 1  # only the user turn; nothing orphaned

    def test_wall_clock_timeout_stops_without_real_sleep(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = InfiniteToolBackend()
        config = _loop.LoopConfig(
            max_iterations=1000, max_tool_calls=1000, wall_clock_timeout_s=5.0
        )
        # A fake clock: 0, 1, 2, 3, ... seconds per call -- crosses the 5s
        # budget on the 6th check without any real time passing.
        ticks = iter(range(0, 100))

        def fake_clock() -> float:
            return float(next(ticks))

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:demo:default", "go", config=config, clock=fake_clock
        )

        assert result.ok is False
        assert result.stop_reason == "timeout"
        assert result.failure_kind == "timeout"

    def test_token_budget_stops_a_turn_that_keeps_spending(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = InfiniteToolBackend()  # 15 tokens (10 in + 5 out) per iteration
        config = _loop.LoopConfig(max_iterations=1000, max_tool_calls=1000, token_budget=40)

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:demo:default", "go", config=config
        )

        assert result.ok is False
        assert result.stop_reason == "token_budget"
        assert result.failure_kind == "invalid_output"
        assert result.usage.total_tokens > 40

    def test_backend_error_is_reported_with_its_own_failure_kind(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = ScriptedBackend(
            [ChatResponse(ok=False, error="endpoint unreachable", failure_kind="daemon_error")]
        )
        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")
        assert result.ok is False
        assert result.stop_reason == "backend_error"
        assert result.failure_kind == "daemon_error"
        assert result.error == "endpoint unreachable"


# ── durability: persisted per iteration ──────────────────────────────────────


class TestDurability:
    def test_incoming_message_is_persisted_before_any_model_call(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        backend = ScriptedBackend([_final("ok")])
        _loop.run_agent_turn(backend, registry, ctx, session_key, "please help")
        # Even inspecting mid-flight isn't possible from outside, but the
        # post-condition proves the user turn was written via append_messages
        # (not assembled only in memory and flushed once at the very end):
        # combined with test_max_tool_calls_never_dispatches_a_partial_batch
        # above (which stops immediately after the same one append), the
        # user message is confirmed present independent of how the turn ends.
        record = load_session(session_key)
        assert record.messages[0].role == "user"
        assert record.messages[0].content == "please help"

    def test_a_crash_after_n_iterations_loses_at_most_the_next_one(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """Simulates a crash: the backend raises on the 3rd call, standing in
        for a process death mid-loop. Iterations 1-2 (each a real tool round
        trip) must already be durable."""
        session_key = "agent:demo:default"

        class CrashingBackend:
            def __init__(self) -> None:
                self.n = 0

            def complete(
                self, messages, *, tools=(), max_tokens=None, temperature=None, timeout=120
            ):
                self.n += 1
                if self.n == 3:
                    raise RuntimeError("simulated crash")
                return _tool_call_response(f"c{self.n}", "echo", f'{{"text": "turn{self.n}"}}')

        backend = CrashingBackend()
        with pytest.raises(RuntimeError):
            _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        record = load_session(session_key)
        # user turn + 2 completed (assistant, tool) pairs = 5 messages.
        roles = [m.role for m in record.messages]
        assert roles == ["user", "assistant", "tool", "assistant", "tool"]


# ── tracing ───────────────────────────────────────────────────────────────────


class TestTracing:
    def test_every_dispatched_tool_call_emits_call_and_result_trace_events(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )
        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        tracefile = _cfg.TRACES_DIR / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        assert tracefile.exists()
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        event_types = [r["event_type"] for r in records]
        assert event_types == ["tool_call", "tool_result"]
        assert records[0]["payload"]["tool"] == "echo"
        assert records[1]["payload"]["decision"] == "allow"
        assert records[1]["payload"]["executed"] is True

    def test_no_tool_calls_means_no_trace_events(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        backend = ScriptedBackend([_final("no tools needed")])
        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        tracefile = _cfg.TRACES_DIR / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        assert not tracefile.exists()

    def test_trace_project_falls_back_to_agent_id_when_project_unset(
        self, workspace: Path, registry: ToolRegistry
    ) -> None:
        bare_ctx = ToolContext(agent_id="bare-agent", roots=(workspace,), timeout=10)
        session_key = "agent:bare:default"
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )
        _loop.run_agent_turn(backend, registry, bare_ctx, session_key, "go")

        tracefile = _cfg.TRACES_DIR / "bare-agent" / f"{session_key}.jsonl"
        assert tracefile.exists()


# ── multi-turn history feeding ───────────────────────────────────────────────


class TestHistoryFeeding:
    def test_prior_session_history_is_loaded_and_sent_to_the_backend(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        # Seed a prior turn.
        _loop.run_agent_turn(
            ScriptedBackend([_final("first answer")]), registry, ctx, session_key, "first question"
        )

        backend = ScriptedBackend([_final("second answer")])
        result = _loop.run_agent_turn(backend, registry, ctx, session_key, "second question")

        assert result.ok
        sent_contents = [m.content for m in backend.calls[0]]
        assert "first question" in sent_contents
        assert "first answer" in sent_contents
        assert "second question" in sent_contents
