"""The task's root and the derived repository maps, for the message that starts a hop.

The capped map is directories with file counts from ``git ls-files``; the bounded map lists the
entries beside the paths a brief names, read from the task's base commit so a hop's edits do not
move it. Both are relative and deterministic, derived again for every hop, and never name an
absolute path.
"""

from __future__ import annotations

from collections import Counter

from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod

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


def _cut(lines: list[str], noun: str) -> str:
    """*lines* up to ``REPO_MAP_MAX_CHARS``, then a ``... N more <noun>`` line."""
    cap = current_home().repo_map_max_chars
    kept: list[str] = []
    used = 0
    for index, line in enumerate(lines):
        if used + len(line) + 1 > cap:
            kept.append(f"... {len(lines) - index} more {noun}")
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept)


def render_repo_map(root: str) -> str:
    """Directories under *root* with their file counts, at the deepest depth that fits
    ``REPO_MAP_MAX_CHARS``; ``""`` when *root* is not a git repository or holds no tracked file."""
    paths = _git.git_ls_files(root)
    if not paths:
        return ""
    cap = current_home().repo_map_max_chars
    rendered = ""
    for depth in _DEPTHS:
        counts = _directory_counts(paths, depth)
        rendered = _render(counts)
        if len(rendered) <= cap:
            return rendered
    return _cut(rendered.splitlines(), "directories")


def _pod_root(project: str, role: str) -> str:
    """The codebase or working directory the pod's tools are rooted in for *role*."""
    roster: dict[str, str] = {}
    for member_id, member_role, _index in _pod.members_of(_fleet.all_agent_ids(), project):
        roster.setdefault(member_role, member_id)
    member_id = roster.get(role) or next(iter(roster.values()), "")
    if not member_id:
        return ""
    return _fleet.meta_get(member_id, "codebase", "") or _fleet.meta_get(member_id, "workDir", "")


def resolve_root(task_worktree: str, project: str, role: str) -> str:
    """The directory *role*'s tools are rooted in: the task's worktree when it has one, else the
    pod's codebase or working directory; ``""`` when none resolves."""
    return task_worktree or (_pod_root(project, role) if project else "")


#: The one line that says where the tools start. It names no path: a model copies a path it is
#: shown, and the tools are already rooted there.
WORKING_DIRECTORY_LINE = (
    "Working directory: the repository root (your tools start there; give paths relative to it)."
)
_CAPPED_HEADER = "Repository map (tracked files by directory):"
_BOUNDED_HEADER = "Repository map (the paths the brief names, with their direct entries):"
_GLOB_LINE = "For any other path, use the `glob` tool."
_EDGE_PUNCTUATION = "`'\"()[]{}<>,;:.!?"


def capped_map(root: str) -> str:
    """The header and the capped directory map of *root*; ``""`` when it has no tracked file."""
    rendered = render_repo_map(root)
    return f"{_CAPPED_HEADER}\n{rendered}" if rendered else ""


def _named(token: str) -> str:
    """A candidate repository path from one whitespace-delimited word of a brief."""
    word = token.strip(_EDGE_PUNCTUATION).removeprefix("path:").split("#", 1)[0]
    return word.removeprefix("./").strip("/")


def _entries_in(paths: list[str], directory: str) -> set[str]:
    """The entries directly in *directory* (``""`` is the root), as relative paths with a
    trailing ``/`` on a subdirectory."""
    prefix = f"{directory}/" if directory else ""
    found: set[str] = set()
    for path in paths:
        if path.startswith(prefix):
            head, slash, _rest = path[len(prefix) :].partition("/")
            found.add(f"{prefix}{head}{slash}")
    return found


def bounded_map(root: str, base_commit: str, brief_text: str) -> str:
    """The header, the entries beside every tracked path *brief_text* names (the root's entries
    when it names none) and a last line naming ``glob``; ``""`` when *root* has no tracked file.
    Read from *base_commit*'s tree when it resolves, else from the index."""
    listed = (_git.git_ls_files(root, base_commit) if base_commit else None) or _git.git_ls_files(
        root
    )
    paths = [
        path
        for path in listed or []
        if not any(part in SKIPPED_DIRS for part in path.split("/")[:-1])
    ]
    if not paths:
        return ""
    files = set(paths)
    directories = {"/".join(p.split("/")[:n]) for p in paths for n in range(1, p.count("/") + 1)}
    entries: set[str] = set()
    for token in brief_text.split():
        target = _named(token)
        if target in files:
            entries |= _entries_in(paths, target.rpartition("/")[0])
        elif target in directories:
            entries |= _entries_in(paths, target)
    entries = entries or _entries_in(paths, "")
    return "\n".join([_BOUNDED_HEADER, *_cut(sorted(entries), "entries").splitlines(), _GLOB_LINE])
