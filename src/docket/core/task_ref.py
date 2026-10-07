"""Resolve what an operator typed to one task: a full id, the short id, a prefix, or a run id."""

from __future__ import annotations

from dataclasses import dataclass, field

from docket.core import dispatch as _dispatch
from docket.core import runs as _runs

SHORT_ID_LEN = 18
LEAD_STEP_ID = "lead"


class TaskRefError(Exception):
    """The reference matched no task, or more than one."""


@dataclass(frozen=True)
class TaskRef:
    task_id: str
    project: str
    session_key: str
    run_ids: tuple[str, ...] = field(default_factory=tuple)
    worktree: str = ""


def short_id(task_id: str) -> str:
    """The form `task list` prints."""
    return task_id[:SHORT_ID_LEN]


def _build(project: str, task: dict[str, object]) -> TaskRef:
    task_id = str(task["id"])
    record = task.get("worktree")
    worktree = str(record.get("dir") or "") if isinstance(record, dict) else ""
    run_ids = tuple(
        str(r["id"])
        for r in _runs.list_runs(project)
        if task_id in (r.get("taskIds") or []) and r.get("id")
    )
    lead = f"{project}-{LEAD_STEP_ID}"
    return TaskRef(
        task_id=task_id,
        project=project,
        session_key=_dispatch.step_session_key(lead, project, task_id, LEAD_STEP_ID),
        run_ids=run_ids,
        worktree=worktree,
    )


def _resolve_run(ref: str) -> TaskRef | None:
    run = _runs.get_run(ref)
    if run is None:
        return None
    project = str(run.get("project", ""))
    task_ids = [str(t) for t in run.get("taskIds") or []]
    tasks = {str(t.get("id")): t for t in _dispatch.read_tasks(project)}
    found = [tasks[t] for t in task_ids if t in tasks]
    if not found:
        raise TaskRefError(f"run {ref} (pod {project}) has no task on the queue")
    if len(found) > 1:
        listing = ", ".join(f"{t['id']} (pod {project})" for t in found)
        raise TaskRefError(f"run {ref} dispatched more than one task: {listing}")
    return _build(project, found[0])


def resolve_task(project: str | None, ref: str) -> TaskRef:
    """Resolve *ref* within one pod, or every pod when *project* is ``None``.

    Raises ``TaskRefError`` listing candidates (ambiguous) or what was searched (unknown)."""
    ref = ref.strip()
    if not ref:
        raise TaskRefError("no task reference given")
    if ref.startswith("run-"):
        via_run = _resolve_run(ref)
        if via_run is not None:
            if project is not None and via_run.project != project:
                raise TaskRefError(f"run {ref} belongs to pod {via_run.project}, not {project}")
            return via_run

    pods = [project] if project is not None else sorted(_dispatch.dispatchable_pods())
    matches: list[tuple[str, dict[str, object]]] = []
    for pod in pods:
        for task in _dispatch.read_tasks(pod):
            if str(task.get("id", "")).startswith(ref):
                matches.append((pod, task))

    exact = [m for m in matches if m[1]["id"] == ref]
    if exact:
        matches = exact
    if len(matches) == 1:
        return _build(*matches[0])
    if matches:
        listing = ", ".join(f"{t['id']} (pod {p})" for p, t in matches)
        raise TaskRefError(f"{ref!r} is ambiguous: {listing}")
    searched = f"pod {project}" if project is not None else f"{len(pods)} pod(s)"
    names = f" ({', '.join(pods)})" if project is None and pods else ""
    raise TaskRefError(f"no task or run matches {ref!r}; searched {searched}{names}")
