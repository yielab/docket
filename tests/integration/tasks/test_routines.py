"""A fired routine is one task, however often the sweep looks, across a restart."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.support import pods as _support_pods
from tests.support.pods import build_pod

from docket.governance import audit as _audit
from docket.kernel.home import current_home
from docket.tasks.application import routines
from docket.tasks.application.repository import TaskRepository

pod_home = _support_pods.pod_home

SUBJECT = "docket.tasks.application.routines"

ROUTINE = """kind: routine
name: nightly
schedule: '0 3 * * *'
tz: America/Bogota
task:
  description: tidy the backlog
  pipeline: tidy
  priority: low
  variables:
    AREA: backlog
"""


def _ts(day: int, hour: int, minute: int = 0) -> float:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC).timestamp()


@pytest.fixture()
def pod(pod_home: Path) -> str:
    build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
    directory = current_home().pod_config_dir("demo") / "routines"
    directory.mkdir(parents=True)
    (directory / "nightly.yaml").write_text(ROUTINE, encoding="utf-8")
    return "demo"


def test_one_slot_creates_one_task_however_often_it_is_looked_at(pod: str) -> None:
    routines.fire_due(_ts(2, 7))
    first = routines.fire_due(_ts(3, 8, 5))
    again = routines.fire_due(_ts(3, 8, 6))

    assert (len(first), again) == (1, [])
    (task,) = TaskRepository.for_pod(pod).list()
    assert task.idempotency_key == "routine:nightly:2026-11-03T08:00:00Z"
    assert (task.pipeline, task.variables, task.priority) == (
        "tidy",
        {"AREA": "backlog"},
        "low",
    )


def test_a_slot_that_was_fired_is_not_fired_again_after_the_state_is_reloaded(pod: str) -> None:
    routines.fire_due(_ts(2, 7))
    routines.fire_due(_ts(3, 8, 5))
    state_file = current_home().routines_state_file
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["routines"]["demo/nightly"]["lastSlot"] == "2026-11-03T08:00:00Z"

    # A restart: nothing in memory, only the file.
    assert routines.fire_due(_ts(3, 8, 7)) == []
    assert len(TaskRepository.for_pod(pod).list()) == 1


def test_a_lost_state_write_fires_the_same_key_and_so_the_same_task(pod: str) -> None:
    routines.fire_due(_ts(2, 7))
    routines.fire_due(_ts(3, 8, 5))
    state_file = current_home().routines_state_file
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    saved["routines"]["demo/nightly"].pop("lastSlot")
    state_file.write_text(json.dumps(saved), encoding="utf-8")

    routines.fire_due(_ts(3, 8, 9))
    assert len(TaskRepository.for_pod(pod).list()) == 1


def test_a_fire_is_audited_with_its_slot_and_channel(pod: str) -> None:
    routines.fire_due(_ts(2, 7))
    (task_id,) = routines.fire_due(_ts(3, 8, 5))
    rows = [e for e in _audit.read_audit() if e.get("action") in ("task.enqueue", "routine.fire")]
    details = {e["action"]: e["detail"] for e in rows}
    assert (
        f"task={task_id}" in details["task.enqueue"]
        and "channel=routine" in details["task.enqueue"]
    )
    assert "routine=nightly" in details["routine.fire"]
    assert "slot=2026-11-03T08:00:00Z" in details["routine.fire"]
