"""`docket setup --fix` — system-wide health checks + JSON health probe.

Calls `run_check()` in-process with `DOCKET_HOME`/`FLEET_FILE`
monkeypatched to a temp seed. stdout is captured to assert on the human
report; the return value is the process exit code.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.support.home import point_config_at as _point_config_at
from tests.support.pods import build_pod
from tests.support.pods import seed_4 as _seed

from docket.interfaces.cli.commands import setup_check as _setup_check
from docket.interfaces.cli.commands import setup_check_budget as _setup_check_budget
from docket.interfaces.cli.commands import setup_check_config as _setup_check_config
from docket.interfaces.cli.commands import setup_check_providers as _setup_check_providers
from docket.interfaces.cli.commands import setup_check_services as _setup_check_services
from docket.kernel.home import current_home, use_home
from docket.operator import channel as _channel
from docket.sandbox import docker as _sandbox_docker

SUBJECT = "docket.interfaces.cli.commands.setup_check"

# ── seed helpers ───────────────────────────────────────────────────────────────

_FULL_META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "type": "repo",
    "name": "My Shop",
    "model": "anthropic/claude-sonnet-4-6",
    "stack": "Node.js",
    "codebase": "/tmp/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
    "templateVersion": str(current_home().template_version),
}

_FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [],
    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _isolation_on() -> None:
    """Record `docket setup sandbox on` in the seeded home."""
    from docket.teams import fleet as _fleet

    _fleet.set_sandbox_isolation()


def _write_session(
    home: Path, session_key: str, *, input_tokens: int, output_tokens: int = 0
) -> None:
    """Seed a docket-native session with measured tokens and no recorded cost -- a
    pod-dispatch hop's turns land here through ``DocketDriver``, whose ``cost_usd`` is
    always ``0.0`` by design (see agent/ports.py)."""
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


# ── JSON health-probe contract ─────────────────────────────────────────────────


class TestJsonProbe:
    def test_json_healthy_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Full workspace, registered, key present, in sync.
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}):
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
        with _seed(tmp_path, monkeypatch, full_workspace=False):
            rc = _setup_check.run_check(json_out=True)
            data = json.loads(capsys.readouterr().out)
            assert data["healthy"] is False
            assert data["issues"] > 0
            assert rc == 1

    def test_json_structure_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}):
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
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}):
            _setup_check.run_check(json_out=True)
            data = json.loads(capsys.readouterr().out)
            assert data["checks"]["fleet"]["ok"] is True
            assert data["checks"]["fleet"]["agents"] == 1


# ── individual checks ──────────────────────────────────────────────────────────


class TestChecks:
    def test_project_agents_missing_files_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, full_workspace=False):
            issues = _setup_check._check_project_agents(["myshop"])
            out = capsys.readouterr().out
            assert issues == 1
            assert "missing AGENTS.md" in out

    def test_project_agents_not_registered_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, register=False):
            issues = _setup_check._check_project_agents(["myshop"])
            out = capsys.readouterr().out
            assert issues == 1
            assert "not registered in fleet" in out

    def test_project_agents_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch) as home:
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
        """A pod Lead never gets a TOOLS.md (`interfaces/cli/commands/pod.py` writes one only for an Implementer) — `docket setup --fix` must not flag that as broken."""
        with _seed(tmp_path, monkeypatch, full_workspace=False) as home:
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

    @staticmethod
    def _implementer_without_tools(home: Path, **extra_meta: object) -> None:
        """Rename the seeded agent to a pod Implementer holding no TOOLS.md, with *extra_meta*."""
        ws = home / "workspaces" / "projects" / "myshop"
        for f in ("SOUL.md", "AGENTS.md", "HEARTBEAT.md"):
            (ws / f).write_text(f"# {f}\n")
        meta_p = ws / ".docket-meta.json"
        data = json.loads(meta_p.read_text())
        data.update(role="implementer", **extra_meta)
        meta_p.write_text(json.dumps(data))
        ws.rename(home / "workspaces" / "projects" / "demo-implementer")
        fleet = json.loads((home / "fleet.json").read_text())
        fleet["agents"][0]["id"] = "demo-implementer"
        (home / "fleet.json").write_text(json.dumps(fleet))

    @pytest.mark.parametrize(
        "extra",
        [
            {"verifyCmd": "pytest -q"},
            {"portRangeStart": 4100, "portRangeCount": 10, "scratchDir": "/tmp/scratch"},
        ],
    )
    def test_pod_implementer_that_provisioning_gives_a_tools_md_is_flagged_without_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        extra: dict[str, object],
    ) -> None:
        """An Implementer with a verify command or allocated resources is written a TOOLS.md."""
        with _seed(tmp_path, monkeypatch, full_workspace=False) as home:
            self._implementer_without_tools(home, **extra)

            issues = _setup_check._check_project_agents(["demo-implementer"])

            assert issues == 1
            assert "missing TOOLS.md" in capsys.readouterr().out

    def test_pod_implementer_with_nothing_to_document_is_not_flagged_for_tools_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Provisioning writes no TOOLS.md for an Implementer without resources or a verify command."""
        with _seed(tmp_path, monkeypatch, full_workspace=False) as home:
            self._implementer_without_tools(home)

            issues = _setup_check._check_project_agents(["demo-implementer"])

            assert issues == 0
            assert "missing TOOLS.md" not in capsys.readouterr().out

    def test_a_pod_member_missing_a_file_is_pointed_at_pod_update_not_setup_fix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`setup --fix` rewrites no workspace file; `pod update` re-renders a missing one."""
        with _seed(tmp_path, monkeypatch, full_workspace=False) as home:
            self._implementer_without_tools(home)
            (home / "workspaces" / "projects" / "demo-implementer" / "SOUL.md").unlink()

            assert _setup_check._check_project_agents(["demo-implementer"]) == 1

            out = capsys.readouterr().out
            assert "missing SOUL.md" in out
            assert "docket pod update --pod demo" in out
            assert "docket setup --fix" not in out

    def test_budget_no_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            cost = {"myshop": ("", 0.0, False)}
            assert _setup_check_budget._check_budget(["myshop"], cost) == 0
            assert "no cap" in capsys.readouterr().out

    def test_budget_over_cap_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Recorded (non-estimated) spend over cap: flagged with a plain `$` figure, no
        estimate label."""
        with _seed(tmp_path, monkeypatch):
            cost = {"myshop": ("10", 12.0, False)}
            issues = _setup_check_budget._check_budget(["myshop"], cost)
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
        with _seed(tmp_path, monkeypatch, budget="0.01") as home:
            _write_session(home, "agent:myshop:default", input_tokens=4000)

            gating = _setup_check_budget._batch_gating_cost(["myshop"])
            issues = _setup_check_budget._check_budget(["myshop"], gating)
            out = capsys.readouterr().out

            assert issues == 1
            assert "over budget" in out
            assert "estimated — no cost recorded" in out

    def test_budget_warns_at_80_percent_from_estimate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unit coverage mirroring the over-cap case at the >=80% threshold; see
        `test_doctor_run_warns_at_80_percent_from_estimate` below for the behavioural case."""
        with _seed(tmp_path, monkeypatch, budget="0.01") as home:
            _write_session(home, "agent:myshop:default", input_tokens=2833)

            gating = _setup_check_budget._batch_gating_cost(["myshop"])
            issues = _setup_check_budget._check_budget(["myshop"], gating)
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
        with _seed(
            tmp_path, monkeypatch, budget="0.01", secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}
        ) as home:
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
        with _seed(
            tmp_path, monkeypatch, budget="0.01", secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}
        ) as home:
            _write_session(home, "agent:myshop:default", input_tokens=2833)

            _setup_check.run_check(json_out=False)
            out = capsys.readouterr().out

            assert "84%" in out
            assert "estimated — no cost recorded" in out
            assert "over budget" not in out

    def test_runaway_flagged_by_turns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            cost = {"myshop": ("", 0.0, 500)}
            issues = _setup_check_budget._check_runaway(["myshop"], cost)
            out = capsys.readouterr().out
            assert issues == 1
            assert "runaway" in out

    def test_the_runaway_thresholds_follow_the_current_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            cost = {"myshop": ("", 1.0, 10)}
            assert _setup_check_budget._check_runaway(["myshop"], cost) == 0
            strict = dataclasses.replace(current_home(), runaway_turns_threshold=5)
            with use_home(strict):
                assert _setup_check_budget._check_runaway(["myshop"], cost) == 1

    def test_runaway_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            cost = {"myshop": ("", 1.0, 10)}
            assert _setup_check_budget._check_runaway(["myshop"], cost) == 0
            assert "ok" in capsys.readouterr().out

    def test_provider_coverage_missing_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            issues = _setup_check_providers._check_provider_coverage(["myshop"])
            out = capsys.readouterr().out
            assert issues == 1
            assert "ANTHROPIC_API_KEY" in out

    def test_provider_coverage_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}):
            assert _setup_check_providers._check_provider_coverage(["myshop"]) == 0

    def test_security_gates_always_on_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """There is no daemon exec-approval config/audit to check -- the tool-call gate is unconditionally active, and that is what this check reports."""
        with _seed(tmp_path, monkeypatch):
            issues = _setup_check_services._check_security_gates()
            out = capsys.readouterr().out
            assert issues == 0
            assert "Tool-call gate: always active" in out

    def test_isolation_is_off_by_default_and_needs_no_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
            issues = _setup_check_services._check_security_gates()
            out = capsys.readouterr().out
            assert issues == 0
            assert "Workspace isolation: off (default)" in out
            assert "docket setup sandbox on" in out
            assert "turns will be refused" not in out
            assert _setup_check._check_json_security()["isolation"] == "off (default)"

    def test_the_default_network_is_reported_as_not_enforced_while_isolation_is_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
            _setup_check_services._check_security_gates()
            line = next(ln for ln in capsys.readouterr().out.splitlines() if "Network:" in ln)
            assert "not enforced: isolation off" in line
            assert "jailed tool calls have no network" not in line
            security = _setup_check._check_json_security()
            assert security["network"] == "none"
            assert security["networkEnforced"] is False

    def test_pods_and_no_usable_backend_is_an_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
            base = _setup_check._check_json()["issues"]
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
            usable = _setup_check._check_json()
            assert base == usable["issues"] + 1
            assert usable["checks"]["securityGates"]["sandboxUsable"] is True
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
            assert _setup_check_services._check_security_gates(["myshop"]) == 1
            assert "no usable sandbox backend" in capsys.readouterr().out

    def test_security_gates_names_the_backend_a_turn_would_use(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            _isolation_on()
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
            _setup_check_services._check_security_gates()
            assert "Workspace isolation: on, backend landlock" in capsys.readouterr().out
            assert _setup_check._check_json_security() == {
                "toolCallGate": "always-on",
                "isolation": "on",
                "sandboxBackend": "landlock",
                "sandboxUsable": True,
                "dockerImageHasGit": None,
                "network": "none",
                "networkEnforced": True,
            }

    def test_security_gates_reports_the_refusal_when_no_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            _isolation_on()
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
            _setup_check_services._check_security_gates()
            out = capsys.readouterr().out
            assert "turns will be refused" in out
            assert "setup sandbox backend docker" in out and "setup sandbox off" in out

    def test_docker_backend_without_git_in_the_image_warns_with_the_fix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            _isolation_on()
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
            monkeypatch.setattr(_sandbox_docker, "docker_image_has_git", lambda: False)
            _setup_check_services._check_security_gates()
            out = capsys.readouterr().out
            assert "has no git" in out and "DOCKET_SANDBOX_IMAGE=<an image with git>" in out
            assert _setup_check._check_json_security()["dockerImageHasGit"] is False

    def test_docker_backend_with_git_in_the_image_is_quiet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            _isolation_on()
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
            monkeypatch.setattr(_sandbox_docker, "docker_image_has_git", lambda: True)
            _setup_check_services._check_security_gates()
            assert "has no git" not in capsys.readouterr().out
            assert _setup_check._check_json_security()["dockerImageHasGit"] is True

    def test_the_image_is_not_probed_when_docker_is_not_the_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            _isolation_on()
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")

            def boom() -> bool:
                raise AssertionError("probed")

            monkeypatch.setattr(_sandbox_docker, "docker_image_has_git", boom)
            _setup_check_services._check_security_gates()
            assert _setup_check._check_json_security()["dockerImageHasGit"] is None

    def test_template_version_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            assert _setup_check_config._check_template_version(["myshop"]) == 0
            assert f"v{current_home().template_version} (current)" in capsys.readouterr().out


# ── a leftover shared-agent directory is not the doctor's business ─────────────


def test_leftover_manager_directory_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}) as home:
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
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}):
            rc = _setup_check.run_check(json_out=False)
            out = capsys.readouterr().out
            assert "All checks passed" in out
            assert rc == 0

    def test_human_degraded_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, full_workspace=False):
            rc = _setup_check.run_check(json_out=False)
            out = capsys.readouterr().out
            assert "critical issue(s) found" in out
            assert rc == 1

    def test_human_no_agents(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": []}))
        (home / "fleet.json").chmod(0o600)
        with _point_config_at(home):
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
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}):
            pol = current_home().policies_dir
            pol.mkdir(parents=True, exist_ok=True)
            (pol / "zz-broken.json").write_text('{"id": "zz", not json')
            rc = _setup_check.run_check()
            out = capsys.readouterr().out
            assert rc == 1
            assert "zz-broken.json" in out

    def test_valid_store_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}):
            rc = _setup_check.run_check()
            out = capsys.readouterr().out
            assert rc == 0
            assert "polic" in out.lower()


class TestScheduleConfig:
    """A bad spec is silently never due -- `_check_schedule_config` names the file,
    project key, and reason instead."""

    def test_no_file_is_healthy(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with _point_config_at(tmp_path / ".docket"):
            assert _setup_check._check_schedule_config() == 0

    def test_bad_spec_is_flagged_by_project_and_reason(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        with _point_config_at(home):
            home.mkdir(parents=True, exist_ok=True)
            current_home().schedule_file.write_text(
                json.dumps({"schedules": {"shop": "@every 3x"}})
            )
            issues = _setup_check._check_schedule_config()
            out = capsys.readouterr().out
            assert issues == 1
            assert "shop" in out
            assert "3x" in out

    def test_valid_schedule_is_healthy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        with _point_config_at(home):
            home.mkdir(parents=True, exist_ok=True)
            current_home().schedule_file.write_text(
                json.dumps({"schedules": {"shop": "@every 30m"}})
            )
            assert _setup_check._check_schedule_config() == 0


class TestModelRegistryEntries:
    """A hand-broken `docket-models.json` entry is named, not silently ignored."""

    def test_no_file_is_healthy(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with _point_config_at(tmp_path / ".docket"):
            assert _setup_check._check_model_registry_entries() == 0

    def test_hand_broken_entry_is_named(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        with _point_config_at(home):
            home.mkdir(parents=True, exist_ok=True)
            current_home().model_registry_file.write_text(json.dumps({"default": "not-a-model-id"}))
            issues = _setup_check._check_model_registry_entries()
            out = capsys.readouterr().out
            assert issues == 1
            assert "default" in out
            assert "not-a-model-id" in out


class TestDoctorSilentOnTwoFixtures:
    """`run_check()` flags both fixtures below: a bad schedule and a bad models entry."""

    def test_full_run_flags_both(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}):
            current_home().schedule_file.write_text(
                json.dumps({"schedules": {"shop": "@every 3x"}})
            )
            current_home().model_registry_file.write_text(json.dumps({"default": "not-a-model-id"}))
            rc = _setup_check.run_check(json_out=False)
            out = capsys.readouterr().out
            assert rc == 1
            assert "shop" in out and "3x" in out
            assert "not-a-model-id" in out


class TestSummaryCountsOnlyCrosses:
    """The summary's critical count is the number of cross-marked lines, never warnings."""

    def _warn_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _check(*_a: Any, **_k: Any) -> int:
            _setup_check.ui.warn("  something advisory")
            return 1

        monkeypatch.setattr(_setup_check_services, "_check_exporters", _check)

    def test_a_warning_alone_is_not_critical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}):
            self._warn_only(monkeypatch)
            rc = _setup_check.run_check(json_out=False)
            out = capsys.readouterr().out
            assert "critical" not in out
            assert rc == 0

    def test_a_cross_is_critical_and_the_hint_is_a_real_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, full_workspace=False):
            self._warn_only(monkeypatch)
            rc = _setup_check.run_check(json_out=False)
            out = capsys.readouterr().out
            assert rc == 1
            crosses = sum(1 for ln in out.splitlines() if "✗" in ln)
            assert f"{crosses} critical issue(s) found" in out
            assert "docket setup --fix" in out


