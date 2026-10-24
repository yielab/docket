"""docket setup check: the JSON probe, the full run and the schedule config."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.support.home import point_config_at as _point_config_at
from tests.support.pods import build_pod
from tests.support.pods import seed_setup_check_home as _seed

from docket.interfaces.cli.commands import setup_check as _setup_check
from docket.interfaces.cli.commands import setup_check_services as _setup_check_services
from docket.kernel.home import current_home
from docket.operator import channel as _channel

SUBJECT = "docket.interfaces.cli.commands.setup_check"


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


class TestSummaryCountsOnlyCrosses:
    """The summary's critical count is the number of cross-marked lines, never warnings."""

    def _warn_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _check(*_a: Any, **_k: Any) -> int:
            _setup_check.ui.warn("  something advisory")
            return 1

        monkeypatch.setattr(_setup_check_services, "check_exporters", _check)

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
