"""The installed console-script entry point, and `_ALIASES` resolution.

`pyproject.toml`'s `[project.scripts]` maps `docket` to an object every pip/uv/Homebrew
install actually runs, which must be `docket.__main__:main` and never the bare Typer `app`
directly -- pointing it at `app` bypasses the `_REMOVED` notices and `_ALIASES` table
entirely, and `test_removed_commands.py`'s `python -m docket` cannot catch that regression.

This resolves the entry point the way pip's generated launcher does --
`importlib.metadata.entry_points(group="console_scripts")` -- and drives that object through
one removed command and one alias, so a regression fails here even though `python -m docket`
still passes.
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

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


def test_entry_point_targets_main_not_the_raw_typer_app() -> None:
    assert _entry_point_target() == "docket.__main__:main"


def test_entry_point_honours_removed_command_notice(tmp_path: Path) -> None:
    result = _run_entry_point(["team", "delegate", "fix login"], tmp_path)
    assert result.returncode == 1
    assert "docket team was retired" in result.stdout


def test_entry_point_resolves_an_alias(tmp_path: Path) -> None:
    # "show" aliases to "info"; --help is side-effect-free and proves the rewrite
    # happened without depending on any project/agent state.
    result = _run_entry_point(["show", "--help"], tmp_path)
    assert result.returncode == 0
    assert "Detailed status of one agent" in result.stdout


def test_module_invocation_still_works_unguarded(tmp_path: Path) -> None:
    """`python -m docket` must be unaffected by guarding `main()` under `__name__`."""
    env = {**os.environ, "DOCKET_HOME": str(tmp_path / ".docket")}
    result = subprocess.run(
        [sys.executable, "-m", "docket", "team"], capture_output=True, text=True, env=env
    )
    assert result.returncode == 1
    assert "docket team was retired" in result.stdout


def test_importing_dunder_main_has_no_side_effect() -> None:
    """Importing the module (as the entry point's resolver does) must not call `main()`."""
    result = subprocess.run(
        [sys.executable, "-c", "import docket.__main__"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
