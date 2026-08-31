"""`DocketDriver`, the daemon-free `RuntimeDriver`
(`edges/adapters/docket_runtime.py`).

`DocketDriver` implements the 7-method `RuntimeDriver` Protocol on top of
`core/agent_loop.py` with no external daemon underneath. Covers:

* **`run_turn`** maps `AgentLoopResult` onto `TurnResult` honestly: `cost_usd`
  stays `0.0` always, real tool calls actually execute end-to-end (through
  the real gated dispatcher, not a stub), and an ordinary failure (missing
  meta, unresolvable model) comes back as `TurnResult(ok=False, ...)`,
  never an exception.
* **Root resolution precedence** for the tool-containment boundary --
  worktree > codebase > work_dir > bare workspace dir -- proven with the
  real `read` tool against real marker files, not just by inspecting the
  helper's logic.
* **`provision`/`teardown`** are honest no-ops (no daemon to register or
  unregister with), and `capabilities()` says so.
* **`list_sessions`/`read_new_turns`/`usage`** read real, durable
  `core/session.py` storage, scoped correctly to one agent's own sessions.
"""

from __future__ import annotations

import json
import time as _time
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _gates, _keys
from docket.core import approval as _approval
from docket.core import fleet as _fleet
from docket.core import memory as _memory
from docket.core import provider as _provider_core
from docket.core import secrets as _secrets
from docket.core import session as _session
from docket.core.audit import read_audit
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.core.runtime_driver import PIPELINE_WORKTREE_ENV
from docket.core.session import load_session
from docket.core.tools import Tool, ToolContext, ToolRegistry
from docket.edges import store as _store
from docket.edges.adapters import llm as _llm_adapter
from docket.edges.adapters import system as _system
from docket.edges.adapters.docket_runtime import DocketDriver
from docket.edges.adapters.system import SandboxAvailability
from docket.edges.adapters.toolbox import ToolOutcome


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", tmp_path / "docket", raising=True)
    monkeypatch.setattr(
        _cfg, "PROJECTS_DIR", tmp_path / "docket" / "workspaces" / "projects", raising=True
    )
    monkeypatch.setattr(_cfg, "SESSIONS_DIR", tmp_path / "sessions", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", tmp_path / "traces", raising=True)
    monkeypatch.setattr(_cfg, "POLICIES_DIR", tmp_path / "policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", tmp_path / "docket" / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)
    # DOCKET_SANDBOX_BACKEND leaking in from the real dev/CI environment would
    # make TestIsolationWiring's "no backend available" cases flaky -- start
    # every test from the same clean slate and let individual tests opt in.
    monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)


def _write_meta(agent_id: str, **overrides: object) -> Path:
    """Write a real `.docket-meta.json` for *agent_id* and return its workspace dir."""
    ws = _cfg.workspace_dir(agent_id)
    ws.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"kind": "project", "role": "implementer", "model": "test/model"}
    data.update(overrides)
    _store.write_json(_cfg.meta_path(agent_id), data)
    return ws


class _ScriptedBackend:
    """Replays a fixed script of `ChatResponse`s -- see test_agent_loop.py
    for the identical pattern; redefined locally per this suite's convention
    of self-contained per-file test doubles rather than a shared fake."""

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []
        self.max_tokens_seen: list[int | None] = []

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
        self.max_tokens_seen.append(max_tokens)
        return self._responses.pop(0)


def _final_response(text: str, usage: TokenUsage | None = None) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=usage or TokenUsage(5, 5)
    )


def _read_call_response(path: str, usage: TokenUsage | None = None) -> ChatResponse:
    call = ToolCall(id="c1", name="read", arguments=json.dumps({"path": path}))
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=usage or TokenUsage(10, 5),
    )


def _never_called(model: str):  # pragma: no cover - only exercised on a real bug
    raise AssertionError(f"backend_factory should not have been called for model {model!r}")


# ── run_turn ─────────────────────────────────────────────────────────────────


