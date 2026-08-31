#!/usr/bin/env python3
"""Run the artifact-installed release journey against a deterministic loopback model."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

PROJECT = "release-journey"
PROVIDER = "release-local"
MODEL = "journey-model"
ARTIFACT_CONTENT = "docket release journey ok\n"


class JourneyFailure(RuntimeError):
    """A bounded, user-actionable release-journey failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JourneyFailure(message)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path.name} did not contain an object")
    return cast(dict[str, Any], value)


def _bounded_output(result: subprocess.CompletedProcess[str]) -> str:
    combined = f"{result.stdout}\n{result.stderr}".strip()
    return combined[-2_000:] if combined else "no diagnostic output"


def _command(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    label: str,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise JourneyFailure(
            f"{label} failed with exit {result.returncode}: {_bounded_output(result)}"
        )
    return result


def _completion(
    content: str | None,
    *,
    sequence: int,
    finish_reason: str = "stop",
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": f"release-journey-{sequence}",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 20 + sequence,
            "completion_tokens": 7,
            "total_tokens": 27 + sequence,
        },
    }


@dataclass
class _Recorder:
    requests: list[dict[str, Any]] = field(default_factory=list)
    final_turn: bool = False
    measured_usage: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.requests.append(payload)
            sequence = len(self.requests)

        messages = payload.get("messages")
        tools = payload.get("tools")
        _require(isinstance(payload.get("model"), str), "model request omitted its model id")
        _require(isinstance(messages, list) and messages, "model request omitted messages")
        _require(isinstance(tools, list), "model request omitted its tool registry")

        if sequence == 1:
            tool_names = {
                str(tool.get("function", {}).get("name", ""))
                for tool in tools
                if isinstance(tool, dict)
            }
            _require("write" in tool_names, "installed Implementer was not offered the write tool")
            self.measured_usage = True
            return _completion(
                None,
                sequence=sequence,
                finish_reason="tool_calls",
                tool_calls=[
                    {
                        "id": "release-write",
                        "type": "function",
                        "function": {
                            "name": "write",
                            "arguments": json.dumps(
                                {
                                    "path": "release-journey.txt",
                                    "content": ARTIFACT_CONTENT,
                                }
                            ),
                        },
                    }
                ],
            )

        if sequence == 2:
            tool_results = [
                message
                for message in messages
                if isinstance(message, dict) and message.get("role") == "tool"
            ]
            _require(bool(tool_results), "follow-up request omitted the tool result")
            _require(
                tool_results[-1].get("tool_call_id") == "release-write",
                "tool result was not paired with the release write call",
            )
            _require(
                "wrote 26 characters" in str(tool_results[-1].get("content", "")),
                "write result did not report the exact release artifact",
            )
            self.final_turn = True
            self.measured_usage = True
            return _completion("Release journey completed.", sequence=sequence)

        raise JourneyFailure(f"unexpected model request {sequence}; expected exactly two")

    def evidence(self) -> dict[str, object]:
        tools_advertised = any(
            isinstance(request.get("tools"), list) and bool(request["tools"])
            for request in self.requests
        )
        tool_result = any(
            any(
                isinstance(message, dict) and message.get("role") == "tool"
                for message in request.get("messages", [])
            )
            for request in self.requests
            if isinstance(request.get("messages"), list)
        )
        return {
            "requestCount": len(self.requests),
            "wire": {
                "finalTurn": self.final_turn,
                "measuredUsage": self.measured_usage,
                "model": bool(self.requests),
                "toolResult": tool_result,
                "toolsAdvertised": tools_advertised,
            },
        }


def _handler(recorder: _Recorder) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/v1/models":
                self.send_error(404)
                return
            self._send_json(
                200,
                {"object": "list", "data": [{"id": MODEL, "object": "model"}]},
            )

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size))
                _require(isinstance(payload, dict), "chat payload was not an object")
                self._send_json(200, recorder.complete(payload))
            except Exception as exc:
                self._send_json(400, {"error": {"message": f"{type(exc).__name__}: {exc}"}})

        def log_message(self, _format: str, *args: object) -> None:
            del args

    return Handler


