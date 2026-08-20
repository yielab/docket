#!/usr/bin/env python3
"""Run one observable Docket workflow through the real CLI and HTTP adapter.

The default endpoint is deterministic and loopback-only so the command is suitable for CI.
``--live-model`` instead defaults to a realistic memory-backed code repair against a real loopback
model (port 8081 by default), without scripting its replies. ``--scenario basic`` retains the
smaller live infrastructure diagnostic. Everything on Docket's side is production in every mode:
CLI subprocesses, persisted state, endpoint resolution, the chat-completions adapter,
``DocketDriver``, the agent loop, gated tools, pipeline gates, resume, sessions, traces and audit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit


class SmokeFailure(RuntimeError):
    """A smoke assertion or subprocess failed."""


_BASIC_SCENARIO = "basic"
_MEMORY_SCENARIO = "memory-maintenance"
_SCENARIOS = (_BASIC_SCENARIO, _MEMORY_SCENARIO)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


@dataclass(frozen=True)
class _LiveModel:
    endpoint: str
    model_id: str
    context_tokens: int | None = None


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


def _loopback_endpoint(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    _require(parsed.scheme in {"http", "https"}, "live endpoint must use http or https")
    _require(
        parsed.username is None and parsed.password is None,
        "live endpoint must not embed credentials",
    )
    host = (parsed.hostname or "").lower()
    _require(
        host == "localhost" or host == "::1" or host.startswith("127."),
        "live smoke accepts only an explicit loopback endpoint",
    )
    _require(
        not parsed.query and not parsed.fragment, "live endpoint must not contain query or fragment"
    )
    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _discover_live_model(endpoint: str, requested_model: str | None) -> _LiveModel:
    normalized = _loopback_endpoint(endpoint)
    request = urllib.request.Request(
        f"{normalized}/models", headers={"Accept": "application/json"}, method="GET"
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise SmokeFailure(f"cannot discover a model at {normalized}: {exc}") from exc
    _require(isinstance(payload, dict), "live /models response was not a JSON object")

    entries: list[dict[str, Any]] = []
    for field in ("data", "models"):
        raw_entries = payload.get(field)
        if isinstance(raw_entries, list):
            entries.extend(
                cast(dict[str, Any], item) for item in raw_entries if isinstance(item, dict)
            )

    candidates: list[str] = []
    for entry in entries:
        candidate = str(entry.get("id") or entry.get("model") or entry.get("name") or "").strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    selected = (requested_model or "").strip()
    if not selected:
        _require(bool(candidates), "live /models response did not identify a loaded model")
        _require(
            len(candidates) == 1,
            "live endpoint exposes multiple models; select one explicitly with --model",
        )
        selected = candidates[0]

    context_tokens: int | None = None
    for entry in entries:
        candidate = str(entry.get("id") or entry.get("model") or entry.get("name") or "").strip()
        if candidate != selected:
            continue
        meta = entry.get("meta")
        raw_context = meta.get("n_ctx") if isinstance(meta, dict) else entry.get("context_length")
        if isinstance(raw_context, int) and raw_context > 0:
            context_tokens = raw_context
            break
    return _LiveModel(normalized, selected, context_tokens)


def _run_cli(
    repo: Path,
    env: dict[str, str],
    *args: str,
    process_timeout: float | None = 45,
) -> subprocess.CompletedProcess[str]:
    print(f"\n$ docket {' '.join(args)}", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=process_timeout,
        check=False,
    )
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr, flush=True)
    if result.returncode != 0:
        raise SmokeFailure(f"docket {' '.join(args)} exited {result.returncode}")
    return result


@contextmanager
def _approve_live_tool_calls(repo: Path, env: dict[str, str], home: Path) -> Iterator[list[str]]:
    """Act as the canary operator for in-turn bash approvals in its isolated home.

    The model remains free to choose its tools. When Docket's real policy creates
    a pending bash approval, this monitor grants it through the public CLI, just
    as an operator would. Pipeline approval records are deliberately ignored and
    remain controlled by the main workflow's explicit pause/resume assertion.
    """
    stop = threading.Event()
    granted: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    implementer_meta = _load_json(
        home / "workspaces" / "projects" / "smoke-implementer" / ".docket-meta.json"
    )
    allowed_worktree = str(implementer_meta.get("worktreeDir", "")).lower()

    def monitor() -> None:
        approvals_dir = home / "approvals"
        while not stop.wait(0.1):
            for path in sorted(approvals_dir.glob("*.json")):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict) or record.get("state") != "pending":
                    continue
                context = record.get("context")
                if not isinstance(context, dict) or context.get("tool") != "bash":
                    continue
                token = str(record.get("token", ""))
                project = str(record.get("project", ""))
                if not token or token in seen or not project.startswith("smoke-"):
                    continue
                seen.add(token)
                action = str(record.get("action", ""))
                action_lower = action.lower()
                if allowed_worktree:
                    action_lower = action_lower.replace(allowed_worktree, "<implementer-worktree>")
                private_markers = (".docket", "heartbeat.md", "memory.md", "/memory/")
                if any(marker in action_lower for marker in private_markers):
                    try:
                        _run_cli(repo, env, "deny", token, process_timeout=30)
                    except (OSError, subprocess.SubprocessError, SmokeFailure) as exc:
                        errors.append(f"{token}: could not deny private-state tool call: {exc}")
                        continue
                    errors.append(f"{token}: model attempted private-state access: {action}")
                    print(f"[operator] denied private-state tool approval: {token}", flush=True)
                    continue
                try:
                    _run_cli(repo, env, "approve", token, process_timeout=30)
                except (OSError, subprocess.SubprocessError, SmokeFailure) as exc:
                    errors.append(f"{token}: {exc}")
                    continue
                granted.append(token)
                print(f"[operator] granted isolated canary tool approval: {token}", flush=True)

    thread = threading.Thread(target=monitor, name="smoke-approval-operator", daemon=True)
    thread.start()
    try:
        yield granted
    finally:
        stop.set()
        thread.join(timeout=5)
        if thread.is_alive():
            errors.append("approval monitor did not stop")
        if errors:
            raise SmokeFailure("live tool approval monitor failed: " + "; ".join(errors))


def _write_realistic_codebase(codebase: Path, acceptance: Path) -> None:
    """Seed a maintenance task whose decisive rules are absent from the repo."""
    (codebase / "src").mkdir(parents=True)
    (codebase / "tests").mkdir()
    (codebase / ".gitignore").write_text("__pycache__/\n*.py[cod]\n", encoding="utf-8")
    (codebase / "README.md").write_text(
        """# Checkout service

