"""Command classifier verdicts for wrappers and deleting flags of allowlisted bins."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.core.security import classify_command

SUBJECT = "docket.core.security"


@pytest.mark.parametrize(
    "command",
    [
        "env rm -rf x",
        "env FOO=1 -i rm -rf x",
        "echo a | xargs rm",
        "echo a | xargs -n1 -I{} rm {}",
        "nice -n 5 rm x",
        "nohup rm x",
        "timeout 5 rm x",
        "time rm x",
        "command rm x",
        "stdbuf -oL rm x",
        "setsid rm x",
        "setsid pytest",
        "env env env env env env env rm x",
        "find . -delete",
        "find . -exec rm {} +",
        "find . -execdir rm {} ;",
        "find . -fprint out.txt",
        "awk 'BEGIN{system(\"rm x\")}'",
        "awk '{print > \"f\"}' in",
        "awk '{print >> \"f\"}' in",
        "awk '{print | \"sh\"}' in",
    ],
)
def test_unsafe_behind_allowlisted_name_asks(command: str) -> None:
    """A dangerous operation behind an allowlisted wrapper or flag still asks."""
    assert classify_command(command).action == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "env",
        "env FOO=1",
        "env FOO=1 pytest",
        "xargs",
        "echo a | xargs grep foo",
        "timeout 5 pytest",
        "find . -name '*.py'",
        "awk '{print $1}' f",
        "python3 -c 'print(1)'",
        "mkdir -p a && touch a/b && cp a/b a/c && mv a/c a/d",
    ],
)
def test_benign_wrapped_commands_stay_allowed(command: str) -> None:
    """Wrappers around allowlisted bins and plain find/awk remain allowed."""
    assert classify_command(command).action == "allow"


def test_jailed_find_delete_is_not_asked(tmp_path: Path) -> None:
    """Inside a working jail the allowlist stands down, so find -delete and env rm are allowed."""
    for command in ("find . -delete", "env rm -rf x", "echo a | xargs rm"):
        assert classify_command(command, roots=(tmp_path,), jailed=True).action == "allow"