class TestRunTurn:
    def test_public_local_provider_setup_reaches_gated_tool_turn_without_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", tmp_path / "docket-models.json")
        monkeypatch.setattr(_secrets, "SECRETS_FILE", tmp_path / "secrets.json")
        monkeypatch.setattr(_secrets, "SECRETS_META_FILE", tmp_path / "secrets.meta.json")
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        monkeypatch.setattr(_provider_core, "ping_endpoint", lambda *args, **kwargs: True)

        runner = CliRunner()
        registered = runner.invoke(
            app,
            [
                "models",
                "provider",
                "add",
                "local",
                "http://127.0.0.1:8081/v1",
                "--model",
                "qwen-live-id",
                "--ctx",
                "16384",
                "--max-tokens",
                "8192",
            ],
        )
        assert registered.exit_code == 0, registered.output
        selected = runner.invoke(app, ["models", "preset", "local"])
        assert selected.exit_code == 0, selected.output

        ws = _write_meta("local-agent", model="local/qwen-live-id", modelSource="policy")
        (ws / "marker.txt").write_text("LOCAL_PROVIDER_MARKER\n", encoding="utf-8")

        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "local-read-1",
                                    "type": "function",
                                    "function": {
                                        "name": "read",
                                        "arguments": json.dumps({"path": "marker.txt"}),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "local tool turn complete"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 17, "completion_tokens": 4},
            },
        ]
        request_urls: list[str] = []
        requests: list[dict[str, Any]] = []

        class _Response:
            def __init__(self, payload: dict[str, Any]) -> None:
                self.payload = payload

            def read(self) -> bytes:
                return json.dumps(self.payload).encode()

            def __enter__(self) -> _Response:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        def fake_urlopen(request: Any, timeout: int = 0) -> _Response:
            request_urls.append(request.full_url)
            requests.append(json.loads(request.data.decode()))
            return _Response(responses.pop(0))

        monkeypatch.setattr(_llm_adapter.urllib.request, "urlopen", fake_urlopen)

        result = DocketDriver().run_turn(
            "local-agent", "agent:local-agent:default", "Read marker.txt with the tool.", 60
        )

        assert result.ok is True
        assert result.output == "local tool turn complete"
        assert len(requests) == 2
        assert request_urls == [
            "http://127.0.0.1:8081/v1/chat/completions",
            "http://127.0.0.1:8081/v1/chat/completions",
        ]
        assert requests[0]["model"] == "qwen-live-id"
        assert requests[0]["tools"]
        assert any(message["role"] == "tool" for message in requests[1]["messages"])
        assert "LOCAL_PROVIDER_MARKER" in json.dumps(requests[1])
        assert _secrets.secrets_keys() == set()

    @pytest.mark.parametrize(
        ("provider_key", "secret", "model", "expected_url", "wire_model"),
        [
            (
                "OPENROUTER_API_KEY",
                "sk-or-runtime-test",
                "openrouter/anthropic/claude-sonnet-4.6",
                "https://openrouter.ai/api/v1/chat/completions",
                "anthropic/claude-sonnet-4.6",
            ),
            (
                "AI_GATEWAY_API_KEY",
                "vercel-runtime-test",
                "ai-gateway/anthropic/claude-sonnet-4.6",
                "https://ai-gateway.vercel.sh/v1/chat/completions",
                "anthropic/claude-sonnet-4.6",
            ),
        ],
    )
    def test_stored_gateway_key_reaches_real_driver_and_http_adapter(
        self,
        provider_key: str,
        secret: str,
        model: str,
        expected_url: str,
        wire_model: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        monkeypatch.delenv(provider_key, raising=False)
        monkeypatch.setattr(_secrets, "SECRETS_FILE", tmp_path / "secrets.json")
        monkeypatch.setattr(_secrets, "SECRETS_META_FILE", tmp_path / "secrets.meta.json")
        monkeypatch.setattr(_keys, "project_ids", lambda: [])
        monkeypatch.setattr(_keys._getpass, "getpass", lambda prompt: secret)

        assert _keys.run_keys("add", [provider_key]) == 0
        _write_meta("gateway-agent", model=model)

        captured: dict[str, object] = {}

        class _Response:
            def read(self) -> bytes:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "gateway ok"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 9, "completion_tokens": 2},
                    }
                ).encode()

            def __enter__(self) -> _Response:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        def fake_urlopen(request: Any, timeout: int = 0) -> _Response:
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            captured["payload"] = json.loads(request.data.decode())
            return _Response()

        monkeypatch.setattr(_llm_adapter.urllib.request, "urlopen", fake_urlopen)

        result = DocketDriver().run_turn(
            "gateway-agent", "agent:gateway-agent:default", "Use the available tools if needed.", 60
        )

        assert result.ok is True
        assert result.output == "gateway ok"
        assert captured["url"] == expected_url
        assert captured["auth"] == f"Bearer {secret}"
        payload = captured["payload"]
        assert isinstance(payload, dict)
        assert payload["model"] == wire_model
        assert payload["stream"] is False
        assert payload["tools"]
        assert secret not in json.dumps(payload)
        trace_text = "".join(
            path.read_text(encoding="utf-8")
            for path in _cfg.TRACES_DIR.rglob("*")
            if path.is_file()
        )
        assert secret not in trace_text

    def test_registered_limits_reach_the_loop_and_transport(self) -> None:
        _write_meta("bounded-agent")
        backend = _ScriptedBackend([_final_response("bounded")])
        backend.context_window_tokens = 4096  # type: ignore[attr-defined]
        backend.max_output_tokens = 64  # type: ignore[attr-defined]
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn("bounded-agent", "agent:bounded-agent:default", "hi", 60)

        assert result.ok
        assert backend.max_tokens_seen == [64]

    def test_default_driver_reserves_a_tool_free_terminal_response_inside_budget(self) -> None:
        ws = _write_meta("budget-agent")
        (ws / "module.py").write_text("VALUE = 'broken'\n")

        class BudgetBackend:
            context_window_tokens = 16_384
            max_output_tokens = 4_000

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                return 7_000 if tools else 1_000

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
                self.tools_seen.append(list(tools))
                call_number = len(self.calls)
                if call_number == 1:
                    call = ToolCall(
                        id="edit-1",
                        name="edit",
                        arguments=json.dumps(
                            {
                                "path": "module.py",
                                "old_string": "broken",
                                "new_string": "fixed",
                            }
                        ),
                    )
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(44_000, 1_000),
                    )
                if call_number == 2:
                    call = ToolCall(
                        id="validate-1",
                        name="read",
                        arguments=json.dumps({"path": "module.py"}),
                    )
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(44_000, 1_000),
                    )
                if tools:
                    call = ToolCall(
                        id="optional-1",
                        name="read",
                        arguments=json.dumps({"path": "module.py"}),
                    )
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(9_500, 600),
                    )
                return _final_response(
                    "fixed and validated without another optional tool round",
                    TokenUsage(900, 100),
                )

        backend = BudgetBackend()
        driver = DocketDriver(backend_factory=lambda model: backend)
        session_key = "agent:budget-agent:default"

        result = driver.run_turn(
            "budget-agent", session_key, "repair module.py and validate it", 60
        )

        assert result.ok
        assert result.output == "fixed and validated without another optional tool round"
        assert (ws / "module.py").read_text() == "VALUE = 'fixed'\n"
        assert len(backend.calls) == 3
        assert backend.tools_seen[0] and backend.tools_seen[1]
        assert backend.tools_seen[2] == []
        assert any(
            message.role == "system" and "terminal response" in message.content.lower()
            for message in backend.calls[2]
        )
        record = load_session(session_key)
        assert record.usage.input_tokens + record.usage.output_tokens == 91_000
        assert [message.role for message in record.messages] == [
            "user",
            "assistant",
            "tool",
            "assistant",
            "tool",
            "assistant",
        ]

    def test_terminal_reservation_precedes_request_fit_compaction(self) -> None:
        _write_meta("window-budget-agent")
        registry = ToolRegistry()
        raw_result = "CURRENT_TOOL_UNIT " * 1_000

        def _lookup(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
            return ToolOutcome(True, content=raw_result)

        registry.register(
            Tool(
                name="lookup",
                description="Return the current diagnostic.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class WindowBudgetBackend:
            context_window_tokens = 100_000
            max_output_tokens = 10_000

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    return 5_000
                if any(
                    message.role == "system" and "terminal response" in message.content.lower()
                    for message in messages
                ):
                    return 5_000
                if any(message.role == "tool" for message in messages) or any(
                    message.content.startswith("[compacted summary of ") for message in messages
                ):
                    return 150_000
                return 20_000

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
                self.tools_seen.append(list(tools))
                if tools:
                    call = ToolCall(id="lookup-1", name="lookup", arguments="{}")
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(65_000, 5_000),
                    )
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    return _final_response("bounded summary", TokenUsage(4_000, 1_000))
                assert any(
                    message.role == "system" and "terminal response" in message.content.lower()
                    for message in messages
                )
                return _final_response("truthful terminal response", TokenUsage(4_000, 1_000))

        backend = WindowBudgetBackend()
        session_key = "agent:window-budget-agent:default"
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=lambda: registry,
            mcp_loader=lambda registry, role: [],
        )

        result = driver.run_turn(
            "window-budget-agent", session_key, "inspect and report truthfully", 60
        )

        assert result.ok
        assert result.output == "truthful terminal response"
        assert len(backend.calls) == 2
        assert [bool(tools) for tools in backend.tools_seen] == [True, False]
        assert not any(
            len(call) == 1 and "compacting durable turn history" in call[0].content
            for call in backend.calls
        )
        assert any(
            message.role == "tool" and "CURRENT_TOOL_UNIT" in message.content
            for message in backend.calls[1]
        )
        record = load_session(session_key)
        assert record.usage.input_tokens + record.usage.output_tokens == 75_000
        assert not any(
            message.content.startswith("[compacted summary of ") for message in record.messages
        )
        assert any("CURRENT_TOOL_UNIT" in message.content for message in record.messages)
        trace_path = _cfg.TRACES_DIR / "window-budget-agent" / f"{session_key}.jsonl"
        records = [json.loads(line) for line in trace_path.read_text().splitlines()]
        warnings = [record for record in records if record["event_type"] == "budget_warning"]
        assert len(warnings) == 1
        assert warnings[0]["payload"]["action"] == "terminal_finalization"
        assert warnings[0]["payload"]["status"] == "entered"

    def test_irreducible_registered_window_fails_before_transport(self) -> None:
        _write_meta("tiny-window-agent")
        backend = _ScriptedBackend([_final_response("must not be called")])
        backend.context_window_tokens = 1  # type: ignore[attr-defined]
        backend.max_output_tokens = 1  # type: ignore[attr-defined]
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn(
            "tiny-window-agent", "agent:tiny-window-agent:default", "keep this exact", 60
        )

        assert not result.ok
        assert result.failure_kind == "invalid_output"
        assert "registered context window 1" in result.error
        assert backend.calls == []

    def test_request_fit_does_not_recompact_the_same_current_turn_segment(self) -> None:
        _write_meta("fit-agent")
        sentinel = "ORIGINAL_SENTINEL " * 500
        dispatches = 0
        registry = ToolRegistry()

        def _lookup(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
            nonlocal dispatches
            dispatches += 1
            return ToolOutcome(True, content=sentinel)

        registry.register(
            Tool(
                name="lookup",
                description="Return a large diagnostic result.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class RecompactionBackend:
            context_window_tokens = 1_000
            max_output_tokens = 200

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []
                self.prospectives: list[tuple[str, int]] = []
                self.summary_lengths = iter((1_500, 1_000, 600, 300))
                self.task_transports = 0

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    prospective = ("compaction", 700)
                elif any(message.role == "tool" for message in messages):
                    prospective = ("task", 1_220)
                elif any(
                    message.content.startswith("[compacted summary of ") for message in messages
                ):
                    prospective = ("task", 890)
                else:
                    prospective = ("task", 200)
                self.prospectives.append(prospective)
                return prospective[1]

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
                self.tools_seen.append(list(tools))
                if tools:
                    self.task_transports += 1
                    if self.task_transports > 1:
                        raise AssertionError("oversized task request must not reach the backend")
                    call = ToolCall(id="lookup-1", name="lookup", arguments="{}")
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(10, 5),
                    )
                assert "compacting durable turn history" in messages[0].content
                return _final_response("S" * next(self.summary_lengths), TokenUsage(10, 5))

        backend = RecompactionBackend()
        session_key = "agent:fit-agent:default"
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=lambda: registry,
            mcp_loader=lambda registry, role: [],
        )

        result = driver.run_turn("fit-agent", session_key, "inspect the diagnostic", 60)

        assert not result.ok
        assert result.failure_kind == "invalid_output"
        assert "estimated request 1090" in result.error
        assert "input 890" in result.error
        assert "output reserve 200" in result.error
        assert "registered context window 1000" in result.error
        assert "irreducible" in result.error
        assert dispatches == 1
        assert len(backend.calls) == 2
        assert [bool(tools) for tools in backend.tools_seen] == [True, False]
        assert backend.prospectives == [
            ("task", 200),
            ("task", 1_220),
            ("compaction", 700),
            ("task", 890),
        ]

        trace_path = _cfg.TRACES_DIR / "fit-agent" / f"{session_key}.jsonl"
        records = [json.loads(line) for line in trace_path.read_text().splitlines()]
        fit_payloads = [
            record["payload"] for record in records if record["event_type"] == "request_fit"
        ]
        assert [
            (payload["purpose"], payload["status"], payload["estimatedInputTokens"])
            for payload in fit_payloads
        ] == [
            ("task", "fits", 200),
            ("task", "failed", 1_220),
            ("compaction", "fits", 700),
            ("task", "failed", 890),
        ]
        expected_fit_keys = {
            "purpose",
            "status",
            "estimatedInputTokens",
            "outputReserveTokens",
            "contextWindowTokens",
            "estimate",
        }
        assert all(set(payload) == expected_fit_keys for payload in fit_payloads)
        assert all(payload["outputReserveTokens"] == 200 for payload in fit_payloads)
        assert all(payload["contextWindowTokens"] == 1_000 for payload in fit_payloads)
        assert all(payload["estimate"] is True for payload in fit_payloads)
        succeeded = [
            record
            for record in records
            if record["event_type"] == "session_compaction"
            and record["payload"]["status"] == "succeeded"
        ]
        assert len(succeeded) == 1
        assert "ORIGINAL_SENTINEL" not in trace_path.read_text()

        stored = _session.load_messages(session_key)
        assert any("S" * 100 in message.content for message in stored)
        assert all("ORIGINAL_SENTINEL" not in message.content for message in stored)
        assert any(message.content == "inspect the diagnostic" for message in stored)
        assert not _session.find_orphaned_tool_messages(stored)
        assert not _session.find_unanswered_tool_calls(stored)

    def test_request_fit_rechecks_an_append_completed_during_the_fit_check(self) -> None:
        _write_meta("fit-refresh-agent")
        session_key = "agent:fit-refresh-agent:default"
        task_message = "CONCURRENT_REVISION " * 600
        original = "ORIGINAL_SUFFIX " * 600
        dispatches = 0
        registry = ToolRegistry()

        def _lookup(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
            nonlocal dispatches
            dispatches += 1
            return ToolOutcome(True, content=original)

        registry.register(
            Tool(
                name="lookup",
                description="Return a large diagnostic result.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class PostReloadAppendBackend:
            context_window_tokens = 1_000
            max_output_tokens = 200

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []
                self.prospectives: list[tuple[str, int]] = []
                self.summary_prompts: list[str] = []
                self.task_transports = 0
                self.injected = False

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    prospective = ("compaction", 700)
                elif any(message.role == "tool" for message in messages):
                    prospective = ("task", 1_220)
                elif (
                    sum(
                        message.role == "user" and message.content == task_message
                        for message in messages
                    )
                    > 1
                ):
                    prospective = ("task", 1_100)
                elif any("SECOND_SUMMARY" in message.content for message in messages):
                    prospective = ("task", 700)
                elif any("FIRST_SUMMARY" in message.content for message in messages):
                    if not self.injected:
                        self.injected = True
                        _session.append_messages(
                            session_key,
                            [
                                ChatMessage(
                                    role="user",
                                    content=task_message,
                                    name="concurrent-copy",
                                )
                            ],
                        )
                    prospective = ("task", 700)
                else:
                    prospective = ("task", 200)
                self.prospectives.append(prospective)
                return prospective[1]

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
                self.tools_seen.append(list(tools))
                if tools:
                    self.task_transports += 1
                    if self.task_transports == 1:
                        call = ToolCall(id="lookup-1", name="lookup", arguments="{}")
                        return ChatResponse(
                            ok=True,
                            message=assistant("", tool_calls=[call]),
                            finish_reason="tool_calls",
                            usage=TokenUsage(10, 5),
                        )
                    fresh = any("SECOND_SUMMARY" in message.content for message in messages)
                    return _final_response(
                        "fresh revision transported" if fresh else "stale revision transported",
                        TokenUsage(10, 5),
                    )
                prompt = messages[0].content
                self.summary_prompts.append(prompt)
                assert "compacting durable turn history" in prompt
                if "CONCURRENT_REVISION" in prompt:
                    assert "FIRST_SUMMARY" not in prompt
                    assert "ORIGINAL_SUFFIX" not in prompt
                    return _final_response("SECOND_SUMMARY " + "N" * 400, TokenUsage(10, 5))
                assert "ORIGINAL_SUFFIX" in prompt
                return _final_response("FIRST_SUMMARY " + "S" * 1_000, TokenUsage(10, 5))

        backend = PostReloadAppendBackend()
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=lambda: registry,
            mcp_loader=lambda registry, role: [],
        )

        result = driver.run_turn("fit-refresh-agent", session_key, task_message, 60)

        assert result.ok
        assert result.output == "fresh revision transported"
        assert backend.injected
        assert dispatches == 1
        assert [bool(tools) for tools in backend.tools_seen] == [True, False, False, True]
        assert backend.prospectives == [
            ("task", 200),
            ("task", 1_220),
            ("compaction", 700),
            ("task", 700),
            ("task", 1_100),
            ("compaction", 700),
            ("task", 700),
        ]
        assert len(backend.summary_prompts) == 2
        assert "FIRST_SUMMARY" not in backend.summary_prompts[1]
        assert "ORIGINAL_SUFFIX" not in backend.summary_prompts[1]

        final_task = backend.calls[-1]
        assert any("FIRST_SUMMARY" in message.content for message in final_task)
        assert any("SECOND_SUMMARY" in message.content for message in final_task)
        assert all("ORIGINAL_SUFFIX" not in message.content for message in final_task)
        final_tasks = [
            message
            for message in final_task
            if message.role == "user" and message.content == task_message
        ]
        assert len(final_tasks) == 1
        assert final_tasks[0].name == ""

        stored = load_session(session_key)
        assert stored.usage.input_tokens == 40
        assert stored.usage.output_tokens == 20
        assert stored.usage.turns == 4
        assert any("FIRST_SUMMARY" in message.content for message in stored.messages)
        assert any("SECOND_SUMMARY" in message.content for message in stored.messages)
        assert all("ORIGINAL_SUFFIX" not in message.content for message in stored.messages)
        stored_tasks = [
            message
            for message in stored.messages
            if message.role == "user" and message.content == task_message
        ]
        assert len(stored_tasks) == 1
        assert stored_tasks[0].name == ""
        assert not _session.find_orphaned_tool_messages(stored.messages)
        assert not _session.find_unanswered_tool_calls(stored.messages)

        trace_path = _cfg.TRACES_DIR / "fit-refresh-agent" / f"{session_key}.jsonl"
        records = [json.loads(line) for line in trace_path.read_text().splitlines()]
        fit_payloads = [
            record["payload"] for record in records if record["event_type"] == "request_fit"
        ]
        expected_fit_keys = {
            "purpose",
            "status",
            "estimatedInputTokens",
            "outputReserveTokens",
            "contextWindowTokens",
            "estimate",
        }
        assert all(set(payload) == expected_fit_keys for payload in fit_payloads)
        assert "ORIGINAL_SUFFIX" not in trace_path.read_text()
        assert "CONCURRENT_REVISION" not in trace_path.read_text()

    def test_request_fit_may_compact_suffix_then_an_independent_prefix(self) -> None:
        _write_meta("two-segment-agent")
        session_key = "agent:two-segment-agent:default"
        prefix_drop = "PREFIX_DROP_SENTINEL " * 250
        prefix_anchor = "PREFIX_ANCHOR " * 250
        suffix = "SUFFIX_SENTINEL " * 500
        _session.append_messages(
            session_key,
            [
                ChatMessage(role="user", content=prefix_drop),
                ChatMessage(role="user", content=prefix_anchor),
            ],
        )
        dispatches = 0
        registry = ToolRegistry()

        def _lookup(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
            nonlocal dispatches
            dispatches += 1
            return ToolOutcome(True, content=suffix)

        registry.register(
            Tool(
                name="lookup",
                description="Return another large diagnostic result.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class TwoSegmentBackend:
            context_window_tokens = 1_000
            max_output_tokens = 200

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []
                self.prospectives: list[tuple[str, int]] = []
                self.task_transports = 0

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    prospective = ("compaction", 700)
                elif any(message.role == "tool" for message in messages):
                    prospective = ("task", 1_220)
                elif any("SUFFIX_SUMMARY" in message.content for message in messages) and any(
                    "PREFIX_DROP_SENTINEL" in message.content for message in messages
                ):
                    prospective = ("task", 1_100)
                elif any("PREFIX_SUMMARY" in message.content for message in messages):
                    prospective = ("task", 700)
                else:
                    prospective = ("task", 200)
                self.prospectives.append(prospective)
                return prospective[1]

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
                self.tools_seen.append(list(tools))
                if tools:
                    self.task_transports += 1
                    if self.task_transports == 1:
                        call = ToolCall(id="lookup-1", name="lookup", arguments="{}")
                        return ChatResponse(
                            ok=True,
                            message=assistant("", tool_calls=[call]),
                            finish_reason="tool_calls",
                            usage=TokenUsage(10, 5),
                        )
                    return _final_response("done", TokenUsage(10, 5))
                prompt = messages[0].content
                assert "compacting durable turn history" in prompt
                if "SUFFIX_SENTINEL" in prompt:
                    return _final_response("SUFFIX_SUMMARY " + "S" * 1_500)
                assert "PREFIX_DROP_SENTINEL" in prompt
                return _final_response("PREFIX_SUMMARY " + "P" * 500)

        backend = TwoSegmentBackend()
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=lambda: registry,
            mcp_loader=lambda registry, role: [],
        )

        result = driver.run_turn("two-segment-agent", session_key, "inspect both segments", 60)

        assert result.ok
        assert result.output == "done"
        assert dispatches == 1
        assert [bool(tools) for tools in backend.tools_seen] == [True, False, False, True]
        assert backend.prospectives == [
            ("task", 200),
            ("task", 1_220),
            ("compaction", 700),
            ("task", 1_100),
            ("compaction", 700),
            ("task", 700),
        ]
        records = [
            json.loads(line)
            for line in (_cfg.TRACES_DIR / "two-segment-agent" / f"{session_key}.jsonl")
            .read_text()
            .splitlines()
        ]
        succeeded = [
            record
            for record in records
            if record["event_type"] == "session_compaction"
            and record["payload"]["status"] == "succeeded"
        ]
        assert len(succeeded) == 2
        stored = _session.load_messages(session_key)
        assert all("PREFIX_DROP_SENTINEL" not in message.content for message in stored)
        assert all("SUFFIX_SENTINEL" not in message.content for message in stored)
        assert any("PREFIX_ANCHOR" in message.content for message in stored)
        assert any("PREFIX_SUMMARY" in message.content for message in stored)
        assert any("SUFFIX_SUMMARY" in message.content for message in stored)
        assert not _session.find_orphaned_tool_messages(stored)
        assert not _session.find_unanswered_tool_calls(stored)

    def test_happy_path_final_message_costs_nothing(self) -> None:
        _write_meta("solo-agent")
        backend = _ScriptedBackend([_final_response("hello there", TokenUsage(12, 4))])
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "hi", 60)

        assert result.ok is True
        assert result.output == "hello there"
        assert result.cost_usd == 0.0
        assert result.error == ""
        assert result.failure_kind is None

    def test_runtime_prompt_projects_startup_state_without_private_file_commands(
        self, tmp_path: Path
    ) -> None:
        codebase = tmp_path / "runtime-project"
        codebase.mkdir()
        ws = _write_meta(
            "runtime-prompt-agent",
            role="tester",
            codebase=str(codebase),
        )
        (ws / "SOUL.md").write_text("# SOUL\nTESTER-ROLE-RULE\n", encoding="utf-8")
        _memory.seed_contract(ws, project="runtime-project", codebase=str(codebase))
        (ws / "AGENTS.md").write_text(
            "# AGENTS\n\n"
            "## Session Startup\n"
            "LEGACY-OPEN-PRIVATE\n\n"
            "## Red Lines\n"
            "SAFE-RED-LINE\n\n"
            "## Custom Operator Rules\n"
            "CUSTOM-RUNTIME-RULE\n",
            encoding="utf-8",
        )
        (ws / "HEARTBEAT.md").write_text(
            _memory.heartbeat_seed("runtime-prompt-agent").replace(
                "_none yet_", "CURRENT-ACTIVE-STATE"
            ),
            encoding="utf-8",
        )
        (ws / "TOOLS.md").write_text("README-VALIDATION-RULE\n", encoding="utf-8")
        (ws / "MEMORY.md").write_text("CURRENT-DURABLE-DECISION\n", encoding="utf-8")
        source_bytes = {
            path.name: path.read_bytes()
            for path in (
                ws / "WORKFLOW_AUTO.md",
                ws / "AGENTS.md",
                ws / "HEARTBEAT.md",
                ws / "TOOLS.md",
                ws / "MEMORY.md",
            )
        }
        backend = _ScriptedBackend([_final_response("PASS")])

        result = DocketDriver(backend_factory=lambda model: backend).run_turn(
            "runtime-prompt-agent",
            "agent:runtime-prompt-agent:default",
            "validate the repaired behavior",
            60,
        )

        assert result.ok is True
        system = backend.calls[0][0]
        assert system.role == "system"
        assert str(codebase) in system.content
        assert "TESTER-ROLE-RULE" in system.content
        assert "CURRENT-ACTIVE-STATE" in system.content
        assert "SAFE-RED-LINE" in system.content
        assert "CUSTOM-RUNTIME-RULE" in system.content
        assert "README-VALIDATION-RULE" in system.content
        assert "CURRENT-DURABLE-DECISION" in system.content
        assert "LEGACY-OPEN-PRIVATE" not in system.content
        assert "open `HEARTBEAT.md`" not in system.content
        assert "write it to `HEARTBEAT.md`" not in system.content
        assert "`MEMORY.md` — what this project" not in system.content
        assert "Read it first every session" not in system.content
        assert "record it here" not in system.content
        assert system.content.count("Never access Docket private control files") == 1
        assert {
            path.name: path.read_bytes()
            for path in (
                ws / "WORKFLOW_AUTO.md",
                ws / "AGENTS.md",
                ws / "HEARTBEAT.md",
                ws / "TOOLS.md",
                ws / "MEMORY.md",
            )
        } == source_bytes
        stored = load_session("agent:runtime-prompt-agent:default")
        assert all(message.role != "system" for message in stored.messages)
        assert not any("CURRENT-DURABLE-DECISION" in message.content for message in stored.messages)

    def test_missing_meta_fails_without_raising(self) -> None:
        driver = DocketDriver(backend_factory=_never_called)

        result = driver.run_turn("ghost-agent", "agent:ghost-agent:default", "hi", 60)

        assert result.ok is False
        assert result.failure_kind == "invalid_output"
        assert "ghost-agent" in result.error

    def test_unresolvable_model_reports_daemon_error(self) -> None:
        _write_meta("solo-agent", model="nowhere/model")
        driver = DocketDriver(backend_factory=lambda model: None)

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "hi", 60)

        assert result.ok is False
        assert result.failure_kind == "daemon_error"
        assert "nowhere/model" in result.error

    def test_a_real_tool_call_executes_end_to_end_through_the_gate(self) -> None:
        ws = _write_meta("reader-agent")
        (ws / "notes.txt").write_text("top secret\n")
        backend = _ScriptedBackend(
            [_read_call_response("notes.txt"), _final_response("here it is")]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn("reader-agent", "agent:reader-agent:default", "read notes.txt", 60)

        assert result.ok is True
        assert result.output == "here it is"
        assert result.cost_usd == 0.0
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert "top secret" in tool_msg.content

    def test_default_driver_stops_after_three_explicit_tool_approval_denials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_meta("denial-agent")
        _store.write_json(
            _cfg.POLICIES_DIR / "approve-validation.json",
            {
                "id": "approve-validation",
                "description": "require an operator for validation",
                "applies_to": ["*"],
                "hook": "pre_tool_call",
                "match": {"type": "regex", "pattern": "^validate\\b"},
                "action": "require_approval",
                "message": "operator validation required",
            },
        )
        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 10, raising=True)

        def deny_pending(_seconds: float) -> None:
            pending = _approval.list_pending()
            assert len(pending) == 1
            _approval.approval_deny(str(pending[0]["token"]))

        monkeypatch.setattr(
            _approval,
            "_time",
            types.SimpleNamespace(sleep=deny_pending, monotonic=_time.monotonic),
            raising=True,
        )
        handler_calls: list[str] = []
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="validate",
                description="operator-gated validation",
                parameters={"type": "object", "properties": {}},
                handler=lambda args, ctx: (
                    handler_calls.append("executed") or ToolOutcome(ok=True, content="ran")
                ),
                kind="read",
            )
        )
        responses = [
            ChatResponse(
                ok=True,
                message=assistant(
                    "",
                    tool_calls=[ToolCall(id=f"deny-{index}", name="validate", arguments="{}")],
                ),
                finish_reason="tool_calls",
                usage=TokenUsage(10, 5),
            )
            for index in range(1, 4)
        ]
        responses.append(_final_response("must not be requested"))
        backend = _ScriptedBackend(responses)
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=lambda: registry,
        )
        session_key = "agent:denial-agent:default"

        result = driver.run_turn(
            "denial-agent",
            session_key,
            "validate without bypassing approval",
            60,
            trace_project="denial-project",
        )

        assert result.ok is False
        assert result.failure_kind == "invalid_output"
        assert "count=3" in result.error
        assert "approval_denied,approval_denied,approval_denied" in result.error
        assert len(backend.calls) == 3
        assert handler_calls == []
        record = load_session(session_key)
        assert [message.role for message in record.messages] == [
            "user",
            "assistant",
            "tool",
            "assistant",
            "tool",
            "assistant",
            "tool",
        ]
        assert record.usage.input_tokens + record.usage.output_tokens == 45
        approval_states = [
            json.loads(path.read_text(encoding="utf-8"))["state"]
            for path in _cfg.APPROVALS_DIR.glob("*.json")
        ]
        assert approval_states == ["denied", "denied", "denied"]
        trace_path = _cfg.TRACES_DIR / "denial-project" / f"{session_key}.jsonl"
        denial_kinds = [
            json.loads(line)["payload"].get("denialKind")
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event_type"] == "tool_result"
        ]
        assert denial_kinds == ["approval_denied", "approval_denied", "approval_denied"]

    def test_env_flows_into_the_tool_context(self) -> None:
        # "env" (not "echo") is on core.security.SAFE_BINS' curated allowlist,
        # so this runs unattended instead of tripping the approval gate.
        _write_meta("env-agent")
        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "env"}))
        backend = _ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
                _final_response("ran it"),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn(
            "env-agent",
            "agent:env-agent:default",
            "run it",
            30,
            env={"DOCKET_TEST_VAR": "hello-from-env"},
        )

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert "DOCKET_TEST_VAR=hello-from-env" in tool_msg.content

    def test_on_spawn_is_accepted_and_ignored(self) -> None:
        """No real OS process backs this driver -- on_spawn must not raise or
        be required, matching the Protocol's own "may simply ignore it"."""
        _write_meta("solo-agent")
        backend = _ScriptedBackend([_final_response("ok")])
        driver = DocketDriver(backend_factory=lambda model: backend)
        spawned: list[int] = []

        result = driver.run_turn(
            "solo-agent", "agent:solo-agent:default", "hi", 30, on_spawn=spawned.append
        )

        assert result.ok is True
        assert spawned == []


