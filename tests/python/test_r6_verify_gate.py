"""R-6: verifyCmd correctness — worktree cwd, bounded shell surface, audited setter.

Two verified defects fixed by this card:
  1. ``core/dispatch.py``'s verify gate ran in ``meta["codebase"]`` (the shared repo
     root) even when a pod implementer had its own git-worktree isolation
     (``worktreeDir``) — so a worktree implementer's work could be verified
     against stale or someone-else's code.
  2. ``set-verify``/``--verify`` had no input validation and no audit trail for a
     value that is later run with ``shell=True``.

Three groups:
  * TestResolveMemberCwd    — ``core/pod.py``'s shared cwd-resolution helper
    (``resolve_member_cwd``), used by both the dispatch verify gate and
    ``cli/_pod.py``'s ``_regenerate_member_tools`` so the two can't diverge again.
  * TestDispatchVerifyCwd   — end-to-end: the verify gate's real subprocess
    actually runs in the resolved directory (proven with marker files, not a
    mocked ``run_verify_cmd``).
  * TestSetVerifyValidation — ``cli/_pod.py``'s ``set-verify``/``--verify``:
    NUL/newline rejection, the length cap, and the audit-log entry a successful
    set writes (``pod.set-verify``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer

import docket.config as _cfg
from docket.cli import _pod
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pod as _pod_core
from docket.core import runtime_driver as _rd

# ── TestResolveMemberCwd: pure unit tests for core/pod.resolve_member_cwd ────


class TestResolveMemberCwd:
    def test_worktree_dir_wins_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "PROJECTS_DIR", tmp_path / "projects", raising=True)
        cwd = _pod_core.resolve_member_cwd(
            "demo-implementer", worktree_dir="/wt/demo", codebase="/src/demo"
        )
        assert cwd == "/wt/demo"

    def test_falls_back_to_codebase_when_no_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "PROJECTS_DIR", tmp_path / "projects", raising=True)
        cwd = _pod_core.resolve_member_cwd(
            "demo-implementer", worktree_dir="", codebase="/src/demo"
        )
        assert cwd == "/src/demo"

    def test_falls_back_to_workspace_dir_when_neither_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        projects_dir = tmp_path / "projects"
        monkeypatch.setattr(_cfg, "PROJECTS_DIR", projects_dir, raising=True)
        cwd = _pod_core.resolve_member_cwd("demo-implementer", worktree_dir="", codebase="")
        assert cwd == str(projects_dir / "demo-implementer")

    def test_defaults_are_falsy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Calling with no worktree_dir/codebase args at all behaves like both unset.
        projects_dir = tmp_path / "projects"
        monkeypatch.setattr(_cfg, "PROJECTS_DIR", projects_dir, raising=True)
        cwd = _pod_core.resolve_member_cwd("demo-implementer")
        assert cwd == str(projects_dir / "demo-implementer")


# ── TestDispatchVerifyCwd: the real verify subprocess runs where it should ──


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = _cfg.PROJECTS_DIR / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.split("-")[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "modelSource": "policy",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-06-25T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member_id, meta["model"], meta["sessionKey"], "default")


def _fake_runner() -> _dispatch.Runner:
    def _run(
        member_id: str,
        session_id: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        return _rd.TurnResult(ok=True, output="ok", cost_usd=0.0, raw={})

    return _run


class TestDispatchVerifyCwd:
    """The verify gate's real subprocess must run in the resolved directory.

    Each test plants a distinguishing marker file and asks the verify command to
    assert on its presence/absence — a real ``shell=True`` subprocess, not a
    mocked ``run_verify_cmd``, so this proves the actual cwd, not just the value
    a helper returned.
    """

    @pytest.fixture(autouse=True)
    def _hermetic(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("DOCKET_NO_RESTART", "1")
        monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
        monkeypatch.setenv("DOCKET_NO_TRACE", "0")
        monkeypatch.delenv("DOCKET_NO_AUDIT", raising=False)

        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))

        monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
        monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
        monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
        monkeypatch.setattr(_cfg, "TRACES_DIR", home / "traces", raising=True)
        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
        monkeypatch.setattr(_cfg, "AUDIT_LOG", home / "audit.log", raising=True)

    def test_verify_runs_in_worktree_when_present(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "WORKTREE_MARKER").touch()
        codebase = tmp_path / "codebase"
        codebase.mkdir()
        (codebase / "CODEBASE_MARKER").touch()

        _write_meta("myapp-lead")
        _write_meta(
            "myapp-implementer",
            {
                "codebase": str(codebase),
                "worktreeDir": str(worktree),
                "verifyCmd": "test -f WORKTREE_MARKER && ! test -f CODEBASE_MARKER",
            },
        )
        task: dict[str, Any] = {"id": "cw1", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_fake_runner())
        assert res.status == "done", res.reason

    def test_verify_falls_back_to_codebase_when_no_worktree(self, tmp_path: Path) -> None:
        codebase = tmp_path / "codebase"
        codebase.mkdir()
        (codebase / "CODEBASE_MARKER").touch()

        _write_meta("myapp-lead")
        _write_meta(
            "myapp-implementer",
            {"codebase": str(codebase), "verifyCmd": "test -f CODEBASE_MARKER"},
        )
        task: dict[str, Any] = {"id": "cw2", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_fake_runner())
        assert res.status == "done", res.reason

    def test_verify_falls_back_to_workspace_dir_when_neither_set(self, tmp_path: Path) -> None:
        _write_meta("myapp-lead")
        _write_meta(
            "myapp-implementer",
            {"codebase": "", "verifyCmd": "test -f WORKSPACE_MARKER"},
        )
        ws = _cfg.PROJECTS_DIR / "myapp-implementer"
        (ws / "WORKSPACE_MARKER").touch()

        task: dict[str, Any] = {"id": "cw3", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_fake_runner())
        assert res.status == "done", res.reason

    def test_verify_fails_if_run_against_wrong_tree(self, tmp_path: Path) -> None:
        # Sanity check the marker technique itself: a worktree WITHOUT the marker
        # correctly fails, so the "done" assertions above are not vacuous.
        worktree = tmp_path / "worktree"
        worktree.mkdir()  # no marker planted here

        _write_meta("myapp-lead")
        _write_meta(
            "myapp-implementer",
            {"worktreeDir": str(worktree), "verifyCmd": "test -f WORKTREE_MARKER"},
        )
        task: dict[str, Any] = {"id": "cw4", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_fake_runner())
        assert res.status == "failed"


# ── TestSetVerifyValidation: cli/_pod.py's set-verify / --verify ────────────


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", home / "audit.log", raising=True)


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    monkeypatch.delenv("DOCKET_NO_AUDIT", raising=False)
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    _point_at(home, monkeypatch)
    _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
    return home


def _meta(home: Path, member_id: str) -> dict[str, Any]:
    p = home / "workspaces" / "projects" / member_id / ".docket-meta.json"
    return json.loads(p.read_text())


class TestSetVerifyValidation:
    def test_rejects_newline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "set-verify", ["demo-implementer", "npm test\nrm -rf /"])

    def test_rejects_nul_byte(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "set-verify", ["demo-implementer", "npm\x00test"])

    def test_rejects_command_over_length_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        too_long = "x" * (_pod._MAX_VERIFY_CMD_LEN + 1)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "set-verify", ["demo-implementer", too_long])

    def test_rejected_command_is_not_persisted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "set-verify", ["demo-implementer", "bad\ncmd"])
        m = _meta(oc_dir, "demo-implementer")
        assert "verifyCmd" not in m

    def test_validator_accepts_command_exactly_at_the_cap(self) -> None:
        # Boundary check on the validator itself (not the full CLI path, which
        # would need to synthesize a single argv token this long).
        at_cap = "x" * _pod._MAX_VERIFY_CMD_LEN
        assert _pod._validate_verify_cmd(at_cap) == at_cap

    def test_validator_rejects_one_char_over_the_cap(self) -> None:
        over_cap = "x" * (_pod._MAX_VERIFY_CMD_LEN + 1)
        with pytest.raises(_pod.VerifyCmdError):
            _pod._validate_verify_cmd(over_cap)

    def test_successful_set_verify_writes_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _pod.dispatch("demo", "set-verify", ["demo-implementer", "npm", "test"])
        entries = _audit.read_audit()
        matches = [e for e in entries if e["action"] == "pod.set-verify"]
        assert matches, f"expected a pod.set-verify audit entry, got: {entries}"
        assert "demo-implementer" in matches[-1]["detail"]
        assert "npm test" in matches[-1]["detail"]

    def test_no_audit_entry_when_validation_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "set-verify", ["demo-implementer", "bad\ncmd"])
        entries = [e for e in _audit.read_audit() if e["action"] == "pod.set-verify"]
        assert entries == []


class TestPodAddVerifyValidation:
    """The same validation + audit trail applies to `docket pod <p> add --verify`."""

    def test_add_rejects_newline_in_verify(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "add", ["implementer", "--verify", "npm test\nrm -rf /"])

    def test_add_with_verify_writes_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _pod.dispatch("demo", "add", ["implementer", "--verify", "npm test"])
        entries = [e for e in _audit.read_audit() if e["action"] == "pod.set-verify"]
        assert entries, "expected a pod.set-verify audit entry from `pod add --verify`"
        assert "demo-implementer-2" in entries[-1]["detail"]
