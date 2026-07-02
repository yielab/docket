"""CH-8 drift guard: shell completions must advertise exactly the live
Typer command set.

`_completions.py` generates the top-level command table from the Typer
`app` registry at call time (see its module docstring): the old hand-written
literal had drifted — it still advertised the retired `team`/`tier` commands
after CH-4/CH-6 removed them, and never learned `auth`/`policies`/`approve`/
`deny`/`metrics`. These tests independently re-derive the "true" command set
straight from the registry (not by importing `_completions`'s own helper) so
this is a real regression check, not a tautology: any future drift between
the CLI surface and the emitted completion scripts fails the suite instead
of shipping silently.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from docket.cli import _completions

REPO_ROOT = Path(__file__).resolve().parents[2]


def _live_command_names() -> set[str]:
    """Walk the Typer `app` registry directly (independent of _completions)."""
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
        _completions.run_completions("bash")
        out = capsys.readouterr().out
        assert _parse_bash_commands(out) == _live_command_names()

    def test_hidden_json_bridge_is_excluded(self, capsys: pytest.CaptureFixture[str]) -> None:
        _completions.run_completions("bash")
        out = capsys.readouterr().out
        assert "_json" not in _parse_bash_commands(out)


class TestZshCompletionsMatchRegistry:
    def test_advertises_exactly_the_live_command_set(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _completions.run_completions("zsh")
        out = capsys.readouterr().out
        assert _parse_zsh_commands(out) == _live_command_names()

    def test_hidden_json_bridge_is_excluded(self, capsys: pytest.CaptureFixture[str]) -> None:
        _completions.run_completions("zsh")
        out = capsys.readouterr().out
        assert "_json" not in _parse_zsh_commands(out)


class TestRetiredCommandsNeverAdvertised:
    """Phase-12 CH-4/CH-6 retired `team` and tier names; a completion script
    that still offers them is exactly the drift this card exists to kill."""

    @pytest.mark.parametrize("shell", ["bash", "zsh"])
    def test_team_and_tier_absent(self, shell: str, capsys: pytest.CaptureFixture[str]) -> None:
        _completions.run_completions(shell)
        out = capsys.readouterr().out
        assert "team" not in out
        for tier in ("economy", "standard", "premium", "tier"):
            assert tier not in out


class TestPhase11CommandsPresent:
    """At-minimum acceptance list from the CH-8 card."""

    REQUIRED = (
        "policies",
        "approve",
        "deny",
        "metrics",
        "keys",
        "auth",
        "context",
        "snapshot",
        "audit",
        "eval",
        "gates",
        "trace",
    )

    @pytest.mark.parametrize("shell", ["bash", "zsh"])
    def test_required_commands_present(
        self, shell: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _completions.run_completions(shell)
        out = capsys.readouterr().out
        names = _parse_bash_commands(out) if shell == "bash" else _parse_zsh_commands(out)
        missing = set(self.REQUIRED) - names
        assert not missing, f"completions ({shell}) missing: {sorted(missing)}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
class TestEvalSmokeCheck:
    """`eval "$(docket completions bash)"` must actually define the
    completion function in a real bash process — a syntax regression here
    would not be caught by pure string assertions."""

    def test_eval_docket_completions_bash_defines_function(self) -> None:
        docket_bin = REPO_ROOT / "bin" / "docket"
        script = (
            f'eval "$("{sys.executable}" -m docket completions bash)" && '
            "type _docket_complete >/dev/null 2>&1 && echo DEFINED"
        )
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert docket_bin.is_file()  # sanity: launcher exists alongside the module path used above
        assert result.returncode == 0, result.stderr
        assert "DEFINED" in result.stdout
