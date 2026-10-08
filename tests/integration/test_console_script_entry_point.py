"""The installed console-script entry point.

`pyproject.toml`'s `[project.scripts]` maps `docket` to the object every pip/uv/Homebrew install
runs. This resolves it the way pip's generated launcher does --
`importlib.metadata.entry_points(group="console_scripts")` -- and drives it, so a broken target
fails here even though `python -m docket` still passes.
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

import pytest

SUBJECT = "docket"


def _entry_point_target() -> str:
    eps = [
        ep for ep in importlib.metadata.entry_points(group="console_scripts") if ep.name == "docket"
    ]
    assert eps, "docket console_scripts entry point is not registered in this environment"
    return eps[0].value


def _run_entry_point(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    module_name, _, attr = _entry_point_target().partition(":")
    code = (
        f"import sys; from {module_name} import {attr} as _entry; "
        f"sys.argv = ['docket', *{args!r}]; _entry()"
    )
    env = {**os.environ, "DOCKET_HOME": str(tmp_path / ".docket")}
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)


def test_entry_point_targets_main() -> None:
    assert _entry_point_target() == "docket.__main__:main"


def test_entry_point_runs_a_command(tmp_path: Path) -> None:
    result = _run_entry_point(["info", "--help"], tmp_path)
    assert result.returncode == 0
    assert "Detailed status of one agent" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["team", "delegate", "fix login"],
        ["list"],
        ["context"],
        ["logs"],
        ["edit"],
        ["scope"],
        ["persona"],
        ["help"],
    ],
)
def test_a_retired_command_name_is_an_unknown_command(args: list[str], tmp_path: Path) -> None:
    """No old name is resolved or explained: it fails like any other unknown command."""
    result = _run_entry_point(args, tmp_path)
    assert result.returncode == 2
    assert "No such command" in result.stderr


def test_module_invocation_runs_the_app(tmp_path: Path) -> None:
    env = {**os.environ, "DOCKET_HOME": str(tmp_path / ".docket")}
    result = subprocess.run(
        [sys.executable, "-m", "docket", "info", "--help"], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0
    assert "Detailed status of one agent" in result.stdout


def test_importing_dunder_main_has_no_side_effect() -> None:
    """Importing the module (as the entry point's resolver does) must not call `main()`."""
    result = subprocess.run(
        [sys.executable, "-c", "import docket.__main__"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
