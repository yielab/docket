"""Pod memory — what a pod learns about its repository, kept in one governed file.

A step's reply may end with a ``## Memory`` section; when the task ends, ``record_task_memory``
parses it and decides every entry itself: only a fact docket verified (a generated path present
at the task's commit, a command with an exit status in the task's trace) is accepted
automatically, anything that reads as an instruction is refused, and the rest waits for the
operator. Accepted entries reach later prompts through ``render_entries`` behind an untrusted
frame (``teams/identity.py``). See specs/functional/workspace-structure.spec.md "Pod memory"."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.governance.audit import audit_log
from docket.kernel import clock as _clock
from docket.kernel.errors import Conflict
from docket.kernel.home import current_home
from docket.observability import trace as _trace
from docket.platform import read_json, read_modify_write
from docket.teams.memory_decide import HopLike, TaskLike, _decide, _task_facts
from docket.teams.memory_parse import KINDS, _safe_path, parse_memory_section


class PodMemoryError(Conflict):
    """An operator action named no such entry, or one in the wrong state."""


@dataclass(frozen=True)
class MemoryEntry:
    """One stored entry; ``subject`` is a path or, for a ``command``, the command."""

    id: str
    kind: str
    subject: str
    note: str
    status: str
    reason: str
    provenance: dict[str, str]
    exit: int | None = None

    def to_dict(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "command" if self.kind == "command" else "path": self.subject,
            "note": self.note,
            "status": self.status,
            "reason": self.reason,
            "provenance": self.provenance,
        }
        if self.exit is not None:
            doc["exit"] = self.exit
        return doc


def _entry_from_dict(doc: Any) -> MemoryEntry | None:
    if not isinstance(doc, dict):
        return None
    kind, status = doc.get("kind"), doc.get("status")
    subject = doc.get("command") if kind == "command" else doc.get("path")
    if kind not in KINDS or status not in ("accepted", "pending", "refused"):
        return None
    if not isinstance(subject, str) or not isinstance(doc.get("id"), str):
        return None
    prov = doc.get("provenance")
    exit_code = doc.get("exit")
    return MemoryEntry(
        id=doc["id"],
        kind=kind,
        subject=subject,
        note=str(doc.get("note", "")),
        status=status,
        reason=str(doc.get("reason", "")),
        provenance={str(k): str(v) for k, v in prov.items()} if isinstance(prov, dict) else {},
        exit=exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None,
    )


def entry_id(kind: str, subject: str) -> str:
    """The deduplication key as an id: stable for one ``(kind, subject)``."""
    return "mem-" + hashlib.sha256(f"{kind}\0{subject}".encode()).hexdigest()[:10]


# -- the store -------------------------------------------------------------------


def _load(doc: dict[str, Any]) -> list[MemoryEntry]:
    raw = doc.get("entries")
    items = raw if isinstance(raw, list) else []
    return [e for e in (_entry_from_dict(d) for d in items) if e is not None]


def _trim(entries: list[MemoryEntry]) -> list[MemoryEntry]:
    """Apply the two caps, oldest first: accepted apart from pending and refused."""
    accepted = [e for e in entries if e.status == "accepted"]
    undecided = [e for e in entries if e.status != "accepted"]
    drop = {
        e.id for e in accepted[: max(0, len(accepted) - current_home().pod_memory_max_accepted)]
    }
    drop |= {
        e.id for e in undecided[: max(0, len(undecided) - current_home().pod_memory_max_undecided)]
    }
    return [e for e in entries if e.id not in drop]


def _write(entries: list[MemoryEntry]) -> dict[str, Any]:
    return {"entries": [e.to_dict() for e in _trim(entries)]}


def list_entries(project: str, status: str | None = None) -> list[MemoryEntry]:
    """The pod's entries, oldest first, optionally only those with *status*."""
    entries = _load(read_json(current_home().pod_memory_path(project)))
    return [e for e in entries if status is None or e.status == status]


def _announce(project: str, action: str, entry: MemoryEntry, task: str, actor: str) -> None:
    payload = {
        "action": action,
        "entry": entry.id,
        "kind": entry.kind,
        "status": entry.status,
        "reason": entry.reason,
        "task": task,
    }
    session = f"agent:{project}:{task or 'memory'}"
    _trace.trace_event(project, session, "lead", "memory_update", json.dumps(payload), task_id=task)
    detail = f"{project} entry={entry.id} kind={entry.kind} status={entry.status} actor={actor}"
    audit_log(f"pod.memory.{action}", detail + (f" task={task}" if task else ""))


def record_task_memory(
    project: str, task_id: str, result: TaskLike, *, root: str | None = None
) -> list[MemoryEntry]:
    """Decide and store the memory section of every ok hop of a finished task; returns the entries
    added or replaced. *root* is the repository holding the task's commit (default: the pod's
    codebase). A failure is audited, never raised: memory must not unwind a finalized task."""
    try:
        return _record_task_memory(project, task_id, result, root)
    except Exception as exc:
        audit_log("pod.memory.error", f"{project} task={task_id} {type(exc).__name__}")
        return []


