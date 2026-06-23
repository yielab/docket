"""M5 tests: doctor — system-wide health checks + JSON health probe.

These call run_doctor() in-process with OPENCLAW_DIR monkeypatched to a temp
seed (the config module reads OPENCLAW_DIR at import time, so we patch the
already-imported module attributes). stdout is captured to assert on the
human report; the return value is the process exit code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _doctor
from docket.edges.adapters import openclaw as _oc

# ── seed helpers ───────────────────────────────────────────────────────────────

_FULL_META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "type": "repo",
    "name": "My Shop",
    "model": "anthropic/claude-sonnet-4-6",
    "modelSource": "policy",
    "stack": "Node.js",
    "codebase": "/tmp/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
    "templateVersion": "3",
}

_OC_CONFIG: dict[str, Any] = {
    "agents": {
        "defaults": {"model": "anthropic/claude-sonnet-4-6"},
        "list": [
            {
                "id": "myshop",
                "model": "anthropic/claude-sonnet-4-6",
                "metadata": {
                    "sessionKey": "agent:myshop:default",
                    "projectKey": "default",
                },
            }
        ],
    },
    "bindings": [],
    "channels": {},
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


@pytest.fixture(autouse=True)
def _no_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never touch systemctl during doctor tests."""
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")


def _point_config_at(oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repoint the already-imported config + ACL modules at a temp OPENCLAW_DIR.

    Both docket.config and the openclaw ACL bind paths at import time, so we
    patch the live module attributes. We also stub the two ACL functions that
    shell out to the real `openclaw` CLI so tests stay hermetic regardless of
    what is on PATH.
    """
    cfg_file = oc_dir / "openclaw.json"
    projects = oc_dir / "workspaces" / "projects"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", projects, raising=True)
    # ACL bound CONFIG_FILE / meta_path directly at import — rebind them.
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)
    # Keep security probes hermetic (no real openclaw CLI invocation).
    monkeypatch.setattr(
        _oc, "security_gate_report", lambda: ("NA", "approvals snapshot unavailable", "")
    )
    monkeypatch.setattr(_oc, "security_audit_report", lambda: _oc.SecurityAudit(False, 0, 0, 0, []))


def _seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    full_workspace: bool = True,
    budget: str | None = None,
    register: bool = True,
    meta_model: str = "anthropic/claude-sonnet-4-6",
    oc_model: str = "anthropic/claude-sonnet-4-6",
    secrets: dict[str, str] | None = None,
) -> Path:
    """Create a temp ~/.openclaw with one myshop agent and repoint config."""
    oc_dir = tmp_path / ".openclaw"
    ws = oc_dir / "workspaces" / "projects" / "myshop"
    (ws / "memory").mkdir(parents=True)

    meta = {**_FULL_META, "model": meta_model}
    if budget is not None:
        meta["budgetUsd"] = budget
    (ws / ".docket-meta.json").write_text(json.dumps(meta))

    files = ("SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md") if full_workspace else ("SOUL.md",)
    for f in files:
        (ws / f).write_text(f"# {f}\n")

    oc = json.loads(json.dumps(_OC_CONFIG))
    oc["agents"]["list"][0]["model"] = oc_model
    if not register:
        oc["agents"]["list"] = []
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps(oc))
    cfg_file.chmod(0o600)

    if secrets is not None:
        sfile = oc_dir / "secrets.json"
        sfile.write_text(json.dumps(secrets))
        sfile.chmod(0o600)

    _point_config_at(oc_dir, monkeypatch)
    return oc_dir


# ── JSON health-probe contract ─────────────────────────────────────────────────


class TestJsonProbe:
    def test_json_healthy_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Full workspace, registered, key present, in sync, gateway forced active.
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        monkeypatch.setattr(_doctor, "gateway_active", lambda: True)
        rc = _doctor.run_doctor(json_out=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["healthy"] is True
        assert data["issues"] == 0
        assert rc == 0

    def test_json_degraded_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Missing workspace files + missing provider key + gateway down → issues.
        _seed(tmp_path, monkeypatch, full_workspace=False)
        monkeypatch.setattr(_doctor, "gateway_active", lambda: False)
        rc = _doctor.run_doctor(json_out=True)
        data = json.loads(capsys.readouterr().out)
        assert data["healthy"] is False
        assert data["issues"] > 0
        assert rc == 1

    def test_json_structure_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        monkeypatch.setattr(_doctor, "gateway_active", lambda: True)
        _doctor.run_doctor(json_out=True)
        checks = json.loads(capsys.readouterr().out)["checks"]
        for key in (
            "openclaw",
            "python3",
            "config",
            "gateway",
            "telegram",
            "agents",
            "modelConfig",
            "drift",
            "budget",
            "runaway",
            "keyHygiene",
            "securityGates",
            "templateDrift",
        ):
            assert key in checks

    def test_json_gateway_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        monkeypatch.setattr(_doctor, "gateway_active", lambda: False)
        _doctor.run_doctor(json_out=True)
        data = json.loads(capsys.readouterr().out)
        assert data["checks"]["gateway"]["ok"] is False
        assert data["checks"]["gateway"]["status"] == "inactive"


# ── individual checks ──────────────────────────────────────────────────────────


class TestChecks:
    def test_config_valid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        assert _doctor._check_config() == 0
        assert "Config JSON valid" in capsys.readouterr().out

    def test_config_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        _point_config_at(oc_dir, monkeypatch)
        assert _doctor._check_config() == 1
        assert "Config missing" in capsys.readouterr().out

    def test_project_agents_missing_files_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, full_workspace=False)
        issues = _doctor._check_project_agents(["myshop"])
        out = capsys.readouterr().out
        assert issues == 1
        assert "missing AGENTS.md" in out

    def test_project_agents_not_registered_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, register=False)
        issues = _doctor._check_project_agents(["myshop"])
        out = capsys.readouterr().out
        assert issues == 1
        assert "not registered in openclaw" in out

    def test_project_agents_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        # Add a Telegram binding so the agent hits the success (stdout) path.
        cfg = json.loads((oc_dir / "openclaw.json").read_text())
        cfg["bindings"] = [
            {
                "agentId": "myshop",
                "match": {"channel": "telegram", "peer": {"kind": "group", "id": "-100"}},
            }
        ]
        (oc_dir / "openclaw.json").write_text(json.dumps(cfg))
        assert _doctor._check_project_agents(["myshop"]) == 0
        assert "OK  →  group -100" in capsys.readouterr().out

    def test_models_stale_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, oc_model="anthropic/claude-haiku-3-5")
        issues = _doctor._check_models()
        out = capsys.readouterr().out
        assert issues == 1
        assert "invalid model" in out.lower()

    def test_models_valid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        assert _doctor._check_models() == 0
        assert "All agent models are valid" in capsys.readouterr().out

    def test_drift_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(
            tmp_path,
            monkeypatch,
            meta_model="anthropic/claude-sonnet-4-6",
            oc_model="anthropic/claude-haiku-4-5",
        )
        issues = _doctor._check_drift(["myshop"], do_fix=False)
        out = capsys.readouterr().out
        assert issues == 1
        assert "drift" in out

    def test_drift_fix_resyncs_and_clears_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(
            tmp_path,
            monkeypatch,
            meta_model="anthropic/claude-sonnet-4-6",
            oc_model="anthropic/claude-haiku-4-5",
        )
        monkeypatch.setattr(_doctor, "restart_gateway", lambda: True)
        issues = _doctor._check_drift(["myshop"], do_fix=True)
        assert issues == 0
        # openclaw.json model now matches meta.
        assert _oc.get_agent("myshop").model == "anthropic/claude-sonnet-4-6"  # type: ignore[union-attr]

    def test_drift_in_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        assert _doctor._check_drift(["myshop"], do_fix=False) == 0
        assert "in sync" in capsys.readouterr().out

    def test_budget_no_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        cost = {"myshop": ("", 0.0, 0)}
        assert _doctor._check_budget(["myshop"], cost) == 0
        assert "no cap" in capsys.readouterr().out

    def test_budget_over_cap_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        cost = {"myshop": ("10", 12.0, 5)}
        issues = _doctor._check_budget(["myshop"], cost)
        out = capsys.readouterr().out
        assert issues == 1
        assert "over budget" in out

    def test_runaway_flagged_by_turns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        cost = {"myshop": ("", 0.0, 500)}
        issues = _doctor._check_runaway(["myshop"], cost)
        out = capsys.readouterr().out
        assert issues == 1
        assert "runaway" in out

    def test_runaway_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        cost = {"myshop": ("", 1.0, 10)}
        assert _doctor._check_runaway(["myshop"], cost) == 0
        assert "ok" in capsys.readouterr().out

    def test_provider_coverage_missing_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)  # no secrets.json
        issues = _doctor._check_provider_coverage(["myshop"])
        out = capsys.readouterr().out
        assert issues == 1
        assert "ANTHROPIC_API_KEY" in out

    def test_provider_coverage_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        assert _doctor._check_provider_coverage(["myshop"]) == 0

    def test_security_gates_perms_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        # No openclaw CLI on PATH → gate report NA, audit unavailable, perms 600.
        issues = _doctor._check_security_gates()
        out = capsys.readouterr().out
        assert issues == 0
        assert "Config perms: 600" in out

    def test_security_gates_perms_world_readable_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        (oc_dir / "openclaw.json").chmod(0o644)
        issues = _doctor._check_security_gates()
        out = capsys.readouterr().out
        assert issues == 1
        assert "group/other-accessible" in out

    def test_template_version_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        assert _doctor._check_template_version(["myshop"]) == 0
        assert "v3 (current)" in capsys.readouterr().out

    def test_metadata_backfill_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        assert _doctor._check_metadata_backfill(["myshop"]) == 0
        assert "metadata" in capsys.readouterr().out.lower()


# ── full human run ─────────────────────────────────────────────────────────────


class TestFullRun:
    def test_human_healthy_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        monkeypatch.setattr(_doctor, "gateway_active", lambda: True)
        rc = _doctor.run_doctor(json_out=False)
        out = capsys.readouterr().out
        assert "All checks passed" in out
        assert rc == 0

    def test_human_degraded_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, full_workspace=False)
        monkeypatch.setattr(_doctor, "gateway_active", lambda: False)
        rc = _doctor.run_doctor(json_out=False)
        out = capsys.readouterr().out
        assert "critical issue(s) found" in out
        assert rc == 1

    def test_human_no_agents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        oc_dir = tmp_path / ".openclaw"
        (oc_dir / "workspaces" / "projects").mkdir(parents=True)
        (oc_dir / "openclaw.json").write_text(json.dumps(_OC_CONFIG))
        (oc_dir / "openclaw.json").chmod(0o600)
        _point_config_at(oc_dir, monkeypatch)
        monkeypatch.setattr(_doctor, "gateway_active", lambda: True)
        rc = _doctor.run_doctor(json_out=False)
        captured = capsys.readouterr()
        # The "no agents" notice is a warn() → stderr.
        assert "No project agents found" in captured.err
        assert rc == 0
