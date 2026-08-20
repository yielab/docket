"""Executable whole-product smoke test.

The harness crosses the real CLI subprocess and loopback HTTP boundaries. Focused suites own the
failure matrix; this test owns one observable proof that the happy-path components compose.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_full_workflow_smoke_is_observable_and_preserves_state(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    world = tmp_path / "smoke-world"
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = "/tmp/docket-uv-cache"

    result = subprocess.run(
        [sys.executable, "scripts/smoke_workflow.py", "--workdir", str(world)],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "waiting_approval -> granted -> resumed" in result.stdout
    assert "tool call/result persisted atomically" in result.stdout
    assert "SMOKE PASS" in result.stdout
    assert (world / "codebase" / "smoke-artifact.txt").read_text() == "docket smoke ok\n"
    assert (
        world / ".docket" / "workspaces" / "projects" / "smoke-lead" / "TASK_LIST.json"
    ).is_file()


@pytest.mark.skipif(
    os.environ.get("DOCKET_RUN_LIVE_SMOKE") != "1",
    reason="set DOCKET_RUN_LIVE_SMOKE=1 to exercise the operator's local model",
)
def test_full_workflow_against_real_local_model(tmp_path: Path) -> None:
    """Opt-in memory-maintenance evidence; never substitutes scripted inference."""
    repo = Path(__file__).resolve().parents[2]
    world = tmp_path / "live-smoke-world"
    endpoint = os.environ.get("DOCKET_LIVE_SMOKE_ENDPOINT", "http://127.0.0.1:8081/v1")
    command = [
        sys.executable,
        "scripts/smoke_workflow.py",
        "--live-model",
        "--scenario",
        "memory-maintenance",
        "--endpoint",
        endpoint,
        "--workdir",
        str(world),
    ]
    model = os.environ.get("DOCKET_LIVE_SMOKE_MODEL", "").strip()
    if model:
        command.extend(["--model", model])

    result = subprocess.run(
        command,
        cwd=repo,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Real model endpoint:" in result.stdout
    assert "pre-existing regressions fail for the intended checkout defects" in result.stdout
    assert "realistic checkout fixture committed before worktree provisioning" in result.stdout
    assert "memory logs distilled and archived" in result.stdout
    assert "current durable decisions crossed the Lead handoff" in result.stdout
    assert "hidden checkout acceptance passed" in result.stdout
    assert "waiting_approval -> granted -> resumed" in result.stdout
    assert "SMOKE PASS" in result.stdout
    meta = json.loads(
        (
            world
            / ".docket"
            / "workspaces"
            / "projects"
            / "smoke-implementer"
            / ".docket-meta.json"
        ).read_text()
    )
    assert Path(meta["worktreeDir"], "src", "checkout.py").is_file()
    assert list(
        (
            world / ".docket" / "workspaces" / "projects" / "smoke-lead" / "memory" / ".distilled"
        ).glob("*/*.md")
    )