class TestJsonCoversEveryTextCheck:
    """The JSON report and the text report derive the verdict from the same check data."""

    @contextmanager
    def _pod_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
        from docket.interfaces.cli.commands import pod as _pod

        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with _point_config_at(home):
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
            _channel.enable_channel("desktop")
            build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
            yield home

    def _json(self, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
        capsys.readouterr()
        _setup_check.run_check(json_out=True)
        return json.loads(capsys.readouterr().out)

    def test_broken_pod_overlay_is_unhealthy_in_both_reports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with self._pod_home(tmp_path, monkeypatch):
            roles = current_home().pod_config_dir("demo") / "roles.json"
            roles.parent.mkdir(parents=True, exist_ok=True)
            roles.write_text(json.dumps({"roles": {"broken-role": {"name": "broken-role"}}}))
            data = self._json(capsys)
            assert data["healthy"] is False
            overlays = data["checks"]["podConfigOverlays"]
            assert overlays["ok"] is False
            assert overlays["problems"][0]["pod"] == "demo"
            assert _setup_check.run_check(json_out=False) == 1

    def test_no_delivering_channel_with_a_pod_is_an_issue_in_both_reports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with self._pod_home(tmp_path, monkeypatch):
            _channel.disable_channel("desktop")
            assert self._json(capsys)["healthy"] is False
            warning = _channel.unreached_warning(_channel.load_catalog().delivering())
            assert warning is not None
            _setup_check.run_check(json_out=False)
            lines = capsys.readouterr().out.splitlines()
            assert any("✗" in ln and warning.splitlines()[0] in ln for ln in lines)

    def test_global_config_problems_are_reported_under_stable_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "test-key"}):
            current_home().schedule_file.write_text(
                json.dumps({"schedules": {"shop": "@every 3x"}})
            )
            current_home().model_registry_file.write_text(json.dumps({"default": "not-a-model-id"}))
            data = self._json(capsys)
            checks = data["checks"]
            assert data["healthy"] is False
            assert checks["modelRegistry"]["problems"][0]["key"]
            assert checks["schedules"]["problems"][0]["key"] == "shop"

    def test_a_clean_home_reports_every_new_check_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with self._pod_home(tmp_path, monkeypatch):
            checks = self._json(capsys)["checks"]
            for key in (
                "modelRegistry",
                "schedules",
                "exporters",
                "guardrailPolicies",
                "podConfigOverlays",
                "podSync",
                "runtimeContract",
            ):
                assert checks[key]["ok"] is True, key

    def test_a_stale_pod_member_counts_in_the_json_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with self._pod_home(tmp_path, monkeypatch) as home:
            (home / "workspaces" / "projects" / "demo-lead" / "SOUL.md").write_text("STALE\n")
            data = self._json(capsys)
            assert data["checks"]["podSync"]["stale"][0]["id"] == "demo-lead"
            assert data["healthy"] is False
