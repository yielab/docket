"""Audit log for mutating operations.

Appends one JSON line per change to ``$DOCKET_HOME/audit.log`` (0600) recording
who/when/what — table stakes for "what changed this agent/binding/key, and when".
Secret VALUES are never logged: callers pass only the key name / action target.

Tamper evidence (G-4): every line carries a monotonic ``seq`` and a ``prev_hash``
— the SHA-256 of the previous line's canonical JSON form (stdlib ``hashlib``, no
new dependency). ``verify_chain()`` walks the file and reports the first broken
link. A missing/empty file, a pre-chain legacy line (no ``seq``/``prev_hash``),
or the first entry after a size-triggered rotation are honest **chain restarts**
(seq resets to 1, prev_hash resets to ``GENESIS_HASH``) rather than tampering —
callers treat them as "unchained (legacy)", never as a break.

There is no environment kill switch: recording is best-effort (a write failure
never raises, matching the pre-G-4 contract) but can no longer be silently
switched off — a prior ``DOCKET_NO_AUDIT=1`` escape hatch was an unauthenticated
way to disable the only tamper record docket keeps. See
specs/functional/audit.spec.md for the full rationale and schema.

Exempt from the store.py single-writer rule (D-12, ROADMAP §6): appends are
line-independent, not a read-modify-write of a whole document, so this module
writes JSONL directly rather than through ``edges/store.py``. The log is a
docket-owned artefact under DOCKET_HOME (Phase 19 P19-7a moved it there
alongside the model/archetype registries and PROJECTS_DIR; Phase 19 P19-7b
then deleted the daemon's directory it used to live under).
"""

from __future__ import annotations

import datetime as _dt
import getpass
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docket.config as _cfg

# Sentinel prev_hash for the first entry of a chain (fresh log, or the first
# entry appended after a legacy line / rotation boundary). Deliberately the
# same length as a real SHA-256 hex digest so chain-start entries are
# structurally uniform with every other entry.
GENESIS_HASH = "0" * 64


