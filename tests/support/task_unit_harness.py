"""Helpers shared by the split halves of one test file."""

from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

from docket.interfaces.cli.app import app

_runner = CliRunner()


def invoke_task(*args: str) -> Any:
    """Run `docket task <args>` and return the runner's result."""
    return _runner.invoke(app, ["task", *args])
