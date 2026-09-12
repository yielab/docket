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
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

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

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.requests: list[dict[str, Any]] = []
        responses_ref = self.responses = list(responses)
        requests_ref = self.requests

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                requests_ref.append(json.loads(body.decode("utf-8")))
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

    def _start(responses: list[dict[str, Any]]) -> _ScriptedLLMServer:
        server = _ScriptedLLMServer(responses)
        servers.append(server)
        return server

    yield _start
    for server in servers:
        server.stop()


# ── subprocess plumbing ───────────────────────────────────────────────────────


def _child_env(home: Path, base_url: str | None, **overrides: str) -> dict[str, str]:
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
    if not proc_dir.is_dir():  # pragma: no cover - non-Linux fallback
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
        child_pid = _find_pid_by_cmdline_substring(marker)
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

        assert _find_pid_by_cmdline_substring(marker) is None, (
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
        env = _child_env(_real_default_home(), "http://127.0.0.1:1/v1")

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