def _utc_now() -> str:
    """Return current UTC time as YYYY-MM-DDTHH:MM:SS.mmmZ (millisecond resolution).

    Second resolution collided under scripted/rapid-fire use; ms is cheap and
    stdlib-only (``datetime.microsecond``).
    """
    now = _dt.datetime.now(_dt.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"


def _username() -> str:
    """Return the current username, falling back to '?'."""
    try:
        return getpass.getuser()
    except Exception:
        return "?"


def _canonical(entry: dict[str, Any]) -> str:
    """Deterministic JSON form used for hashing (sorted keys, no whitespace).

    Hashing the re-serialised, sorted form (rather than the exact on-disk
    bytes) means the chain is robust to incidental reformatting and only
    breaks on an actual content change — the property we want tamper
    evidence to catch.
    """
    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


def _hash_entry(entry: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(entry).encode("utf-8")).hexdigest()


def _last_line(logf: Path) -> str | None:
    """Return the last non-blank line of *logf*, or None if empty/missing."""
    try:
        text = logf.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line:
            return line
    return None


def _chain_head(logf: Path) -> tuple[int, str]:
    """Return (next_seq, prev_hash) for the next entry appended to *logf*.

    A missing/empty file, a last line that predates the chain (no ``seq``/
    ``prev_hash``), or a corrupt last line all start a fresh chain at seq=1
    with ``GENESIS_HASH`` — an honest restart boundary, not a defect.
    """
    line = _last_line(logf)
    if line is None:
        return 1, GENESIS_HASH
    try:
        last: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        return 1, GENESIS_HASH
    if "seq" not in last or "prev_hash" not in last:
        return 1, GENESIS_HASH
    try:
        seq = int(last["seq"])
    except (TypeError, ValueError):
        return 1, GENESIS_HASH
    return seq + 1, _hash_entry(last)


def _rotate_if_needed(logf: Path) -> None:
    """Rotate *logf* to a single-generation ``<name>.1`` backup once oversized.

    Best-effort: any OSError is swallowed (matches audit_log's never-fail
    contract). The new current file starts a fresh chain (see _chain_head).
    """
    try:
        if logf.exists() and logf.stat().st_size >= _cfg.AUDIT_LOG_MAX_BYTES:
            backup = logf.with_suffix(logf.suffix + ".1")
            os.replace(logf, backup)
    except OSError:
        pass


def audit_log(action: str, detail: str = "") -> None:
    """Append one chained audit entry for a mutating operation.

    action: dotted verb, e.g. ``keys.add``, ``gates.enable``, ``agent.delete``.
    detail: human-readable target (an id, key name, model id — never a secret
    value).

    Best-effort and never raises: a write failure silently no-ops. Recording
    cannot be disabled by environment variable — there is no kill switch (see
    module docstring).

    Phase 19 P19-7a: AUDIT_LOG moved from the daemon's own directory
    (guaranteed to exist by something outside docket's control, before that
    directory was deleted outright in P19-7b) to DOCKET_HOME (genuinely
    docket-owned). Nothing external bootstraps
    DOCKET_HOME anymore, so this creates its parent directory itself, exactly
    like every other DOCKET_HOME-derived writer already does
    (``core/trace.py``'s ``project_dir.mkdir(parents=True, exist_ok=True)``,
    ``core/session.py``'s ``_ensure_session_dir``) — the log would otherwise
    silently lose its very first entry on a fresh ``~/.docket``.
    """
    logf = _cfg.AUDIT_LOG
    try:
        logf.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    try:
        _rotate_if_needed(logf)
        seq, prev_hash = _chain_head(logf)
        entry: dict[str, Any] = {
            "seq": seq,
            "ts": _utc_now(),
            "user": _username(),
            "pid": os.getpid(),
            "action": action,
            "detail": detail,
            "prev_hash": prev_hash,
        }
        new = not logf.exists()
        with logf.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        if new:
            os.chmod(logf, 0o600)
    except OSError:
        pass


def read_audit() -> list[dict[str, Any]]:
    """Return every parseable audit entry in file order (oldest first).

    Malformed lines are skipped. Entries from before the tamper-evidence
    chain landed simply lack ``seq``/``prev_hash`` — callers must not assume
    those keys are present.
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


@dataclass(frozen=True)
class ChainBreak:
    """The first detected tamper-evidence failure, and where it was found."""

    line: int
    reason: str


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of walking the current audit log's hash chain."""

    exists: bool
    total_lines: int
    chained: int
    legacy: int
    break_at: ChainBreak | None
    rotated_backup: bool


def verify_chain() -> VerifyResult:
    """Walk ``$DOCKET_HOME/audit.log`` and verify its tamper-evidence chain.

    Only the *current* file is checked — a rotation starts a fresh chain, so
    there is nothing to bridge across the boundary (``rotated_backup`` tells
    the caller a backup exists so it can say so explicitly). Legacy lines
    (written before this chain existed, i.e. missing ``seq``/``prev_hash``)
    are counted separately and reset expectations for the next chained line,
    exactly like a rotation boundary — they are never reported as breaks.
    """
    logf = _cfg.AUDIT_LOG
    rotated = logf.with_suffix(logf.suffix + ".1").exists()

    if not logf.is_file():
        return VerifyResult(False, 0, 0, 0, None, rotated)

    try:
        text = logf.read_text(encoding="utf-8")
    except OSError:
        return VerifyResult(False, 0, 0, 0, None, rotated)

    lines = [ln for ln in text.splitlines() if ln.strip()]
    chained = 0
    legacy = 0
    expected_seq: int | None = None
    expected_prev: str | None = None

    for i, raw in enumerate(lines, start=1):
        try:
            entry: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            return VerifyResult(
                True,
                len(lines),
                chained,
                legacy,
                ChainBreak(i, "malformed JSON line, cannot verify"),
                rotated,
            )

        if "seq" not in entry or "prev_hash" not in entry:
            legacy += 1
            expected_seq = None
            expected_prev = None
            continue

        try:
            seq = int(entry["seq"])
        except (TypeError, ValueError):
            return VerifyResult(
                True,
                len(lines),
                chained,
                legacy,
                ChainBreak(i, "non-integer seq, cannot verify"),
                rotated,
            )
        prev_hash = str(entry.get("prev_hash", ""))

        if expected_seq is None:
            if seq != 1:
                return VerifyResult(
                    True,
                    len(lines),
                    chained,
                    legacy,
                    ChainBreak(i, f"expected chain restart at seq=1, found seq={seq}"),
                    rotated,
                )
            if prev_hash != GENESIS_HASH:
                return VerifyResult(
                    True,
                    len(lines),
                    chained,
                    legacy,
                    ChainBreak(i, "expected GENESIS prev_hash at chain start"),
                    rotated,
                )
        else:
            if seq != expected_seq:
                return VerifyResult(
                    True,
                    len(lines),
                    chained,
                    legacy,
                    ChainBreak(i, f"seq out of order (expected {expected_seq}, found {seq})"),
                    rotated,
                )
            if prev_hash != expected_prev:
                return VerifyResult(
                    True,
                    len(lines),
                    chained,
                    legacy,
                    ChainBreak(i, "prev_hash mismatch — an earlier line was altered or removed"),
                    rotated,
                )

        chained += 1
        expected_seq = seq + 1
        expected_prev = _hash_entry(entry)

    return VerifyResult(True, len(lines), chained, legacy, None, rotated)
