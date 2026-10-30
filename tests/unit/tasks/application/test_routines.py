"""A routine's slots are computed in its own zone, and a due slot becomes one task."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tests.support import pods as _support_pods
from tests.support.pods import build_pod
from tests.support.tasks import update_task

from docket.kernel.home import current_home
from docket.tasks.application import routines
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.routine import Routine
from docket.tasks.domain.state import Status

pod_home = _support_pods.pod_home

SUBJECT = "docket.tasks.application.routines"


def _at(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def _routine(schedule: str, tz: str = "UTC", **fields: Any) -> Routine:
    return Routine.from_document(
        {"name": "r", "schedule": schedule, "tz": tz, "task": {"description": "do it"}, **fields}
    )


class TestSlotsInTheRoutinesZone:
    def test_a_weekday_slot_in_bogota_is_due_at_1400z(self) -> None:
        routine = _routine("0 9 * * 1-5", "America/Bogota")
        monday = routines.due(routine, _at(2026, 11, 2, 0), _at(2026, 11, 2, 14))
        assert monday is not None and monday.latest == _at(2026, 11, 2, 14)
        assert routines.due(routine, _at(2026, 11, 2, 0), _at(2026, 11, 2, 13, 59)) is None

    def test_a_saturday_has_no_slot(self) -> None:
        routine = _routine("0 9 * * 1-5", "America/Bogota")
        assert routines.due(routine, _at(2026, 11, 7, 0), _at(2026, 11, 8, 0)) is None

    def test_madrid_stays_at_0900_local_across_both_changes_of_offset(self) -> None:
        routine = _routine("0 9 * * *", "Europe/Madrid")

        def slot(day: tuple[int, int, int]) -> datetime | None:
            window = routines.due(routine, _at(*day, 0) - timedelta(minutes=1), _at(*day, 12))
            return window.latest if window else None

        assert slot((2026, 3, 28)) == _at(2026, 3, 28, 8)
        assert slot((2026, 3, 29)) == _at(2026, 3, 29, 7)
        assert slot((2026, 10, 24)) == _at(2026, 10, 24, 7)
        assert slot((2026, 10, 25)) == _at(2026, 10, 25, 8)

    def test_a_local_time_the_clock_skips_has_no_slot_and_a_repeated_one_has_one(self) -> None:
        gap = _routine("30 2 * * *", "Europe/Madrid")  # 2026-03-29 02:30 never happens
        assert routines.due(gap, _at(2026, 3, 29, 0), _at(2026, 3, 29, 12)) is None
        repeated = _routine("30 2 * * *", "Europe/Madrid")  # 2026-10-25 02:30 happens twice
        window = routines.due(repeated, _at(2026, 10, 25, 0), _at(2026, 10, 25, 12))
        assert window is not None and window.count == 1

    def test_every_counts_from_the_anchor(self) -> None:
        routine = _routine("@every 10m")
        window = routines.due(routine, _at(2026, 11, 2, 10, 0), _at(2026, 11, 2, 10, 35))
        assert window is not None
        assert (window.first, window.latest, window.count) == (
            _at(2026, 11, 2, 10, 10),
            _at(2026, 11, 2, 10, 30),
            3,
        )

    def test_next_slot_is_the_first_after_now(self) -> None:
        routine = _routine("0 9 * * 1-5", "America/Bogota")
        assert routines.next_slot(routine, _at(2026, 11, 6, 15)) == _at(2026, 11, 9, 14)


@pytest.fixture()
def pod(pod_home: Path) -> str:
    build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
    return "demo"


def _write(pod: str, text: str, name: str = "hourly") -> None:
    directory = current_home().pod_config_dir(pod) / "routines"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.yaml").write_text(text, encoding="utf-8")


def _hourly(**fields: str) -> str:
    extra = "".join(f"{k}: {v}\n" for k, v in fields.items())
    return (
        "kind: routine\nname: hourly\nschedule: '0 * * * *'\n"
        "task:\n  description: check the inbox\n" + extra
    )


def _tick(hour: int, minute: int = 0) -> list[str]:
    return routines.fire_due(_at(2026, 11, 2, hour, minute).timestamp())


class TestFireDue:
    def test_three_missed_slots_fire_the_latest_under_skip(self, pod: str) -> None:
        _write(pod, _hourly())
        assert _tick(10, 30) == []  # first sighting: history is not replayed
        assert len(_tick(13, 30)) == 1
        (task,) = TaskRepository.for_pod(pod).list()
        assert task.idempotency_key == "routine:hourly:2026-11-02T13:00:00Z"
        assert task.channel == "routine"
        assert task.description == "check the inbox"

    def test_three_missed_slots_fire_one_task_under_once(self, pod: str) -> None:
        _write(pod, _hourly(catchUp="once"))
        _tick(10, 30)
        assert len(_tick(13, 30)) == 1
        (task,) = TaskRepository.for_pod(pod).list()
        assert task.description.startswith("check the inbox")
        assert "3 scheduled runs were missed" in task.description

    @pytest.mark.parametrize(
        "status", [Status.pending, Status.running, Status.waiting_input, Status.waiting_approval]
    )
    def test_overlap_skip_fires_nothing_while_the_last_task_is_unfinished(
        self, pod: str, status: Status
    ) -> None:
        _write(pod, _hourly())
        _tick(10, 30)
        (first,) = _tick(11)
        update_task(pod, first, status=status)
        assert _tick(12) == []
        assert len(TaskRepository.for_pod(pod).list()) == 1
        update_task(pod, first, status=Status.done)
        assert len(_tick(13)) == 1

    def test_overlap_queue_fires_regardless(self, pod: str) -> None:
        _write(pod, _hourly(overlap="queue"))
        _tick(10, 30)
        _tick(11)
        assert len(_tick(12)) == 1
        assert len(TaskRepository.for_pod(pod).list()) == 2

    def test_a_disabled_routine_never_fires(self, pod: str) -> None:
        _write(pod, _hourly(enabled="false"))
        _tick(10, 30)
        assert _tick(12) == []

    def test_the_first_every_slot_is_the_moment_it_is_first_seen(self, pod: str) -> None:
        _write(pod, _hourly(overlap="queue").replace("'0 * * * *'", "'@every 1h'"))
        assert len(_tick(10, 30)) == 1
        assert _tick(10, 45) == []
        assert len(_tick(11, 30)) == 1
