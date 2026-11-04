"""`teams/memory_decide.py`: the exit status docket finds for a command in a finished task."""

from __future__ import annotations

from typing import Any

from docket.teams import memory_decide as md

SUBJECT = "docket.teams.memory_decide"


def _facts(
    events: list[dict[str, Any]] | None = None, verified: list[tuple[str, int]] | None = None
) -> md._TaskFacts:
    return md._TaskFacts("demo", "", "", False, True, events or [], verified or [])


class TestDecideCommand:
    def test_a_verify_gate_exit_is_accepted_with_its_status(self) -> None:
        got = md._decide_command("pytest -q", _facts(verified=[("pytest -q", 1)]))

        assert (got[1], got[3]) == ("accepted", 1)

    def test_the_last_command_step_in_the_trace_wins(self) -> None:
        steps = [
            {"event_type": "command_step", "payload": {"cmd": "make", "exit": code}}
            for code in (1, 0)
        ]

        got = md._decide_command("make", _facts(events=steps))

        assert (got[1], got[3]) == ("accepted", 0)

    def test_a_command_nobody_ran_is_refused(self) -> None:
        got = md._decide_command("make", _facts())

        assert (got[1], got[3]) == ("refused", None)
