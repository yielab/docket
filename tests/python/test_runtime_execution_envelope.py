"""Artifact-installed RED contract for W28-C1's execution envelope."""

from __future__ import annotations

import os
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "packages" / "docket-runtime"


@dataclass(frozen=True)
class RuntimeArtifacts:
    wheel_python: Path
    sdist_python: Path


def _run(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=True)


def _python(
    python: Path, source: str, *, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(python), "-c", source],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture(scope="module")
def runtime_artifacts(tmp_path_factory: pytest.TempPathFactory) -> RuntimeArtifacts:
    base = tmp_path_factory.mktemp("w28-c1-artifacts")
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
        _run("uv", "venv", str(venv), "--python", "3.11", cwd=base, env=env)
        python = venv / "bin" / "python"
        _run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(artifact),
            cwd=base,
            env=env,
        )
        pythons.append(python)

    assert not list(build_tmp.glob("docket-runtime-build-*"))
    return RuntimeArtifacts(wheel_python=pythons[0], sdist_python=pythons[1])


def _consumer(body: str) -> str:
    prelude = textwrap.dedent(
        """
        import json
        import os
        from pathlib import Path

        from docket_runtime import (
            ExecutionLimits,
            ExecutionResult,
            GovernedExecution,
            HandoffArtifact,
            Runtime,
            TokenUsage,
            Tool,
            ToolCall,
            ToolContext,
            ToolOutcome,
        )

        home = Path(os.environ["DOCKET_HOME"])
        workspace = Path(os.environ["W28_WORKSPACE"])
        workspace.mkdir(parents=True, exist_ok=True)
        state = workspace / "state.txt"
        state.write_text("initial", encoding="utf-8")

        def mutate(args, context):
            state.write_text(str(args["value"]), encoding="utf-8")
            return ToolOutcome(True, state.read_text(encoding="utf-8"))

        def read_state(args, context):
            return ToolOutcome(True, state.read_text(encoding="utf-8"))

        parameters = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }
        context = ToolContext(
            agent_id="external",
            session_key="w28-execution",
            roots=(workspace,),
            role="implementer",
            project="portable-proof",
        )
        """
    )
    return f"{prelude}\n{textwrap.dedent(body)}"


def _assert_consumer(
    artifacts: RuntimeArtifacts,
    source: str,
    *,
    tmp_path: Path,
    use_sdist: bool = False,
) -> None:
    python = artifacts.sdist_python if use_sdist else artifacts.wheel_python
    outside = tmp_path / "outside-checkout"
    outside.mkdir(parents=True)
    env = {
        **os.environ,
        "DOCKET_HOME": str(tmp_path / "docket-home"),
        "W28_WORKSPACE": str(tmp_path / "workspace"),
        "PYTHONPATH": "",
    }
    result = _python(python, source, cwd=outside, env=env)
    assert result.returncode == 0, result.stderr or result.stdout


def test_reported_token_budget_terminalizes_before_mutation(
    runtime_artifacts: RuntimeArtifacts, tmp_path: Path
) -> None:
    source = _consumer(
        """
        runtime = Runtime()
        runtime.register(Tool("mutate", "mutate state", parameters, mutate, kind="write"))
        execution = runtime.start_execution(
            context, ExecutionLimits(token_budget=10, max_tool_calls=3)
        )
        call = ToolCall("over-budget", "mutate", json.dumps({"value": "changed"}))

        terminal = execution.record_response(
            TokenUsage(input_tokens=8, output_tokens=3), (call,)
        )

        assert isinstance(execution, GovernedExecution)
        assert isinstance(terminal, ExecutionResult)
        assert terminal.ok is False
        assert terminal.stop_reason == "token_budget"
        assert terminal.usage.total_tokens == 11
        assert terminal.tool_calls_executed == 0
        assert isinstance(terminal.handoff, HandoffArtifact)
        assert state.read_text(encoding="utf-8") == "initial"
        try:
            execution.dispatch(call)
        except RuntimeError:
            pass
        else:
            raise AssertionError("terminal execution accepted a mutation")
        assert state.read_text(encoding="utf-8") == "initial"
        """
    )
    _assert_consumer(runtime_artifacts, source, tmp_path=tmp_path)


