"""Artifact-installed RED contract for W28-C2's OpenHands SDK adapter."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest

from tests.fixtures.runtime_adapters.scenarios import (
    FINAL_SUMMARY,
    SCENARIOS,
    GovernanceScenario,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "packages" / "docket-runtime"
FIXTURE = ROOT / "tests" / "fixtures" / "runtime_adapters" / "openhands"


@dataclass(frozen=True)
class OpenHandsArtifacts:
    wheel_python: Path
    sdist_python: Path


def _run(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=True)


@pytest.fixture(scope="module")
def openhands_artifacts(tmp_path_factory: pytest.TempPathFactory) -> OpenHandsArtifacts:
    base = tmp_path_factory.mktemp("w28-c2-openhands-artifacts")
    dist = base / "dist"
    build_tmp = base / "build-tmp"
    build_tmp.mkdir()
    env = {
        **os.environ,
        "DOCKET_RUNTIME_BUILD_TMPDIR": str(build_tmp),
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(base / "uv-cache")),
        "PYTHONPATH": "",
    }
    _run("uv", "build", "--out-dir", str(dist), cwd=RUNTIME, env=env)
    wheel = next(dist.glob("docket_runtime-*.whl"))
    sdist = next(dist.glob("docket_runtime-*.tar.gz"))

    pythons: list[Path] = []
    for name, artifact in (("wheel", wheel), ("sdist", sdist)):
        venv = base / name
        fixture_env = {**env, "UV_PROJECT_ENVIRONMENT": str(venv)}
        _run("uv", "sync", "--frozen", "--no-dev", cwd=FIXTURE, env=fixture_env)
        python = venv / "bin" / "python"
        _run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(artifact),
            cwd=base,
            env=fixture_env,
        )
        pythons.append(python)

    assert not list(build_tmp.glob("docket-runtime-build-*"))
    return OpenHandsArtifacts(wheel_python=pythons[0], sdist_python=pythons[1])


_EXTERNAL_CONSUMER = r"""
import importlib.metadata
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from openhands.sdk import Agent, AgentContext, Conversation, LLM

mode = os.environ["W28_MODE"]
scenario = json.loads(os.environ.get("W28_SCENARIO", "{}"))
workspace = Path(os.environ["W28_WORKSPACE"])
workspace.mkdir(parents=True, exist_ok=True)
state = workspace / "state.txt"
state.write_text("initial", encoding="utf-8")


class ScriptedHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length))
        self.__class__.requests.append({"path": self.path, "body": request})
        index = len(self.__class__.requests)
        if mode == "probe" or index > 1:
            message = {"role": "assistant", "content": os.environ["W28_FINAL_SUMMARY"]}
            usage = {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
            finish_reason = "stop"
        else:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"call-{scenario['name']}",
                    "type": "function",
                    "function": {
                        "name": scenario["tool_name"],
                        "arguments": scenario["arguments"],
                    },
                }],
            }
            usage = {
                "prompt_tokens": scenario["usage"]["input_tokens"],
                "completion_tokens": scenario["usage"]["output_tokens"],
                "total_tokens": (
                    scenario["usage"]["input_tokens"]
                    + scenario["usage"]["output_tokens"]
                ),
                "prompt_tokens_details": {
                    "cached_tokens": scenario["usage"]["cached_tokens"]
                },
            }
            finish_reason = "tool_calls"
        payload = {
            "id": f"response-{mode}-{index}",
            "object": "chat.completion",
            "created": 1_788_220_800,
            "model": "gpt-4o-mini",
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": usage,
        }
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedHandler)
port = server.server_address[1]
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()
llm = LLM(
    model="openai/gpt-4o-mini",
    api_key="fixture-not-a-secret",
    base_url=f"http://127.0.0.1:{port}/v1",
    num_retries=0,
    timeout=5,
)

