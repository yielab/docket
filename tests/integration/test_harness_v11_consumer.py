"""The harness contract 1.1 consumer seam, driven the way Tack drives it.

Each test spawns the real ``python -m docket harness run --contract 1.1`` process, takes the
task from a file, and reads its stdout as a caller does: ``process_started`` before a signal,
an approval answered on stdin, ``files`` from the terminal result, a ``--recipe`` run, and a
SIGTERM cancel that ends with ``process_exited``. Every emitted line is validated against the
**committed** ``docs/contracts/harness-v1.1/schema.json``, never a regenerated copy, so a
drift between the code and the published file fails here.
"""

from __future__ import annotations

import json
import signal
import subprocess
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from tests.integration.test_harness_cli import (
    REPO_ROOT,
    _AnsweredRun,
    _child_env,
    _final_response,
    _real_docket_home_is_untouched,  # noqa: F401 - module-scoped guard, re-used here
    _tool_call_response,
    llm_server,  # noqa: F401 - fixture, re-used here
)

SUBJECT = "docket.cli._harness"

SCHEMA_PATH = REPO_ROOT / "docs" / "contracts" / "harness-v1.1" / "schema.json"
_PUSH_CALL = {"command": "git push origin production"}
_RED = "red: one failing test written"
_GREEN = "green: the test passes"


def _schema(definition: str) -> Draft202012Validator:
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator({**document, "$ref": f"#/definitions/{definition}"})


def _assert_every_line_validates(lines: list[dict[str, Any]]) -> None:
    """Each event line validates as ``HarnessEvent``; the terminal result as ``HarnessResult``."""
    assert lines, "the run emitted no stdout"
    event_schema = _schema("HarnessEvent")
    result_schema = _schema("HarnessResult")
    for line in lines[:-1]:
        event_schema.validate(line)
    result_schema.validate(lines[-1])


def _write_task(tmp_path: Path, text: str = "do the thing") -> Path:
    task = tmp_path / "task.md"
    task.write_text(text, encoding="utf-8")
    return task


def _consumer_args(workspace: Path, task: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--workspace",
        str(workspace),
        "--task-file",
        str(task),
        "--model",
        "local/x",
        "--contract",
        "1.1",
        *extra,
    ]


def _recipe_args(workspace: Path, task: Path, recipe: str, *extra: str) -> list[str]:
    return _consumer_args(workspace, task, "--recipe", recipe, "--verify", "true", *extra)


