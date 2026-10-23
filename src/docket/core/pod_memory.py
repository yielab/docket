"""Pod memory — what a pod learns about its repository, kept in one governed file.

A step's reply may end with a ``## Memory`` section; when the task ends, ``record_task_memory``
parses it and decides every entry itself: only a fact docket verified (a generated path present
at the task's commit, a command with an exit status in the task's trace) is accepted
automatically, anything that reads as an instruction is refused, and the rest waits for the
operator. Accepted entries reach later prompts through ``render_entries`` behind an untrusted
frame (``core/identity.py``). See specs/functional/workspace-structure.spec.md "Pod memory"."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import docket.config as _cfg
from docket.core import fleet as _fleet
from docket.core import pod as _pod
from docket.core import policy as _policy
from docket.core import trace as _trace
from docket.core.audit import audit_log
from docket.edges import store as _store
from docket.edges.adapters import system as _sys
from docket.kernel import clock as _clock
from docket.kernel.errors import Conflict

KINDS: tuple[str, ...] = ("generated", "command", "pitfall", "convention")
MEMORY_HEADING = "## Memory"

_BULLET = re.compile(r"^-\s+([A-Za-z]+):\s+(.+?)\s+--\s+(.+?)\s*$")
_URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
_INSTRUCTION_PHRASES = re.compile(
    r"\b(ignore|disregard|override|forget|always|never|must|should|you|your|instructions?)\b"
    r"|\bdo not\b|\bdon'?t\b|\bfrom now on\b|\bsystem prompt\b",
    re.IGNORECASE,
)
_IMPERATIVE_FIRST_WORDS = frozenset(
    [
        "run",
        "use",
        "call",
        "execute",
        "delete",
        "remove",
        "write",
        "read",
        "send",
        "fetch",
        "download",
        "install",
        "push",
        "pull",
        "curl",
        "wget",
        "ignore",
        "disregard",
        "override",
        "always",
        "never",
        "do",
        "don't",
        "dont",
        "make",
        "ensure",
        "change",
        "edit",
        "open",
        "skip",
        "avoid",
        "prefer",
        "apply",
        "create",
        "rename",
        "replace",
        "enable",
        "disable",
        "allow",
        "approve",
        "grant",
        "reveal",
        "print",
        "tell",
        "paste",
        "follow",
        "obey",
        "treat",
        "assume",
        "pretend",
        "forget",
        "remember",
        "try",
        "merge",
        "commit",
        "add",
        "fix",
        "keep",
        "put",
        "take",
        "look",
        "go",
        "be",
        "let",
    ]
)


class PodMemoryError(Conflict):
    """An operator action named no such entry, or one in the wrong state."""


@dataclass(frozen=True)
class ParsedLine:
    """One bullet of a reply's memory section; ``refusal`` is set when it fits no entry."""

    kind: str
    subject: str
    note: str
    refusal: str = ""


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


# -- the reply's memory section --------------------------------------------------


