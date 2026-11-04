"""`teams/memory_decide.py`: the evidence docket finds for a tool call in a finished task."""

from __future__ import annotations

from typing import Any

from docket.teams import memory_decide as md

SUBJECT = "docket.teams.memory_decide"


def _facts(
    events: list[dict[str, Any]] | None = None, verified: list[tuple[str, int]] | None = None
) -> md._TaskFacts:
    return md._TaskFacts("demo", "", "", False, True, events or [], verified or [])


def _call(tool: str, call_id: str, ok: bool | None = True) -> list[dict[str, Any]]:
    """A ``tool_call`` and, unless *ok* is None, its ``tool_result``."""
    events = [{"event_type": "tool_call", "payload": {"tool": tool, "callId": call_id}}]
    if ok is not None:
        payload = {"tool": tool, "callId": call_id, "ok": ok, "executed": True}
        events.append({"event_type": "tool_result", "payload": payload})
    return events


class TestDecideTool:
    def test_a_verify_gate_exit_is_accepted_with_its_status(self) -> None:
        got = md._decide_tool("pytest -q", _facts(verified=[("pytest -q", 1)]))

        assert (got[1], got[3]) == ("accepted", {"exit": 1})

    def test_the_last_command_step_in_the_trace_wins(self) -> None:
        steps = [
            {"event_type": "command_step", "payload": {"cmd": "make", "exit": code}}
            for code in (1, 0)
        ]

        got = md._decide_tool("make", _facts(events=steps))

        assert (got[1], got[3]) == ("accepted", {"exit": 0})

    def test_a_command_nobody_ran_is_refused(self) -> None:
        got = md._decide_tool("make", _facts())

        assert (got[1], got[3]) == ("refused", None)

    def test_a_service_call_is_accepted_with_its_outcome(self) -> None:
        got = md._decide_tool("rec__query SELECT 1", _facts(events=_call("rec__query", "c1")))

        assert got[1:] == ("accepted", "tool call found in the task's trace", {"ok": True})

    def test_the_last_result_of_the_tool_gives_the_outcome(self) -> None:
        events = _call("rec__query", "c1") + _call("rec__query", "c2", ok=False)

        got = md._decide_tool("rec__query", _facts(events=events))

        assert (got[1], got[3]) == ("accepted", {"ok": False})

    def test_a_call_without_its_result_is_refused(self) -> None:
        got = md._decide_tool("rec__query", _facts(events=_call("rec__query", "c1", ok=None)))

        assert (got[1], got[3]) == ("refused", None)

    def test_the_first_token_names_the_tool(self) -> None:
        got = md._decide_tool(
            "svc__hn__search python", _facts(events=_call("svc__hn__search", "c"))
        )

        assert got[1] == "accepted"
        assert md._decide_tool("svc__hn python", _facts(events=_call("svc__hn__search", "c")))[
            1
        ] == ("refused")