# ── root resolution precedence ───────────────────────────────────────────────


def _tool_reply(backend: _ScriptedBackend) -> str:
    return next(m for m in backend.calls[1] if m.role == "tool").content


class TestRootResolutionPrecedence:
    """worktree > codebase > work_dir > bare workspace dir. Each case proven
    with the real `read` tool against a distinctly-labelled marker file, not
    by inspecting `_resolve_roots`'s logic directly."""

    def test_bare_workspace_is_the_base_fallback(self) -> None:
        ws = _write_meta("prec-a")
        (ws / "marker.txt").write_text("workspace")
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])
        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "prec-a", "agent:prec-a:default", "go", 30
        )
        assert _tool_reply(backend) == "workspace"

    def test_work_dir_wins_over_bare_workspace(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "marker.txt").write_text("workdir")
        _write_meta("prec-b", workDir=str(work_dir))
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])
        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "prec-b", "agent:prec-b:default", "go", 30
        )
        assert _tool_reply(backend) == "workdir"

    def test_codebase_wins_over_work_dir(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "work2"
        work_dir.mkdir()
        (work_dir / "marker.txt").write_text("workdir2")
        codebase = tmp_path / "code"
        codebase.mkdir()
        (codebase / "marker.txt").write_text("codebase")
        _write_meta("prec-c", workDir=str(work_dir), codebase=str(codebase))
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])
        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "prec-c", "agent:prec-c:default", "go", 30
        )
        assert _tool_reply(backend) == "codebase"

    def test_worktree_wins_over_codebase(self, tmp_path: Path) -> None:
        codebase = tmp_path / "code2"
        codebase.mkdir()
        (codebase / "marker.txt").write_text("codebase2")
        worktree = tmp_path / "wt"
        worktree.mkdir()
        (worktree / "marker.txt").write_text("worktree")
        _write_meta("prec-d", codebase=str(codebase), worktreeDir=str(worktree))
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])
        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "prec-d", "agent:prec-d:default", "go", 30
        )
        assert _tool_reply(backend) == "worktree"

    def test_registered_same_pod_worktree_wins_for_reviewer(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        origin.mkdir()
        (origin / "marker.txt").write_text("origin")
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "marker.txt").write_text("implementation")
        _write_meta(
            "demo-implementer",
            role="implementer",
            codebase=str(origin),
            worktreeDir=str(worktree),
        )
        _write_meta("demo-reviewer", role="reviewer", codebase=str(origin))
        _fleet.add_agent("demo-implementer", "test/model", "agent:demo:default", "default")
        _fleet.add_agent("demo-reviewer", "test/model", "agent:demo:default", "default")
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])

        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "demo-reviewer",
            "agent:demo-reviewer:default",
            "go",
            30,
            {PIPELINE_WORKTREE_ENV: str(worktree)},
        )

        assert _tool_reply(backend) == "implementation"


