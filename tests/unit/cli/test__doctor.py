"""`docket doctor` — system-wide health checks + JSON health probe.

Calls `run_doctor()` in-process with `DOCKET_HOME`/`FLEET_FILE`
monkeypatched to a temp seed. stdout is captured to assert on the human
report; the return value is the process exit code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _doctor

SUBJECT = "docket.cli._doctor"

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

_FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [],
    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _point_config_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repoint the already-imported config module at a temp DOCKET_HOME."""
    repoint_docket_home(monkeypatch, home)


def _write_session(
    home: Path, session_key: str, *, input_tokens: int, output_tokens: int = 0
) -> None:
    """Seed a docket-native session with measured tokens and no recorded cost -- a
    pod-dispatch hop's turns land here through ``DocketDriver``, whose ``cost_usd`` is
    always ``0.0`` by design (see core/runtime_driver.py)."""
    from urllib.parse import quote

    sdir = home / "sessions" / quote(session_key, safe="")
    sdir.mkdir(parents=True, exist_ok=True)
    record = {
        "sessionKey": session_key,
        "created": "2024-03-15T10:00:00Z",
        "updated": "2024-03-15T10:00:00Z",
        "messages": [],
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cachedTokens": 0,
            "turns": 1,
        },
    }
    (sdir / "session.json").write_text(json.dumps(record))


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
    """Create a temp DOCKET_HOME with one myshop agent and repoint config."""
    home = tmp_path / ".docket"
    ws = home / "workspaces" / "projects" / "myshop"
    (ws / "memory").mkdir(parents=True)

    meta = {**_FULL_META, "model": meta_model}
    if budget is not None:
        meta["budgetUsd"] = budget
    (ws / ".docket-meta.json").write_text(json.dumps(meta))

    files = ("SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md") if full_workspace else ("SOUL.md",)
    for f in files:
        (ws / f).write_text(f"# {f}\n")

    fleet = json.loads(json.dumps(_FLEET_CONFIG))
    if not register:
        fleet["agents"] = []
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps(fleet))
    fleet_file.chmod(0o600)

    if secrets is not None:
        sfile = home / "secrets.json"
        sfile.write_text(json.dumps(secrets))
        sfile.chmod(0o600)

    _point_config_at(home, monkeypatch)
    return home


# ── JSON health-probe contract ─────────────────────────────────────────────────


