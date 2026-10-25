"""An operator who is not at the terminal sees the run park, answers from the inbox, and it resumes.

A non-interactive `docket run` parks a gated call or a question instead of waiting for a person.
Everything the operator does is a `docket` command: `inbox`, `task approve` (once, for the task,
or ahead of time with `--for`), `task deny`, `task answer`. Only the model is faked; the
repo, the task worktree, the audit log and the park/resume machinery are real.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, Request, call, say, write_file

PIPELINE = """name: operator-loop
steps:
  - implement: implementer
"""

GATED = "rm -rf build"
CACHE_QUESTION = {
    "message": "Which cache should the service use?",
    "kind": "decision",
    "options": [
        {"id": "redis", "label": "Redis", "description": "already deployed"},
        {"id": "memcached", "label": "Memcached", "description": "simpler"},
    ],
    "recommendation": {"optionId": "redis", "rationale": "it is already deployed"},
}
PARKED = [
    ("hop_started", "implementer", "implement"),
    ("hop_finished", "implementer", "fail"),
]
DONE = [
    ("hop_started", "implementer", "implement"),
    ("hop_finished", "implementer", "ok"),
    ("verification", "implementer", "skipped"),
    ("session_end", "lead", "done"),
]


def _run_the_queue(w: World) -> None:
    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")


def _status(w: World, task_id: str) -> str:
    return str(w.task(task_id)["task"]["status"])


def _escalations(w: World, task_id: str) -> list[tuple[str, str, str]]:
    """The task's ``escalation_*`` events as ``(event, kind, by)``, in trace order. The trace
    skeleton keeps the older events; this is the same pauses told with the one payload."""
    return [
        (e["event_type"], e["payload"]["kind"], e["payload"].get("by", ""))
        for e in oracles.trace_events(w, w.pod, task_id)
        if e["event_type"].startswith("escalation_")
    ]


def _needs_you(w: World) -> list[dict[str, Any]]:
    return list(w.docket("inbox", "--peek", "--json").json()["needsYou"])


def _consult_description(request: Request) -> str:
    tools = {t["function"]["name"]: t["function"] for t in request.body["tools"]}
    return str(tools["consult"]["description"])


def _worktree(w: World, task_id: str) -> Path:
    return Path(w.task(task_id)["task"]["worktree"]["path"])


def _audit_actions(w: World, prefix: str) -> list[str]:
    return [str(r["action"]) for r in oracles.audit_rows(w) if str(r["action"]).startswith(prefix)]


def _the_model_saw_the_rules_and_the_reason_but_no_token(model: FakeModel, token: str) -> None:
    """Everything the Implementer was sent states the bash rules, explains the park, hides the token."""
    sent = model.by_role("implementer")
    wire = json.dumps([r.body for r in sent])
    assert token not in wire and not re.search(r"apr[-_][0-9A-Za-z-]+", wire)
    bash = next(
        t["function"]["description"]
        for t in sent[-1].body["tools"]
        if t["function"]["name"] == "bash"
    )
    assert "Runs without approval: " in bash and "Needs approval: " in bash
    refusals = [
        m["content"]
        for r in sent
        for m in r.messages
        if m.get("role") == "tool" and str(m.get("content")).startswith("REFUSED [approval_parked]")
    ]
    assert refusals and all(
        "not on the curated allowlist" in text
        and text.endswith("a person must approve this command; the task resumes once they do")
        for text in refusals
    )


def test_a_parked_approval_shows_in_the_inbox_and_a_task_grant_covers_the_rest(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "implementer": [
                write_file("build/out.txt", "artifact\n"),
                call("bash", "c2", command=GATED),
                call("bash", "c3", command=GATED),
                call("bash", "c4", command=GATED),
                say("build directory removed."),
            ]
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Remove the build directory")
    statuses = [_status(w, task_id)]

    _run_the_queue(w)
    statuses.append(_status(w, task_id))

    (parked,) = _needs_you(w)
    token = parked["approvalToken"]
    assert (parked["id"], parked["state"]) == (task_id, "needs_approval")
    assert token.startswith("apr-")
    assert parked["command"] == f"docket task approve {task_id}"
    listing = w.docket("inbox", "--peek").out
    assert f"task {task_id}" in listing and GATED in listing and "needs approval" in listing
    assert (_worktree(w, task_id) / "build" / "out.txt").exists()
    assert len(model.by_role("implementer")) == 2

    w.docket("task", "approve", token, "--task", "--pod", w.pod)
    statuses.append(_status(w, task_id))
    (ready,) = _needs_you(w)
    assert (ready["id"], ready["state"]) == (task_id, "approved_ready")
    assert ready["command"] == f"docket run --pod {w.pod}"

    _run_the_queue(w)
    statuses.append(_status(w, task_id))

    assert statuses == ["pending", "waiting_approval", "pending", "done"]
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        *PARKED,
        ("approval_required", "implementer", ""),
        ("session_end", "lead", "waiting_approval"),
        ("approval_resumed", "lead", ""),
        *DONE,
    ]
    assert _escalations(w, task_id) == [("escalation_asked", "approval", "")]
    assert len(model.by_role("implementer")) == 5
    _the_model_saw_the_rules_and_the_reason_but_no_token(model, token)
    assert not (_worktree(w, task_id) / "build").exists()
    assert _needs_you(w) == []
    assert "Needs you" not in w.docket("inbox", "--peek").out
    assert _audit_actions(w, "approval.consume") == ["approval.consume"] * 2
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id, refused=2)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_a_pre_grant_lets_a_run_pass_without_stopping(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "implementer": [
                write_file("build/out.txt", "artifact\n"),
                call("bash", "c2", command=GATED),
                say("build directory removed."),
            ]
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Remove the build directory")
    statuses = [_status(w, task_id)]

    granted = w.docket("task", "approve", task_id, "--for", GATED, "--pod", w.pod)
    statuses.append(_status(w, task_id))
    _run_the_queue(w)
    statuses.append(_status(w, task_id))

    assert statuses == ["pending", "pending", "done"]
    assert "Pre-granted" in granted.out and _needs_you(w) == []
    assert oracles.trace_skeleton(w, w.pod, task_id) == DONE
    assert len(model.by_role("implementer")) == 3
    assert not (_worktree(w, task_id) / "build").exists()
    assert _audit_actions(w, "approval.") == ["approval.pregrant", "approval.consume"]
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id, refused=1)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_a_question_from_the_model_waits_for_an_answer(
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
    w = world(model)
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Add a cache to the service")
    statuses = [_status(w, task_id)]

    _run_the_queue(w)
    statuses.append(_status(w, task_id))

    (asked,) = _needs_you(w)
    assert (asked["id"], asked["state"]) == (task_id, "needs_answer")
    assert asked["question"]["message"] == CACHE_QUESTION["message"]
    assert [o["id"] for o in asked["question"]["options"]] == ["redis", "memcached"]
    assert asked["question"]["recommendation"]["optionId"] == "redis"
    assert asked["command"] == f"docket task answer {task_id}"
    listing = w.docket("inbox", "--peek").out
    assert (
        "Which cache should the service use?" in listing
        and "redis (Redis) (recommended)" in listing
    )

    unknown = w.docket("task", "answer", task_id, "--option", "etcd", "--pod", w.pod, check=False)
    assert unknown.code != 0 and _status(w, task_id) == "waiting_input"

    w.docket("task", "answer", task_id, "--option", "redis", "--pod", w.pod)
    statuses.append(_status(w, task_id))
    _run_the_queue(w)
    statuses.append(_status(w, task_id))

    assert statuses == ["pending", "waiting_input", "pending", "done"]
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        *PARKED,
        ("session_end", "lead", "waiting_input"),
        ("input_answered", "lead", "implement"),
        *DONE,
    ]
    assert _escalations(w, task_id) == [("escalation_asked", "consult", "")]
    first, resumed = model.by_role("implementer")
    assert "ENDS your turn" in _consult_description(first)
    assert "3 consultations left" in _consult_description(first)
    assert "2 consultations left" in _consult_description(resumed)
    assert "Operator answered" not in first.last_user_text
    assert (
        f"Operator answered your consultation {asked['question']['id']}" in resumed.last_user_text
    )
    assert "option redis (Redis)" in resumed.last_user_text
    assert _needs_you(w) == []
    assert _audit_actions(w, "task.answer") == ["task.answer"]
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_a_parked_question_carries_the_deadline_the_pod_sets(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script={"implementer": [call("consult", "k1", **CACHE_QUESTION)]})
    w = world(model)
    w.make_pod(PIPELINE)
    w.docket("pod", "set", "inputExpiryHours", "1", "--pod", w.pod)
    task_id = w.add_task("Add a cache to the service")

    _run_the_queue(w)

    (asked,) = _needs_you(w)
    deadline = dt.datetime.fromisoformat(asked["question"]["expiresAt"])
    remaining = (deadline - dt.datetime.now(dt.UTC)).total_seconds()
    assert (asked["id"], asked["state"]) == (task_id, "needs_answer")
    assert 3000 < remaining <= 3600
    assert _status(w, task_id) == "waiting_input"
    oracles.assert_log_verifies(w)


def test_an_unanswered_question_expires_to_blocked(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script={"implementer": [call("consult", "k1", **CACHE_QUESTION)]})
    w = world(model)
    w.make_pod(PIPELINE)
    w.docket("pod", "set", "inputExpiryHours", "1", "--pod", w.pod)
    task_id = w.add_task("Add a cache to the service")
    statuses = [_status(w, task_id)]

    _run_the_queue(w)
    statuses.append(_status(w, task_id))
    (asked,) = _needs_you(w)
    assert (asked["id"], asked["state"]) == (task_id, "needs_answer")

    w.env["DOCKET_CLOCK_OFFSET_S"] = "7200"
    with w.service(dispatch=False):
        w.wait_for(lambda: _status(w, task_id) == "blocked", what="the question to expire")
    del w.env["DOCKET_CLOCK_OFFSET_S"]
    statuses.append(_status(w, task_id))

    assert statuses == ["pending", "waiting_input", "blocked"]
    (blocked,) = _needs_you(w)
    assert (blocked["id"], blocked["state"], blocked["command"]) == (
        task_id,
        "blocked",
        f"docket task retry {task_id}",
    )
    assert blocked["reason"] == f"question {asked['question']['id']!r} expired unanswered"
    assert blocked["question"] is None
    assert ("input_expired", "lead", "") in oracles.trace_skeleton(w, w.pod, task_id)
    assert _escalations(w, task_id) == [
        ("escalation_asked", "consult", ""),
        ("escalation_expired", "consult", "timeout"),
    ]
    assert len(model.by_role("implementer")) == 1

    w.docket("task", "retry", task_id, "--pod", w.pod)
    statuses.append(_status(w, task_id))
    assert statuses[-1] == "pending"
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_a_denied_approval_fails_the_task_with_the_reason(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "implementer": [
                write_file("build/out.txt", "artifact\n"),
                call("bash", "c2", command=GATED),
                say("build directory removed."),
            ]
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Remove the build directory")
    statuses = [_status(w, task_id)]

    _run_the_queue(w)
    statuses.append(_status(w, task_id))
    denied = w.docket("task", "deny", task_id, "--reason", "not today", "--pod", w.pod)
    statuses.append(_status(w, task_id))

    assert statuses == ["pending", "waiting_approval", "failed"]
    assert "Denied" in denied.out
    (failed,) = w.docket("inbox", "--json").json()["failed"]
    assert (failed["id"], failed["reason"]) == (task_id, "approval denied: not today")
    assert _needs_you(w) == []
    corrections = w.task(task_id)["corrections"]
    assert [(c["kind"], c["text"]) for c in corrections] == [("deny_reason", "not today")]
    assert "not today" in w.docket("task", "show", task_id, "--pod", w.pod).out
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        *PARKED,
        ("approval_required", "implementer", ""),
        ("session_end", "lead", "waiting_approval"),
        ("approval_task_denied", "lead", ""),
    ]
    assert len(model.by_role("implementer")) == 2
    assert (_worktree(w, task_id) / "build" / "out.txt").exists()
    assert _audit_actions(w, "approval.") == ["approval.deny"]
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)
