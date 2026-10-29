"""``teams/workspace/repo_map.py``: the derived repository map and the task root block."""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

from docket.agent.tools.builtins import toolbox
from docket.kernel.home import current_home, use_home
from docket.teams.workspace import repo_map as R

SUBJECT = "docket.teams.workspace.repo_map"


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


class TestCappedMapAndRoot:
    def test_the_capped_map_has_a_header_and_no_path(self, tmp_path: Path) -> None:
        root = _repo(tmp_path / "wt", ["src/a.py"])

        block = R.capped_map(str(root))

        assert block == "Repository map (tracked files by directory):\nsrc/ (1 file)"
        assert str(root) not in block

    def test_a_directory_with_no_tracked_file_has_no_capped_map(self, tmp_path: Path) -> None:
        assert R.capped_map(str(tmp_path)) == ""

    def test_a_task_worktree_is_the_root_before_the_pod_codebase(self) -> None:
        assert R.resolve_root("/some/worktree", "", "implementer") == "/some/worktree"

    def test_nothing_resolves_to_no_root(self) -> None:
        assert R.resolve_root("", "", "implementer") == ""
        assert R.resolve_root("", "no-such-pod", "implementer") == ""


class TestBoundedMap:
    def _big(self, tmp_path: Path) -> Path:
        files = [f"pkg{i % 25:02d}/mod{i}.py" for i in range(450)]
        files += ["src/app/x.py", "src/app/y.py", "src/app/util/z.py", "src/lib/q.py", "README.md"]
        return _repo(tmp_path / "big", files)

    def test_a_named_file_lists_its_directory_and_not_the_tree(self, tmp_path: Path) -> None:
        root = self._big(tmp_path)

        text = R.bounded_map(str(root), "", "change src/app/x.py to take a flag")

        lines = text.splitlines()
        assert lines[0] == "Repository map (the paths the brief names, with their direct entries):"
        assert lines[1:-1] == ["src/app/util/", "src/app/x.py", "src/app/y.py"]
        assert "glob" in lines[-1]
        assert "pkg00" not in text and "src/lib" not in text

    def test_a_named_directory_lists_its_direct_entries(self, tmp_path: Path) -> None:
        root = self._big(tmp_path)

        text = R.bounded_map(
            str(root), "", "everything under `src/app/`, then path:src/lib/q.py#L1-4."
        )

        assert text.splitlines()[1:-1] == [
            "src/app/util/",
            "src/app/x.py",
            "src/app/y.py",
            "src/lib/q.py",
        ]

    def test_a_brief_that_names_nothing_lists_the_root(self, tmp_path: Path) -> None:
        root = self._big(tmp_path)

        text = R.bounded_map(str(root), "", "make it faster")

        assert "README.md" in text.splitlines() and "src/" in text.splitlines()
        assert "pkg00/mod0.py" not in text

    def test_the_map_is_cut_at_the_cap_before_the_glob_line(self, tmp_path: Path) -> None:
        root = self._big(tmp_path)
        with use_home(dataclasses.replace(current_home(), repo_map_max_chars=120)):
            text = R.bounded_map(str(root), "", "see pkg03")

        lines = text.splitlines()
        assert "more entries" in lines[-2] and "glob" in lines[-1]

    def test_the_base_commit_not_the_index_is_listed(self, tmp_path: Path) -> None:
        root = _repo(tmp_path / "r", ["src/a.py"])
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-qm",
                "x",
            ],
            check=True,
        )
        base = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        (root / "src" / "b.py").write_text("x\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)

        assert "src/b.py" not in R.bounded_map(str(root), base, "src/a.py")
        assert "src/b.py" in R.bounded_map(str(root), "", "src/a.py")
