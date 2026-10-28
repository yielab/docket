"""Cooperative cancellation of a turn, and the trace the loop writes."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from tests.support.loop_harness import (
    ScriptedBackend,
    _final,
    _tool_call_response,
    _write_gate_policy,
)
from tests.support.model_server import call, say

from docket.agent import loop as _loop
from docket.agent import loop_trace as _loop_trace
from docket.agent import session as _session
from docket.agent import session_units as _session_units
from docket.agent.ports import (
    ChatMessage,
    ChatResponse,
    Endpoint,
    TokenUsage,
    ToolCall,
    ToolSpec,
    assistant,
)
from docket.agent.session import append_messages as append_session_messages
from docket.agent.session import load_session
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool as _Tool
from docket.agent.tools.registry import ToolContext, ToolRegistry
from docket.governance import approval as _approval
from docket.governance import gate as _gate
from docket.kernel.home import current_home, use_home
from docket.kernel.threads import new_thread
from docket.models.adapters import openai_http as _llm_adapter
from docket.observability import trace as _trace

SUBJECT = "docket.agent.loop"


class CancellationProbe:
    """Thread-safe test callback matching C10b's ToolContext boundary."""

    def __init__(self) -> None:
        self._requested = threading.Event()
        self.checkpoints = 0

    def request(self) -> None:
        self._requested.set()

    def __call__(self) -> bool:
        self.checkpoints += 1
        return self._requested.is_set()


class BarrierBackend(ScriptedBackend):
    """Block one selected transport while recording its exact call ordinal."""

    def __init__(self, responses: Sequence[ChatResponse], *, block_call: int = 0) -> None:
        super().__init__(responses)
        self.block_call = block_call
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        tool_choice: str | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        ordinal = len(self.calls)
        self.calls.append(list(messages))
        self.tool_specs.append(list(tools))
        if ordinal == self.block_call:
            self.entered.set()
            assert self.release.wait(timeout=5)
        if not self._responses:
            raise AssertionError("BarrierBackend ran out of scripted responses")
        return self._responses.pop(0)


def _attach_cancellation(ctx: ToolContext, probe: CancellationProbe) -> None:
    # ToolContext intentionally has no slots. This reaches the future public
    # callback boundary while allowing the pre-C10b loop to run far enough to
    # demonstrate the missing checkpoint instead of failing at construction.
    ctx.cancellation_check = probe  # type: ignore[attr-defined]


def _threaded_turn(
    backend: ScriptedBackend,
    registry: ToolRegistry,
    ctx: ToolContext,
    session_key: str,
    message: str,
    *,
    config: _loop.LoopConfig | None = None,
) -> tuple[threading.Thread, list[_loop.AgentLoopResult], list[BaseException]]:
    results: list[_loop.AgentLoopResult] = []
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            results.append(
                _loop.run_agent_turn(
                    backend,
                    registry,
                    ctx,
                    session_key,
                    message,
                    config=config,
                )
            )
        except BaseException as exc:  # surfaced in the owning test thread
            errors.append(exc)

    worker = new_thread(target=_run, name=f"turn:{session_key}")
    worker.start()
    return worker, results, errors


_WIRE_PART_BY_ROLE = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "toolResults",
}


def _wire_parts(body: dict[str, Any]) -> dict[str, int]:
    """Bytes of each request part, measured on the body the stub endpoint received."""
    sizes = dict.fromkeys(("system", "tools", "toolResults", "assistant", "user"), 0)
    for message in body["messages"]:
        sizes[_WIRE_PART_BY_ROLE[message["role"]]] += _utf8(message)
    for tool in body.get("tools", []):
        sizes["tools"] += _utf8(tool)
    return sizes


def _utf8(part: Any) -> int:
    return len(json.dumps(part, ensure_ascii=False).encode("utf-8"))


