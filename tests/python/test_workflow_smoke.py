"""Executable whole-product smoke test.

The harness crosses the real CLI subprocess and loopback HTTP boundaries. Focused suites own the
failure matrix; this test owns one observable proof that the happy-path components compose.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
