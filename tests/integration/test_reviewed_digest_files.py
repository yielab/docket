"""The remembered review covers the contents of the repository files its commands name.

Real git, because the blob ids and the tracked-file listing come from it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from docket.core import pod_apply as _pod_apply
from docket.core import reviewed_repos as _reviewed
from docket.core.pod_apply import RunItem

SUBJECT = "docket.core.reviewed_repos"

GATE = RunItem("pipeline-step", "verify", "bash scripts/check.sh")
PLAIN = RunItem("pipeline-step", "echo", "echo hi")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    _git(root, "config", "user.email", "t@t.test")
    _git(root, "config", "user.name", "T")
    (root / "scripts" / "check.sh").write_text("exit 0\n")
    (root / "notes.txt").write_text("a\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    return root


def test_changing_the_script_a_command_names_asks_again(repo: Path) -> None:
    _reviewed.remember(repo, "demo", (GATE,))
    assert _reviewed.is_reviewed(repo, "demo", (GATE,))
    before = _reviewed.review_code((GATE,), repo)

    (repo / "scripts" / "check.sh").write_text("exit 0  # looser\n")

    assert not _reviewed.is_reviewed(repo, "demo", (GATE,))
    assert _reviewed.review_code((GATE,), repo) != before


def test_the_code_follows_the_content_and_returns_with_it(repo: Path) -> None:
    before = _reviewed.review_code((GATE,), repo)
    script = repo / "scripts" / "check.sh"
    script.write_text("exit 1\n")
    assert _reviewed.review_code((GATE,), repo) != before
    script.write_text("exit 0\n")
    assert _reviewed.review_code((GATE,), repo) == before


def test_a_file_no_command_names_does_not_move_the_review(repo: Path) -> None:
    _reviewed.remember(repo, "demo", (GATE, PLAIN))
    (repo / "notes.txt").write_text("b\n")
    assert _reviewed.is_reviewed(repo, "demo", (GATE, PLAIN))


def test_an_untracked_file_a_command_names_is_not_covered(repo: Path) -> None:
    item = RunItem("pipeline-step", "extra", "bash scripts/extra.sh")
    before = _reviewed.review_code((item,), repo)
    (repo / "scripts" / "extra.sh").write_text("exit 0\n")
    assert _reviewed.review_code((item,), repo) == before


def test_items_that_name_no_file_review_the_same_in_any_directory(tmp_path: Path) -> None:
    other = tmp_path / "plain"
    other.mkdir()
    assert _reviewed.review_code((PLAIN,), other) == _reviewed.review_code((PLAIN,), tmp_path)


def test_a_command_list_of_allowed_binaries_names_no_file(repo: Path) -> None:
    item = RunItem("allow-commands", "allowCommands", "scripts/check.sh")
    before = _reviewed.review_code((item,), repo)
    (repo / "scripts" / "check.sh").write_text("exit 5\n")
    assert _reviewed.review_code((item,), repo) == before


def test_pod_update_asks_again_after_the_script_its_pipeline_runs_changes(repo: Path) -> None:
    config = repo / ".docket"
    config.mkdir()
    (config / "pipeline.yaml").write_text(
        "name: p\nsteps:\n  - id: lead\n    role: lead\n  - id: check\n"
        "    run: bash scripts/check.sh\n"
    )
    review = _pod_apply.classify_directory(config)
    assert [i.runs for i in review.runs] == ["bash scripts/check.sh"]
    _reviewed.remember(repo, "demo", review.runs)
    assert _pod_apply.review_decision(repo, "demo", config, None).status == "go"

    (repo / "scripts" / "check.sh").write_text("exit 0  # looser\n")

    assert _pod_apply.review_decision(repo, "demo", config, None).status == "needs_code"
