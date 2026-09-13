"""Audit log for mutating operations.
Appends one JSON line per change to ``$DOCKET_HOME/audit.log`` (0600): who/when/what, secret
VALUES never logged. Tamper evidence: each line carries a monotonic ``seq`` and ``prev_hash``
(SHA-256 of the prior line); ``verify_chain()`` reports the first broken link, and a missing/
empty file or pre-chain legacy line is an honest **chain restart**, never tampering. Rotation
does NOT restart the chain: the first entry after it declares what generation it continues,
checked against the single backup (``audit.log.1``); an unsubstantiated claim is a break --
evident, not prevented, since deleting both files together still yields an indistinguishable
fresh genesis (specs/functional/audit.spec.md Requirement 9). Recording is best-effort (never
raises) with no environment kill switch (see that spec). Exempt from the store.py single-writer
rule: appends are line-independent, so this writes JSONL directly, not through ``edges/store.py``.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from filelock import FileLock, Timeout

import docket.config as _cfg

# Sentinel prev_hash for the first entry of a chain (fresh log, or the first
# entry appended after a legacy line / rotation boundary). Deliberately the
# same length as a real SHA-256 hex digest so chain-start entries are
# structurally uniform with every other entry.
GENESIS_HASH = "0" * 64

# Kept private and deliberately independent from edges/store.py's directory
# lock: audit is JSONL, and this one lock protects only its rotate/head/append
# transition. Tests lower it to make a timeout deterministic.
_AUDIT_LOCK_TIMEOUT = 5


@dataclass(frozen=True)
class AuditWriteResult:
    """Observable outcome of one best-effort audit write."""

    status: Literal["written", "failed"]


def _audit_lock_path(logf: Path) -> Path:
    """Return the dedicated inter-process lock for one audit log."""
    return logf.with_name(f".{logf.name}.lock")


def _rotation_marker_path(logf: Path) -> Path:
    """Return the short-lived marker that makes a failed rotation recoverable."""
    return logf.with_name(f".{logf.name}.rotation")


@contextmanager
def _with_audit_lock(logf: Path) -> Iterator[None]:
    """Hold the audit-only lock for a coherent current/backup snapshot."""
    lock = FileLock(str(_audit_lock_path(logf)), timeout=_AUDIT_LOCK_TIMEOUT)
    with lock:
        yield


def _utc_now() -> str:
    """Return current UTC time as ISO ``YYYY-MM-DDTHH:MM:SS.mmmZ``. Millisecond resolution
    because second resolution collided under scripted/rapid-fire use (stdlib-only).
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
    """Deterministic JSON form used for hashing (sorted keys, no whitespace) so the chain is
    robust to incidental reformatting and only breaks on an actual content change.
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
    """Return (next_seq, prev_hash) for the next append: missing/empty file, pre-chain line, or
    corrupt line all restart the chain at seq=1/``GENESIS_HASH`` -- honest, not a defect.
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


def _rotate_if_needed(logf: Path) -> tuple[int, str] | None:
    """Rotate *logf* to the single-generation ``<name>.1`` backup once oversized (see
    specs/functional/audit.spec.md Rotation Requirement 2). Best-effort: OSError is swallowed
    and reported as ``None``, same as "no rotation happened". Returns ``(seq, prev_hash)`` to
    continue the rotated chain, or ``None`` in that case or when the rotated generation had no
    chain to continue -- both collapse to the caller's ``_chain_head(logf)`` fallback, which is
    correct either way.
    """
    try:
        if not (logf.exists() and logf.stat().st_size >= _cfg.AUDIT_LOG_MAX_BYTES):
            return None
        continuation = _chain_head(logf)
        marker = _rotation_marker_path(logf)
        # Persist intent before the rename. If the process dies after the
        # rename and before append, only this marker authorizes recovery from
        # the backup; an unrelated legacy backup must not affect a fresh log.
        marker.write_text("pending\n", encoding="utf-8")
        os.chmod(marker, 0o600)
    except OSError:
        return None
    try:
        os.replace(logf, logf.with_suffix(logf.suffix + ".1"))
    except OSError:
        with suppress(OSError):
            _rotation_marker_path(logf).unlink()
        return None
    return None if continuation == (1, GENESIS_HASH) else continuation


