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
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum
from fnmatch import fnmatchcase
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit


class SmokeFailure(RuntimeError):
    """A smoke assertion or subprocess failed."""


_BASIC_SCENARIO = "basic"
_MEMORY_SCENARIO = "memory-maintenance"
_SCENARIOS = (_BASIC_SCENARIO, _MEMORY_SCENARIO)


def _basic_task_description() -> str:
    return (
        "Create smoke-artifact.txt in the workspace containing exactly the UTF-8 bytes "
        "docket smoke ok followed by one terminal LF, with no other bytes or lines. The "
        "Implementer must create it through Docket's write tool; keep the change limited to "
        "that artifact, then review and verify the result."
    )


def _memory_task_description() -> str:
    return (
        "Repair checkout calculation and receipt metadata per the Lead's current durable "
        "decisions. Each downstream role must use only the Lead's typed handoff. Never search or "
        "access Docket private control paths (MEMORY.md, HEARTBEAT.md, memory/, .docket) with "
        "project tools. Keep public APIs stable. Modify source only with edit/write. Only run "
        "exactly: PYTHONPATH=src python -m unittest discover -s tests -v. "
        "No alternatives, wrappers, inline code, or redirects. Never copy private logs."
    )


def _delegate_smoke_task(run_cli: Callable[..., object], scenario: str) -> None:
    if scenario == _MEMORY_SCENARIO:
        description = _memory_task_description()
    elif scenario == _BASIC_SCENARIO:
        description = _basic_task_description()
    else:
        raise SmokeFailure(f"unsupported smoke scenario: {scenario}")
    run_cli("pod", "smoke", "delegate", description)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


_PRIVATE_PATH_COMPONENTS = frozenset({".docket", "memory.md", "heartbeat.md", "memory"})
_PRIVATE_PATH_MARKERS = (".docket", "memory.md", "heartbeat.md", "memory")
_PATH_FIELD_TOOLS = frozenset({"read", "write", "edit"})
_KNOWN_PROJECT_TOOLS = _PATH_FIELD_TOOLS | {"glob", "grep", "bash"}
_MALFORMED_ARGUMENTS = "malformed-arguments"


class _ToolVerdictKind(StrEnum):
    ALLOWED = "allowed"
    CONFIRMED_PRIVATE = "confirmed_private"
    OPAQUE = "opaque"


@dataclass(frozen=True)
class _ToolVerdict:
    kind: _ToolVerdictKind
    marker: str | None = None

    @property
    def disqualifies(self) -> bool:
        return self.kind is not _ToolVerdictKind.ALLOWED


_ALLOWED_TOOL_VERDICT = _ToolVerdict(_ToolVerdictKind.ALLOWED)


