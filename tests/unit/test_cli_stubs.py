"""Cutover guard: every command is ported — no `_not_ported` stubs remain.

Every command (including `install`) dispatches to Python, so the
invariant is: the CLI module must contain zero `_not_ported(` call sites.
"""

import os
from pathlib import Path

from typer.testing import CliRunner

from docket.cli import app

SUBJECT = "docket.cli"

_CLI = Path(__file__).resolve().parents[2] / "src" / "docket" / "cli" / "__init__.py"


def test_no_not_ported_callsites() -> None:
    source = _CLI.read_text(encoding="utf-8")
    # The helper definition may remain; assert it is never CALLED.
    # A real call passes a command-name string literal, e.g. _not_ported("serve").
    call_sites = [
        line.strip()
        for line in source.splitlines()
        if '_not_ported("' in line or "_not_ported('" in line
    ]
    assert call_sites == [], f"un-ported command stubs remain: {call_sites}"


def test_debug_flag_is_a_no_op() -> None:
    """--debug is a deprecated, hidden no-op: it must exit 0 and never set os.environ."""
    assert "DEBUG" not in os.environ
    try:
        result = CliRunner().invoke(app, ["--debug"])
        assert result.exit_code == 0
        assert "DEBUG" not in os.environ
    finally:
        os.environ.pop("DEBUG", None)
