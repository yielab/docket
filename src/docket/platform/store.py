"""Atomic JSON file I/O with filelock, .bak rotation, and 0600 permissions.

All reads and writes to docket-owned JSON files (.docket-meta.json,
fleet.json, and every other docket-owned registry) go through these two
functions.

Single-writer rule: this module is the one chokepoint for docket-owned JSON
writes. The one documented exemption is append-only JSONL
logs — ``observability/trace.py`` and ``governance/audit.py`` write directly, since each line
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
from pydantic import BaseModel, ValidationError

from docket.kernel.home import current_home
from docket.kernel.operator_contract import (
    Escalation,
    EscalationState,
    Resolution,
    is_escalation_id,
)

_LOCK_TIMEOUT = 10  # seconds


class StoreRecoveryError(json.JSONDecodeError):
    """A malformed JSON primary cannot be recovered from its owned backup."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "", 0)


class _NotJSONObject(ValueError):
    """A parsed Docket JSON document has the wrong top-level type."""


def mkdir_private(path: Path) -> None:
    """Create *path* and any missing parents; every directory this call creates is 0700,
    whatever the umask. An existing directory's mode is never changed."""
    missing: list[Path] = []
    current = path
    while not current.exists() and current != current.parent:
        missing.append(current)
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    for made in missing:
        os.chmod(made, 0o700)


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
    dispatch-queue claim race — see ``tasks/application/queue.py``). *fn* receives the
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
    _unlink_if_symlink(quarantine)
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
                _copy_backup(path)
        else:
            try:
                _parse_json_object(current_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError, _NotJSONObject):
                _write_quarantine(path, current_bytes)
            else:
                with contextlib.suppress(OSError):
                    _copy_backup(path)

    _replace_bytes(path, content.encode("utf-8"))


def _unlink_if_symlink(sibling: Path) -> None:
    """A planted symlink on a sibling name (`.tmp`, `.bak`, `.corrupt`) would redirect the
    write to wherever it points; remove the link itself, never its target."""
    if sibling.is_symlink():
        sibling.unlink()


def _copy_backup(path: Path) -> None:
    """Copy *path* to its `.bak` at 0600: copy2 keeps the original's mode, which may be looser."""
    backup = path.with_suffix(path.suffix + ".bak")
    _unlink_if_symlink(backup)
    shutil.copy2(path, backup)
    os.chmod(backup, 0o600)


def _replace_bytes(path: Path, content: bytes) -> None:
    """Atomically replace one owned file with mode 0600. The temporary file is created
    exclusively, 0600 from the first byte, and never through a symlink."""

    tmp = path.with_suffix(path.suffix + ".tmp")
    _unlink_if_symlink(tmp)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ── escalations ──────────────────────────────────────────────────────────────
# One 0600 file per pause beside a counter file; the directory's one lock orders every change.


def _escalation_path(escalation_id: str) -> Path:
    return current_home().escalations_dir / f"{escalation_id}.json"


def next_escalation_seq() -> int:
    """The next ``seq`` for an escalation: one counter file, incremented under the store lock."""
    folder = current_home().escalations_dir
    mkdir_private(folder)
    issued: list[int] = []

    def _bump(doc: dict[str, Any]) -> dict[str, Any]:
        issued[:] = [int(doc.get("seq", 0)) + 1]
        return {"seq": issued[0]}

    read_modify_write(folder / "_seq.json", _bump)
    return issued[0]


def write_escalation(escalation: Escalation) -> Escalation:
    """Persist *escalation*, numbering it when it has no ``seq`` yet; returns the record as stored."""
    stored = (
        escalation
        if escalation.seq
        else escalation.model_copy(update={"seq": next_escalation_seq()})
    )
    mkdir_private(current_home().escalations_dir)
    write_json(_escalation_path(stored.id), stored.model_dump(by_alias=True, mode="json"))
    return stored


def read_escalation(escalation_id: str) -> Escalation | None:
    """The record named *escalation_id*; ``None`` for a malformed id, an absent file or a file
    that is not a valid escalation."""
    if not is_escalation_id(escalation_id):
        return None
    return _parse_escalation(read_json(_escalation_path(escalation_id)))


def _parse_escalation(doc: dict[str, Any]) -> Escalation | None:
    try:
        return Escalation.model_validate(doc) if doc else None
    except ValidationError:
        return None


def list_escalations(
    state: EscalationState | None = None, since_seq: int | None = None
) -> list[Escalation]:
    """Every valid record ordered by ``seq``; only those in *state* and with ``seq`` greater than
    *since_seq* when given."""
    folder = current_home().escalations_dir
    if not folder.is_dir():
        return []
    found = (read_escalation(path.stem) for path in sorted(folder.glob("esc-*.json")))
    return sorted(
        (
            e
            for e in found
            if e is not None
            and (state is None or e.state == state)
            and (since_seq is None or e.seq > since_seq)
        ),
        key=lambda e: e.seq,
    )


def _settle(escalation_id: str, state: EscalationState) -> bool:
    moved: list[bool] = []

    def _move(doc: dict[str, Any]) -> dict[str, Any] | None:
        current = _parse_escalation(doc)
        if current is None or current.state != "pending":
            return None
        moved.append(True)
        return current.model_copy(update={"state": state}).model_dump(by_alias=True, mode="json")

    read_modify_write(_escalation_path(escalation_id), _move)
    return bool(moved)


def resolve_escalation(escalation_id: str, resolution: Resolution) -> Escalation | None:
    """Move the record *escalation_id* from ``pending`` to ``resolved`` carrying *resolution*; the
    record as stored, or ``None`` when it was not pending (another caller settled it first)."""
    settled: list[Escalation] = []

    def _move(doc: dict[str, Any]) -> dict[str, Any] | None:
        current = _parse_escalation(doc)
        if current is None or current.state != "pending":
            return None
        moved = current.model_copy(update={"state": "resolved", "resolution": resolution})
        settled.append(moved)
        return moved.model_dump(by_alias=True, mode="json")

    read_modify_write(_escalation_path(escalation_id), _move)
    return settled[0] if settled else None


def mark_escalation_applied(escalation_id: str, at: str) -> bool:
    """Stamp ``resolution.applied_at`` on the record *escalation_id* when it is ``resolved`` and not
    stamped yet; whether this call did (two callers racing see exactly one ``True``)."""
    stamped: list[bool] = []

    def _stamp(doc: dict[str, Any]) -> dict[str, Any] | None:
        current = _parse_escalation(doc)
        if current is None or current.state != "resolved" or current.resolution is None:
            return None
        if current.resolution.applied_at is not None:
            return None
        stamped.append(True)
        resolution = current.resolution.model_copy(update={"applied_at": at})
        return current.model_copy(update={"resolution": resolution}).model_dump(
            by_alias=True, mode="json"
        )

    read_modify_write(_escalation_path(escalation_id), _stamp)
    return bool(stamped)


def settle_escalation(key: str, value: str, state: EscalationState) -> bool:
    """Move the one pending escalation whose ``legacy[key]`` is *value* to *state*; whether one
    moved."""
    return any(
        _settle(e.id, state)
        for e in list_escalations(state="pending")
        if e.legacy.get(key) == value
    )
