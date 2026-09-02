"""Atomic JSON file I/O with filelock, .bak rotation, and 0600 permissions.

All reads and writes to docket-owned JSON files (.docket-meta.json,
fleet.json, and every other docket-owned registry) go through these two
functions.

Single-writer rule: this module is the one chokepoint for docket-owned JSON
writes. The one documented exemption is append-only JSONL
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
from typing import Any, cast

from filelock import FileLock, Timeout
from pydantic import BaseModel

_LOCK_TIMEOUT = 10  # seconds


class StoreRecoveryError(json.JSONDecodeError):
    """A malformed JSON primary cannot be recovered from its owned backup."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "", 0)


class _NotJSONObject(ValueError):
    """A parsed Docket JSON document has the wrong top-level type."""


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
        current = _read_json_unlocked(path)
        updated = fn(current)
        if updated is None:
            return current
        _atomic_write(path, json.dumps(updated, indent=2) + "\n")
        return updated


def read_json(path: Path) -> dict[str, Any]:
    """Read one object, recovering a malformed primary from its valid backup."""
    if not path.exists() and not path.parent.exists():
        return {}
    with with_lock(path):
        return _read_json_unlocked(path)


def _read_json_unlocked(path: Path) -> dict[str, Any]:
    """Read or recover *path* while its per-directory lock is already held."""
    if not path.exists():
        return {}

    primary_bytes = path.read_bytes()
    try:
        return _parse_json_object(primary_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, _NotJSONObject):
        return _recover_from_backup(path, primary_bytes)


def _parse_json_object(raw: bytes) -> dict[str, Any]:
    parsed: Any = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise _NotJSONObject("Docket-owned JSON must contain an object")
    return cast(dict[str, Any], parsed)


def _recover_from_backup(path: Path, malformed_bytes: bytes) -> dict[str, Any]:
    backup = path.with_suffix(path.suffix + ".bak")
    try:
        backup_bytes = backup.read_bytes()
    except FileNotFoundError:
        raise StoreRecoveryError(
            f"Cannot recover malformed {path}: backup {backup} is missing; "
            "restore a valid backup or replace the primary manually."
        ) from None
    except OSError as exc:
        raise StoreRecoveryError(
            f"Cannot recover malformed {path}: backup {backup} is unreadable "
            f"({exc.strerror or type(exc).__name__}); restore a valid backup or replace "
            "the primary manually."
        ) from None

    try:
        recovered = _parse_json_object(backup_bytes)
        backup_text = backup_bytes.decode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError, _NotJSONObject):
        raise StoreRecoveryError(
            f"Cannot recover malformed {path}: backup {backup} is malformed; "
            "restore a valid backup or replace the primary manually."
        ) from None

    _write_quarantine(path, malformed_bytes)
    _atomic_write(path, backup_text, rotate_backup=False)
    return recovered


def _write_quarantine(path: Path, malformed_bytes: bytes) -> None:
    quarantine = path.with_suffix(path.suffix + ".corrupt")
    _replace_bytes(quarantine, malformed_bytes)


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


def _atomic_write(path: Path, content: str, *, rotate_backup: bool = True) -> None:
    """Write *content* to *path* atomically.  Caller must hold the lock."""
    if rotate_backup and path.exists():
        try:
            current_bytes = path.read_bytes()
        except OSError:
            with contextlib.suppress(OSError):
                shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        else:
            try:
                _parse_json_object(current_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError, _NotJSONObject):
                _write_quarantine(path, current_bytes)
            else:
                with contextlib.suppress(OSError):
                    shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))

    _replace_bytes(path, content.encode("utf-8"))


def _replace_bytes(path: Path, content: bytes) -> None:
    """Atomically replace one owned file with mode 0600."""

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
