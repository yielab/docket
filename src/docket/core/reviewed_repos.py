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

CODE_LENGTH = 6


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


def lookup(repo_root: Path) -> ReviewedRepo | None:
    """The remembered review for *repo_root*, or None."""
    entry = store.read_json(_cfg.REVIEWED_REPOS_FILE).get("repos", {}).get(_key(repo_root))
    if not isinstance(entry, dict):
        return None
    items = tuple(RunItem(str(i["kind"]), str(i["name"]), str(i["runs"])) for i in entry["items"])
    return ReviewedRepo(
        _key(repo_root), str(entry["digest"]), str(entry["code"]), str(entry["date"]), items
    )


def is_reviewed(repo_root: Path, items: tuple[RunItem, ...]) -> bool:
    """Whether *repo_root* was allowed with exactly these items."""
    found = lookup(repo_root)
    return found is not None and found.digest == _digest(items)


def remember(repo_root: Path, items: tuple[RunItem, ...]) -> str:
    """Record the operator's OK for these items and audit ``repo.allow``; returns the code."""
    code = review_code(items)
    entry: dict[str, Any] = {
        "digest": _digest(items),
        "code": code,
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "items": [{"kind": i.kind, "name": i.name, "runs": i.runs} for i in items],
    }

    def _write(current: dict[str, Any]) -> dict[str, Any]:
        repos = dict(current.get("repos", {}))
        repos[_key(repo_root)] = entry
        return {"repos": repos}

    store.read_modify_write(_cfg.REVIEWED_REPOS_FILE, _write)
    audit_log("repo.allow", f"repo={_key(repo_root)} code={code} items={len(items)}")
    return code