This tiny service calculates invoice totals and produces receipt metadata.

Run its project-visible tests with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Keep the public function signatures stable. Durable product decisions are maintained by the pod
Lead rather than duplicated in this repository.
""",
        encoding="utf-8",
    )
    (codebase / "src" / "checkout.py").write_text(
        '''"""Checkout calculations and receipt metadata."""


def invoice_total(subtotal_cents: int, tax_basis_points: int) -> int:
    """Return the subtotal plus tax in cents."""
    tax_cents = round(subtotal_cents * tax_basis_points / 10_000)
    return subtotal_cents + tax_cents


def receipt_metadata(order_id: str) -> dict[str, str]:
    """Return stable metadata for a generated receipt."""
    return {"order_id": order_id}
''',
        encoding="utf-8",
    )
    (codebase / "tests" / "test_checkout.py").write_text(
        """import unittest

from checkout import invoice_total, receipt_metadata


class CheckoutTests(unittest.TestCase):
    def test_regular_invoice_total(self) -> None:
        self.assertEqual(invoice_total(10_000, 500), 10_500)

    def test_half_up_rounding_edge(self) -> None:
        self.assertEqual(invoice_total(500, 1_250), 563)

    def test_receipt_preserves_order_id(self) -> None:
        self.assertEqual(receipt_metadata("order-17")["order_id"], "order-17")

    def test_receipt_has_tenant_key(self) -> None:
        self.assertIn("tenant", receipt_metadata("order-17"))


if __name__ == "__main__":
    unittest.main()
""",
        encoding="utf-8",
    )
    acceptance.write_text(
        '''"""Canary-owned acceptance: intentionally outside the agent's project roots."""

from __future__ import annotations

import ast
from pathlib import Path

from checkout import invoice_total, receipt_metadata


