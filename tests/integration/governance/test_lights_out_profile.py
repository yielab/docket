"""The ``lights-out`` profile: a task is refused before its first hop unless every requirement holds.

Specs: security-gates.spec.md "Profiles", cli-interface.spec.md (``setup profile``),
operator-loop.spec.md "Profile lines".
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.fakes import FakeDriver, FakeJail
from tests.support.home import record_isolation_off, record_isolation_on
from tests.support.pods import build_pod
from tests.support.pods import spec as _spec
from typer.testing import CliRunner

from docket.governance import audit as _audit
from docket.governance import secrets as _secrets
from docket.hops.application import report as _pod_report
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel import mcp as _kernel_mcp
from docket.kernel.home import Home, use_home
from docket.kernel.ports import SandboxAvailability
from docket.tasks.application import queue as _queue
from docket.tasks.domain import state as _state
from docket.tasks.domain import task as _task
from docket.teams import fleet as _fleet
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import pod_settings as _pod_settings

SUBJECT = "docket.hops.gates.profile"

_GATED = """\
name: gated
steps:
  - plan: lead
  - build: implementer
    gate: {external: "true"}
"""

_UNGATED = """\
name: ungated
steps:
  - plan: lead
  - build: implementer
"""

_USABLE = SandboxAvailability(backend="landlock", docker=False, landlock=True)
_NONE = SandboxAvailability(backend="none", docker=False)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / ".docket"
    (root / "workspaces" / "projects").mkdir(parents=True)
    (root / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(root)):
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        _fleet.meta_set("demo-implementer", "codebase", str(tmp_path))
        yield root


def _meet_everything(root: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail) -> None:
    record_isolation_on(root)
    fake_jail.sandbox_availability = lambda *a, **k: _USABLE
    _fleet.set_network_mode("none")
    _fleet.set_profile("lights-out")
    _set_consult_mode("decide")


def _set_consult_mode(value: str) -> None:
    _fleet.meta_set(
        "demo-lead", "consultMode", _pod_settings.PodSettings.coerce("consultMode", value)
    )


def _dispatch_one(spec_text: str) -> tuple[_task.TaskResult, FakeDriver]:
    _queue.enqueue_task_once("demo", "Ship it", channel="cli")
    driver = FakeDriver()
    res = _sweep.dispatch_pod("demo", runner=driver, spec=_spec(spec_text))[0]
    return res, driver


def _refused(res: _task.TaskResult, driver: FakeDriver, requirement: str) -> None:
    assert res.status == "failed"
    assert res.failure_kind == "dispatch_refused"
    assert requirement in (res.reason or "")
    assert driver.calls == []
    entries = [e for e in _audit.read_audit() if e["action"] == "profile.refused"]
    assert entries
    assert "pod=demo" in entries[-1]["detail"]
    assert requirement in entries[-1]["detail"]


class TestRefusals:
    def test_isolation_off_refuses(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        record_isolation_off(home)

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "isolation")
        assert "docket setup sandbox on" in (res.reason or "")

    def test_isolation_without_a_backend_refuses(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        fake_jail.sandbox_availability = lambda *a, **k: _NONE

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "isolation")

    def test_open_network_refuses(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        _fleet.set_network_mode("open")

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "network")

    def test_an_unrecorded_network_none_refuses(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        data = json.loads((home / "fleet.json").read_text())
        data["security"]["networkMode"] = "unset"
        (home / "fleet.json").write_text(json.dumps(data))

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "network")

    def test_a_pod_level_network_none_satisfies_it(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        _fleet.set_network_mode("open")
        _fleet.meta_set("demo-lead", "network", "none")

        res, driver = _dispatch_one(_GATED)

        assert res.failure_kind != "dispatch_refused"
        assert driver.calls

    def test_an_implementer_step_without_an_external_gate_refuses(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)

        res, driver = _dispatch_one(_UNGATED)

        _refused(res, driver, "external-gate")
        assert "build" in (res.reason or "")

    def test_an_injected_variable_named_in_the_secret_store_refuses(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        _secrets.save_secrets({"MY_TOKEN": "x"})
        _mcp_servers.write_pod_mcp_servers(
            "demo", [_kernel_mcp.McpServerConfig(name="s", command="true", env={"MY_TOKEN": "y"})]
        )

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "secrets")
        assert "MY_TOKEN" in (res.reason or "")

    def test_the_refusal_is_resumable(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        record_isolation_off(home)
        res, _driver = _dispatch_one(_GATED)
        assert res.failure_kind in _state.RESUMABLE_FAILURE_KINDS

    def test_a_resuming_sweep_refuses_a_task_once_per_run(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        record_isolation_off(home)
        _queue.enqueue_task_once("demo", "Ship it", channel="cli")

        def _stop() -> bool:
            return len(_audit.read_audit()) > 50

        results = _sweep.dispatch_pod(
            "demo", runner=FakeDriver(), spec=_spec(_GATED), resume=True, stop=_stop
        )

        assert len(results) == 1
        assert results[0].failure_kind == "dispatch_refused"

    def test_a_resuming_sweep_still_reaches_the_next_task(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        record_isolation_off(home)
        first = _queue.enqueue_task_once("demo", "First", channel="cli")[0].id
        second = _queue.enqueue_task_once("demo", "Second", channel="cli")[0].id

        results = _sweep.dispatch_pod(
            "demo",
            runner=FakeDriver(),
            spec=_spec(_GATED),
            resume=True,
            stop=lambda: len(_audit.read_audit()) > 50,
        )

        assert sorted(r.task_id for r in results) == sorted([first, second])


class TestAConsultThatWouldWait:
    def test_the_default_park_mode_refuses_and_names_the_setting(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        _set_consult_mode("park")

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "consult")
        assert "docket pod set consultMode decide" in (res.reason or "")

    def test_an_unset_mode_is_park(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)
        _fleet.meta_set("demo-lead", "consultMode", "")

        res, driver = _dispatch_one(_GATED)

        _refused(res, driver, "consult")

    def test_decide_has_no_consult_violation(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)

        assert "consult" not in [v.requirement for v in _pod_report.project_violations("demo")]

    def test_setup_fix_prints_the_violation_and_its_fix(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        from docket.interfaces.cli.app import app

        _meet_everything(home, monkeypatch, fake_jail)
        _set_consult_mode("park")

        out = CliRunner().invoke(app, ["setup", "--fix"]).stdout

        assert "consult: a consultation would wait for a person" in out
        assert "docket pod set consultMode decide" in out


class TestPositive:
    def test_every_requirement_met_runs_the_task(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _meet_everything(home, monkeypatch, fake_jail)

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

        with pytest.raises(_pod_settings.PodSettingsError, match="stricter"):
            _pod_settings.PodSettings.coerce("profile", "attended", project="demo")

        assert (
            _pod_settings.PodSettings.coerce("profile", "lights-out", project="demo")
            == "lights-out"
        )

    def test_attended_is_fine_when_the_fleet_is_attended(self, home: Path) -> None:
        assert _pod_settings.PodSettings.coerce("profile", "attended", project="demo") == "attended"

    def test_pod_set_refuses_the_weaker_value(self, home: Path) -> None:
        from docket.interfaces.cli.app import app

        _fleet.set_profile("lights-out")
        result = CliRunner().invoke(app, ["pod", "set", "profile", "attended", "--pod", "demo"])

        assert result.exit_code == 1
        assert _fleet.meta_get("demo-lead", "profile", "") == ""


class TestSetupProfile:
    def test_records_and_audits_and_clears(self, home: Path) -> None:
        from docket.interfaces.cli.app import app

        runner = CliRunner()
        assert runner.invoke(app, ["setup", "profile", "lights-out"]).exit_code == 0
        assert _fleet.get_profile() == "lights-out"
        assert [e for e in _audit.read_audit() if e["action"] == "gates.profile"]

        assert runner.invoke(app, ["setup", "profile", "attended"]).exit_code == 0
        assert _fleet.get_profile() == "attended"
        assert json.loads((home / "fleet.json").read_text())["security"]["profile"] == "unset"

    def test_a_stray_word_is_a_usage_error(self, home: Path) -> None:
        from docket.interfaces.cli.app import app

        assert CliRunner().invoke(app, ["setup", "profile", "loud"]).exit_code == 2


class TestStatusAndDoctor:
    def test_status_and_doctor_show_the_same_violations(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        from docket.interfaces.cli.commands import setup_check as _setup_check
        from docket.interfaces.cli.commands import status as _status

        _meet_everything(home, monkeypatch, fake_jail)
        record_isolation_off(home)

        expected = [v.requirement for v in _pod_report.project_violations("demo")]
        assert "isolation" in expected
        summary = _status._project_summary("demo")
        assert [v["requirement"] for v in summary["profile"]["violations"]] == expected
        report = _setup_check._check_json()["checks"]["securityGates"]["profile"]["demo"]
        assert [v["requirement"] for v in report["violations"]] == expected

    def test_attended_output_has_no_profile_keys(self, home: Path) -> None:
        from docket.interfaces.cli.commands import setup_check as _setup_check
        from docket.interfaces.cli.commands import status as _status

        assert "profile" not in _status._project_summary("demo")
        assert "profile" not in _setup_check._check_json()["checks"]["securityGates"]
