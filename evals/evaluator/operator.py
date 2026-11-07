"""The scripted operator: answers what a task waits on from the task's `operator` mapping.

It runs the queue, reads the task's status and answers `waiting_approval` and `waiting_input`
through `docket task answer`, as a person at a terminal would. A pause the script does not name
is left unanswered and ends the trial: the harness has no answer, so the verdict is not the
model's to carry. An approval scripted `park` is the opposite on purpose: the script holds the
task there, recorded as an ask, for a task whose right ending is a person's decision.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from evals.evaluator.world import TrialWorld

APPROVAL_OPTIONS = ("approve_once", "approve_task", "deny")
DEFAULT_MAX_ANSWERS = 12
PARK = "park"
_WAITING = {"waiting_approval": "approval", "waiting_input": "consult"}
_MIN_SLICE_S = 1.0


@dataclass(frozen=True)
class Ask:
    """One pause the operator met: its kind (`approval` or `consult`), the prompt and the reply."""

    kind: str
    prompt: str
    answer: str


@dataclass
class OperatorOutcome:
    """How the operator's loop ended. `unscripted` names a pause the script has no answer for;
    `timed_out` and `stalled` say the task did not settle; `reason` is one line for the record;
    `statuses` is every status the operator saw, in order."""

    status: str
    asks: list[Ask] = field(default_factory=list)
    unscripted: str = ""
    timed_out: bool = False
    stalled: bool = False
    reason: str = ""
    statuses: list[str] = field(default_factory=list)


def run_operator(
    world: TrialWorld,
    task_id: str,
    script: Mapping[str, str],
    *,
    wall_s: float,
    turn_timeout_s: int = 120,
    max_answers: int = DEFAULT_MAX_ANSWERS,
) -> OperatorOutcome:
    """Run the pod's queue until the task settles, answering each pause from *script*."""
    deadline = time.monotonic() + wall_s
    outcome = OperatorOutcome(status=world.status(task_id))
    outcome.statuses.append(outcome.status)
    while True:
        remaining = deadline - time.monotonic()
        if remaining < _MIN_SLICE_S:
            return _end(outcome, world, task_id, timed_out=True, reason="wall-clock limit reached")
        command = ["run", "--timeout", str(min(turn_timeout_s, max(1, int(remaining))))]
        if world.pipeline.exists():
            command += ["--pipeline", str(world.pipeline)]
        try:
            ran = world.docket(*command, check=False, timeout=remaining)
        except subprocess.TimeoutExpired:
            return _end(outcome, world, task_id, timed_out=True, reason="wall-clock limit reached")
        status = world.status(task_id)
        outcome.statuses.append(status)
        if world.is_terminal(task_id):
            return _end(outcome, world, task_id)
        kind = _WAITING.get(status)
        if kind is None:
            tail = (ran.err or ran.out).strip().splitlines()[-1:] or [""]
            return _end(outcome, world, task_id, stalled=True, reason=f"{status}: {tail[0]}"[:300])
        if len(outcome.asks) >= max_answers:
            return _end(outcome, world, task_id, reason=f"more than {max_answers} pauses")
        wanted = script.get(kind)
        if not wanted:
            outcome.unscripted = kind
            return _end(outcome, world, task_id, reason=f"the operator script has no {kind}")
        if wanted == PARK:
            prompt = str(_pending(world, task_id).get("prompt", ""))
            outcome.asks.append(Ask(kind, prompt, PARK))
            return _end(outcome, world, task_id, reason=f"left parked for a person: {prompt}"[:300])
        ask = _answer(world, task_id, kind, wanted)
        if ask is None:
            outcome.unscripted = kind
            return _end(
                outcome, world, task_id, reason=f"no option of the {kind} matches {wanted!r}"
            )
        outcome.asks.append(ask)


def _end(
    outcome: OperatorOutcome,
    world: TrialWorld,
    task_id: str,
    *,
    timed_out: bool = False,
    stalled: bool = False,
    reason: str = "",
) -> OperatorOutcome:
    outcome.status = world.status(task_id)
    outcome.timed_out = timed_out
    outcome.stalled = stalled
    outcome.reason = reason
    return outcome


def _option_id(options: list[dict[str, Any]], wanted: str) -> str | None:
    """The option *wanted* names: its id, or the one option whose label the text holds."""
    if wanted in {str(o.get("id")) for o in options}:
        return wanted
    named = [
        str(o["id"])
        for o in options
        if str(o.get("label", "")).strip().casefold() in wanted.casefold()
        and str(o.get("label", "")).strip()
    ]
    return named[0] if len(named) == 1 else None


def _answer(world: TrialWorld, task_id: str, kind: str, wanted: str) -> Ask | None:
    """Answer the task's pause: an approval by its option, a question by the option it names or by
    text; `None` when the question has options and *wanted* names none of them."""
    pending = _pending(world, task_id)
    prompt = str(pending.get("prompt", ""))
    base = ["task", "answer", task_id, "--pod", world.pod]
    if kind == "approval":
        if wanted not in APPROVAL_OPTIONS:
            raise ValueError(f"operator approval must be one of {APPROVAL_OPTIONS}, got {wanted!r}")
        world.docket(*base, "--option", wanted)
    elif options := list(pending.get("options", [])):
        chosen = _option_id(options, wanted)
        if chosen is None:
            return None
        world.docket(*base, "--option", chosen)
    else:
        world.docket(*base, wanted)
    return Ask(kind, prompt, wanted)


def _pending(world: TrialWorld, task_id: str) -> dict[str, Any]:
    """The inbox's escalation for the task, or an empty mapping when the inbox shows none."""
    inbox = world.docket("inbox", "--peek", "--json").json()
    ids = {n["escalation"] for n in inbox.get("needsYou", []) if n.get("id") == task_id}
    for escalation in inbox.get("escalations", []):
        if escalation.get("id") in ids:
            return dict(escalation)
    return {}