def _record_task_memory(
    project: str, task_id: str, result: TaskLike, root: str | None
) -> list[MemoryEntry]:
    hops: list[HopLike] = [h for h in result.hops if h.ok]
    wanted = [(h, ln) for h in hops for ln in parse_memory_section(h.output)]
    if not wanted:
        return []
    facts = _task_facts(project, hops, root)
    today = _clock.today().isoformat()
    changes: list[MemoryEntry] = []
    for hop, line in wanted:
        if line.refusal:
            _trace.trace_event(
                project,
                f"agent:{project}:{task_id}",
                "lead",
                "memory_update",
                json.dumps(
                    {
                        "action": "refused",
                        "status": "refused",
                        "reason": line.refusal,
                        "task": task_id,
                    }
                ),
                task_id=task_id,
            )
            continue
        subject, status, reason, code = _decide(line, facts, hop.role)
        changes.append(
            MemoryEntry(
                id=entry_id(line.kind, subject),
                kind=line.kind,
                subject=subject,
                note=line.note[: current_home().pod_memory_note_max_chars],
                status=status,
                reason=reason,
                provenance={"task": task_id, "date": today, "commit": facts.commit},
                exit=code,
            )
        )
    applied: list[MemoryEntry] = []

    def _merge(doc: dict[str, Any]) -> dict[str, Any] | None:
        entries = _load(doc)
        applied.clear()
        for new in changes:
            old = next((e for e in entries if e.id == new.id), None)
            if old is not None and not (old.status == "pending" and new.status == "accepted"):
                continue
            entries = [e for e in entries if e.id != new.id] + [new]
            applied.append(new)
        return _write(entries) if applied else None

    read_modify_write(current_home().pod_memory_path(project), _merge)
    for entry in applied:
        _announce(project, entry.status, entry, task_id, "docket")
    return applied


def _decide_entry(
    project: str,
    entry_id_: str,
    allowed: str,
    make: Callable[[MemoryEntry], MemoryEntry],
    action: str,
    actor: str,
) -> MemoryEntry:
    decided: list[MemoryEntry] = []

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        entries = _load(doc)
        old = next((e for e in entries if e.id == entry_id_), None)
        if old is None:
            raise PodMemoryError(f"no memory entry '{entry_id_}'")
        if old.status != allowed:
            raise PodMemoryError(f"entry '{entry_id_}' is {old.status}, not {allowed}")
        new = make(old)
        decided.append(new)
        return _write([new if e.id == entry_id_ else e for e in entries])

    read_modify_write(current_home().pod_memory_path(project), _fn)
    _announce(project, action, decided[0], decided[0].provenance.get("task", ""), actor)
    return decided[0]


def _with(entry: MemoryEntry, status: str, reason: str) -> MemoryEntry:
    return MemoryEntry(
        entry.id,
        entry.kind,
        entry.subject,
        entry.note,
        status,
        reason,
        entry.provenance,
        entry.exit,
    )


def approve(project: str, entry_id_: str, *, actor: str = "operator") -> MemoryEntry:
    """Accept a pending entry."""
    return _decide_entry(
        project,
        entry_id_,
        "pending",
        lambda e: _with(e, "accepted", "approved by the operator"),
        "approved",
        actor,
    )


def refuse(project: str, entry_id_: str, reason: str, *, actor: str = "operator") -> MemoryEntry:
    """Refuse a pending entry; the same fact is not stored again."""
    why = reason.strip()[:200] or "refused by the operator"
    return _decide_entry(
        project, entry_id_, "pending", lambda e: _with(e, "refused", why), "refused", actor
    )


def revert(project: str, entry_id_: str, *, actor: str = "operator") -> MemoryEntry:
    """Take an accepted entry out of every prompt; it stays as a refusal so it is not re-added."""
    return _decide_entry(
        project,
        entry_id_,
        "accepted",
        lambda e: _with(e, "refused", "reverted by the operator"),
        "reverted",
        actor,
    )


def reset(project: str, *, actor: str = "operator") -> int:
    """Remove every entry of the pod; returns how many there were."""
    removed: list[MemoryEntry] = []

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        removed.extend(_load(doc))
        return {"entries": []} if removed else None

    read_modify_write(current_home().pod_memory_path(project), _fn)
    if removed:
        audit_log("pod.memory.reset", f"{project} entries={len(removed)} actor={actor}")
        _trace.trace_event(
            project,
            f"agent:{project}:memory",
            "lead",
            "memory_update",
            json.dumps(
                {"action": "reset", "status": "", "reason": "", "task": "", "count": len(removed)}
            ),
        )
    return len(removed)


# -- what the next task reads ----------------------------------------------------


def _line(entry: MemoryEntry) -> str:
    if entry.kind == "command":
        status = f" (exit {entry.exit})" if entry.exit is not None else ""
        return f"- command `{entry.subject}`{status}: {entry.note}"
    return f"- {entry.kind} {entry.subject}: {entry.note}"


def render_entries(project: str, root: Path | None, max_bytes: int) -> str:
    """The accepted entries as bullet lines, oldest first, fitted to *max_bytes* by dropping the
    oldest whole entries. An entry whose path no longer exists under *root* is left out (it is
    not deleted). ``""`` when nothing accepted fits."""
    lines: list[str] = []
    for entry in list_entries(project, "accepted"):
        if entry.kind != "command":
            rel = _safe_path(entry.subject)
            if not rel or (root is not None and not os.path.lexists(os.path.join(root, rel))):
                continue
        lines.append(_line(entry))
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        cost = len(line.encode("utf-8")) + (1 if kept else 0)
        if used + cost > max_bytes:
            break
        kept.append(line)
        used += cost
    return "\n".join(reversed(kept))
