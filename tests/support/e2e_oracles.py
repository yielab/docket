"""What an end-to-end test checks about a finished run, read through the CLI and read-only tables.

Each oracle takes the world and reads what docket recorded: the task trace, the audit log, the
checkout, the fake home. ``skeleton_of`` and ``audit_gaps`` are the pure halves, so a test of an
oracle can feed them a doctored copy of the record.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from itertools import pairwise
from typing import Any

from docket.tasks.domain.state import ALLOWED, Status
from tests.support.e2e import SENTINEL_NAME, SENTINEL_TEXT, World

# The skeleton keeps hop start and finish, routing and rework, verdict failures, approvals, parks
# and their answers, skipped and command steps, stale claims, refusals, cancellation, the budget
# stop and the session end, plus the verify gate's pass (``verification``). It drops ids, times,
# model text, token counts, prompt and context events and each tool call. The outcome is the step
# for a start, the verdict or ok/fail for a finish, ``outcome>target`` for a route, and the status
# for the session end.
_CONTROL_FLOW = frozenset(
    {
        "hop_started",
        "hop_finished",
        "route_taken",
        "rework_started",
        "review_rejected",
        "verdict_rework_started",
        "verdict_rejected",
        "verdict_unparseable",
        "reviewer_verdict_unparseable",
        "verification_failed",
        "approval_required",
        "approval_requested",
        "approval_granted",
        "approval_denied",
        "approval_resumed",
        "approval_task_denied",
        "input_requested",
        "input_answered",
        "input_expired",
        "step_skipped",
        "command_step",
        "stale_claim",
        "dispatch_refused",
        "run_cancelled",
        "budget_exceeded",
        "session_end",
    }
)


def _outcome(event_type: str, payload: Mapping[str, Any]) -> str:
    if event_type == "hop_started":
        return str(payload.get("step", ""))
    if event_type == "hop_finished":
        return str(payload.get("verdict") or ("ok" if payload.get("ok") else "fail"))
    if event_type == "route_taken":
        return f"{payload.get('outcome', '')}>{payload.get('target', '')}"
    if event_type == "rework_started":
        return f"cycle {payload.get('cycle', '')}"
    for key in ("status", "outcome", "kind", "reason", "step"):
        if payload.get(key):
            return str(payload[key])
    return ""


def skeleton_of(events: Iterable[Mapping[str, Any]]) -> list[tuple[str, ...]]:
    """The control flow of a trace as ``(event_type, role, outcome)``; ``_CONTROL_FLOW`` is the set."""
    skeleton: list[tuple[str, ...]] = []
    for event in events:
        kind, role = str(event.get("event_type", "")), str(event.get("agent_role", ""))
        payload = event.get("payload") or {}
        if kind in _CONTROL_FLOW:
            skeleton.append((kind, role, _outcome(kind, payload)))
        elif kind == "tool_result" and "verification" in payload:
            skeleton.append(("verification", role, str(payload["verification"])))
    return skeleton


def trace_events(world: World, pod: str, task_id: str) -> list[dict[str, Any]]:
    """The task's trace events, as ``docket task trace --json`` prints them."""
    shown = world.docket("task", "trace", task_id, "--pod", pod, "--json").json()
    return list(shown["events"])


def trace_skeleton(world: World, pod: str, task_id: str) -> list[tuple[str, ...]]:
    """``skeleton_of`` the task's trace: the control flow a reviewer reads inline in the test."""
    return skeleton_of(trace_events(world, pod, task_id))


def audit_rows(world: World) -> list[dict[str, Any]]:
    """Every audit entry, as ``docket log --json`` prints the file."""
    lines = world.docket("log", "--json").out.splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def audit_gaps(
    events: Iterable[Mapping[str, Any]],
    rows: Iterable[Mapping[str, Any]],
    pod: str,
    refused: int = 0,
) -> list[str]:
    """Where the pod's ``tool.*`` audit rows and the trace's denied calls disagree.

    An allowed call leaves no row. *refused* counts the audit rows without a trace denial: handler
    refusals, and gated calls that a grant later admitted. A parked consultation has no row."""
    denied = [
        e["payload"]["tool"]
        for e in events
        if e.get("event_type") == "tool_result"
        and e["payload"].get("decision") not in (None, "allow")
        and e["payload"].get("policyId") != "consult"
    ]
    audited = [
        str(r["detail"]).split("tool=", 1)[1].split()[0]
        for r in rows
        if str(r.get("action", "")).startswith("tool.") and f"project={pod}" in str(r["detail"])
    ]
    gaps = [f"gate decision on {tool} has no audit row" for tool in denied if tool not in audited]
    if len(audited) != len(denied) + refused:
        gaps.append(
            f"{len(audited)} tool.* audit rows for {len(denied)} denials + {refused} refusals"
        )
    return gaps


def assert_audit_covers_tool_calls(
    world: World, pod: str, task_id: str, *, refused: int = 0
) -> None:
    """Every refused or denied call in the task's trace has its audit row, and no row is extra."""
    gaps = audit_gaps(trace_events(world, pod, task_id), audit_rows(world), pod, refused)
    assert not gaps, "; ".join(gaps)


def assert_transitions_legal(statuses: Sequence[str]) -> None:
    """Each consecutive pair of observed statuses is an edge of the task state table."""
    known = {s.value for s in Status}
    for status in statuses:
        assert status in known, f"{status!r} is not a task status"
    for before, after in pairwise(statuses):
        if before != after:
            edge = (Status(before), Status(after))
            assert edge in ALLOWED, f"{before} -> {after} is not a legal task transition"


def assert_checkout_untouched(world: World, head_before: str) -> None:
    """The operator's checkout kept its commit and has no change, staged or not."""
    assert world.head() == head_before, "HEAD moved in the checkout"
    dirty = world.git("status", "--porcelain")
    assert dirty == "", f"the checkout has changes:\n{dirty}"


def assert_sentinel_untouched(world: World) -> None:
    """The file in the fake home still holds the bytes it was created with."""
    found = (world.user_home / SENTINEL_NAME).read_bytes()
    assert found == SENTINEL_TEXT.encode(), f"{SENTINEL_NAME} changed: {found!r}"


def assert_log_verifies(world: World) -> None:
    """``docket log verify`` finds the audit chain intact."""
    result = world.docket("log", "verify", check=False)
    assert result.code == 0, result.describe()
