"""A pod with a researcher says at creation that it cannot read the web, and opens nothing.

The pod records the `fetch-hosts` need on its Lead when a `researcher` joins it (from a blueprint
or from `pod add`); `pod show` and `GET /pods/<pod>` then carry the not-ready line and the one
command that fixes it. No fetch grant and no network setting is written.
"""

from __future__ import annotations

from pathlib import Path

from tests.support.pods import build_pod
from tests.support.pods import seed_empty_home as _seed
from typer.testing import CliRunner

from docket.hops.application import report as pod_report
from docket.interfaces.cli.app import app
from docket.teams import fleet as _fleet
from docket.teams import pod_provisioning as _pp
from docket.teams import pod_settings as _pod_settings

SUBJECT = "docket.teams.pod_provisioning"

runner = CliRunner()

FETCH_NOT_READY = (
    "needs fetch-hosts: the researchers cannot read the web "
    "-> docket pod set fetchDomains <hosts> --pod demo"
)


def _need_lines(output: str) -> list[str]:
    return [ln.strip() for ln in output.splitlines() if ln.strip().startswith("needs ")]


def test_a_respond_pod_records_the_need_and_the_report_serves_it(tmp_path: Path) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")

        report = pod_report.pod_report("demo")

    assert report["needs"] == [
        {
            "kind": "fetch-hosts",
            "name": "fetch-hosts",
            "fix": "docket pod set fetchDomains <hosts> --pod demo",
            "satisfied": False,
        }
    ]
    assert report["fetchDomains"] == []
    assert report["network"]["mode"] == "none"


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
        assert _need_lines(result.output) == [FETCH_NOT_READY]
        assert pod_report.pod_report("demo")["needs"][0]["satisfied"] is False


def test_naming_hosts_makes_the_recorded_need_ready(tmp_path: Path) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")
        _fleet.meta_set("demo-lead", "fetchDomains", "example.org")

        (need,) = pod_report.pod_report("demo")["needs"]

    assert need["satisfied"] is True
