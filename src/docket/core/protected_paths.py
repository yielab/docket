"""Paths a change may not touch without a person: the files a check is defined by.

Pure functions over repository-relative paths, with one reader of a worktree
(``changed_protected``). See security-gates.spec.md ("Protected paths and the reviewed digest") and
pod-dispatch.spec.md ("A change that edits its own check").
"""

from __future__ import annotations

import fnmatch
import posixpath
import shlex
from collections.abc import Collection, Iterable

from docket.core import prepare as _prepare
from docket.edges.adapters import system as _sys
from docket.kernel.errors import InvalidInput

DEFAULT_PATTERNS: tuple[str, ...] = (
    *(name for name, _command in _prepare.LOCKFILES),
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    ".eslintrc*",
    "eslint.config.*",
    "tsconfig*.json",
    "vitest.config.*",
    "jest.config.*",
    "ruff.toml",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
    "mypy.ini",
    ".docket/**",
    ".github/workflows/**",
)
MAX_PATTERNS = 50
MAX_PATTERN_CHARS = 200
MAX_LISTED_PATHS = 20


def check_pattern(value: object) -> str:
    """The stripped glob; raises ``ValueError`` for an empty, long, absolute or escaping one, or
    one holding a comma, NUL or newline."""
    text = str(value or "").strip()
    if not text:
        raise InvalidInput("must not be empty")
    if len(text) > MAX_PATTERN_CHARS:
        raise InvalidInput(f"must be at most {MAX_PATTERN_CHARS} characters")
    if any(ch in text for ch in (",", "\x00", "\n", "\r")):
        raise InvalidInput("must not contain a comma, NUL or newline")
    if text.startswith("/") or ".." in text.split("/"):
        raise InvalidInput("must be a path inside the repository")
    return text


def matches(path: str, patterns: Iterable[str]) -> bool:
    """Whether *path* matches a pattern: one without ``/`` is matched against the file name at
    any depth, one with ``/`` against the whole path (``*`` crossing ``/``)."""
    name = path.rsplit("/", 1)[-1]
    for pattern in patterns:
        target = path if "/" in pattern else name
        if fnmatch.fnmatchcase(target, pattern):
            return True
    return False


def _tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return command.split()


def command_files(commands: Iterable[str], tracked: Collection[str]) -> frozenset[str]:
    """The tracked files *commands* name: a token, or the part of ``--flag=value`` after the
    ``=``, that is a tracked path once a leading ``./`` is removed."""
    known = tracked if isinstance(tracked, (set, frozenset)) else frozenset(tracked)
    found: set[str] = set()
    for command in commands:
        for token in _tokens(command):
            for candidate in (token, token.split("=", 1)[-1]):
                path = posixpath.normpath(candidate.removeprefix("./")) if candidate else ""
                if path in known:
                    found.add(path)
    return frozenset(found)


def protected_among(
    changed: Iterable[str], patterns: Iterable[str], named: Collection[str] = ()
) -> list[str]:
    """The sorted *changed* paths that match *patterns* or are in *named*."""
    listed = tuple(patterns)
    return sorted({p for p in changed if p in named or matches(p, listed)})


def changed_protected(
    worktree: str,
    base_commit: str,
    branch: str,
    patterns: Iterable[str],
    commands: Iterable[str],
) -> list[str]:
    """The protected paths a task's worktree changed: ``git diff --name-only base..branch`` plus
    its uncommitted and untracked paths, against the defaults, *patterns* and the tracked files
    *commands* name. ``[]`` when git can say nothing."""
    changed = {
        *_sys.git_diff_names(worktree, base_commit, branch),
        *_sys.git_changed_files(worktree, all_untracked=True),
    }
    if not changed:
        return []
    named = command_files(commands, frozenset(_sys.git_tracked_files(worktree)))
    return protected_among(changed, (*DEFAULT_PATTERNS, *patterns), named)