# ── provision / teardown / capabilities ──────────────────────────────────────


class TestProvisionTeardownCapabilities:
    def test_provision_is_an_honest_noop(self) -> None:
        result = DocketDriver().provision("some-agent", "/tmp/ws", "test/model")
        assert result.ok is True
        assert "no daemon" in result.message

    def test_teardown_is_an_honest_noop(self) -> None:
        result = DocketDriver().teardown("some-agent")
        assert result.ok is True
        assert "no daemon" in result.message

    def test_capabilities_reports_this_driver_honestly(self) -> None:
        caps = DocketDriver().capabilities()
        assert caps.driver_name == "docket"
        # cost_usd is never populated by this driver -- see run_turn/usage.
        assert caps.reports_cost_usd is False
        # Provision/teardown are no-ops because Docket owns its local state.
        assert caps.supports_provisioning is False
        # list_sessions/read_new_turns/usage are real, unlike a driver with
        # no durable store at all.
        assert caps.supports_sessions is True


# ── list_sessions / read_new_turns / usage ───────────────────────────────────


class TestSessionIntrospection:
    def test_reflect_a_real_turn_with_a_tool_call(self) -> None:
        ws = _write_meta("chat-agent")
        (ws / "x.txt").write_text("hi\n")
        session_key = "agent:chat-agent:default"
        backend = _ScriptedBackend(
            [
                _read_call_response("x.txt", TokenUsage(10, 5)),
                _final_response("done", TokenUsage(6, 2)),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)
        driver.run_turn("chat-agent", session_key, "go", 60)

        sessions = driver.list_sessions("chat-agent")
        assert len(sessions) == 1
        assert sessions[0].session_id == session_key
        assert sessions[0].turns == 4  # user, assistant(tool_calls), tool, assistant(final)

        first_slice = driver.read_new_turns("chat-agent", session_key, 0)
        assert first_slice.had_new_content is True
        assert [t.kind for t in first_slice.turns] == ["other", "tool_call", "tool_result", "other"]
        assert first_slice.next_offset == 4
        assert first_slice.session_start_ts != ""

        second_slice = driver.read_new_turns("chat-agent", session_key, first_slice.next_offset)
        assert second_slice.had_new_content is False

        report = driver.usage("chat-agent")
        assert report.totals.input_tokens == 16
        assert report.totals.output_tokens == 7
        assert report.totals.cost_usd == 0.0
        assert report.by_day == []

    def test_list_sessions_is_scoped_to_the_agent_id_prefix(self) -> None:
        _write_meta("agent-a")
        _write_meta("agent-b")
        DocketDriver(
            backend_factory=lambda model: _ScriptedBackend([_final_response("a")])
        ).run_turn("agent-a", "agent:agent-a:default", "hi", 30)
        DocketDriver(
            backend_factory=lambda model: _ScriptedBackend([_final_response("b")])
        ).run_turn("agent-b", "agent:agent-b:default", "hi", 30)

        sessions_a = DocketDriver().list_sessions("agent-a")
        assert [s.session_id for s in sessions_a] == ["agent:agent-a:default"]

    def test_no_sessions_directory_yet_returns_empty(self) -> None:
        assert DocketDriver().list_sessions("nobody") == []

    def test_read_new_turns_on_an_unknown_session_is_a_no_op_slice(self) -> None:
        sl = DocketDriver().read_new_turns("nobody", "agent:nobody:default", 0)
        assert sl.had_new_content is False
        assert sl.turns == []


# ── isolation wiring (W18-3) ──────────────────────────────────────────────────


def _probe_registry() -> ToolRegistry:
    """A one-tool registry that reports back the exact `ctx.sandbox` value
    `run_turn` built, so a test can observe it without hand-constructing a
    `ToolContext` itself -- the real construction path is the thing under
    test."""
    registry = ToolRegistry()

    def _probe(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(True, content=f"sandbox={ctx.sandbox}")

    registry.register(
        Tool(
            name="probe",
            description="reports ctx.sandbox",
            parameters={"type": "object", "properties": {}},
            handler=_probe,
            kind="read",
        )
    )
    return registry


def _probe_call_response() -> ChatResponse:
    call = ToolCall(id="c1", name="probe", arguments="{}")
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


class TestIsolationWiring:
    """`docket gates isolate on` writes `security.isolationEnabled` to
    fleet.json -- before this wire, nothing on the real turn path ever read
    it back, so isolation ON was silently indistinguishable from isolation
    OFF on every live turn (the reproduction this card was opened against).
    `DocketDriver.run_turn` now resolves it via `_resolve_sandbox`.
    """

    def test_isolation_off_leaves_ctx_sandbox_off(self) -> None:
        # No fleet.json write at all -- the default, overwhelmingly common
        # path (`get_isolation_enabled()` on a missing fleet.json resolves to
        # False). This is the "off stays byte-identical" proof: the
        # `ToolContext` a real turn builds today carries `sandbox="off"`.
        _write_meta("solo-agent")
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_probe_registry
        )

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "sandbox=off"

    def test_isolation_on_with_backend_available_sets_sandbox_auto(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_meta("solo-agent")
        monkeypatch.setattr(
            _system,
            "sandbox_availability",
            lambda: SandboxAvailability(backend="docker", docker=True, bwrap=False),
        )
        _fleet.set_isolation_enabled(True)
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_probe_registry
        )

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "sandbox=auto"

    def test_isolation_on_no_backend_refuses_the_turn_rather_than_running_unsandboxed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The failure mode this card exists to end: isolation is ON but
        # neither docker nor bwrap is usable. The turn must refuse outright
        # -- not silently downgrade to an unsandboxed run -- and the LLM
        # backend must never even be reached (`_never_called` fails the test
        # if it is).
        _write_meta("solo-agent")
        monkeypatch.setattr(
            _system,
            "sandbox_availability",
            lambda: SandboxAvailability(backend="none", docker=False, bwrap=False),
        )
        _fleet.set_isolation_enabled(True)
        driver = DocketDriver(backend_factory=_never_called)

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is False
        assert result.failure_kind == "daemon_error"
        assert "docker" in result.error.lower()
        assert "bwrap" in result.error.lower()

        refusals = [e for e in read_audit() if e["action"] == "isolation.refused"]
        assert len(refusals) == 1
        assert "agent=solo-agent" in refusals[0]["detail"]
        assert "docker=False" in refusals[0]["detail"]
        assert "bwrap=False" in refusals[0]["detail"]

    def test_docket_sandbox_backend_override_still_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Both real backends report usable, but the operator's own override
        # forces "none" -- this wire adds no parallel backend-selection
        # mechanism, it only gates in front of the existing one
        # (`system.sandbox_availability`), so the override must still be the
        # last word, exactly as it already is for `toolbox.run_bash`.
        _write_meta("solo-agent")
        monkeypatch.setattr(_system, "docker_daemon_reachable", lambda: True)
        monkeypatch.setattr(_system, "bwrap_available", lambda: True)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        _fleet.set_isolation_enabled(True)
        driver = DocketDriver(backend_factory=_never_called)

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is False
        assert result.failure_kind == "daemon_error"

    def test_the_flag_docket_gates_isolate_on_writes_is_the_one_the_turn_reads(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # End-to-end through fleet: drive the real `docket gates isolate on`
        # CLI path (not `set_isolation_enabled` directly, and not a
        # hand-built `ToolContext`), then confirm a real turn observes
        # exactly the flag it wrote.
        _write_meta("solo-agent")
        monkeypatch.setattr(_gates.shutil, "which", lambda name, *a, **k: "/usr/bin/docker")
        monkeypatch.setattr(
            _system,
            "sandbox_availability",
            lambda: SandboxAvailability(backend="bwrap", docker=False, bwrap=True),
        )
        rc = _gates.run_gates("isolate", want="on")
        capsys.readouterr()
        assert rc == 0

        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_probe_registry
        )
        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "sandbox=auto"