def test_tool_call_budget_refuses_complete_next_batch(
    runtime_artifacts: RuntimeArtifacts, tmp_path: Path
) -> None:
    source = _consumer(
        """
        runtime = Runtime()
        runtime.register(Tool("mutate", "mutate state", parameters, mutate, kind="write"))
        execution = runtime.start_execution(
            context, ExecutionLimits(token_budget=100, max_tool_calls=1)
        )
        first = ToolCall("first", "mutate", json.dumps({"value": "first"}))
        assert execution.record_response(TokenUsage(input_tokens=2, output_tokens=1), (first,)) is None
        first_result = execution.dispatch(first)
        assert first_result.ok and first_result.executed
        assert state.read_text(encoding="utf-8") == "first"

        second = ToolCall("second", "mutate", json.dumps({"value": "second"}))
        terminal = execution.record_response(
            TokenUsage(input_tokens=2, output_tokens=1), (second,)
        )
        assert terminal is not None
        assert terminal.stop_reason == "max_tool_calls"
        assert terminal.tool_calls_executed == 1
        assert state.read_text(encoding="utf-8") == "first"
        """
    )
    _assert_consumer(runtime_artifacts, source, tmp_path=tmp_path)


def test_every_decision_emits_one_paired_trace_with_execution_identity(
    runtime_artifacts: RuntimeArtifacts, tmp_path: Path
) -> None:
    source = _consumer(
        """
        policies = home / "policies"
        policies.mkdir(parents=True, exist_ok=True)
        (policies / "deny.json").write_text(json.dumps({
            "id": "deny-external",
            "applies_to": ["*"],
            "hook": "pre_tool_call",
            "match": {"type": "regex", "pattern": "deny_action"},
            "action": "block",
            "message": "fixture denial",
        }), encoding="utf-8")
        (policies / "approval.json").write_text(json.dumps({
            "id": "approve-external",
            "applies_to": ["*"],
            "hook": "pre_tool_call",
            "match": {"type": "regex", "pattern": "approval_action"},
            "action": "require_approval",
            "message": "fixture approval",
        }), encoding="utf-8")

        cases = (
            ("allow", Runtime(), Tool("read_action", "read", {"type": "object"}, read_state), True),
            ("deny", Runtime(), Tool("deny_action", "deny", parameters, mutate, kind="write"), False),
            ("approval-deny", Runtime(approval_stub=lambda token: False), Tool("approval_action", "approval", parameters, mutate, kind="write"), False),
            ("approval-grant", Runtime(approval_stub=lambda token: True), Tool("approval_action", "approval", parameters, mutate, kind="write"), True),
        )
        for index, (label, runtime, tool, expected_ok) in enumerate(cases):
            runtime.register(tool)
            case_context = ToolContext(
                agent_id="external",
                session_key=f"case-{index}",
                roots=(workspace,),
                role="implementer",
                project="portable-proof",
            )
            execution = runtime.start_execution(
                case_context, ExecutionLimits(token_budget=100, max_tool_calls=1)
            )
            arguments = "{}" if label == "allow" else json.dumps({"value": label})
            call = ToolCall(f"call-{index}", tool.name, arguments)
            assert execution.record_response(TokenUsage(input_tokens=1, output_tokens=1), (call,)) is None
            result = execution.dispatch(call)
            assert result.ok is expected_ok
            execution.finish(label)

            trace_file = home / "traces" / "portable-proof" / f"case-{index}.jsonl"
            records = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
            tool_records = [record for record in records if record["event_type"] in {"tool_call", "tool_result"}]
            assert [record["event_type"] for record in tool_records] == ["tool_call", "tool_result"]
            assert all(record["project"] == "portable-proof" for record in tool_records)
            assert all(record["session_id"] == f"case-{index}" for record in tool_records)
            assert all(record["agent_role"] == "implementer" for record in tool_records)
            assert all(record["payload"]["callId"] == f"call-{index}" for record in tool_records)

        audit = (home / "audit.log").read_text(encoding="utf-8")
        assert "tool.deny" in audit
        assert "approval.deny" in audit
        assert "approval.grant" in audit
        """
    )
    _assert_consumer(runtime_artifacts, source, tmp_path=tmp_path)