try:
    if mode == "probe":
        agent = Agent(
            llm=llm,
            tools=[],
            include_default_tools=[],
            mcp_config={},
            security_policy_filename="",
            agent_context=AgentContext(
                skills=[],
                load_user_skills=False,
                load_public_skills=False,
                load_project_skills=False,
                load_memory=False,
                marketplace_path=None,
            ),
            tool_concurrency_limit=1,
            system_prompt="Return the scripted fixture response.",
        )
        conversation = Conversation(
            agent=agent,
            workspace=workspace,
            plugins=[],
            persistence_dir=Path(os.environ["W28_OPENHANDS_HOME"]),
            max_iteration_per_run=2,
            stuck_detection=False,
            visualizer=None,
        )
        try:
            conversation.send_message("probe")
            conversation.run()
            assert agent.tools_map == {}
            assert len(ScriptedHandler.requests) == 1
            usage = llm.metrics.token_usages[-1]
            assert (usage.prompt_tokens, usage.completion_tokens) == (2, 1)
        finally:
            conversation.close()
        output = {"port": port, "requests": len(ScriptedHandler.requests)}
    else:
        from docket_runtime import ExecutionLimits, Runtime, Tool, ToolContext, ToolOutcome
        from docket_runtime.adapters.openhands import OpenHandsAdapter
        from docket_runtime._internal.docket.core.audit import verify_chain

        home = Path(os.environ["DOCKET_HOME"])
        if scenario["policy"] != "none":
            policies = home / "policies"
            policies.mkdir(parents=True, exist_ok=True)
            (policies / "scenario.json").write_text(json.dumps({
                "id": f"w28-{scenario['name']}",
                "applies_to": ["*"],
                "hook": "pre_tool_call",
                "match": {"type": "regex", "pattern": "mutate_state"},
                "action": scenario["policy"],
                "message": f"fixture {scenario['policy']}",
            }), encoding="utf-8")

        handler_calls = []
        mutations = []

        def read_state(args, context):
            handler_calls.append("read_state")
            return ToolOutcome(True, state.read_text(encoding="utf-8"))

        def mutate_state(args, context):
            handler_calls.append("mutate_state")
            mutations.append(args["value"])
            state.write_text(args["value"], encoding="utf-8")
            return ToolOutcome(True, args["value"])

        runtime = Runtime(
            approval_stub=(
                None
                if scenario["approval_response"] is None
                else lambda token: scenario["approval_response"]
            )
        )
        runtime.register(Tool("read_state", "read fixture state", {"type": "object"}, read_state))
        runtime.register(Tool(
            "mutate_state",
            "mutate fixture state",
            {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            mutate_state,
            kind="write",
        ))
        context = ToolContext(
            agent_id="openhands-fixture",
            session_key=f"w28-{scenario['name']}",
            roots=(workspace,),
            role="implementer",
            project="portable-proof",
        )
        adapter = OpenHandsAdapter(
            runtime=runtime,
            context=context,
            limits=ExecutionLimits(
                token_budget=10 if scenario["expected_stop"] == "token_budget" else 100,
                max_tool_calls=4,
            ),
        )
        terminal = adapter.run(
            llm=llm,
            prompt=f"execute deterministic case {scenario['name']}",
            workspace=workspace,
            persistence_dir=Path(os.environ["W28_OPENHANDS_HOME"]),
        )

        assert set(adapter.agent.tools_map) == {"read_state", "mutate_state"}
        assert adapter.agent.include_default_tools == []
        assert adapter.agent.mcp_config == {}
        assert adapter.agent.security_policy_filename == ""
        assert adapter.agent.tool_concurrency_limit == 1
        assert adapter.agent.agent_context is not None
        assert adapter.agent.agent_context.skills == []
        assert adapter.agent.agent_context.load_user_skills is False
        assert adapter.agent.agent_context.load_public_skills is False
        assert adapter.agent.agent_context.load_project_skills is False
        assert adapter.agent.agent_context.load_memory is False
        first_tools = ScriptedHandler.requests[0]["body"].get("tools", [])
        requested_names = {
            tool["function"]["name"] for tool in first_tools if tool.get("type") == "function"
        }
        assert requested_names == {"read_state", "mutate_state"}
        assert not requested_names & {"bash", "terminal", "file_editor", "native_bash", "native_file_editor"}
        assert len(mutations) == scenario["expected_mutations"]

        trace_file = home / "traces" / "portable-proof" / f"w28-{scenario['name']}.jsonl"
        trace = (
            [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
            if trace_file.exists()
            else []
        )
        tool_trace = [
            record for record in trace if record["event_type"] in {"tool_call", "tool_result"}
        ]
        dispatched = scenario["tool_name"] in {"read_state", "mutate_state"} and scenario["expected_stop"] != "token_budget"
        assert len(tool_trace) == (2 if dispatched else 0)
        if dispatched:
            assert [record["event_type"] for record in tool_trace] == ["tool_call", "tool_result"]
            assert all(record["agent_role"] == "implementer" for record in tool_trace)
            assert all(
                record["payload"]["callId"] == f"call-{scenario['name']}"
                for record in tool_trace
            )
            expected_decision = scenario["expected_decision"]
            if expected_decision in ("gate_denied", "approval_denied"):
                assert tool_trace[-1]["payload"]["decision"] == "deny"
                assert tool_trace[-1]["payload"]["denialKind"] == expected_decision
            else:
                assert tool_trace[-1]["payload"]["decision"] == expected_decision

        assert terminal.stop_reason == scenario["expected_stop"]
        assert terminal.tool_calls_executed == (1 if dispatched else 0)
        if scenario["expected_stop"] == "token_budget":
            assert terminal.ok is False
            assert terminal.usage.total_tokens == 11
            assert len(ScriptedHandler.requests) == 1
        else:
            assert terminal.ok is True
            assert terminal.output == os.environ["W28_FINAL_SUMMARY"]
            assert terminal.handoff.summary == os.environ["W28_FINAL_SUMMARY"]
            assert terminal.usage.input_tokens == scenario["usage"]["input_tokens"] + 2
            assert terminal.usage.output_tokens == scenario["usage"]["output_tokens"] + 1
            assert len(ScriptedHandler.requests) == 2

        if scenario["expected_mutations"]:
            assert state.read_text(encoding="utf-8") == "approval granted"
        else:
            assert state.read_bytes() == b"initial"
        audit_path = home / "audit.log"
        audit = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""
        if scenario["expected_decision"] == "gate_denied":
            assert "tool.deny" in audit
        elif scenario["expected_decision"] == "approval_denied":
            assert "approval.deny" in audit
        elif scenario["approval_response"] is True:
            assert "approval.grant" in audit

        requirements = importlib.metadata.requires("docket-runtime") or []
        dependency_names = {
            requirement.split(";", 1)[0].split("[", 1)[0].split(">", 1)[0].split("=", 1)[0].strip().lower()
            for requirement in requirements
        }
        assert dependency_names == {"filelock", "pydantic"}
        audit_records = [json.loads(line) for line in audit.splitlines() if line.strip()]
        verification = verify_chain()
        normalized_trace = [
            {
                "event_type": record["event_type"],
                "project": record["project"],
                "session_id": "<scenario>",
                "agent_role": record["agent_role"],
                "payload": record["payload"],
            }
            for record in tool_trace
        ]
        output = {
            "port": port,
            "requests": len(ScriptedHandler.requests),
            "stop_reason": terminal.stop_reason,
            "normalized": {
                "advertised_tools": sorted(requested_names),
                "audit_actions": [record["action"] for record in audit_records],
                "audit_chain": {
                    "exists": verification.exists,
                    "lines": verification.total_lines,
                    "chained": verification.chained,
                    "legacy": verification.legacy,
                    "break": (
                        None
                        if verification.break_at is None
                        else {
                            "line": verification.break_at.line,
                            "reason": verification.break_at.reason,
                        }
                    ),
                },
                "handler_calls": handler_calls,
                "state_hex": state.read_bytes().hex(),
                "terminal": {
                    "ok": terminal.ok,
                    "output": terminal.output,
                    "stop_reason": terminal.stop_reason,
                    "usage": {
                        "input_tokens": terminal.usage.input_tokens,
                        "output_tokens": terminal.usage.output_tokens,
                        "cached_tokens": terminal.usage.cached_tokens,
                    },
                    "tool_calls_executed": terminal.tool_calls_executed,
                    "handoff": terminal.handoff.summary,
                    "error": terminal.error,
                },
                "trace": normalized_trace,
            },
        }
finally:
    server.shutdown()
    server.server_close()
    server_thread.join(5)
    assert not server_thread.is_alive()

print("W28_RESULT=" + json.dumps(output, sort_keys=True))
"""


def _invoke(
    python: Path,
    *,
    tmp_path: Path,
    mode: str,
    scenario: dict[str, object] | None = None,
) -> dict[str, object]:
    outside = tmp_path / "outside-checkout"
    outside.mkdir(parents=True)
    env = {
        **os.environ,
        "DOCKET_HOME": str(tmp_path / "docket-home"),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "OPENHANDS_SUPPRESS_BANNER": "1",
        "W28_FINAL_SUMMARY": FINAL_SUMMARY,
        "W28_MODE": mode,
        "W28_OPENHANDS_HOME": str(tmp_path / "openhands-home"),
        "W28_SCENARIO": json.dumps(scenario or {}),
        "W28_WORKSPACE": str(tmp_path / "workspace"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "PYTHONPATH": "",
    }
    result = subprocess.run(
        [str(python), "-c", textwrap.dedent(_EXTERNAL_CONSUMER)],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    line = next(line for line in result.stdout.splitlines() if line.startswith("W28_RESULT="))
    payload = json.loads(line.removeprefix("W28_RESULT="))
    port = int(payload["port"])
    with socket.socket() as probe:
        probe.settimeout(0.1)
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    return payload


def test_pinned_openhands_agent_uses_credential_free_loopback_fixture(
    openhands_artifacts: OpenHandsArtifacts, tmp_path: Path
) -> None:
    payload = _invoke(openhands_artifacts.wheel_python, tmp_path=tmp_path, mode="probe")
    assert payload["requests"] == 1


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_openhands_adapter_matches_shared_governance_scenarios(
    openhands_artifacts: OpenHandsArtifacts,
    tmp_path: Path,
    scenario: GovernanceScenario,
) -> None:
    _invoke(
        openhands_artifacts.wheel_python,
        tmp_path=tmp_path,
        mode="adapter",
        scenario=asdict(scenario),
    )


def test_openhands_adapter_rebuilt_sdist_matches_wheel_outside_checkout(
    openhands_artifacts: OpenHandsArtifacts, tmp_path: Path
) -> None:
    scenario = next(case for case in SCENARIOS if case.name == "approval_granted_mutation")
    payload = _invoke(
        openhands_artifacts.sdist_python,
        tmp_path=tmp_path,
        mode="adapter",
        scenario=asdict(scenario),
    )
    assert payload["stop_reason"] == "final_message"
