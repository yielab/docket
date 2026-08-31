"""Audit log for mutating operations.

Appends one JSON line per change to ``$DOCKET_HOME/audit.log`` (0600) recording
who/when/what — table stakes for "what changed this agent/binding/key, and when".
Secret VALUES are never logged: callers pass only the key name / action target.

Tamper evidence: every line carries a monotonic ``seq`` and a ``prev_hash``
— the SHA-256 of the previous line's canonical JSON form (stdlib ``hashlib``, no
new dependency). ``verify_chain()`` walks the file and reports the first broken
link. A missing/empty file, or a pre-chain legacy line (no ``seq``/``prev_hash``),
are honest **chain restarts** (seq resets to 1, prev_hash resets to
``GENESIS_HASH``) rather than tampering — callers treat them as "unchained
(legacy)", never as a break.

A size-triggered rotation does NOT restart the chain: the first entry written
after a rotation carries the rotated generation's final ``seq + 1`` and the
SHA-256 of its final entry, so the new file *declares what it continues from*
instead of silently claiming to be a fresh install. ``verify_chain()`` checks
that declaration against the single rotated-backup generation
(``audit.log.1``) it should still be sitting in; a claim that can't be
substantiated there (backup missing, or its tail doesn't match) is reported as
a break, not silently accepted. This makes a deleted or altered backup
generation *evident* — it does not, and cannot, make erasure impossible: an
attacker with full filesystem access can always delete both the current file
and the backup and let the next write start a genuine fresh genesis chain,
indistinguishable from a real fresh install. See
specs/functional/audit.spec.md Requirement 9 for the full state table.

There is no environment kill switch: recording is best-effort (a write failure
never raises) but can no longer be silently switched off — a prior
``DOCKET_NO_AUDIT=1`` escape hatch was an unauthenticated way to disable the
only tamper record docket keeps. See specs/functional/audit.spec.md for the
full rationale and schema.

Exempt from the store.py single-writer rule: appends are line-independent, not
a read-modify-write of a whole document, so this module writes JSONL directly
rather than through ``edges/store.py``. The log is a docket-owned artefact
under DOCKET_HOME, alongside the model/archetype registries and PROJECTS_DIR.
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


def _rotate_if_needed(logf: Path) -> tuple[int, str] | None:
    """Rotate *logf* to a single-generation ``<name>.1`` backup once oversized.

    Best-effort: any OSError is swallowed (matches audit_log's never-fail
    contract) and reported as None, same as "no rotation happened".

    Returns the ``(seq, prev_hash)`` the very next entry should carry to
    honestly continue the rotated generation's chain — exactly what
    ``_chain_head`` would have returned for *logf* had it never been renamed
    away — or ``None`` when either no rotation happened, or the rotated
    generation's last line had nothing chained to continue from (missing/
    empty file, or a legacy line with no ``seq``/``prev_hash``). In both
    ``None`` cases the caller falls back to ``_chain_head(logf)``, which
    correctly reads the (now-absent) current file as a fresh genesis chain —
    unchanged from pre-rotation-continuation behaviour.
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
    """Return the append head, including the only safe post-rotation recovery.

    If a rotation renamed the current file but its following append failed,
    the current path is absent and the retained backup is the authoritative
    tail. The next successful writer resumes from that tail instead of
    inventing a genesis restart/gap.
    """
    if continuation is not None:
        return continuation
    if not logf.exists() and _rotation_marker_path(logf).is_file():
        backup_head = _chain_head(logf.with_suffix(logf.suffix + ".1"))
        if backup_head != (1, GENESIS_HASH):
            return backup_head
    return _chain_head(logf)


