"""``core/dispatch.py::_hop_message`` names the task's root and carries the repository map."""

from __future__ import annotations

from pathlib import Path

from docket.core import dispatch as _dispatch

SUBJECT = "docket.core.dispatch"

_TASK = {"description": "ship the feature"}


def _repo_with_files(root: Path) -> Path:
    import subprocess

    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x = 1\n")
    (root / "src" / "util.py").write_text("y = 2\n")
    (root / "README.md").write_text("hi\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root


class TestTaskRootAndRepositoryMap:
    """The task message names the worktree root and holds the map, ahead of prior artifacts."""

    def test_a_worktree_task_names_its_root_and_carries_the_map(self, tmp_path: Path) -> None:
        worktree = _repo_with_files(tmp_path / "wt")
        task = {**_TASK, "worktree": {"dir": str(worktree)}}

        message, comp = _dispatch._hop_message(task, "implementer", [])

        assert f"Working directory: {worktree}" in message
        assert "src/ (2 files)" in message
        assert "./ (1 file)" in message
        assert message.index("Task:") < message.index("Working directory:")
        assert comp.total_bytes == len(message.encode("utf-8"))

    def test_the_block_precedes_a_prior_artifact(self, tmp_path: Path) -> None:
        from docket.core.dispatch import HopResult

        worktree = _repo_with_files(tmp_path / "wt")
        task = {**_TASK, "worktree": {"dir": str(worktree)}}
        hop = HopResult(role="lead", member_id="p-lead", ok=True, output="the plan")

        message, _ = _dispatch._hop_message(task, "implementer", [hop])

        assert message.index("Working directory:") < message.index("--- lead output ---")

    def test_the_lead_is_never_told_a_task_worktree(self, tmp_path: Path) -> None:
        worktree = _repo_with_files(tmp_path / "wt")
        task = {**_TASK, "worktree": {"dir": str(worktree)}}

        message, _ = _dispatch._hop_message(task, "lead", [])

        assert (
            message
            == "You are the pod Lead. Decompose this task into a concrete plan for the Implementer (you never edit code yourself):\n\nship the feature"
        )

    def test_a_root_that_is_not_a_repository_gets_the_line_and_no_map(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        task = {**_TASK, "worktree": {"dir": str(plain)}}

        message, _ = _dispatch._hop_message(task, "reviewer", [])

        assert f"Working directory: {plain}" in message
        assert "Repository map" not in message

    def test_no_worktree_and_no_pod_adds_nothing(self) -> None:
        message, _ = _dispatch._hop_message(_TASK, "implementer", [])
        assert "Working directory" not in message
