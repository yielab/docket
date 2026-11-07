"""Paths a change may not touch without a person: the files a check is defined by.

Pure functions over repository-relative paths, with one reader of a worktree
(``changed_protected``) and one of a folder (``hash_protected``, ``changed_hashes``). See security-gates.spec.md ("Protected paths and the reviewed digest") and
pod-dispatch.spec.md ("A change that edits its own check").
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import posixpath
import shlex
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path

from docket.kernel.errors import InvalidInput
from docket.kernel.ports import git as _git

# Each lockfile and the install command it implies; the lockfiles are protected paths too.
LOCKFILES: tuple[tuple[str, str], ...] = (
    ("package-lock.json", "npm ci"),
    ("pnpm-lock.yaml", "pnpm install --frozen-lockfile"),
    ("yarn.lock", "yarn install --immutable"),
    ("uv.lock", "uv sync --frozen"),
    ("poetry.lock", "poetry install"),
    ("Cargo.lock", "cargo fetch"),
)

DEFAULT_PATTERNS: tuple[str, ...] = (
    *(name for name, _command in LOCKFILES),
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
#: Docket's own state, which the tools refuse and the prompt names (the one list). ``.docket`` is a
#: directory, private as any path component; the files are private only as a direct child of a root
#: that is not a repository checkout (a repository's own ``AGENTS.md`` is the project's file).
PRIVATE_CONTROL_NAMES: tuple[str, ...] = (
    "HEARTBEAT.md",
    "AGENTS.md",
    "TOOLS.md",
    "MEMORY.md",
    ".docket",
)
_PRIVATE_DIR = ".docket"


def _holds_private_files(root: Path) -> bool:
    return not (root / ".git").exists()


def private_control_name(root: Path, parts: Sequence[str]) -> str | None:
    """The private name that *parts* (a path relative to *root*) names, else ``None``."""
    if _PRIVATE_DIR in parts:
        return _PRIVATE_DIR
    first = parts[0].casefold() if parts else ""
    if _holds_private_files(root):
        for name in PRIVATE_CONTROL_NAMES:
            if name != _PRIVATE_DIR and first == name.casefold():
                return name
    return None


def private_control_paths(root: Path) -> list[Path]:
    """The private paths directly under *root*, for a jail profile to deny."""
    files = (n for n in PRIVATE_CONTROL_NAMES if n != _PRIVATE_DIR and _holds_private_files(root))
    return [root / _PRIVATE_DIR, *(root / name for name in files)]


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
        *_git.git_diff_names(worktree, base_commit, branch),
        *_git.git_changed_files(worktree, all_untracked=True),
    }
    if not changed:
        return []
    named = command_files(commands, frozenset(_git.git_tracked_files(worktree)))
    return protected_among(changed, (*DEFAULT_PATTERNS, *patterns), named)


#: Directories a folder walk never enters, and the most files it lists before it stops.
_UNWALKED_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__"})
MAX_WALKED_FILES = 20000


def _folder_files(root: Path) -> list[str]:
    """The ``/``-separated paths of the regular files under *root*, symlinks not followed."""
    found: list[str] = []
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _UNWALKED_DIRS)
        base = Path(current)
        for name in sorted(names):
            if len(found) >= MAX_WALKED_FILES:
                return found
            if (base / name).is_symlink():
                continue
            found.append((base / name).relative_to(root).as_posix())
    return found


def _digests(
    root: Path, patterns: Iterable[str], commands: Iterable[str], named_from: Collection[str] | None
) -> dict[str, str]:
    files = _folder_files(root)
    candidates = (
        frozenset(files) if named_from is None else frozenset(files) & frozenset(named_from)
    )
    wanted = protected_among(
        files, (*DEFAULT_PATTERNS, *patterns), command_files(commands, candidates)
    )
    digests: dict[str, str] = {}
    for path in wanted:
        try:
            digests[path] = hashlib.sha256((root / path).read_bytes()).hexdigest()
        except OSError:
            continue
    return digests


def hash_protected(
    directory: str | Path, patterns: Iterable[str], commands: Iterable[str]
) -> dict[str, str]:
    """The sha256 of each protected file under *directory*: the defaults, *patterns* and the files
    *commands* name, keyed by relative path. ``{}`` when the folder cannot be read."""
    return _digests(Path(directory), patterns, commands, None)


def changed_hashes(
    directory: str | Path,
    recorded: Mapping[str, str],
    patterns: Iterable[str],
    commands: Iterable[str],
) -> list[str]:
    """The sorted protected paths whose digest under *directory* differs from *recorded*: edited,
    added or removed since. A file a command names is protected only if *recorded* holds it, so a
    check that reads the deliverable does not protect a file the task first created."""
    now = _digests(Path(directory), patterns, commands, recorded)
    return sorted(p for p in {*recorded, *now} if recorded.get(p) != now.get(p))
