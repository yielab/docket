"""The remembered operator review of a repository's commands."""

from __future__ import annotations

import json
from pathlib import Path

import docket.config as _cfg
from docket.core import reviewed_repos as _reviewed
from docket.core.audit import read_audit
from docket.core.pod_apply import RunItem

SUBJECT = "docket.core.reviewed_repos"

A = RunItem("pipeline-step", "migrate", "sh scripts/migrate.sh")
B = RunItem("mcp-server", "db", "npx -y @acme/db-mcp@1.4.2")


def test_the_code_is_sixteen_hex_and_independent_of_item_order() -> None:
    """The same items in any order give the same 16-hex code; a changed command changes it."""
    code = _reviewed.review_code((A, B))
    assert len(code) == 16 and int(code, 16) >= 0
    assert _reviewed.review_code((B, A)) == code
    assert _reviewed.review_code((A, RunItem(B.kind, B.name, "npx evil"))) != code


def test_remember_then_lookup_matches_only_the_same_items(tmp_path: Path) -> None:
    """A remembered review matches its exact items and nothing else, per repository root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _reviewed.lookup(repo) is None
    _reviewed.remember(repo, (A, B))
    assert _reviewed.is_reviewed(repo, (B, A))
    assert not _reviewed.is_reviewed(repo, (A,))
    assert not _reviewed.is_reviewed(tmp_path / "other", (A, B))
    found = _reviewed.lookup(repo)
    assert found is not None and set(found.items) == {A, B}


def test_remember_writes_a_private_file_and_audits_without_content(tmp_path: Path) -> None:
    """The store file is 0600 and the repo.allow entry names the repo, code and count only."""
    repo = tmp_path / "repo"
    repo.mkdir()
    code = _reviewed.remember(repo, (A,))
    assert oct(_cfg.REVIEWED_REPOS_FILE.stat().st_mode & 0o777) == "0o600"
    assert json.loads(_cfg.REVIEWED_REPOS_FILE.read_text())["repos"]
    entry = [e for e in read_audit() if e.get("action") == "repo.allow"][-1]
    assert f"code={code}" in entry["detail"] and "items=1" in entry["detail"]
    assert "migrate.sh" not in entry["detail"]
