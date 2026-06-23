"""Cutover guard: every command is ported — no `_not_ported` stubs remain.

This file used to assert that un-ported commands exited 127. After M6 every
command (including `install`) dispatches to Python, so the inverse is now the
invariant: the CLI module must contain zero `_not_ported(` call sites.
"""

from pathlib import Path

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
