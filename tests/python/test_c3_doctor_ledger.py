"""ROADMAP Phase 17 C-3: ``docket doctor``'s TASK_LIST.json <-> HEARTBEAT.md
dispatch-ledger divergence check (``cli/_doctor.py``'s ``_check_dispatch_ledger``).

Dispatch itself keeps the two in sync mechanically (see
``test_c3_c5_dispatch_wiring.py``); this file proves the *doctor* side: it
detects a workspace whose ledger has drifted from TASK_LIST.json — in either
direction — and ``--fix`` safely re-syncs it without touching an agent's own
prose in the same file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _doctor, _pod
from docket.core import dispatch as _dispatch
from docket.core import memory as _mem
from docket.edges.adapters import openclaw as _oc

# ── hermetic pod fixture (mirrors test_dispatch.py's _seed_pod) ─────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = oc_dir / "openclaw.json"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", oc_dir / "traces", raising=True)
    monkeypatch.setattr(
        _cfg, "CONVERSATIONS_FILE", oc_dir / "docket-conversations.json", raising=True
    )
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)
    # Doctor's other checks shell out to the real openclaw CLI for security
    # state -- stub them so this file only ever exercises the ledger check.
    monkeypatch.setattr(
        _oc, "security_gate_report", lambda: ("NA", "approvals snapshot unavailable", "")
    )
    monkeypatch.setattr(_oc, "security_audit_report", lambda: _oc.SecurityAudit(False, 0, 0, 0, []))


def _fake_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_pod.shutil, "which", lambda _name: "/usr/bin/openclaw")

    def _register(agent_id: str, workspace: str, model: str) -> tuple[bool, str]:
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw.setdefault("agents", {}).setdefault("list", []).append(
            {"id": agent_id, "model": model, "metadata": {}}
        )
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        return (True, "")

    monkeypatch.setattr(_oc, "register_agent_cli", _register)


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    (oc_dir / "openclaw.json").write_text(
        json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}})
    )
    _point_at(oc_dir, monkeypatch)
    _fake_daemon(monkeypatch)
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return oc_dir


def _lead_ws(project: str = "demo") -> Path:
    return _cfg.workspace_dir(f"{project}-lead")


def _claim_a_task(project: str = "demo") -> str:
    """Enqueue + claim a task via the real dispatch state machine (so
    TASK_LIST.json ends up in a genuine 'running' state, ledger written by
    dispatch itself); returns the task id."""
    _dispatch.enqueue_task(project, "some work")
    claim = _dispatch._claim_next_task(project, resume=False)
    assert claim is not None
    return str(claim[0]["id"])


class TestNoPods:
    def test_no_dispatchable_pods_is_a_silent_no_op(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        (oc_dir / "openclaw.json").write_text(json.dumps({"agents": {"list": []}}))
        _point_at(oc_dir, monkeypatch)
        assert _doctor._check_dispatch_ledger(do_fix=False) == 0
        assert "Dispatch task ledger" not in capsys.readouterr().out


class TestInSync:
    def test_in_sync_reports_zero_issues(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _claim_a_task()
        assert _doctor._check_dispatch_ledger(do_fix=False) == 0
        out = capsys.readouterr().out
        assert "demo: in sync (1 running)" in out

    def test_no_tasks_at_all_is_in_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        assert _doctor._check_dispatch_ledger(do_fix=False) == 0
        assert "demo: in sync (0 running)" in capsys.readouterr().out


class TestMissingFromLedger:
    """TASK_LIST.json says a task is running; HEARTBEAT.md's ledger doesn't
    show it (an older docket version, a hand-edited HEARTBEAT.md, ...)."""

    def _corrupt(self, project: str = "demo") -> None:
        # Simulate drift: wipe dispatch's own ledger while the task is still
        # running in TASK_LIST.json.
        _mem.write_dispatch_tasks(_lead_ws(project), [])

    def test_detected_without_fix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task_id = _claim_a_task()
        self._corrupt()
        issues = _doctor._check_dispatch_ledger(do_fix=False)
        out = capsys.readouterr().out
        assert issues == 1
        assert f"missing from ledger: {task_id}" in out
        assert "Fix with: docket doctor --fix" in out

    def test_fix_resyncs_and_clears_the_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task_id = _claim_a_task()
        self._corrupt()
        issues = _doctor._check_dispatch_ledger(do_fix=True)
        assert issues == 0
        assert "ledger re-synced" in capsys.readouterr().out
        assert _mem.read_dispatch_task_ids(_lead_ws()) == [task_id]


class TestStaleInLedger:
    """HEARTBEAT.md's ledger names a task that TASK_LIST.json no longer shows
    as running (finished since, or never existed) -- the reverse divergence."""

    def test_detected_without_fix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        # No real running task -- inject a stale ledger entry directly.
        stale = _mem.DispatchHeartbeatTask(
            task_id="task-ghost", description="long finished", claimed_at="t"
        )
        _mem.write_dispatch_tasks(_lead_ws(), [stale])

        issues = _doctor._check_dispatch_ledger(do_fix=False)
        out = capsys.readouterr().out
        assert issues == 1
        assert "stale in ledger: task-ghost" in out

    def test_fix_clears_the_stale_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        stale = _mem.DispatchHeartbeatTask(
            task_id="task-ghost", description="long finished", claimed_at="t"
        )
        _mem.write_dispatch_tasks(_lead_ws(), [stale])

        issues = _doctor._check_dispatch_ledger(do_fix=True)
        assert issues == 0
        assert _mem.read_dispatch_task_ids(_lead_ws()) == []

    def test_fix_never_touches_agent_prose_elsewhere_in_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        ws = _lead_ws()
        hb = ws / _mem.HEARTBEAT_FILE
        text = hb.read_text(encoding="utf-8")
        text = text.replace("## Notes\n_none_\n", "## Notes\n- Don't touch prod on Fridays.\n")
        hb.write_text(text, encoding="utf-8")
        stale = _mem.DispatchHeartbeatTask(task_id="task-ghost", description="x", claimed_at="t")
        _mem.write_dispatch_tasks(ws, [stale])

        _doctor._check_dispatch_ledger(do_fix=True)

        final = hb.read_text(encoding="utf-8")
        assert "Don't touch prod on Fridays." in final
        assert "task-ghost" not in final


class TestDoctorJson:
    def test_dispatch_ledger_key_present_and_flags_divergence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        monkeypatch.setattr(_doctor, "gateway_active", lambda: True)
        task_id = _claim_a_task()
        _mem.write_dispatch_tasks(_lead_ws(), [])  # corrupt: drop the ledger entry

        capsys.readouterr()  # discard pod-provisioning output from setup above
        rc = _doctor.run_doctor(json_out=True)
        data = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert data["healthy"] is False
        ledger = data["checks"]["dispatchLedger"]
        assert ledger == [
            {
                "project": "demo",
                "ok": False,
                "missingFromLedger": [task_id],
                "staleInLedger": [],
            }
        ]

    def test_in_sync_reports_ok_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        monkeypatch.setattr(_doctor, "gateway_active", lambda: True)
        _claim_a_task()

        capsys.readouterr()  # discard pod-provisioning output from setup above
        _doctor.run_doctor(json_out=True)
        data = json.loads(capsys.readouterr().out)
        ledger = data["checks"]["dispatchLedger"]
        assert ledger == [
            {"project": "demo", "ok": True, "missingFromLedger": [], "staleInLedger": []}
        ]
