"""The real `files_changed`/`diff_ref` producer for an Implementer hop's artifact.

`HandoffArtifact.files_changed`/`.diff_ref` are real, structurally-typed fields
(`kernel/handoff.py`'s module docstring documents the seam). Covers: TestHopDiffProbeUnit
(`_hop_diff_probe` in isolation, with `edges/adapters/system.py`'s git calls
monkeypatched out); TestDispatchPopulatesRealDiff (end to end through a real `dispatch_pod`
claim against a real git repo: the hop's artifact carries the actual changed file and the
task worktree's branch); and TestDegradePaths (the three ways this must degrade to an empty,
never exceptional, artifact -- a `workdir` pod, a non-git `codebase`, and no `git` binary --
each pinned end to end through `dispatch_task` so a call-site change can't reintroduce a crash).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.support import home as _support_home
from tests.support.fakes import FakeGit
from tests.support.pods import build_pod

from docket.hops.application import executor as _executor
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, use_home
from docket.tasks.application import queue as _queue
from docket.teams import fleet as _fleet
from docket.teams.workspace import worktree as _worktree

_hermetic = _support_home.hermetic_2

SUBJECT = "docket.teams.workspace.worktree"

# ── TestHopDiffProbeUnit: _hop_diff_probe in isolation ──────


class TestHopDiffProbeUnit:
    def test_non_implementer_role_on_a_non_repo_gets_nothing(
        self, monkeypatch: pytest.MonkeyPatch, fake_git: FakeGit
    ) -> None:
        monkeypatch.setattr(_fleet, "meta_get", lambda _id, _field, default="": default)
        fake_git.git_available = lambda: True
        fake_git.git_is_repo = lambda _cwd: False
        assert _worktree._hop_diff_probe("demo-lead", "lead", {}) == ([], None, None, "")
        assert _worktree._hop_diff_probe("demo-reviewer", "reviewer", {}) == ([], None, None, "")

    def test_non_implementer_role_gets_files_and_diff_but_no_ref_or_evidence(
        self, monkeypatch: pytest.MonkeyPatch, fake_git: FakeGit
    ) -> None:
        monkeypatch.setattr(_fleet, "meta_get", lambda _id, _field, default="": default)
        fake_git.git_available = lambda: True
        fake_git.git_is_repo = lambda _cwd: True
        fake_git.git_changed_files = lambda _cwd: ["notes/"]
        fake_git.git_diff = lambda _cwd, _base: ""
        fake_git.git_new_files_text = lambda _cwd, _limit: "--- new file: n\nx\n"
        result = _worktree._hop_diff_probe("demo-researcher", "researcher", {})
        assert result == (["notes/"], None, None, "--- new file: n\nx\n")
        same = _worktree._hop_diff_probe("demo-critic", "critic", {}, "--- new file: n\nx\n")
        assert same == ([], None, None, "")

    def test_missing_git_binary_degrades_without_probing_further(
        self, monkeypatch: pytest.MonkeyPatch, fake_git: FakeGit
    ) -> None:
        monkeypatch.setattr(_fleet, "meta_get", lambda _id, _field, default="": default)
        fake_git.git_available = lambda: False

        def boom(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("must not call git_is_repo when git is unavailable")

        fake_git.git_is_repo = boom
        result = _worktree._hop_diff_probe("demo-implementer", "implementer", {})
        assert result == ([], None, {"commit": None, "baseCommit": None, "diffStat": None}, "")

    def test_non_repo_cwd_degrades_without_probing_further(
        self, monkeypatch: pytest.MonkeyPatch, fake_git: FakeGit
    ) -> None:
        monkeypatch.setattr(_fleet, "meta_get", lambda _id, _field, default="": default)
        fake_git.git_available = lambda: True
        fake_git.git_is_repo = lambda _cwd: False

        def boom(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("must not call git_changed_files on a non-repo cwd")

        fake_git.git_changed_files = boom
        fake_git.git_current_branch = boom
        result = _worktree._hop_diff_probe("demo-implementer", "implementer", {})
        assert result == ([], None, {"commit": None, "baseCommit": None, "diffStat": None}, "")

    def test_real_probe_resolves_task_worktree_first(
        self, monkeypatch: pytest.MonkeyPatch, fake_git: FakeGit
    ) -> None:
        meta = {"codebase": "/src/demo"}
        task = {"worktree": {"dir": "/wt/demo-implementer", "branch": "b", "baseCommit": "abc"}}
        monkeypatch.setattr(
            _fleet, "meta_get", lambda _id, field, default="": meta.get(field, default)
        )
        fake_git.git_available = lambda: True
        seen_cwds: list[str] = []

        def fake_is_repo(cwd: str) -> bool:
            seen_cwds.append(cwd)
            return True

        fake_git.git_is_repo = fake_is_repo
        fake_git.git_changed_files = lambda cwd: ["a.py", "b.py"]
        fake_git.git_current_branch = lambda cwd: "pc/demo-implementer"

        result = _worktree._hop_diff_probe("demo-implementer", "implementer", task)
        files_changed, diff_ref, evidence, _diff = result
        assert (files_changed, diff_ref) == (["a.py", "b.py"], "pc/demo-implementer")
        # The commit/diffStat producers are real git calls against a nonexistent path here
        # (unmocked) -- they degrade to None rather than raising; the base is the recorded one.
        assert evidence == {"commit": None, "baseCommit": "abc", "diffStat": None}
        # resolve_member_cwd prefers the task worktree over the shared codebase.
        assert seen_cwds == ["/wt/demo-implementer"]

    def test_detached_head_reports_diff_ref_as_none_not_empty_string(
        self, monkeypatch: pytest.MonkeyPatch, fake_git: FakeGit
    ) -> None:
        monkeypatch.setattr(
            _fleet,
            "meta_get",
            lambda _id, field, default="": {"codebase": "/src/demo"}.get(field, default),
        )
        fake_git.git_available = lambda: True
        fake_git.git_is_repo = lambda _cwd: True
        fake_git.git_changed_files = lambda _cwd: []
        fake_git.git_current_branch = lambda _cwd: ""
        result = _worktree._hop_diff_probe("demo-implementer", "implementer", {})
        assert result == ([], None, {"commit": None, "baseCommit": None, "diffStat": None}, "")


# ── shared pod-seeding helpers (mirrors test_handoff_artifacts.py) ───────


def _init_git_repo(path: Path) -> None:
    """Create a minimal git repo with one commit at `path`."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"], check=True, capture_output=True
    )
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True
    )


