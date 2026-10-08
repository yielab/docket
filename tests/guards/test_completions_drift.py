"""Drift guard: shell completions must advertise exactly the live
Typer command set.

`_setup_shell.py` generates the top-level command table from the Typer
`app` registry at call time (see its module docstring). These tests
independently re-derive the "true" command set straight from the registry
(not by importing `_setup_shell`'s own helper), so this is a real
regression check, not a tautology: any future drift between the CLI
surface and the emitted completion scripts fails the suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from docket.cli import _setup_shell

REPO_ROOT = Path(__file__).resolve().parents[2]


def _live_command_names() -> set[str]:
    """Walk the Typer `app` registry directly (independent of _setup_shell)."""
    from typer.core import TyperGroup
    from typer.main import get_command

    from docket.cli import app

    click_group = get_command(app)
    assert isinstance(click_group, TyperGroup)
    return {name for name, cmd in click_group.commands.items() if not getattr(cmd, "hidden", False)}


def _parse_bash_commands(script: str) -> set[str]:
    match = re.search(r'local commands="([^"]*)"', script)
    assert match, 'bash script is missing the `local commands="..."` line'
    return set(match.group(1).split())


def _parse_zsh_commands(script: str) -> set[str]:
    block = re.search(r"commands=\(\n(.*?)\n\s*\)\n", script, re.DOTALL)
    assert block, "zsh script is missing the `commands=( ... )` array"
    names = re.findall(r"^\s*'([^:']+):", block.group(1), re.MULTILINE)
    assert names, "no command entries parsed out of the zsh commands array"
    return set(names)


class TestBashCompletionsMatchRegistry:
    def test_advertises_exactly_the_live_command_set(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print(_setup_shell.render_bash(), end="")
        out = capsys.readouterr().out
        assert _parse_bash_commands(out) == _live_command_names()


class TestZshCompletionsMatchRegistry:
    def test_advertises_exactly_the_live_command_set(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print(_setup_shell.render_zsh(), end="")
        out = capsys.readouterr().out
        assert _parse_zsh_commands(out) == _live_command_names()


class TestCommandsPresent:
    """At-minimum acceptance list of commands completions must advertise."""

    REQUIRED = (
        "setup",
        "log",
        "task",
    )

    @pytest.mark.parametrize("shell", ["bash", "zsh"])
    def test_required_commands_present(
        self, shell: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print(_setup_shell.render_bash() if shell == "bash" else _setup_shell.render_zsh(), end="")
        out = capsys.readouterr().out
        names = _parse_bash_commands(out) if shell == "bash" else _parse_zsh_commands(out)
        missing = set(self.REQUIRED) - names
        assert not missing, f"completions ({shell}) missing: {sorted(missing)}"
