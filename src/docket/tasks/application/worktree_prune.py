from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.governance.audit import audit_log
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.platform import read_json, read_modify_write
from docket.tasks.application.queue import RESUMABLE_FAILURE_KINDS as resumable
from docket.teams import pod
from docket.teams.task_worktrees import task_worktrees_dir, worktree_branch

PRUNABLE_TASK_STATUSES = frozenset({"done", "failed", "cancelled"})


@dataclass(frozen=True)
class WorktreePruneEntry:
    """One finished task's worktree and what ``prune_task_worktrees`` did (or would do)."""

    task_id: str
    dir: str
    action: str  # "removed" | "would-remove" | "kept"
    reason: str = ""


def _task_list_file(project: str) -> Path:
    return current_home().workspace_dir(pod.member_id(project, "lead")) / "TASK_LIST.json"


def _worktree_owner(project: str, wt_dir: str) -> tuple[str, str] | None:
    """``(member id, codebase)`` of the pod member whose task-worktrees dir directly holds
    *wt_dir* once resolved; ``None`` for any path outside every member's ``tasks/`` dir."""
    resolved = Path(wt_dir).resolve()
    if not current_home().projects_dir.is_dir():
        return None
    names = [p.name for p in current_home().projects_dir.iterdir() if p.is_dir()]
    for member_id, _role, _idx in pod.members_of(names, project):
        if resolved.parent != task_worktrees_dir(member_id).resolve():
            continue
        try:
            raw = read_json(current_home().projects_dir / member_id / current_home().meta_file)
        except Exception:
            return None
        return member_id, str(raw.get("codebase", ""))
    return None


def _prune_one(
    project: str, task: dict[str, Any], *, force: bool, dry_run: bool
) -> WorktreePruneEntry:
    task_id = str(task.get("id", ""))
    wt_dir = str(task["worktree"]["dir"])

    def kept(reason: str) -> WorktreePruneEntry:
        return WorktreePruneEntry(task_id, wt_dir, "kept", reason)

    owner = _worktree_owner(project, wt_dir)
    if owner is None or not owner[1]:
        return kept("worktree dir is not inside a pod member's task-worktrees dir")
    codebase = owner[1]
    branch = worktree_branch(project, task_id)
    recorded = str(task["worktree"].get("branch", ""))
    if recorded and recorded != branch:
        return kept(f"recorded branch {recorded!r} is not {branch!r}")
    exists = Path(wt_dir).is_dir()
    changes = _git.git_worktree_changes(wt_dir) if exists else []
    # Only tracked changes are unsaved work; untracked files in a finished task's worktree are
    # build and verify artifacts (``__pycache__/``, outputs), discarded but named.
    dirty = any(status.strip() != "??" for status, _ in changes)
    untracked = sum(1 for status, _ in changes if status.strip() == "??")
    discarded = f"{untracked} untracked file(s) discarded" if untracked else ""
    current = _git.git_current_branch(codebase)
    merged = bool(current) and _git.git_branch_merged(codebase, branch, current)
    problems = (["uncommitted changes"] if dirty else []) + (
        [] if merged else [f"branch {branch!r} not merged into {current or 'the current branch'!r}"]
    )
    if problems and not force:
        return kept("; ".join(problems))
    if dry_run:
        return WorktreePruneEntry(
            task_id, wt_dir, "would-remove", "; ".join([*problems, *filter(None, [discarded])])
        )
    if exists:
        ok, err = _git.git_worktree_remove(codebase, wt_dir)
        if not ok:
            return kept(f"git worktree remove failed ({err})")
    _git.git_worktree_prune(codebase)
    notes = [discarded] if discarded else []
    if merged:
        _git.git_branch_delete(codebase, branch)
    else:
        notes.append(f"branch {branch!r} kept (unmerged)")
    if problems:
        audit_log("pod.worktrees.prune", f"project={project} task={task_id} forced: {problems}")
    return WorktreePruneEntry(task_id, wt_dir, "removed", "; ".join(notes))


def prune_task_worktrees(
    project: str, *, force: bool = False, dry_run: bool = False
) -> list[WorktreePruneEntry]:
    """Remove finished tasks' worktrees (and merged branches), recording ``worktree.prunedAt``.

    Only done/failed/cancelled tasks with a recorded dir are considered. Without *force* a
    dirty worktree or unmerged branch is kept and reported; *force* removes the worktree but
    never deletes an unmerged branch. A failed task ``dispatch --resume`` would re-claim keeps its
    worktree."""

    raw = read_json(_task_list_file(project))
    tasks = raw.get("tasks") if isinstance(raw, dict) else None
    entries: list[WorktreePruneEntry] = []
    for task in tasks if isinstance(tasks, list) else []:
        wt = task.get("worktree") if isinstance(task, dict) else None
        if (
            not isinstance(wt, dict)
            or not wt.get("dir")
            or wt.get("prunedAt")
            or task.get("status") not in PRUNABLE_TASK_STATUSES
        ):
            continue
        if task.get("status") == "failed" and task.get("failureKind") in resumable:
            entries.append(
                WorktreePruneEntry(
                    str(task.get("id", "")), str(wt["dir"]), "kept", "resumable (dispatch --resume)"
                )
            )
            continue
        entries.append(_prune_one(project, task, force=force, dry_run=dry_run))
    pruned = {e.task_id for e in entries if e.action == "removed"}
    if pruned:
        stamp = _clock.iso()

        def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
            for t in doc.get("tasks") or []:
                if t.get("id") in pruned and isinstance(t.get("worktree"), dict):
                    t["worktree"]["prunedAt"] = stamp
            return doc

        read_modify_write(_task_list_file(project), _fn)
    return entries
