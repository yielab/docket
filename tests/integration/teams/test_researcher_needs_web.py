"""A pod with a researcher says at creation how it reads the web, and opens nothing.

The pod records the `fetch-hosts`, `search-host` and `isolation` needs on its Lead when a
`researcher` joins it (from a blueprint or from `pod add`); `pod show` and `GET /pods/<pod>` then
carry `webRead` (how the pod reads the web), each need with the one command that fixes it and
whether it blocks the work. No fetch grant and no network setting is written.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from tests.support.pods import build_pod
from tests.support.pods import seed_empty_home as _seed
from typer.testing import CliRunner

from docket.hops.application import report as pod_report
from docket.interfaces.cli.app import app
from docket.sandbox.launch import Launcher
from docket.teams import fleet as _fleet
from docket.teams import pod_provisioning as _pp
from docket.teams import pod_settings as _pod_settings

SUBJECT = "docket.teams.pod_provisioning"

runner = CliRunner()

FETCH_NOT_READY = (
    "needs fetch-hosts: the researchers cannot read the web -> docket setup sandbox on"
)
REPO_FETCH_NOT_READY = (
    "needs fetch-hosts: the researchers cannot read the web "
    "-> docket pod set fetchDomains <host> --pod demo"
)


def _need_lines(output: str) -> list[str]:
    return [ln.strip() for ln in output.splitlines() if ln.strip().startswith("needs ")]


_SEARCH_FIX = "docket setup search searxng --pod demo"


def _wire(kind: str, fix: str, *, satisfied: bool, blocking: bool) -> dict[str, object]:
    return {"kind": kind, "name": kind, "fix": fix, "satisfied": satisfied, "blocking": blocking}


def test_a_respond_pod_under_the_jail_reads_openly_but_has_no_search_service(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    bind_launcher(landlock=True)
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")
        _fleet.set_sandbox_isolation()

        report = pod_report.pod_report("demo")

    assert report["webRead"] == {
        "mode": "open",
        "reason": "a folder team under the jail reads any public host",
        "fix": "",
    }
    assert report["needs"] == [
        _wire("fetch-hosts", "", satisfied=True, blocking=True),
        _wire("search-host", _SEARCH_FIX, satisfied=False, blocking=False),
        _wire("isolation", "", satisfied=True, blocking=False),
    ]
    assert report["fetchDomains"] == []
    assert report["network"]["mode"] == "none"


def test_a_respond_pod_without_the_jail_reads_nothing_and_only_fetch_hosts_blocks(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    bind_launcher(landlock=True)
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")

        report = pod_report.pod_report("demo")

    assert report["webRead"]["mode"] == "none"
    assert report["webRead"]["fix"] == "docket setup sandbox on"
    assert report["needs"] == [
        _wire("fetch-hosts", "docket setup sandbox on", satisfied=False, blocking=True),
        _wire("search-host", _SEARCH_FIX, satisfied=False, blocking=False),
        _wire("isolation", "docket setup sandbox on", satisfied=False, blocking=False),
    ]


def test_a_repository_pod_with_a_researcher_names_a_host_to_read(tmp_path: Path) -> None:
    with _seed(tmp_path):
        build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
        assert runner.invoke(app, ["pod", "add", "researcher", "--pod", "demo"]).exit_code == 0

        report = pod_report.pod_report("demo")

    assert report["webRead"]["mode"] == "none"
    fetch_need = report["needs"][0]
    assert fetch_need["fix"] == "docket pod set fetchDomains <host> --pod demo"
    assert fetch_need["blocking"] is True
    assert [n["kind"] for n in report["needs"]] == ["fetch-hosts", "search-host", "isolation"]


def test_pod_show_prints_the_web_line_and_json_carries_web_read(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    bind_launcher(landlock=True)
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")

        closed = runner.invoke(app, ["pod", "show", "--pod", "demo"])
        _fleet.set_sandbox_isolation()
        opened = runner.invoke(app, ["pod", "show", "--pod", "demo"])
        as_json = runner.invoke(app, ["pod", "show", "--pod", "demo", "--json"])

    assert (
        "Web: a folder team reads the web only under the jail, and the jail is not running"
        in closed.output
    )
    assert "-> docket setup sandbox on" in closed.output
    assert "Web: a folder team under the jail reads any public host" in opened.output
    assert json.loads(as_json.stdout)["webRead"]["mode"] == "open"


def test_a_pod_without_a_researcher_records_no_need(tmp_path: Path) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("demo", "routine")

        assert pod_report.pod_report("demo")["needs"] == []


def test_init_of_a_respond_pod_prints_the_line_and_writes_no_grant(tmp_path: Path) -> None:
    with _seed(tmp_path):
        result = runner.invoke(app, ["init", "demo", "--blueprint", "respond"])

        assert result.exit_code == 0, result.output
        assert _need_lines(result.output) == [FETCH_NOT_READY]
        settings = _pod_settings.PodSettings.load_for("demo")
        assert settings.fetch_domains == ()
        assert _fleet.meta_get("demo-lead", "network", "") == ""


def test_adding_a_researcher_records_the_need_and_prints_the_line(tmp_path: Path) -> None:
    with _seed(tmp_path):
        build_pod("demo", ("lead", "implementer"), codebase="/src/demo")

        result = runner.invoke(app, ["pod", "add", "researcher", "--pod", "demo"])

        assert result.exit_code == 0, result.output
        assert _need_lines(result.output) == [REPO_FETCH_NOT_READY]
        assert pod_report.pod_report("demo")["needs"][0]["satisfied"] is False


def test_naming_hosts_makes_the_recorded_need_ready(tmp_path: Path) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")
        _fleet.meta_set("demo-lead", "fetchDomains", "example.org")

        need = pod_report.pod_report("demo")["needs"][0]

    assert need["satisfied"] is True
