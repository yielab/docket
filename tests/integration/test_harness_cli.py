"""``docket harness run``/``docket harness status``, driven as a real
``python -m docket`` subprocess against a loopback OpenAI-compatible stub.

Every test here spawns a real process rather than calling into
``cli._harness`` in-process: stdout-as-wire-protocol, SIGTERM handling and
home isolation are all properties of the *process*, not of a function call.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from tests.conftest import record_isolation_off

SUBJECT = "docket.cli._harness"

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── (f) isolation: the developer's real ~/.docket, byte-identical ───────────
#
# A module-scoped autouse fixture (not a per-test assertion) wraps every test
# below in one before/after snapshot -- the conftest guard patches in-process
# constants and never reaches a subprocess, so this is the only thing that
# actually proves a real "docket harness run" process cannot leak into it.


def _snapshot_real_home() -> dict[str, str]:
    home = Path.home() / ".docket"
    if not home.is_dir():
        return {}
    snapshot: dict[str, str] = {}
    for path in sorted(home.rglob("*")):
        if not path.is_file():
            continue
        try:
            snapshot[str(path.relative_to(home))] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            snapshot[str(path.relative_to(home))] = "<unreadable>"
    return snapshot


@pytest.fixture(scope="module", autouse=True)
def _real_docket_home_is_untouched() -> Iterator[None]:
    before = _snapshot_real_home()
    yield
    after = _snapshot_real_home()
    assert before == after, (
        "a `docket harness` subprocess touched the real ~/.docket -- every "
        "test in this module must pass DOCKET_HOME pointing at a tmp_path"
    )


# ── loopback OpenAI-compatible stub ──────────────────────────────────────────


def _tool_call_response(
    name: str, arguments: dict[str, Any], call_id: str = "call-1"
) -> dict[str, Any]:
    return {
        "model": "local/qwen3-stub-served",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def _final_response(text: str) -> dict[str, Any]:
    return {
        "model": "local/qwen3-stub-served",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10},
    }


class _ScriptedLLMServer:
    """A loopback ``ThreadingHTTPServer`` replaying a fixed script of
    OpenAI-compatible chat-completion bodies, one per POST."""

    def __init__(
        self,
        responses: list[dict[str, Any]],
        on_request: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        responses_ref = self.responses = list(responses)
        requests_ref = self.requests

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                requests_ref.append(json.loads(body.decode("utf-8")))
                if on_request is not None:
                    on_request(requests_ref[-1])
                index = min(len(requests_ref) - 1, len(responses_ref) - 1)
                payload = json.dumps(responses_ref[index]).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, fmt: str, *args: object) -> None:  # pragma: no cover - silence
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}/v1"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture()
def llm_server() -> Iterator[Any]:
    servers: list[_ScriptedLLMServer] = []

    def _start(
        responses: list[dict[str, Any]],
        on_request: Callable[[dict[str, Any]], None] | None = None,
    ) -> _ScriptedLLMServer:
        server = _ScriptedLLMServer(responses, on_request)
        servers.append(server)
        return server

    yield _start
    for server in servers:
        server.stop()


# ── subprocess plumbing ───────────────────────────────────────────────────────


def _child_env(
    home: Path, base_url: str | None, isolation_off: bool = True, **overrides: str
) -> dict[str, str]:
    if isolation_off:
        record_isolation_off(home)
    env = os.environ.copy()
    env.pop("DOCKET_HOME", None)
    env["DOCKET_HOME"] = str(home)
    if base_url is not None:
        env["DOCKET_LLM_BASE_URL"] = base_url
    else:
        env.pop("DOCKET_LLM_BASE_URL", None)
    env.pop("DOCKET_NO_TRACE", None)
    env["DOCKET_TOOL_MAX_OUTPUT_CHARS"] = "2500"
    env.update(overrides)
    return env


def _run_harness(
    args: list[str], env: dict[str, str], timeout: float = 30
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "docket", "harness", *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _parse_ndjson(stdout: str) -> list[dict[str, Any]]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _real_default_home() -> Path:
    return Path.home() / ".docket"


# ── (a) ok ────────────────────────────────────────────────────────────────────


class TestOkRun:
    def test_one_write_call_then_a_final_message(self, tmp_path: Path, llm_server: Any) -> None:
        server = llm_server(
            [
                _tool_call_response("write", {"path": "out.txt", "content": "hello"}),
                _final_response("done writing"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(
            [
                "run",
                "--workspace",
                str(workspace),
                "--task",
                "write hello to out.txt",
                "--model",
                "local/requested-id",
            ],
            env,
        )

        assert proc.returncode == 0, proc.stderr
        assert proc.stderr.strip() != ""
        lines = _parse_ndjson(proc.stdout)
        assert len(lines) >= 2
        *events, result = lines
        assert events, "expected at least one streamed event before the result"

        token = events[0]["token"]
        for line in lines:
            assert line["v"] == "1.0.0"
            assert line["token"] == token

        seqs = [e["seq"] for e in events]
        assert seqs == list(range(len(events)))

        event_types = [e["event"]["event_type"] for e in events]
        assert event_types[0] == "harness_start"
        assert event_types[1] == "session_start"
        assert "tool_call" in event_types
        assert "tool_result" in event_types
        assert event_types.index("tool_call") < event_types.index("tool_result")
        assert event_types[-1] == "session_end"

        assert result["status"] == "ok"
        assert result["model"]["requested"] == "local/requested-id"
        assert result["model"]["served"] == "local/qwen3-stub-served"
        assert result["usage"] == {
            "input_tokens": 150,
            "output_tokens": 30,
            "cached_tokens": 0,
            "turns": 2,
        }
        assert result["cost_usd"] is None
        assert result["run_state"] == "succeeded"

        run_record = json.loads((home / "docket-runs.json").read_text())["runs"][0]
        assert run_record["state"] == "succeeded"
        assert run_record["id"] == token

        assert [p.name for p in workspace.iterdir()] == ["out.txt"]
        assert (workspace / "out.txt").read_text() == "hello"

        for line in proc.stdout.splitlines():
            if line.strip():
                json.loads(line)  # never raises -- no non-JSON byte on stdout


# ── (a2) ok, contract 1.1 ────────────────────────────────────────────────────


class TestContract11Run:
    def test_contract_1_1_stamps_every_line_and_carries_empty_v11_fields(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [
                _tool_call_response("write", {"path": "out.txt", "content": "hello"}),
                _final_response("done writing"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(
            [
                "run",
                "--workspace",
                str(workspace),
                "--task",
                "write hello to out.txt",
                "--model",
                "local/requested-id",
                "--contract",
                "1.1",
            ],
            env,
        )

        assert proc.returncode == 0, proc.stderr
        lines = _parse_ndjson(proc.stdout)
        result = lines[-1]
        for line in lines:
            assert line["v"] == "1.1.0"

        assert result["status"] == "ok"
        assert result["files"] == [{"path": "out.txt", "op": "write"}]
        assert result["task"] is None
        assert result["limits"] == {"maxTokens": None}

    def test_an_unrecognized_contract_refuses_with_no_partial_output(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1", isolation_off=False)

        proc = _run_harness(
            [
                "run",
                "--workspace",
                str(workspace),
                "--task",
                "x",
                "--model",
                "local/x",
                "--contract",
                "2.0",
            ],
            env,
        )

        assert proc.returncode == 2, proc.stderr
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        assert len(lines) == 1
        result = json.loads(lines[0])
        assert result["status"] == "refused"
        assert "--contract" in result["error"]
        assert not (tmp_path / "home").exists()

    def test_a_bash_call_reports_process_lifecycle_events_on_the_v11_stream(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        """`_run`'s `with _trace.subscribe(_emit):` relays every trace event
        verbatim, so `process_started`/`process_exited` reach this stream
        with no harness-specific wiring at all."""
        server = llm_server(
            [
                _tool_call_response("bash", {"command": "echo hi"}),
                _final_response("done"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(
            [
                "run",
                "--workspace",
                str(workspace),
                "--task",
                "run echo hi",
                "--model",
                "local/requested-id",
                "--contract",
                "1.1",
            ],
            env,
        )

        assert proc.returncode == 0, proc.stderr
        lines = _parse_ndjson(proc.stdout)
        events = lines[:-1]
        for line in lines:
            assert line["v"] == "1.1.0"

        started = [e for e in events if e["event"]["event_type"] == "process_started"]
        exited = [e for e in events if e["event"]["event_type"] == "process_exited"]
        assert len(started) == 1
        assert len(exited) == 1
        started_payload = started[0]["event"]["payload"]
        exited_payload = exited[0]["event"]["payload"]
        assert started_payload["tool"] == "bash"
        assert isinstance(started_payload["pgid"], int)
        assert exited_payload["pgid"] == started_payload["pgid"]
        assert exited_payload["exitCode"] == 0
        assert "signal" not in exited_payload

        event_types = [e["event"]["event_type"] for e in events]
        assert event_types.index("process_started") < event_types.index("process_exited")


# ── (a3) written paths, token file, caller limits, policies (contract 1.1) ──


def _contract_11_args(workspace: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--workspace",
        str(workspace),
        "--task",
        "do the thing",
        "--model",
        "local/x",
        "--contract",
        "1.1",
        *extra,
    ]


class TestWrittenPathsAndLimits:
    def test_a_write_and_an_edit_are_both_listed_as_touched_files(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [
                _tool_call_response("write", {"path": "a.txt", "content": "alpha"}, "call-1"),
                _tool_call_response(
                    "edit",
                    {"path": "b.txt", "old_string": "old", "new_string": "new"},
                    "call-2",
                ),
                _final_response("done"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "b.txt").write_text("old text")
        env = _child_env(home, server.base_url)

        proc = _run_harness(_contract_11_args(workspace), env)

        assert proc.returncode == 0, proc.stderr
        result = _parse_ndjson(proc.stdout)[-1]
        assert sorted(result["files"], key=lambda f: f["path"]) == [
            {"path": "a.txt", "op": "write"},
            {"path": "b.txt", "op": "edit"},
        ]

    def test_an_untracked_file_written_by_bash_appears_in_a_git_workspace(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [
                _tool_call_response("bash", {"command": "touch made-by-bash.txt"}),
                _final_response("done"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
        env = _child_env(home, server.base_url)

        proc = _run_harness(_contract_11_args(workspace), env)

        assert proc.returncode == 0, proc.stderr
        result = _parse_ndjson(proc.stdout)[-1]
        assert {"path": "made-by-bash.txt", "op": "write"} in result["files"]

    def test_a_file_dirty_before_the_run_and_untouched_by_it_is_not_listed(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [
                _tool_call_response("write", {"path": "a.txt", "content": "alpha"}, "call-1"),
                _final_response("done"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
        (workspace / "already-dirty.txt").write_text("dirty before")
        env = _child_env(home, server.base_url)

        proc = _run_harness(_contract_11_args(workspace), env)

        assert proc.returncode == 0, proc.stderr
        paths = [f["path"] for f in _parse_ndjson(proc.stdout)[-1]["files"]]
        assert paths == ["a.txt"]

    def test_a_file_dirty_before_the_run_that_the_run_edits_is_listed(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [
                _tool_call_response(
                    "edit",
                    {"path": "already-dirty.txt", "old_string": "before", "new_string": "after"},
                    "call-1",
                ),
                _final_response("done"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
        (workspace / "already-dirty.txt").write_text("dirty before")
        env = _child_env(home, server.base_url)

        proc = _run_harness(_contract_11_args(workspace), env)

        assert proc.returncode == 0, proc.stderr
        files = _parse_ndjson(proc.stdout)[-1]["files"]
        assert {"path": "already-dirty.txt", "op": "edit"} in files

    def test_the_token_file_is_0600_and_complete_before_the_first_request(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        token_file = tmp_path / "run-token.json"
        seen: list[tuple[int, dict[str, Any]]] = []

        def _inspect(_body: dict[str, Any]) -> None:
            if not seen:
                mode = token_file.stat().st_mode & 0o777
                seen.append((mode, json.loads(token_file.read_text())))

        server = llm_server([_final_response("done")], on_request=_inspect)
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(_contract_11_args(workspace, "--token-file", str(token_file)), env)

        assert proc.returncode == 0, proc.stderr
        assert len(seen) == 1
        mode, content = seen[0]
        assert mode == 0o600
        assert content["v"] == "1.1.0"
        assert isinstance(content["pid"], int)
        result = _parse_ndjson(proc.stdout)[-1]
        assert content["token"] == result["token"]
        assert not list(tmp_path.glob("*.tmp"))

        stderr_lines = [
            line for line in proc.stderr.splitlines() if line.startswith("docket harness: run ")
        ]
        assert stderr_lines
        assert stderr_lines[0].split()[3] == content["token"]
        assert stderr_lines[0].split()[4].startswith("agent=")

    def test_max_tokens_stops_the_turn_on_the_token_bound(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [
                _tool_call_response("write", {"path": "a.txt", "content": "alpha"}),
                _final_response("done"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(_contract_11_args(workspace, "--max-tokens", "10"), env)

        assert proc.returncode == 1, proc.stderr
        result = _parse_ndjson(proc.stdout)[-1]
        assert result["status"] == "failed"
        assert "token_budget=10" in result["error"]
        assert result["limits"] == {"maxTokens": 10}
        assert len(server.requests) == 1

    def test_a_policy_that_blocks_bash_stops_the_call(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [
                _tool_call_response("bash", {"command": "touch ran.txt"}),
                _final_response("done"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        policy = tmp_path / "no-bash.json"
        policy.write_text(
            json.dumps(
                {
                    "id": "no-bash",
                    "description": "Deny every shell command",
                    "applies_to": ["*"],
                    "hook": "pre_tool_call",
                    "match": {"type": "regex", "pattern": "touch"},
                    "action": "block",
                    "message": "shell is off for this run",
                }
            )
        )
        env = _child_env(home, server.base_url)

        proc = _run_harness(_contract_11_args(workspace, "--policy", str(policy)), env)

        assert proc.returncode == 0, proc.stderr
        events = _parse_ndjson(proc.stdout)[:-1]
        assert not [e for e in events if e["event"]["event_type"] == "process_started"]
        assert not (workspace / "ran.txt").exists()
        assert (home / "policies" / "no-bash.json").is_file()

    def test_a_malformed_policy_exits_2_before_any_run_is_created(self, tmp_path: Path) -> None:
        policy = tmp_path / "broken.json"
        policy.write_text("{not json")
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, "http://127.0.0.1:1/v1")

        proc = _run_harness(_contract_11_args(workspace, "--policy", str(policy)), env)

        assert proc.returncode == 2, proc.stderr
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        assert len(lines) == 1
        result = json.loads(lines[0])
        assert result["status"] == "refused"
        assert "broken.json" in result["error"]
        assert not (home / "docket-runs.json").exists()
        assert not (home / "policies").exists()

    @pytest.mark.parametrize(
        "extra",
        [
            ["--token-file", "{tmp}/t.json"],
            ["--max-tokens", "10"],
            ["--policy", "{tmp}/p.json"],
        ],
    )
    def test_v11_flags_need_contract_1_1(self, tmp_path: Path, extra: list[str]) -> None:
        (tmp_path / "p.json").write_text("{}")
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1", isolation_off=False)
        args = [a.replace("{tmp}", str(tmp_path)) for a in extra]

        proc = _run_harness(
            ["run", "--workspace", str(workspace), "--task", "x", "--model", "local/x", *args],
            env,
        )

        assert proc.returncode == 2, proc.stderr
        result = json.loads(proc.stdout.strip())
        assert result["status"] == "refused"
        assert result["v"] == "1.0.0"
        assert "--contract 1.1" in result["error"]
        assert not (tmp_path / "home").exists()

    @pytest.mark.parametrize("value", ["0", "-3", "ten"])
    def test_max_tokens_must_be_a_positive_integer(self, tmp_path: Path, value: str) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1", isolation_off=False)

        proc = _run_harness(_contract_11_args(workspace, "--max-tokens", value), env)

        assert proc.returncode == 2, proc.stderr
        assert json.loads(proc.stdout.strip())["status"] == "refused"
        assert not (tmp_path / "home").exists()


# ── (b) blocked ───────────────────────────────────────────────────────────────


class TestBlockedRun:
    def test_a_destructive_command_denies_immediately_as_blocked(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_tool_call_response("bash", {"command": "rm -rf build"})])
        home = tmp_path / "home"
        (home / "policies").mkdir(parents=True)
        (home / "policies" / "block-destructive.json").write_text(
            json.dumps(
                {
                    "id": "block-destructive",
                    "description": "Gate destructive shell commands",
                    "applies_to": ["*"],
                    "hook": "pre_tool_call",
                    "match": {"type": "regex", "pattern": r"\brm\s+-[rf]"},
                    "action": "require_approval",
                    "message": "Destructive command requires operator approval.",
                }
            )
        )
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(
            ["run", "--workspace", str(workspace), "--task", "delete build", "--model", "local/x"],
            env,
        )

        assert proc.returncode == 1, proc.stderr
        lines = _parse_ndjson(proc.stdout)
        result = lines[-1]
        assert result["status"] == "blocked"
        assert result["blocked"]["policy_id"] == "block-destructive"
        assert result["blocked"]["denial_kind"] == "approval_unavailable"

        approvals_dir = home / "approvals"
        assert not approvals_dir.exists() or list(approvals_dir.glob("*.json")) == []

        run_record = json.loads((home / "docket-runs.json").read_text())["runs"][0]
        assert run_record["state"] == "failed"

        assert len(server.requests) == 1


# ── (c) cancelled + (e, partial) status == live ──────────────────────────────


def _find_pid_by_cmdline_substring(marker: str) -> int | None:
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():  # macOS: no procfs, so ask ps for every command line
        listing = subprocess.run(
            ["ps", "-A", "-ww", "-o", "pid=,command="], capture_output=True, text=True, check=True
        ).stdout
        for row in listing.splitlines():
            pid, _, command = row.strip().partition(" ")
            if marker in command:
                return int(pid)
        return None
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        if marker in cmdline:
            return int(entry.name)
    return None


def _poll_for_pid_state(
    marker: str,
    *,
    want_present: bool,
    deadline_seconds: float = 3.0,
    interval_seconds: float = 0.02,
) -> int | None:
    # The tool_call NDJSON event is emitted before the bash handler spawns the
    # child, and the kill leaves the process group to be reaped, so a single
    # /proc lookup right after either moment races the real state change.
    deadline = time.monotonic() + deadline_seconds
    while True:
        pid = _find_pid_by_cmdline_substring(marker)
        if (pid is not None) == want_present:
            return pid
        if time.monotonic() >= deadline:
            return pid
        time.sleep(interval_seconds)


class TestCancelledRun:
    def test_sigterm_after_the_tool_call_event_cancels_within_three_seconds(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        marker = f"HARNESS_CANCEL_{uuid.uuid4().hex}"
        sleep_command = f'python3 -c "import time; time.sleep(30)  # {marker}"'
        server = llm_server([_tool_call_response("bash", {"command": sleep_command})])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "docket",
                "harness",
                "run",
                "--workspace",
                str(workspace),
                "--task",
                "sleep",
                "--model",
                "local/x",
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        lines: list[str] = []
        reader_done = threading.Event()

        def _drain() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.append(line)
            reader_done.set()

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()

        deadline = time.monotonic() + 10
        token = ""
        while time.monotonic() < deadline:
            for raw in lines:
                if not raw.strip():
                    continue
                parsed = json.loads(raw)
                if parsed.get("event", {}).get("event_type") == "tool_call":
                    token = parsed["token"]
                    break
            if token:
                break
            time.sleep(0.02)
        assert token, "the tool_call event never arrived"

        # The real child process is now blocked in time.sleep(30) -- confirm
        # it genuinely exists before proving cancellation kills it.
        child_pid = _poll_for_pid_state(marker, want_present=True)
        assert child_pid is not None, "the sleeping child process was never found"

        time.sleep(0.5)
        requested_at = time.monotonic()
        proc.send_signal(signal.SIGTERM)

        try:
            proc.wait(timeout=10)
        finally:
            reader.join(timeout=5)
        elapsed = time.monotonic() - requested_at
        assert elapsed < 3, f"took {elapsed:.2f}s to terminalize, not within 3s"

        assert proc.returncode == 1
        result = json.loads(lines[-1])
        assert result["status"] == "cancelled"

        assert _poll_for_pid_state(marker, want_present=False) is None, (
            "the child process group was not actually killed"
        )

        run_record = json.loads((home / "docket-runs.json").read_text())["runs"][0]
        assert run_record["id"] == token
        assert run_record["state"] == "cancelled"
        lifecycle = run_record["cancellation"]
        assert lifecycle["requestedAt"] is not None
        assert lifecycle["observedAt"] is not None
        assert lifecycle["stoppedAt"] is not None


# ── (d) refused x5 ────────────────────────────────────────────────────────────


class TestRefused:
    def _assert_refused(self, proc: subprocess.CompletedProcess[str], home: Path | None) -> None:
        assert proc.returncode == 2, proc.stderr
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        assert len(lines) == 1
        result = json.loads(lines[0])
        assert result["status"] == "refused"
        assert result["token"] == ""
        if home is not None:
            assert not (home / "docket-runs.json").exists()
            assert not (home / "workspaces").exists()

    def test_unset_docket_home(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "unused-home", "http://127.0.0.1:1/v1")
        del env["DOCKET_HOME"]

        proc = _run_harness(
            ["run", "--workspace", str(workspace), "--task", "x", "--model", "local/x"], env
        )
        self._assert_refused(proc, None)
        assert "DOCKET_HOME" in json.loads(proc.stdout.strip())["error"]

    def test_default_docket_home(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(_real_default_home(), "http://127.0.0.1:1/v1", isolation_off=False)

        proc = _run_harness(
            ["run", "--workspace", str(workspace), "--task", "x", "--model", "local/x"], env
        )
        self._assert_refused(proc, None)
        assert "default home" in json.loads(proc.stdout.strip())["error"]

    def test_missing_base_url(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", None)

        proc = _run_harness(
            ["run", "--workspace", str(workspace), "--task", "x", "--model", "local/x"], env
        )
        self._assert_refused(proc, tmp_path / "home")
        assert "DOCKET_LLM_BASE_URL" in json.loads(proc.stdout.strip())["error"]

    def test_no_trace_set(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1", DOCKET_NO_TRACE="1")

        proc = _run_harness(
            ["run", "--workspace", str(workspace), "--task", "x", "--model", "local/x"], env
        )
        self._assert_refused(proc, tmp_path / "home")
        assert "DOCKET_NO_TRACE" in json.loads(proc.stdout.strip())["error"]

    def test_missing_workspace(self, tmp_path: Path) -> None:
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1")

        proc = _run_harness(
            [
                "run",
                "--workspace",
                str(tmp_path / "does-not-exist"),
                "--task",
                "x",
                "--model",
                "local/x",
            ],
            env,
        )
        self._assert_refused(proc, tmp_path / "home")
        assert "workspace" in json.loads(proc.stdout.strip())["error"]


# ── (e) status ────────────────────────────────────────────────────────────────


class TestPostureRefusal:
    def test_isolation_refusal_is_a_failed_result_with_the_remedy(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_final_response("never reached")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url, isolation_off=False, DOCKET_SANDBOX_BACKEND="none")

        proc = _run_harness(
            ["run", "--workspace", str(workspace), "--task", "x", "--model", "local/x"], env
        )

        assert proc.returncode == 1, proc.stderr
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        assert result["status"] == "failed"
        assert result["run_state"] == "failed"
        assert "docket gates isolate off" in result["error"]
        assert result["usage"]["turns"] == 0


class TestStatus:
    def test_finished_reports_the_result(self, tmp_path: Path, llm_server: Any) -> None:
        server = llm_server([_final_response("done")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(
            ["run", "--workspace", str(workspace), "--task", "x", "--model", "local/x"], env
        )
        assert proc.returncode == 0, proc.stderr
        token = _parse_ndjson(proc.stdout)[0]["token"]

        status_proc = _run_harness(["status", token], env)
        assert status_proc.returncode == 0, status_proc.stderr
        body = json.loads(status_proc.stdout.strip())
        assert body["state"] == "finished"
        assert body["result"]["status"] == "ok"
        assert body["result"]["run_state"] == "succeeded"

    def test_unknown_token(self, tmp_path: Path) -> None:
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1")
        proc = _run_harness(["status", "not-a-real-token"], env)
        assert proc.returncode == 0, proc.stderr
        body = json.loads(proc.stdout.strip())
        assert body["state"] == "unknown"

    def test_live_while_inside_a_tool_call(self, tmp_path: Path, llm_server: Any) -> None:
        marker = f"HARNESS_LIVE_{uuid.uuid4().hex}"
        sleep_command = f'python3 -c "import time; time.sleep(10)  # {marker}"'
        server = llm_server([_tool_call_response("bash", {"command": sleep_command})])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "docket",
                "harness",
                "run",
                "--workspace",
                str(workspace),
                "--task",
                "sleep a bit",
                "--model",
                "local/x",
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        lines: list[str] = []

        def _drain() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.append(line)

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()

        deadline = time.monotonic() + 10
        token = ""
        while time.monotonic() < deadline:
            for raw in lines:
                if not raw.strip():
                    continue
                parsed = json.loads(raw)
                if parsed.get("event", {}).get("event_type") == "tool_call":
                    token = parsed["token"]
                    break
            if token:
                break
            time.sleep(0.02)
        assert token, "the tool_call event never arrived"

        try:
            status_proc = _run_harness(["status", token], env)
            assert status_proc.returncode == 0, status_proc.stderr
            body = json.loads(status_proc.stdout.strip())
            assert body["state"] == "live"
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=10)
            reader.join(timeout=5)


# ── (g) answers on stdin ─────────────────────────────────────────────────────

# classify_command asks on a push to a named remote; the workspace is not a git
# repository, so an approved push fails locally and never reaches a network.
_PUSH_CALL = {"command": "git push origin production"}


class _AnsweredRun:
    """A ``docket harness run --answers stdin`` child. Its stdout is pumped by a
    thread so a test can wait for one event (the approval request) and then write
    an answer line to the child's stdin, the way a real caller would."""

    def __init__(self, args: list[str], env: dict[str, str], stderr_path: Path) -> None:
        self._stderr = stderr_path.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "docket", "harness", *args],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            bufsize=1,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._seen: list[str] = []
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def wait_for_event(self, event_type: str, timeout: float = 30.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            line = self._lines.get(timeout=max(0.1, deadline - time.monotonic()))
            if line is None:
                raise AssertionError(f"stdout closed before {event_type!r}")
            self._seen.append(line)
            record = json.loads(line)
            if record.get("event", {}).get("event_type") == event_type:
                return record

    def write_raw(self, text: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def write_answer(self, token: str, approval: str, action: str) -> None:
        answer = {"approvalToken": approval, "action": action}
        self.write_raw(json.dumps({"v": "1.1.0", "token": token, "answer": answer}))

    def close_stdin(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()

    def finish(self, timeout: float = 60.0) -> tuple[int, list[dict[str, Any]]]:
        while True:
            line = self._lines.get(timeout=timeout)
            if line is None:
                break
            self._seen.append(line)
        returncode = self.proc.wait(timeout=timeout)
        self._stderr.close()
        return returncode, _parse_ndjson("".join(self._seen))


def _approval_records(home: Path) -> list[dict[str, Any]]:
    directory = home / "approvals"
    if not directory.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]


def _answered_args(workspace: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--workspace",
        str(workspace),
        "--task",
        "push it",
        "--model",
        "local/x",
        "--contract",
        "1.1",
        "--answers",
        "stdin",
        *extra,
    ]


class TestAnswersOnStdin:
    def test_an_accept_line_grants_the_paused_call_and_the_run_completes(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_tool_call_response("bash", _PUSH_CALL), _final_response("done")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(_answered_args(workspace), env, tmp_path / "stderr.txt")
        requested = run.wait_for_event("approval_requested")
        payload = requested["event"]["payload"]
        assert payload["tool"] == "bash"
        assert payload["callId"] == "call-1"
        run.write_answer(requested["token"], payload["token"], "accept")
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0, (tmp_path / "stderr.txt").read_text(encoding="utf-8")
        assert lines[-1]["status"] == "ok"
        [record] = _approval_records(home)
        assert record["state"] == "granted"
        assert "channel=harness" in (home / "audit.log").read_text(encoding="utf-8")

    def test_a_decline_line_denies_the_call_and_the_model_is_told_so(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_tool_call_response("bash", _PUSH_CALL), _final_response("done")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(_answered_args(workspace), env, tmp_path / "stderr.txt")
        requested = run.wait_for_event("approval_requested")
        run.write_answer(requested["token"], requested["event"]["payload"]["token"], "decline")
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0
        assert lines[-1]["status"] == "ok"
        [record] = _approval_records(home)
        assert record["state"] == "denied"
        assert "approval.deny" in (home / "audit.log").read_text(encoding="utf-8")
        # The second model request carries the refused tool result: the push never ran.
        assert "approval denied" in json.dumps(server.requests[-1]["messages"])

    def test_a_decline_with_reason_records_reason_in_audit(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_tool_call_response("bash", _PUSH_CALL), _final_response("done")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(_answered_args(workspace), env, tmp_path / "stderr.txt")
        requested = run.wait_for_event("approval_requested")
        # Send decline with reason
        token = requested["token"]
        approval_token = requested["event"]["payload"]["token"]
        answer = {
            "approvalToken": approval_token,
            "action": "decline",
            "content": {"reason": "not approved"},
        }
        run.write_raw(json.dumps({"v": "1.1.0", "token": token, "answer": answer}))
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0
        assert lines[-1]["status"] == "ok"
        [record] = _approval_records(home)
        assert record["state"] == "denied"
        audit_text = (home / "audit.log").read_text(encoding="utf-8")
        assert "approval.deny" in audit_text
        assert "reason=" in audit_text

    def test_no_answer_before_the_timeout_denies_the_call(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_tool_call_response("bash", _PUSH_CALL), _final_response("done")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(
            _answered_args(workspace, "--answer-timeout", "1"), env, tmp_path / "stderr.txt"
        )
        run.wait_for_event("approval_requested")
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0
        assert lines[-1]["status"] == "ok"
        [record] = _approval_records(home)
        assert record["state"] == "denied"
        assert "timed out" in json.dumps(server.requests[-1]["messages"])

    def test_malformed_and_foreign_lines_are_ignored_and_never_echoed(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        canary = "MALFORMED-MARKER-7f3a"
        server = llm_server([_tool_call_response("bash", _PUSH_CALL), _final_response("done")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(_answered_args(workspace), env, tmp_path / "stderr.txt")
        requested = run.wait_for_event("approval_requested")
        run.write_raw(f"not json {canary}")
        run.write_raw(json.dumps({"v": "1.1.0", "token": "other-run", "answer": {}}))
        run.write_answer(requested["token"], requested["event"]["payload"]["token"], "accept")
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0
        assert lines[-1]["status"] == "ok"
        stderr = (tmp_path / "stderr.txt").read_text(encoding="utf-8")
        assert stderr.count("answer line ignored") == 2
        assert canary not in stderr
        assert canary not in json.dumps(lines)

    def test_an_answer_whose_content_a_pre_input_policy_blocks_leaves_the_approval_pending(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_tool_call_response("bash", _PUSH_CALL), _final_response("done")])
        home = tmp_path / "home"
        (home / "policies").mkdir(parents=True)
        (home / "policies" / "block-input.json").write_text(
            json.dumps(
                {
                    "id": "block-input",
                    "description": "Refuse forbidden phrases from humans",
                    "applies_to": ["*"],
                    "hook": "pre_input",
                    "match": {"type": "regex", "pattern": "forbidden phrase"},
                    "action": "block",
                    "message": "Input refused by policy.",
                }
            )
        )
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(_answered_args(workspace), env, tmp_path / "stderr.txt")
        requested = run.wait_for_event("approval_requested")
        token = requested["token"]
        approval = requested["event"]["payload"]["token"]
        run.write_raw(
            json.dumps(
                {
                    "v": "1.1.0",
                    "token": token,
                    "answer": {
                        "approvalToken": approval,
                        "action": "accept",
                        "content": {"note": "forbidden phrase"},
                    },
                }
            )
        )
        run.write_answer(token, approval, "accept")
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0
        assert lines[-1]["status"] == "ok"
        assert "block-input" in (tmp_path / "stderr.txt").read_text(encoding="utf-8")
        [record] = _approval_records(home)
        assert record["state"] == "granted"

    def test_an_answer_for_a_question_is_refused_until_recipe_runs_exist(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_tool_call_response("bash", _PUSH_CALL), _final_response("done")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(
            _answered_args(workspace, "--answer-timeout", "1"), env, tmp_path / "stderr.txt"
        )
        requested = run.wait_for_event("approval_requested")
        question = {"questionId": "q-1", "action": "accept"}
        run.write_raw(json.dumps({"v": "1.1.0", "token": requested["token"], "answer": question}))
        run.close_stdin()
        returncode, _ = run.finish()

        assert returncode == 0
        assert "need --recipe" in (tmp_path / "stderr.txt").read_text(encoding="utf-8")

    @pytest.mark.parametrize("extra", [["--answers", "stdin"], ["--answer-timeout", "5"]])
    def test_answer_flags_need_contract_1_1(self, tmp_path: Path, extra: list[str]) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1", isolation_off=False)

        proc = _run_harness(
            ["run", "--workspace", str(workspace), "--task", "x", "--model", "local/x", *extra],
            env,
        )

        assert proc.returncode == 2, proc.stderr
        result = json.loads(proc.stdout.strip().splitlines()[0])
        assert result["status"] == "refused"
        assert "--contract 1.1" in result["error"]
        assert not (tmp_path / "home").exists()

    def test_answers_stdin_refuses_a_task_file_that_reads_stdin(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1", isolation_off=False)

        proc = _run_harness(
            [
                "run",
                "--workspace",
                str(workspace),
                "--task-file",
                "-",
                "--model",
                "local/x",
                "--contract",
                "1.1",
                "--answers",
                "stdin",
            ],
            env,
        )

        assert proc.returncode == 2, proc.stderr
        result = json.loads(proc.stdout.strip().splitlines()[0])
        assert result["status"] == "refused"
        assert "conflicts" in result["error"]
        assert "--task-file" in result["error"]
        assert not (tmp_path / "home").exists()


# ── (g) recipe runs (contract 1.1) ────────────────────────────────────────────


def _recipe_args(workspace: Path, recipe: str, *extra: str) -> list[str]:
    return [
        "run",
        "--workspace",
        str(workspace),
        "--task",
        "add the thing",
        "--model",
        "local/x",
        "--contract",
        "1.1",
        "--recipe",
        recipe,
        *extra,
    ]


_RED = "red: one failing test written"
_GREEN = "green: the test passes"
_INTAKE_BRIEF = (
    "Need one thing.\n```json\n"
    '{"objective": "add rate limiting", "acceptance": ["429 after 100"], '
    '"resources": [], "questions": ["Which branch?"]}\n```\nNEEDS-INPUT'
)


def _assert_result_validates_v11(result: dict[str, Any]) -> None:
    schema_path = REPO_ROOT / "docs" / "contracts" / "harness-v1.1" / "schema.json"
    document = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator({**document, "$ref": "#/definitions/HarnessResult"})
    validator.validate(result)


class TestRecipeRun:
    def test_tdd_streams_its_hops_and_ends_with_a_task_block(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [_final_response(_RED), _final_response(_GREEN), _final_response("PASS")]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(_recipe_args(workspace, "tdd", "--verify", "true"), env, timeout=120)

        assert proc.returncode == 0, proc.stderr
        lines = _parse_ndjson(proc.stdout)
        result = lines[-1]
        assert result["v"] == "1.1.0"
        assert result["status"] == "ok"
        assert result["task"]["status"] == "done"
        roles = [hop["role"] for hop in result["task"]["hops"]]
        assert roles == ["implementer", "check-red", "implementer", "tester"]
        assert result["task"]["hops"][3]["verdict"] == "pass"
        _assert_result_validates_v11(result)

    def test_a_failing_verify_ends_failed_with_its_exit_code(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [_final_response(_RED), _final_response(_GREEN), _final_response("FAIL")]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(_recipe_args(workspace, "tdd", "--verify", "false"), env, timeout=120)

        assert proc.returncode == 1, proc.stderr
        result = _parse_ndjson(proc.stdout)[-1]
        assert result["status"] == "failed"
        assert result["task"]["status"] == "failed"
        verified = [hop for hop in result["task"]["hops"] if hop["verify"] is not None]
        assert verified[-1]["verify"]["exitCode"] == 1
        _assert_result_validates_v11(result)

    def test_the_intake_question_is_answered_on_stdin_and_reaches_the_lead(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [
                _final_response(_INTAKE_BRIEF),
                _final_response("ready\nREADY"),
                _final_response("built"),
                _final_response("APPROVE"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(
            _recipe_args(workspace, "intake", "--verify", "true", "--answers", "stdin"),
            env,
            tmp_path / "stderr.txt",
        )
        asked = run.wait_for_event("input_requested")
        question_id = asked["event"]["payload"]["questionId"]
        answer = {"questionId": question_id, "action": "accept", "content": {"q1": "use main"}}
        run.write_raw(json.dumps({"v": "1.1.0", "token": asked["token"], "answer": answer}))
        run.close_stdin()
        returncode, lines = run.finish(timeout=120)

        assert returncode == 0, (tmp_path / "stderr.txt").read_text(encoding="utf-8")
        result = lines[-1]
        assert result["status"] == "ok"
        assert result["task"]["status"] == "done"
        assert [h["role"] for h in result["task"]["hops"]] == [
            "lead",
            "operator",
            "lead",
            "implementer",
            "reviewer",
        ]
        assert "use main" in json.dumps(server.requests[1])
        _assert_result_validates_v11(result)

    def test_a_refused_approval_ends_blocked_with_the_rule(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server(
            [
                _tool_call_response("bash", _PUSH_CALL),
                _final_response(_RED),
                _final_response(_GREEN),
                _final_response("PASS"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(_recipe_args(workspace, "tdd", "--verify", "true"), env, timeout=120)

        assert proc.returncode == 1, proc.stderr
        result = _parse_ndjson(proc.stdout)[-1]
        assert result["status"] == "blocked"
        assert result["blocked"]["tool"] == "bash"
        assert result["blocked"]["denial_kind"] == "approval_unavailable"
        _assert_result_validates_v11(result)

    def test_an_unanswered_question_ends_blocked(self, tmp_path: Path, llm_server: Any) -> None:
        server = llm_server([_final_response(_INTAKE_BRIEF)])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        proc = _run_harness(_recipe_args(workspace, "intake", "--verify", "true"), env, timeout=120)

        assert proc.returncode == 1, proc.stderr
        result = _parse_ndjson(proc.stdout)[-1]
        assert result["status"] == "blocked"
        assert result["task"]["status"] == "waiting_input"
        _assert_result_validates_v11(result)

    def test_recipe_with_role_is_a_usage_error(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1", isolation_off=False)

        proc = _run_harness([*_recipe_args(workspace, "tdd"), "--role", "reviewer"], env)

        assert proc.returncode == 2, proc.stderr
        result = json.loads(proc.stdout.strip().splitlines()[0])
        assert result["status"] == "refused"
        assert result["v"] == "1.1.0"
        assert "--role" in result["error"]
        assert not (tmp_path / "home").exists()

    def test_recipe_with_contract_1_0_is_refused(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1")
        args = _recipe_args(workspace, "tdd")
        args[args.index("1.1")] = "1.0"

        proc = _run_harness(args, env)

        assert proc.returncode == 2, proc.stderr
        result = json.loads(proc.stdout.strip().splitlines()[0])
        assert result["status"] == "refused"
        assert result["v"] == "1.0.0"
        assert "--contract 1.1" in result["error"]

    def test_an_unknown_recipe_is_refused_before_any_pod_exists(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        home = tmp_path / "home"
        env = _child_env(home, "http://127.0.0.1:1/v1")

        proc = _run_harness(_recipe_args(workspace, "no-such-recipe-anywhere"), env)

        assert proc.returncode == 2, proc.stderr
        result = json.loads(proc.stdout.strip().splitlines()[0])
        assert result["status"] == "refused"
        assert "no-such-recipe-anywhere" in result["error"]
        projects = home / "workspaces" / "projects"
        assert not projects.is_dir() or not any(projects.iterdir())

    @pytest.mark.parametrize("extra", [["--max-tokens", "100"], ["--agent-id", "x"]])
    def test_flags_a_recipe_run_cannot_honour_are_refused(
        self, tmp_path: Path, extra: list[str]
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", "http://127.0.0.1:1/v1")

        proc = _run_harness([*_recipe_args(workspace, "tdd"), *extra], env)

        assert proc.returncode == 2, proc.stderr
        result = json.loads(proc.stdout.strip().splitlines()[0])
        assert result["status"] == "refused"
        assert extra[0] in result["error"]


class TestApprovalsOnTheResult:
    """The v1.1 result says how each approval a run asked for ended."""

    def test_a_declined_approval_is_reported_with_its_call_and_the_run_still_ends_ok(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_tool_call_response("bash", _PUSH_CALL), _final_response("done")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(_answered_args(workspace), env, tmp_path / "stderr.txt")
        requested = run.wait_for_event("approval_requested")
        payload = requested["event"]["payload"]
        run.write_answer(requested["token"], payload["token"], "decline")
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0
        result = lines[-1]
        assert result["status"] == "ok"
        assert payload["tool"] == "bash" and payload["callId"] == "call-1"
        assert result["approvals"] == [
            {
                "token": payload["token"],
                "tool": "bash",
                "callId": "call-1",
                "outcome": "declined",
            }
        ]
        _assert_result_validates_v11(result)

    def test_an_accepted_approval_is_reported_as_accepted(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_tool_call_response("bash", _PUSH_CALL), _final_response("done")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(_answered_args(workspace), env, tmp_path / "stderr.txt")
        requested = run.wait_for_event("approval_requested")
        payload = requested["event"]["payload"]
        run.write_answer(requested["token"], payload["token"], "accept")
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0
        assert lines[-1]["approvals"] == [
            {"token": payload["token"], "tool": "bash", "callId": "call-1", "outcome": "accepted"}
        ]
        _assert_result_validates_v11(lines[-1])

    def test_an_approval_nobody_answers_is_reported_as_timed_out(
        self, tmp_path: Path, llm_server: Any
    ) -> None:
        server = llm_server([_tool_call_response("bash", _PUSH_CALL), _final_response("done")])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)

        run = _AnsweredRun(
            _answered_args(workspace, "--answer-timeout", "1"), env, tmp_path / "stderr.txt"
        )
        requested = run.wait_for_event("approval_requested")
        payload = requested["event"]["payload"]
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0
        result = lines[-1]
        assert result["status"] == "ok"
        assert result["approvals"] == [
            {"token": payload["token"], "tool": "bash", "callId": "call-1", "outcome": "timed_out"}
        ]
        _assert_result_validates_v11(result)

    def test_a_clean_run_reports_no_approvals(self, tmp_path: Path, llm_server: Any) -> None:
        server = llm_server([_final_response("nothing to approve")])
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", server.base_url)

        proc = _run_harness(
            [
                "run",
                "--workspace",
                str(workspace),
                "--task",
                "say hi",
                "--model",
                "local/x",
                "--contract",
                "1.1",
            ],
            env,
        )

        assert proc.returncode == 0, proc.stderr
        result = _parse_ndjson(proc.stdout)[-1]
        assert result["approvals"] == []
        _assert_result_validates_v11(result)
