"""Atomic JSON file I/O with filelock, .bak rotation, and 0600 permissions.

All reads and writes to docket-owned JSON files (.docket-meta.json,
fleet.json, and every other docket-owned registry) go through these two
functions.

Single-writer rule (D-12, ROADMAP §6): this module is the one chokepoint for
docket-owned JSON writes. The one documented exemption is append-only JSONL
logs — ``core/trace.py`` and ``core/audit.py`` write directly, since each line
is an independent, self-contained append rather than a read-modify-write of a
whole document; everything else goes through ``write_json``.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout
from pydantic import BaseModel

_LOCK_TIMEOUT = 10  # seconds


def _lock_path(target: Path) -> Path:
    # Shared lock file per directory so concurrent writes to any file in the
    # same dir are serialised without deadlock (a single lock per dir, never nested).
    return target.parent / ".docket.lock"


def _acquire(path: Path) -> FileLock:
    """A fresh FileLock for *path*'s per-directory lock file (never reused/shared)."""
    return FileLock(str(_lock_path(path)), timeout=_LOCK_TIMEOUT)


def _lock_timeout_error(path: Path) -> RuntimeError:
    return RuntimeError(
        f"Could not acquire lock for {path} within {_LOCK_TIMEOUT}s "
        "(is another docket process running?)"
    )


@contextlib.contextmanager
def with_lock(path: Path) -> Iterator[None]:
    """Hold *path*'s per-directory filelock for the duration of the ``with`` block.

    Use this to make a multi-step read-modify-write atomic against every other
    docket process/thread touching the same directory (the same lock file
    ``write_json`` uses) — ``read_modify_write`` below is built directly on
    this primitive. Do **not** call ``write_json`` on the same path from
    inside a ``with_lock`` block — that would try to acquire the lock a second
    time and block forever; use ``read_modify_write`` (or the module-private
    ``_atomic_write``) for the write step instead.
    """
    lock = _acquire(path)
    try:
        with lock:
            yield
    except Timeout:
        raise _lock_timeout_error(path) from None


def read_modify_write(
    path: Path, fn: Callable[[dict[str, Any]], dict[str, Any] | None]
) -> dict[str, Any]:
    """Locked read-modify-write: the one safe way to do read-then-write on one file.

    Holds *path*'s per-directory filelock (via ``with_lock``) across the whole
    read + *fn* + write, so no concurrent ``write_json``/``read_modify_write``
    call on the same path can interleave (this is what closes the
    dispatch-queue claim race — see ``core/dispatch.py``). *fn* receives the
    file's current contents (``{}`` if it doesn't exist yet) and returns the
    new contents to persist, or ``None`` to abort without writing (e.g.
    "nothing eligible to claim"). Returns whatever ended up in the file (the
    new contents, or the unmodified current contents when *fn* returned
    ``None``).
    """
    with with_lock(path):
        current = read_json(path)
        updated = fn(current)
        if updated is None:
            return current
        _atomic_write(path, json.dumps(updated, indent=2) + "\n")
        return updated


def read_json(path: Path) -> dict[str, Any]:
    """Parse a JSON file; return {} when it does not exist."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def write_json(path: Path, data: dict[str, Any] | BaseModel) -> None:
    """Atomically write *data* to *path* with 0600 permissions.

    Steps:
      1. Validate serializability before touching the file.
      2. Acquire an exclusive filelock (timeout: 10s).
      3. Copy current file to .bak.
      4. Write to .tmp sibling, chmod 0600, then os.replace (atomic on POSIX).
    """
    if isinstance(data, BaseModel):
        payload: dict[str, Any] = data.model_dump(by_alias=True, exclude_none=False)
    else:
        payload = data

    serialised = json.dumps(payload, indent=2) + "\n"

    lock = _acquire(path)
    try:
        with lock:
            _atomic_write(path, serialised)
    except Timeout:
        raise _lock_timeout_error(path) from None


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically.  Caller must hold the lock."""
    if path.exists():
        with contextlib.suppress(OSError):
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
