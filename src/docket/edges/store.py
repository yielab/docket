"""Atomic JSON file I/O with filelock, .bak rotation, and 0600 permissions.

All reads and writes to docket-owned JSON files (both .docket-meta.json and
openclaw.json) go through these two functions. The ACL (edges/adapters/openclaw.py)
is the only caller for openclaw-owned files.

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
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout
from pydantic import BaseModel

_LOCK_TIMEOUT = 10  # seconds


def _lock_path(target: Path) -> Path:
    # Shared lock file per directory so concurrent writes to any file in the
    # same dir are serialised without deadlock (a single lock per dir, never nested).
    return target.parent / ".docket.lock"


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

    lock = FileLock(str(_lock_path(path)), timeout=_LOCK_TIMEOUT)
    try:
        with lock:
            _atomic_write(path, serialised)
    except Timeout:
        raise RuntimeError(
            f"Could not acquire lock for {path} within {_LOCK_TIMEOUT}s "
            "(is another docket process running?)"
        ) from None


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
