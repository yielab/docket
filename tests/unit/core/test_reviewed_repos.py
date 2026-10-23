"""The remembered operator review of a repository's commands."""

from __future__ import annotations

import json
from pathlib import Path

from docket.core import reviewed_repos as _reviewed
from docket.core.audit import read_audit
from docket.core.pod_apply import RunItem
from docket.kernel.home import current_home

SUBJECT = "docket.core.reviewed_repos"

A = RunItem("pipeline-step", "migrate", "sh scripts/migrate.sh")
B = RunItem("mcp-server", "db", "npx -y @acme/db-mcp@1.4.2")


def test_the_code_is_sixteen_hex_and_independent_of_item_order(tmp_path: Path) -> None:
    """The same items in any order give the same 16-hex code; a changed command changes it."""
    code = _reviewed.review_code((A, B), tmp_path)
    assert len(code) == 16 and int(code, 16) >= 0
    assert _reviewed.review_code((B, A), tmp_path) == code
    assert _reviewed.review_code((A, RunItem(B.kind, B.name, "npx evil")), tmp_path) != code


def test_remember_then_lookup_matches_only_the_same_items(tmp_path: Path) -> None:
    """A remembered review matches its exact items and nothing else, per repository root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _reviewed.lookup(repo, "a") is None
    _reviewed.remember(repo, "a", (A, B))
    assert _reviewed.is_reviewed(repo, "a", (B, A))
    assert not _reviewed.is_reviewed(repo, "a", (A,))
    assert not _reviewed.is_reviewed(tmp_path / "other", "a", (A, B))
    found = _reviewed.lookup(repo, "a")
    assert found is not None and set(found.items) == {A, B}


def test_two_pods_on_one_codebase_keep_their_approvals(tmp_path: Path) -> None:
    """A second pod's approval adds to the store; the first pod's set stays approved."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _reviewed.remember(repo, "a", (A,))
    _reviewed.remember(repo, "b", (B,))
    assert _reviewed.is_reviewed(repo, "a", (A,))
    assert _reviewed.is_reviewed(repo, "b", (B,))
    assert not _reviewed.is_reviewed(repo, "b", (A,))


def test_a_pod_keeps_every_set_it_approved_and_its_latest_is_the_last(tmp_path: Path) -> None:
    """Returning to an earlier approved set is still approved; lookup is the latest approval."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _reviewed.remember(repo, "a", (A,))
    _reviewed.remember(repo, "a", (A, B))
    assert _reviewed.is_reviewed(repo, "a", (A,))
    assert _reviewed.is_reviewed(repo, "a", (A, B))
    found = _reviewed.lookup(repo, "a")
    assert found is not None and set(found.items) == {A, B}
    _reviewed.remember(repo, "a", (A,))
    assert len(_reviewed.approvals(repo, "a")) == 2


def test_an_approved_set_is_not_duplicated(tmp_path: Path) -> None:
    """Approving the same items twice leaves one entry for the pod."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _reviewed.remember(repo, "a", (A,))
    _reviewed.remember(repo, "a", (A,))
    assert len(_reviewed.approvals(repo, "a")) == 1


def test_the_file_is_keyed_by_codebase_then_pod(tmp_path: Path) -> None:
    """The shape on disk is repos -> root -> pod -> list of approvals."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _reviewed.remember(repo, "a", (A,))
    data = json.loads(current_home().reviewed_repos_file.read_text())
    (root,) = data["repos"].values()
    assert list(root) == ["a"] and len(root["a"]) == 1
    assert set(root["a"][0]) == {"digest", "code", "date", "items"}


def test_the_older_one_entry_shape_is_not_read(tmp_path: Path) -> None:
    """A file written with one entry per codebase is not found, so its operator is asked again."""
    repo = tmp_path / "repo"
    repo.mkdir()
    old = {
        "repos": {
            str(repo.resolve()): {
                "digest": _reviewed._digest((A,), repo),
                "code": _reviewed.review_code((A,), repo),
                "date": "2026-10-01",
                "items": [{"kind": A.kind, "name": A.name, "runs": A.runs}],
            }
        }
    }
    current_home().reviewed_repos_file.parent.mkdir(parents=True, exist_ok=True)
    current_home().reviewed_repos_file.write_text(json.dumps(old))
    assert _reviewed.lookup(repo, "a") is None
    assert not _reviewed.is_reviewed(repo, "a", (A,))
    assert not _reviewed.is_reviewed(repo, "items", (A,))


def test_remember_writes_a_private_file_and_audits_without_content(tmp_path: Path) -> None:
    """The store file is 0600 and the repo.allow entry names the repo, code and count only."""
    repo = tmp_path / "repo"
    repo.mkdir()
    code = _reviewed.remember(repo, "a", (A,))
    assert oct(current_home().reviewed_repos_file.stat().st_mode & 0o777) == "0o600"
    assert json.loads(current_home().reviewed_repos_file.read_text())["repos"]
    entry = [e for e in read_audit() if e.get("action") == "repo.allow"][-1]
    assert f"code={code}" in entry["detail"] and "items=1" in entry["detail"]
    assert "pod=a" in entry["detail"]
    assert "migrate.sh" not in entry["detail"]
