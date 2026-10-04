"""The real `files_changed`/`diff_ref` producer for an Implementer hop's artifact.

`HandoffArtifact.files_changed`/`.diff_ref` are real, structurally-typed fields
(`core/handoff.py`'s module docstring documents the seam). Covers: TestImplementerDiffProbeUnit
(`_implementer_diff_probe` in isolation, with `edges/adapters/system.py`'s git calls
monkeypatched out); TestDispatchPopulatesRealDiff (end to end through a real `dispatch_pod`
claim against a real git repo: the hop's artifact carries the actual changed file and the
task worktree's branch); and TestDegradePaths (the three ways this must degrade to an empty,
never exceptional, artifact -- a `workdir` pod, a non-git `codebase`, and no `git` binary --
each pinned end to end through `dispatch_task` so a call-site change can't reintroduce a crash).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.edges.adapters import system as _sys

SUBJECT = "docket.core"

# ── TestImplementerDiffProbeUnit: _implementer_diff_probe in isolation ──────


class TestImplementerDiffProbeUnit:
    def test_non_implementer_role_never_touches_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("a non-implementer hop must never probe git")

        monkeypatch.setattr(_sys, "git_available", boom)
        monkeypatch.setattr(_fleet, "meta_get", boom)
        assert _dispatch._implementer_diff_probe("demo-lead", "lead", {}) == ([], None, None)
        assert _dispatch._implementer_diff_probe("demo-reviewer", "reviewer", {}) == (
            [],
            None,
            None,
        )

    def test_missing_git_binary_degrades_without_probing_further(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_fleet, "meta_get", lambda _id, _field, default="": default)
        monkeypatch.setattr(_sys, "git_available", lambda: False)

        def boom(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("must not call git_is_repo when git is unavailable")

        monkeypatch.setattr(_sys, "git_is_repo", boom)
        result = _dispatch._implementer_diff_probe("demo-implementer", "implementer", {})
        assert result == ([], None, {"commit": None, "baseCommit": None, "diffStat": None})

    def test_non_repo_cwd_degrades_without_probing_further(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_fleet, "meta_get", lambda _id, _field, default="": default)
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        monkeypatch.setattr(_sys, "git_is_repo", lambda _cwd: False)

        def boom(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("must not call git_changed_files on a non-repo cwd")

        monkeypatch.setattr(_sys, "git_changed_files", boom)
        monkeypatch.setattr(_sys, "git_current_branch", boom)
        result = _dispatch._implementer_diff_probe("demo-implementer", "implementer", {})
        assert result == ([], None, {"commit": None, "baseCommit": None, "diffStat": None})

    def test_real_probe_resolves_task_worktree_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = {"codebase": "/src/demo"}
        task = {"worktree": {"dir": "/wt/demo-implementer", "branch": "b", "baseCommit": "abc"}}
        monkeypatch.setattr(
            _fleet, "meta_get", lambda _id, field, default="": meta.get(field, default)
        )
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        seen_cwds: list[str] = []

        def fake_is_repo(cwd: str) -> bool:
            seen_cwds.append(cwd)
            return True

        monkeypatch.setattr(_sys, "git_is_repo", fake_is_repo)
        monkeypatch.setattr(_sys, "git_changed_files", lambda cwd: ["a.py", "b.py"])
        monkeypatch.setattr(_sys, "git_current_branch", lambda cwd: "pc/demo-implementer")

        result = _dispatch._implementer_diff_probe("demo-implementer", "implementer", task)
        files_changed, diff_ref, evidence = result
        assert (files_changed, diff_ref) == (["a.py", "b.py"], "pc/demo-implementer")
        # The commit/diffStat producers are real git calls against a nonexistent path here
        # (unmocked) -- they degrade to None rather than raising; the base is the recorded one.
        assert evidence == {"commit": None, "baseCommit": "abc", "diffStat": None}
        # resolve_member_cwd prefers the task worktree over the shared codebase.
        assert seen_cwds == ["/wt/demo-implementer"]

    def test_detached_head_reports_diff_ref_as_none_not_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _fleet,
            "meta_get",
            lambda _id, field, default="": {"codebase": "/src/demo"}.get(field, default),
        )
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        monkeypatch.setattr(_sys, "git_is_repo", lambda _cwd: True)
        monkeypatch.setattr(_sys, "git_changed_files", lambda _cwd: [])
        monkeypatch.setattr(_sys, "git_current_branch", lambda _cwd: "")
        result = _dispatch._implementer_diff_probe("demo-implementer", "implementer", {})
        assert result == ([], None, {"commit": None, "baseCommit": None, "diffStat": None})


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


def _seed_pod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str,
    *,
    codebase: str = "",
    work_dir: str = "",
) -> Path:
    home = tmp_path / f"{project}-oc"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=codebase, work_dir=work_dir)
    return home


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")


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
        from docket.core.runtime_driver import PIPELINE_WORKTREE_ENV, TurnResult

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
        from docket.core.runtime_driver import TurnResult

        role = agent_id.rsplit("-", 1)[-1]
        text = {"lead": "plan", "implementer": "did it"}[role]
        return TurnResult(True, text, 0.01, {})


# ── TestDispatchPopulatesRealDiff: end to end against a real repo ──────────


class TestDispatchPopulatesRealDiff:
    def test_implementer_hop_reports_real_changed_files_and_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo_dir = tmp_path / "repo"
        _init_git_repo(repo_dir)
        _seed_pod(tmp_path, monkeypatch, "demo", codebase=str(repo_dir))

        _dispatch.enqueue_task("demo", "add a feature")
        runner = _ImplementerWritesFile()
        (res,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)
        recorded = _dispatch.read_tasks("demo")[0]["worktree"]
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
    def test_workdir_pod_degrades_to_empty_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `workdir` pod's Implementer has no codebase or worktree -- its cwd resolves to
        its own plain docket workspace dir, never a git repo -- yet the hop must still
        complete and produce a valid empty artifact, not raise."""
        work_dir = tmp_path / "workdir-target"
        work_dir.mkdir()
        _seed_pod(tmp_path, monkeypatch, "taskpod", work_dir=str(work_dir))

        task: dict[str, Any] = {
            "id": "t2",
            "description": "research something",
            "status": "pending",
        }
        res = _dispatch.dispatch_task("taskpod", task, runner=_PlainRunner())

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

    def test_non_repo_codebase_degrades_to_empty_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `codebase` that exists but was never `git init`-ed falls back to a flat
        workspace; the diff probe must degrade the same way the mechanical verify gate
        already does for this exact case."""
        plain_dir = tmp_path / "plain-codebase"
        plain_dir.mkdir()
        _seed_pod(tmp_path, monkeypatch, "flatpod", codebase=str(plain_dir))

        implementer_id = "flatpod-implementer"
        assert _fleet.meta_get(implementer_id, "worktreeDir", "") == ""

        _dispatch.enqueue_task("flatpod", "work")
        (res,) = _dispatch.dispatch_pod("flatpod", runner=_PlainRunner(), max_tasks=1)
        assert "not a git repo" in _dispatch.read_tasks("flatpod")[0]["worktree"]["fallbackReason"]

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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even against a real git repo with real uncommitted changes, a host
        with no `git` binary on PATH at dispatch time must degrade cleanly --
        never crash mid-dispatch just because the probe couldn't run."""
        repo_dir = tmp_path / "repo2"
        _init_git_repo(repo_dir)
        _seed_pod(tmp_path, monkeypatch, "gitless", codebase=str(repo_dir))

        # Simulate "no git binary" only for the dispatch call itself -- the
        # pod was already provisioned (with real git) above.
        monkeypatch.setattr(_sys, "git_available", lambda: False)

        _dispatch.enqueue_task("gitless", "work")
        (res,) = _dispatch.dispatch_pod("gitless", runner=_PlainRunner(), max_tasks=1)
        assert _dispatch.read_tasks("gitless")[0]["worktree"]["dir"] == ""

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
