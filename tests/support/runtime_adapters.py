"""Out-of-checkout consumer sources the release-lane runtime adapter tests install and run."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import textwrap
from pathlib import Path

from tests.fixtures.runtime_adapters.scenarios import (
    ADVERTISED_TOOLS,
    FINAL_SUMMARY,
    SUBPROCESS_TIMEOUT_S,
    GovernanceScenario,
)

PYDANTIC_AI_VERSION = "2.37.0"


def pydantic_scenario_source(scenario: GovernanceScenario, *, parity: bool = False) -> str:
    approval_stub = (
        "None"
        if scenario.approval_response is None
        else f"lambda token: {scenario.approval_response!r}"
    )
    policy_match = json.loads(scenario.arguments)["value"] if scenario.policy != "none" else ""
    policy_setup = ""
    if scenario.policy != "none":
        policy_setup = f"""
        policies = home.policies_dir
        policies.mkdir(parents=True, exist_ok=True)
        (policies / "scenario.json").write_text(json.dumps({{
            "kind": "policy",
            "name": "pydantic-{scenario.name}",
            "appliesTo": ["*"],
            "on": "toolCall",
            "when": {{"matches": {policy_match!r}}},
            "then": {"block" if scenario.policy == "block" else "ask"!r},
            "message": "fixture {scenario.name}",
        }}), encoding="utf-8")
        """
    call_id = f"call-{scenario.name}" if parity else f"pydantic-{scenario.name}"
    session_key = f"w28-{scenario.name}" if parity else f"pydantic-{scenario.name}"
    final_usage = "RequestUsage(input_tokens=2, output_tokens=1)" if parity else "RequestUsage()"
    finish_call = (
        "toolset.finish(result.output, usage=result.usage)"
        if parity
        else "toolset.finish(result.output)"
    )
    final_input_tokens = scenario.usage.input_tokens + (
        2 if parity and scenario.expected_stop == "final_message" else 0
    )
    final_output_tokens = scenario.usage.output_tokens + (
        1 if parity and scenario.expected_stop == "final_message" else 0
    )
    return textwrap.dedent(
        f"""
        import importlib.metadata
        import json
        import os
        from pathlib import Path

        from docket_runtime import (
            ExecutionLimits,
            HandoffArtifact,
            Runtime,
            TokenUsage,
            Tool,
            ToolContext,
            ToolOutcome,
        )
        from docket_runtime.adapters.pydantic_ai import DocketToolset
        from docket_runtime._internal.docket.governance.audit import verify_chain
        from docket_runtime._internal.docket.kernel.home import Home
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.toolsets import AbstractToolset
        from pydantic_ai.usage import RequestUsage, UsageLimits

        assert importlib.metadata.version("pydantic-ai") == {PYDANTIC_AI_VERSION!r}

        home = Home(Path(os.environ["DOCKET_HOME"]))
        workspace = Path(os.environ["W28_WORKSPACE"])
        workspace.mkdir(parents=True, exist_ok=True)
        state = workspace / "state.txt"
        state.write_text("initial", encoding="utf-8")
        handler_calls = []

        def mutate_state(args, context):
            handler_calls.append(("mutate_state", args["value"]))
            state.write_text(args["value"], encoding="utf-8")
            return ToolOutcome(True, state.read_text(encoding="utf-8"))

        def read_state(args, context):
            handler_calls.append(("read_state", None))
            return ToolOutcome(True, state.read_text(encoding="utf-8"))

        __POLICY_SETUP__
        runtime = Runtime(approval_stub={approval_stub})
        runtime.register(Tool("read_state", "read fixture state", {{"type": "object"}}, read_state))
        runtime.register(
            Tool(
                "mutate_state",
                "mutate fixture state",
                {{
                    "type": "object",
                    "properties": {{"value": {{"type": "string"}}}},
                    "required": ["value"],
                }},
                mutate_state,
                kind="write",
            )
        )
        context = ToolContext(
            agent_id="pydantic-ai",
            session_key={session_key!r},
            roots=(workspace,),
            role="implementer",
            project="portable-proof",
        )
        toolset = DocketToolset(
            runtime=runtime,
            context=context,
            limits=ExecutionLimits(token_budget=10, max_tool_calls=2),
        )
        assert isinstance(toolset, AbstractToolset)

        responses = [
            ModelResponse(
                parts=[ToolCallPart(
                    {scenario.tool_name!r},
                    {scenario.arguments!r},
                    tool_call_id={call_id!r},
                )],
                usage=RequestUsage(
                    input_tokens={scenario.usage.input_tokens},
                    output_tokens={scenario.usage.output_tokens},
                    cache_read_tokens={scenario.usage.cached_tokens},
                ),
            ),
            ModelResponse(
                parts=[TextPart({FINAL_SUMMARY!r})],
                usage={final_usage},
            ),
        ]
        advertised = []

        async def scripted_model(messages, info):
            advertised.append(tuple(info.function_tools))
            return responses.pop(0)

        result = Agent(
            FunctionModel(scripted_model),
            toolsets=[toolset],
        ).run_sync(
            "run governed fixture",
            usage_limits=UsageLimits(total_tokens_limit=100, tool_calls_limit=10),
        )
        assert result.output == {FINAL_SUMMARY!r}
        assert advertised
        assert tuple(tool.name for tool in advertised[0]) == {ADVERTISED_TOOLS!r}
        assert all(tool.kind == "function" and tool.sequential for tool in advertised[0])

        terminal = {finish_call}
        assert terminal.stop_reason == {scenario.expected_stop!r}
        assert terminal.usage == TokenUsage(
            input_tokens={final_input_tokens},
            output_tokens={final_output_tokens},
            cached_tokens={scenario.usage.cached_tokens},
        )
        assert terminal.tool_calls_executed == {0 if scenario.expected_stop == "token_budget" else 1}
        assert terminal.handoff == HandoffArtifact(
            summary={"" if scenario.expected_stop == "token_budget" else FINAL_SUMMARY!r}
        )
        assert state.read_text(encoding="utf-8") == (
            "approval granted" if {scenario.name!r} == "approval_granted_mutation" else "initial"
        )
        assert len(handler_calls) == {scenario.expected_mutations or (1 if scenario.name == "allow_read" else 0)}

        trace_path = home.traces_dir / "portable-proof" / {f"{session_key}.jsonl"!r}
        records = []
        if {scenario.expected_stop!r} == "token_budget":
            assert not trace_path.exists()
            assert handler_calls == []
        else:
            records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
            pair = [record for record in records if record["event_type"] in {{"tool_call", "tool_result"}}]
            assert [record["event_type"] for record in pair] == ["tool_call", "tool_result"]
            assert all(record["project"] == "portable-proof" for record in pair)
            assert all(record["session_id"] == {session_key!r} for record in pair)
            assert all(record["agent_role"] == "implementer" for record in pair)
            assert all(record["payload"]["callId"] == {call_id!r} for record in pair)
            expected_decision = {scenario.expected_decision!r}
            if expected_decision in ("gate_denied", "approval_denied"):
                assert pair[-1]["payload"]["decision"] == "deny"
                assert pair[-1]["payload"]["denialKind"] == expected_decision
            else:
                assert pair[-1]["payload"]["decision"] == expected_decision

        audit_path = home.audit_log
        audit = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""
        if {scenario.expected_decision!r} == "gate_denied":
            assert "tool.deny" in audit
        if {scenario.expected_decision!r} == "approval_denied":
            assert "approval.deny" in audit
        if {scenario.name!r} == "approval_granted_mutation":
            assert "approval.grant" in audit

        audit_records = [json.loads(line) for line in audit.splitlines() if line.strip()]
        verification = verify_chain()
        normalized_trace = [
            {{
                "event_type": record["event_type"],
                "project": record["project"],
                "session_id": "<scenario>",
                "agent_role": record["agent_role"],
                "payload": record["payload"],
            }}
            for record in records
            if record["event_type"] in {{"tool_call", "tool_result"}}
        ]
        print("W28_RESULT=" + json.dumps({{
            "normalized": {{
                "advertised_tools": sorted(tool.name for tool in advertised[0]),
                "audit_actions": [record["action"] for record in audit_records],
                "audit_chain": {{
                    "exists": verification.exists,
                    "lines": verification.total_lines,
                    "chained": verification.chained,
                    "break": (
                        None
                        if verification.break_at is None
                        else {{
                            "line": verification.break_at.line,
                            "reason": verification.break_at.reason,
                        }}
                    ),
                }},
                "handler_calls": [call[0] for call in handler_calls],
                "state_hex": state.read_bytes().hex(),
                "terminal": {{
                    "ok": terminal.ok,
                    "output": terminal.output,
                    "stop_reason": terminal.stop_reason,
                    "usage": {{
                        "input_tokens": terminal.usage.input_tokens,
                        "output_tokens": terminal.usage.output_tokens,
                        "cached_tokens": terminal.usage.cached_tokens,
                    }},
                    "tool_calls_executed": terminal.tool_calls_executed,
                    "handoff": terminal.handoff.summary,
                    "error": terminal.error,
                }},
                "trace": normalized_trace,
            }},
        }}, sort_keys=True))
        """
    ).replace("__POLICY_SETUP__", textwrap.dedent(policy_setup).strip())


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
        from docket_runtime._internal.docket.governance.audit import verify_chain
        from docket_runtime._internal.docket.kernel.home import Home

        home = Home(Path(os.environ["DOCKET_HOME"]))
        if scenario["policy"] != "none":
            policies = home.policies_dir
            policies.mkdir(parents=True, exist_ok=True)
            (policies / "scenario.json").write_text(json.dumps({
                "kind": "policy",
                "name": f"w28-{scenario['name']}",
                "appliesTo": ["*"],
                "on": "toolCall",
                "when": {"matches": "mutate_state"},
                "then": {"require_approval": "ask"}.get(scenario["policy"], scenario["policy"]),
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

        trace_file = home.traces_dir / "portable-proof" / f"w28-{scenario['name']}.jsonl"
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
        audit_path = home.audit_log
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


def invoke_openhands(
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
        timeout=SUBPROCESS_TIMEOUT_S,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    line = next(line for line in result.stdout.splitlines() if line.startswith("W28_RESULT="))
    payload = json.loads(line.removeprefix("W28_RESULT="))
    port = int(payload["port"])
    with socket.socket() as probe:
        probe.settimeout(0.1)
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    return payload