@contextmanager
def _seed_pod(
    tmp_path: Path,
    project: str,
    *,
    codebase: str = "",
    work_dir: str = "",
) -> Iterator[Path]:
    home = tmp_path / f"{project}-oc"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=codebase, work_dir=work_dir)
        yield home


class _ImplementerWritesFile:
    """A dispatch Runner simulating the Implementer changing a real file: writes into the
    task worktree the dispatcher hands the hop as its pipeline root before returning, so the
    probe run right after sees a genuinely dirty tree, not a canned answer."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.roots: list[str] = []

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> Any:
        from docket.agent.ports import PIPELINE_WORKTREE_ENV, TurnResult

        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append(role)
        if role == "implementer":
            root = (env or {})[PIPELINE_WORKTREE_ENV]
            self.roots.append(root)
            (Path(root) / "feature.py").write_text("print('new feature')\n")
        text = {"lead": "plan", "implementer": "did it"}[role]
        return TurnResult(True, text, 0.01, {})


class _PlainRunner:
    """A dispatch Runner that never touches the filesystem -- used for the
    degrade-path tests, where the point is that nothing crashes even though
    nothing was ever written."""

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> Any:
        from docket.agent.ports import TurnResult

        role = agent_id.rsplit("-", 1)[-1]
        text = {"lead": "plan", "implementer": "did it"}[role]
        return TurnResult(True, text, 0.01, {})


# ── TestDispatchPopulatesRealDiff: end to end against a real repo ──────────


class TestDispatchPopulatesRealDiff:
    def test_implementer_hop_reports_real_changed_files_and_branch(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        _init_git_repo(repo_dir)
        with _seed_pod(tmp_path, "demo", codebase=str(repo_dir)):
            _queue.enqueue_task_once("demo", "add a feature", channel="cli")
            runner = _ImplementerWritesFile()
            (res,) = _sweep.dispatch_pod("demo", runner=runner, max_tasks=1)
            recorded = _queue.read_tasks("demo")[0]["worktree"]
            expected_branch = recorded["branch"]
            assert recorded["dir"] and expected_branch
            assert runner.roots == [recorded["dir"]]

            assert res.status == "done"
            implementer_hop = next(h for h in res.hops if h.role == "implementer")
            assert implementer_hop.artifact is not None
            assert implementer_hop.artifact.files_changed == ["feature.py"]
            assert implementer_hop.artifact.diff_ref == expected_branch

            # Real git evidence: a 40-hex commit sha and a resolved base against the
            # codebase's own branch, not just the artifact's file list/branch name.
            assert implementer_hop.evidence is not None
            commit = implementer_hop.evidence["commit"]
            base_commit = implementer_hop.evidence["baseCommit"]
            assert commit is not None and len(commit) == 40
            assert all(c in "0123456789abcdef" for c in commit)
            assert base_commit == recorded["baseCommit"]
            assert isinstance(implementer_hop.evidence["diffStat"], dict)
            assert set(implementer_hop.evidence["diffStat"]) == {"files", "insertions", "deletions"}

            # The lead hop is not an implementer -- it must carry no diff at all,
            # even though it ran in the same task.
            lead_hop = next(h for h in res.hops if h.role == "lead")
            assert lead_hop.artifact is not None
            assert lead_hop.artifact.files_changed == []
            assert lead_hop.artifact.diff_ref is None
            assert lead_hop.evidence is None


# ── TestDegradePaths: workdir pod, non-repo workspace, no git binary ────────


class TestDegradePaths:
    def test_workdir_pod_degrades_to_empty_artifact(self, tmp_path: Path) -> None:
        """A `workdir` pod's Implementer has no codebase or worktree -- its cwd resolves to
        its own plain docket workspace dir, never a git repo -- yet the hop must still
        complete and produce a valid empty artifact, not raise."""
        work_dir = tmp_path / "workdir-target"
        work_dir.mkdir()
        with _seed_pod(tmp_path, "taskpod", work_dir=str(work_dir)):
            task: dict[str, Any] = {
                "id": "t2",
                "description": "research something",
                "status": "pending",
            }
            res = _executor.dispatch_task("taskpod", task, runner=_PlainRunner())

            assert res.status == "done"
            implementer_hop = next(h for h in res.hops if h.role == "implementer")
            assert implementer_hop.artifact is not None
            assert implementer_hop.artifact.files_changed == []
            assert implementer_hop.artifact.diff_ref is None
            assert implementer_hop.evidence == {
                "commit": None,
                "baseCommit": None,
                "diffStat": None,
            }

    def test_non_repo_codebase_degrades_to_empty_artifact(self, tmp_path: Path) -> None:
        """A `codebase` that exists but was never `git init`-ed falls back to a flat
        workspace; the diff probe must degrade the same way the mechanical verify gate
        already does for this exact case."""
        plain_dir = tmp_path / "plain-codebase"
        plain_dir.mkdir()
        with _seed_pod(tmp_path, "flatpod", codebase=str(plain_dir)):
            implementer_id = "flatpod-implementer"
            assert _fleet.meta_get(implementer_id, "worktreeDir", "") == ""

            _queue.enqueue_task_once("flatpod", "work", channel="cli")
            (res,) = _sweep.dispatch_pod("flatpod", runner=_PlainRunner(), max_tasks=1)
            assert "not a git repo" in _queue.read_tasks("flatpod")[0]["worktree"]["fallbackReason"]

            assert res.status == "done"
            implementer_hop = next(h for h in res.hops if h.role == "implementer")
            assert implementer_hop.artifact is not None
            assert implementer_hop.artifact.files_changed == []
            assert implementer_hop.artifact.diff_ref is None
            assert implementer_hop.evidence == {
                "commit": None,
                "baseCommit": None,
                "diffStat": None,
            }

    def test_missing_git_binary_degrades_to_empty_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_git: FakeGit
    ) -> None:
        """Even against a real git repo with real uncommitted changes, a host
        with no `git` binary on PATH at dispatch time must degrade cleanly --
        never crash mid-dispatch just because the probe couldn't run."""
        repo_dir = tmp_path / "repo2"
        _init_git_repo(repo_dir)
        with _seed_pod(tmp_path, "gitless", codebase=str(repo_dir)):
            # Simulate "no git binary" only for the dispatch call itself -- the
            # pod was already provisioned (with real git) above.
            fake_git.git_available = lambda: False

            _queue.enqueue_task_once("gitless", "work", channel="cli")
            (res,) = _sweep.dispatch_pod("gitless", runner=_PlainRunner(), max_tasks=1)
            assert _queue.read_tasks("gitless")[0]["worktree"]["dir"] == ""

            assert res.status == "done"
            implementer_hop = next(h for h in res.hops if h.role == "implementer")
            assert implementer_hop.artifact is not None
            assert implementer_hop.artifact.files_changed == []
            assert implementer_hop.artifact.diff_ref is None
            assert implementer_hop.evidence == {
                "commit": None,
                "baseCommit": None,
                "diffStat": None,
            }