assert invoice_total(1_001, 825) == 1_084, "half-up boundary was not preserved"
metadata = receipt_metadata("order-17")
assert metadata == {"order_id": "order-17", "tenant": "cobalt-7"}, metadata

source = Path.cwd() / "src" / "checkout.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
assert not any(isinstance(node, ast.Div) for node in ast.walk(tree)), (
    "checkout arithmetic still uses true division rather than integer math"
)
assert not any(
    isinstance(node, ast.Constant) and isinstance(node.value, float) for node in ast.walk(tree)
)
''',
        encoding="utf-8",
    )


def _verify_realistic_fixture_is_red(codebase: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=codebase,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    evidence = result.stdout + result.stderr
    _require(result.returncode != 0, "realistic fixture unexpectedly started green")
    for regression in ("test_half_up_rounding_edge", "test_receipt_has_tenant_key"):
        _require(regression in evidence, f"fixture did not exercise {regression}")
    _require("FAILED (failures=2)" in evidence, "fixture failed for unexpected reasons")


def _initialize_fixture_repo(codebase: Path) -> None:
    commands = (
        ("git", "init", "--quiet"),
        ("git", "config", "user.name", "Docket Smoke"),
        ("git", "config", "user.email", "smoke@invalid.example"),
        ("git", "add", "."),
        ("git", "commit", "--quiet", "-m", "Seed failing checkout regressions"),
    )
    for command in commands:
        result = subprocess.run(command, cwd=codebase, text=True, capture_output=True, check=False)
        _require(
            result.returncode == 0,
            f"could not prepare realistic git fixture: {result.stdout}{result.stderr}",
        )


def _write_inputs(world: Path, scenario: str) -> tuple[Path, Path, Path, Path]:
    home = world / ".docket"
    codebase = world / "codebase"
    codebase.mkdir(parents=True, exist_ok=True)
    acceptance = world / "checkout_acceptance.py"
    if scenario == _MEMORY_SCENARIO:
        _write_realistic_codebase(codebase, acceptance)
    else:
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

    if scenario == _MEMORY_SCENARIO:
        verify_command = (
            "PYTHONPATH=src python -m unittest discover -s tests -v && "
            f"PYTHONPATH=src python {shlex.quote(str(acceptance))}"
        )
        pipeline_description = (
            "Realistic memory-backed maintenance workflow with every gate family."
        )
    else:
        verify_command = 'test "$(cat smoke-artifact.txt)" = "docket smoke ok"'
        pipeline_description = "Observable full workflow with every gate family."

    pipeline = world / "smoke.pipeline.yaml"
    pipeline.write_text(
        f"""name: end-to-end-smoke
description: {pipeline_description}
steps:
  - id: plan
    role: lead
  - id: implement
    role: implementer
    gate:
      type: mechanical
      command: {json.dumps(verify_command)}
  - id: review
    role: reviewer
    gate:
      type: verdict
      pattern: '^\\s*(APPROVE|REQUEST-CHANGES)\\b'
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
      pattern: '^\\s*(PASS|FAIL)\\b'
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


def _verify_sessions(home: Path, *, memory_scenario: bool) -> None:
    session_files = sorted((home / "sessions").glob("*/session.json"))
    expected = 6 if memory_scenario else 5
    _require(
        len(session_files) == expected, f"expected {expected} sessions, found {len(session_files)}"
    )
    records = [_load_json(path) for path in session_files]
    mutating_tools = {"bash", "edit", "write"} if memory_scenario else {"write"}
    if memory_scenario:
        implementer_meta = _load_json(
            home / "workspaces" / "projects" / "smoke-implementer" / ".docket-meta.json"
        )
        allowed_worktree = str(implementer_meta.get("worktreeDir", "")).lower()
        for record in records:
            for message in record.get("messages", []):
                if not isinstance(message, dict):
                    continue
                for call in message.get("toolCalls", []):
                    if not isinstance(call, dict):
                        continue
                    arguments = str(call.get("arguments", "")).lower()
                    if allowed_worktree:
                        arguments = arguments.replace(allowed_worktree, "<implementer-worktree>")
                    private_markers = (".docket", "heartbeat.md", "memory.md", "/memory/")
                    _require(
                        not any(marker in arguments for marker in private_markers),
                        f"project tool attempted private-state access: {call.get('name')}",
                    )
    implementer = next(
        (
            record
            for record in records
            if any(
                isinstance(message, dict)
                and any(
                    isinstance(call, dict) and call.get("name") in mutating_tools
                    for call in message.get("toolCalls", [])
                )
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
    tool_call_index = -1
    write_call_id = ""
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        calls = message.get("toolCalls")
        if not isinstance(calls, list):
            continue
        mutating_call = next(
            (
                call
                for call in calls
                if isinstance(call, dict) and str(call.get("name", "")) in mutating_tools
            ),
            None,
        )
        if isinstance(mutating_call, dict):
            tool_call_index = index
            write_call_id = str(mutating_call.get("id", ""))
            break
    _require(tool_call_index >= 0 and bool(write_call_id), "no durable write tool call was found")
    _require(tool_call_index + 1 < len(messages), "persisted tool call has no following result")
    tool_result = messages[tool_call_index + 1]
    _require(
        isinstance(tool_result, dict)
        and tool_result.get("role") == "tool"
        and tool_result.get("toolCallId") == write_call_id,
        "tool call/result did not persist as one adjacent atomic unit",
    )
    measured = sum(int(record.get("usage", {}).get("inputTokens", 0)) for record in records)
    _require(measured > 0, "endpoint token usage was not persisted")


def _normalized_fact_text(text: str) -> str:
    return re.sub(r"[\s,_`]+", "", text.lower())


def _seed_memory_logs(home: Path) -> Path:
    lead_ws = home / "workspaces" / "projects" / "smoke-lead"
    memory_dir = lead_ws / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "2026-08-17.md").write_text(
        """# Checkout incident notes

- [exact] MONEY-104: integer cents; tax uses `(subtotal_cents * tax_basis_points + 5_000) // 10_000`; binary floats are forbidden.
- META-201: receipt metadata tenant was temporarily `amber-2`.
- Transient note: a staging worker was restarted; do not retain this as product behavior.
""",
        encoding="utf-8",
    )
    (memory_dir / "2026-08-18.md").write_text(
        """# Checkout decision follow-up

- [exact] META-202 supersedes META-201: every receipt must use tenant `cobalt-7`, never `amber-2`.
- Keep the public APIs `invoice_total(subtotal_cents, tax_basis_points)` and
  `receipt_metadata(order_id)` stable.
- The MONEY-104 integer half-up rule remains active.
""",
        encoding="utf-8",
    )
    return lead_ws


def _verify_distilled_memory(lead_ws: Path) -> None:
    pending = sorted((lead_ws / "memory").glob("*.md"))
    _require(not pending, "daily memory logs remained pending after distillation")
    archived = sorted((lead_ws / "memory" / ".distilled").glob("*/*.md"))
    archived_names = {path.name for path in archived}
    expected_names = {"2026-08-17.md", "2026-08-18.md"}
    _require(
        expected_names <= archived_names,
        f"scenario memory logs were not both archived: {sorted(archived_names)}",
    )
    memory_text = (lead_ws / "MEMORY.md").read_text(encoding="utf-8")
    facts = _normalized_fact_text(memory_text)
    for expected_fact in ("cobalt-7", "5000", "10000", "integer"):
        _require(expected_fact in facts, f"distilled MEMORY.md lost {expected_fact!r}")


def _verify_memory_maintenance(world: Path, home: Path, task: dict[str, Any]) -> None:
    hops = cast(list[dict[str, Any]], task["hops"])
    lead_artifact = cast(dict[str, Any], hops[0]["artifact"])
    lead_facts = _normalized_fact_text(str(lead_artifact.get("summary", "")))
    for expected_fact in ("cobalt-7", "5000", "10000", "integer"):
        _require(expected_fact in lead_facts, f"Lead handoff lost {expected_fact!r}")

    implementer_meta = _load_json(
        home / "workspaces" / "projects" / "smoke-implementer" / ".docket-meta.json"
    )
    effective_checkout = Path(
        str(implementer_meta.get("worktreeDir") or implementer_meta.get("codebase") or "")
    )
    _require(effective_checkout.is_dir(), "Implementer has no effective checkout")
    acceptance = subprocess.run(
        [sys.executable, str(world / "checkout_acceptance.py")],
        cwd=effective_checkout,
        env={**os.environ, "PYTHONPATH": str(effective_checkout / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    _require(
        acceptance.returncode == 0,
        f"hidden checkout acceptance failed: {acceptance.stdout}{acceptance.stderr}",
    )


def _verify_final_state(
    world: Path,
    home: Path,
    model: _ScriptedModel | None,
    scenario: str,
) -> None:
    if scenario == _BASIC_SCENARIO:
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

    memory_scenario = scenario == _MEMORY_SCENARIO
    _verify_sessions(home, memory_scenario=memory_scenario)
    if memory_scenario:
        _verify_memory_maintenance(world, home, task)
    if model is not None:
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


def _configure_live_model(repo: Path, env: dict[str, str], live: _LiveModel) -> None:
    provider_args = [
        "models",
        "provider",
        "add",
        "smoke-local",
        live.endpoint,
        "--model",
        live.model_id,
        "--name",
        "Live smoke model",
    ]
    if live.context_tokens is not None:
        provider_args.extend(["--ctx", str(live.context_tokens)])
    _run_cli(repo, env, *provider_args, process_timeout=None)

    model_ref = f"smoke-local/{live.model_id}"
    for role in ("manager", "programmer", "reviewer", "tester"):
        _run_cli(repo, env, "models", "set", role, model_ref, process_timeout=None)
    _run_cli(repo, env, "models", "set", "default", model_ref, process_timeout=None)


def _run(
    world: Path,
    repo: Path,
    live: _LiveModel | None = None,
    scenario: str = _BASIC_SCENARIO,
) -> None:
    home, codebase, pod_spec, pipeline = _write_inputs(world, scenario)
    model: _ScriptedModel | None
    endpoint_context: AbstractContextManager[str]
    if live is None:
        model = _ScriptedModel()
        endpoint_context = _model_endpoint(model)
    else:
        model = None
        endpoint_context = nullcontext(live.endpoint)

    with endpoint_context as endpoint:
        env = os.environ.copy()
        env.update(
            {
                "DOCKET_HOME": str(home),
                "DOCKET_SERVICE_MANAGER": "none",
                "DOCKET_LOG_DIR": str(world / "logs"),
                "NO_COLOR": "1",
                "NO_PROXY": "127.0.0.1,localhost",
                "PYTHONUNBUFFERED": "1",
                "no_proxy": "127.0.0.1,localhost",
            }
        )
        if live is None:
            env.update(
                {
                    "DOCKET_LLM_BASE_URL": endpoint,
                    "DOCKET_LLM_API_KEY": "smoke-local",
                    "DISPATCH_RETRY_BACKOFF_S": "0",
                }
            )
        else:
            for inherited in (
                "DOCKET_LLM_BASE_URL",
                "DOCKET_LLM_API_KEY",
                "SMOKE_LOCAL_API_KEY",
            ):
                env.pop(inherited, None)

        process_timeout: float | None = 45 if live is None else None

        def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
            return _run_cli(repo, env, *args, process_timeout=process_timeout)

        print(f"Docket smoke world: {world}")
        if live is None:
            print(f"Deterministic endpoint: {endpoint} (loopback only)")
        else:
            print(f"Real model endpoint: {endpoint} (loopback only)")
            print(f"Loaded model: {live.model_id}")
            if live.context_tokens is not None:
                print(f"Reported context window: {live.context_tokens:,} tokens")
            _configure_live_model(repo, env, live)

        if scenario == _MEMORY_SCENARIO:
            _verify_realistic_fixture_is_red(codebase)
            print("[check] pre-existing regressions fail for the intended checkout defects")
            _initialize_fixture_repo(codebase)
            print("[check] realistic checkout fixture committed before worktree provisioning")

        run_cli("add", "--from", str(pod_spec))
        fleet = _load_json(home / "fleet.json")
        _require(len(fleet.get("agents", [])) == 4, "full pod did not provision four members")
        print("[check] full pod provisioned: lead, implementer, reviewer, tester")

        if scenario == _MEMORY_SCENARIO:
            lead_ws = _seed_memory_logs(home)
            run_cli("maintain", "smoke-lead", "distill")
            _verify_distilled_memory(lead_ws)
            print("[check] memory logs distilled and archived with current decisions retained")

        if scenario == _MEMORY_SCENARIO:
            task_description = (
                "Diagnose and repair the checkout calculation and receipt metadata so they comply "
                "with the Lead's current durable project decisions. Keep both public function "
                "signatures stable, make the existing failing regression suite pass, and validate "
                "the behavior. Do not copy private memory logs into the repository."
            )
        else:
            task_description = (
                "Create smoke-artifact.txt in the workspace with exactly one line: docket smoke "
                "ok. The Implementer must create it through Docket's write tool; keep the change "
                "limited to that artifact, then review and verify the result."
            )
        run_cli("pod", "smoke", "delegate", task_description)
        run_cli("pipeline", "plan", "smoke", "--file", str(pipeline))
        first_run = [
            "pipeline",
            "run",
            "smoke",
            "--file",
            str(pipeline),
            "--follow",
        ]
        if live is None:
            first_run.extend(["--timeout", "30"])
        approval_context: AbstractContextManager[list[str]]
        if scenario == _MEMORY_SCENARIO:
            approval_context = _approve_live_tool_calls(repo, env, home)
        else:
            approval_context = nullcontext([])
        with approval_context as tool_approvals:
            run_cli(*first_run)

            waiting = _task(home)
            _require(
                waiting.get("status") == "waiting_approval",
                "pipeline did not pause for approval",
            )
            _require(len(waiting.get("hops", [])) == 3, "approval pause occurred at the wrong step")
            token = str(waiting.get("approvalToken") or "")
            _require(bool(token), "waiting task has no approval token")
            print("[check] tool write + mechanical check + reviewer verdict reached approval pause")

            run_cli("approve", token)
            second_run = [
                "pipeline",
                "run",
                "smoke",
                "--file",
                str(pipeline),
                "--follow",
            ]
            if live is None:
                second_run.extend(["--timeout", "30"])
            run_cli(*second_run)
        if tool_approvals:
            print(f"[check] operator granted {len(tool_approvals)} in-turn tool approval(s)")
        print("[check] waiting_approval -> granted -> resumed at release-check -> done")

        run_cli("pod", "smoke", "queue")
        run_cli("runs", "list", "--project", "smoke", "--json")
        run_cli("trace", "export", "smoke")
        run_cli("cost", "smoke-implementer", "--json")
        run_cli("audit", "verify")

    _verify_final_state(world, home, model, scenario)
    if scenario == _MEMORY_SCENARIO:
        print("[check] current durable decisions crossed the Lead handoff")
        print("[check] hidden checkout acceptance passed")
    print("[check] typed handoffs and verdicts persisted for all five steps")
    print("[check] five isolated step histories retain measured usage")
    print("[check] tool call/result persisted atomically")
    print("[check] traces, audit chain, and two run records are queryable")
    print("\nSMOKE PASS — complete Docket workflow is operational")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-model",
        action="store_true",
        help="Use genuine inference from a loopback OpenAI-compatible endpoint.",
    )
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:8081/v1",
        help="Loopback base URL for --live-model (default: http://127.0.0.1:8081/v1).",
    )
    parser.add_argument(
        "--model",
        help="Loaded model id for --live-model; by default it is discovered from /models.",
    )
    parser.add_argument(
        "--scenario",
        choices=_SCENARIOS,
        help=(
            "Scenario to run; defaults to memory-maintenance with --live-model and basic otherwise."
        ),
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        help="Preserve the smoke world at this new or empty directory for inspection.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.model and not args.live_model:
        print("SMOKE FAIL — --model requires --live-model", file=sys.stderr)
        return 2
    scenario = args.scenario or (_MEMORY_SCENARIO if args.live_model else _BASIC_SCENARIO)
    if scenario == _MEMORY_SCENARIO and not args.live_model:
        print("SMOKE FAIL — memory-maintenance requires --live-model", file=sys.stderr)
        return 2
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
        live = _discover_live_model(args.endpoint, args.model) if args.live_model else None
        _run(world, repo, live, scenario)
    except (
        SmokeFailure,
        OSError,
        ValueError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
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
