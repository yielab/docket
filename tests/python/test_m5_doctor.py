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
    "templateVersion": str(_doctor.TEMPLATE_VERSION),
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

# P19-6: agent registration + channel bindings + gates/isolation flags live in
# fleet.json now, not openclaw.json's `agents`/`bindings`/`security` above
# (which the daemon still owns until P19-7 and stays in `_OC_CONFIG`, used
# only for the pieces that are still genuinely daemon-owned, e.g. `channels`).
_FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [],
    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


@pytest.fixture(autouse=True)
def _no_restart(monkeypatch: pytest.MonkeyPatch, fake_openclaw: Path) -> None:
    """Never touch systemctl during doctor tests.

    ``fake_openclaw`` puts a real `openclaw` shim on PATH so the binary health
    check runs its real ``shutil.which`` probe (CI has no daemon) — the health
    result then reflects config state, not what's on the runner's PATH.
    """
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")


def _point_config_at(oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repoint the already-imported config + ACL modules at a temp OPENCLAW_DIR.

    Both docket.config and the openclaw ACL bind paths at import time, so we
    patch the live module attributes. We also stub the two ACL functions that
    shell out to the real `openclaw` CLI so tests stay hermetic regardless of
    what is on PATH.
    """
    cfg_file = oc_dir / "openclaw.json"
    fleet_file = oc_dir / "fleet.json"
    projects = oc_dir / "workspaces" / "projects"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", fleet_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", projects, raising=True)
    # ACL bound CONFIG_FILE / FLEET_FILE / meta_path directly at import — rebind them.
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "FLEET_FILE", fleet_file, raising=True)
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

    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps(_OC_CONFIG))
    cfg_file.chmod(0o600)

    fleet = json.loads(json.dumps(_FLEET_CONFIG))
    if not register:
        fleet["agents"] = []
    fleet_file = oc_dir / "fleet.json"
    fleet_file.write_text(json.dumps(fleet))
    fleet_file.chmod(0o600)

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
        fleet = json.loads((oc_dir / "fleet.json").read_text())
        fleet["bindings"] = [
            {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-100"}
        ]
        (oc_dir / "fleet.json").write_text(json.dumps(fleet))
        assert _doctor._check_project_agents(["myshop"]) == 0
        assert "OK  →  group -100" in capsys.readouterr().out

    def test_pod_lead_missing_tools_md_not_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A pod Lead never gets a TOOLS.md (`cli/_pod.py` writes one only for
        an Implementer) — `docket doctor` must not flag that as broken.
        """
        oc_dir = _seed(tmp_path, monkeypatch, full_workspace=False)
        ws = oc_dir / "workspaces" / "projects" / "myshop"
        for f in ("SOUL.md", "AGENTS.md", "HEARTBEAT.md"):
            (ws / f).write_text(f"# {f}\n")
        meta_p = ws / ".docket-meta.json"
        data = json.loads(meta_p.read_text())
        data["role"] = "lead"
        meta_p.write_text(json.dumps(data))
        # Rename the workspace/agent so it resolves as a pod member (`pod_of`
        # requires the `<project>-<role>` shape).
        pod_ws = oc_dir / "workspaces" / "projects" / "demo-lead"
        ws.rename(pod_ws)
        fleet = json.loads((oc_dir / "fleet.json").read_text())
        fleet["agents"][0]["id"] = "demo-lead"
        (oc_dir / "fleet.json").write_text(json.dumps(fleet))

        issues = _doctor._check_project_agents(["demo-lead"])
        out = capsys.readouterr().out
        assert issues == 0
        assert "missing TOOLS.md" not in out

    def test_pod_implementer_missing_tools_md_still_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unlike the Lead, an Implementer is still expected to have a TOOLS.md."""
        oc_dir = _seed(tmp_path, monkeypatch, full_workspace=False)
        ws = oc_dir / "workspaces" / "projects" / "myshop"
        for f in ("SOUL.md", "AGENTS.md", "HEARTBEAT.md"):
            (ws / f).write_text(f"# {f}\n")
        meta_p = ws / ".docket-meta.json"
        data = json.loads(meta_p.read_text())
        data["role"] = "implementer"
        meta_p.write_text(json.dumps(data))
        pod_ws = oc_dir / "workspaces" / "projects" / "demo-implementer"
        ws.rename(pod_ws)
        fleet = json.loads((oc_dir / "fleet.json").read_text())
        fleet["agents"][0]["id"] = "demo-implementer"
        (oc_dir / "fleet.json").write_text(json.dumps(fleet))

        issues = _doctor._check_project_agents(["demo-implementer"])
        out = capsys.readouterr().out
        assert issues == 1
        assert "missing TOOLS.md" in out

    def test_models_stale_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, meta_model="anthropic/claude-haiku-3-5")
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
        assert f"v{_doctor.TEMPLATE_VERSION} (current)" in capsys.readouterr().out

    def test_metadata_backfill_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        assert _doctor._check_metadata_backfill(["myshop"]) == 0
        assert "metadata" in capsys.readouterr().out.lower()

    def test_scope_backfilled_for_legacy_meta(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # AA-8: a meta written before `scope` existed gets it backfilled.
        oc_dir = _seed(tmp_path, monkeypatch)
        meta_p = oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json"
        data = json.loads(meta_p.read_text())
        data.pop("scope", None)
        meta_p.write_text(json.dumps(data))
        _doctor._check_metadata_backfill(["myshop"])
        assert json.loads(meta_p.read_text())["scope"] == "project"

    def test_legacy_project_role_singleton_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # AA-8: a leftover global programmer/reviewer/tester workspace is flagged.
        oc_dir = _seed(tmp_path, monkeypatch)
        (oc_dir / "workspaces" / "programmer").mkdir(parents=True)
        _doctor._check_metadata_backfill(["myshop"])
        out = capsys.readouterr().out
        assert "programmer" in out and "legacy shared specialist" in out


# ── Phase 17 C-4: specialists join the runtime contract healer ──────────────────


def _seed_bare_specialist(oc_dir: Path, role: str = "security") -> Path:
    """A specialist workspace with only `.docket-meta.json` — the exact
    pre-C-4 defect (`_provision_specialists` used to write nothing else).
    """
    ws = oc_dir / "workspaces" / role
    ws.mkdir(parents=True)
    ws.chmod(0o700)
    meta = {
        "kind": "specialist",
        "scope": "org",
        "role": role,
        "name": role,
        "model": "anthropic/claude-sonnet-4-6",
        "modelSource": "policy",
    }
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    (ws / ".docket-meta.json").chmod(0o600)
    return ws


class TestRuntimeContractSpecialists:
    def test_managed_workspace_ids_includes_provisioned_specialists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _seed_bare_specialist(oc_dir, "security")
        ids = _doctor._managed_workspace_ids(["myshop"])
        assert "myshop" in ids
        assert "security" in ids
        # Never-provisioned specialists (no workspace dir) are not included.
        assert "knowledge" not in ids

    def test_heals_missing_workflow_auto_for_specialist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import memory as _mem

        oc_dir = _seed(tmp_path, monkeypatch)
        ws = _seed_bare_specialist(oc_dir, "security")
        assert not (ws / _mem.REQUIRED_STARTUP_FILE).exists()

        issues = _doctor._check_runtime_contract(["myshop"])
        out = capsys.readouterr().out

        assert issues == 0  # advisory — never fails the run
        assert "security: seeded WORKFLOW_AUTO.md" in out
        assert _mem.contract_ok(ws)

    def test_heals_stale_contract_marker_for_specialist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import memory as _mem

        oc_dir = _seed(tmp_path, monkeypatch)
        ws = _seed_bare_specialist(oc_dir, "knowledge")
        (ws / _mem.REQUIRED_STARTUP_FILE).write_text("# Auto-generated workflow steps\n(legacy)\n")
        assert not _mem.contract_ok(ws)

        _doctor._check_runtime_contract(["myshop"])

        assert _mem.contract_ok(ws)
        assert "knowledge: seeded WORKFLOW_AUTO.md" in capsys.readouterr().out

    def test_does_not_touch_an_already_current_specialist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import memory as _mem

        # myshop (from _seed) has no WORKFLOW_AUTO.md of its own — isolate the
        # specialist-only assertion by checking just the "manager" agent.
        oc_dir = _seed(tmp_path, monkeypatch)
        ws = _seed_bare_specialist(oc_dir, "manager")
        _mem.seed_contract(ws, project="manager", codebase="")
        (ws / "MEMORY.md").write_text("real curated memory\n")

        _doctor._check_runtime_contract(["myshop"])

        out = capsys.readouterr().out
        assert "manager: seeded" not in out
        assert (ws / "MEMORY.md").read_text() == "real curated memory\n"

    def test_full_doctor_run_heals_specialist_and_fix_keeps_it_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """End-to-end: `docket doctor` (with --fix) repairs a specialist with a
        missing WORKFLOW_AUTO.md as part of a normal full run.
        """
        from docket.core import memory as _mem

        oc_dir = _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        ws = _seed_bare_specialist(oc_dir, "security")
        monkeypatch.setattr(_doctor, "gateway_active", lambda: True)

        _doctor.run_doctor(json_out=False, do_fix=True)

        assert _mem.contract_ok(ws)


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
        # The "no agents" notice is a warn() → stdout (mirrors Bash).
        assert "No project agents found" in captured.out
        assert rc == 0