def _recovery_head(logf: Path, continuation: tuple[int, str] | None) -> tuple[int, str]:
    """Return the append head, including post-rotation recovery: if a rename succeeded but the
    append failed, the retained backup is authoritative and the next writer resumes from its tail.
    """
    if continuation is not None:
        return continuation
    if not logf.exists() and _rotation_marker_path(logf).is_file():
        backup_head = _chain_head(logf.with_suffix(logf.suffix + ".1"))
        if backup_head != (1, GENESIS_HASH):
            return backup_head
    return _chain_head(logf)


def _append_entry(logf: Path, encoded: str) -> bool:
    """Append or roll back one entry (caller holds the lock): a failed append leaves no partial
    line, and removes a fresh post-rotation file so the backup stays the recovery authority.
    """
    existed = logf.exists()
    try:
        original_size = logf.stat().st_size if existed else 0
    except OSError:
        return False

    stream: Any | None = None
    try:
        stream = logf.open("a+", encoding="utf-8")
        stream.write(encoded + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        stream = None
        os.chmod(logf, 0o600)
        _rotation_marker_path(logf).unlink(missing_ok=True)
        return True
    except (OSError, ValueError):
        # Best effort applies to failure reporting too: preserve the exact
        # pre-transition bytes whenever the filesystem permits it.
        if stream is not None:
            # A close may fail after closing the underlying descriptor. Do
            # not use this possibly-closed object for rollback; close it best
            # effort, then reopen the durable path below.
            with suppress(OSError, ValueError):
                stream.close()
        if existed:
            # Reopen even when ``stream`` is non-None: a failing close can
            # have closed it already, and only this fresh handle can reliably
            # restore the pre-transition length.
            with suppress(OSError, ValueError), logf.open("r+", encoding="utf-8") as rollback:
                rollback.truncate(original_size)
                rollback.flush()
                os.fsync(rollback.fileno())
        if not existed:
            with suppress(OSError):
                logf.unlink()
        return False


def audit_log(action: str, detail: str = "") -> AuditWriteResult:
    """Append one chained audit entry. *action* is a dotted verb (e.g. ``keys.add``); *detail*
    is a human-readable target, never a secret value. Best-effort, never raises: a failed
    transition returns ``AuditWriteResult(status="failed")`` without changing the caller's own
    result, and recording cannot be disabled (no kill switch -- see module docstring). Creates
    its own parent directory under DOCKET_HOME so a fresh install doesn't silently lose its
    first entry, matching every other DOCKET_HOME-derived writer.
    """
    logf = _cfg.AUDIT_LOG
    try:
        logf.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return AuditWriteResult("failed")

    try:
        with _with_audit_lock(logf):
            continuation = _rotate_if_needed(logf)
            seq, prev_hash = _recovery_head(logf, continuation)
            entry: dict[str, Any] = {
                "seq": seq,
                "ts": _utc_now(),
                "user": _username(),
                "pid": os.getpid(),
                "action": action,
                "detail": detail,
                "prev_hash": prev_hash,
            }
            if _append_entry(logf, json.dumps(entry)):
                return AuditWriteResult("written")
    except (OSError, Timeout):
        pass
    return AuditWriteResult("failed")


def _read_audit_text_unlocked(logf: Path) -> str | None:
    if not logf.is_file():
        return None
    try:
        return logf.read_text(encoding="utf-8")
    except OSError:
        return None


def read_audit_text() -> str | None:
    """Return a locked, exact current-log snapshot for the raw CLI view."""
    logf = _cfg.AUDIT_LOG
    if not logf.parent.is_dir():
        return None
    try:
        with _with_audit_lock(logf):
            return _read_audit_text_unlocked(logf)
    except (OSError, Timeout):
        return None


def read_audit() -> list[dict[str, Any]]:
    """Return every parseable audit entry, oldest first; malformed lines are skipped. Entries
    predating the tamper-evidence chain lack ``seq``/``prev_hash`` -- callers must not assume so.
    """
    text = read_audit_text()
    if text is None:
        return []
    out: list[dict[str, Any]] = []
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
    """``continued_from_seq`` is set only for a substantiated rotation-continuation claim (see
    specs/functional/audit.spec.md Requirement 9); ``None`` means no claim, or no entries at all.
    """

    exists: bool
    total_lines: int
    chained: int
    legacy: int
    break_at: ChainBreak | None
    rotated_backup: bool
    continued_from_seq: int | None = None


def _verify_rotation_continuation(
    logf: Path, claimed_seq: int, claimed_prev_hash: str
) -> str | None:
    """Check a first-entry rotation-continuation claim (*claimed_seq*/*claimed_prev_hash*, the
    entry's own values, claiming the rotated-away generation ended at ``seq - 1`` with that
    hash) against ``<logf>.1`` -- the "continued, unverifiable" erasure case of
    specs/functional/audit.spec.md Requirement 9. Returns ``None`` if substantiated, else a
    reason string. Only called when the claim is structurally plausible (``claimed_seq > 1``,
    not ``GENESIS_HASH``) -- see ``verify_chain``.
    """
    backup = logf.with_suffix(logf.suffix + ".1")
    claimed_from = claimed_seq - 1
    line = _last_line(backup)
    if line is None:
        return (
            f"chain claims continuation from seq={claimed_from}, but "
            f"{backup.name} is missing — earlier history may have been deleted"
        )
    try:
        backup_entry: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        return (
            f"chain claims continuation from seq={claimed_from}, but "
            f"{backup.name}'s last line is not valid JSON — predecessor cannot "
            "be verified"
        )
    try:
        backup_seq = int(backup_entry.get("seq", -1))
    except (TypeError, ValueError):
        backup_seq = -1
    if backup_seq != claimed_from or _hash_entry(backup_entry) != claimed_prev_hash:
        return (
            f"chain claims continuation from seq={claimed_from}, but "
            f"{backup.name} does not match — the predecessor generation was "
            "altered or replaced"
        )
    return None


def _verify_chain_unlocked(logf: Path) -> VerifyResult:
    """Walk ``$DOCKET_HOME/audit.log`` and verify its tamper-evidence chain. Only the *current*
    file's entries are re-hashed, but its first entry may *claim* to continue a rotated-away
    generation, checked against ``audit.log.1``; the three resulting states (genesis /
    continued-verified / continued-unverifiable) are specs/functional/audit.spec.md
    Requirement 9. Legacy lines (missing ``seq``/``prev_hash``) are counted separately, reset
    expectations for the next chained line, and are never reported as breaks.
    """
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
    continued_from_seq: int | None = None

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
                continued_from_seq,
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
                continued_from_seq,
            )
        prev_hash = str(entry.get("prev_hash", ""))

        if expected_seq is None:
            is_chain_start = i == 1
            if seq == 1 and prev_hash == GENESIS_HASH:
                pass  # genuine genesis chain (or a restart after a legacy tail)
            elif is_chain_start and seq > 1 and prev_hash != GENESIS_HASH:
                # Only the file's very first entry can legitimately claim a
                # rotation continuation -- a restart after a mid-file legacy
                # line never can, since audit_log() never produces one there.
                gap = _verify_rotation_continuation(logf, seq, prev_hash)
                if gap is not None:
                    return VerifyResult(
                        True,
                        len(lines),
                        chained,
                        legacy,
                        ChainBreak(i, gap),
                        rotated,
                        continued_from_seq,
                    )
                continued_from_seq = seq - 1
            elif seq != 1:
                return VerifyResult(
                    True,
                    len(lines),
                    chained,
                    legacy,
                    ChainBreak(i, f"expected chain restart at seq=1, found seq={seq}"),
                    rotated,
                    continued_from_seq,
                )
            else:
                return VerifyResult(
                    True,
                    len(lines),
                    chained,
                    legacy,
                    ChainBreak(i, "expected GENESIS prev_hash at chain start"),
                    rotated,
                    continued_from_seq,
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
                    continued_from_seq,
                )
            if prev_hash != expected_prev:
                return VerifyResult(
                    True,
                    len(lines),
                    chained,
                    legacy,
                    ChainBreak(i, "prev_hash mismatch — an earlier line was altered or removed"),
                    rotated,
                    continued_from_seq,
                )

        chained += 1
        expected_seq = seq + 1
        expected_prev = _hash_entry(entry)

    return VerifyResult(True, len(lines), chained, legacy, None, rotated, continued_from_seq)


def verify_chain() -> VerifyResult:
    """Walk one locked snapshot; readers share the writer's lock so rotation can't split the
    file from the backup proving its claim; failure is non-raising, same as an unavailable log.
    """
    logf = _cfg.AUDIT_LOG
    if not logf.parent.is_dir():
        return VerifyResult(False, 0, 0, 0, None, False)
    try:
        with _with_audit_lock(logf):
            return _verify_chain_unlocked(logf)
    except (OSError, Timeout):
        return VerifyResult(False, 0, 0, 0, None, False)
