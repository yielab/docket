"""``docket pod routine list`` shows each routine's schedule, next slot and last fired slot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support import pods as _support_pods
from tests.support.pods import build_pod
from typer.testing import CliRunner

from docket.interfaces.cli.app import app as _app
from docket.interfaces.http import sweeps as _sweeps
from docket.kernel.home import current_home
from docket.tasks.application.repository import TaskRepository

pod_home = _support_pods.pod_home

SUBJECT = "docket.interfaces.cli.commands.pod_routines"

EVERY = """kind: routine
name: heartbeat
schedule: '@every 1h'
task:
  description: write the heartbeat
"""
WEEKDAYS = """kind: routine
name: weekdays
schedule: '0 9 * * 1-5'
tz: America/Bogota
enabled: false
task:
  description: read the tickets
"""


@pytest.fixture()
def pod(pod_home: Path) -> str:
    build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
    directory = current_home().pod_config_dir("demo") / "routines"
    directory.mkdir(parents=True)
    (directory / "heartbeat.yaml").write_text(EVERY, encoding="utf-8")
    (directory / "weekdays.yaml").write_text(WEEKDAYS, encoding="utf-8")
    return "demo"


def _list(*flags: str) -> tuple[int, str]:
    result = CliRunner().invoke(_app, ["pod", "routine", "list", "--pod", "demo", *flags])
    return result.exit_code, result.output


def test_the_list_names_every_routine_with_its_zone_and_whether_it_is_enabled(pod: str) -> None:
    code, out = _list("--json")
    rows = {r["name"]: r for r in json.loads(out)}

    assert code == 0
    assert (rows["weekdays"]["tz"], rows["weekdays"]["enabled"]) == ("America/Bogota", False)
    assert rows["weekdays"]["schedule"] == "0 9 * * 1-5"
    assert rows["weekdays"]["last"] is None and rows["weekdays"]["next"].endswith("Z")
    assert rows["heartbeat"]["scope"] == "pod"


def test_the_last_fired_slot_shows_after_the_sweep_fires_it(pod: str) -> None:
    _sweeps.check_schedules(1_793_000_000.0)

    (task,) = TaskRepository.for_pod(pod).list()
    assert task.channel == "routine"
    rows = {r["name"]: r for r in json.loads(_list("--json")[1])}
    assert task.idempotency_key == f"routine:heartbeat:{rows['heartbeat']['last']}"
    code, out = _list()
    assert code == 0 and "heartbeat" in out and "weekdays" in out


def test_a_pod_with_no_routines_says_so(pod_home: Path) -> None:
    build_pod("bare", ("lead", "implementer"), codebase="/src/bare")
    result = CliRunner().invoke(_app, ["pod", "routine", "list", "--pod", "bare"])
    assert result.exit_code == 0
    assert "No routines in pod 'bare'." in result.output
