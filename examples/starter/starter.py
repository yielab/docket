#!/usr/bin/env python3
"""Run one approval-deny/grant journey through the installed root Docket CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

PROJECT = "docket-starter"
PROVIDER = "starter-local"
MODEL = "starter-model"
TARGET_NAME = "starter-output.txt"
INITIAL_BYTES = b"starter pending\n"
APPROVED_TEXT = "docket starter approved\n"
TERMINAL_SUMMARY = "Starter journey completed."
HANDOFF_FIELDS = {"summary", "files_changed", "diff_ref", "verdict", "notes"}


class StarterFailure(RuntimeError):
    """One bounded, actionable starter failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StarterFailure(message)


def _bounded_output(result: subprocess.CompletedProcess[str]) -> str:
    output = f"{result.stdout}\n{result.stderr}".strip()
    return output[-2_000:] if output else "no diagnostic output"


def _command(
    args: list[str], *, cwd: Path, env: dict[str, str], label: str
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise StarterFailure(
            f"{label} failed with exit {result.returncode}: {_bounded_output(result)}"
        )
    return result


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path} did not contain a JSON object")
    return cast(dict[str, Any], value)


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
        "id": f"starter-{sequence}",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 10 + sequence,
            "completion_tokens": 4,
            "total_tokens": 14 + sequence,
        },
    }