def test_malformed_and_unknown_calls_remain_dispatcher_denials(
    runtime_artifacts: RuntimeArtifacts, tmp_path: Path
) -> None:
    source = _consumer(
        """
        runtime = Runtime()
        runtime.register(Tool("mutate", "mutate state", parameters, mutate, kind="write"))
        for invalid_limits in (
            {"token_budget": 0, "max_tool_calls": 1},
            {"token_budget": 1, "max_tool_calls": 0},
        ):
            try:
                ExecutionLimits(**invalid_limits)
            except ValueError:
                pass
            else:
                raise AssertionError("non-positive execution limit was accepted")
        execution = runtime.start_execution(
            context, ExecutionLimits(token_budget=100, max_tool_calls=2)
        )
        calls = (
            ToolCall("unknown", "native_bash", "{}"),
            ToolCall("malformed", "mutate", "[not-an-object]"),
        )
        for call in calls:
            assert execution.record_response(TokenUsage(input_tokens=1, output_tokens=1), (call,)) is None
            result = execution.dispatch(call)
            assert result.denial_kind == "invalid_call"
            assert result.executed is False
        terminal = execution.finish("both refused")
        assert terminal.ok
        assert terminal.tool_calls_executed == 2
        assert state.read_text(encoding="utf-8") == "initial"

        trace_file = home / "traces" / "portable-proof" / "w28-execution.jsonl"
        records = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
        pairs = [record for record in records if record["event_type"] in {"tool_call", "tool_result"}]
        assert [record["event_type"] for record in pairs] == [
            "tool_call", "tool_result", "tool_call", "tool_result"
        ]
        assert [record["payload"]["denialKind"] for record in pairs if record["event_type"] == "tool_result"] == [
            "invalid_call", "invalid_call"
        ]
        """
    )
    _assert_consumer(runtime_artifacts, source, tmp_path=tmp_path)


def test_response_lifecycle_and_terminal_handoff_are_single_use(
    runtime_artifacts: RuntimeArtifacts, tmp_path: Path
) -> None:
    source = _consumer(
        """
        runtime = Runtime()
        runtime.register(Tool("mutate", "mutate state", parameters, mutate, kind="write"))
        execution = runtime.start_execution(
            context, ExecutionLimits(token_budget=100, max_tool_calls=2)
        )
        call = ToolCall("pending", "mutate", json.dumps({"value": "done"}))
        assert execution.record_response(TokenUsage(input_tokens=3, output_tokens=2), (call,)) is None

        for invalid in (
            lambda: execution.record_response(TokenUsage(input_tokens=1), ()),
            lambda: execution.dispatch(ToolCall("wrong", "mutate", call.arguments)),
            lambda: execution.finish("too early"),
        ):
            try:
                invalid()
            except RuntimeError:
                pass
            else:
                raise AssertionError("invalid lifecycle transition succeeded")

        result = execution.dispatch(call)
        assert result.ok
        terminal = execution.finish("portable result")
        assert terminal.ok
        assert terminal.stop_reason == "final_message"
        assert terminal.output == "portable result"
        assert terminal.usage == TokenUsage(input_tokens=3, output_tokens=2)
        assert terminal.tool_calls_executed == 1
        assert terminal.handoff == HandoffArtifact(summary="portable result")

        for invalid in (
            lambda: execution.record_response(TokenUsage(), ()),
            lambda: execution.dispatch(call),
            lambda: execution.finish("again"),
        ):
            try:
                invalid()
            except RuntimeError:
                pass
            else:
                raise AssertionError("terminal execution accepted another transition")
        assert state.read_text(encoding="utf-8") == "done"
        """
    )
    _assert_consumer(runtime_artifacts, source, tmp_path=tmp_path)


