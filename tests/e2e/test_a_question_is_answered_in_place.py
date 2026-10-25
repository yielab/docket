"""A person at the terminal answers a model's question in place, and the task never parks.

`docket run` on a real terminal waits in the turn: the `consult` shows its options with the
approval-style prompt, the person types the number of one, and the same turn goes on with that
answer. The task goes straight to done and the inbox never holds it. Only the model is faked; the
terminal is a real pseudo-terminal, and the repo, the worktree, the audit log and the approval
and escalation records are real.
"""

from __future__ import annotations

import os
import pty
import select
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, call, say

PIPELINE = """name: in-place
steps:
  - implement: implementer
"""

CACHE_QUESTION = {
    "message": "Which cache should the service use?",
    "kind": "decision",
    "options": [
        {"id": "redis", "label": "Redis", "description": "already deployed"},
        {"id": "memcached", "label": "Memcached", "description": "simpler"},
    ],
    "recommendation": {"optionId": "redis", "rationale": "it is already deployed"},
}
PROMPT = "[Enter] keep waiting"


def _read_until(master: int, needle: str, seen: str, timeout: float = 60) -> str:
    """Everything the terminal printed, read until *needle* appears in it."""
    end = time.monotonic() + timeout
    while needle not in seen:
        if time.monotonic() > end:
            raise AssertionError(f"no {needle!r} on the terminal:\n{seen}")
        if select.select([master], [], [], 0.2)[0]:
            try:
                seen += os.read(master, 4096).decode("utf-8", "replace")
            except OSError:
                break
    return seen


def _run_on_a_terminal(w: World, answer: str) -> tuple[int, str]:
    """`docket run` with a pseudo-terminal for stdin and stderr; type *answer* at the prompt.
    Returns the exit code and what the terminal showed."""
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "docket", "run", "--pipeline", str(w.pipeline), "--timeout", "30"],
        cwd=w.repo,
        env=w.env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    try:
        shown = _read_until(master, PROMPT, "")
        os.write(master, f"{answer}\n".encode())
        deadline = time.monotonic() + 60
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.2)[0]:
                try:
                    shown += os.read(master, 4096).decode("utf-8", "replace")
                except OSError:
                    break
        code = process.wait(timeout=30)
        while select.select([master], [], [], 0.2)[0]:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            shown += chunk.decode("utf-8", "replace")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
    return code, shown


def _task_status(w: World, task_id: str) -> str:
    return str(w.task(task_id)["task"]["status"])


def _inbox_rows(w: World) -> list[dict[str, Any]]:
    return list(w.docket("inbox", "--peek", "--json").json()["needsYou"])


def test_a_question_typed_at_the_terminal_is_answered_in_the_same_turn(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "implementer": [
                call("consult", "k1", **CACHE_QUESTION),
                say("Wrote the service against Redis."),
            ]
        }
    )
    w = world(model, env={"TOOL_APPROVAL_POLL_INTERVAL_S": "0.1"})
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Add a cache to the service")
    statuses = [_task_status(w, task_id)]

    code, shown = _run_on_a_terminal(w, "1")
    statuses.append(_task_status(w, task_id))

    assert code == 0, shown
    assert statuses == ["pending", "done"]
    assert "[1] redis (Redis)  [2] memcached (Memcached)" in shown
    assert "[d]ecline" in shown and "[a]pprove" not in shown
    first, resumed = model.by_role("implementer")
    assert first.tool_result("k1") is None
    answer = resumed.tool_result("k1") or ""
    assert answer.startswith("Operator answered your consultation q-")
    assert answer.endswith("option redis (Redis)")
    assert _inbox_rows(w) == []
    skeleton = oracles.trace_skeleton(w, w.pod, task_id)
    assert ("session_end", "lead", "waiting_input") not in skeleton
    assert skeleton[-1] == ("session_end", "lead", "done")
    escalations = [
        (e["event_type"], e["payload"]["kind"], e["payload"].get("by", ""))
        for e in oracles.trace_events(w, w.pod, task_id)
        if e["event_type"].startswith("escalation_")
    ]
    assert escalations == [
        ("escalation_asked", "consult", ""),
        ("escalation_resolved", "consult", "person"),
    ]
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_declining_at_the_terminal_tells_the_model_to_decide_itself(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "implementer": [
                call("consult", "k1", **CACHE_QUESTION),
                say("Decided on Redis myself."),
            ]
        }
    )
    w = world(model, env={"TOOL_APPROVAL_POLL_INTERVAL_S": "0.1"})
    w.make_pod(PIPELINE)
    task_id = w.add_task("Add a cache to the service")

    code, shown = _run_on_a_terminal(w, "d")

    assert code == 0, shown
    assert _task_status(w, task_id) == "done"
    _, resumed = model.by_role("implementer")
    assert (resumed.tool_result("k1") or "").endswith("declined. Decide yourself.")
    assert _inbox_rows(w) == []
    oracles.assert_log_verifies(w)