@dataclass
class _Recorder:
    requests: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.requests.append(payload)
            sequence = len(self.requests)

        messages = payload.get("messages")
        tools = payload.get("tools")
        if not isinstance(messages, list) or not messages:
            raise StarterFailure("model request omitted messages")
        if not isinstance(tools, list):
            raise StarterFailure("model request omitted tools")
        if sequence == 1:
            tool_names = {
                str(tool.get("function", {}).get("name", ""))
                for tool in tools
                if isinstance(tool, dict)
            }
            _require("write" in tool_names, "installed Implementer was not offered write")
            return _completion(
                None,
                sequence=sequence,
                finish_reason="tool_calls",
                tool_calls=[
                    {
                        "id": "starter-write",
                        "type": "function",
                        "function": {
                            "name": "write",
                            "arguments": json.dumps(
                                {"path": TARGET_NAME, "content": APPROVED_TEXT}
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
            _require(bool(tool_results), "follow-up model request omitted the tool result")
            _require(
                tool_results[-1].get("tool_call_id") == "starter-write",
                "tool result was not paired with starter-write",
            )
            return _completion(TERMINAL_SUMMARY, sequence=sequence)

        raise StarterFailure(f"unexpected model request {sequence}; expected exactly two")


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
            self._send_json(200, {"object": "list", "data": [{"id": MODEL}]})

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size))
                _require(isinstance(payload, dict), "model payload was not an object")
                self._send_json(200, recorder.complete(payload))
            except Exception as exc:
                self._send_json(400, {"error": {"message": f"{type(exc).__name__}: {exc}"}})

        def log_message(self, _format: str, *args: object) -> None:
            del args

    return Handler


@contextmanager
def _recording_endpoint(recorder: _Recorder) -> Iterator[str]:
    server: ThreadingHTTPServer | None = None
    for _attempt in range(10):
        candidate = ThreadingHTTPServer(("127.0.0.1", 0), _handler(recorder))
        if int(candidate.server_address[1]) != 8081:
            server = candidate
            break
        candidate.server_close()
    _require(server is not None, "could not allocate a loopback port other than 8081")
    assert server is not None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1"
    print(f"STARTER LOOPBACK {endpoint}", flush=True)
    try:
        yield endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _configure(docket: Path, endpoint: str, *, cwd: Path, env: dict[str, str]) -> None:
    _command(
        [
            str(docket),
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
        label="loopback provider configuration",
    )
    model = f"{PROVIDER}/{MODEL}"
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
        _command(
            [str(docket), "models", "set", role, model],
            cwd=cwd,
            env=env,
            label=f"{role} model selection",
        )


def _write_inputs(base: Path, workspace: Path) -> tuple[Path, Path]:
    pod = base / "starter-pod.json"
    pod.write_text(
        json.dumps(
            {
                "id": PROJECT,
                "blueprint": "agentic-product",
                "codebase": str(workspace),
                "stack": "Python",
                "description": "Run the extractable Docket starter.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    pipeline = base / "starter.pipeline.yaml"
    pipeline.write_text(
        """name: docket-starter
description: One approval-gated Implementer mutation.
steps:
  - id: implement
    role: implementer
    gate:
      type: approval
      message: Approve the starter file mutation.
""",
        encoding="utf-8",
    )
    return pod, pipeline


def _pending_token(docket: Path, *, cwd: Path, env: dict[str, str]) -> str:
    result = _command([str(docket), "approve"], cwd=cwd, env=env, label="approval listing")
    tokens = sorted(set(re.findall(r"\bapr-[0-9a-f-]+\b", result.stdout)))
    if len(tokens) != 1:
        raise StarterFailure(f"expected one pending approval, found {len(tokens)}")
    return str(tokens[0])


def _decision(expected: str) -> None:
    try:
        actual = input(f"Type {expected} to continue: ").strip().casefold()
    except EOFError as exc:
        raise StarterFailure(f"expected interactive decision {expected!r}") from exc
    _require(actual == expected, f"expected {expected!r}, received {actual!r}")


def _delegate(docket: Path, *, cwd: Path, env: dict[str, str]) -> None:
    _command(
        [
            str(docket),
            "pod",
            PROJECT,
            "delegate",
            (
                f"Write {TARGET_NAME} with exactly 'docket starter approved' followed by one LF, "
                "using Docket's write tool, then finish."
            ),
        ],
        cwd=cwd,
        env=env,
        label="task delegation",
    )


def _dispatch(docket: Path, pipeline: Path, *, cwd: Path, env: dict[str, str]) -> None:
    _command(
        [
            str(docket),
            "pipeline",
            "run",
            PROJECT,
            "--file",
            str(pipeline),
            "--timeout",
            "30",
        ],
        cwd=cwd,
        env=env,
        label="pipeline dispatch",
    )


def _terminal_evidence(home: Path) -> tuple[Path, dict[str, Any]]:
    task_lists = list((home / "workspaces" / "projects").glob("*/TASK_LIST.json"))
    _require(len(task_lists) == 1, f"expected one task list, found {len(task_lists)}")
    payload = _load_object(task_lists[0])
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise StarterFailure("task list omitted tasks")
    denied = [
        task
        for task in tasks
        if isinstance(task, dict) and task.get("failureKind") == "approval_denied"
    ]
    done = [task for task in tasks if isinstance(task, dict) and task.get("status") == "done"]
    _require(len(denied) == 1, "denial task did not persist as approval_denied")
    _require(len(done) == 1, "grant task did not persist as done")
    done_task = cast(dict[str, Any], done[0])
    hops = done_task.get("hops")
    if not isinstance(hops, list) or not hops:
        raise StarterFailure("done task omitted terminal hop")
    final_hop = hops[-1]
    if not isinstance(final_hop, dict):
        raise StarterFailure("terminal hop was not an object")
    artifact = final_hop.get("artifact")
    if not isinstance(artifact, dict):
        raise StarterFailure("terminal hop omitted typed handoff")
    _require(set(artifact) == HANDOFF_FIELDS, "terminal handoff shape was incomplete")
    _require(artifact.get("summary") == TERMINAL_SUMMARY, "terminal handoff summary mismatched")
    _require(final_hop.get("output") == TERMINAL_SUMMARY, "legacy output mismatched handoff")
    return task_lists[0], done_task


def _inspect_public_cli(
    docket: Path,
    done_task: dict[str, Any],
    *,
    cwd: Path,
    env: dict[str, str],
) -> str:
    listed = _command(
        [str(docket), "runs", "list", "--project", PROJECT, "--json"],
        cwd=cwd,
        env=env,
        label="public run list",
    )
    payload = json.loads(listed.stdout)
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        raise StarterFailure("public run list returned no runs array")
    matching = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("state") == "succeeded"
        and done_task.get("id") in run.get("taskIds", [])
    ]
    _require(bool(matching), "public run list omitted the completed task")
    run = cast(dict[str, Any], matching[0])
    run_id = str(run["id"])
    shown = _command(
        [str(docket), "runs", "show", run_id, "--json"],
        cwd=cwd,
        env=env,
        label="public run show",
    )
    _require(json.loads(shown.stdout) == run, "public run list/show disagreed")

    exported = _command(
        [str(docket), "trace", "export", PROJECT],
        cwd=cwd,
        env=env,
        label="public trace export",
    )
    records = [json.loads(line) for line in exported.stdout.splitlines() if line.strip()]
    pair = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("event_type") in {"tool_call", "tool_result"}
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("callId") == "starter-write"
    ]
    _require(
        [record["event_type"] for record in pair] == ["tool_call", "tool_result"],
        "public trace omitted the paired starter-write events",
    )
    _require(pair[0].get("session_id") == pair[1].get("session_id"), "trace identity mismatched")

    verified = _command(
        [str(docket), "audit", "verify"],
        cwd=cwd,
        env=env,
        label="public audit verification",
    )
    _require("verified clean" in verified.stdout, "audit verifier did not report a clean chain")
    return run_id


def _run(workspace: Path) -> None:
    workspace = workspace.expanduser().resolve()
    _require(workspace.is_dir(), f"workspace does not exist: {workspace}")
    target = workspace / TARGET_NAME
    _require(target.is_file(), f"target does not exist: {target}")
    _require(target.read_bytes() == INITIAL_BYTES, f"target must start with {INITIAL_BYTES!r}")
    _require("DOCKET_HOME" in os.environ, "set DOCKET_HOME to a fresh directory before running")
    home = Path(os.environ["DOCKET_HOME"]).expanduser().resolve()
    docket = Path(sys.executable).with_name("docket")
    _require(
        docket.is_file(),
        f"installed docket executable missing; run: uv pip install --python {sys.executable} "
        "--no-deps /path/to/docket-<version>.whl",
    )

    base = Path(__file__).resolve().parent
    pod, pipeline = _write_inputs(base, workspace)
    env = os.environ.copy()
    env["DOCKET_SERVICE_MANAGER"] = "none"
    env["DISPATCH_RETRY_BACKOFF_S"] = "0"
    recorder = _Recorder()
    with _recording_endpoint(recorder) as endpoint:
        _configure(docket, endpoint, cwd=base, env=env)
        _command(
            [str(docket), "init", "--from", str(pod)],
            cwd=base,
            env=env,
            label="project initialization",
        )

        _delegate(docket, cwd=base, env=env)
        _dispatch(docket, pipeline, cwd=base, env=env)
        first_token = _pending_token(docket, cwd=base, env=env)
        print(f"STARTER DENIAL PAUSED {first_token}", flush=True)
        _decision("deny")
        _command(
            [str(docket), "deny", first_token],
            cwd=base,
            env=env,
            label="public approval denial",
        )
        _require(target.read_bytes() == INITIAL_BYTES, "denied task changed target bytes")
        print("STARTER DENIAL CONFIRMED", flush=True)

        _delegate(docket, cwd=base, env=env)
        _dispatch(docket, pipeline, cwd=base, env=env)
        second_token = _pending_token(docket, cwd=base, env=env)
        print(f"STARTER GRANT PAUSED {second_token}", flush=True)
        _decision("grant")
        _command(
            [str(docket), "approve", second_token],
            cwd=base,
            env=env,
            label="public approval grant",
        )
        _require(target.read_bytes() == INITIAL_BYTES, "approval grant executed before resume")
        _dispatch(docket, pipeline, cwd=base, env=env)

    _require(len(recorder.requests) == 2, "loopback model did not receive exactly two requests")
    _require(target.read_bytes() == APPROVED_TEXT.encode(), "approved target bytes mismatched")
    task_list, done_task = _terminal_evidence(home)
    run_id = _inspect_public_cli(docket, done_task, cwd=base, env=env)
    trace_dir = home / "traces" / PROJECT
    audit = home / "audit.log"
    print(f"Target: {target}")
    print(f"Task list: {task_list}")
    print(f"Trace: {trace_dir}")
    print(f"Audit: {audit}")
    print(f"Inspect: docket runs list --project {PROJECT} --json")
    print(f"Inspect: docket runs show {run_id} --json")
    print(f"Inspect: docket trace export {PROJECT}")
    print("Inspect: docket audit verify")
    print("STARTER JOURNEY PASS", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        _run(args.workspace)
    except (StarterFailure, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"STARTER FAIL — {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