def _path_violation_marker(
    value: str,
    allowed_project_roots: tuple[Path, ...],
    resolution_root: Path | None,
    containment_root: Path | None,
    *,
    selector: bool,
) -> str | None:
    candidate = value.strip().replace("\\", "/")
    if not candidate:
        return None
    candidate_path = Path(candidate)
    resolved: Path | None = None
    if candidate_path.is_absolute():
        resolved = candidate_path.resolve(strict=False)
    elif resolution_root is not None:
        resolved = (resolution_root / candidate_path).resolve(strict=False)
    if resolved is not None:
        if (
            selector
            and containment_root is not None
            and any(character in candidate for character in "*?[")
        ):
            try:
                resolved.relative_to(containment_root.resolve(strict=False))
            except ValueError:
                return ".docket"
        for root in sorted(
            (root.resolve(strict=False) for root in allowed_project_roots),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            try:
                candidate = resolved.relative_to(root).as_posix()
                break
            except ValueError:
                continue
        else:
            candidate = resolved.as_posix()
    for component in candidate.split("/"):
        marker = component.casefold()
        if marker in _PRIVATE_PATH_COMPONENTS:
            return marker
        if selector and marker not in {"*", "**"}:
            for private_marker in _PRIVATE_PATH_MARKERS:
                if fnmatchcase(private_marker, marker):
                    return private_marker
    return None


def _normalize_shell_newlines(command: str) -> str | None:
    normalized: list[str] = []
    quote: str | None = None
    escaped = False
    for character in command:
        if escaped:
            if character in "\r\n":
                return None
            normalized.append(character)
            escaped = False
            continue
        if character == "\\" and quote != "'":
            normalized.append(character)
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            normalized.append(character)
            continue
        if character in "\r\n" and quote is None:
            if not normalized or normalized[-1] != " ; ":
                normalized.append(" ; ")
            continue
        normalized.append(character)
    return "".join(normalized)


def _shell_path_candidates(command: str) -> list[str] | None:
    if "$(" in command or "`" in command or re.search(r"\$[{A-Za-z_]", command):
        return None
    normalized_command = _normalize_shell_newlines(command)
    if normalized_command is None:
        return None
    try:
        lexer = shlex.shlex(normalized_command, posix=True, punctuation_chars=";&|(){}")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens:
        return None
    if "<<" in command:
        return None
    command_boundaries = {"&&", "||", ";", "|", "&", "(", "{"}
    segment_boundaries = command_boundaries | {
        ")",
        "}",
    }
    if any(
        token
        and all(character in ";&|(){}" for character in token)
        and token not in segment_boundaries
        for token in tokens
    ):
        return None
    initial_command_positions = {0}
    initial_command_positions.update(
        index + 1 for index, token in enumerate(tokens[:-1]) if token in command_boundaries
    )
    command_positions: set[int] = set()
    for initial_position in initial_command_positions:
        position = initial_position
        while position < len(tokens):
            token = tokens[position]
            if token in {"(", "{"}:
                position += 1
                continue
            if token in segment_boundaries:
                return None
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
                position += 1
                continue
            executable = token.rsplit("/", 1)[-1].casefold()
            if executable == "env":
                position += 1
                while position < len(tokens):
                    option = tokens[position]
                    if option in segment_boundaries:
                        break
                    if option == "--":
                        position += 1
                        break
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", option):
                        position += 1
                        continue
                    if option in {"-i", "--ignore-environment", "-0", "--null"}:
                        position += 1
                        continue
                    if option.startswith("-"):
                        return None
                    break
                if position >= len(tokens) or tokens[position] in segment_boundaries:
                    command_positions.add(initial_position)
                    break
                continue
            if executable == "command":
                position += 1
                if position < len(tokens) and tokens[position] in {"-v", "-V"}:
                    command_positions.add(initial_position)
                    break
                while position < len(tokens) and tokens[position] in {"--", "-p"}:
                    position += 1
                if position >= len(tokens) or tokens[position] in segment_boundaries:
                    return None
                continue
            if executable in {"exec", "nohup"}:
                position += 1
                while position < len(tokens) and tokens[position] == "--":
                    position += 1
                if (
                    position >= len(tokens)
                    or tokens[position] in segment_boundaries
                    or tokens[position].startswith("-")
                ):
                    return None
                continue
            if executable == "uv" and position + 1 < len(tokens) and tokens[position + 1] == "run":
                position += 2
                while position < len(tokens) and tokens[position] == "--":
                    position += 1
                if (
                    position >= len(tokens)
                    or tokens[position] in segment_boundaries
                    or tokens[position].startswith("-")
                ):
                    return None
                continue
            if executable in {
                "busybox",
                "chroot",
                "docker",
                "ionice",
                "just",
                "make",
                "mise",
                "nice",
                "nox",
                "npm",
                "parallel",
                "pnpm",
                "podman",
                "poetry",
                "setsid",
                "stdbuf",
                "sudo",
                "task",
                "taskset",
                "time",
                "timeout",
                "tox",
                "watch",
                "xargs",
                "yarn",
            }:
                return None
            if executable == "find":
                segment = tokens[position + 1 :]
                if any(argument in {"-exec", "-execdir", "-ok", "-okdir"} for argument in segment):
                    return None
            command_positions.add(position)
            break
    for index in command_positions:
        if tokens[index].casefold() in {".", "eval", "source"}:
            return None
    inline_flags: dict[str, frozenset[str]] = {
        "awk": frozenset({"-f", "--file"}),
        "bun": frozenset({"-e", "--eval"}),
        "deno": frozenset({"eval"}),
        "gawk": frozenset({"-f", "--file"}),
        "lua": frozenset({"-e"}),
        "mawk": frozenset({"-f", "--file"}),
        "nawk": frozenset({"-f", "--file"}),
        "node": frozenset({"-e", "--eval", "-p", "--print"}),
        "nodejs": frozenset({"-e", "--eval", "-p", "--print"}),
        "perl": frozenset({"-e", "-E"}),
        "php": frozenset({"-r"}),
        "powershell": frozenset({"-command", "-encodedcommand"}),
        "pwsh": frozenset({"-command", "-encodedcommand"}),
        "ruby": frozenset({"-e"}),
    }
    for index in command_positions:
        token = tokens[index]
        executable = token.rsplit("/", 1)[-1].casefold()
        flags = inline_flags.get(executable)
        if re.fullmatch(r"(?:python|pypy)\d*(?:\.\d+)*", executable):
            flags = frozenset({"-c"})
        if flags is None:
            continue
        arguments = tokens[index + 1 :]
        segment_arguments: list[str] = []
        for argument in arguments:
            if argument in segment_boundaries:
                break
            segment_arguments.append(argument)
        if not segment_arguments or segment_arguments[0] == "-":
            return None
        is_python = bool(re.fullmatch(r"(?:python|pypy)\d*(?:\.\d+)*", executable))
        if is_python and "-m" in segment_arguments:
            if segment_arguments != ["-m", "unittest", "discover", "-s", "tests", "-v"]:
                return None
            continue
        position = 0
        while position < len(arguments):
            argument = arguments[position]
            if argument in segment_boundaries:
                break
            normalized_argument = argument.casefold()
            normalized_flags = {flag.casefold() for flag in flags}
            if normalized_argument in normalized_flags or any(
                flag.startswith("--") and normalized_argument.startswith(flag + "=")
                for flag in normalized_flags
            ):
                return None
            if any(
                len(flag) == 2
                and normalized_argument.startswith(flag)
                and len(normalized_argument) > 2
                for flag in normalized_flags
            ):
                return None
            if executable.startswith(("python", "pypy")) and argument in {"-X", "-W"}:
                position += 2
                continue
            if argument == "--":
                if position + 1 < len(arguments):
                    return None
                break
            if not argument.startswith("-"):
                return None
            if argument == "--version":
                break
            position += 1
    for index in command_positions:
        if tokens[index].rsplit("/", 1)[-1].casefold() in {"py.test", "pytest"}:
            return None
    candidates: list[str] = []
    shells = {"bash", "dash", "sh", "zsh"}
    nested_commands: dict[int, list[str]] = {}
    shell_option_values = {"--init-file", "--rcfile", "-O", "-o"}
    for shell_index in command_positions:
        token = tokens[shell_index]
        if token.rsplit("/", 1)[-1] not in shells:
            continue
        option_index = shell_index + 1
        found_command = False
        found_script = False
        while option_index < len(tokens):
            option = tokens[option_index]
            if option in segment_boundaries | {"--"}:
                break
            if not option.startswith("-"):
                found_script = True
                break
            is_command_option = option == "--command" or (
                not option.startswith("--") and "c" in option[1:]
            )
            if is_command_option:
                command_index = option_index + 1
                if command_index >= len(tokens):
                    return None
                nested = _shell_path_candidates(tokens[command_index])
                if nested is None:
                    return None
                nested_commands[command_index] = nested
                found_command = True
                break
            option_index += 2 if option in shell_option_values else 1
        if found_script or (not found_command and not found_script):
            return None
    for index, token in enumerate(tokens):
        if index in nested_commands:
            candidates.extend(nested_commands[index])
            continue
        for piece in re.split(r"[;&|()]+", token):
            candidate = re.sub(r"^\d*[<>]+", "", piece.strip())
            if not candidate:
                continue
            if "=" in candidate:
                prefix, value = candidate.split("=", 1)
                if prefix.startswith("-") or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", prefix):
                    candidate = value
            normalized_candidate = candidate.casefold().replace("\\", "/")
            if normalized_candidate == "/proc" or normalized_candidate.startswith("/proc/"):
                return None
            if normalized_candidate in {"/dev/stdin", "/dev/stdout", "/dev/stderr"} or (
                normalized_candidate == "/dev/fd" or normalized_candidate.startswith("/dev/fd/")
            ):
                return None
            if candidate and not candidate.startswith("-"):
                candidates.append(candidate)
    return candidates


def _selector_resolution_root(path: object, relative_project_root: Path | None) -> Path | None:
    if relative_project_root is None or not isinstance(path, str) or not path.strip():
        return relative_project_root
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return (relative_project_root / candidate).resolve(strict=False)


def _private_tool_violation(
    tool: str,
    raw_arguments: object,
    allowed_project_roots: tuple[Path, ...],
    *,
    relative_project_root: Path | None = None,
) -> str | None:
    normalized_tool = tool.casefold()
    if normalized_tool not in _KNOWN_PROJECT_TOOLS:
        return None
    if not isinstance(raw_arguments, str):
        return _MALFORMED_ARGUMENTS
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return _MALFORMED_ARGUMENTS
    if not isinstance(arguments, dict):
        return _MALFORMED_ARGUMENTS

    candidates: list[tuple[str, bool, Path | None]] = []
    if normalized_tool in _PATH_FIELD_TOOLS:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return _MALFORMED_ARGUMENTS
        candidates.append((path, False, relative_project_root))
    elif normalized_tool == "glob":
        pattern = arguments.get("pattern")
        path = arguments.get("path")
        if not isinstance(pattern, str) or (path is not None and not isinstance(path, str)):
            return _MALFORMED_ARGUMENTS
        if path:
            candidates.append((path, False, relative_project_root))
        selector_root = _selector_resolution_root(path, relative_project_root)
        if pattern:
            candidates.append((pattern, True, selector_root))
    elif normalized_tool == "grep":
        pattern = arguments.get("pattern")
        path = arguments.get("path")
        file_glob = arguments.get("glob")
        if (
            not isinstance(pattern, str)
            or (path is not None and not isinstance(path, str))
            or (file_glob is not None and not isinstance(file_glob, str))
        ):
            return _MALFORMED_ARGUMENTS
        if path:
            candidates.append((path, False, relative_project_root))
        selector_root = _selector_resolution_root(path, relative_project_root)
        if file_glob:
            candidates.append((file_glob, True, selector_root))
    else:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return _MALFORMED_ARGUMENTS
        shell_candidates = _shell_path_candidates(command)
        if shell_candidates is None:
            return _MALFORMED_ARGUMENTS
        candidates.extend(
            (candidate, True, relative_project_root) for candidate in shell_candidates
        )

    for candidate, selector, resolution_root in candidates:
        marker = _path_violation_marker(
            candidate,
            allowed_project_roots,
            resolution_root,
            relative_project_root,
            selector=selector,
        )
        if marker is not None:
            return marker
    return None


def _tool_verdict(
    tool: str,
    raw_arguments: object,
    allowed_project_roots: tuple[Path, ...],
    *,
    relative_project_root: Path | None = None,
) -> _ToolVerdict:
    """Classify one project-tool call without exposing its raw arguments."""
    marker = _private_tool_violation(
        tool,
        raw_arguments,
        allowed_project_roots,
        relative_project_root=relative_project_root,
    )
    if marker is None:
        return _ALLOWED_TOOL_VERDICT
    if marker == _MALFORMED_ARGUMENTS:
        return _ToolVerdict(_ToolVerdictKind.OPAQUE, marker)
    return _ToolVerdict(_ToolVerdictKind.CONFIRMED_PRIVATE, marker)


def _traced_tool_arguments(
    home: Path,
    call_id: str,
    *,
    tool: str,
    role: str,
) -> tuple[bool, object]:
    latest: tuple[tuple[int, str, int], object] | None = None
    for path in sorted((home / "traces" / "smoke").glob("*.jsonl")):
        modified = path.stat().st_mtime_ns
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or record.get("event_type") != "tool_call":
                continue
            payload = record.get("payload")
            if (
                not isinstance(payload, dict)
                or str(payload.get("callId", "")) != call_id
                or str(payload.get("tool", "")).casefold() != tool.casefold()
                or str(record.get("agent_role", "")).casefold() != role.casefold()
            ):
                continue
            key = (modified, path.name, line_number)
            if latest is None or key > latest[0]:
                latest = key, payload.get("arguments")
    if latest is None:
        return False, ""
    return True, latest[1]


def _approval_tool_verdict(
    home: Path,
    record: dict[str, Any],
    allowed_project_roots: tuple[Path, ...],
) -> tuple[bool, _ToolVerdict]:
    context = record.get("context")
    if not isinstance(context, dict):
        return True, _ToolVerdict(_ToolVerdictKind.OPAQUE, _MALFORMED_ARGUMENTS)
    tool = str(context.get("tool", ""))
    call_id = str(context.get("callId", ""))
    project = str(record.get("project", ""))
    role = str(record.get("role") or project.rsplit("-", 1)[-1])
    if tool.casefold() != "bash" or not call_id or not role:
        return True, _ToolVerdict(_ToolVerdictKind.OPAQUE, _MALFORMED_ARGUMENTS)
    found, raw_arguments = _traced_tool_arguments(
        home,
        call_id,
        tool=tool,
        role=role,
    )
    if not found:
        return False, _ALLOWED_TOOL_VERDICT
    relative_root = _relative_project_root(role, allowed_project_roots)
    return True, _tool_verdict(
        "bash",
        raw_arguments,
        allowed_project_roots,
        relative_project_root=relative_root,
    )


def _approval_private_tool_violation(
    home: Path,
    record: dict[str, Any],
    allowed_project_roots: tuple[Path, ...],
) -> tuple[bool, str | None]:
    """Compatibility projection for focused classifier tests."""
    resolved, verdict = _approval_tool_verdict(home, record, allowed_project_roots)
    return resolved, verdict.marker


def _relative_project_root(identity: object, allowed_project_roots: tuple[Path, ...]) -> Path:
    normalized = str(identity).casefold()
    if len(allowed_project_roots) > 1 and normalized.split("-")[-1] != "lead":
        return allowed_project_roots[1]
    return allowed_project_roots[0]


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
    abort_event: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    print(f"\n$ docket {' '.join(args)}", flush=True)
    command = [sys.executable, "-m", "docket", *args]
    if abort_event is not None and abort_event.is_set():
        raise SmokeFailure("docket subprocess blocked after canary disqualification")
    if abort_event is None:
        result = subprocess.run(
            command,
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            timeout=process_timeout,
            check=False,
        )
    else:
        process = subprocess.Popen(
            command,
            cwd=repo,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        started = time.monotonic()
        while True:
            if abort_event.is_set():
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                if stdout:
                    print(stdout.rstrip(), flush=True)
                if stderr:
                    print(stderr.rstrip(), file=sys.stderr, flush=True)
                raise SmokeFailure("docket subprocess stopped after canary disqualification")
            if process_timeout is not None and time.monotonic() - started >= process_timeout:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(command, process_timeout, stdout, stderr)
            try:
                stdout, stderr = process.communicate(timeout=0.1)
            except subprocess.TimeoutExpired:
                continue
            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            break
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr, flush=True)
    if result.returncode != 0:
        raise SmokeFailure(f"docket {' '.join(args)} exited {result.returncode}")
    return result


@dataclass
class _LiveApprovalState:
    granted: list[str] = dataclass_field(default_factory=list)
    abort: threading.Event = dataclass_field(default_factory=threading.Event)
    failures: list[str] = dataclass_field(default_factory=list)


def _tool_verdict_diagnostic(
    *,
    source: str,
    role: object,
    tool: object,
    call_id: object,
    verdict: _ToolVerdict,
) -> str:
    marker = verdict.marker or "none"
    return (
        f"source={source} role={role} tool={tool} callId={call_id} "
        f"verdict={verdict.kind.value} marker={marker}"
    )


def _cancel_active_smoke_run(repo: Path, env: dict[str, str]) -> str:
    result = _run_cli(
        repo,
        env,
        "runs",
        "list",
        "--project",
        "smoke",
        "--json",
        process_timeout=30,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeFailure("active smoke run lookup returned malformed JSON") from exc
    runs = payload.get("runs") if isinstance(payload, dict) else None
    active = next(
        (
            record
            for record in runs or []
            if isinstance(record, dict) and record.get("state") in {"queued", "running"}
        ),
        None,
    )
    run_id = str(active.get("id", "")) if isinstance(active, dict) else ""
    if not run_id:
        raise SmokeFailure("active smoke run was not found")
    _run_cli(repo, env, "runs", "cancel", run_id, process_timeout=30)
    return run_id


@contextmanager
def _approve_live_tool_calls(
    repo: Path, env: dict[str, str], home: Path
) -> Iterator[_LiveApprovalState]:
    """Act as the canary operator for in-turn bash approvals in its isolated home.

    The model remains free to choose its tools. When Docket's real policy creates
    a pending bash approval, this monitor grants it through the public CLI, just
    as an operator would. Pipeline approval records are deliberately ignored and
    remain controlled by the main workflow's explicit pause/resume assertion.
    """
    stop = threading.Event()
    state = _LiveApprovalState()
    seen: set[str] = set()
    allowed_project_roots = _smoke_allowed_project_roots(home)

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
                resolved, verdict = _approval_tool_verdict(
                    home,
                    record,
                    allowed_project_roots,
                )
                if not resolved:
                    continue
                seen.add(token)
                if verdict.disqualifies:
                    role = str(record.get("role") or project.rsplit("-", 1)[-1])
                    call_id = str(context.get("callId", "unknown"))
                    try:
                        _cancel_active_smoke_run(repo, env)
                    except (OSError, subprocess.SubprocessError, SmokeFailure) as exc:
                        del exc
                        state.failures.append(
                            _tool_verdict_diagnostic(
                                source="approval-cancel",
                                role=role,
                                tool="bash",
                                call_id=call_id,
                                verdict=_ToolVerdict(verdict.kind, "cancel-failed"),
                            )
                        )
                    state.abort.set()
                    try:
                        _run_cli(repo, env, "deny", token, process_timeout=30)
                    except (OSError, subprocess.SubprocessError, SmokeFailure) as exc:
                        del exc
                        state.failures.append(
                            _tool_verdict_diagnostic(
                                source="approval-deny",
                                role=role,
                                tool="bash",
                                call_id=call_id,
                                verdict=_ToolVerdict(verdict.kind, "deny-failed"),
                            )
                        )
                    state.failures.insert(
                        0,
                        _tool_verdict_diagnostic(
                            source="approval",
                            role=role,
                            tool="bash",
                            call_id=call_id,
                            verdict=verdict,
                        ),
                    )
                    print(
                        f"[operator] denied disqualifying {verdict.kind.value} tool approval",
                        flush=True,
                    )
                    return
                try:
                    _run_cli(repo, env, "approve", token, process_timeout=30)
                except (OSError, subprocess.SubprocessError, SmokeFailure) as exc:
                    del exc
                    state.failures.append(
                        _tool_verdict_diagnostic(
                            source="approval-grant",
                            role=str(record.get("role") or project.rsplit("-", 1)[-1]),
                            tool="bash",
                            call_id=str(context.get("callId", "unknown")),
                            verdict=_ToolVerdict(_ToolVerdictKind.OPAQUE, "approve-failed"),
                        )
                    )
                    continue
                state.granted.append(token)
                print(f"[operator] granted isolated canary tool approval: {token}", flush=True)

    thread = threading.Thread(target=monitor, name="smoke-approval-operator", daemon=True)
    thread.start()
    try:
        yield state
    finally:
        stop.set()
        thread.join(timeout=5)
        if thread.is_alive():
            state.failures.append(
                "source=approval-monitor role=unknown tool=unknown callId=unknown "
                "verdict=opaque marker=monitor-timeout"
            )
        if state.failures:
            raise SmokeFailure("live tool approval monitor failed: " + "; ".join(state.failures))


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
        verify_command = (
            'python -c "from pathlib import Path; import sys; '
            "sys.exit(Path('smoke-artifact.txt').read_bytes() != b'docket smoke ok\\n')\""
        )
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


def _smoke_allowed_project_roots(home: Path) -> tuple[Path, ...]:
    expected_codebase = (home.parent / "codebase").resolve(strict=False)
    expected_worktree = (
        home / "workspaces" / "projects" / "smoke-implementer" / "worktree"
    ).resolve(strict=False)
    implementer_meta = _load_json(
        home / "workspaces" / "projects" / "smoke-implementer" / ".docket-meta.json"
    )
    codebase = implementer_meta.get("codebase")
    worktree = implementer_meta.get("worktreeDir")
    _require(
        isinstance(codebase, str) and Path(codebase).resolve(strict=False) == expected_codebase,
        "Implementer metadata did not retain the isolated origin checkout",
    )
    _require(
        isinstance(worktree, str) and Path(worktree).resolve(strict=False) == expected_worktree,
        "Implementer metadata did not retain the isolated worktree",
    )
    return expected_codebase, expected_worktree


def _session_role(record: dict[str, Any]) -> str:
    session_key = str(record.get("sessionKey", ""))
    parts = session_key.split(":", 2)
    if len(parts) >= 2 and parts[0] == "agent" and parts[1]:
        return parts[1]
    return "unknown"


def _raise_private_tool_violation(
    *,
    source: str,
    role: object,
    tool: object,
    call_id: object,
    raw_arguments: object,
    allowed_project_roots: tuple[Path, ...],
) -> None:
    tool_name = str(tool)
    verdict = _tool_verdict(
        tool_name,
        raw_arguments,
        allowed_project_roots,
        relative_project_root=_relative_project_root(role, allowed_project_roots),
    )
    if not verdict.disqualifies:
        return
    raise SmokeFailure(
        _tool_verdict_diagnostic(
            source=source,
            role=role,
            tool=tool_name,
            call_id=call_id,
            verdict=verdict,
        )
    )


def _verify_private_tool_boundary(home: Path) -> None:
    allowed_project_roots = _smoke_allowed_project_roots(home)
    trace_files = sorted((home / "traces" / "smoke").glob("*.jsonl"))
    for path in trace_files:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SmokeFailure(
                    f"malformed durable trace: source=trace line={line_number}"
                ) from exc
            if not isinstance(record, dict) or record.get("event_type") != "tool_call":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or "tool" not in payload:
                continue
            _raise_private_tool_violation(
                source="trace",
                role=record.get("agent_role", "unknown"),
                tool=payload.get("tool", "unknown"),
                call_id=payload.get("callId", "unknown"),
                raw_arguments=payload.get("arguments"),
                allowed_project_roots=allowed_project_roots,
            )

    for path in sorted((home / "sessions").glob("*/session.json")):
        record = _load_json(path)
        messages = record.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            calls = message.get("toolCalls")
            if not isinstance(calls, list):
                continue
            for call in calls:
                if not isinstance(call, dict):
                    continue
                _raise_private_tool_violation(
                    source="session",
                    role=_session_role(record),
                    tool=call.get("name", "unknown"),
                    call_id=call.get("id", "unknown"),
                    raw_arguments=call.get("arguments"),
                    allowed_project_roots=allowed_project_roots,
                )


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
        _verify_private_tool_boundary(home)
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

        def run_cli(
            *args: str, abort_event: threading.Event | None = None
        ) -> subprocess.CompletedProcess[str]:
            return _run_cli(
                repo,
                env,
                *args,
                process_timeout=process_timeout,
                abort_event=abort_event,
            )

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

        run_cli("init", "--from", str(pod_spec))
        fleet = _load_json(home / "fleet.json")
        project_agents = [
            agent
            for agent in fleet.get("agents", [])
            if str(agent.get("id", "")).startswith("smoke-")
        ]
        _require(len(project_agents) == 4, "full pod did not provision four members")
        print("[check] full pod provisioned: lead, implementer, reviewer, tester")

        if scenario == _MEMORY_SCENARIO:
            lead_ws = _seed_memory_logs(home)
            run_cli("maintain", "smoke-lead", "distill")
            _verify_distilled_memory(lead_ws)
            print("[check] memory logs distilled and archived with current decisions retained")

        _delegate_smoke_task(run_cli, scenario)
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
        approval_context: AbstractContextManager[_LiveApprovalState]
        if scenario == _MEMORY_SCENARIO:
            approval_context = _approve_live_tool_calls(repo, env, home)
        else:
            approval_context = nullcontext(_LiveApprovalState())
        with approval_context as approval_state:
            canary_abort = approval_state.abort if scenario == _MEMORY_SCENARIO else None
            run_cli(*first_run, abort_event=canary_abort)

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
            run_cli(*second_run, abort_event=canary_abort)
        if approval_state.granted:
            print(
                f"[check] operator granted {len(approval_state.granted)} in-turn tool approval(s)"
            )
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
