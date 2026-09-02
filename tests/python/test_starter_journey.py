"""Artifact-installed acceptance contract for the extractable Docket starter."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STARTER = ROOT / "examples" / "starter"
PROJECT = "docket-starter"
INITIAL_BYTES = b"starter pending\n"
APPROVED_BYTES = b"docket starter approved\n"
TERMINAL_SUMMARY = "Starter journey completed."
PUBLIC_COMMAND = "python starter.py --workspace ./workspace"
HANDOFF_FIELDS = {"summary", "files_changed", "diff_ref", "verdict", "notes"}


def _run(
    *args: str,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _require_success(result: subprocess.CompletedProcess[str], label: str) -> None:
    assert result.returncode == 0, (
        f"{label} failed with exit {result.returncode}:\n{result.stdout}\n{result.stderr}"
    )


def _remaining(deadline: float) -> int:
    remaining = int(deadline - time.monotonic())
    assert remaining > 0, "starter journey exceeded its 600-second contract"
    return remaining


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} did not contain a JSON object"
    return value


def _workspace_bytes(workspace: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(workspace)): path.read_bytes()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


class _OutputMonitor:
    """Read a line-buffered interactive starter without racing its pause oracles."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        self._stream = process.stdout
        self._condition = threading.Condition()
        self._lines: list[str] = []
        self._closed = False
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        for line in self._stream:
            with self._condition:
                self._lines.append(line)
                self._condition.notify_all()
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def wait_for(self, marker: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while marker not in "".join(self._lines):
                if self._closed:
                    raise AssertionError(
                        f"starter exited before {marker!r}; output:\n{''.join(self._lines)}"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(
                        f"starter did not emit {marker!r}; output:\n{''.join(self._lines)}"
                    )
                self._condition.wait(remaining)

    def finish(self, timeout: float = 5) -> str:
        self._thread.join(timeout)
        assert not self._thread.is_alive(), "starter output reader did not finish"
        with self._condition:
            return "".join(self._lines)


def _json_lines(output: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        assert isinstance(value, dict)
        records.append(value)
    return records


def test_artifact_installed_starter_journey(tmp_path: Path) -> None:
    """One copied command proves rollback, mutation, handoff, run, trace, and audit."""
    assert STARTER.is_dir(), (
        "missing extractable starter directory: examples/starter/ "
        "(W29-C2 RED: production/example files are not implemented yet)"
    )
    started = time.monotonic()
    deadline = started + 600

    expected_files = {"README.md", "requirements.lock", "starter.py"}
    assert expected_files <= {path.name for path in STARTER.iterdir() if path.is_file()}
    readme = (STARTER / "README.md").read_text(encoding="utf-8")
    assert PUBLIC_COMMAND in readme
    lock_lines = [
        line.strip()
        for line in (STARTER / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lock_lines, "starter dependency lock is empty"
    assert all("==" in line for line in lock_lines), "starter requirements must be exact pins"
    assert not any(line.lower().startswith("docket") for line in lock_lines), (
        "the starter must install Docket from the exact local artifact, not its dependency lock"
    )

    outside = tmp_path / "outside-checkout"
    copied_starter = outside / "starter"
    outside.mkdir()
    shutil.copytree(STARTER, copied_starter)
    assert not copied_starter.resolve().is_relative_to(ROOT.resolve())

    build_home = tmp_path / "build-home"
    artifact_dir = tmp_path / "artifacts"
    build_env = {
        **os.environ,
        "DOCKET_HOME": str(tmp_path / "build-docket-home"),
        "HOME": str(build_home),
        "PYTHONPATH": "",
        "TMPDIR": str(tmp_path / "build-tmp"),
        "UV_CACHE_DIR": str(tmp_path / "build-uv-cache"),
    }
    build_home.mkdir()
    Path(build_env["TMPDIR"]).mkdir()
    built = _run(
        "uv",
        "build",
        "--out-dir",
        str(artifact_dir),
        cwd=ROOT,
        env=build_env,
        timeout=_remaining(deadline),
    )
    _require_success(built, "root wheel/sdist build")
    wheels = list(artifact_dir.glob("docket-*.whl"))
    sdists = list(artifact_dir.glob("docket-*.tar.gz"))
    assert len(wheels) == 1, f"expected one root wheel, found {wheels}"
    assert len(sdists) == 1, f"expected one root sdist, found {sdists}"

    venv = tmp_path / "venv"
    created = _run(
        "uv",
        "venv",
        str(venv),
        "--python",
        "3.11",
        cwd=outside,
        env=build_env,
        timeout=_remaining(deadline),
    )
    _require_success(created, "Python 3.11 environment creation")
    python = venv / "bin" / "python"
    docket = venv / "bin" / "docket"
    installed_dependencies = _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--requirement",
        str(copied_starter / "requirements.lock"),
        cwd=outside,
        env=build_env,
        timeout=_remaining(deadline),
    )
    _require_success(installed_dependencies, "locked dependency installation")
    installed_artifact = _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--no-deps",
        str(wheels[0]),
        cwd=outside,
        env=build_env,
        timeout=_remaining(deadline),
    )
    _require_success(installed_artifact, "exact root wheel installation")
    assert docket.is_file()

    inspected = _run(
        str(python),
        "-c",
        (
            "import importlib.util, json, pathlib, platform, docket; "
            "print(json.dumps({'module': docket.__file__, "
            "'runtime': importlib.util.find_spec('docket_runtime'), "
            "'python': platform.python_version()}))"
        ),
        cwd=outside,
        env={**build_env, "PYTHONPATH": ""},
        timeout=_remaining(deadline),
    )
    _require_success(inspected, "installed module inspection")
    installation = json.loads(inspected.stdout)
    assert str(installation["python"]).split(".")[:2] == ["3", "11"]
    assert Path(str(installation["module"])).resolve().is_relative_to(venv.resolve())
    assert installation["runtime"] is None, "root starter unexpectedly installed docket-runtime"

    workspace = copied_starter / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Docket starter workspace\n", encoding="utf-8")
    target = workspace / "starter-output.txt"
    target.write_bytes(INITIAL_BYTES)
    before = _workspace_bytes(workspace)

    run_home = tmp_path / "docket-home"
    run_env = os.environ.copy()
    for key in (
        "ANTHROPIC_API_KEY",
        "DOCKET_LLM_API_KEY",
        "DOCKET_LLM_BASE_URL",
        "OPENAI_API_KEY",
        "PYTHONHOME",
        "SMOKE_LOCAL_API_KEY",
    ):
        run_env.pop(key, None)
    run_env.update(
        {
            "ALL_PROXY": "http://127.0.0.1:9",
            "DOCKET_HOME": str(run_home),
            "DOCKET_LOG_DIR": str(tmp_path / "logs"),
            "DOCKET_SERVICE_MANAGER": "none",
            "HOME": str(tmp_path / "run-home"),
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "NO_COLOR": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "PIP_NO_INDEX": "1",
            "PYTHONPATH": "",
            "TMPDIR": str(tmp_path / "run-tmp"),
            "UV_CACHE_DIR": str(tmp_path / "run-uv-cache"),
            "UV_OFFLINE": "1",
            "all_proxy": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    Path(run_env["HOME"]).mkdir()
    Path(run_env["TMPDIR"]).mkdir()

    process = subprocess.Popen(
        [str(python), "starter.py", "--workspace", str(workspace)],
        cwd=copied_starter,
        env=run_env,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    monitor = _OutputMonitor(process)
    try:
        assert process.stdin is not None
        monitor.wait_for("STARTER DENIAL PAUSED", _remaining(deadline))
        assert _workspace_bytes(workspace) == before
        process.stdin.write("deny\n")
        process.stdin.flush()

        monitor.wait_for("STARTER DENIAL CONFIRMED", _remaining(deadline))
        assert _workspace_bytes(workspace) == before
        monitor.wait_for("STARTER GRANT PAUSED", _remaining(deadline))
        assert _workspace_bytes(workspace) == before
        process.stdin.write("grant\n")
        process.stdin.flush()
        process.stdin.close()

        monitor.wait_for("STARTER JOURNEY PASS", _remaining(deadline))
        returncode = process.wait(timeout=_remaining(deadline))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    output = monitor.finish()
    assert returncode == 0, output
    assert "Traceback" not in output
    endpoint_match = re.search(r"^STARTER LOOPBACK http://127\.0\.0\.1:(\d+)/v1$", output, re.M)
    assert endpoint_match is not None, output
    assert int(endpoint_match.group(1)) != 8081
    for locator in (target, run_home / "audit.log"):
        assert str(locator) in output

    after = _workspace_bytes(workspace)
    assert after.keys() == before.keys()
    assert {name for name in after if after[name] != before[name]} == {"starter-output.txt"}
    assert target.read_bytes() == APPROVED_BYTES

    listed = _run(
        str(docket),
        "runs",
        "list",
        "--project",
        PROJECT,
        "--json",
        cwd=copied_starter,
        env=run_env,
        timeout=_remaining(deadline),
    )
    _require_success(listed, "public run list")
    list_payload = json.loads(listed.stdout)
    runs = list_payload.get("runs", [])
    assert isinstance(runs, list) and runs
    task_lists = list((run_home / "workspaces" / "projects").glob("*/TASK_LIST.json"))
    assert len(task_lists) == 1, task_lists
    tasks_payload = _load_object(task_lists[0])
    tasks = tasks_payload.get("tasks", [])
    assert isinstance(tasks, list)
    denied_tasks = [
        task
        for task in tasks
        if isinstance(task, dict) and task.get("failureKind") == "approval_denied"
    ]
    assert len(denied_tasks) == 1
    done_tasks = [task for task in tasks if isinstance(task, dict) and task.get("status") == "done"]
    assert len(done_tasks) == 1
    done_task = done_tasks[0]
    successful = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("state") == "succeeded"
        and done_task.get("id") in run.get("taskIds", [])
    ]
    assert successful, runs

    shown = _run(
        str(docket),
        "runs",
        "show",
        str(successful[0]["id"]),
        "--json",
        cwd=copied_starter,
        env=run_env,
        timeout=_remaining(deadline),
    )
    _require_success(shown, "public run show")
    assert json.loads(shown.stdout) == successful[0]
    assert done_task.get("id") in successful[0]["taskIds"]
    hops = done_task.get("hops", [])
    assert isinstance(hops, list) and hops
    final_hop = hops[-1]
    assert isinstance(final_hop, dict)
    artifact = final_hop.get("artifact")
    assert isinstance(artifact, dict)
    assert set(artifact) == HANDOFF_FIELDS
    assert artifact["summary"] == TERMINAL_SUMMARY
    assert final_hop.get("output") == TERMINAL_SUMMARY
    for locator in (task_lists[0], run_home / "traces" / PROJECT):
        assert str(locator) in output

    exported = _run(
        str(docket),
        "trace",
        "export",
        PROJECT,
        cwd=copied_starter,
        env=run_env,
        timeout=_remaining(deadline),
    )
    _require_success(exported, "public trace export")
    records = _json_lines(exported.stdout)
    event_types = [record.get("event_type") for record in records]
    assert event_types.count("approval_denied") == 1
    assert event_types.count("approval_granted") == 1
    assert event_types.count("approval_required") == 2
    pair = [
        record
        for record in records
        if record.get("event_type") in {"tool_call", "tool_result"}
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("callId") == "starter-write"
    ]
    assert [record["event_type"] for record in pair] == ["tool_call", "tool_result"]
    assert all(record.get("project") == PROJECT for record in pair)
    assert pair[0].get("session_id") == pair[1].get("session_id")
    assert pair[0].get("agent_role") == pair[1].get("agent_role") == "implementer"
    assert pair[0]["payload"]["tool"] == pair[1]["payload"]["tool"] == "write"
    assert pair[1]["payload"]["ok"] is True
    assert pair[1]["payload"]["executed"] is True

    verified = _run(
        str(docket),
        "audit",
        "verify",
        cwd=copied_starter,
        env=run_env,
        timeout=_remaining(deadline),
    )
    _require_success(verified, "public audit verification")
    assert "verified clean" in verified.stdout
    assert time.monotonic() - started <= 600
