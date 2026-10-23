from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from stat import S_ISREG

from docket.platform.process import _QUERY_TIMEOUT, _SANDBOX_PROBE_TIMEOUT, _TRUSTED_TREES, _which


def trust_worktree(path: str, git_dir: str, common_dir: str) -> None:
    """Record the git dir and common dir docket created for the task worktree at *path*. Host-side
    git then names them explicitly and never reads the worktree's ``.git`` file, which the
    jailed agent can rewrite."""
    if path and git_dir and common_dir:
        _TRUSTED_TREES[os.path.realpath(path)] = (git_dir, common_dir)


def _git_plain(cwd: str, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=_SANDBOX_PROBE_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


_WORKTREE_CONFIG_ON = re.compile(r"^\s*worktreeconfig\s*=\s*(true|yes|on|1)\s*$", re.I | re.M)


def _worktree_config_poisoned(git_dir: str, common_dir: str) -> bool:
    """True when a per-worktree config file exists and the shared config makes git read it: the
    jail can write that file under Landlock, and a config key can name a program."""
    if not os.path.exists(os.path.join(git_dir, "config.worktree")):
        return False
    try:
        text = Path(common_dir, "config").read_text(errors="replace")
    except OSError:
        return True
    return bool(_WORKTREE_CONFIG_ON.search(text))


def _trusted_git_env(
    cwd: str, env: dict[str, str] | None
) -> tuple[dict[str, str] | None, str | None]:
    """The environment for host-side git in *cwd*, and a refusal reason or ``None``. In a worktree
    docket recorded, the git dir, common dir and work tree are named through the environment, so
    nothing the agent wrote at ``.git`` is read; a poisoned per-worktree config is refused."""
    trusted = _TRUSTED_TREES.get(os.path.realpath(cwd))
    if trusted is None:
        return env, None
    git_dir, common_dir = trusted
    if _worktree_config_poisoned(git_dir, common_dir):
        return env, "refused: the worktree config could name a program to run"
    return {
        **(os.environ if env is None else env),
        "GIT_DIR": git_dir,
        "GIT_COMMON_DIR": common_dir,
        "GIT_WORK_TREE": os.path.realpath(cwd),
    }, None


def _git_run(
    cwd: str,
    args: list[str],
    timeout: float,
    env: dict[str, str] | None = None,
    config: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Run ``git -C cwd <config> <args>``; a worktree docket recorded is addressed through its
    recorded git dirs (see ``_trusted_git_env``) and fails closed on a poisoned config."""
    env, refused = _trusted_git_env(cwd, env)
    if refused is not None:
        return subprocess.CompletedProcess(args, 1, "", refused)
    return subprocess.run(
        ["git", "-C", cwd, *config, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


_GIT_IDENTITY_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
)


def git_identity_env(root: Path) -> dict[str, str]:
    """The operator's git identity for a jailed command in *root*: the four ``GIT_AUTHOR_*``/
    ``GIT_COMMITTER_*`` variables when set, else ``user.name``/``user.email`` as git resolves
    them on the host there. Identity only, never a credential; empty when git knows none."""
    found = {k: os.environ[k] for k in _GIT_IDENTITY_VARS if os.environ.get(k)}
    if len(found) == len(_GIT_IDENTITY_VARS) or not git_available():
        return found
    resolved: dict[str, str] = {}
    for key in ("name", "email"):
        try:
            out = _git_run(str(root), ["config", "--get", f"user.{key}"], _QUERY_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0 and out.stdout.strip():
            resolved[key] = out.stdout.strip()
    for var in _GIT_IDENTITY_VARS:
        value = resolved.get(var.rsplit("_", 1)[1].lower())
        if var not in found and value:
            found[var] = value
    return found


def git_available() -> bool:
    """Return True if a git binary is on PATH."""
    return _which("git")


def git_current_branch(cwd: str) -> str:
    """Return the current git branch for `cwd`, or '' if not a repo or unavailable; degrades
    gracefully on a missing binary, non-repo directory, or timeout. The ``diff_ref`` producer for an
    Implementer hop's ``HandoffArtifact`` (`core/dispatch.py`'s `_hop_diff_probe`)."""
    if not git_available():
        return ""
    try:
        result = _git_run(cwd, ["rev-parse", "--abbrev-ref", "HEAD"], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def git_is_repo(cwd: str) -> bool:
    """Return True if ``cwd`` is inside a git repository."""
    if not git_available():
        return False
    try:
        result = _git_run(cwd, ["rev-parse", "--git-dir"], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def git_changed_files(cwd: str, *, all_untracked: bool = False) -> list[str]:
    """Return paths with uncommitted changes in `cwd` (staged, unstaged,
    untracked; with `all_untracked`, each file inside a new directory rather
    than the directory); the `files_changed` producer for an Implementer hop's
    `HandoffArtifact`. Uses `git status --porcelain` (not a diff against a
    fixed base ref) so it reflects the real tree regardless of what the
    Implementer has committed this hop. Degrades to `[]` -- never raises --
    on a missing binary, non-repo directory, timeout, or clean tree. Sorted
    for determinism (porcelain order is otherwise platform-dependent)."""
    if not git_available():
        return []
    try:
        args = ["status", "--porcelain", *(["--untracked-files=all"] if all_untracked else [])]
        result = _git_run(cwd, args, _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain v1: two status chars, a space, then the path. A rename/copy
        # line reads "R  old/path -> new/path" — keep only the new path.
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip())
    return sorted(files)


def git_worktree_changes(cwd: str) -> list[tuple[str, str]]:
    """Return ``(status, absolute path)`` for every path ``git status`` reports in the repository
    containing `cwd`, untracked files listed one by one. Degrades to ``[]`` -- never raises --
    on a missing binary, non-repo directory, or timeout, like `git_changed_files`."""
    if not git_available():
        return []
    try:
        top = _git_run(cwd, ["rev-parse", "--show-toplevel"], _QUERY_TIMEOUT)
        status = _git_run(
            cwd, ["status", "--porcelain", "-z", "--untracked-files=all"], _QUERY_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if top.returncode != 0 or status.returncode != 0:
        return []
    root = top.stdout.strip()
    fields = status.stdout.split("\0")
    changes: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        # With -z a rename or copy is "XY new\0old\0": the original path is its own field.
        if code[0] in "RC":
            index += 1
        changes.append((code, os.path.join(root, path)))
    return changes


def git_worktree_add(
    repo_dir: str, worktree_path: str, branch: str, start_point: str = ""
) -> tuple[bool, str]:
    """Create a worktree at ``worktree_path`` on new branch ``branch`` (from ``start_point`` if
    given). Returns ``(success, error_message)``; never raises, returning ``(False, reason)``."""
    if not git_available():
        return False, "git not found on PATH"
    if start_point.startswith("-"):
        return False, f"invalid start point {start_point!r}"
    argv = ["git", "-C", repo_dir, "worktree", "add", "-b", branch, worktree_path]
    if start_point:
        argv.append(start_point)
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def git_info_exclude(common_dir: str, patterns: tuple[str, ...]) -> None:
    """Append each of *patterns* not already there to ``<common_dir>/info/exclude``, the one
    exclude file git reads for every worktree of the repository. Best effort, never raises."""
    path = Path(common_dir) / "info" / "exclude"
    try:
        existing = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        missing = [p for p in patterns if p not in existing]
        if missing:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write("".join(f"{p}\n" for p in missing))
    except OSError:
        return


def git_worktree_remove(repo_dir: str, worktree_path: str) -> tuple[bool, str]:
    """Remove the git worktree at ``worktree_path`` (``--force``, to handle
    unclean worktrees). Returns ``(success, message)``; degrades gracefully
    on errors."""
    if not git_available():
        return False, "git not found on PATH"
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "worktree", "remove", "--force", worktree_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def git_worktree_prune(repo_dir: str) -> None:
    """Drop worktree records whose directory is gone; silent on every error."""
    if not git_available():
        return
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(
            ["git", "-C", repo_dir, "worktree", "prune"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )


def git_branch_merged(repo_dir: str, branch: str, into: str) -> bool:
    """True if ``branch`` is fully merged into ``into`` in ``repo_dir``; False on a missing
    binary, non-repo directory, timeout, or a genuinely unmerged branch."""
    if not git_available():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "branch", "--merged", into],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        return False
    # "*" marks the current branch, "+" a branch checked out in another worktree.
    names = {line.strip().lstrip("*+ ").strip() for line in result.stdout.splitlines()}
    return branch in names


def git_branch_delete(repo_dir: str, branch: str) -> tuple[bool, str]:
    """Delete a local branch with ``-d`` (refuses an unmerged branch; never ``-D``).
    Returns ``(success, message)``; degrades gracefully on errors."""
    if not git_available():
        return False, "git not found on PATH"
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "branch", "-d", branch],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def git_head_sha(cwd: str) -> str | None:
    """Return the full 40-hex-char HEAD sha for `cwd`, or ``None`` if not a repo or
    unavailable; degrades gracefully like `git_current_branch`. The ``commit`` producer
    for an Implementer hop's persisted evidence."""
    if not git_available():
        return None
    try:
        result = _git_run(cwd, ["rev-parse", "HEAD"], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


_FULL_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _repo_rel_path_ok(rel: str) -> bool:
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and all(p not in ("", ".", "..") for p in parts)


def git_read_blob(cwd: str, rev: str, rel: str) -> bytes | None:
    """The bytes of repository path *rel* at commit *rev* (a full sha), read host-side through the
    git dirs docket recorded for the worktree at *cwd* when it recorded any. ``None`` when the
    path is absent at *rev*, is not a blob, *rev*/*rel* are malformed, or git is unavailable."""
    if not _FULL_SHA.match(rev) or not _repo_rel_path_ok(rel) or not git_available():
        return None
    env, refused = _trusted_git_env(cwd, None)
    if refused is not None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "cat-file", "blob", f"{rev}:{rel}"],
            capture_output=True,
            timeout=_QUERY_TIMEOUT,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout if result.returncode == 0 else None


def git_path_exists_at(cwd: str, rev: str, rel: str) -> bool:
    """Whether repository path *rel* (a file or a directory) exists at commit *rev* (a full sha),
    asked host-side like ``git_read_blob``; ``False`` for a malformed *rev* or *rel* and when
    git is unavailable."""
    if not _FULL_SHA.match(rev) or not _repo_rel_path_ok(rel) or not git_available():
        return False
    env, refused = _trusted_git_env(cwd, None)
    if refused is not None:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "cat-file", "-e", f"{rev}:{rel}"],
            capture_output=True,
            timeout=_QUERY_TIMEOUT,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def git_list_tree_dirs(cwd: str, rev: str, rel: str) -> list[str] | None:
    """Names of the subdirectories directly under *rel* at commit *rev*, sorted, read like
    ``git_read_blob``; ``None`` when *rel* is absent at *rev* or not a directory."""
    if not _FULL_SHA.match(rev) or not _repo_rel_path_ok(rel) or not git_available():
        return None
    env, refused = _trusted_git_env(cwd, None)
    if refused is not None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "ls-tree", "-d", "--name-only", "-z", f"{rev}:{rel}"],
            capture_output=True,
            timeout=_QUERY_TIMEOUT,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return sorted(n.decode("utf-8", "replace") for n in result.stdout.split(b"\0") if n)


