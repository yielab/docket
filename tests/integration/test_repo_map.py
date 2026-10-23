"""``hops/workspace/repo_map.py``: the derived repository map and the task root block."""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

from docket.agent.tools.builtins import toolbox
from docket.hops.workspace import repo_map as R
from docket.kernel.home import current_home, use_home

SUBJECT = "docket.hops.workspace.repo_map"


def _repo(root: Path, files: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n")
    subprocess.run(["git", "-C", str(root), "add", "-f", "."], check=True)
    return root


class TestRenderRepoMap:
    def test_directories_with_counts_sorted_and_relative(self, tmp_path: Path) -> None:
        root = _repo(tmp_path / "r", ["a.py", "src/x.py", "src/y.py", "docs/z.md"])

        assert R.render_repo_map(str(root)) == "./ (1 file)\ndocs/ (1 file)\nsrc/ (2 files)"

    def test_the_same_tree_renders_the_same_bytes_at_two_roots(self, tmp_path: Path) -> None:
        files = ["a.py", "src/x.py", "src/deep/y.py"]
        first = _repo(tmp_path / "one", files)
        second = _repo(tmp_path / "two", files)

        assert R.render_repo_map(str(first)) == R.render_repo_map(str(second))
        assert str(tmp_path) not in R.render_repo_map(str(first))

    def test_vendored_and_generated_directories_are_skipped(self, tmp_path: Path) -> None:
        root = _repo(tmp_path / "r", ["src/a.py", "node_modules/pkg/b.js", "dist/c.js"])

        assert R.render_repo_map(str(root)) == "src/ (1 file)"

    def test_untracked_files_are_not_listed(self, tmp_path: Path) -> None:
        root = _repo(tmp_path / "r", ["src/a.py"])
        (root / "scratch").mkdir()
        (root / "scratch" / "n.py").write_text("x\n")

        assert "scratch" not in R.render_repo_map(str(root))

    def test_a_deep_tree_falls_back_to_the_deepest_depth_that_fits(self, tmp_path: Path) -> None:
        files = [f"pkg/mod{i}/sub/f.py" for i in range(30)]
        root = _repo(tmp_path / "r", files)
        with use_home(dataclasses.replace(current_home(), repo_map_max_chars=200)):
            rendered = R.render_repo_map(str(root))

            assert rendered == "pkg/ (30 files)"

    def test_a_wide_tree_is_cut_at_the_cap_with_a_marker(self, tmp_path: Path) -> None:
        root = _repo(tmp_path / "r", [f"dir{i:03d}/f.py" for i in range(80)])
        with use_home(dataclasses.replace(current_home(), repo_map_max_chars=300)):
            rendered = R.render_repo_map(str(root))

            assert len(rendered) <= 300 + len("... 80 more directories")
            assert rendered.splitlines()[-1].startswith("... ") and "more directories" in rendered

    def test_a_directory_that_is_not_a_repository_has_no_map(self, tmp_path: Path) -> None:
        (tmp_path / "plain").mkdir()
        assert R.render_repo_map(str(tmp_path / "plain")) == ""

    def test_the_skip_list_matches_the_tools(self) -> None:
        assert R.SKIPPED_DIRS == toolbox.SKIPPED_DIRS


class TestTaskRootBlock:
    def test_a_worktree_is_named_with_its_map(self, tmp_path: Path) -> None:
        root = _repo(tmp_path / "wt", ["src/a.py"])

        block = R.task_root_block(str(root), "", "implementer")

        assert block.startswith(f"Working directory: {root}\n")
        assert block.endswith("src/ (1 file)")

    def test_nothing_resolves_to_no_block(self) -> None:
        assert R.task_root_block("", "", "implementer") == ""
        assert R.task_root_block("", "no-such-pod", "implementer") == ""