def _append_entry(logf: Path, encoded: str) -> bool:
    """Append, flush, close, and permission-restore one entry or roll it back.

    The caller holds the audit lock. A failed append must not leave a partial
    JSON line, and a newly-created post-rotation current file is removed so
    its backup remains the recovery authority.
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
    except OSError:
        # Best effort applies to failure reporting too: preserve the exact
        # pre-transition bytes whenever the filesystem permits it.
        if stream is not None:
            with suppress(OSError):
                stream.seek(original_size)
                stream.truncate(original_size)
                stream.flush()
                os.fsync(stream.fileno())
            with suppress(OSError):
                stream.close()
        elif existed:
            # A close or permission-restoration failure happens after the
            # stream was closed; reopen solely to remove the just-appended
            # bytes before reporting this transition as failed.
            with suppress(OSError), logf.open("r+", encoding="utf-8") as rollback:
                rollback.truncate(original_size)
                rollback.flush()
                os.fsync(rollback.fileno())
        if not existed:
            with suppress(OSError):
                logf.unlink()
        return False


def audit_log(action: str, detail: str = "") -> AuditWriteResult:
    """Append one chained audit entry for a mutating operation.

    action: dotted verb, e.g. ``keys.add``, ``gates.enable``, ``agent.delete``.
    detail: human-readable target (an id, key name, model id — never a secret
    value).

    Best-effort and never raises audit I/O detail: a failed transition returns
    ``AuditWriteResult(status="failed")`` without changing the caller's own
    command result. Existing callers may intentionally ignore the return.
    Recording cannot be disabled by environment variable — there is no kill
    switch (see module docstring).

    AUDIT_LOG lives under DOCKET_HOME, which is genuinely docket-owned but not
    bootstrapped by anything external, so this creates its parent directory
    itself, exactly like every other DOCKET_HOME-derived writer already does
    (``core/trace.py``'s ``project_dir.mkdir(parents=True, exist_ok=True)``,
    ``core/session.py``'s ``_ensure_session_dir``) — the log would otherwise
    silently lose its very first entry on a fresh ``~/.docket``.
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
    """Return every parseable audit entry in file order (oldest first).

    Malformed lines are skipped. Entries from before the tamper-evidence
    chain landed simply lack ``seq``/``prev_hash`` — callers must not assume
    those keys are present.
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
    """Outcome of walking the current audit log's hash chain.

    ``continued_from_seq`` is set only when the current file's first entry
    made — and this walk successfully verified against ``audit.log.1`` — a
    rotation-continuation claim (Requirement 9c): the seq the rotated-away
    generation ended on. ``None`` covers both "no claim was made" (a genuine
    genesis chain, or a chain restart after a legacy tail) and "this file has
    no entries at all" — callers that care about the distinction already have
    ``exists``/``total_lines`` for that.
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
    """Check a first-entry rotation-continuation claim against ``<logf>.1``.

    *claimed_seq*/*claimed_prev_hash* are the current file's first entry's
    own ``seq``/``prev_hash`` — i.e. it claims the rotated-away generation
    ended at ``seq=claimed_seq - 1`` with that hash. Returns ``None`` when
    the backup's last line substantiates the claim, or an explanatory reason
    string (unmatched to a specific line — the caller attaches it to line 1,
    the entry making the claim) when it does not: this is the "erasure"
    case this card exists to surface. Only ever called when the claim is
    structurally plausible (``claimed_seq > 1``, ``claimed_prev_hash !=
    GENESIS_HASH``) — see ``verify_chain``.
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
    """Walk ``$DOCKET_HOME/audit.log`` and verify its tamper-evidence chain.

    Only the *current* file's entries are re-hashed — but its very first
    entry may *claim* to continue a rotated-away generation (Requirement 9c),
    and when it does, that claim is checked against the single rotated
    backup (``audit.log.1``) it should still be sitting in. Three states
    follow from this: a genuine genesis chain (no claim made — a fresh
    install, or a restart after a legacy tail), a claim that the backup
    substantiates (reported clean, with ``continued_from_seq`` set), or a
    claim the backup cannot substantiate — missing, unreadable, or simply not
    a match — which is reported as a break exactly like a hand-tampered
    line, not silently accepted. Legacy lines (written before this chain
    existed, i.e. missing ``seq``/``prev_hash``) are counted separately and
    reset expectations for the next chained line, same as before this card —
    they are never reported as breaks.
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
    """Walk one locked current/backup audit snapshot and verify its chain.

    Readers use the same dedicated lock as writers so a rotation cannot split
    the current file from the backup used to prove its continuation claim.
    A lock/read failure remains non-raising and is indistinguishable from an
    unavailable log to this compatibility-preserving API.
    """
    logf = _cfg.AUDIT_LOG
    if not logf.parent.is_dir():
        return VerifyResult(False, 0, 0, 0, None, False)
    try:
        with _with_audit_lock(logf):
            return _verify_chain_unlocked(logf)
    except (OSError, Timeout):
        return VerifyResult(False, 0, 0, 0, None, False)
