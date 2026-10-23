"""Prepare the worktree docket makes for a task: pick an install command, run it once per lockfile.

Resolution is pure. ``prepare_worktree`` keeps what an install left in ``node_modules`` under
``Home.prepare_cache_dir`` and links it into the worktree; the command itself is run by the
caller, so dispatch decides the jail. See pod-dispatch.spec.md ("Task preparation").
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from filelock import FileLock

from docket.kernel import clock as _clock
from docket.kernel.errors import InvalidInput
from docket.kernel.git import git as _git
from docket.kernel.home import current_home

LOCKFILES: tuple[tuple[str, str], ...] = (
    ("package-lock.json", "npm ci"),
    ("pnpm-lock.yaml", "pnpm install --frozen-lockfile"),
    ("yarn.lock", "yarn install --immutable"),
    ("uv.lock", "uv sync --frozen"),
    ("poetry.lock", "poetry install"),
    ("Cargo.lock", "cargo fetch"),
)
LINKED_DIRS: tuple[str, ...] = ("node_modules",)
MAX_COMMAND_CHARS = 1000

Source = Literal["task", "pod", "lockfile"]
Runner = Callable[[str], tuple[int | None, str]]


def check_command(value: object) -> str:
    """The command as one stripped line; raises ``ValueError`` for a NUL, a newline or too long."""
    text = str(value or "").strip()
    if "\x00" in text or "\n" in text or "\r" in text:
        raise InvalidInput("must be one line without a NUL byte")
    if len(text) > MAX_COMMAND_CHARS:
        raise InvalidInput(f"must be at most {MAX_COMMAND_CHARS} characters")
    return text


def is_off(command: str) -> bool:
    """Whether *command* turns preparation off: blank or ``none``."""
    return command.strip().lower() in ("", "none")


def lockfile_in(root: Path) -> tuple[str, str] | None:
    """``(lockfile name, its derived command)`` for the first lockfile at *root*'s top level."""
    for name, command in LOCKFILES:
        if (root / name).is_file():
            return name, command
    return None


@dataclass(frozen=True)
class PrepareSpec:
    """What to run: the *command*, where it came from and the lockfile's sha256 (``""`` if none)."""

    command: str
    source: Source
    lock_hash: str


@dataclass(frozen=True)
class PrepareOutcome:
    """How a preparation ended: the exit status (``None`` on a hit or a command that never ran)."""

    ok: bool
    cache_hit: bool
    exit_code: int | None
    seconds: float
    output: str


def resolve(root: Path, *, task_prepare: object, pod_prepare: str) -> PrepareSpec | None:
    """The command for *root*: the task's ``prepare`` (even blank), else the pod's, else the
    lockfile's; ``None`` when off or when there is nothing to run."""
    found = lockfile_in(root)
    lock_hash = hashlib.sha256((root / found[0]).read_bytes()).hexdigest() if found else ""
    if isinstance(task_prepare, str):
        source: Source = "task"
        command = task_prepare.strip()
    elif pod_prepare.strip():
        source, command = "pod", pod_prepare.strip()
    elif found:
        source, command = "lockfile", found[1]
    else:
        return None
    return None if is_off(command) else PrepareSpec(command, source, lock_hash)


def needs_prepare(root: Path, prepared: object, spec: PrepareSpec) -> bool:
    """False when the task record says this command and lockfile were prepared and no link broke."""
    if not isinstance(prepared, dict):
        return True
    if prepared.get("command") != spec.command or prepared.get("lockHash") != spec.lock_hash:
        return True
    return any((root / n).is_symlink() and not (root / n).exists() for n in LINKED_DIRS)


def record(spec: PrepareSpec, outcome: PrepareOutcome) -> dict[str, Any]:
    """The ``prepared`` entry stored on the task."""
    return {
        "command": spec.command,
        "source": spec.source,
        "lockHash": spec.lock_hash,
        "cacheHit": outcome.cache_hit,
    }


def codebase_dir(codebase: str) -> Path:
    """Where the entries of one codebase live."""
    resolved = Path(codebase).resolve()
    key = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
    return current_home().prepare_cache_dir / f"{resolved.name or 'repo'}-{key}"


def entry_dir(codebase: str, spec: PrepareSpec) -> Path:
    """The cache entry for *spec*'s lockfile and command."""
    command = hashlib.sha256(spec.command.encode()).hexdigest()[:8]
    return codebase_dir(codebase) / f"{spec.lock_hash[:16]}-{command}"


def linked_entries(root: str | Path) -> tuple[Path, ...]:
    """The cache entries *root* links into, found from its own symlinks and never outside the
    cache: the read-only roots a jailed command in *root* needs."""
    base = current_home().prepare_cache_dir.resolve()
    found: dict[Path, None] = {}
    for name in LINKED_DIRS:
        link = Path(root) / name
        if not link.is_symlink():
            continue
        try:
            rel = link.resolve().relative_to(base).parts
        except (ValueError, OSError):
            continue
        if len(rel) >= 3:
            found.setdefault(base / rel[0] / rel[1], None)
    return tuple(found)


def _link(entry: Path, root: Path) -> list[str]:
    linked: list[str] = []
    for name in LINKED_DIRS:
        target, link = entry / name, root / name
        if not target.is_dir():
            continue
        if link.is_symlink() and not link.exists():
            link.unlink()
        if link.exists() or link.is_symlink():
            continue
        link.symlink_to(target, target_is_directory=True)
        linked.append(name)
    return linked


def _store(entry: Path, root: Path) -> None:
    partial = entry.with_name(entry.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    moved: list[str] = []
    try:
        for name in LINKED_DIRS:
            source = root / name
            if source.is_dir() and not source.is_symlink():
                shutil.move(str(source), str(partial / name))
                moved.append(name)
        if not moved:
            shutil.rmtree(partial, ignore_errors=True)
            return
        os.rename(partial, entry)
    except OSError:
        for name in moved:
            if not (root / name).exists() and (partial / name).exists():
                shutil.move(str(partial / name), str(root / name))
        shutil.rmtree(partial, ignore_errors=True)


def _evict(directory: Path, keep: int) -> None:
    entries = [p for p in directory.iterdir() if p.is_dir() and not p.name.endswith(".partial")]
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in entries[keep:]:
        shutil.rmtree(stale, ignore_errors=True)


def prepare_worktree(
    spec: PrepareSpec, root: Path, codebase: str, common_dir: str, run: Runner
) -> PrepareOutcome:
    """Prepare *root*: link the cache entry for *spec* when it exists, else run the command
    through *run* (under the codebase's lock) and keep ``node_modules`` as the entry. Without a
    lockfile nothing is cached."""
    start = _clock.monotonic()
    if not spec.lock_hash or not codebase:
        code, output = run(spec.command)
        return PrepareOutcome(code == 0, False, code, _clock.monotonic() - start, output)
    entry = entry_dir(codebase, spec)
    directory = entry.parent
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / ".lock")):
        if entry.is_dir():
            with contextlib.suppress(OSError):
                os.utime(entry)
            names = _link(entry, root)
            _exclude(common_dir, names)
            return PrepareOutcome(True, True, None, _clock.monotonic() - start, "")
        code, output = run(spec.command)
        if code == 0:
            _store(entry, root)
            if entry.is_dir():
                _exclude(common_dir, _link(entry, root))
                _evict(directory, current_home().prepare_cache_keep)
        return PrepareOutcome(code == 0, False, code, _clock.monotonic() - start, output)


def _exclude(common_dir: str, names: list[str]) -> None:
    if common_dir and names:
        _git.git_info_exclude(common_dir, tuple(f"/{n}" for n in names))