class TestConsumerSeam:
    def test_an_approval_answered_on_stdin_and_files_and_process_events_on_the_stream(
        self,
        tmp_path: Path,
        llm_server: Any,  # noqa: F811 - the imported fixture
    ) -> None:
        # The bash call needs approval, is granted on stdin, then a write call lands a file.
        server = llm_server(
            [
                _tool_call_response("bash", _PUSH_CALL, "call-1"),
                _tool_call_response("write", {"path": "a.txt", "content": "alpha"}, "call-2"),
                _final_response("done"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)
        task = _write_task(tmp_path)
        stderr = tmp_path / "stderr.txt"

        run = _AnsweredRun(
            _consumer_args(workspace, task, "--answers", "stdin", "--answer-timeout", "20"),
            env,
            stderr,
        )
        requested = run.wait_for_event("approval_requested")
        approval = requested["event"]["payload"]["token"]
        run.write_answer(requested["token"], approval, "accept")
        run.close_stdin()
        returncode, lines = run.finish(timeout=120)

        assert returncode == 0, stderr.read_text(encoding="utf-8")
        _assert_every_line_validates(lines)
        result = lines[-1]
        assert result["status"] == "ok"
        assert [a["outcome"] for a in result["approvals"]] == ["accepted"]
        assert {"path": "a.txt", "op": "write"} in result["files"]
        started = [ln for ln in lines if ln.get("event", {}).get("event_type") == "process_started"]
        exited = [ln for ln in lines if ln.get("event", {}).get("event_type") == "process_exited"]
        assert len(started) == len(exited) == 1
        assert started[0]["event"]["payload"]["tool"] == "bash"
        assert exited[0]["event"]["payload"]["pgid"] == started[0]["event"]["payload"]["pgid"]

    def test_sigterm_during_a_bash_call_cancels_and_reports_process_exited(
        self,
        tmp_path: Path,
        llm_server: Any,  # noqa: F811 - the imported fixture
    ) -> None:
        marker = f"SEAM_CANCEL_{uuid.uuid4().hex}"
        sleep_command = f'python3 -c "import time; time.sleep(30)  # {marker}"'
        server = llm_server([_tool_call_response("bash", {"command": sleep_command})])
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)
        task = _write_task(tmp_path, "sleep")
        stderr = tmp_path / "stderr.txt"

        run = _AnsweredRun(_consumer_args(workspace, task), env, stderr)
        started = run.wait_for_event("process_started")
        assert isinstance(started["event"]["payload"]["pgid"], int)
        run.proc.send_signal(signal.SIGTERM)
        returncode, lines = run.finish(timeout=60)

        _assert_every_line_validates(lines)
        assert returncode == 1, stderr.read_text(encoding="utf-8")
        assert lines[-1]["status"] == "cancelled"
        [exited] = [ln for ln in lines if ln.get("event", {}).get("event_type") == "process_exited"]
        assert exited["event"]["payload"] == {
            "pgid": started["event"]["payload"]["pgid"],
            "tool": "bash",
            "signal": "SIGKILL",
        }

    def test_a_recipe_run_from_a_task_file_reports_its_task_block_and_files(
        self,
        tmp_path: Path,
        llm_server: Any,  # noqa: F811 - the imported fixture
    ) -> None:
        # Hops: implementer (write, then red), check-red (a command), implementer (green), tester.
        server = llm_server(
            [
                _tool_call_response("write", {"path": "a.txt", "content": "alpha"}, "call-1"),
                _final_response(_RED),
                _final_response(_GREEN),
                _final_response("PASS"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(home, server.base_url)
        task = _write_task(tmp_path, "add the thing")
        stderr = tmp_path / "stderr.txt"

        run = _AnsweredRun(_recipe_args(workspace, task, "tdd"), env, stderr)
        returncode, lines = run.finish(timeout=180)

        assert returncode == 0, stderr.read_text(encoding="utf-8")
        _assert_every_line_validates(lines)
        result = lines[-1]
        assert result["status"] == "ok"
        assert result["task"]["status"] == "done"
        assert [hop["role"] for hop in result["task"]["hops"]] == [
            "implementer",
            "check-red",
            "implementer",
            "tester",
        ]
        assert {"path": "a.txt", "op": "write"} in result["files"]

    def test_a_recipe_run_does_not_list_what_its_verify_command_produced(
        self,
        tmp_path: Path,
        llm_server: Any,  # noqa: F811 - the imported fixture
    ) -> None:
        server = llm_server(
            [
                _tool_call_response("write", {"path": "a.txt", "content": "alpha"}, "call-1"),
                _final_response(_RED),
                _final_response(_GREEN),
                _final_response("PASS"),
            ]
        )
        home = tmp_path / "home"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
        (workspace / "already-dirty.txt").write_text("dirty before")
        env = _child_env(home, server.base_url)
        task = _write_task(tmp_path, "add the thing")
        stderr = tmp_path / "stderr.txt"
        args = _consumer_args(
            workspace, task, "--recipe", "tdd", "--verify", "sh -c 'touch verify-artifact.txt'"
        )

        returncode, lines = _AnsweredRun(args, env, stderr).finish(timeout=180)

        assert returncode == 0, stderr.read_text(encoding="utf-8")
        _assert_every_line_validates(lines)
        assert (workspace / "verify-artifact.txt").exists()
        paths = [f["path"] for f in lines[-1]["files"]]
        assert "a.txt" in paths
        assert "verify-artifact.txt" not in paths
        assert "already-dirty.txt" not in paths
