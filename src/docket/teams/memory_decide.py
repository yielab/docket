"""Pod memory verdicts -- what docket itself knows about a finished task, and the status it gives
one memory line from that.

``_task_facts`` gathers the commit, the trace events and the verify gates of a task's hops;
``_decide`` turns one parsed line into ``(subject, status, reason, exit)``. See
specs/functional/workspace-structure.spec.md "Pod memory"."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from docket.governance import policy as _policy
from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.observability import trace as _trace
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams.memory_parse import ParsedLine, _vet

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


def _session_events(link: dict[str, str] | None) -> list[dict[str, Any]] | None:
    if not link:
        return None
    project, session = link.get("project", ""), link.get("session", "")
    if not project or not session or Path(project).name != project or Path(session).name != session:
        return None
    path = current_home().traces_dir / project / f"{session}.jsonl"
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
    if line.kind == "tool":
        return _decide_command(subject, facts)
    if not facts.commit or not facts.root:
        return subject, "pending", "no task commit to check the path against", None
    if _git.git_path_exists_at(facts.root, facts.commit, subject):
        return subject, "accepted", "path present at the task commit", None
    return subject, "refused", "path not present at the task commit", None


def _decide_command(command: str, facts: _TaskFacts) -> tuple[str, str, str, int | None]:
    code = next((c for cmd, c in reversed(facts.verified) if cmd == command), None)
    if code is None:
        code = _traced_exit(facts.events, command)
    if code is not None:
        return command, "accepted", "exit status found in the task's trace", code
    return command, "refused", "no exit status for this command in the task's trace", None
