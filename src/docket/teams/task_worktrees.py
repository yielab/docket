from __future__ import annotations

from pathlib import Path

from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.kernel.ports import jail as _jail

# Per-task git worktrees live under this directory of the Implementer's workspace.
TASK_WORKTREES_DIRNAME = "tasks"


def worktree_branch(project: str, task_id: str) -> str:
    """Branch name for a task's git worktree: ``docket/<project>/<task-id>``."""
    return f"docket/{project}/{task_id}"


def task_worktrees_dir(member_id: str) -> Path:
    """Where an Implementer's per-task worktrees live: ``<member workspace>/tasks``."""
    return current_home().projects_dir / member_id / TASK_WORKTREES_DIRNAME


def provision_task_worktree(
    member_id: str, project: str, task_id: str, codebase: str, base_ref: str = ""
) -> tuple[dict[str, str], str]:
    """Create ``tasks/<task_id>`` on a new task branch from ``base_ref`` (else HEAD). Returns
    ``({dir, branch, baseCommit[, baseRef]}, "")``, or ``({}, reason)`` for no worktree."""
    tail = "" if base_ref else " -- running in place"
    if not _git.git_is_repo(codebase):
        return {}, f"codebase '{codebase}' is not a git repo{tail}"
    branch = worktree_branch(project, task_id)
    wt_path = str(task_worktrees_dir(member_id) / task_id)
    if base_ref:
        ok, err = _git.git_worktree_add(codebase, wt_path, branch, start_point=base_ref)
    else:
        ok, err = _git.git_worktree_add(codebase, wt_path, branch)
    if not ok:
        return {}, f"git worktree add failed ({err}){tail}"
    base = _git.git_head_sha(wt_path) or ""
    record = {"dir": wt_path, "branch": branch, "baseCommit": base}
    if base_ref:
        record["baseRef"] = base_ref
    dirs = _jail.worktree_git_dirs(wt_path)
    if dirs is not None:
        record["gitDir"], record["commonDir"] = dirs
    return record, ""


def _teardown_worktree_branch(codebase: str, branch: str) -> str:
    """Delete *branch* if merged into the codebase's current branch; else return a one-line
    manual ``git branch -D`` note for the caller to print (this module never imports ``ui``)."""
    current = _git.git_current_branch(codebase)
    if current and _git.git_branch_merged(codebase, branch, current):
        ok, _err = _git.git_branch_delete(codebase, branch)
        if ok:
            return ""
    where = f" into {current!r}" if current else ""
    return (
        f"kept branch {branch!r} (not merged{where}) -- delete manually: "
        f"git branch -D {branch}  (run inside {codebase})"
    )
