"""`docket setup --fix` — system-wide health checks + JSON health probe.

Calls `run_check()` in-process with `DOCKET_HOME`/`FLEET_FILE`
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
from docket.cli import _setup_check
from docket.core import channel as _channel
from docket.edges import store as _store

SUBJECT = "docket.cli._setup_check"

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
    "templateVersion": str(_setup_check.TEMPLATE_VERSION),
}

_FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [],
    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _isolation_on() -> None:
    """Record `docket gates isolate on` in the seeded home."""
    from docket.core import fleet as _fleet

    _fleet.set_sandbox_isolation()


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
    notify: bool = True,
) -> Path:
    """Create a temp DOCKET_HOME with one myshop agent and repoint config; a healthy home
    has a channel that delivers beyond the console, so `desktop` is enabled unless asked not to."""
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
    if notify:
        _channel.enable_channel("desktop")
    return home


# ── JSON health-probe contract ─────────────────────────────────────────────────


class TestJsonProbe:
    def test_json_healthy_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Full workspace, registered, key present, in sync.
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        rc = _setup_check.run_check(json_out=True)
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
        rc = _setup_check.run_check(json_out=True)
        data = json.loads(capsys.readouterr().out)
        assert data["healthy"] is False
        assert data["issues"] > 0
        assert rc == 1

    def test_json_structure_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        _setup_check.run_check(json_out=True)
        checks = json.loads(capsys.readouterr().out)["checks"]
        for key in (
            "python3",
            "fleet",
            "agents",
            "budget",
            "runaway",
            "keyHygiene",
            "notifications",
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
        _setup_check.run_check(json_out=True)
        data = json.loads(capsys.readouterr().out)
        assert data["checks"]["fleet"]["ok"] is True
        assert data["checks"]["fleet"]["agents"] == 1


class TestNotifications:
    def test_agents_and_only_console_is_a_counted_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, notify=False)
        issues = _setup_check._check_notifications(["myshop"])
        out = capsys.readouterr().out
        assert issues == 1
        assert "docket channels enable desktop" in out
        assert "docket inbox" in out

    def test_no_agents_is_informational(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, notify=False, register=False)
        issues = _setup_check._check_notifications([])
        out = capsys.readouterr().out
        assert issues == 0
        assert "docket channels enable desktop" in out

    def test_a_delivering_channel_is_named_and_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        issues = _setup_check._check_notifications(["myshop"])
        out = capsys.readouterr().out
        assert issues == 0
        assert "desktop" in out
        assert "docket channels enable" not in out

    def test_json_names_the_delivering_channels(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        _setup_check.run_check(json_out=True)
        data = json.loads(capsys.readouterr().out)
        assert data["checks"]["notifications"] == {"ok": True, "delivering": ["desktop"]}
        assert data["healthy"] is True

    def test_json_only_console_with_an_agent_is_unhealthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}, notify=False)
        rc = _setup_check.run_check(json_out=True)
        data = json.loads(capsys.readouterr().out)
        assert data["checks"]["notifications"] == {"ok": False, "delivering": []}
        assert data["healthy"] is False
        assert rc == 1


# ── individual checks ──────────────────────────────────────────────────────────


class TestChecks:
    def test_project_agents_missing_files_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, full_workspace=False)
        issues = _setup_check._check_project_agents(["myshop"])
        out = capsys.readouterr().out
        assert issues == 1
        assert "missing AGENTS.md" in out

    def test_project_agents_not_registered_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, register=False)
        issues = _setup_check._check_project_agents(["myshop"])
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
        assert _setup_check._check_project_agents(["myshop"]) == 0
        out = capsys.readouterr().out
        assert "global fleet" in out
        assert "OK  →  group -100" in out

    def test_pod_lead_missing_tools_md_not_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A pod Lead never gets a TOOLS.md (`cli/_pod.py` writes one only for an Implementer) — `docket setup --fix` must not flag that as broken."""
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

        issues = _setup_check._check_project_agents(["demo-lead"])
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

        issues = _setup_check._check_project_agents(["demo-implementer"])
        out = capsys.readouterr().out
        assert issues == 1
        assert "missing TOOLS.md" in out

    def test_budget_no_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        cost = {"myshop": ("", 0.0, False)}
        assert _setup_check._check_budget(["myshop"], cost) == 0
        assert "no cap" in capsys.readouterr().out

    def test_budget_over_cap_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Recorded (non-estimated) spend over cap: flagged with a plain `$` figure, no
        estimate label."""
        _seed(tmp_path, monkeypatch)
        cost = {"myshop": ("10", 12.0, False)}
        issues = _setup_check._check_budget(["myshop"], cost)
        out = capsys.readouterr().out
        assert issues == 1
        assert "over budget" in out
        assert "estimated" not in out

    def test_budget_over_cap_from_estimate_when_nothing_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unit coverage of `_check_budget` reading an already-computed gating tuple -- see
        `test_doctor_run_flags_over_budget_from_estimate` below for the behavioural case that
        drives this through the real `run_check()` entry point."""
        home = _seed(tmp_path, monkeypatch, budget="0.01")
        _write_session(home, "agent:myshop:default", input_tokens=4000)

        gating = _setup_check._batch_gating_cost(["myshop"])
        issues = _setup_check._check_budget(["myshop"], gating)
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

        gating = _setup_check._batch_gating_cost(["myshop"])
        issues = _setup_check._check_budget(["myshop"], gating)
        out = capsys.readouterr().out

        assert issues == 0
        assert "84%" in out
        assert "estimated — no cost recorded" in out

    def test_doctor_run_flags_over_budget_from_estimate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Behavioural, through the real `run_check()` entry point: `DocketDriver` always
        records `cost_usd = 0.0`, so 4000 input tokens (~$0.012 at $3.00/1M) against a
        $0.01 cap must still be flagged, via the estimate, not raw recorded spend."""
        home = _seed(
            tmp_path, monkeypatch, budget="0.01", secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}
        )
        _write_session(home, "agent:myshop:default", input_tokens=4000)

        rc = _setup_check.run_check(json_out=False)
        out = capsys.readouterr().out

        assert "over budget" in out
        assert "estimated — no cost recorded" in out
        assert rc == 1

    def test_doctor_run_warns_at_80_percent_from_estimate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Behavioural mirror at the >=80% warning threshold, through `run_check()`: 2833
        input tokens estimate to ~$0.0085, 84% of a $0.01 cap."""
        home = _seed(
            tmp_path, monkeypatch, budget="0.01", secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}
        )
        _write_session(home, "agent:myshop:default", input_tokens=2833)

        _setup_check.run_check(json_out=False)
        out = capsys.readouterr().out

        assert "84%" in out
        assert "estimated — no cost recorded" in out
        assert "over budget" not in out

    def test_runaway_flagged_by_turns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        cost = {"myshop": ("", 0.0, 500)}
        issues = _setup_check._check_runaway(["myshop"], cost)
        out = capsys.readouterr().out
        assert issues == 1
        assert "runaway" in out

    def test_runaway_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        cost = {"myshop": ("", 1.0, 10)}
        assert _setup_check._check_runaway(["myshop"], cost) == 0
        assert "ok" in capsys.readouterr().out

    def test_provider_coverage_missing_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)  # no secrets.json
        issues = _setup_check._check_provider_coverage(["myshop"])
        out = capsys.readouterr().out
        assert issues == 1
        assert "ANTHROPIC_API_KEY" in out

    def test_provider_coverage_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        assert _setup_check._check_provider_coverage(["myshop"]) == 0

    def test_security_gates_always_on_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """There is no daemon exec-approval config/audit to check -- the tool-call gate is unconditionally active, and that is what this check reports."""
        _seed(tmp_path, monkeypatch)
        issues = _setup_check._check_security_gates()
        out = capsys.readouterr().out
        assert issues == 0
        assert "Tool-call gate: always active" in out

    def test_isolation_is_off_by_default_and_needs_no_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        issues = _setup_check._check_security_gates()
        out = capsys.readouterr().out
        assert issues == 0
        assert "Workspace isolation: off (default)" in out
        assert "docket gates isolate on" in out
        assert "turns will be refused" not in out
        assert _setup_check._check_json_security()["isolation"] == "off (default)"

    def test_security_gates_names_the_backend_a_turn_would_use(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _isolation_on()
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
        _setup_check._check_security_gates()
        assert "Workspace isolation: on, backend bwrap" in capsys.readouterr().out
        assert _setup_check._check_json_security() == {
            "toolCallGate": "always-on",
            "isolation": "on",
            "sandboxBackend": "bwrap",
            "dockerImageHasGit": None,
            "network": "open",
            "unjailedMcpServers": [],
        }

    def test_security_gates_reports_the_refusal_when_no_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _isolation_on()
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        _setup_check._check_security_gates()
        out = capsys.readouterr().out
        assert "turns will be refused" in out
        assert "bubblewrap" in out and "isolate off" in out

    def test_docker_backend_without_git_in_the_image_warns_with_the_fix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _isolation_on()
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
        monkeypatch.setattr(_setup_check._sys, "docker_image_has_git", lambda: False)
        _setup_check._check_security_gates()
        out = capsys.readouterr().out
        assert "has no git" in out and "DOCKET_SANDBOX_IMAGE=<an image with git>" in out
        assert _setup_check._check_json_security()["dockerImageHasGit"] is False

    def test_docker_backend_with_git_in_the_image_is_quiet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _isolation_on()
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
        monkeypatch.setattr(_setup_check._sys, "docker_image_has_git", lambda: True)
        _setup_check._check_security_gates()
        assert "has no git" not in capsys.readouterr().out
        assert _setup_check._check_json_security()["dockerImageHasGit"] is True

    def test_the_image_is_not_probed_when_docker_is_not_the_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _isolation_on()
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")

        def boom() -> bool:
            raise AssertionError("probed")

        monkeypatch.setattr(_setup_check._sys, "docker_image_has_git", boom)
        _setup_check._check_security_gates()
        assert _setup_check._check_json_security()["dockerImageHasGit"] is None

    def test_template_version_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        assert _setup_check._check_template_version(["myshop"]) == 0
        assert f"v{_setup_check.TEMPLATE_VERSION} (current)" in capsys.readouterr().out


# ── a leftover shared-agent directory is not the doctor's business ─────────────


def test_leftover_manager_directory_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
    (home / "workspaces" / "manager").mkdir(parents=True)
    (home / "workspaces" / "manager" / ".docket-meta.json").write_text("{}")

    rc = _setup_check.run_check(json_out=False, do_fix=True)

    assert rc == 0
    assert "workspaces/manager" not in capsys.readouterr().out
    assert not (home / "workspaces" / "manager" / "WORKFLOW_AUTO.md").exists()


# ── full human run ─────────────────────────────────────────────────────────────


class TestFullRun:
    def test_human_healthy_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        rc = _setup_check.run_check(json_out=False)
        out = capsys.readouterr().out
        assert "All checks passed" in out
        assert rc == 0

    def test_human_degraded_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, full_workspace=False)
        rc = _setup_check.run_check(json_out=False)
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
        rc = _setup_check.run_check(json_out=False)
        captured = capsys.readouterr()
        # The "no agents" notice is a warn() → stdout (mirrors Bash).
        assert "No project agents found" in captured.out
        assert rc == 0


