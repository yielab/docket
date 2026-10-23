"""The task's root and a derived repository map, for the message that starts a hop.

The map is directories with file counts from ``git ls-files``: relative, deterministic, and
capped, so a model starts from the shape of the tree instead of listing it. Nothing here is
persisted; it is derived again for every hop.
"""

from __future__ import annotations

from collections import Counter

from docket.core import fleet as _fleet
from docket.core import pod as _pod
from docket.edges.adapters import system as _sys
from docket.kernel.home import current_home

#: Directories the built-in ``glob``/``grep`` skip; a unit test pins this to the toolbox set.
SKIPPED_DIRS = frozenset(
    {".git", "node_modules", ".venv", "dist", "build", "target", "vendor", "__pycache__"}
)
_DEPTHS = (3, 2, 1)


def _directory_counts(paths: list[str], depth: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in paths:
        parts = path.split("/")
        if any(part in SKIPPED_DIRS for part in parts[:-1]):
            continue
        counts["/".join(parts[:-1][:depth]) or "."] += 1
    return counts


def _render(counts: Counter[str]) -> str:
    return "\n".join(
        f"{name}/ ({n} {'file' if n == 1 else 'files'})" for name, n in sorted(counts.items())
    )


def render_repo_map(root: str) -> str:
    """Directories under *root* with their file counts, at the deepest depth that fits
    ``REPO_MAP_MAX_CHARS``; ``""`` when *root* is not a git repository or holds no tracked file."""
    paths = _sys.git_ls_files(root)
    if not paths:
        return ""
    cap = current_home().repo_map_max_chars
    rendered = ""
    for depth in _DEPTHS:
        counts = _directory_counts(paths, depth)
        rendered = _render(counts)
        if len(rendered) <= cap:
            return rendered
    kept: list[str] = []
    used = 0
    lines = rendered.splitlines()
    for index, line in enumerate(lines):
        if used + len(line) + 1 > cap:
            kept.append(f"... {len(lines) - index} more directories")
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept)


def _pod_root(project: str, role: str) -> str:
    """The codebase or working directory the pod's tools are rooted in for *role*."""
    roster: dict[str, str] = {}
    for member_id, member_role, _index in _pod.members_of(_fleet.all_agent_ids(), project):
        roster.setdefault(member_role, member_id)
    member_id = roster.get(role) or next(iter(roster.values()), "")
    if not member_id:
        return ""
    return _fleet.meta_get(member_id, "codebase", "") or _fleet.meta_get(member_id, "workDir", "")


def task_root_block(task_worktree: str, project: str, role: str) -> str:
    """The ``Working directory`` line and repository map for a hop: the task's worktree when it
    has one, else the pod's codebase or working directory. ``""`` when no root resolves."""
    root = task_worktree or (_pod_root(project, role) if project else "")
    if not root:
        return ""
    block = f"Working directory: {root}"
    repo_map = render_repo_map(root)
    return (
        f"{block}\nRepository map (tracked files by directory):\n{repo_map}" if repo_map else block
    )
