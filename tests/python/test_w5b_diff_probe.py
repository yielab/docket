"""W-5b: real `files_changed`/`diff_ref` producer for an Implementer hop's artifact.

ROADMAP Phase 16 card W-5 shipped `HandoffArtifact.files_changed`/`.diff_ref` as
real, structurally-typed fields with **no producer** -- an explicit, documented
seam (`core/handoff.py`'s module docstring) because the git shell-out surface
(`edges/adapters/system.py`) belonged to a different in-flight card that wave.
This suite closes it:

  * TestImplementerDiffProbeUnit -- `core/dispatch.py`'s `_implementer_diff_probe`
    in isolation, with `edges/adapters/system.py`'s git calls monkeypatched out
    (no real git, no real filesystem).
  * TestDispatchPopulatesRealDiff -- end to end through a real `dispatch_task`
    call against a real git repo (and the real git worktree CD-5 provisions for
    a repo pod's Implementer): the hop's artifact carries the actual changed
    file and the actual checked-out branch.
  * TestDegradePaths -- the three ways this must degrade to an empty (never
    exceptional) artifact: a `workdir` (non-codebase) pod, a `codebase` that
    exists but is not a git repository, and a host with no `git` binary at all
    -- each pinned end to end through `dispatch_task`, not just at the unit
    level, so a future change to the call site can't quietly reintroduce a
    crash.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.edges.adapters import system as _sys

# ── TestImplementerDiffProbeUnit: _implementer_diff_probe in isolation ──────


class TestImplementerDiffProbeUnit:
    def test_non_implementer_role_never_touches_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("a non-implementer hop must never probe git")

        monkeypatch.setattr(_sys, "git_available", boom)
        monkeypatch.setattr(_fleet, "meta_get", boom)
        assert _dispatch._implementer_diff_probe("demo-lead", "lead") == ([], None)
        assert _dispatch._implementer_diff_probe("demo-reviewer", "reviewer") == ([], None)

    def test_missing_git_binary_degrades_without_probing_further(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_fleet, "meta_get", lambda _id, _field, default="": default)
        monkeypatch.setattr(_sys, "git_available", lambda: False)

        def boom(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("must not call git_is_repo when git is unavailable")

        monkeypatch.setattr(_sys, "git_is_repo", boom)
        result = _dispatch._implementer_diff_probe("demo-implementer", "implementer")
        assert result == ([], None)

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
        result = _dispatch._implementer_diff_probe("demo-implementer", "implementer")
        assert result == ([], None)

    def test_real_probe_resolves_worktree_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = {"worktreeDir": "/wt/demo-implementer", "codebase": "/src/demo"}
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

        result = _dispatch._implementer_diff_probe("demo-implementer", "implementer")
        assert result == (["a.py", "b.py"], "pc/demo-implementer")
        # resolve_member_cwd prefers the worktree over the shared codebase --
        # verified here, not just asserted by reading the source.
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
        result = _dispatch._implementer_diff_probe("demo-implementer", "implementer")
        assert result == ([], None)


# ── shared pod-seeding helpers (mirrors test_w5_handoff_artifacts.py) ───────


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


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", home / "traces", raising=True)


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
    _point_at(home, monkeypatch)
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=codebase, work_dir=work_dir)
    return home


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")


class _ImplementerWritesFile:
    """A dispatch Runner that simulates the Implementer changing a real file.

    Writes into whatever directory the caller resolves as the Implementer's
    real working tree -- a real git worktree when the pod has one -- *before*
    returning, so the probe that runs right after this hop completes sees a
    genuinely dirty tree, not a canned answer.
    """

    def __init__(self, implementer_cwd: str) -> None:
        self.implementer_cwd = implementer_cwd
        self.calls: list[str] = []

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
        self.calls.append(role)
        if role == "implementer":
            (Path(self.implementer_cwd) / "feature.py").write_text("print('new feature')\n")
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

        implementer_id = "demo-implementer"
        worktree_dir = _fleet.meta_get(implementer_id, "worktreeDir", "")
        # CD-5 provisions a real worktree for a repo pod's Implementer -- if
        # this is empty, the fixture didn't set up what this test assumes.
        assert worktree_dir, "expected a provisioned git worktree for the Implementer"
        expected_branch = _fleet.meta_get(implementer_id, "worktreeBranch", "")
        assert expected_branch

        task: dict[str, Any] = {"id": "t1", "description": "add a feature", "status": "pending"}
        runner = _ImplementerWritesFile(worktree_dir)
        res = _dispatch.dispatch_task("demo", task, runner=runner)

        assert res.status == "done"
        implementer_hop = next(h for h in res.hops if h.role == "implementer")
        assert implementer_hop.artifact is not None
        assert implementer_hop.artifact.files_changed == ["feature.py"]
        assert implementer_hop.artifact.diff_ref == expected_branch

        # The lead hop is not an implementer -- it must carry no diff at all,
        # even though it ran in the same task.
        lead_hop = next(h for h in res.hops if h.role == "lead")
        assert lead_hop.artifact is not None
        assert lead_hop.artifact.files_changed == []
        assert lead_hop.artifact.diff_ref is None


# ── TestDegradePaths: workdir pod, non-repo workspace, no git binary ────────


class TestDegradePaths:
    def test_workdir_pod_degrades_to_empty_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `workdir` (non-codebase) pod's Implementer has no codebase and no
        worktree -- its cwd resolves to its own plain docket workspace dir,
        which is never a git repo. The hop must still complete and produce a
        valid (empty) artifact, not raise."""
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

    def test_non_repo_codebase_degrades_to_empty_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `codebase` that exists on disk but was never `git init`-ed --
        the worktree provisioning step falls back to a flat workspace (CD-5),
        and the diff probe must degrade the same way the mechanical verify
        gate already does for this exact case."""
        plain_dir = tmp_path / "plain-codebase"
        plain_dir.mkdir()
        _seed_pod(tmp_path, monkeypatch, "flatpod", codebase=str(plain_dir))

        implementer_id = "flatpod-implementer"
        assert _fleet.meta_get(implementer_id, "worktreeDir", "") == ""

        task: dict[str, Any] = {"id": "t3", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("flatpod", task, runner=_PlainRunner())

        assert res.status == "done"
        implementer_hop = next(h for h in res.hops if h.role == "implementer")
        assert implementer_hop.artifact is not None
        assert implementer_hop.artifact.files_changed == []
        assert implementer_hop.artifact.diff_ref is None

    def test_missing_git_binary_degrades_to_empty_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even against a real git repo with real uncommitted changes, a host
        with no `git` binary on PATH at dispatch time must degrade cleanly --
        never crash mid-dispatch just because the probe couldn't run."""
        repo_dir = tmp_path / "repo2"
        _init_git_repo(repo_dir)
        _seed_pod(tmp_path, monkeypatch, "gitless", codebase=str(repo_dir))

        implementer_id = "gitless-implementer"
        worktree_dir = _fleet.meta_get(implementer_id, "worktreeDir", "")
        assert worktree_dir

        # Simulate "no git binary" only for the dispatch call itself -- the
        # pod was already provisioned (with real git) above.
        monkeypatch.setattr(_sys, "git_available", lambda: False)

        task: dict[str, Any] = {"id": "t4", "description": "work", "status": "pending"}
        runner = _ImplementerWritesFile(worktree_dir)
        res = _dispatch.dispatch_task("gitless", task, runner=runner)

        assert res.status == "done"
        implementer_hop = next(h for h in res.hops if h.role == "implementer")
        assert implementer_hop.artifact is not None
        assert implementer_hop.artifact.files_changed == []
        assert implementer_hop.artifact.diff_ref is None
