"""Artifact-installed RED contract for the W28-C3 PydanticAI toolset adapter."""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.fixtures.runtime_adapters.scenarios import (
    ADVERTISED_TOOLS,
    FINAL_SUMMARY,
    PLANTED_BYPASSES,
    SCENARIOS,
    GovernanceScenario,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "packages" / "docket-runtime"
PYDANTIC_AI_FIXTURE = ROOT / "tests" / "fixtures" / "runtime_adapters" / "pydantic_ai"
PYDANTIC_AI_VERSION = "2.37.0"


@dataclass(frozen=True)
class RuntimeArtifacts:
    wheel_python: Path
    sdist_python: Path


def _run(*args: str, cwd: Path, env: dict[str, str]) -> None:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr or result.stdout


def _consumer(python: Path, source: str, *, cwd: Path, env: dict[str, str]) -> None:
    result = subprocess.run(
        [str(python), "-c", source],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.fixture(scope="module")
def runtime_artifacts(tmp_path_factory: pytest.TempPathFactory) -> RuntimeArtifacts:
    base = tmp_path_factory.mktemp("w28-c3-artifacts")
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
    assert not list(build_tmp.glob("docket-runtime-build-*"))
    return RuntimeArtifacts(
        wheel_python=_installed_python(wheel, label="wheel", tmp_path=base, env=env),
        sdist_python=_installed_python(sdist, label="sdist", tmp_path=base, env=env),
    )


def _installed_python(artifact: Path, *, label: str, tmp_path: Path, env: dict[str, str]) -> Path:
    venv = tmp_path / label
    install_env = {**env, "UV_PROJECT_ENVIRONMENT": str(venv)}
    _run(
        "uv",
        "sync",
        "--frozen",
        "--no-install-project",
        "--project",
        str(PYDANTIC_AI_FIXTURE),
        cwd=tmp_path,
        env=install_env,
    )
    python = venv / "bin" / "python"
    _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        str(artifact),
        cwd=tmp_path,
        env=install_env,
    )
    return python


def _scenario_source(scenario: GovernanceScenario, *, parity: bool = False) -> str:
    approval_stub = (
        "None"
        if scenario.approval_response is None
        else f"lambda token: {scenario.approval_response!r}"
    )
    policy_match = json.loads(scenario.arguments)["value"] if scenario.policy != "none" else ""
    policy_setup = ""
    if scenario.policy != "none":
        policy_setup = f"""
        policies = home / "policies"
        policies.mkdir(parents=True, exist_ok=True)
        (policies / "scenario.json").write_text(json.dumps({{
            "id": "pydantic-{scenario.name}",
            "applies_to": ["*"],
            "hook": "pre_tool_call",
            "match": {{"type": "regex", "pattern": {policy_match!r}}},
            "action": {"block" if scenario.policy == "block" else "require_approval"!r},
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
        from docket_runtime._internal.docket.core.audit import verify_chain
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.toolsets import AbstractToolset
        from pydantic_ai.usage import RequestUsage, UsageLimits

        assert importlib.metadata.version("pydantic-ai") == {PYDANTIC_AI_VERSION!r}

        home = Path(os.environ["DOCKET_HOME"])
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

        trace_path = home / "traces" / "portable-proof" / {f"{session_key}.jsonl"!r}
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

        audit_path = home / "audit.log"
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
                    "legacy": verification.legacy,
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


def test_pinned_pydantic_ai_function_model_is_credential_free(
    runtime_artifacts: RuntimeArtifacts, tmp_path: Path
) -> None:
    source = textwrap.dedent(
        f"""
        import importlib.metadata

        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, TextPart
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.usage import RequestUsage

        assert importlib.metadata.version("pydantic-ai") == {PYDANTIC_AI_VERSION!r}

        async def scripted_model(messages, info):
            assert info.function_tools == []
            return ModelResponse(
                parts=[TextPart("function model ready")],
                usage=RequestUsage(input_tokens=2, output_tokens=1),
            )

        result = Agent(FunctionModel(scripted_model)).run_sync("probe")
        assert result.output == "function model ready"
        assert result.usage.input_tokens == 2
        assert result.usage.output_tokens == 1
        """
    )
    outside = tmp_path / "outside-checkout"
    outside.mkdir()
    _consumer(
        runtime_artifacts.wheel_python,
        source,
        cwd=outside,
        env={**os.environ, "PYTHONPATH": ""},
    )


@pytest.mark.parametrize("artifact_name", ("wheel", "sdist"))
def test_pydantic_ai_toolset_governs_shared_scenarios_from_artifacts(
    runtime_artifacts: RuntimeArtifacts, artifact_name: str, tmp_path: Path
) -> None:
    python = getattr(runtime_artifacts, f"{artifact_name}_python")
    env = {
        **os.environ,
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(tmp_path / "uv-cache")),
        "PYTHONPATH": "",
    }
    outside = tmp_path / "outside-checkout"
    outside.mkdir()

    for scenario in SCENARIOS[0:1] + SCENARIOS[3:]:
        scenario_env = {
            **env,
            "DOCKET_HOME": str(tmp_path / f"docket-home-{scenario.name}"),
            "W28_WORKSPACE": str(tmp_path / f"workspace-{scenario.name}"),
        }
        _consumer(python, _scenario_source(scenario), cwd=outside, env=scenario_env)


@pytest.mark.parametrize("artifact_name", ("wheel", "sdist"))
@pytest.mark.parametrize("bypass_name", PLANTED_BYPASSES)
def test_pydantic_ai_toolset_exposes_no_native_or_unknown_bypass(
    runtime_artifacts: RuntimeArtifacts,
    artifact_name: str,
    bypass_name: str,
    tmp_path: Path,
) -> None:
    python = getattr(runtime_artifacts, f"{artifact_name}_python")
    env = {
        **os.environ,
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(tmp_path / "uv-cache")),
        "PYTHONPATH": "",
    }
    source = textwrap.dedent(
        f"""
        import os
        from pathlib import Path

        from docket_runtime import ExecutionLimits, Runtime, Tool, ToolContext, ToolOutcome
        from docket_runtime.adapters.pydantic_ai import DocketToolset
        from pydantic_ai import Agent, UsageLimitExceeded
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.toolsets import AbstractToolset
        from pydantic_ai.usage import RequestUsage, UsageLimits

        workspace = Path(os.environ["W28_WORKSPACE"])
        workspace.mkdir(parents=True, exist_ok=True)
        state = workspace / "state.txt"
        state.write_text("initial", encoding="utf-8")
        handler_calls = []

        def read_state(args, context):
            handler_calls.append("read_state")
            return ToolOutcome(True, state.read_text(encoding="utf-8"))

        def mutate_state(args, context):
            handler_calls.append("mutate_state")
            state.write_text(args["value"], encoding="utf-8")
            return ToolOutcome(True, state.read_text(encoding="utf-8"))

        runtime = Runtime()
        runtime.register(Tool("read_state", "read fixture state", {{"type": "object"}}, read_state))
        runtime.register(Tool(
            "mutate_state",
            "mutate fixture state",
            {{"type": "object", "properties": {{"value": {{"type": "string"}}}}}},
            mutate_state,
            kind="write",
        ))
        context = ToolContext(
            agent_id="pydantic-ai",
            session_key="pydantic-native-bypass",
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
        advertised = []

        async def scripted_model(messages, info):
            advertised.append(tuple(info.function_tools))
            return ModelResponse(
                parts=[ToolCallPart(
                    {bypass_name!r},
                    {{"command": "printf bypass"}},
                    tool_call_id="pydantic-{bypass_name}",
                )],
                usage=RequestUsage(input_tokens=1, output_tokens=1),
            )

        try:
            Agent(FunctionModel(scripted_model), toolsets=[toolset]).run_sync(
                "attempt provider-native bypass",
                usage_limits=UsageLimits(request_limit=1, total_tokens_limit=100),
            )
        except UsageLimitExceeded as exc:
            assert "request_limit" in str(exc)
        else:
            raise AssertionError("unknown native tool bypass was accepted")
        assert len(advertised) == 1
        assert tuple(tool.name for tool in advertised[0]) == {ADVERTISED_TOOLS!r}
        assert all(tool.kind == "function" and tool.sequential for tool in advertised[0])
        assert not set(tool.name for tool in advertised[0]) & set({PLANTED_BYPASSES!r})
        assert handler_calls == []
        assert state.read_text(encoding="utf-8") == "initial"
        """
    )
    outside = tmp_path / "outside-checkout"
    outside.mkdir()
    _consumer(
        python,
        source,
        cwd=outside,
        env={
            **env,
            "DOCKET_HOME": str(tmp_path / "docket-home"),
            "W28_WORKSPACE": str(tmp_path / "workspace"),
        },
    )
