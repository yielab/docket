#!/usr/bin/env python3
"""Run one observable Docket workflow through the real CLI and HTTP adapter.

The endpoint is a deterministic loopback server, but everything on Docket's side is production:
CLI subprocesses, persisted state, endpoint resolution, the chat-completions adapter,
``DocketDriver``, the agent loop, gated tools, pipeline gates, resume, sessions, traces and audit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast


class SmokeFailure(RuntimeError):
    """A smoke assertion or subprocess failed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _latest(messages: list[dict[str, Any]], role: str) -> dict[str, Any]:
    for message in reversed(messages):
        if message.get("role") == role:
            return message
    raise SmokeFailure(f"model request did not contain a {role!r} message")


class _ScriptedModel:
    """Six deterministic replies for the two-dispatch smoke scenario."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    @staticmethod
    def _response(
        content: str | None,
        *,
        finish_reason: str = "stop",
        tool_calls: list[dict[str, Any]] | None = None,
        sequence: int,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
        return {
            "id": f"smoke-{sequence}",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {
                "prompt_tokens": 10 + sequence,
                "completion_tokens": 5,
                "total_tokens": 15 + sequence,
            },
        }

    def complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.requests.append(payload)
            sequence = len(self.requests)

        _require(payload.get("stream") is False, "chat request must explicitly disable streaming")
        _require(isinstance(payload.get("model"), str), "chat request did not carry a model id")
        messages_raw = payload.get("messages")
        tools_raw = payload.get("tools")
        _require(
            isinstance(messages_raw, list) and bool(messages_raw), "chat request has no messages"
        )
        _require(
            isinstance(messages_raw, list)
            and all(isinstance(message, dict) for message in messages_raw),
            "chat request contains a non-object message",
        )
        _require(isinstance(tools_raw, list), "chat request did not advertise the tool registry")
        messages = cast(list[dict[str, Any]], messages_raw)
        tools = cast(list[Any], tools_raw)

        if sequence == 1:
            return self._response(
                "Lead prepared the implementation plan and acceptance checks.", sequence=sequence
            )

        if sequence == 2:
            user_text = str(_latest(messages, "user").get("content", ""))
            _require("Lead prepared" in user_text, "Implementer did not receive the Lead handoff")
            tool_names = {
                str(item.get("function", {}).get("name", ""))
                for item in tools
                if isinstance(item, dict)
            }
            _require("write" in tool_names, "Implementer was not advertised the write tool")
            return self._response(
                None,
                finish_reason="tool_calls",
                tool_calls=[
                    {
                        "id": "smoke-write",
                        "type": "function",
                        "function": {
                            "name": "write",
                            "arguments": json.dumps(
                                {
                                    "path": "smoke-artifact.txt",
                                    "content": "docket smoke ok\n",
                                }
                            ),
                        },
                    }
                ],
                sequence=sequence,
            )

        if sequence == 3:
            tool_message = _latest(messages, "tool")
            _require(
                tool_message.get("tool_call_id") == "smoke-write",
                "tool result was not paired with the requested call",
            )
            _require(
                "wrote 16 characters" in str(tool_message.get("content", "")),
                "write tool did not report success back to the model",
            )
            return self._response(
                "Implemented smoke artifact through the gated write tool.", sequence=sequence
            )

        if sequence == 4:
            user_text = str(_latest(messages, "user").get("content", ""))
            _require(
                "Implemented smoke artifact" in user_text,
                "Reviewer did not receive the Implementer handoff",
            )
            return self._response(
                "APPROVE\nThe implementation and mechanical check are sound.", sequence=sequence
            )

        if sequence == 5:
            user_text = str(_latest(messages, "user").get("content", ""))
            _require("APPROVE" in user_text, "approved review was absent from the resumed handoff")
            return self._response(
                "Release checklist completed after human approval.", sequence=sequence
            )

        if sequence == 6:
            user_text = str(_latest(messages, "user").get("content", ""))
            _require(
                "Release checklist completed" in user_text,
                "final Tester did not receive the resumed-step handoff",
            )
            return self._response("PASS\nThe end-to-end artifact is valid.", sequence=sequence)

        raise SmokeFailure(f"unexpected model request #{sequence}; workflow should need exactly 6")


def _handler_for(model: _ScriptedModel) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                payload = json.loads(raw)
                _require(isinstance(payload, dict), "chat payload must be an object")
                response = model.complete(payload)
                body = json.dumps(response).encode()
                self.send_response(200)
            except Exception as exc:  # surfaced to Docket as an endpoint failure
                body = json.dumps({"error": {"message": f"{type(exc).__name__}: {exc}"}}).encode()
                self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            del args

    return Handler


@contextmanager
def _model_endpoint(model: _ScriptedModel) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(model))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = server.server_address
    host_raw, port = address[0], address[1]
    host = host_raw.decode() if isinstance(host_raw, bytes) else host_raw
    try:
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _run_cli(repo: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    print(f"\n$ docket {' '.join(args)}", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr, flush=True)
    if result.returncode != 0:
        raise SmokeFailure(f"docket {' '.join(args)} exited {result.returncode}")
    return result


def _write_inputs(world: Path) -> tuple[Path, Path, Path, Path]:
    home = world / ".docket"
    codebase = world / "codebase"
    codebase.mkdir(parents=True, exist_ok=True)
    (codebase / "README.md").write_text("# Docket smoke world\n", encoding="utf-8")

    pod_spec = world / "pod.json"
    pod_spec.write_text(
        json.dumps(
            {
                "id": "smoke",
                "blueprint": "agentic-product",
                "codebase": str(codebase),
                "stack": "Python",
                "description": "Exercise the complete Docket workflow.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    pipeline = world / "smoke.pipeline.yaml"
    pipeline.write_text(
        r"""name: end-to-end-smoke
