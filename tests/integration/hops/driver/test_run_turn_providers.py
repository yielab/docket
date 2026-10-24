"""DocketDriver.run_turn: providers, model overrides, limits and the surfaces the driver reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.driver_harness import (
    _final_response,
    _read_call_response,
    _ScriptedBackend,
)
from tests.support.home import record_isolation_off
from tests.support.pods import write_meta_2 as _write_meta

from docket.agent.ports import (
    PIPELINE_WORKTREE_ENV,
    TokenUsage,
)
from docket.governance import secrets as _secrets
from docket.hops.application import driver as _docket_runtime
from docket.hops.application.driver import DocketDriver
from docket.interfaces.cli.commands import setup_model_credentials as _setup_model_credentials
from docket.kernel.home import Home, current_home, use_home
from docket.models.adapters import openai_http as _llm_adapter
from docket.models.application import probe as _probe
from docket.platform import store as _store
from docket.teams import fleet as _fleet

SUBJECT = "docket.hops.application.driver"


def _tool_reply(backend: _ScriptedBackend) -> str:
    """The tool message's text, without the leading line number `read` prefixes."""
    return next(m for m in backend.calls[1] if m.role == "tool").content.removeprefix("1\t")


class TestRunTurn:
    def test_owned_run_binds_persisted_cancellation_signal_before_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class RequestedSignal:
            observations = 0

            def observe(self) -> bool:
                self.observations += 1
                return True

        signal = RequestedSignal()
        monkeypatch.setattr(
            _docket_runtime._runs,
            "current_cancellation_signal",
            lambda: signal,
            raising=True,
        )
        _write_meta("cancelled-agent")
        backend = _ScriptedBackend([_final_response("must not be requested")])

        result = DocketDriver(backend_factory=lambda _model: backend).run_turn(
            "cancelled-agent",
            "agent:cancelled-agent:default",
            "go",
            60,
        )

        assert result.ok is False
        assert result.failure_kind == "run_cancelled"
        assert backend.calls == []
        assert signal.observations >= 1

    def test_public_local_provider_setup_reaches_gated_tool_turn_without_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from docket.interfaces.cli.app import app

        with use_home(Home(tmp_path)):
            record_isolation_off(tmp_path)
            monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
            monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
            # Registration probes /models through models/adapters/openai_http.py; answer "reachable, 200".
            monkeypatch.setattr(
                _llm_adapter, "probe_models", lambda *a, **k: _probe.ProbeResult(status=200)
            )

            runner = CliRunner()
            registered = runner.invoke(
                app,
                [
                    "setup",
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
            selected = runner.invoke(app, ["setup", "model", "preset", "local"])
            assert selected.exit_code == 0, selected.output

            ws = _write_meta("local-agent", model="local/qwen-live-id")
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

            monkeypatch.setattr(_llm_adapter, "open_same_origin", fake_urlopen)

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
        with use_home(Home(tmp_path)):
            assert _setup_model_credentials._write_credential(provider_key, secret, "add")
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

            monkeypatch.setattr(_llm_adapter, "open_same_origin", fake_urlopen)

            result = DocketDriver().run_turn(
                "gateway-agent",
                "agent:gateway-agent:default",
                "Use the available tools if needed.",
                60,
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
                for path in current_home().traces_dir.rglob("*")
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

    def test_run_turn_model_override_wins_for_this_hop_and_is_never_persisted(self) -> None:
        # A pipeline step's own `model` (pipeline-format.spec.md Steps Req. 10) resolves
        # to a literal model id before it ever reaches this driver (core.dispatch's job);
        # this driver's own contract is just to honor that literal over the member's own
        # meta model for this call, and to never write it back. See
        # pod-dispatch.spec.md "Per-hop execution" requirement 5.
        ws = _write_meta("model-override-agent", model="test/meta-model")
        backend = _ScriptedBackend([_final_response("done")])
        seen_models: list[str] = []

        def _factory(model: str) -> _ScriptedBackend:
            seen_models.append(model)
            return backend

        result = DocketDriver(backend_factory=_factory).run_turn(
            "model-override-agent",
            "agent:model-override-agent:default",
            "go",
            60,
            model="anthropic/claude-opus-4-6",
        )

        assert result.ok
        assert seen_models == ["anthropic/claude-opus-4-6"]
        meta = _store.read_json(current_home().meta_path("model-override-agent"))
        assert meta["model"] == "test/meta-model"
        assert (ws / ".docket-meta.json").exists()


class TestRootResolutionPrecedence:
    """codebase > work_dir > bare workspace dir, with a task worktree root above all. Each case proven
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

    def test_task_worktree_root_wins_over_codebase(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        origin.mkdir()
        (origin / "marker.txt").write_text("origin")
        _write_meta("demo-implementer", role="implementer", codebase=str(origin))
        _fleet.add_agent("demo-implementer")
        task_dir = current_home().projects_dir / "demo-implementer" / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        (task_dir / "marker.txt").write_text("task worktree")
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])

        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "demo-implementer",
            "agent:demo-implementer:default",
            "go",
            30,
            {PIPELINE_WORKTREE_ENV: str(task_dir)},
        )

        assert _tool_reply(backend) == "task worktree"

    def test_task_worktree_root_wins_for_reviewer(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        origin.mkdir()
        (origin / "marker.txt").write_text("origin")
        _write_meta("demo-implementer", role="implementer", codebase=str(origin))
        _write_meta("demo-reviewer", role="reviewer", codebase=str(origin))
        _fleet.add_agent("demo-implementer")
        _fleet.add_agent("demo-reviewer")
        task_dir = current_home().projects_dir / "demo-implementer" / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        (task_dir / "marker.txt").write_text("implementation")
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])

        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "demo-reviewer",
            "agent:demo-reviewer:default",
            "go",
            30,
            {PIPELINE_WORKTREE_ENV: str(task_dir)},
        )

        assert _tool_reply(backend) == "implementation"

    def test_pipeline_root_outside_every_tasks_dir_is_ignored(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        origin.mkdir()
        (origin / "marker.txt").write_text("origin")
        stray = tmp_path / "stray"
        stray.mkdir()
        (stray / "marker.txt").write_text("stray")
        _write_meta("demo-implementer", role="implementer", codebase=str(origin))
        _fleet.add_agent("demo-implementer")
        backend = _ScriptedBackend([_read_call_response("marker.txt"), _final_response("ok")])

        DocketDriver(backend_factory=lambda model: backend).run_turn(
            "demo-implementer",
            "agent:demo-implementer:default",
            "go",
            30,
            {PIPELINE_WORKTREE_ENV: str(stray)},
        )

        assert _tool_reply(backend) == "origin"


class TestCapabilities:
    def test_capabilities_reports_this_driver_honestly(self) -> None:
        caps = DocketDriver().capabilities()
        assert caps.driver_name == "docket"
        # cost_usd is never populated by this driver -- see run_turn/usage.
        assert caps.reports_cost_usd is False
        # list_sessions/usage are real, unlike a driver with
        # no durable store at all.
        assert caps.supports_sessions is True


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
