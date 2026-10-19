"""The operator's remembered OK for what a repository's ``.docket/`` runs on this machine."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket.core.audit import audit_log
from docket.core.pod_apply import RunItem
from docket.edges import store

CODE_LENGTH = 16


@dataclass(frozen=True)
class ReviewedRepo:
    """One remembered repository: the full ``digest``, its shown ``code``, date and items."""

    root: str
    digest: str
    code: str
    date: str
    items: tuple[RunItem, ...]


def _digest(items: tuple[RunItem, ...]) -> str:
    canonical = sorted((i.kind, i.name, i.runs) for i in items)
    return hashlib.sha256(json.dumps(canonical).encode("utf-8")).hexdigest()


def review_code(items: tuple[RunItem, ...]) -> str:
    """The short code shown for exactly these items, independent of their order."""
    return _digest(items)[:CODE_LENGTH]


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
    repos = store.read_json(_cfg.REVIEWED_REPOS_FILE).get("repos", {})
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
    digest = _digest(items)
    return any(found.digest == digest for found in approvals(repo_root, project))


def remember(repo_root: Path, project: str, items: tuple[RunItem, ...]) -> str:
    """Record *project*'s OK for these items and audit ``repo.allow``; returns the code.
    A set already approved moves to the latest position instead of being repeated."""
    code = review_code(items)
    digest = _digest(items)
    entry: dict[str, Any] = {
        "digest": digest,
        "code": code,
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
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

    store.read_modify_write(_cfg.REVIEWED_REPOS_FILE, _write)
    audit_log(
        "repo.allow",
        f"repo={_key(repo_root)} pod={project} code={code} items={len(items)}",
    )
    return code
