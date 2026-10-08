"""Guard: every leaf command's `--help` carries an `Example:` line and every group's help renders.

The walk starts at the registry, so a verb added anywhere in the tree is covered without a list.
"""

from __future__ import annotations

import pytest
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from docket.cli import app

_runner = CliRunner()


def _walk(
    cmd: object, path: tuple[str, ...], leaves: list[tuple[str, ...]], groups: list[tuple[str, ...]]
) -> None:
    children = getattr(cmd, "commands", None)
    if children is None:
        leaves.append(path)
        return
    groups.append(path)
    for name, sub in children.items():
        if not getattr(sub, "hidden", False):
            _walk(sub, (*path, name), leaves, groups)


def _tree() -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
    root = get_command(app)
    assert isinstance(root, TyperGroup)
    leaves: list[tuple[str, ...]] = []
    groups: list[tuple[str, ...]] = []
    _walk(root, (), leaves, groups)
    return leaves, groups


_LEAVES, _GROUPS = _tree()


def _id(path: tuple[str, ...]) -> str:
    return " ".join(path) or "docket"


@pytest.mark.parametrize("path", _LEAVES, ids=_id)
def test_every_leaf_help_exits_zero_and_carries_an_example(path: tuple[str, ...]) -> None:
    result = _runner.invoke(app, [*path, "--help"])

    assert result.exit_code == 0, f"docket {_id(path)} --help exited {result.exit_code}"
    assert "Example:" in result.output, f"docket {_id(path)} --help has no 'Example:' line"


@pytest.mark.parametrize("path", _GROUPS, ids=_id)
def test_every_group_help_exits_zero(path: tuple[str, ...]) -> None:
    result = _runner.invoke(app, [*path, "--help"])

    assert result.exit_code == 0, f"docket {_id(path)} --help exited {result.exit_code}"
