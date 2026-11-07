"""The verifier: run a task's `hidden/` checks on a copy of a repository the agent cannot reach.

`hidden/` is a pytest directory. The copy and the checks sit side by side under one verifier root,
never one inside the other, so a `conftest.py`, `pytest.ini` or `pyproject.toml` the agent wrote
into the repository is not on pytest's path and cannot change how the checks run or what they
report. The checks read the repository through the working directory and `EVAL_REPO`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RESULT_NAME = "result.txt"
_TAIL_CHARS = 2000
_NO_TESTS_COLLECTED = 5

Status = Literal["pass", "fail", "error"]


@dataclass(frozen=True)
class HiddenResult:
    status: Status
    exit_code: int
    output_tail: str


def run_hidden(repo: Path, hidden: Path, root: Path, *, timeout_s: float = 300.0) -> HiddenResult:
    """Copy `repo` and `hidden` under `root` (emptied first) and run the checks there; no test
    collected, a timeout or a missing `hidden/` is `error`, never `pass`."""
    if not hidden.is_dir():
        return HiddenResult("error", -1, f"no hidden/ directory at {hidden.name}")
    if root.exists():
        shutil.rmtree(root)
    copy = root / "repo"
    checks = root / "hidden"
    shutil.copytree(repo, copy, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    shutil.copytree(hidden, checks)
    env = {**os.environ, "EVAL_REPO": str(copy), "PYTHONPATH": str(copy)}
    env.pop("PYTEST_ADDOPTS", None)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--rootdir={checks}",
        f"--confcutdir={checks}",
        str(checks),
    ]
    try:
        done = subprocess.run(
            command, cwd=copy, env=env, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        result = HiddenResult("error", -1, f"hidden checks exceeded {timeout_s:.0f} s")
    else:
        output = (done.stdout + done.stderr)[-_TAIL_CHARS:]
        if done.returncode == 0:
            result = HiddenResult("pass", 0, output)
        elif done.returncode == 1:
            result = HiddenResult("fail", 1, output)
        else:
            reason = "no hidden test collected" if done.returncode == _NO_TESTS_COLLECTED else ""
            result = HiddenResult("error", done.returncode, (reason + "\n" + output).strip())
    (root / RESULT_NAME).write_text(f"{result.status} {result.exit_code}\n", encoding="utf-8")
    return result
