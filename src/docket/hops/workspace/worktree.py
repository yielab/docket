from __future__ import annotations

from typing import Any

from docket.agent import handoff as _handoff
from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.platform import read_modify_write
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import task_worktrees as _task_worktrees
from docket.teams.settings import pod_task_list_path


def _task_worktree_dir(task: dict[str, Any]) -> str:
    """The directory of the worktree recorded on *task* at claim, or empty when the task runs in
    place (no recorded worktree, or a recorded fallback). It also tells host-side git the git dir
    docket recorded for that worktree, so nothing the agent wrote at ``.git`` is ever read."""
    record = task.get("worktree")
    if not isinstance(record, dict):
        return ""
    wt_dir = str(record.get("dir") or "")
    _git.trust_worktree(wt_dir, str(record.get("gitDir") or ""), str(record.get("commonDir") or ""))
    return wt_dir


def _hop_diff_probe(
    member_id: str, role: str, task: dict[str, Any], prior_diff: str = ""
) -> tuple[list[str], str | None, dict[str, Any] | None, str]:
    """``(files_changed, diff_ref, evidence, diff)`` for a hop; ``diff_ref``/``evidence`` are the
    Implementer's, and a non-Implementer hop whose diff equals *prior_diff* changed nothing.
    See pod-dispatch.spec.md, "Implementer diff producer" and "Hop evidence"."""
    implementer = role == "implementer"
    task_dir = _task_worktree_dir(task)
    member_codebase = str(_fleet.meta_get(member_id, "codebase", "") or "")
    cwd = _pod.resolve_member_cwd(member_id, task_dir, member_codebase)
    if not _git.git_available() or not _git.git_is_repo(cwd):
        empty = {"commit": None, "baseCommit": None, "diffStat": None} if implementer else None
        return [], None, empty, ""
    files_changed = _git.git_changed_files(cwd)
    diff = _tree_diff(cwd) if files_changed else ""
    if not implementer:
        if not diff or diff == prior_diff:
            return [], None, None, ""
        if task_dir:
            _pin_hop_tree(cwd, task, role, in_worktree=True)
        return files_changed, None, None, diff
    diff_ref = _git.git_current_branch(cwd) or None
    commit = _pin_hop_tree(cwd, task, role, in_worktree=bool(task_dir))
    recorded = task.get("worktree")
    base_commit: str | None = None
    if task_dir and isinstance(recorded, dict):
        base_commit = str(recorded.get("baseCommit") or "") or None
    else:
        base_branch = _git.git_current_branch(member_codebase or cwd) or None
        base_commit = _git.git_merge_base(cwd, base_branch) if base_branch else None
    diff_stat = _git.git_diff_stat(cwd, base_commit, commit) if base_commit and commit else None
    evidence = {"commit": commit, "baseCommit": base_commit, "diffStat": diff_stat}
    return files_changed, diff_ref, evidence, "" if diff == prior_diff else diff


def _tree_diff(cwd: str) -> str:
    """The tree's uncommitted tracked changes plus the content of its new files, capped at
    ``HANDOFF_DIFF_MAX_CHARS`` with a marker; ``""`` when git can say nothing."""
    limit = current_home().handoff_diff_max_chars
    text = (_git.git_diff(cwd, "HEAD") or "") + _git.git_new_files_text(cwd, limit)
    return _handoff.cap_diff(text, limit)


def _cut_at_word(text: str, limit: int) -> str:
    """*text* whole when it fits *limit*, else cut at the last space before the limit (at the
    limit itself when its first word is longer)."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    if text[limit] == " ":
        return head.rstrip()
    cut = head.rfind(" ")
    return head[:cut].rstrip() if cut > 0 else head


def _pin_hop_tree(cwd: str, task: dict[str, Any], role: str, *, in_worktree: bool) -> str | None:
    """Pin the tree a hop left in a commit and return its sha, ``None`` on failure: committed on
    the task branch in a task worktree, a branchless snapshot in place. An agent normally leaves
    its work uncommitted, and the task branch would then stay at its base commit."""
    task_id = str(task.get("id") or "")
    first_line = str(task.get("description") or "").strip().split("\n", 1)[0].strip()
    subject = _cut_at_word(first_line, 72) or f"docket task {task_id}"
    message = f"{subject}\n\ndocket task {task_id}, {role} hop"
    if in_worktree:
        return _git.git_commit_all(cwd, message)
    return _git.git_snapshot_commit(cwd, message)


def _ensure_task_worktree(project: str, claimed: dict[str, Any]) -> None:
    """Record ``task["worktree"]`` for a claimed task (a recorded one is kept); a failed add
    records ``fallbackReason`` and runs in place. With a ``baseRef`` it never runs in place:
    it sets ``claimed["claimRefusal"] = (failure_kind, reason)`` instead."""
    if "worktree" in claimed:
        return
    base_ref = str(claimed.get("baseRef") or "")
    implementer = _pod.member_id(project, "implementer")
    codebase = str(_fleet.meta_get(implementer, "codebase", "") or "")
    if not codebase:
        if base_ref:
            claimed["claimRefusal"] = (
                "base_ref",
                f"baseRef {base_ref!r} needs a task worktree, but the Implementer has no codebase",
            )
        return
    task_id = str(claimed.get("id", ""))
    record, reason = _task_worktrees.provision_task_worktree(
        implementer, project, task_id, codebase, base_ref
    )
    if base_ref and not record:
        claimed["claimRefusal"] = ("base_ref", f"baseRef {base_ref!r} was not used: {reason}")
        return
    stored: dict[str, Any] = (
        record if record else {"dir": "", "branch": "", "baseCommit": "", "fallbackReason": reason}
    )

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks = doc.get("tasks")
        if not isinstance(tasks, list):
            return None
        for t in tasks:
            if isinstance(t, dict) and t.get("id") == task_id:
                t["worktree"] = stored
        return {"tasks": tasks}

    read_modify_write(pod_task_list_path(project), _fn)
    claimed["worktree"] = stored
