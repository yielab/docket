"""Pod memory — what a pod learns about its repository, kept in one governed file.

A step's reply may end with a ``## Memory`` section; when the task ends, ``record_task_memory``
parses it and decides every entry itself: only a fact docket verified (a generated path present
at the task's commit, a tool call with an exit status in the task's trace) is accepted
automatically, anything that reads as an instruction is refused, and the rest waits for the
operator. Accepted entries reach later prompts through ``render_entries`` behind an untrusted
frame (``teams/identity.py``). See specs/functional/workspace-structure.spec.md "Pod memory"."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docket.governance.audit import audit_log
from docket.kernel import clock as _clock
from docket.kernel.errors import Conflict
from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.kernel.text import one_line
from docket.observability import trace as _trace
from docket.platform import read_json, read_modify_write
from docket.teams.memory_decide import HopLike, TaskLike, _decide, _task_facts, _TaskFacts
from docket.teams.memory_parse import KINDS, _safe_path, parse_memory_section


class PodMemoryError(Conflict):
    """An operator action named no such entry, or one in the wrong state."""


@dataclass(frozen=True)
class MemoryEntry:
    """One stored entry; ``subject`` is a path, a label or, for a ``tool``, the invocation, and
    ``evidence`` is ``{"exit": n}``, ``{"ok": bool}`` or empty."""

    id: str
    kind: str
    subject: str
    note: str
    status: str
    reason: str
    provenance: dict[str, str]
    stale: bool = False
    evidence: dict[str, int | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "subject": self.subject,
            "note": self.note,
            "status": self.status,
            "reason": self.reason,
            "provenance": self.provenance,
            "stale": self.stale,
            "evidence": self.evidence,
        }


def _evidence_from(raw: Any) -> dict[str, int | bool]:
    if not isinstance(raw, dict):
        return {}
    code, ok = raw.get("exit"), raw.get("ok")
    if isinstance(code, int) and not isinstance(code, bool):
        return {"exit": code}
    return {"ok": ok} if isinstance(ok, bool) else {}


def _entry_from_dict(doc: Any) -> MemoryEntry | None:
    if not isinstance(doc, dict):
        return None
    kind, status, subject = doc.get("kind"), doc.get("status"), doc.get("subject")
    if kind not in KINDS or status not in ("accepted", "pending", "refused"):
        return None
    if not isinstance(subject, str) or not isinstance(doc.get("id"), str):
        return None
    prov = doc.get("provenance")
    return MemoryEntry(
        id=doc["id"],
        kind=kind,
        subject=subject,
        note=str(doc.get("note", "")),
        status=status,
        reason=str(doc.get("reason", "")),
        provenance={str(k): str(v) for k, v in prov.items()} if isinstance(prov, dict) else {},
        stale=doc.get("stale") is True,
        evidence=_evidence_from(doc.get("evidence")),
    )


def entry_id(kind: str, subject: str, note: str) -> str:
    """The deduplication key as an id: stable for one ``(kind, subject, note)``, the note
    casefolded with its whitespace collapsed."""
    fact = one_line(note.casefold())
    return "mem-" + hashlib.sha256(f"{kind}\0{subject}\0{fact}".encode()).hexdigest()[:10]


# -- the store -------------------------------------------------------------------


def _load(doc: dict[str, Any]) -> list[MemoryEntry]:
    raw = doc.get("entries")
    items = raw if isinstance(raw, list) else []
    return [e for e in (_entry_from_dict(d) for d in items) if e is not None]


def _trim(entries: list[MemoryEntry]) -> list[MemoryEntry]:
    """Apply the two caps: over the accepted cap a stale entry goes first, then the oldest
    accepted; over the other, a refused entry goes first, then the oldest pending. Oldest first
    within each."""
    home = current_home()
    accepted = [e for e in entries if e.status == "accepted"]
    undecided = [e for e in entries if e.status != "accepted"]
    by_value = sorted(accepted, key=lambda e: not e.stale)
    by_weight = sorted(undecided, key=lambda e: e.status != "refused")
    drop = {e.id for e in by_value[: max(0, len(accepted) - home.pod_memory_max_accepted)]}
    drop |= {e.id for e in by_weight[: max(0, len(undecided) - home.pod_memory_max_undecided)]}
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
    live = [e for e in list_entries(project, "accepted") if e.kind == "generated"]
    if not wanted and not live:
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
        subject, status, reason, evidence = _decide(line, facts, hop.role)
        note = line.note[: current_home().pod_memory_note_max_chars]
        changes.append(
            MemoryEntry(
                id=entry_id(line.kind, subject, note),
                kind=line.kind,
                subject=subject,
                note=note,
                status=status,
                reason=reason,
                provenance={"task": task_id, "date": today, **facts.anchor},
                evidence=evidence or {},
            )
        )
    applied: list[MemoryEntry] = []
    flipped: list[tuple[str, MemoryEntry]] = []

    def _merge(doc: dict[str, Any]) -> dict[str, Any] | None:
        entries = _load(doc)
        applied.clear()
        flipped.clear()
        entries = _recheck(entries, facts, flipped)
        for new in changes:
            old = next((e for e in entries if e.id == new.id), None)
            if old is not None and not (old.status == "pending" and new.status == "accepted"):
                continue
            entries = [e for e in entries if e.id != new.id] + [new]
            applied.append(new)
        return _write(entries) if applied or flipped else None

    read_modify_write(current_home().pod_memory_path(project), _merge)
    for action, entry in flipped:
        _announce(project, action, entry, task_id, "docket")
    for entry in applied:
        _announce(project, entry.status, entry, task_id, "docket")
    return applied


def _still_there(facts: _TaskFacts, subject: str) -> bool | None:
    """Whether *subject* is present at the task's commit, else under its root; ``None`` when
    neither is known."""
    if not facts.root:
        return None
    if facts.commit:
        return _git.git_path_exists_at(facts.root, facts.commit, subject)
    rel = _safe_path(subject)
    return os.path.lexists(os.path.join(facts.root, rel)) if rel else None


def _recheck(
    entries: list[MemoryEntry], facts: _TaskFacts, flipped: list[tuple[str, MemoryEntry]]
) -> list[MemoryEntry]:
    """*entries* with ``stale`` flipped on every accepted ``generated`` one whose path is gone
    (or back); each flip is added to *flipped* as ``(action, entry)``."""
    out: list[MemoryEntry] = []
    for entry in entries:
        present = (
            _still_there(facts, entry.subject)
            if entry.kind == "generated" and entry.status == "accepted"
            else None
        )
        if present is not None and present == entry.stale:
            entry = dataclasses.replace(entry, stale=not present)
            flipped.append(("fresh" if present else "stale", entry))
        out.append(entry)
    return out


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
    return dataclasses.replace(entry, status=status, reason=reason)


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
    if entry.kind == "tool":
        evidence = entry.evidence
        shown = (
            f"exit {evidence['exit']}"
            if "exit" in evidence
            else "ok"
            if evidence.get("ok") is True
            else "error"
            if "ok" in evidence
            else ""
        )
        return f"- tool `{entry.subject}`{f' ({shown})' if shown else ''}: {entry.note}"
    return f"- {entry.kind} {entry.subject}: {entry.note}"


def render_entries(project: str, root: Path | None, max_bytes: int) -> str:
    """The accepted entries as bullet lines, oldest first, fitted to *max_bytes* by dropping the
    oldest whole entries. A stale entry, or one whose path no longer exists under *root*, is left
    out (it is not deleted). ``""`` when nothing accepted fits."""
    lines: list[str] = []
    for entry in list_entries(project, "accepted"):
        if entry.stale:
            continue
        if entry.kind == "generated":
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