class TestGuardrailPolicies:
    """Doctor reports a policy file the evaluator would fail closed on."""

    def test_reports_broken_policy_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        pol = _cfg.POLICIES_DIR
        pol.mkdir(parents=True, exist_ok=True)
        (pol / "zz-broken.json").write_text('{"id": "zz", not json')
        rc = _setup_check.run_check()
        out = capsys.readouterr().out
        assert rc == 1
        assert "zz-broken.json" in out

    def test_valid_store_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        rc = _setup_check.run_check()
        out = capsys.readouterr().out
        assert rc == 0
        assert "polic" in out.lower()


class TestScheduleConfig:
    """A bad spec is silently never due -- `_check_schedule_config` names the file,
    project key, and reason instead."""

    def test_no_file_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _point_config_at(tmp_path / ".docket", monkeypatch)
        assert _setup_check._check_schedule_config() == 0

    def test_bad_spec_is_flagged_by_project_and_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        _point_config_at(home, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.SCHEDULE_FILE.write_text(json.dumps({"schedules": {"shop": "@every 3x"}}))
        issues = _setup_check._check_schedule_config()
        out = capsys.readouterr().out
        assert issues == 1
        assert "shop" in out
        assert "3x" in out

    def test_valid_schedule_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        _point_config_at(home, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.SCHEDULE_FILE.write_text(json.dumps({"schedules": {"shop": "@every 30m"}}))
        assert _setup_check._check_schedule_config() == 0


class TestModelRegistryEntries:
    """A hand-broken `docket-models.json` entry is named, not silently ignored."""

    def test_no_file_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _point_config_at(tmp_path / ".docket", monkeypatch)
        assert _setup_check._check_model_registry_entries() == 0

    def test_hand_broken_entry_is_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        _point_config_at(home, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.MODEL_REGISTRY_FILE.write_text(json.dumps({"default": "not-a-model-id"}))
        issues = _setup_check._check_model_registry_entries()
        out = capsys.readouterr().out
        assert issues == 1
        assert "default" in out
        assert "not-a-model-id" in out


class TestArchetypeOverlay:
    """A malformed `docket-roles.json` overlay entry is named, not silently skipped."""

    def test_no_file_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _point_config_at(tmp_path / ".docket", monkeypatch)
        assert _setup_check._check_archetype_overlay() == 0

    def test_broken_role_is_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        _point_config_at(home, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.ARCHETYPE_REGISTRY_FILE.write_text(
            json.dumps({"roles": {"broken-role": {"name": "broken-role"}}})
        )
        issues = _setup_check._check_archetype_overlay()
        out = capsys.readouterr().out
        assert issues == 1
        assert "broken-role" in out


class TestProviderCatalog:
    """A malformed global provider document (docket-providers.json) is named, not
    silently skipped -- model-profiles.spec.md, "Provider catalog" requirement 7."""

    def test_no_file_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _point_config_at(tmp_path / ".docket", monkeypatch)
        assert _setup_check._check_provider_catalog() == 0

    def test_broken_auth_type_is_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        _point_config_at(home, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _store.write_json(
            _cfg.PROVIDERS_FILE,
            {
                "providers": {
                    "broken": {
                        "name": "broken",
                        "baseUrl": "https://example.com/v1",
                        "auth": {"type": "oauth"},
                    }
                }
            },
        )
        issues = _setup_check._check_provider_catalog()
        out = capsys.readouterr().out
        assert issues == 1
        assert str(_cfg.PROVIDERS_FILE) in out
        assert "auth.type" in out

        json_issues, problems = _setup_check._check_json_provider_catalog()
        assert json_issues == 1
        assert problems == [{"name": "broken", "reason": problems[0]["reason"]}]
        assert "auth.type" in problems[0]["reason"]


class TestPodConfigOverlays:
    """A malformed pod-scoped role overlay or policy file is named with the pod, not
    silently skipped -- the pod-scoped counterpart of `TestArchetypeOverlay`/
    `TestGuardrailPolicies`, which only ever look at the global files."""

    def _build_pod(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        from docket.cli import _pod

        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        _point_config_at(home, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        return home

    def test_no_pods_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _point_config_at(tmp_path / ".docket", monkeypatch)
        assert _setup_check._check_pod_config_overlays() == 0

    def test_pod_with_no_overlay_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._build_pod(tmp_path, monkeypatch)
        assert _setup_check._check_pod_config_overlays() == 0

    def test_broken_pod_role_overlay_is_named_by_pod(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._build_pod(tmp_path, monkeypatch)
        pod_roles = _cfg.pod_config_dir("demo") / "roles.json"
        pod_roles.parent.mkdir(parents=True, exist_ok=True)
        pod_roles.write_text(json.dumps({"roles": {"broken-role": {"name": "broken-role"}}}))
        issues = _setup_check._check_pod_config_overlays()
        out = capsys.readouterr().out
        assert issues == 1
        assert "demo" in out
        assert "broken-role" in out

    def test_broken_pod_policy_file_is_named_by_pod(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._build_pod(tmp_path, monkeypatch)
        pod_policies = _cfg.pod_config_dir("demo") / "policies"
        pod_policies.mkdir(parents=True, exist_ok=True)
        (pod_policies / "zz-broken.json").write_text('{"id": "zz", not json')
        issues = _setup_check._check_pod_config_overlays()
        out = capsys.readouterr().out
        assert issues == 1
        assert "demo" in out
        assert "zz-broken.json" in out

    def test_global_overlay_problem_is_not_double_counted_per_pod(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A pre-existing global overlay problem (already reported by
        `_check_archetype_overlay`) must not also show up here once per pod."""
        self._build_pod(tmp_path, monkeypatch)
        _cfg.ARCHETYPE_REGISTRY_FILE.write_text(
            json.dumps({"roles": {"broken-role": {"name": "broken-role"}}})
        )
        issues = _setup_check._check_pod_config_overlays()
        assert issues == 0


class TestDoctorSilentOnThreeFixtures:
    """`run_check()` flags all three fixtures below: a bad schedule, a bad models
    entry, and a bad archetype overlay."""

    def test_full_run_flags_all_three(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        _cfg.SCHEDULE_FILE.write_text(json.dumps({"schedules": {"shop": "@every 3x"}}))
        _cfg.MODEL_REGISTRY_FILE.write_text(json.dumps({"default": "not-a-model-id"}))
        _cfg.ARCHETYPE_REGISTRY_FILE.write_text(
            json.dumps({"roles": {"broken-role": {"name": "broken-role"}}})
        )
        rc = _setup_check.run_check(json_out=False)
        out = capsys.readouterr().out
        assert rc == 1
        assert "shop" in out and "3x" in out
        assert "not-a-model-id" in out
        assert "broken-role" in out


class TestPodSyncCheck:
    """`_check_pod_sync` -- the pod-member counterpart of `_check_template_version`,
    which explicitly skips pod members (they use their own template scheme)."""

    def _build_pod(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        from docket.cli import _pod

        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        _point_config_at(home, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        return home

    def test_in_sync_pod_reports_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._build_pod(tmp_path, monkeypatch)
        issues = _setup_check._check_pod_sync(["demo-lead", "demo-implementer"])
        out = capsys.readouterr().out
        assert issues == 0
        assert "✗" not in out
        assert "in sync" in out

    def test_stale_pod_member_is_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = self._build_pod(tmp_path, monkeypatch)
        (home / "workspaces" / "projects" / "demo-lead" / "SOUL.md").write_text(
            "STALE-HAND-EDITED-SOUL\n"
        )
        issues = _setup_check._check_pod_sync(["demo-lead", "demo-implementer"])
        out = capsys.readouterr().out
        assert "✗" in out
        assert "demo-lead" in out
        assert "docket pod <project> sync" in out
        # Advisory only, same as `_check_template_version`.
        assert issues == 0

    def test_non_pod_agents_are_skipped(self) -> None:
        assert _setup_check._check_pod_sync([]) == 0


class TestSummaryCountsOnlyCrosses:
    """The summary's critical count is the number of cross-marked lines, never warnings."""

    def _warn_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _check(*_a: Any, **_k: Any) -> int:
            _setup_check.ui.warn("  something advisory")
            return 1

        monkeypatch.setattr(_setup_check, "_check_exporters", _check)

    def test_a_warning_alone_is_not_critical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"})
        self._warn_only(monkeypatch)
        rc = _setup_check.run_check(json_out=False)
        out = capsys.readouterr().out
        assert "critical" not in out
        assert rc == 0

    def test_a_cross_is_critical_and_the_hint_is_a_real_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, full_workspace=False)
        self._warn_only(monkeypatch)
        rc = _setup_check.run_check(json_out=False)
        out = capsys.readouterr().out
        assert rc == 1
        crosses = sum(1 for ln in out.splitlines() if "✗" in ln)
        assert f"{crosses} critical issue(s) found" in out
        assert "docket setup --fix" in out
        assert "docket maintain" not in out.split("critical issue(s) found")[1]
