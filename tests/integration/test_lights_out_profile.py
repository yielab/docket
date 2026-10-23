"""The ``lights-out`` profile: a task is refused before its first hop unless every requirement holds.

Specs: security-gates.spec.md "Profiles", cli-interface.spec.md (``setup profile``),
operator-loop.spec.md "Profile lines".
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.conftest import record_isolation_off, record_isolation_on
from tests.fakes import FakeDriver
from tests.pods import build_pod
from typer.testing import CliRunner

from docket.cli import _pod
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import mcp_tools as _mcp
from docket.core import pipeline as _pipeline
from docket.core import pod as _pod_core
from docket.core import secrets as _secrets
from docket.edges.adapters import system as _system
from docket.kernel.home import Home, use_home

SUBJECT = "docket.core"

_GATED = """\
name: gated
steps:
  - id: plan
    role: lead
  - id: build
    role: implementer
    gate: {external: "true"}
"""

_UNGATED = """\
name: ungated
steps:
  - id: plan
    role: lead
  - id: build
    role: implementer
"""

_USABLE = _system.SandboxAvailability(backend="landlock", docker=False, landlock=True)
_NONE = _system.SandboxAvailability(backend="none", docker=False)


def _spec(text: str) -> _pipeline.PipelineSpec:
    loaded = _pipeline.load_pipeline(text)
    assert loaded.ok, loaded.errors
    assert loaded.spec is not None
    return loaded.spec


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    root = tmp_path / ".docket"
    (root / "workspaces" / "projects").mkdir(parents=True)
    (root / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(root)):
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        _fleet.meta_set("demo-implementer", "codebase", str(tmp_path))
        yield root


def _meet_everything(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record_isolation_on(root)
    monkeypatch.setattr(_system, "sandbox_availability", lambda *a, **k: _USABLE)
    _fleet.set_network_mode("none")
    _fleet.set_profile("lights-out")


def _dispatch_one(spec_text: str) -> tuple[_dispatch.TaskResult, FakeDriver]:
    _dispatch.enqueue_task("demo", "Ship it", channel="cli")
    driver = FakeDriver()
    res = _dispatch.dispatch_pod("demo", runner=driver, spec=_spec(spec_text))[0]
    return res, driver


def _refused(res: _dispatch.TaskResult, driver: FakeDriver, requirement: str) -> None:
    assert res.status == "failed"
    assert res.failure_kind == "dispatch_refused"
    assert requirement in (res.reason or "")
    assert driver.calls == []
    entries = [e for e in _audit.read_audit() if e["action"] == "profile.refused"]
    assert entries
    assert "pod=demo" in entries[-1]["detail"]
    assert requirement in entries[-1]["detail"]


class TestRefusals:
    def test_isolation_off_refuses(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _meet_everything(home, monkeypatch)
        record_isolation_off(home)

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "isolation")
        assert "docket setup sandbox on" in (res.reason or "")

    def test_isolation_without_a_backend_refuses(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _meet_everything(home, monkeypatch)
        monkeypatch.setattr(_system, "sandbox_availability", lambda *a, **k: _NONE)

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "isolation")

    def test_open_network_refuses(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _meet_everything(home, monkeypatch)
        _fleet.set_network_mode("open")

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "network")

    def test_an_unrecorded_network_none_refuses(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _meet_everything(home, monkeypatch)
        data = json.loads((home / "fleet.json").read_text())
        data["security"]["networkMode"] = "unset"
        (home / "fleet.json").write_text(json.dumps(data))

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "network")

    def test_a_pod_level_network_none_satisfies_it(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _meet_everything(home, monkeypatch)
        _fleet.set_network_mode("open")
        _fleet.meta_set("demo-lead", "network", "none")

        res, driver = _dispatch_one(_GATED)

        assert res.failure_kind != "dispatch_refused"
        assert driver.calls

    def test_an_implementer_step_without_an_external_gate_refuses(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _meet_everything(home, monkeypatch)

        res, driver = _dispatch_one(_UNGATED)

        _refused(res, driver, "external-gate")
        assert "build" in (res.reason or "")

    def test_an_injected_variable_named_in_the_secret_store_refuses(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _meet_everything(home, monkeypatch)
        _secrets.save_secrets({"MY_TOKEN": "x"})
        _mcp.write_pod_mcp_servers(
            "demo", [_mcp.McpServerConfig(name="s", command="true", env={"MY_TOKEN": "y"})]
        )

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "secrets")
        assert "MY_TOKEN" in (res.reason or "")

    def test_the_refusal_is_resumable(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _meet_everything(home, monkeypatch)
        record_isolation_off(home)
        res, _driver = _dispatch_one(_GATED)
        assert res.failure_kind in _dispatch.RESUMABLE_FAILURE_KINDS


class TestPositive:
    def test_every_requirement_met_runs_the_task(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _meet_everything(home, monkeypatch)

        res, driver = _dispatch_one(_GATED)

        assert res.failure_kind != "dispatch_refused"
        assert any(call[0].endswith("-implementer") for call in driver.calls)
        assert not [e for e in _audit.read_audit() if e["action"] == "profile.refused"]


class TestAttendedChangesNothing:
    def test_no_record_runs_an_ungated_pipeline(self, home: Path) -> None:
        record_isolation_off(home)

        res, driver = _dispatch_one(_UNGATED)

        assert res.status == "done"
        assert driver.calls

    def test_a_pod_profile_alone_opts_that_pod_in(self, home: Path) -> None:
        record_isolation_off(home)
        _fleet.meta_set("demo-lead", "profile", "lights-out")

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "isolation")


class TestStricterOnly:
    def test_a_pod_cannot_be_weaker_than_the_fleet(self, home: Path) -> None:
        _fleet.set_profile("lights-out")

        with pytest.raises(_pod_core.PodSettingsError, match="stricter"):
            _pod_core.PodSettings.coerce("profile", "attended", project="demo")

        assert _pod_core.PodSettings.coerce("profile", "lights-out", project="demo") == "lights-out"

    def test_attended_is_fine_when_the_fleet_is_attended(self, home: Path) -> None:
        assert _pod_core.PodSettings.coerce("profile", "attended", project="demo") == "attended"

    def test_pod_set_refuses_the_weaker_value(self, home: Path) -> None:
        from docket.cli import app

        _fleet.set_profile("lights-out")
        result = CliRunner().invoke(app, ["pod", "set", "profile", "attended", "--pod", "demo"])

        assert result.exit_code == 1
        assert _fleet.meta_get("demo-lead", "profile", "") == ""


class TestSetupProfile:
    def test_records_and_audits_and_clears(self, home: Path) -> None:
        from docket.cli import app

        runner = CliRunner()
        assert runner.invoke(app, ["setup", "profile", "lights-out"]).exit_code == 0
        assert _fleet.get_profile() == "lights-out"
        assert [e for e in _audit.read_audit() if e["action"] == "gates.profile"]

        assert runner.invoke(app, ["setup", "profile", "attended"]).exit_code == 0
        assert _fleet.get_profile() == "attended"
        assert json.loads((home / "fleet.json").read_text())["security"]["profile"] == "unset"

    def test_a_stray_word_is_a_usage_error(self, home: Path) -> None:
        from docket.cli import app

        assert CliRunner().invoke(app, ["setup", "profile", "loud"]).exit_code == 2


class TestStatusAndDoctor:
    def test_status_and_doctor_show_the_same_violations(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.cli import _setup_check, _status
        from docket.core import profile as _profile

        _meet_everything(home, monkeypatch)
        record_isolation_off(home)

        expected = [v.requirement for v in _profile.project_violations("demo")]
        assert "isolation" in expected
        summary = _status._project_summary("demo")
        assert [v["requirement"] for v in summary["profile"]["violations"]] == expected
        report = _setup_check._check_json()["checks"]["securityGates"]["profile"]["demo"]
        assert [v["requirement"] for v in report["violations"]] == expected

    def test_attended_output_has_no_profile_keys(self, home: Path) -> None:
        from docket.cli import _setup_check, _status

        assert "profile" not in _status._project_summary("demo")
        assert "profile" not in _setup_check._check_json()["checks"]["securityGates"]
