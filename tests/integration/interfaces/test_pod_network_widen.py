"""``docket pod set network open --widen``: the operator's recorded yes that widens one pod.

A machine at network ``none`` stays ``none`` for every pod except the one the operator widened
(security-gates.spec.md item 7, "The pod grant").
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.support.cli import invoke_pod
from tests.support.pods import build_pod
from tests.support.pods import seed_empty_home as _seed
from typer.testing import CliRunner

from docket.governance.audit import read_audit
from docket.interfaces.cli.app import app as _app
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands.setup_check_services import _check_security_gates
from docket.kernel.home import current_home
from docket.teams import fleet as _fleet
from docket.teams import pod, pod_settings

SUBJECT = "docket.interfaces.cli.commands.pod"


@contextmanager
def _machine(tmp_path: Path, *, isolation: bool = True) -> Iterator[None]:
    with _seed(tmp_path):
        build_pod("proj", pod.DEFAULT_POD_ROLES, codebase="/src/proj")
        build_pod("other", pod.DEFAULT_POD_ROLES, codebase="/src/other")
        _fleet.set_network_mode("none")
        if isolation:
            _fleet.set_sandbox_isolation()
        yield


def _meta(project: str) -> dict[str, object]:
    return dict(json.loads(current_home().meta_path(f"{project}-lead").read_text()))


def _actions(prefix: str) -> list[dict[str, str]]:
    return [e for e in read_audit() if str(e["action"]).startswith(prefix)]


def _answer(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    monkeypatch.setattr(_contract, "is_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": reply)


class TestWiden:
    def test_answering_no_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _machine(tmp_path):
            before = _meta("proj")
            _answer(monkeypatch, "n")
            result = invoke_pod(["set", "network", "open", "--widen", "--pod", "proj"])
            assert result.exit_code == 1, result.output
            assert "can reach any host" in result.output
            assert _meta("proj") == before
            assert _actions("pod.network") == []
            assert pod_settings.effective_network("proj") == ("none", "global")

    def test_answering_yes_records_the_grant_and_audits_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _machine(tmp_path):
            _answer(monkeypatch, "y")
            result = invoke_pod(["set", "network", "open", "--widen", "--pod", "proj"])
            assert result.exit_code == 0, result.output
            grant = _meta("proj")["networkGrant"]
            assert isinstance(grant, dict)
            assert grant["at"] and grant["by"]
            assert pod_settings.effective_network("proj") == ("open", "pod-grant")
            assert pod_settings.effective_network("other") == ("none", "global")
            (row,) = _actions("pod.network_widen")
            assert "pod=proj" in row["detail"] and "overrides=global" in row["detail"]

    def test_yes_flag_skips_the_prompt(self, tmp_path: Path) -> None:
        with _machine(tmp_path):
            result = invoke_pod(["set", "network", "open", "--widen", "--yes", "--pod", "proj"])
            assert result.exit_code == 0, result.output
            assert pod_settings.effective_network("proj") == ("open", "pod-grant")

    def test_off_a_terminal_without_yes_refuses(self, tmp_path: Path) -> None:
        with _machine(tmp_path):
            result = invoke_pod(["set", "network", "open", "--widen", "--pod", "proj"])
            assert result.exit_code == 1
            assert "networkGrant" not in _meta("proj")
            assert _actions("pod.network") == []

    def test_refused_while_isolation_is_off(self, tmp_path: Path) -> None:
        with _machine(tmp_path, isolation=False):
            result = invoke_pod(["set", "network", "open", "--widen", "--yes", "--pod", "proj"])
            assert result.exit_code == 1
            assert "isolation" in result.output
            assert "networkGrant" not in _meta("proj")

    def test_widen_belongs_to_network(self, tmp_path: Path) -> None:
        with _machine(tmp_path):
            result = invoke_pod(["set", "budgetUsd", "5", "--widen", "--pod", "proj"])
            assert result.exit_code == 1
            assert _meta("proj").get("budgetUsd") != 5

    def test_the_grant_key_is_not_settable_by_hand(self, tmp_path: Path) -> None:
        with _machine(tmp_path):
            result = invoke_pod(["set", "networkGrant", "x", "--pod", "proj"])
            assert result.exit_code == 1
            assert "networkGrant" not in _meta("proj")


class TestNarrow:
    def _widened(self) -> None:
        result = invoke_pod(["set", "network", "open", "--widen", "--yes", "--pod", "proj"])
        assert result.exit_code == 0, result.output

    @pytest.mark.parametrize("args", [["none"], ["open"]])
    def test_removes_the_grant_and_audits_it(self, tmp_path: Path, args: list[str]) -> None:
        with _machine(tmp_path):
            self._widened()
            result = invoke_pod(["set", "network", *args, "--pod", "proj"])
            assert result.exit_code == 0, result.output
            assert "networkGrant" not in _meta("proj")
            assert _meta("proj").get("network") == args[0]
            assert pod_settings.effective_network("proj")[0] == "none"
            (row,) = _actions("pod.network_narrow")
            assert "pod=proj" in row["detail"]

    def test_narrowing_a_pod_without_a_grant_audits_nothing(self, tmp_path: Path) -> None:
        with _machine(tmp_path):
            result = invoke_pod(["set", "network", "none", "--pod", "proj"])
            assert result.exit_code == 0, result.output
            assert _actions("pod.network_narrow") == []


class TestReports:
    def test_status_and_the_health_report_name_the_pod_with_a_grant(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _machine(tmp_path):
            assert pod_settings.network_grant_pods(["proj", "other"]) == []
            before = json.loads(_cli(["status", "--pod", "proj", "--json"]))
            assert "networkGrant" not in before
            invoke_pod(["set", "network", "open", "--widen", "--yes", "--pod", "proj"])
            assert pod_settings.network_grant_pods(["proj", "other"]) == ["proj"]
            after = json.loads(_cli(["status", "--pod", "proj", "--json"]))
            assert "any host" in after["networkGrant"]
            assert "networkGrant" not in json.loads(_cli(["status", "--pod", "other", "--json"]))
            assert "Network" in _cli(["status", "--pod", "proj"])
            capsys.readouterr()
            _check_security_gates(["proj", "other"])
            out = capsys.readouterr().out
            assert "proj" in out and "network grant" in out
            assert "other" not in out


def _cli(args: list[str]) -> str:
    result = CliRunner().invoke(_app, args)
    assert result.exit_code == 0, result.output
    return str(result.stdout)
