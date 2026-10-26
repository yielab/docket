from __future__ import annotations

from typing import Any

from docket.kernel import handoff as _handoff
from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import task_worktrees as _task_worktrees


def trusted_worktree_dir(directory: str, git_dir: str, common_dir: str) -> str:
    """*directory*, the worktree recorded on a claimed task (``""`` when it runs in place), after
    telling host-side git the *git_dir* and *common_dir* docket recorded for it, so nothing the
    agent wrote at ``.git`` is ever read."""
    _git.trust_worktree(directory, git_dir, common_dir)
    return directory


def hop_diff_probe(
    member_id: str,
    role: str,
    *,
    task_id: str,
    description: str,
    worktree_dir: str,
    base_commit: str,
    prior_diff: str = "",
) -> tuple[list[str], str | None, dict[str, Any] | None, str]:
    """``(files_changed, diff_ref, evidence, diff)`` for a hop of task *task_id* (*description* is
    the subject of the commit pinning the tree); ``diff_ref``/``evidence`` are the Implementer's,
    and a non-Implementer hop whose diff equals *prior_diff* changed nothing. *worktree_dir* is
    the task's worktree (``""`` when it runs in place) and *base_commit* the commit it started
    from. See pod-dispatch.spec.md, "Implementer diff producer" and "Hop evidence"."""
    implementer = role == "implementer"
    member_codebase = str(_fleet.meta_get(member_id, "codebase", "") or "")
    cwd = _pod.resolve_member_cwd(member_id, worktree_dir, member_codebase)
    if not _git.git_available() or not _git.git_is_repo(cwd):
        empty = {"commit": None, "baseCommit": None, "diffStat": None} if implementer else None
        return [], None, empty, ""
    files_changed = _git.git_changed_files(cwd)
    diff = _tree_diff(cwd) if files_changed else ""
    if not implementer:
        if not diff or diff == prior_diff:
            return [], None, None, ""
        if worktree_dir:
            _pin_hop_tree(cwd, task_id, description, role, in_worktree=True)
        return files_changed, None, None, diff
    diff_ref = _git.git_current_branch(cwd) or None
    commit = _pin_hop_tree(cwd, task_id, description, role, in_worktree=bool(worktree_dir))
    if worktree_dir:
        base: str | None = base_commit or None
    else:
        base_branch = _git.git_current_branch(member_codebase or cwd) or None
        base = _git.git_merge_base(cwd, base_branch) if base_branch else None
    diff_stat = _git.git_diff_stat(cwd, base, commit) if base and commit else None
    evidence = {"commit": commit, "baseCommit": base, "diffStat": diff_stat}
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


def _pin_hop_tree(
    cwd: str, task_id: str, description: str, role: str, *, in_worktree: bool
) -> str | None:
    """Pin the tree a hop left in a commit and return its sha, ``None`` on failure: committed on
    the task branch in a task worktree, a branchless snapshot in place. An agent normally leaves
    its work uncommitted, and the task branch would then stay at its base commit."""
    first_line = description.strip().split("\n", 1)[0].strip()
    subject = _cut_at_word(first_line, 72) or f"docket task {task_id}"
    message = f"{subject}\n\ndocket task {task_id}, {role} hop"
    if in_worktree:
        return _git.git_commit_all(cwd, message)
    return _git.git_snapshot_commit(cwd, message)


def ensure_task_worktree(
    project: str, task_id: str, base_ref: str
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    """``(worktree, refusal)`` for a claimed task that has no recorded worktree. *worktree* is the
    record to store (a failed add is an empty record with a ``fallbackReason``: the task runs in
    place); ``None`` when none was made. With a *base_ref* it never runs in place: *refusal* is
    ``(failure_kind, reason)`` and nothing is stored. The caller stores the record; this module
    does not touch the queue."""
    implementer = _pod.member_id(project, "implementer")
    codebase = str(_fleet.meta_get(implementer, "codebase", "") or "")
    if not codebase:
        if base_ref:
            reason = (
                f"baseRef {base_ref!r} needs a task worktree, but the Implementer has no codebase"
            )
            return None, ("base_ref", reason)
        return None, None
    record, reason = _task_worktrees.provision_task_worktree(
        implementer, project, task_id, codebase, base_ref
    )
    if base_ref and not record:
        return None, ("base_ref", f"baseRef {base_ref!r} was not used: {reason}")
    stored: dict[str, Any] = (
        record if record else {"dir": "", "branch": "", "baseCommit": "", "fallbackReason": reason}
    )
    return stored, None
