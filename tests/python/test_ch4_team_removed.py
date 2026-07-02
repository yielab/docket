"""CH-4: `docket team` is retired — it must exit 1 with the pod-delegation mapping.

`docket team` used to be a second, manual task queue that nothing ever dispatched.
Pods now own delegation with real execution (`docket pod <project> delegate/queue/
dispatch`, backed by core/dispatch.py). This test locks in the removed-command
notice added to `src/docket/__main__.py`'s `_REMOVED` map.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run(args: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(tmp_path / ".openclaw"),
        "DOCKET_NO_RESTART": "1",
    }


def test_team_delegate_exits_1_with_pod_mapping(tmp_path: Path) -> None:
    rc, out, _ = _run(["team", "delegate", "x"], _env(tmp_path))
    assert rc == 1
    assert "docket pod <project> delegate" in out
    assert "docket pod <project> queue" in out
    assert "portfolio" in out.lower()


def test_team_queue_exits_1_with_pod_mapping(tmp_path: Path) -> None:
    rc, out, _ = _run(["team", "queue"], _env(tmp_path))
    assert rc == 1
    assert "docket pod <project> queue" in out


def test_team_old_queue_file_preserved_language(tmp_path: Path) -> None:
    rc, out, _ = _run(["team"], _env(tmp_path))
    assert rc == 1
    assert "TASK_LIST.json" in out
    assert "preserved" in out.lower()
