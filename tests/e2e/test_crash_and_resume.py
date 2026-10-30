"""A killed run resumes at the hop it died in, and a cancel from a second terminal stops a run.

``docket run`` is started as a real child process and killed (or cancelled) while the fake model
holds its reply; every command after that is a fresh ``python -m docket`` subprocess over the same
home. Only the model is faked.
"""

from __future__ import annotations

import contextlib
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, hold, say, write_file

PIPELINE = """name: crash-and-resume
steps:
  - plan: lead
  - implement: implementer
    verify: "sh checks/verify.sh"
    until: verify
    max: 1
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
"""

RUN = ("--timeout", "30")


@contextlib.contextmanager
def background_run(world: World, *flags: str) -> Iterator[subprocess.Popen[bytes]]:
    """``docket run`` as a child process; whatever happens, it is killed and reaped on exit."""
    log = (world.root / "background-run.log").open("wb")
    command = [sys.executable, "-m", "docket", "run", "--pipeline", str(world.pipeline), *flags]
    process = subprocess.Popen(
        command,
        cwd=world.repo,
        env=world.env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=30)
        log.close()


def requests_by_role(model: FakeModel) -> dict[str, int]:
    """How many requests each team role has made to the fake so far."""
    return {role: len(model.by_role(role)) for role in ("lead", "implementer", "reviewer")}


def test_a_run_killed_mid_hop_resumes_at_that_hop_without_repeating_earlier_ones(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    release = threading.Event()
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [write_file("app.txt", "fixed\n"), say("app.txt now says fixed.")],
            "reviewer": [hold(release, then=say("APPROVE")), say("APPROVE")],
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed")
    statuses = [w.task(task_id)["task"]["status"]]

    try:
        with background_run(w, *RUN) as run:
            w.wait_for(lambda: model.by_role("reviewer"), what="the reviewer's first request")
            assert run.poll() is None
            statuses.append(w.task(task_id)["task"]["status"])
            run.send_signal(signal.SIGKILL)
            assert run.wait(timeout=30) == -signal.SIGKILL
    finally:
        release.set()
    killed_at = requests_by_role(model)
    assert killed_at == {"lead": 1, "implementer": 2, "reviewer": 1}
    statuses.append(w.task(task_id)["task"]["status"])

    w.docket("run", "--resume", "--pipeline", str(w.pipeline), *RUN)

    statuses.append(w.task(task_id)["task"]["status"])
    assert statuses == ["pending", "running", "running", "done"]
    assert requests_by_role(model) == {**killed_at, "reviewer": 2}
    hop = ("hop_started", "reviewer", "review")
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("verification", "implementer", "passed"),
        hop,
        ("stale_claim", "lead", ""),
        hop,
        ("hop_finished", "reviewer", "approve"),
        ("session_end", "lead", "done"),
    ]
    reclaimed = [r for r in oracles.audit_rows(w) if r["action"] == "task.reclaimed"]
    assert [r["detail"] for r in reclaimed] == [
        f"{w.pod}/{task_id}: claimant pid {run.pid} is gone"
    ]
    assert "+fixed" in w.docket("task", "diff", task_id).out
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_a_running_task_cancelled_from_another_terminal_stops(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    release = threading.Event()
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [
                hold(release, then=write_file("app.txt", "fixed\n")),
                say("app.txt now says fixed."),
            ],
            "reviewer": [say("APPROVE")],
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed")

    try:
        with background_run(w, *RUN) as run:
            w.wait_for(lambda: model.by_role("implementer"), what="the implementer's request")
            statuses = [w.task(task_id)["task"]["status"]]
            cancel = w.docket("task", "cancel", task_id, "--pod", w.pod)
            release.set()
            run.wait(timeout=30)
    finally:
        release.set()

    shown = w.task(task_id)
    statuses.append(shown["task"]["status"])
    assert statuses == ["running", "cancelled"]
    assert "requested cancellation" in cancel.out
    [record] = shown["runs"]
    assert record["state"] == "cancelled"
    assert record["error"] == "cancelled by operator"
    assert record["cancellation"]["source"] == "cli"
    assert record["cancellation"]["stoppedAt"] is not None
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "fail"),
        ("session_end", "lead", "cancelled"),
    ]
    assert requests_by_role(model) == {"lead": 1, "implementer": 1, "reviewer": 0}
    actions = [r["action"] for r in oracles.audit_rows(w)]
    assert actions.count("runs.cancel") == 1 and actions.count("task.cancel") == 1
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)