def git_merge_base(cwd: str, other_branch: str) -> str | None:
    """Return the merge-base sha of HEAD and `other_branch` in `cwd`, or ``None`` if not a
    repo, `other_branch` is unknown, or git is unavailable; degrades gracefully like
    `git_current_branch`. The ``baseCommit`` producer for an Implementer hop's evidence."""
    if not git_available():
        return None
    try:
        result = _git_run(cwd, ["merge-base", "HEAD", other_branch], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


_SHORTSTAT_FILES = re.compile(r"(\d+) files? changed")
_SHORTSTAT_INSERTIONS = re.compile(r"(\d+) insertions?\(\+\)")
_SHORTSTAT_DELETIONS = re.compile(r"(\d+) deletions?\(-\)")


def git_diff_stat(cwd: str, base: str, head: str | None = None) -> dict[str, int] | None:
    """Return ``{"files", "insertions", "deletions"}`` diffing `base` against `head`, else against
    `cwd`'s current state (``git diff --shortstat``), or ``None`` if not a repo, a ref is missing,
    or git is unavailable; an empty summary (no changes) reports all-zero counts, not ``None``."""
    if not git_available():
        return None
    try:
        result = _git_run(
            cwd, ["diff", "--shortstat", base, *([head] if head else [])], _QUERY_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    summary = result.stdout.strip()
    files_match = _SHORTSTAT_FILES.search(summary)
    insertions_match = _SHORTSTAT_INSERTIONS.search(summary)
    deletions_match = _SHORTSTAT_DELETIONS.search(summary)
    return {
        "files": int(files_match.group(1)) if files_match else 0,
        "insertions": int(insertions_match.group(1)) if insertions_match else 0,
        "deletions": int(deletions_match.group(1)) if deletions_match else 0,
    }


def git_diff(path: str, base: str) -> str | None:
    """Return ``git diff <base>`` for the tree at `path`, or ``None`` if git is unavailable,
    `path` is not a repo or `base` is unknown; an unchanged tree returns an empty string."""
    if not git_available():
        return None
    try:
        result = _git_run(path, ["diff", base], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout if result.returncode == 0 else None


DIFF_MAX_CHARS = 500_000
_DIFF_TIMEOUT = 30


def git_diff_range(repo_dir: str, base: str, ref: str) -> str | None:
    """``git diff <base>..<ref>`` in *repo_dir*, cut at ``DIFF_MAX_CHARS`` with a trailing marker
    line; ``None`` when git is unavailable, *repo_dir* is not a repo or a ref is unknown."""
    if not git_available():
        return None
    try:
        result = _git_run(repo_dir, ["diff", f"{base}..{ref}"], _DIFF_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    patch = result.stdout
    if len(patch) > DIFF_MAX_CHARS:
        patch = f"{patch[:DIFF_MAX_CHARS]}\n[diff truncated at {DIFF_MAX_CHARS} characters]\n"
    return patch


def git_new_files_text(cwd: str, limit: int) -> str:
    """Each new untracked file's content under a ``--- new file: <path>`` line, path order, read up
    to about `limit` characters; a symlink, non-regular or binary file gets a note, not content.
    ``""`` on no git, no repo or no new file."""
    parts: list[str] = []
    size = 0
    for _code, path in sorted(c for c in git_worktree_changes(cwd) if c[0] == "??"):
        if size > limit:
            break
        rel = os.path.relpath(path, cwd)
        body = _read_new_file(path, limit - size + 1)
        parts.append(f"--- new file: {rel}\n{body}")
        size += len(parts[-1])
    return "".join(part if part.endswith("\n") else part + "\n" for part in parts)


def _read_new_file(path: str, limit: int) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return "(not a regular file; content not shown)"
    with os.fdopen(fd, "rb") as handle:
        if not S_ISREG(os.fstat(handle.fileno()).st_mode):
            return "(not a regular file; content not shown)"
        data = handle.read(max(limit, 1))
    if b"\0" in data:
        return "(binary file; content not shown)"
    return data.decode("utf-8", errors="replace")


def git_ls_files(cwd: str) -> list[str] | None:
    """Tracked paths of the repository at *cwd*, repository-relative and sorted; ``None`` when
    git is missing, *cwd* is not a repository, or the listing fails or times out."""
    if not git_available():
        return None
    try:
        result = _git_run(cwd, ["ls-files", "-z"], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return sorted(path for path in result.stdout.split("\0") if path)


def git_untracked(worktree: str) -> list[str]:
    """Paths git reports as untracked (``??``) in *worktree*, sorted; ``[]`` on a missing binary,
    non-repo directory or timeout."""
    if not git_available():
        return []
    try:
        result = _git_run(
            worktree, ["status", "--porcelain", "--untracked-files=all"], _QUERY_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return sorted(line[3:] for line in result.stdout.splitlines() if line.startswith("?? "))


def git_rev_parse(cwd: str, ref: str) -> str | None:
    """The commit *ref* names in *cwd*, else ``None`` (no repo, unknown ref, no git)."""
    if not git_available():
        return None
    try:
        result = _git_run(
            cwd, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], _QUERY_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def git_diff_names(cwd: str, base: str, head: str) -> list[str]:
    """Paths changed between `base` and `head` (``git diff --name-only``), sorted; ``[]`` on a
    missing binary, non-repo directory, unknown ref, or timeout."""
    if not git_available():
        return []
    try:
        result = _git_run(cwd, ["diff", "--name-only", base, head], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return sorted(line for line in result.stdout.splitlines() if line.strip())


def git_tracked_files(cwd: str) -> list[str]:
    """Every path ``git ls-files`` lists in `cwd`, sorted; ``[]`` on a missing binary, a
    non-repo directory or a timeout."""
    if not git_available():
        return []
    try:
        result = _git_run(cwd, ["ls-files", "-z"], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return sorted(name for name in result.stdout.split("\0") if name)


def git_blob_ids(cwd: str, paths: list[str]) -> dict[str, str]:
    """The git blob id of each of *paths* as the files stand in `cwd` (``git hash-object``); a
    path that cannot be hashed is left out, and ``{}`` on a missing binary or a timeout."""
    if not paths or not git_available():
        return {}
    ids: dict[str, str] = {}
    for rel in paths:
        if not _repo_rel_path_ok(rel):
            continue
        try:
            result = _git_run(cwd, ["hash-object", "--", rel], _QUERY_TIMEOUT)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return {}
        if result.returncode == 0 and result.stdout.strip():
            ids[rel] = result.stdout.strip()
    return ids


_PIN_TIMEOUT = 60
# Repository hooks and signing stay off: a pin is bookkeeping, and a hook is the codebase's own
# code, which docket never runs on the host outside a gate.
_PIN_CONFIG = ("-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false")


def _pin_env(cwd: str) -> dict[str, str]:
    """The environment for a pin commit: the operator's git identity, else ``docket``."""
    identity = {
        "GIT_AUTHOR_NAME": "docket",
        "GIT_AUTHOR_EMAIL": "docket@localhost",
        "GIT_COMMITTER_NAME": "docket",
        "GIT_COMMITTER_EMAIL": "docket@localhost",
    }
    return {**os.environ, **identity, **git_identity_env(Path(cwd))}


def _pin_git(
    cwd: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str] | None:
    try:
        return _git_run(cwd, list(args), _PIN_TIMEOUT, env=env, config=_PIN_CONFIG)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def git_commit_all(cwd: str, message: str) -> str | None:
    """Commit every change in `cwd`'s tree (``git add -A``, so untracked files too and
    ``.gitignore`` respected) on its current branch and return the new HEAD sha; a tree with
    nothing to commit returns HEAD unchanged. ``None`` on any failure, never raising."""
    if not git_available():
        return None
    env = _pin_env(cwd)
    added = _pin_git(cwd, "add", "-A", env=env)
    if added is None or added.returncode != 0:
        return None
    staged = _pin_git(cwd, "diff", "--cached", "--quiet", env=env)
    if staged is None or staged.returncode not in (0, 1):
        return None
    if staged.returncode == 1:
        done = _pin_git(cwd, "commit", "--no-verify", "-q", "-m", message, env=env)
        if done is None or done.returncode != 0:
            return None
    return git_head_sha(cwd)


def git_snapshot_commit(cwd: str, message: str) -> str | None:
    """Pin `cwd`'s whole tree (untracked too, ``.gitignore`` respected) in a branchless commit on
    HEAD through a temporary index, leaving index, branch and working tree untouched; HEAD itself
    when the tree is HEAD's, ``None`` on any failure."""
    head = git_head_sha(cwd)
    if head is None:
        return None
    env = _pin_env(cwd)
    index_path = _pin_git(cwd, "rev-parse", "--path-format=absolute", "--git-path", "index")
    with tempfile.TemporaryDirectory(prefix="docket-pin-") as tmp:
        index = os.path.join(tmp, "index")
        env["GIT_INDEX_FILE"] = index
        real_index = index_path.stdout.strip() if index_path and index_path.returncode == 0 else ""
        if real_index and os.path.isfile(real_index):
            # A copy keeps the stat cache, so only files that changed are hashed again.
            shutil.copyfile(real_index, index)
        else:
            read = _pin_git(cwd, "read-tree", "HEAD", env=env)
            if read is None or read.returncode != 0:
                return None
        added = _pin_git(cwd, "add", "-A", ":/", env=env)
        tree = _pin_git(cwd, "write-tree", env=env)
        if added is None or added.returncode != 0 or tree is None or tree.returncode != 0:
            return None
    tree_sha = tree.stdout.strip()
    head_tree = _pin_git(cwd, "rev-parse", "HEAD^{tree}")
    if head_tree is not None and head_tree.stdout.strip() == tree_sha:
        return head
    done = _pin_git(cwd, "commit-tree", tree_sha, "-p", head, "-m", message, env=env)
    if done is None or done.returncode != 0:
        return None
    return done.stdout.strip() or None
