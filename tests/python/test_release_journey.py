"""Artifact-installed release journey contract."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
JOURNEY = ROOT / "scripts" / "release_journey.py"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PROJECT = "release-journey"


def _run_journey(tmp_path: Path, *extra_args: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the public harness outside the checkout with a poisoned source import."""
    world = tmp_path / "world"
    outside = tmp_path / "outside-checkout"
    poison = tmp_path / "poison"
    outside.mkdir()
    (poison / "docket").mkdir(parents=True)
    (poison / "docket" / "__init__.py").write_text(
        "raise RuntimeError('release journey imported the source override')\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "DOCKET_HOME": str(tmp_path / "forbidden-real-home"),
        "PYTHONPATH": str(poison),
        "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
    }
    result = subprocess.run(
        [sys.executable, str(JOURNEY), "--workdir", str(world), *extra_args],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    return result, world


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_installed_artifact_reaches_one_inspectable_governed_turn(tmp_path: Path) -> None:
    """A clean wheel install must complete without importing Docket from the checkout."""
    result, world = _run_journey(tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "RELEASE JOURNEY PASS" in result.stdout
    assert (world / "codebase" / "release-journey.txt").read_bytes() == (
        b"docket release journey ok\n"
    )

    evidence = _json(world / "journey-evidence.json")
    assert isinstance(evidence, dict)
    environment = (world / "venv").resolve()
    assert Path(str(evidence["executable"])).resolve().is_relative_to(environment)
    assert Path(str(evidence["module"])).resolve().is_relative_to(environment)
    assert Path(str(evidence["artifact"])).resolve().is_relative_to((world / "dist").resolve())
    assert evidence["wire"] == {
        "finalTurn": True,
        "measuredUsage": True,
        "model": True,
        "toolResult": True,
        "toolsAdvertised": True,
    }
    assert int(evidence["requestCount"]) >= 2

    home = world / ".docket"
    runs = _json(home / "docket-runs.json")
    assert isinstance(runs, dict)
    assert any(run.get("state") == "succeeded" for run in runs.get("runs", []))
    task_lists = list((home / "workspaces" / "projects").glob("*/TASK_LIST.json"))
    assert task_lists
    tasks = _json(task_lists[0])
    assert isinstance(tasks, dict)
    assert any(task.get("status") == "done" for task in tasks.get("tasks", []))
    assert list((home / "sessions").glob("*/session.json"))
    trace_text = "\n".join(
        path.read_text(encoding="utf-8") for path in home.glob("traces/**/*.jsonl")
    )
    assert '"event_type": "tool_call"' in trace_text
    assert '"event_type": "tool_result"' in trace_text
    assert (home / "audit.log").read_text(encoding="utf-8").strip()
    assert not (tmp_path / "forbidden-real-home").exists()


def _closed_loopback_endpoint() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


def test_unreachable_endpoint_leaves_no_half_ready_project(tmp_path: Path) -> None:
    """Provider rejection must stop before project state or model/tool side effects."""
    result, world = _run_journey(tmp_path, "--endpoint", _closed_loopback_endpoint())
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "endpoint" in output.lower()
    assert "Traceback" not in output
    assert len(output.encode("utf-8")) <= 8_192
    assert not (world / "journey-evidence.json").exists()
    assert not (world / "codebase" / "release-journey.txt").exists()
    assert not (world / ".docket" / "workspaces" / "projects" / PROJECT).exists()
    assert not list((world / ".docket").glob("traces/**/*.jsonl"))
    audit = world / ".docket" / "audit.log"
    assert not audit.exists() or not audit.read_text(encoding="utf-8").strip()
    fleet = world / ".docket" / "fleet.json"
    assert not fleet.exists() or "release-local" not in fleet.read_text(encoding="utf-8")


def test_release_journey_is_a_blocking_linux_and_macos_ci_matrix() -> None:
    """Both supported CI operating systems must run the identical release exit command."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    matching_jobs: list[dict[str, object]] = []
    for job in workflow["jobs"].values():
        matrix = job.get("strategy", {}).get("matrix", {})
        operating_systems = matrix.get("os", [])
        commands = "\n".join(str(step.get("run", "")) for step in job.get("steps", []))
        if "uv run python scripts/release_journey.py" in commands:
            assert {"ubuntu-latest", "macos-latest"}.issubset(set(operating_systems))
            matching_jobs.append(job)

    assert len(matching_jobs) == 1
    assert matching_jobs[0].get("continue-on-error", False) is False