class TestCooperativeRunCancellation:
    def test_task_response_after_request_is_discarded_before_tool_execution(
        self,
        ctx: ToolContext,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        probe = CancellationProbe()
        _attach_cancellation(ctx, probe)
        handler_calls: list[str] = []
        registry = ToolRegistry()
        registry.register(
            _Tool(
                name="record",
                description="record one value",
                parameters={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
                handler=lambda args, _ctx: (
                    handler_calls.append(str(args["value"]))
                    or ToolOutcome(ok=True, content="recorded")
                ),
            )
        )
        backend = BarrierBackend(
            [
                _tool_call_response("late-call", "record", '{"value":"must-not-run"}'),
                _final("must not make a second transport"),
            ]
        )
        events: list[tuple[str, dict[str, Any]]] = []

        def _trace(
            _project: str,
            _session: str,
            _role: str,
            event_type: str,
            payload: str,
            *_args: object,
            **_kwargs: object,
        ) -> str:
            events.append((event_type, json.loads(payload)))
            return "written"

        real_tracer_except(trace_event=_trace)
        session_key = "agent:cancel-task:demo"
        worker, results, errors = _threaded_turn(backend, registry, ctx, session_key, "go")
        try:
            assert backend.entered.wait(timeout=5)
            probe.request()
        finally:
            backend.release.set()
            worker.join(timeout=5)

        assert not worker.is_alive()
        assert errors == []
        assert len(results) == 1
        assert results[0].ok is False
        assert results[0].stop_reason == "run_cancelled"
        assert results[0].failure_kind == "run_cancelled"
        assert len(backend.calls) == 1
        assert handler_calls == []
        stored = load_session(session_key)
        assert [message.role for message in stored.messages] == ["user"]
        assert stored.usage.input_tokens == 10
        assert stored.usage.output_tokens == 5
        assert stored.usage.cached_tokens == 0
        assert stored.usage.turns == 1
        assert [kind for kind, _payload in events if kind in {"tool_call", "tool_result"}] == []

    def test_compaction_response_after_request_cannot_rewrite_or_start_task_transport(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        probe = CancellationProbe()
        _attach_cancellation(ctx, probe)
        session_key = "agent:cancel-compaction:demo"
        append_session_messages(
            session_key,
            [
                ChatMessage(role="user", content="old context " * 100),
                ChatMessage(role="assistant", content="old complete answer"),
                ChatMessage(role="user", content="recent context"),
            ],
        )
        before = load_session(session_key)
        backend = BarrierBackend(
            [
                _final("cancelled summary must not replace history", TokenUsage(7, 3)),
                _final("task transport must not start"),
            ]
        )
        worker, results, errors = _threaded_turn(
            backend,
            registry,
            ctx,
            session_key,
            "new request",
            config=_loop.LoopConfig(history_budget_tokens=1),
        )
        try:
            assert backend.entered.wait(timeout=5)
            assert backend.tool_specs == [[]]
            probe.request()
        finally:
            backend.release.set()
            worker.join(timeout=5)

        assert not worker.is_alive()
        assert errors == []
        assert len(results) == 1
        assert results[0].stop_reason == "run_cancelled"
        assert results[0].failure_kind == "run_cancelled"
        assert len(backend.calls) == 1
        after = load_session(session_key)
        assert after.messages == before.messages
        assert not any("cancelled summary" in message.content for message in after.messages)

    def test_cancellation_after_concurrent_approval_grant_never_runs_handler(
        self, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        probe = CancellationProbe()
        _attach_cancellation(ctx, probe)
        handler_calls: list[str] = []
        registry = ToolRegistry()
        registry.register(
            _Tool(
                name="guarded",
                description="approval-gated action",
                parameters={"type": "object", "properties": {}},
                handler=lambda _args, _ctx: (
                    handler_calls.append("ran") or ToolOutcome(ok=True, content="ran")
                ),
                kind="write",
            )
        )
        monkeypatch.setattr(
            _gate,
            "evaluate_tool_call",
            lambda _tool, _args, _ctx: _gate.ToolVerdict("ask", "operator approval required"),
        )
        with use_home(
            dataclasses.replace(
                current_home(), tool_approval_timeout=5, tool_approval_poll_interval_s=0.005
            )
        ):
            backend = ScriptedBackend(
                [
                    _tool_call_response("guarded-call", "guarded", "{}"),
                    _final("must not continue after cancellation"),
                ]
            )
            session_key = "agent:cancel-approval:demo"
            worker, results, errors = _threaded_turn(backend, registry, ctx, session_key, "go")
            deadline = time.monotonic() + 5
            approval_files: list[Path] = []
            while time.monotonic() < deadline:
                approval_files = list(current_home().approvals_dir.glob("apr-*.json"))
                if approval_files:
                    break
                time.sleep(0.005)
            assert len(approval_files) == 1
            token = approval_files[0].stem
            assert _approval.approval_get(token)["state"] == "pending"

            probe.request()
            # The in-turn cancellation self-deny (`wait_for_approval`'s
            # `channel="cancellation"` path) may win this race instead, a real named
            # conflict; either winner must still uphold the invariant below: the
            # handler never runs.
            with contextlib.suppress(_approval.ApprovalConflict):
                _approval.approval_grant(token, channel="cli")
            worker.join(timeout=5)

            assert not worker.is_alive()
            assert errors == []
            assert _approval.approval_get(token)["state"] in {"granted", "denied"}
            assert handler_calls == []
            assert len(results) == 1
            assert results[0].stop_reason == "run_cancelled"
            assert results[0].failure_kind == "run_cancelled"
            assert len(backend.calls) == 1

    def test_running_handler_finishes_then_remainder_is_cancelled_as_one_unit(
        self,
        ctx: ToolContext,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        probe = CancellationProbe()
        _attach_cancellation(ctx, probe)
        first_entered = threading.Event()
        release_first = threading.Event()
        handler_calls: list[str] = []

        def _handler(args: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
            value = str(args["value"])
            handler_calls.append(value)
            if value == "first":
                first_entered.set()
                assert release_first.wait(timeout=5)
            return ToolOutcome(ok=True, content=f"{value} done")

        registry = ToolRegistry()
        registry.register(
            _Tool(
                name="record",
                description="record ordered values",
                parameters={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
                handler=_handler,
            )
        )
        calls = [
            ToolCall(id="first-call", name="record", arguments='{ "value": "first" }'),
            ToolCall(id="second-call", name="record", arguments='{ "value": "second" }'),
        ]
        backend = ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=calls),
                    finish_reason="tool_calls",
                    usage=TokenUsage(input_tokens=12, output_tokens=6),
                ),
                _final("must not start another backend request"),
            ]
        )
        events: list[tuple[str, dict[str, Any]]] = []

        def _trace(
            _project: str,
            _session: str,
            _role: str,
            event_type: str,
            payload: str,
            *_args: object,
            **_kwargs: object,
        ) -> str:
            events.append((event_type, json.loads(payload)))
            return "written"

        real_tracer_except(trace_event=_trace)
        session_key = "agent:cancel-tool-batch:demo"
        worker, results, errors = _threaded_turn(backend, registry, ctx, session_key, "go")
        try:
            assert first_entered.wait(timeout=5)
            probe.request()
        finally:
            release_first.set()
            worker.join(timeout=5)

        assert not worker.is_alive()
        assert errors == []
        assert handler_calls == ["first"]
        assert len(results) == 1
        assert results[0].stop_reason == "run_cancelled"
        assert results[0].failure_kind == "run_cancelled"
        assert results[0].tool_calls_executed == 1
        assert len(backend.calls) == 1
        stored = load_session(session_key)
        assert [message.role for message in stored.messages] == [
            "user",
            "assistant",
            "tool",
            "tool",
        ]
        assert stored.messages[2].tool_call_id == "first-call"
        assert stored.messages[2].content == "first done"
        assert stored.messages[3].tool_call_id == "second-call"
        assert (
            stored.messages[3].content
            == "REFUSED [run_cancelled]: run cancellation requested before execution"
        )
        assert not _session_units.find_orphaned_tool_messages(stored.messages)
        assert not _session_units.find_unanswered_tool_calls(stored.messages)
        tool_results = [payload for kind, payload in events if kind == "tool_result"]
        assert [payload["callId"] for payload in tool_results] == ["first-call", "second-call"]
        assert tool_results[1]["executed"] is False
        assert tool_results[1]["denialKind"] == "run_cancelled"


class TestTracing:
    def test_trace_coordinate_can_differ_from_durable_history_coordinate(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        history_key = "agent:demo-agent:demo:task:t1:step:implementer"
        trace_key = "agent:demo:t1"
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )

        _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            history_key,
            "go",
            trace_session_key=trace_key,
        )

        assert [m.role for m in _session.load_messages(history_key)] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        assert _session.load_messages(trace_key) == []
        assert not (current_home().traces_dir / "demo" / f"{history_key}.jsonl").exists()
        tracefile = current_home().traces_dir / "demo" / f"{trace_key}.jsonl"
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        assert all(record["session_id"] == trace_key for record in records)
        assert {record["event_type"] for record in records} >= {
            "session_compaction",
            "tool_call",
            "tool_result",
        }

    def test_every_dispatched_tool_call_emits_call_and_result_trace_events(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )
        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        tracefile = (
            current_home().traces_dir / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        )
        assert tracefile.exists()
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        event_types = [r["event_type"] for r in records]
        assert [kind for kind in event_types if kind in {"tool_call", "tool_result"}] == [
            "tool_call",
            "tool_result",
        ]
        tool_records = [
            record for record in records if record["event_type"] in {"tool_call", "tool_result"}
        ]
        assert tool_records[0]["payload"]["tool"] == "echo"
        assert tool_records[1]["payload"]["decision"] == "allow"
        assert tool_records[1]["payload"]["executed"] is True

    def test_tool_result_trace_carries_policy_id_and_reason_for_a_gated_denial(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """A denial that carries a policy id/reason -- here, a refuse-mode
        `approval_unavailable` -- surfaces both on the `tool_result` trace
        payload, not just on the returned `ToolResult`."""
        _write_gate_policy("test-trace-echo", r"\becho\b", "require_approval")
        ctx.approval_mode = "refuse"
        session_key = "agent:demo:trace-policy"
        backend = ScriptedBackend([_tool_call_response("c1", "echo", '{"text": "hi"}')])

        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        tracefile = (
            current_home().traces_dir / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        )
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        tool_result_record = next(r for r in records if r["event_type"] == "tool_result")
        assert tool_result_record["payload"]["denialKind"] == "approval_unavailable"
        assert tool_result_record["payload"]["policyId"] == "test-trace-echo"
        assert tool_result_record["payload"]["reason"]

    def test_no_tool_calls_means_no_trace_events(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        backend = ScriptedBackend([_final("no tools needed")])
        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        tracefile = (
            current_home().traces_dir / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        )
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        assert not [
            record for record in records if record["event_type"] in {"tool_call", "tool_result"}
        ]

    def test_request_fit_trace_is_registered_and_contains_only_estimates(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:fit-trace:default"
        backend = ScriptedBackend([_final("done")])

        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        tracefile = (
            current_home().traces_dir / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        )
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        fit = next(record["payload"] for record in records if record["event_type"] == "request_fit")
        assert fit["status"] == "unknown_window"
        assert fit["purpose"] == "task"
        assert fit["estimate"] is True
        assert "messages" not in fit and "prompt" not in fit and "usage" not in fit

    def test_trace_project_falls_back_to_agent_id_when_project_unset(
        self, workspace: Path, registry: ToolRegistry
    ) -> None:
        bare_ctx = ToolContext(agent_id="bare-agent", roots=(workspace,), timeout=10)
        session_key = "agent:bare:default"
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )
        _loop.run_agent_turn(backend, registry, bare_ctx, session_key, "go")

        tracefile = current_home().traces_dir / "bare-agent" / f"{session_key}.jsonl"
        assert tracefile.exists()


class TestLlmCallRequestBreakdown:
    def test_request_parts_match_the_bytes_the_endpoint_received(
        self, ctx: ToolContext, registry: ToolRegistry, fake_model: Any
    ) -> None:
        server = fake_model(sequence=[call("echo", "c1", text="hi"), say("ok")])
        backend = _llm_adapter.OpenAIChatClient(
            Endpoint(base_url=server.base_url, model_id="local-model")
        )
        events: list[dict[str, Any]] = []
        with _trace.subscribe(events.append):
            result = _loop.run_agent_turn(
                backend, registry, ctx, "agent:demo:default", "revisa el \u00f1and\u00fa"
            )

        assert result.ok
        payloads = [e["payload"] for e in events if e["event_type"] == "llm_call"]
        assert len(payloads) == len(server.requests) == 2
        for payload, sent_request in zip(payloads, server.requests, strict=True):
            request = payload["request"]
            assert set(request) == {"system", "tools", "toolResults", "assistant", "user"}
            sent = _wire_parts(sent_request.body)
            assert {part: request[part]["bytes"] for part in request} == sent
            for part in request.values():
                assert part["estTokens"] == part["bytes"] // current_home().context_bytes_per_token
        assert payloads[0]["request"]["tools"]["bytes"] > 0
        assert payloads[1]["request"]["toolResults"]["bytes"] > 0
        assert payloads[1]["request"]["assistant"]["bytes"] > 0


class TestLlmCallTrace:
    def test_two_llm_call_records_with_measured_usage_and_no_cost(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        backend = ScriptedBackend(
            [
                _tool_call_response(
                    "c1",
                    "echo",
                    '{"text": "hi"}',
                    usage=TokenUsage(input_tokens=10, output_tokens=5),
                ),
                _final("ok", usage=TokenUsage(input_tokens=20, output_tokens=8)),
            ]
        )
        events: list[dict[str, Any]] = []
        with _trace.subscribe(events.append):
            result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        assert result.ok
        llm_calls = [e for e in events if e["event_type"] == "llm_call"]
        assert [c["payload"]["iteration"] for c in llm_calls] == [1, 2]
        assert [c["payload"]["inputTokens"] for c in llm_calls] == [10, 20]
        assert [c["payload"]["outputTokens"] for c in llm_calls] == [5, 8]
        for record in llm_calls:
            assert isinstance(record["duration_ms"], int)
            assert record["duration_ms"] >= 0
            assert "cost_usd" not in record

    def test_cache_write_tokens_appear_only_when_positive(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = ScriptedBackend(
            [
                _tool_call_response(
                    "c1",
                    "echo",
                    '{"text": "hi"}',
                    usage=TokenUsage(input_tokens=10, output_tokens=5, cache_write_tokens=7),
                ),
                _final("ok", usage=TokenUsage(input_tokens=20, output_tokens=8)),
            ]
        )
        events: list[dict[str, Any]] = []
        with _trace.subscribe(events.append):
            result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")

        assert result.ok
        first, second = [e["payload"] for e in events if e["event_type"] == "llm_call"]
        assert first["cacheWriteTokens"] == 7
        assert "cacheWriteTokens" not in second

    def test_a_failed_second_call_is_traced_with_its_failure_kind(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        backend = ScriptedBackend(
            [
                _tool_call_response("c1", "echo", '{"text": "hi"}'),
                ChatResponse(ok=False, error="timed out", failure_kind="timeout"),
            ]
        )
        events: list[dict[str, Any]] = []
        with _trace.subscribe(events.append):
            result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        assert not result.ok
        assert result.failure_kind == "timeout"
        llm_calls = [e for e in events if e["event_type"] == "llm_call"]
        assert len(llm_calls) == 2
        assert llm_calls[1]["payload"]["ok"] is False
        assert llm_calls[1]["payload"]["failureKind"] == "timeout"

    def test_prompts_and_completions_are_captured_and_redacted_when_granted(
        self,
        ctx: ToolContext,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        real_tracer_except(capture_classes=lambda: frozenset({"prompts", "completions"}))
        session_key = "agent:demo:content"
        secret_call = '{"text": "leaked-secret@example.com"}'
        backend = ScriptedBackend([_tool_call_response("c1", "echo", secret_call), _final("ok")])
        events: list[dict[str, Any]] = []
        with _trace.subscribe(events.append):
            result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        assert result.ok
        llm_calls = [e["payload"] for e in events if e["event_type"] == "llm_call"]
        assert len(llm_calls) == 2
        first, second = llm_calls

        # No exporter granted "instructions" -- neither call carries it.
        assert "systemInstructions" not in first
        assert "systemInstructionsSha256" not in first
        assert "systemInstructions" not in second
        assert "systemInstructionsSha256" not in second

        # First call: a tool call was requested; its arguments are redacted in outputMessages,
        # and inputMessages is only the user's task (no system turn).
        assert [m["role"] for m in first["inputMessages"]] == ["user"]
        assert first["outputMessages"] == [
            {
                "role": "assistant",
                "parts": [
                    {
                        "type": "tool_call",
                        "id": "c1",
                        "name": "echo",
                        "arguments": '{"text": "[REDACTED]"}',
                    }
                ],
            }
        ]

        # Second call: inputMessages replays the tool call and its result -- both redacted --
        # and outputMessages is the final text reply.
        assert [m["role"] for m in second["inputMessages"]] == ["user", "assistant", "tool"]
        assistant_turn, tool_turn = second["inputMessages"][1], second["inputMessages"][2]
        assert assistant_turn["parts"] == [
            {"type": "tool_call", "id": "c1", "name": "echo", "arguments": '{"text": "[REDACTED]"}'}
        ]
        assert tool_turn["parts"] == [
            {"type": "tool_call_response", "id": "c1", "response": "[REDACTED]"}
        ]
        assert second["outputMessages"] == [
            {"role": "assistant", "parts": [{"type": "text", "content": "ok"}]}
        ]

    def test_empty_grant_matches_the_capture_disabled_shape(
        self,
        ctx: ToolContext,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        real_tracer_except(capture_classes=lambda: frozenset())
        session_key = "agent:demo:no-content"
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )
        events: list[dict[str, Any]] = []
        with _trace.subscribe(events.append):
            result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go")
        assert result.ok
        with_capture_path = [
            json.dumps({k: v for k, v in e["payload"].items() if k != "request"})
            for e in events
            if e["event_type"] == "llm_call"
        ]

        # The pre-card call shape: `_trace_llm_call` invoked with no `messages` at all, as
        # every call site did before this card -- the capture path never runs.
        baseline_events: list[dict[str, Any]] = []
        with _trace.subscribe(baseline_events.append):
            _loop_trace._trace_llm_call(
                "demo",
                session_key,
                "implementer",
                _tool_call_response("c1", "echo", '{"text": "hi"}'),
                1,
            )
            _loop_trace._trace_llm_call("demo", session_key, "implementer", _final("ok"), 2)
        baseline = [json.dumps(e["payload"]) for e in baseline_events]

        assert with_capture_path == baseline

    @pytest.mark.parametrize("granted", [frozenset({"toolResults"}), frozenset()])
    def test_tool_result_text_is_captured_only_when_granted(
        self,
        ctx: ToolContext,
        registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
        granted: frozenset[str],
        real_tracer_except: Callable[..., None],
    ) -> None:
        real_tracer_except(capture_classes=lambda: granted)
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "echoed-back"}'), _final("ok")]
        )
        events: list[dict[str, Any]] = []
        with _trace.subscribe(events.append):
            result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:tool-text", "go")
        assert result.ok
        (payload,) = [e["payload"] for e in events if e["event_type"] == "tool_result"]
        if granted:
            assert "echoed-back" in payload["text"]
        else:
            assert "text" not in payload
