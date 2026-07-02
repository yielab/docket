"""Audit log for mutating operations.

Appends one JSON line per change to ``$OPENCLAW_DIR/audit.log`` (0600) recording
who/when/what — table stakes for "what changed this agent/binding/key, and when".
Secret VALUES are never logged: callers pass only the key name / action target.
Disable all writes with ``DOCKET_NO_AUDIT=1``.

Exempt from the store.py single-writer rule (D-12, ROADMAP §6): appends are
line-independent, not a read-modify-write of a whole document, so this module
writes JSONL directly rather than through ``edges/store.py``. The log lives
under OPENCLAW_DIR but is a docket-owned artefact, not an openclaw config
file, so it does not go through the ACL either.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import json
import os
from typing import Any

import docket.config as _cfg


def _utc_now() -> str:
    """Return current UTC time as YYYY-MM-DDTHH:MM:SSZ."""
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _username() -> str:
    """Return the current username, falling back to '?'."""
    try:
        return getpass.getuser()
    except Exception:
        return "?"


def audit_log(action: str, detail: str = "") -> None:
    """Append one audit entry for a mutating operation.

    action: dotted verb, e.g. ``keys.add``, ``gates.enable``, ``agent.delete``.
    detail: human-readable target (an id, key name, tier — never a secret value).

    Best-effort and never raises. No-ops when
    DOCKET_NO_AUDIT=1 or the OPENCLAW_DIR does not exist yet.
    """
    if os.environ.get("DOCKET_NO_AUDIT", "0") == "1":
        return
    logf = _cfg.AUDIT_LOG
    if not logf.parent.is_dir():
        return

    entry: dict[str, Any] = {
        "ts": _utc_now(),
        "user": _username(),
        "pid": os.getpid(),
        "action": action,
        "detail": detail,
    }
    try:
        new = not logf.exists()
        with logf.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        if new:
            os.chmod(logf, 0o600)
    except OSError:
        pass


def read_audit() -> list[dict[str, Any]]:
    """Return every parseable audit entry in file order (oldest first).

    Malformed lines are skipped.
    """
    logf = _cfg.AUDIT_LOG
    if not logf.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = logf.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
