"""Real git evidence helpers (`git_head_sha`, `git_merge_base`, `git_diff_stat`).

Each degrades to `None` rather than raising -- the same convention `git_current_branch`/
`git_changed_files` already use -- on a missing binary, a non-repository directory, or an
unresolvable ref. `subprocess.run` is monkeypatched throughout, mirroring
`tests/integration/test_system_adapter.py`'s pattern; no real git process ever runs here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from docket.platform import git as _git
from docket.sandbox import landlock as _landlock

SUBJECT = "docket.platform.git"


class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


# ── git_new_files_text ────────────────────────────────────────────────────────


class TestGitNewFilesText:
    def _changes(self, monkeypatch: pytest.MonkeyPatch, *paths: Path) -> None:
        monkeypatch.setattr(
            _git, "git_worktree_changes", lambda _cwd: [("??", str(p)) for p in paths]
        )

    def test_gives_each_new_file_under_a_header_in_path_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "b.md").write_text("second\n")
        (tmp_path / "a.md").write_text("first")
        self._changes(monkeypatch, tmp_path / "b.md", tmp_path / "a.md")
        text = _git.git_new_files_text(str(tmp_path), 1000)
        assert text == "--- new file: a.md\nfirst\n--- new file: b.md\nsecond\n"

    def test_a_symlink_and_a_binary_file_show_a_note_not_their_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP-SECRET")
        link = tmp_path / "link"
        link.symlink_to(secret)
        blob = tmp_path / "blob.bin"
        blob.write_bytes(b"\x00\x01TOP-SECRET")
        self._changes(monkeypatch, link, blob)
        text = _git.git_new_files_text(str(tmp_path), 1000)
        assert "TOP-SECRET" not in text
        assert "not a regular file" in text and "binary file" in text

    def test_reading_stops_once_the_limit_is_gathered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("a", "b", "c"):
            (tmp_path / name).write_text(name * 100)
        self._changes(monkeypatch, tmp_path / "a", tmp_path / "b", tmp_path / "c")
        text = _git.git_new_files_text(str(tmp_path), 50)
        assert "--- new file: a" in text and "--- new file: c" not in text

    def test_no_new_file_gives_an_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._changes(monkeypatch)
        assert _git.git_new_files_text("/nowhere", 10) == ""


# ── git_head_sha ──────────────────────────────────────────────────────────────


class TestGitHeadSha:
    def test_returns_stripped_sha_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        sha = "a" * 40
        monkeypatch.setattr(
            _git.subprocess,
            "run",
            lambda *a, **k: _FakeCompleted(returncode=0, stdout=sha + "\n"),
        )
        assert _git.git_head_sha("/tmp/repo") == sha

    def test_none_when_not_a_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        monkeypatch.setattr(_git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
        assert _git.git_head_sha("/tmp/notrepo") is None

    def test_none_when_git_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: False)

        def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
            raise AssertionError("must not shell out without git")

        monkeypatch.setattr(_git.subprocess, "run", boom)
        assert _git.git_head_sha("/tmp/repo") is None

    def test_none_on_missing_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)

        def raise_fnf(*_a: Any, **_k: Any) -> _FakeCompleted:
            raise FileNotFoundError

        monkeypatch.setattr(_git.subprocess, "run", raise_fnf)
        assert _git.git_head_sha("/tmp/repo") is None

    def test_none_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)

        def raise_timeout(*_a: Any, **_k: Any) -> _FakeCompleted:
            raise _git.subprocess.TimeoutExpired(cmd="git", timeout=5)

        monkeypatch.setattr(_git.subprocess, "run", raise_timeout)
        assert _git.git_head_sha("/tmp/repo") is None


# ── git_merge_base ────────────────────────────────────────────────────────────


class TestGitMergeBase:
    def test_returns_stripped_sha_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        sha = "b" * 40
        monkeypatch.setattr(
            _git.subprocess,
            "run",
            lambda *a, **k: _FakeCompleted(returncode=0, stdout=sha + "\n"),
        )
        assert _git.git_merge_base("/tmp/repo", "main") == sha

    def test_none_for_unknown_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        monkeypatch.setattr(_git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
        assert _git.git_merge_base("/tmp/repo", "no-such-branch") is None

    def test_none_when_git_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: False)

        def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
            raise AssertionError("must not shell out without git")

        monkeypatch.setattr(_git.subprocess, "run", boom)
        assert _git.git_merge_base("/tmp/repo", "main") is None


# ── git_diff_stat ─────────────────────────────────────────────────────────────


class TestGitDiffStat:
    def test_parses_files_insertions_and_deletions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        summary = " 2 files changed, 10 insertions(+), 3 deletions(-)\n"
        monkeypatch.setattr(
            _git.subprocess,
            "run",
            lambda *a, **k: _FakeCompleted(returncode=0, stdout=summary),
        )
        assert _git.git_diff_stat("/tmp/repo", "abc123") == {
            "files": 2,
            "insertions": 10,
            "deletions": 3,
        }

    def test_singular_wording_still_parses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        summary = " 1 file changed, 1 insertion(+)\n"
        monkeypatch.setattr(
            _git.subprocess,
            "run",
            lambda *a, **k: _FakeCompleted(returncode=0, stdout=summary),
        )
        assert _git.git_diff_stat("/tmp/repo", "abc123") == {
            "files": 1,
            "insertions": 1,
            "deletions": 0,
        }

    def test_empty_summary_reports_all_zero_not_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        monkeypatch.setattr(
            _git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="")
        )
        assert _git.git_diff_stat("/tmp/repo", "abc123") == {
            "files": 0,
            "insertions": 0,
            "deletions": 0,
        }

    def test_none_for_unresolvable_base(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        monkeypatch.setattr(_git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
        assert _git.git_diff_stat("/tmp/repo", "no-such-ref") is None

    def test_none_when_not_a_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        monkeypatch.setattr(_git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
        assert _git.git_diff_stat("/tmp/notrepo", "HEAD") is None

    def test_none_when_git_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: False)

        def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
            raise AssertionError("must not shell out without git")

        monkeypatch.setattr(_git.subprocess, "run", boom)
        assert _git.git_diff_stat("/tmp/repo", "HEAD") is None


class TestGitTrackedFilesAndBlobIds:
    def test_tracked_files_are_the_nul_separated_listing_sorted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        listing = "scripts/check.sh\0README.md\0"
        monkeypatch.setattr(_git.subprocess, "run", lambda *a, **k: _FakeCompleted(stdout=listing))
        assert _git.git_tracked_files("/tmp/repo") == ["README.md", "scripts/check.sh"]

    def test_tracked_files_are_empty_outside_a_repo_or_without_git(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        monkeypatch.setattr(_git.subprocess, "run", lambda *a, **k: _FakeCompleted(128))
        assert _git.git_tracked_files("/tmp/notrepo") == []
        monkeypatch.setattr(_git, "git_available", lambda: False)
        assert _git.git_tracked_files("/tmp/repo") == []

    def test_blob_ids_skip_unsafe_paths_and_failed_hashes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        answers = {"a.sh": _FakeCompleted(stdout="abc123\n"), "gone.sh": _FakeCompleted(128)}
        monkeypatch.setattr(_git.subprocess, "run", lambda argv, **k: answers[argv[-1]])
        got = _git.git_blob_ids("/tmp/repo", ["a.sh", "gone.sh", "../x", "/etc/passwd"])
        assert got == {"a.sh": "abc123"}

    def test_blob_ids_are_empty_without_paths_or_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: False)
        assert _git.git_blob_ids("/tmp/repo", ["a.sh"]) == {}
        monkeypatch.setattr(_git, "git_available", lambda: True)
        assert _git.git_blob_ids("/tmp/repo", []) == {}


class TestTrustedWorktree:
    def test_git_dirs_answers_from_the_record(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        gitdir, common = tmp_path / "c" / "worktrees" / "wt", tmp_path / "c"
        _git.trust_worktree(str(wt), str(gitdir), str(common))
        assert _landlock.git_dirs(wt) == [gitdir.resolve(), common.resolve()]

    def test_host_git_names_the_recorded_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wt = tmp_path / "wt2"
        wt.mkdir()
        seen: dict[str, Any] = {}

        def fake(argv: list[str], **kw: Any) -> _FakeCompleted:
            seen.update(kw)
            return _FakeCompleted(0, "main\n")

        monkeypatch.setattr(_git.subprocess, "run", fake)
        _git.trust_worktree(str(wt), str(tmp_path / "g"), str(tmp_path / "c"))
        _git._git_run(str(wt), ["status"], 5)
        env = seen["env"]
        assert env["GIT_DIR"] == str(tmp_path / "g") and env["GIT_COMMON_DIR"] == str(
            tmp_path / "c"
        )
        assert env["GIT_WORK_TREE"] == str(wt.resolve())

    def test_a_poisoned_worktree_config_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wt, gitdir, common = tmp_path / "wt3", tmp_path / "g3", tmp_path / "c3"
        for d in (wt, gitdir, common):
            d.mkdir()
        (gitdir / "config.worktree").write_text("[core]\n")
        (common / "config").write_text("[extensions]\n\tworktreeConfig = true\n")
        ran: list[object] = []
        monkeypatch.setattr(_git.subprocess, "run", lambda *a, **k: ran.append(a))
        _git.trust_worktree(str(wt), str(gitdir), str(common))
        out = _git._git_run(str(wt), ["status"], 5)
        assert out.returncode == 1 and ran == []


# ── git_worktree_add ──────────────────────────────────────────────────────────


class TestGitWorktreeAddStartPoint:
    def _capture(self, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        argvs: list[list[str]] = []

        def _run(argv: list[str], *a: Any, **k: Any) -> _FakeCompleted:
            argvs.append(argv)
            return _FakeCompleted(returncode=0)

        monkeypatch.setattr(_git, "git_available", lambda: True)
        monkeypatch.setattr(_git.subprocess, "run", _run)
        return argvs

    def test_start_point_is_the_last_argument(self, monkeypatch: pytest.MonkeyPatch) -> None:
        argvs = self._capture(monkeypatch)

        assert _git.git_worktree_add("/r", "/w", "br", start_point="prev") == (True, "")

        assert argvs == [["git", "-C", "/r", "worktree", "add", "-b", "br", "/w", "prev"]]

    def test_no_start_point_keeps_the_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        argvs = self._capture(monkeypatch)

        _git.git_worktree_add("/r", "/w", "br")

        assert argvs == [["git", "-C", "/r", "worktree", "add", "-b", "br", "/w"]]

    def test_a_start_point_that_looks_like_an_option_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        argvs = self._capture(monkeypatch)

        ok, reason = _git.git_worktree_add("/r", "/w", "br", start_point="--detach")

        assert not ok
        assert "--detach" in reason
        assert argvs == []


class TestGitDiffRange:
    def test_diffs_base_dot_dot_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        seen: list[list[str]] = []

        def _run(argv: list[str], **kwargs: Any) -> _FakeCompleted:
            seen.append(argv)
            return _FakeCompleted(returncode=0, stdout="diff --git a/x b/x\n")

        monkeypatch.setattr(_git.subprocess, "run", _run)
        assert _git.git_diff_range("/tmp/repo", "abc", "br") == "diff --git a/x b/x\n"
        assert seen[0][-2:] == ["diff", "abc..br"]

    def test_a_long_patch_is_cut_with_a_marker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        big = "x" * (_git.DIFF_MAX_CHARS + 10)
        monkeypatch.setattr(
            _git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout=big)
        )
        patch = _git.git_diff_range("/tmp/repo", "a", "b")
        assert patch is not None
        assert patch.startswith("x" * _git.DIFF_MAX_CHARS)
        assert patch.endswith("characters]\n") and len(patch) < len(big) + 80

    def test_none_on_failure_or_without_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        monkeypatch.setattr(_git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
        assert _git.git_diff_range("/tmp/repo", "a", "b") is None
        monkeypatch.setattr(_git, "git_available", lambda: False)
        assert _git.git_diff_range("/tmp/repo", "a", "b") is None


class TestGitUntracked:
    def test_lists_only_question_mark_lines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        out = " M tracked.py\n?? b/new.txt\n?? a.txt\nA  added.py\n"
        monkeypatch.setattr(
            _git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout=out)
        )
        assert _git.git_untracked("/tmp/wt") == ["a.txt", "b/new.txt"]

    def test_empty_when_not_a_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_git, "git_available", lambda: True)
        monkeypatch.setattr(_git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
        assert _git.git_untracked("/tmp/nowhere") == []


class TestGitInfoExclude:
    """``git_info_exclude`` appends each pattern once to the common dir's ``info/exclude``."""

    def test_appends_missing_patterns_once(self, tmp_path: Path) -> None:
        exclude = tmp_path / "info" / "exclude"
        _git.git_info_exclude(str(tmp_path), ("/node_modules",))
        _git.git_info_exclude(str(tmp_path), ("/node_modules", "/.venv"))
        assert exclude.read_text().splitlines() == ["/node_modules", "/.venv"]

    def test_keeps_what_was_already_there(self, tmp_path: Path) -> None:
        (tmp_path / "info").mkdir()
        (tmp_path / "info" / "exclude").write_text("# keep\n")
        _git.git_info_exclude(str(tmp_path), ("/node_modules",))
        assert (tmp_path / "info" / "exclude").read_text() == "# keep\n/node_modules\n"

    def test_an_unwritable_common_dir_is_ignored(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x")
        _git.git_info_exclude(str(blocker), ("/node_modules",))