def test_concurrent_runtime_approval_stubs_never_cross_answer(
    runtime_artifacts: RuntimeArtifacts, tmp_path: Path
) -> None:
    source = textwrap.dedent(
        """
        import json
        import os
        import threading
        from pathlib import Path

        from docket_runtime import Runtime, Tool, ToolCall, ToolContext, ToolOutcome

        home = Path(os.environ["DOCKET_HOME"])
        policies = home / "policies"
        policies.mkdir(parents=True, exist_ok=True)
        (policies / "race.json").write_text(json.dumps({
            "id": "approval-race",
            "applies_to": ["*"],
            "hook": "pre_tool_call",
            "match": {"type": "regex", "pattern": "race_"},
            "action": "require_approval",
            "message": "controlled overlap",
        }), encoding="utf-8")

        first_entered = threading.Event()
        second_entered = threading.Event()
        release_first = threading.Event()
        start_barrier = threading.Barrier(2)
        first_tokens = []
        second_tokens = []
        executed = []
        results = {}

        def first_stub(token):
            first_tokens.append(token)
            if len(first_tokens) == 1:
                first_entered.set()
                assert release_first.wait(5)
            return True

        def second_stub(token):
            second_tokens.append(token)
            second_entered.set()
            return False

        def handler(label):
            def run(args, context):
                executed.append(label)
                return ToolOutcome(True, label)
            return run

        first = Runtime(approval_stub=first_stub)
        second = Runtime(approval_stub=second_stub)
        first.register(Tool("race_first", "first", {"type": "object"}, handler("first"), kind="write"))
        second.register(Tool("race_second", "second", {"type": "object"}, handler("second"), kind="write"))

        def dispatch(label, runtime, tool):
            if label == "first":
                start_barrier.wait()
            results[label] = runtime.dispatch(
                ToolCall(label, tool, "{}"),
                ToolContext(agent_id=label, project="portable-proof", role="implementer"),
            )

        first_thread = threading.Thread(target=dispatch, args=("first", first, "race_first"))
        second_thread = threading.Thread(target=dispatch, args=("second", second, "race_second"))
        first_thread.start()
        start_barrier.wait()
        assert first_entered.wait(5)
        second_thread.start()

        # The first stub remains open while the second runtime attempts dispatch. A correct
        # serialized implementation may keep the second outside until the first is released.
        second_entered.wait(0.5)
        release_first.set()

        first_thread.join(5)
        second_thread.join(5)
        assert not first_thread.is_alive() and not second_thread.is_alive()
        assert len(first_tokens) == 1
        assert len(second_tokens) == 1
        assert results["first"].ok and results["first"].executed
        assert results["second"].denial_kind == "approval_denied"
        assert results["second"].executed is False
        assert executed == ["first"]
        """
    )
    _assert_consumer(runtime_artifacts, source, tmp_path=tmp_path)


def test_wheel_and_sdist_publish_the_same_narrow_facade_and_base_dependencies(
    runtime_artifacts: RuntimeArtifacts, tmp_path: Path
) -> None:
    source = textwrap.dedent(
        """
        import importlib.metadata
        import sys

        import docket_runtime
        from docket_runtime import (
            ExecutionLimits,
            ExecutionResult,
            GovernedExecution,
            HandoffArtifact,
            Runtime,
            TokenUsage,
            Tool,
            ToolCall,
            ToolContext,
            ToolOutcome,
            ToolResult,
            ToolSpec,
        )

        expected = {
            "ExecutionLimits", "ExecutionResult", "GovernedExecution", "HandoffArtifact",
            "Runtime", "TokenUsage", "Tool", "ToolCall", "ToolContext", "ToolOutcome",
            "ToolResult", "ToolSpec", "__version__",
        }
        assert set(docket_runtime.__all__) == expected
        assert docket_runtime.__version__ == "0.3.0"
        runtime = Runtime()
        runtime.register(Tool("visible", "safe schema", {"type": "object"}, lambda args, ctx: ToolOutcome(True)))
        assert runtime.tool_specs() == (
            ToolSpec(name="visible", description="safe schema", parameters={"type": "object"}),
        )
        assert not hasattr(runtime.tool_specs()[0], "handler")
        assert not hasattr(runtime, "registry")
        requirements = importlib.metadata.requires("docket-runtime") or []
        names = {requirement.split(";", 1)[0].split("[", 1)[0].split(">", 1)[0].split("=", 1)[0].strip().lower() for requirement in requirements}
        assert names == {"filelock", "pydantic"}
        assert not any(name == "docket" or name.startswith("docket.") for name in sys.modules)
        """
    )
    _assert_consumer(runtime_artifacts, source, tmp_path=tmp_path / "wheel")
    _assert_consumer(runtime_artifacts, source, tmp_path=tmp_path / "sdist", use_sdist=True)
