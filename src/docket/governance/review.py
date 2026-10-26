"""The operator's remembered OK for what a repository's ``.docket/`` runs on this machine."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.governance.audit import audit_log
from docket.kernel import clock as _clock
from docket.kernel import protected_paths as _protected
from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.platform import read_json, read_modify_write

CODE_LENGTH = 16
_NAMES_NO_FILE = frozenset({"allow-commands", "network", "role-loosens"})


@dataclass(frozen=True)
class ReviewedRepo:
    """One remembered repository: the full ``digest``, its shown ``code``, date and items."""

    root: str
    digest: str
    code: str
    date: str
    items: tuple[RunItem, ...]


def _named_file_ids(items: tuple[RunItem, ...], repo_root: Path) -> list[tuple[str, str]]:
    """``(path, blob id)`` of each tracked file of *repo_root* that a command in *items* names."""
    commands = [i.runs for i in items if i.kind not in _NAMES_NO_FILE]
    if not commands:
        return []
    root = str(repo_root)
    names = _protected.command_files(commands, frozenset(_git.git_tracked_files(root)))
    return sorted(_git.git_blob_ids(root, sorted(names)).items())


def _digest(items: tuple[RunItem, ...], repo_root: Path) -> str:
    canonical = [
        sorted((i.kind, i.name, i.runs) for i in items),
        _named_file_ids(items, repo_root),
    ]
    return hashlib.sha256(json.dumps(canonical).encode("utf-8")).hexdigest()


def review_code(items: tuple[RunItem, ...], repo_root: Path) -> str:
    """The short code shown for exactly these items and the files their commands name in
    *repo_root*, independent of the items' order."""
    return _digest(items, repo_root)[:CODE_LENGTH]


def _key(repo_root: Path) -> str:
    return str(repo_root.resolve())


def _rows(by_pod: dict[str, Any], project: str) -> list[dict[str, Any]]:
    rows = by_pod.get(project)
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("digest"), str)]


def _is_one_entry_shape(by_pod: Any) -> bool:
    """One entry per codebase (no pod keys) is not read as pods; it counts as nothing."""
    return not isinstance(by_pod, dict) or isinstance(by_pod.get("digest"), str)


def approvals(repo_root: Path, project: str) -> list[ReviewedRepo]:
    """Every item set *project* approved for *repo_root*, oldest first."""
    repos = read_json(current_home().reviewed_repos_file).get("repos", {})
    by_pod = repos.get(_key(repo_root))
    if _is_one_entry_shape(by_pod):
        return []
    key = _key(repo_root)
    return [
        ReviewedRepo(
            key,
            str(row["digest"]),
            str(row["code"]),
            str(row["date"]),
            tuple(RunItem(str(i["kind"]), str(i["name"]), str(i["runs"])) for i in row["items"]),
        )
        for row in _rows(by_pod, project)
    ]


def lookup(repo_root: Path, project: str) -> ReviewedRepo | None:
    """The latest set *project* approved for *repo_root*, or None."""
    found = approvals(repo_root, project)
    return found[-1] if found else None


def is_reviewed(repo_root: Path, project: str, items: tuple[RunItem, ...]) -> bool:
    """Whether *project* approved exactly these items for *repo_root* at some point."""
    digest = _digest(items, repo_root)
    return any(found.digest == digest for found in approvals(repo_root, project))


def remember(repo_root: Path, project: str, items: tuple[RunItem, ...]) -> str:
    """Record *project*'s OK for these items and audit ``repo.allow``; returns the code.
    A set already approved moves to the latest position instead of being repeated."""
    code = review_code(items, repo_root)
    digest = _digest(items, repo_root)
    entry: dict[str, Any] = {
        "digest": digest,
        "code": code,
        "date": _clock.today_iso(),
        "items": [{"kind": i.kind, "name": i.name, "runs": i.runs} for i in items],
    }

    def _write(current: dict[str, Any]) -> dict[str, Any]:
        repos = dict(current.get("repos", {}))
        key = _key(repo_root)
        by_pod = repos.get(key) or {}
        kept: dict[str, Any] = {} if _is_one_entry_shape(by_pod) else dict(by_pod)
        rows = [r for r in _rows(kept, project) if r["digest"] != digest]
        kept[project] = [*rows, entry]
        repos[key] = kept
        return {"repos": repos}

    read_modify_write(current_home().reviewed_repos_file, _write)
    audit_log(
        "repo.allow",
        f"repo={_key(repo_root)} pod={project} code={code} items={len(items)}",
    )
    return code


@dataclass(frozen=True)
class RunItem:
    """One thing a directory would run on this machine: its ``kind``, ``name`` and the
    exact ``runs`` text the operator is asked to allow."""

    kind: str
    name: str
    runs: str