def parse_memory_section(text: str) -> list[ParsedLine]:
    """The entries of *text*'s trailing ``## Memory`` section (the last such heading wins; it
    ends at the next heading). Prose lines are ignored, a bullet outside the grammar or naming
    another kind is returned with a ``refusal``; at most ``POD_MEMORY_MAX_PER_TASK`` come back."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip().lower() == MEMORY_HEADING.lower()]
    if not starts:
        return []
    parsed: list[ParsedLine] = []
    for raw in lines[starts[-1] + 1 :]:
        line = raw.strip()
        if line.startswith("#"):
            break
        if not line.startswith("- "):
            continue
        if len(parsed) >= _cfg.POD_MEMORY_MAX_PER_TASK:
            break
        match = _BULLET.match(line)
        if match is None:
            parsed.append(
                ParsedLine("", "", line[:80], "not of the form '- <kind>: <subject> -- <note>'")
            )
            continue
        kind = match.group(1).lower()
        subject = match.group(2).strip().strip("`").strip()
        if kind not in KINDS:
            parsed.append(ParsedLine(kind, subject, match.group(3), f"unknown kind '{kind[:20]}'"))
            continue
        parsed.append(ParsedLine(kind, subject, match.group(3).strip()))
    return parsed


# -- deciding an entry -----------------------------------------------------------


class HopLike(Protocol):
    """The part of a dispatch hop result pod memory reads."""

    @property
    def role(self) -> str: ...
    @property
    def ok(self) -> bool: ...
    @property
    def output(self) -> str: ...
    @property
    def evidence(self) -> dict[str, Any] | None: ...
    @property
    def verify(self) -> dict[str, Any] | None: ...
    @property
    def trace(self) -> dict[str, str] | None: ...


class TaskLike(Protocol):
    """The part of a dispatch task result pod memory reads."""

    @property
    def hops(self) -> Any: ...


@dataclass
class _TaskFacts:
    """What docket itself knows about a finished task, against which entries are checked."""

    project: str
    root: str
    commit: str
    tainted: bool
    trace_ok: bool
    events: list[dict[str, Any]]
    verified: list[tuple[str, int]]


def _safe_path(subject: str) -> str:
    """*subject* as a normalised repository-relative path, or ``""`` when it is not one."""
    path = subject[:-1] if subject.endswith("/") and len(subject) > 1 else subject
    if not path or len(path) > _cfg.POD_MEMORY_NOTE_MAX_CHARS or any(ord(c) < 32 for c in path):
        return ""
    if path == ".":
        return path
    if path.startswith(("/", "~")) or "\\" in path:
        return ""
    return path if all(part not in ("", ".", "..") for part in path.split("/")) else ""


def _reads_as_instruction(text: str) -> str:
    words = re.findall(r"[A-Za-z']+", text.lower())
    if _URL.search(text):
        return "contains a link"
    if words and words[0] in _IMPERATIVE_FIRST_WORDS:
        return "starts with an imperative verb"
    if _INSTRUCTION_PHRASES.search(text):
        return "reads as an instruction"
    return ""


def _session_events(link: dict[str, str] | None) -> list[dict[str, Any]] | None:
    if not link:
        return None
    project, session = link.get("project", ""), link.get("session", "")
    if not project or not session or Path(project).name != project or Path(session).name != session:
        return None
    path = _cfg.TRACES_DIR / project / f"{session}.jsonl"
    return _trace.read_trace(path) if path.is_file() else None


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _bash_command(arguments: Any) -> str:
    try:
        parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError:
        return ""
    command = parsed.get("command") if isinstance(parsed, dict) else None
    return command if isinstance(command, str) else ""


def _traced_exit(events: list[dict[str, Any]], command: str) -> int | None:
    """The exit status of the last run of *command* in *events*: a ``command_step``, or a
    ``bash`` call whose ``process_exited`` falls between its ``tool_call`` and ``tool_result``."""
    found: int | None = None
    call_id, seen = "", None
    for event in events:
        kind, data = event.get("event_type"), _payload(event)
        if kind == "command_step" and data.get("cmd") == command:
            code = data.get("exit")
            found = code if isinstance(code, int) and not isinstance(code, bool) else found
        elif kind == "tool_call" and data.get("tool") == "bash":
            run = _bash_command(data.get("arguments")) == command
            call_id, seen = (str(data.get("callId", "")), None) if run else ("", None)
        elif kind == "process_exited" and call_id and isinstance(data.get("exitCode"), int):
            seen = data["exitCode"]
        elif kind == "tool_result" and call_id and str(data.get("callId", "")) == call_id:
            found = seen if seen is not None else found
            call_id, seen = "", None
    return found


def _pod_codebase(project: str) -> str:
    roster: dict[str, str] = {}
    for member_id, role, _index in _pod.members_of(_fleet.all_agent_ids(), project):
        roster.setdefault(role, member_id)
    member = roster.get("implementer") or next(iter(roster.values()), "")
    return str(_fleet.meta_get(member, "codebase", "") or "") if member else ""


def _task_facts(project: str, hops: list[HopLike], root: str | None) -> _TaskFacts:
    events: list[dict[str, Any]] = []
    trace_ok = bool(hops)
    seen: set[tuple[str, str]] = set()
    for hop in hops:
        link = hop.trace
        key = (link.get("project", ""), link.get("session", "")) if link else ("", "")
        if key in seen:
            continue
        loaded = _session_events(link)
        if loaded is None:
            trace_ok = False
            continue
        seen.add(key)
        events.extend(loaded)
    commit = next(
        (
            str(h.evidence["commit"])
            for h in reversed(hops)
            if isinstance(h.evidence, dict) and h.evidence.get("commit")
        ),
        "",
    )
    verified = [
        (str(h.verify["cmd"]), int(h.verify["exitCode"]))
        for h in hops
        if isinstance(h.verify, dict)
        and isinstance(h.verify.get("cmd"), str)
        and isinstance(h.verify.get("exitCode"), int)
    ]
    tainted = any(
        e.get("event_type") == "tool_call" and _payload(e).get("tool") == "fetch" for e in events
    )
    return _TaskFacts(
        project=project,
        root=_pod_codebase(project) if root is None else root,
        commit=commit,
        tainted=tainted,
        trace_ok=trace_ok,
        events=events,
        verified=verified,
    )


def _screen(role: str, project: str, text: str) -> tuple[str, str]:
    """The ``pre_input`` verdict on *text* as ``(status, reason)``: ``refused`` for a block,
    approval or redaction, ``pending`` for a warning, else ``("", "")``."""
    hit = _policy.policy_eval_detail(role, "pre_input", text, trusted=False, project=project)
    if hit.action in ("block", "require_approval", "redact"):
        return "refused", f"policy {hit.policy_id or 'pre_input'}: {hit.action}"
    if hit.action == "warn":
        return "pending", f"policy {hit.policy_id or 'pre_input'}: warn"
    return "", ""


def _vet(line: ParsedLine) -> tuple[str, str]:
    """``(subject, refusal)``: the normalised subject and why the line cannot be an entry."""
    subject = line.subject
    if line.kind != "command":
        subject = _safe_path(subject)
        if not subject:
            return line.subject[:200], "not a repository-relative path"
    elif not subject or len(subject) > _cfg.POD_MEMORY_NOTE_MAX_CHARS:
        return subject[:200], "not a command of a reasonable length"
    if len(line.note) > _cfg.POD_MEMORY_NOTE_MAX_CHARS:
        return subject, f"note over {_cfg.POD_MEMORY_NOTE_MAX_CHARS} characters"
    if line.kind == "command" and _URL.search(subject):
        return subject, "contains a link"
    return subject, _reads_as_instruction(line.note)


def _decide(line: ParsedLine, facts: _TaskFacts, role: str) -> tuple[str, str, str, int | None]:
    """``(subject, status, reason, exit)`` for one well-formed line."""
    subject, refusal = _vet(line)
    if refusal:
        return subject, "refused", refusal, None
    verdict, why = _screen(role, facts.project, f"{subject} {line.note}")
    if verdict == "refused":
        return subject, "refused", why, None
    held = (
        "the task called fetch"
        if facts.tainted
        else "the task's trace could not be read"
        if not facts.trace_ok
        else why
        if verdict == "pending"
        else "awaits operator approval"
        if line.kind in ("pitfall", "convention")
        else ""
    )
    if held:
        return subject, "pending", held, None
    if line.kind == "command":
        return _decide_command(subject, facts)
    if not facts.commit or not facts.root:
        return subject, "pending", "no task commit to check the path against", None
    if _sys.git_path_exists_at(facts.root, facts.commit, subject):
        return subject, "accepted", "path present at the task commit", None
    return subject, "refused", "path not present at the task commit", None


def _decide_command(command: str, facts: _TaskFacts) -> tuple[str, str, str, int | None]:
    code = next((c for cmd, c in reversed(facts.verified) if cmd == command), None)
    if code is None:
        code = _traced_exit(facts.events, command)
    if code is not None:
        return command, "accepted", "exit status found in the task's trace", code
    return command, "refused", "no exit status for this command in the task's trace", None


# -- the store -------------------------------------------------------------------


def _load(doc: dict[str, Any]) -> list[MemoryEntry]:
    raw = doc.get("entries")
    items = raw if isinstance(raw, list) else []
    return [e for e in (_entry_from_dict(d) for d in items) if e is not None]


def _trim(entries: list[MemoryEntry]) -> list[MemoryEntry]:
    """Apply the two caps, oldest first: accepted apart from pending and refused."""
    accepted = [e for e in entries if e.status == "accepted"]
    undecided = [e for e in entries if e.status != "accepted"]
    drop = {e.id for e in accepted[: max(0, len(accepted) - _cfg.POD_MEMORY_MAX_ACCEPTED)]}
    drop |= {e.id for e in undecided[: max(0, len(undecided) - _cfg.POD_MEMORY_MAX_UNDECIDED)]}
    return [e for e in entries if e.id not in drop]


def _write(entries: list[MemoryEntry]) -> dict[str, Any]:
    return {"entries": [e.to_dict() for e in _trim(entries)]}


def list_entries(project: str, status: str | None = None) -> list[MemoryEntry]:
    """The pod's entries, oldest first, optionally only those with *status*."""
    entries = _load(_store.read_json(_cfg.pod_memory_path(project)))
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
                note=line.note[: _cfg.POD_MEMORY_NOTE_MAX_CHARS],
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

    _store.read_modify_write(_cfg.pod_memory_path(project), _merge)
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

    _store.read_modify_write(_cfg.pod_memory_path(project), _fn)
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

    _store.read_modify_write(_cfg.pod_memory_path(project), _fn)
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
