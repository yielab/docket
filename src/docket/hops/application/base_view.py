"""The task's base commit as a ``RepoView``, for a reader that composes text outside a turn.

A task's worktree is writable by its Implementer, so a prompt composed from ``.docket/prompts``
is read from the commit the worktree was made at, through the git dirs docket recorded, never
from the worktree's files (config-format.spec.md, "Scopes, references and the lockfile").
"""

from __future__ import annotations

from pathlib import Path

from docket.platform import git as _git
from docket.tasks.domain.parts import Worktree
from docket.teams.workspace import repo_view as _repo_view


def base_commit_view(record: Worktree | None, directory: str) -> _repo_view.RepoView | None:
    """The codebase at *record*'s base commit, or ``None`` (read nothing from the repository)
    without a recorded worktree, base commit and git dirs: host-side git would otherwise read the
    worktree's own agent-writable ``.git`` file."""
    if record is None or not directory:
        return None
    base, git_dir = record.base_commit, record.git_dir or ""
    common_dir = record.common_dir or ""
    if not (base and git_dir and common_dir and record.dir):
        return None
    if Path(record.dir).resolve() != Path(directory).resolve():
        return None
    _git.trust_worktree(directory, git_dir, common_dir)
    return _repo_view.RepoView(
        base,
        lambda rel: _git.git_read_blob(directory, base, rel),
        lambda rel: _git.git_list_tree_dirs(directory, base, rel),
    )