@contextmanager
def _recording_endpoint(recorder: _Recorder) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(recorder))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _loopback_endpoint(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    _require(parsed.scheme in {"http", "https"}, "endpoint must use http or https")
    _require(
        parsed.username is None and parsed.password is None, "endpoint must not embed credentials"
    )
    _require(
        (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"},
        "endpoint must be loopback-only",
    )
    _require(parsed.port is not None, "endpoint must include an explicit loopback port")
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path or '/v1'}"


def _write_inputs(world: Path) -> tuple[Path, Path]:
    codebase = world / "codebase"
    codebase.mkdir(parents=True)
    (codebase / "README.md").write_text("# Release journey\n", encoding="utf-8")
    pod = world / "pod.json"
    pod.write_text(
        json.dumps(
            {
                "id": PROJECT,
                "blueprint": "agentic-product",
                "codebase": str(codebase),
                "stack": "Python",
                "description": "Verify the installed Docket release boundary.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    pipeline = world / "release-journey.pipeline.yaml"
    pipeline.write_text(
        """name: artifact-installed-release-journey
description: Complete one governed tool turn from the installed wheel.
steps:
  - id: implement
    role: implementer
""",
        encoding="utf-8",
    )
    return pod, pipeline


def _clean_environment(world: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "DOCKET_LLM_API_KEY",
        "DOCKET_LLM_BASE_URL",
    ):
        env.pop(key, None)
    home = world / ".docket"
    user_home = world / "home"
    user_home.mkdir()
    env.update(
        {
            "DOCKET_HOME": str(home),
            "DOCKET_SERVICE_MANAGER": "none",
            "DOCKET_LOG_DIR": str(world / "logs"),
            "DISPATCH_RETRY_BACKOFF_S": "0",
            "HOME": str(user_home),
            "NO_COLOR": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "PYTHONUNBUFFERED": "1",
            "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(world / "uv-cache")),
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    return env


def _install(repo: Path, world: Path, env: dict[str, str]) -> tuple[Path, Path, Path]:
    dist = world / "dist"
    venv = world / "venv"
    outside = world / "outside-checkout"
    outside.mkdir()
    _command(
        ["uv", "build", "--wheel", "--out-dir", str(dist)],
        cwd=repo,
        env=env,
        label="wheel build",
    )
    wheels = list(dist.glob("docket-*.whl"))
    _require(len(wheels) == 1, f"wheel build produced {len(wheels)} canonical artifacts")
    _command(
        ["uv", "venv", str(venv), "--python", "3.11"],
        cwd=outside,
        env=env,
        label="fresh virtual environment creation",
    )
    python = venv / "bin" / "python"
    executable = venv / "bin" / "docket"
    _command(
        ["uv", "pip", "install", "--python", str(python), str(wheels[0])],
        cwd=outside,
        env=env,
        label="exact wheel installation",
    )
    _require(executable.is_file(), "installed wheel did not expose the docket executable")
    return wheels[0], python, executable


def _run_cli(
    executable: Path,
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    label: str,
) -> subprocess.CompletedProcess[str]:
    return _command([str(executable), *args], cwd=cwd, env=env, label=label, timeout=60)


def _configure_provider(
    executable: Path,
    endpoint: str,
    *,
    cwd: Path,
    env: dict[str, str],
) -> None:
    model = f"{PROVIDER}/{MODEL}"
    _run_cli(
        executable,
        [
            "models",
            "provider",
            "add",
            PROVIDER,
            endpoint,
            "--model",
            MODEL,
            "--ctx",
            "16384",
            "--max-tokens",
            "1024",
        ],
        cwd=cwd,
        env=env,
        label="provider endpoint validation",
    )
    for role in (
        "default",
        "manager",
        "programmer",
        "reviewer",
        "tester",
        "knowledge",
        "security",
        "repo",
    ):
        _run_cli(
            executable,
            ["models", "set", role, model],
            cwd=cwd,
            env=env,
            label=f"{role} model selection",
        )


def _verify_state(world: Path, executable: Path, env: dict[str, str]) -> None:
    home = world / ".docket"
    artifact = world / "codebase" / "release-journey.txt"
    _require(
        artifact.read_bytes() == ARTIFACT_CONTENT.encode(), "tool side effect was not byte-exact"
    )
    runs = _load_json(home / "docket-runs.json").get("runs")
    _require(
        isinstance(runs, list) and any(run.get("state") == "succeeded" for run in runs),
        "release journey has no successful run record",
    )
    task_files = list((home / "workspaces" / "projects").glob("*/TASK_LIST.json"))
    _require(bool(task_files), "release journey did not persist its task list")
    tasks = _load_json(task_files[0]).get("tasks")
    _require(
        isinstance(tasks, list) and any(task.get("status") == "done" for task in tasks),
        "release journey task did not reach done",
    )
    sessions = sorted((home / "sessions").glob("*/session.json"))
    _require(bool(sessions), "release journey retained no durable session")
    atomic_unit = False
    measured_usage = False
    for path in sessions:
        record = _load_json(path)
        usage = record.get("usage", {})
        if isinstance(usage, dict) and int(usage.get("inputTokens", 0)) > 0:
            measured_usage = True
        messages = record.get("messages", [])
        if not isinstance(messages, list):
            continue
        for index, message in enumerate(messages[:-1]):
            if not isinstance(message, dict):
                continue
            calls = message.get("toolCalls", [])
            if not isinstance(calls, list) or not calls:
                continue
            call = calls[0]
            result = messages[index + 1]
            if (
                isinstance(call, dict)
                and isinstance(result, dict)
                and result.get("role") == "tool"
                and result.get("toolCallId") == call.get("id")
            ):
                atomic_unit = True
    _require(atomic_unit, "session did not retain an atomic tool call/result unit")
    _require(measured_usage, "session did not retain measured endpoint usage")
    traces = list(home.glob("traces/**/*.jsonl"))
    trace_text = "\n".join(path.read_text(encoding="utf-8") for path in traces)
    _require('"event_type": "tool_call"' in trace_text, "trace omitted the tool call")
    _require('"event_type": "tool_result"' in trace_text, "trace omitted the tool result")
    _require((home / "audit.log").read_text(encoding="utf-8").strip() != "", "audit is empty")
    _run_cli(executable, ["audit", "verify"], cwd=world / "codebase", env=env, label="audit verify")
    _run_cli(
        executable,
        ["runs", "list", "--project", PROJECT, "--json"],
        cwd=world / "codebase",
        env=env,
        label="public run inspection",
    )
    _run_cli(
        executable,
        ["trace", "export", PROJECT],
        cwd=world / "codebase",
        env=env,
        label="public trace inspection",
    )


def _run(world: Path, repo: Path, requested_endpoint: str | None) -> None:
    _require(not world.exists() or not any(world.iterdir()), "--workdir must be new or empty")
    world.mkdir(parents=True, exist_ok=True)
    env = _clean_environment(world)
    pod, pipeline = _write_inputs(world)
    wheel, python, executable = _install(repo, world, env)
    module_result = _command(
        [str(python), "-c", "import docket; print(docket.__file__)"],
        cwd=world / "outside-checkout",
        env=env,
        label="installed module inspection",
    )
    module = module_result.stdout.strip()
    _require(bool(module), "installed module inspection returned no path")

    recorder = _Recorder()
    endpoint_context: AbstractContextManager[str]
    if requested_endpoint is None:
        endpoint_context = _recording_endpoint(recorder)
    else:
        endpoint_context = nullcontext(_loopback_endpoint(requested_endpoint))

    with endpoint_context as endpoint:
        _configure_provider(
            executable,
            endpoint,
            cwd=world / "outside-checkout",
            env=env,
        )
        _run_cli(
            executable,
            ["init", "--from", str(pod)],
            cwd=world / "outside-checkout",
            env=env,
            label="project initialization",
        )
        _run_cli(
            executable,
            [
                "pod",
                PROJECT,
                "delegate",
                (
                    "Create release-journey.txt with exactly 'docket release journey ok' followed "
                    "by one LF using Docket's write tool, then finish the turn."
                ),
            ],
            cwd=world / "outside-checkout",
            env=env,
            label="task delegation",
        )
        _run_cli(
            executable,
            [
                "pipeline",
                "run",
                PROJECT,
                "--file",
                str(pipeline),
                "--follow",
                "--timeout",
                "30",
            ],
            cwd=world / "outside-checkout",
            env=env,
            label="governed turn dispatch",
        )

    _verify_state(world, executable, env)
    evidence = recorder.evidence()
    _require(evidence["requestCount"] == 2, "recorder did not observe exactly two model requests")
    evidence.update(
        {
            "artifact": str(wheel.resolve()),
            "executable": str(executable.resolve()),
            "module": str(Path(module).resolve()),
        }
    )
    (world / "journey-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("[check] exact wheel installed outside the checkout")
    print("[check] loopback provider, governed write, and final turn observed")
    print("[check] task, run, session, trace, and audit evidence retained")
    print("RELEASE JOURNEY PASS")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, help="Preserve the journey at a new or empty path.")
    parser.add_argument(
        "--endpoint", help="Use an explicit loopback endpoint instead of the recorder."
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo = Path(__file__).resolve().parents[1]
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.workdir is None:
        temporary = tempfile.TemporaryDirectory(prefix="docket-release-journey-")
        world = Path(temporary.name)
    else:
        world = args.workdir.expanduser().resolve()
    try:
        _run(world, repo, args.endpoint)
    except (JourneyFailure, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"RELEASE JOURNEY FAIL — {exc}", file=sys.stderr)
        if args.workdir is not None:
            print(f"Inspect state at: {world}", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
