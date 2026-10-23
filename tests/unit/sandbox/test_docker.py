"""Real git evidence helpers (`git_head_sha`, `git_merge_base`, `git_diff_stat`).

Each degrades to `None` rather than raising -- the same convention `git_current_branch`/
`git_changed_files` already use -- on a missing binary, a non-repository directory, or an
unresolvable ref. `subprocess.run` is monkeypatched throughout, mirroring
`tests/integration/test_system_adapter.py`'s pattern; no real git process ever runs here.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docket.sandbox import docker as _docker_mod
from docket.sandbox import landlock as _landlock

SUBJECT = "docket.sandbox.docker"


class TestRefNarrowingOnDocker:
    def _linked(self, tmp_path: Path, head: str) -> tuple[Path, Path, Path]:
        wt, common = tmp_path / "wt", tmp_path / "main" / ".git"
        gitdir = common / "worktrees" / "wt"
        for d in (wt, gitdir, common / "objects", common / "refs", common / "logs" / "refs"):
            d.mkdir(parents=True)
        (gitdir / "HEAD").write_text(head)
        return wt, common, gitdir

    def _docker(self, root: Path, dirs: list[Path]) -> list[str]:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(_landlock, "git_dirs", lambda r: dirs)
            mp.setattr(os, "getuid", lambda: 1000)
            mp.setattr(os, "getgid", lambda: 1000)
            return _docker_mod._docker_prefix("c", (root,), None, True)

    def _mounts(self, argv: list[str]) -> list[str]:
        return [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]

    def test_docker_binds_the_refs_read_only_then_reopens_the_task_branch_dirs(
        self, tmp_path: Path
    ) -> None:
        wt, common, gitdir = self._linked(tmp_path, "ref: refs/heads/docket/pod/wt\n")
        mounts = self._mounts(self._docker(wt, [gitdir, common]))
        refs = f"{common / 'refs'}:{common / 'refs'}:ro"
        branch = common / "refs" / "heads" / "docket" / "pod"
        reflog = common / "logs" / "refs" / "heads" / "docket" / "pod"
        assert refs in mounts
        assert f"{common / 'logs' / 'refs'}:{common / 'logs' / 'refs'}:ro" in mounts
        assert f"{common / 'packed-refs'}:{common / 'packed-refs'}:ro" in mounts
        assert mounts.index(f"{branch}:{branch}") > mounts.index(refs)
        assert mounts.index(f"{reflog}:{reflog}") > mounts.index(refs)

    def test_a_linked_worktree_that_is_not_a_task_reopens_nothing(self, tmp_path: Path) -> None:
        wt, common, gitdir = self._linked(tmp_path, "ref: refs/heads/feature\n")
        mounts = self._mounts(self._docker(wt, [gitdir, common]))
        assert f"{common / 'refs'}:{common / 'refs'}:ro" in mounts
        assert not [m for m in mounts if "heads" in m]

    def test_a_main_checkout_keeps_its_refs_writable(self, tmp_path: Path) -> None:
        common = tmp_path / ".git"
        (common / "refs").mkdir(parents=True)
        mounts = self._mounts(self._docker(tmp_path, [common]))
        assert not [m for m in mounts if m.endswith(":ro") and "refs" in m]