description: Observable full workflow with every gate family.
steps:
  - id: plan
    role: lead
  - id: implement
    role: implementer
    gate:
      type: mechanical
      command: "test -f smoke-artifact.txt"
  - id: review
    role: reviewer
    gate:
      type: verdict
      pattern: '^\s*(APPROVE|REQUEST-CHANGES)\b'
      passValues: [approve]
      rework:
        to: implement
        when: [request-changes]
        maxCycles: 1
  - id: release-check
    role: tester
    gate:
      type: approval
      message: "Approve the smoke release checkpoint."
  - id: verify
    role: tester
    gate:
      type: verdict
      pattern: '^\s*(PASS|FAIL)\b'
      passValues: [pass]
""",
        encoding="utf-8",
    )
    return home, codebase, pod_spec, pipeline


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SmokeFailure(f"{path} did not contain a JSON object")
    return cast(dict[str, Any], data)


def _task(home: Path) -> dict[str, Any]:
    path = home / "workspaces" / "projects" / "smoke-lead" / "TASK_LIST.json"
    tasks = _load_json(path).get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1:
        raise SmokeFailure("expected one persisted smoke task")
    task = tasks[0]
    if not isinstance(task, dict):
        raise SmokeFailure("persisted smoke task is not an object")
    return cast(dict[str, Any], task)


def _verify_sessions(home: Path) -> None:
    session_files = sorted((home / "sessions").glob("*/session.json"))
    _require(
        len(session_files) == 5, f"expected 5 step-scoped sessions, found {len(session_files)}"
    )
    records = [_load_json(path) for path in session_files]
    implementer = next(
        (
            record
            for record in records
            if any(
                isinstance(message, dict) and message.get("toolCalls")
                for message in record.get("messages", [])
            )
        ),
        None,
    )
    if implementer is None:
        raise SmokeFailure("no durable session retained the Implementer tool call")
    messages_raw = implementer.get("messages", [])
    if not isinstance(messages_raw, list):
        raise SmokeFailure("Implementer session messages are not a list")
    messages = messages_raw
    tool_call_index = next(
        i
        for i, message in enumerate(messages)
        if isinstance(message, dict) and message.get("toolCalls")
    )
    _require(tool_call_index + 1 < len(messages), "persisted tool call has no following result")
    tool_result = messages[tool_call_index + 1]
    _require(
        isinstance(tool_result, dict)
        and tool_result.get("role") == "tool"
        and tool_result.get("toolCallId") == "smoke-write",
        "tool call/result did not persist as one adjacent atomic unit",
    )
    measured = sum(int(record.get("usage", {}).get("inputTokens", 0)) for record in records)
    _require(measured > 0, "endpoint token usage was not persisted")


def _verify_final_state(world: Path, home: Path, model: _ScriptedModel) -> None:
    artifact = world / "codebase" / "smoke-artifact.txt"
    _require(artifact.read_text(encoding="utf-8") == "docket smoke ok\n", "artifact mismatch")

    task = _task(home)
    _require(task.get("status") == "done", f"task ended as {task.get('status')!r}, not done")
    hops_raw = task.get("hops")
    if not isinstance(hops_raw, list) or not all(isinstance(hop, dict) for hop in hops_raw):
        raise SmokeFailure("task has no valid persisted hops")
    hops = cast(list[dict[str, Any]], hops_raw)
    _require(
        [hop.get("stepId") for hop in hops]
        == ["plan", "implement", "review", "release-check", "verify"],
        "pipeline did not resume at the exact approval-gated step",
    )
    _require(all(isinstance(hop.get("artifact"), dict) for hop in hops), "typed handoff missing")
    _require(hops[2]["artifact"].get("verdict") == "approve", "Reviewer verdict not persisted")
    _require(hops[4]["artifact"].get("verdict") == "pass", "Tester verdict not persisted")

    _verify_sessions(home)
    _require(len(model.requests) == 6, f"expected 6 model requests, got {len(model.requests)}")

    trace_files = sorted((home / "traces" / "smoke").glob("*.jsonl"))
    _require(bool(trace_files), "no trace files were persisted")
    event_types = {
        json.loads(line).get("event_type")
        for path in trace_files
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    for expected in (
        "session_start",
        "tool_call",
        "tool_result",
        "approval_required",
        "approval_resumed",
        "session_end",
    ):
        _require(expected in event_types, f"trace is missing {expected!r}")

    runs_raw = _load_json(home / "docket-runs.json").get("runs")
    if not isinstance(runs_raw, list) or not all(isinstance(run, dict) for run in runs_raw):
        raise SmokeFailure("dispatch run registry is malformed")
    runs = cast(list[dict[str, Any]], runs_raw)
    _require(len(runs) == 2, "expected two dispatch run records")
    _require(all(run.get("state") == "succeeded" for run in runs), "a dispatch run did not succeed")
    _require((home / "audit.log").is_file(), "audit log was not created")


def _run(world: Path, repo: Path) -> None:
    home, _codebase, pod_spec, pipeline = _write_inputs(world)
    model = _ScriptedModel()

    with _model_endpoint(model) as endpoint:
        env = os.environ.copy()
        env.update(
            {
                "DOCKET_HOME": str(home),
                "DOCKET_LLM_BASE_URL": endpoint,
                "DOCKET_LLM_API_KEY": "smoke-local",
                "DOCKET_SERVICE_MANAGER": "none",
                "DOCKET_LOG_DIR": str(world / "logs"),
                "DISPATCH_RETRY_BACKOFF_S": "0",
                "NO_COLOR": "1",
                "NO_PROXY": "127.0.0.1,localhost",
                "PYTHONUNBUFFERED": "1",
                "no_proxy": "127.0.0.1,localhost",
            }
        )

        print(f"Docket smoke world: {world}")
        print(f"Deterministic endpoint: {endpoint} (loopback only)")

        _run_cli(repo, env, "add", "--from", str(pod_spec))
        fleet = _load_json(home / "fleet.json")
        _require(len(fleet.get("agents", [])) == 4, "full pod did not provision four members")
        print("[check] full pod provisioned: lead, implementer, reviewer, tester")

        _run_cli(
            repo,
            env,
            "pod",
            "smoke",
            "delegate",
            "Create smoke-artifact.txt through the Docket tool path.",
        )
        _run_cli(repo, env, "pipeline", "plan", "smoke", "--file", str(pipeline))
        _run_cli(
            repo,
            env,
            "pipeline",
            "run",
            "smoke",
            "--file",
            str(pipeline),
            "--follow",
            "--timeout",
            "30",
        )

        waiting = _task(home)
        _require(waiting.get("status") == "waiting_approval", "pipeline did not pause for approval")
        _require(len(waiting.get("hops", [])) == 3, "approval pause occurred at the wrong step")
        token = str(waiting.get("approvalToken") or "")
        _require(bool(token), "waiting task has no approval token")
        print("[check] tool write + mechanical check + reviewer verdict reached approval pause")

        _run_cli(repo, env, "approve", token)
        _run_cli(
            repo,
            env,
            "pipeline",
            "run",
            "smoke",
            "--file",
            str(pipeline),
            "--follow",
            "--timeout",
            "30",
        )
        print("[check] waiting_approval -> granted -> resumed at release-check -> done")

        _run_cli(repo, env, "pod", "smoke", "queue")
        _run_cli(repo, env, "runs", "list", "--project", "smoke", "--json")
        _run_cli(repo, env, "trace", "export", "smoke")
        _run_cli(repo, env, "cost", "smoke-implementer", "--json")
        _run_cli(repo, env, "audit", "verify")

    _verify_final_state(world, home, model)
    print("[check] typed handoffs and verdicts persisted for all five steps")
    print("[check] five isolated step histories retain measured usage")
    print("[check] tool call/result persisted atomically")
    print("[check] traces, audit chain, and two run records are queryable")
    print("\nSMOKE PASS — complete Docket workflow is operational")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        type=Path,
        help="Preserve the smoke world at this new or empty directory for inspection.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo = Path(__file__).resolve().parents[1]
    temp: tempfile.TemporaryDirectory[str] | None = None
    if args.workdir is None:
        temp = tempfile.TemporaryDirectory(prefix="docket-smoke-")
        world = Path(temp.name)
    else:
        world = args.workdir.expanduser().resolve()
        if world.exists() and any(world.iterdir()):
            print(f"SMOKE FAIL — --workdir must be new or empty: {world}", file=sys.stderr)
            return 2
        world.mkdir(parents=True, exist_ok=True)

    try:
        _run(world, repo)
    except (SmokeFailure, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"\nSMOKE FAIL — {exc}", file=sys.stderr)
        if temp is not None:
            print("Rerun with --workdir PATH to preserve failed state.", file=sys.stderr)
            temp.cleanup()
        else:
            print(f"Inspect state at: {world}", file=sys.stderr)
        return 1

    if temp is not None:
        print("Smoke world was temporary; rerun with --workdir PATH to preserve it.")
        temp.cleanup()
    else:
        print(f"Preserved smoke world: {world}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