class TestJsonProbe:
    def test_json_healthy_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Full workspace, registered, key present, in sync.
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        rc = _doctor.run_doctor(json_out=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["healthy"] is True
        assert data["issues"] == 0
        assert rc == 0

    def test_json_degraded_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Missing workspace files + missing provider key → issues.
        _seed(tmp_path, monkeypatch, full_workspace=False)
        rc = _doctor.run_doctor(json_out=True)
        data = json.loads(capsys.readouterr().out)
        assert data["healthy"] is False
        assert data["issues"] > 0
        assert rc == 1

    def test_json_structure_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        _doctor.run_doctor(json_out=True)
        checks = json.loads(capsys.readouterr().out)["checks"]
        for key in (
            "python3",
            "fleet",
            "agents",
            "modelConfig",
            "budget",
            "runaway",
            "keyHygiene",
            "securityGates",
            "templateDrift",
        ):
            assert key in checks
        # No daemon, so these keys are gone, not repointed -- a doctor --json
        # consumer must not expect them any more.
        retired_brand = "open" + "claw"
        for gone_key in (retired_brand, "gateway", "telegram"):
            assert gone_key not in checks

    def test_json_fleet_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        _doctor.run_doctor(json_out=True)
        data = json.loads(capsys.readouterr().out)
        assert data["checks"]["fleet"]["ok"] is True
        assert data["checks"]["fleet"]["agents"] == 1


# ── individual checks ──────────────────────────────────────────────────────────


class TestChecks:
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
        assert "not registered in fleet" in out

    def test_project_agents_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        # Add a channel binding so the agent hits the success (stdout) path.
        fleet = json.loads((home / "fleet.json").read_text())
        fleet["bindings"] = [
            {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-100"}
        ]
        (home / "fleet.json").write_text(json.dumps(fleet))
        assert _doctor._check_project_agents(["myshop"]) == 0
        out = capsys.readouterr().out
        assert "global fleet" in out
        assert "OK  →  group -100" in out

    def test_pod_lead_missing_tools_md_not_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A pod Lead never gets a TOOLS.md (`cli/_pod.py` writes one only for an Implementer) — `docket doctor` must not flag that as broken."""
        home = _seed(tmp_path, monkeypatch, full_workspace=False)
        ws = home / "workspaces" / "projects" / "myshop"
        for f in ("SOUL.md", "AGENTS.md", "HEARTBEAT.md"):
            (ws / f).write_text(f"# {f}\n")
        meta_p = ws / ".docket-meta.json"
        data = json.loads(meta_p.read_text())
        data["role"] = "lead"
        meta_p.write_text(json.dumps(data))
        # Rename the workspace/agent so it resolves as a pod member (`pod_of`
        # requires the `<project>-<role>` shape).
        pod_ws = home / "workspaces" / "projects" / "demo-lead"
        ws.rename(pod_ws)
        fleet = json.loads((home / "fleet.json").read_text())
        fleet["agents"][0]["id"] = "demo-lead"
        (home / "fleet.json").write_text(json.dumps(fleet))

        issues = _doctor._check_project_agents(["demo-lead"])
        out = capsys.readouterr().out
        assert issues == 0
        assert "missing TOOLS.md" not in out

    def test_pod_implementer_missing_tools_md_still_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unlike the Lead, an Implementer is still expected to have a TOOLS.md."""
        home = _seed(tmp_path, monkeypatch, full_workspace=False)
        ws = home / "workspaces" / "projects" / "myshop"
        for f in ("SOUL.md", "AGENTS.md", "HEARTBEAT.md"):
            (ws / f).write_text(f"# {f}\n")
        meta_p = ws / ".docket-meta.json"
        data = json.loads(meta_p.read_text())
        data["role"] = "implementer"
        meta_p.write_text(json.dumps(data))
        pod_ws = home / "workspaces" / "projects" / "demo-implementer"
        ws.rename(pod_ws)
        fleet = json.loads((home / "fleet.json").read_text())
        fleet["agents"][0]["id"] = "demo-implementer"
        (home / "fleet.json").write_text(json.dumps(fleet))

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
        cost = {"myshop": ("", 0.0, False)}
        assert _doctor._check_budget(["myshop"], cost) == 0
        assert "no cap" in capsys.readouterr().out

    def test_budget_over_cap_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Recorded (non-estimated) spend over cap: flagged with a plain `$` figure, no
        estimate label."""
        _seed(tmp_path, monkeypatch)
        cost = {"myshop": ("10", 12.0, False)}
        issues = _doctor._check_budget(["myshop"], cost)
        out = capsys.readouterr().out
        assert issues == 1
        assert "over budget" in out
        assert "estimated" not in out

    def test_budget_over_cap_from_estimate_when_nothing_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unit coverage of `_check_budget` reading an already-computed gating tuple -- see
        `test_doctor_run_flags_over_budget_from_estimate` below for the behavioural case that
        drives this through the real `run_doctor()` entry point."""
        home = _seed(tmp_path, monkeypatch, budget="0.01")
        _write_session(home, "agent:myshop:default", input_tokens=4000)

        gating = _doctor._batch_gating_cost(["myshop"])
        issues = _doctor._check_budget(["myshop"], gating)
        out = capsys.readouterr().out

        assert issues == 1
        assert "over budget" in out
        assert "estimated — no cost recorded" in out

    def test_budget_warns_at_80_percent_from_estimate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unit coverage mirroring the over-cap case at the >=80% threshold; see
        `test_doctor_run_warns_at_80_percent_from_estimate` below for the behavioural case."""
        home = _seed(tmp_path, monkeypatch, budget="0.01")
        _write_session(home, "agent:myshop:default", input_tokens=2833)

        gating = _doctor._batch_gating_cost(["myshop"])
        issues = _doctor._check_budget(["myshop"], gating)
        out = capsys.readouterr().out

        assert issues == 0
        assert "84%" in out
        assert "estimated — no cost recorded" in out

    def test_doctor_run_flags_over_budget_from_estimate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Behavioural, through the real `run_doctor()` entry point: `DocketDriver` always
        records `cost_usd = 0.0`, so 4000 input tokens (~$0.012 at $3.00/1M) against a
        $0.01 cap must still be flagged, via the estimate, not raw recorded spend."""
        home = _seed(
            tmp_path, monkeypatch, budget="0.01", secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}
        )
        _write_session(home, "agent:myshop:default", input_tokens=4000)

        rc = _doctor.run_doctor(json_out=False)
        out = capsys.readouterr().out

        assert "over budget" in out
        assert "estimated — no cost recorded" in out
        assert rc == 1

    def test_doctor_run_warns_at_80_percent_from_estimate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Behavioural mirror at the >=80% warning threshold, through `run_doctor()`: 2833
        input tokens estimate to ~$0.0085, 84% of a $0.01 cap."""
        home = _seed(
            tmp_path, monkeypatch, budget="0.01", secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}
        )
        _write_session(home, "agent:myshop:default", input_tokens=2833)

        _doctor.run_doctor(json_out=False)
        out = capsys.readouterr().out

        assert "84%" in out
        assert "estimated — no cost recorded" in out
        assert "over budget" not in out

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

    def test_security_gates_always_on_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """There is no daemon exec-approval config/audit to check -- the tool-call gate is unconditionally active, and that is what this check reports."""
        _seed(tmp_path, monkeypatch)
        issues = _doctor._check_security_gates()
        out = capsys.readouterr().out
        assert issues == 0
        assert "Tool-call gate: always active" in out

    def test_security_gates_reports_approval_routing_and_isolation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        fleet = json.loads((home / "fleet.json").read_text())
        fleet["security"]["approvalRoutingState"] = "on"
        fleet["security"]["approvalRoutingMode"] = "session"
        (home / "fleet.json").write_text(json.dumps(fleet))

        issues = _doctor._check_security_gates()
        out = capsys.readouterr().out
        assert issues == 0
        assert "Approval routing: on (mode=session)" in out

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
        # A meta written before `scope` existed gets it backfilled.
        home = _seed(tmp_path, monkeypatch)
        meta_p = home / "workspaces" / "projects" / "myshop" / ".docket-meta.json"
        data = json.loads(meta_p.read_text())
        data.pop("scope", None)
        meta_p.write_text(json.dumps(data))
        _doctor._check_metadata_backfill(["myshop"])
        assert json.loads(meta_p.read_text())["scope"] == "project"

    def test_legacy_project_role_singleton_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A leftover global programmer/reviewer/tester workspace is flagged.
        home = _seed(tmp_path, monkeypatch)
        (home / "workspaces" / "programmer").mkdir(parents=True)
        _doctor._check_metadata_backfill(["myshop"])
        out = capsys.readouterr().out
        assert "programmer" in out and "legacy shared specialist" in out


# ── specialists join the runtime contract healer ──────────────────


def _seed_bare_specialist(home: Path, role: str = "security") -> Path:
    """A specialist workspace with only `.docket-meta.json` -- provisioning
    must fill in the rest of the runtime contract, not leave a bare file.
    """
    ws = home / "workspaces" / role
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
        home = _seed(tmp_path, monkeypatch)
        _seed_bare_specialist(home, "security")
        ids = _doctor._managed_workspace_ids(["myshop"])
        assert "myshop" in ids
        assert "security" in ids
        # Never-provisioned specialists (no workspace dir) are not included.
        assert "knowledge" not in ids

    def test_heals_missing_workflow_auto_for_specialist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import memory as _mem

        home = _seed(tmp_path, monkeypatch)
        ws = _seed_bare_specialist(home, "security")
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

        home = _seed(tmp_path, monkeypatch)
        ws = _seed_bare_specialist(home, "knowledge")
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
        home = _seed(tmp_path, monkeypatch)
        ws = _seed_bare_specialist(home, "manager")
        _mem.seed_contract(ws, project="manager", codebase="")
        (ws / "MEMORY.md").write_text("real curated memory\n")

        _doctor._check_runtime_contract(["myshop"])

        out = capsys.readouterr().out
        assert "manager: seeded" not in out
        assert (ws / "MEMORY.md").read_text() == "real curated memory\n"

    def test_full_doctor_run_heals_specialist_and_fix_keeps_it_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """End-to-end: `docket doctor` (with --fix) repairs a specialist with a missing WORKFLOW_AUTO.md as part of a normal full run."""
        from docket.core import memory as _mem

        home = _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        ws = _seed_bare_specialist(home, "security")

        _doctor.run_doctor(json_out=False, do_fix=True)

        assert _mem.contract_ok(ws)


# ── full human run ─────────────────────────────────────────────────────────────


class TestFullRun:
    def test_human_healthy_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        rc = _doctor.run_doctor(json_out=False)
        out = capsys.readouterr().out
        assert "All checks passed" in out
        assert rc == 0

    def test_human_degraded_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, full_workspace=False)
        rc = _doctor.run_doctor(json_out=False)
        out = capsys.readouterr().out
        assert "critical issue(s) found" in out
        assert rc == 1

    def test_human_no_agents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": []}))
        (home / "fleet.json").chmod(0o600)
        _point_config_at(home, monkeypatch)
        rc = _doctor.run_doctor(json_out=False)
        captured = capsys.readouterr()
        # The "no agents" notice is a warn() → stdout (mirrors Bash).
        assert "No project agents found" in captured.out
        assert rc == 0


class TestWorkspaceEnvFiles:
    """A stray workspace `.env` has no reader on the live turn path -- credentials resolve
    through `core/secrets.py` directly, never a per-agent file. `--fix` deletes it."""

    def test_flags_a_stray_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        env_file = home / "workspaces" / "projects" / "myshop" / ".env"
        env_file.write_text('ANTHROPIC_API_KEY="sk-ant-x"\n')

        issues = _doctor._check_workspace_env_files(["myshop"], do_fix=False)
        out = capsys.readouterr().out

        assert issues == 1
        assert "myshop" in out and "stray .env" in out
        assert env_file.is_file()

    def test_fix_removes_the_stray_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        env_file = home / "workspaces" / "projects" / "myshop" / ".env"
        env_file.write_text('ANTHROPIC_API_KEY="sk-ant-x"\n')

        issues = _doctor._check_workspace_env_files(["myshop"], do_fix=True)
        out = capsys.readouterr().out

        assert issues == 0
        assert not env_file.exists()
        assert "removed stray .env" in out

    def test_no_env_file_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        assert _doctor._check_workspace_env_files(["myshop"], do_fix=False) == 0
        assert capsys.readouterr().out == ""

    def test_full_doctor_run_with_fix_heals_a_stray_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        env_file = home / "workspaces" / "projects" / "myshop" / ".env"
        env_file.write_text('ANTHROPIC_API_KEY="sk-ant-x"\n')

        rc = _doctor.run_doctor(json_out=False, do_fix=True)

        assert rc == 0
        assert not env_file.exists()


class TestGuardrailPolicies:
    """Doctor reports a policy file the evaluator would fail closed on."""

    def test_reports_broken_policy_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        pol = _cfg.POLICIES_DIR
        pol.mkdir(parents=True, exist_ok=True)
        (pol / "zz-broken.json").write_text('{"id": "zz", not json')
        rc = _doctor.run_doctor()
        out = capsys.readouterr().out
        assert rc == 1
        assert "zz-broken.json" in out

    def test_valid_store_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        rc = _doctor.run_doctor()
        out = capsys.readouterr().out
        assert rc == 0
        assert "polic" in out.lower()
