"""docket setup check: every individual check."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.support.fakes import FakeJail
from tests.support.pods import seed_setup_check_home as _seed

from docket.interfaces.cli.commands import setup_check as _setup_check
from docket.interfaces.cli.commands import setup_check_budget as _setup_check_budget
from docket.interfaces.cli.commands import setup_check_config as _setup_check_config
from docket.interfaces.cli.commands import setup_check_providers as _setup_check_providers
from docket.interfaces.cli.commands import setup_check_services as _setup_check_services
from docket.kernel.home import current_home, use_home
from docket.kernel.ports import SandboxAvailability
from docket.sandbox.launch import Launcher

SUBJECT = "docket.interfaces.cli.commands.setup_check"


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

    sdir = home / "state" / "sessions" / quote(session_key, safe="")
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
            fleet = json.loads((home / "state" / "fleet.json").read_text())
            fleet["bindings"] = [
                {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-100"}
            ]
            (home / "state").mkdir(parents=True, exist_ok=True)
            (home / "state" / "fleet.json").write_text(json.dumps(fleet))
            assert _setup_check._check_project_agents(["myshop"]) == 0
            out = capsys.readouterr().out
            assert "global fleet" in out
            assert "OK  →  group -100" in out

    def test_pod_lead_missing_tools_md_not_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A pod Lead never gets a TOOLS.md (`interfaces/cli/commands/pod.py` writes one only for an Implementer) — `docket setup --fix` must not flag that as broken."""
        with _seed(tmp_path, monkeypatch, full_workspace=False) as home:
            ws = home / "state" / "workspaces" / "projects" / "myshop"
            for f in ("SOUL.md", "AGENTS.md", "HEARTBEAT.md"):
                (ws / f).write_text(f"# {f}\n")
            meta_p = ws / ".docket-meta.json"
            data = json.loads(meta_p.read_text())
            data["role"] = "lead"
            meta_p.write_text(json.dumps(data))
            # Rename the workspace/agent so it resolves as a pod member (`pod_of`
            # requires the `<project>-<role>` shape).
            pod_ws = home / "state" / "workspaces" / "projects" / "demo-lead"
            ws.rename(pod_ws)
            fleet = json.loads((home / "state" / "fleet.json").read_text())
            fleet["agents"][0]["id"] = "demo-lead"
            (home / "state" / "fleet.json").write_text(json.dumps(fleet))

            issues = _setup_check._check_project_agents(["demo-lead"])
            out = capsys.readouterr().out
            assert issues == 0
            assert "missing TOOLS.md" not in out

    @staticmethod
    def _implementer_without_tools(home: Path, **extra_meta: object) -> None:
        """Rename the seeded agent to a pod Implementer holding no TOOLS.md, with *extra_meta*."""
        ws = home / "state" / "workspaces" / "projects" / "myshop"
        for f in ("SOUL.md", "AGENTS.md", "HEARTBEAT.md"):
            (ws / f).write_text(f"# {f}\n")
        meta_p = ws / ".docket-meta.json"
        data = json.loads(meta_p.read_text())
        data.update(role="implementer", **extra_meta)
        meta_p.write_text(json.dumps(data))
        ws.rename(home / "state" / "workspaces" / "projects" / "demo-implementer")
        fleet = json.loads((home / "state" / "fleet.json").read_text())
        fleet["agents"][0]["id"] = "demo-implementer"
        (home / "state" / "fleet.json").write_text(json.dumps(fleet))

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
            (home / "state" / "workspaces" / "projects" / "demo-implementer" / "SOUL.md").unlink()

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
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        bind_launcher: Callable[..., Launcher],
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            bind_launcher(landlock=False, seatbelt=False)
            issues = _setup_check_services._check_security_gates()
            out = capsys.readouterr().out
            assert issues == 0
            assert "Workspace isolation: off (default)" in out
            assert "docket setup sandbox on" in out
            assert "turns will be refused" not in out
            assert _setup_check._check_json_security()["isolation"] == "off (default)"

    def test_the_default_network_is_reported_as_not_enforced_while_isolation_is_off(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        bind_launcher: Callable[..., Launcher],
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            bind_launcher(landlock=True)
            _setup_check_services._check_security_gates()
            line = next(ln for ln in capsys.readouterr().out.splitlines() if "Network:" in ln)
            assert "not enforced: isolation off" in line
            assert "jailed tool calls have no network" not in line
            security = _setup_check._check_json_security()
            assert security["network"] == "none"
            assert security["networkEnforced"] is False

    def test_pods_and_no_usable_backend_is_an_issue(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        bind_launcher: Callable[..., Launcher],
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            bind_launcher(landlock=False, seatbelt=False)
            base = _setup_check._check_json()["issues"]
            bind_launcher(landlock=True)
            usable = _setup_check._check_json()
            assert base == usable["issues"] + 1
            assert usable["checks"]["securityGates"]["sandboxUsable"] is True
            bind_launcher(landlock=False, seatbelt=False)
            assert _setup_check_services._check_security_gates(["myshop"]) == 1
            assert "no usable sandbox backend" in capsys.readouterr().out

    def test_security_gates_names_the_backend_a_turn_would_use(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        bind_launcher: Callable[..., Launcher],
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            _isolation_on()
            bind_launcher(landlock=True)
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
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        bind_launcher: Callable[..., Launcher],
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            _isolation_on()
            bind_launcher(landlock=False, seatbelt=False)
            _setup_check_services._check_security_gates()
            out = capsys.readouterr().out
            assert "turns will be refused" in out
            assert "setup sandbox backend docker" in out and "setup sandbox off" in out

    def test_docker_backend_without_git_in_the_image_warns_with_the_fix(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_jail: FakeJail,
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            _isolation_on()
            fake_jail.availability = SandboxAvailability(backend="docker", docker=True)
            fake_jail.docker_has_git = False
            _setup_check_services._check_security_gates()
            out = capsys.readouterr().out
            assert "has no git" in out and "DOCKET_SANDBOX_IMAGE=<an image with git>" in out
            assert _setup_check._check_json_security()["dockerImageHasGit"] is False

    def test_docker_backend_with_git_in_the_image_is_quiet(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_jail: FakeJail,
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            _isolation_on()
            fake_jail.availability = SandboxAvailability(backend="docker", docker=True)
            fake_jail.docker_has_git = True
            _setup_check_services._check_security_gates()
            assert "has no git" not in capsys.readouterr().out
            assert _setup_check._check_json_security()["dockerImageHasGit"] is True

    def test_the_image_is_not_probed_when_docker_is_not_the_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            _isolation_on()
            fake_jail.availability = SandboxAvailability(backend="landlock", docker=False)

            def boom(*_a: object) -> bool:
                raise AssertionError("probed")

            fake_jail.docker_image_has_git = boom
            _setup_check_services._check_security_gates()
            assert _setup_check._check_json_security()["dockerImageHasGit"] is None

    def test_template_version_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            assert _setup_check_config._check_template_version(["myshop"]) == 0
            assert f"v{current_home().template_version} (current)" in capsys.readouterr().out
