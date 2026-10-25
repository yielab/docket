"""A model that fails the way providers fail ends the task with the reason an operator can act on.

The whole product runs for real as ``python -m docket`` subprocesses over a real git repo; only
the model is faked, and it answers with provider errors, slow replies, bad bodies, bad tool calls
and a context window too small for what the turn sends.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, Reply, call, fail, hang, not_json, say, truncated

PIPELINE = """name: model-failures
steps:
  - implement: implementer
"""

FAST_RETRIES = {
    "DISPATCH_RETRIES_DEFAULT": "1",
    "DISPATCH_RETRY_MAX_WAIT_S": "1",
    "AGENT_LOOP_REQUEST_TIMEOUT_S": "2",
}

DONE = say("Finished.")


def run_one(world: World, text: str = "Make app.txt say fixed") -> tuple[str, int]:
    """Provision the pod, queue a task, run it; return ``(task_id, exit code)``."""
    world.make_pod(PIPELINE)
    task_id = world.add_task(text)
    run = world.docket("run", "--pipeline", str(world.pipeline), "--timeout", "30", check=False)
    return task_id, run.code


def failure_reason(world: World, task_id: str) -> str:
    """The reason the inbox gives for a failed task."""
    failed = world.docket("inbox", "--json").json()["failed"]
    assert [f["id"] for f in failed] == [task_id]
    return str(failed[0]["reason"])


@pytest.mark.parametrize(
    ("first", "kind", "reason"),
    [
        pytest.param(
            fail(400, "bad request body"), "nonzero_exit", "bad request body", id="http-400"
        ),
        pytest.param(not_json(), "invalid_output", "non-JSON", id="not-json"),
        pytest.param(truncated("cut off"), None, "truncated", id="truncated"),
    ],
)
def test_a_provider_failure_that_retrying_cannot_fix_fails_the_task_at_once(
    world: Callable[..., World],
    fake_model: Callable[..., FakeModel],
    first: Reply,
    kind: str | None,
    reason: str,
) -> None:
    model = fake_model(script={"implementer": [first, DONE]})
    w = world(model, env=FAST_RETRIES)

    task_id, code = run_one(w)

    assert code == 1
    assert w.task(task_id)["task"]["status"] == "failed"
    assert reason in failure_reason(w, task_id)
    assert len(model.by_role("implementer")) == 1
    events = oracles.trace_events(w, w.pod, task_id)
    assert [e for e in events if e["event_type"] == "hop_retry"] == []
    assert [e["payload"]["failureKind"] for e in events if e["event_type"] == "llm_call"] == [kind]
    oracles.assert_log_verifies(w)


@pytest.mark.parametrize(
    ("first", "kind", "waited"),
    [
        pytest.param(fail(429, "slow down", retry_after=1), "daemon_error", 1.0, id="http-429"),
        pytest.param(fail(503, "overloaded"), "daemon_error", None, id="http-503"),
        pytest.param(hang(5), "timeout", None, id="request-timeout"),
    ],
)
def test_a_transient_provider_failure_is_retried_and_the_task_finishes(
    world: Callable[..., World],
    fake_model: Callable[..., FakeModel],
    first: Reply,
    kind: str,
    waited: float | None,
) -> None:
    model = fake_model(script={"implementer": [first, DONE]})
    w = world(model, env=FAST_RETRIES)

    task_id, code = run_one(w)

    assert code == 0
    assert w.task(task_id)["task"]["status"] == "done"
    assert len(model.by_role("implementer")) == 2
    events = oracles.trace_events(w, w.pod, task_id)
    retries = [e["payload"] for e in events if e["event_type"] == "hop_retry"]
    assert [(r["failure_kind"], r["attempt"], r["retry_after_s"]) for r in retries] == [
        (kind, 1, waited)
    ]
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("verification", "implementer", "skipped"),
        ("session_end", "lead", "done"),
    ]
    oracles.assert_log_verifies(w)


def test_three_invalid_tool_calls_end_the_turn(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    calls_made = [call("no_such_tool", f"c{i}") for i in (1, 2, 3)]
    model = fake_model(script={"implementer": [*calls_made, DONE]})
    w = world(model, env=FAST_RETRIES)

    task_id, code = run_one(w)

    assert code == 1
    assert w.task(task_id)["task"]["status"] == "failed"
    reason = failure_reason(w, task_id)
    assert "consecutive tool denials" in reason and "count=3" in reason
    assert len(model.by_role("implementer")) == 3
    results = [
        e["payload"]
        for e in oracles.trace_events(w, w.pod, task_id)
        if e["event_type"] == "tool_result"
    ]
    assert [(r["tool"], r["decision"], r["denialKind"]) for r in results] == [
        ("no_such_tool", "deny", "invalid_call")
    ] * 3
    assert "unknown tool 'no_such_tool'" in results[0]["reason"]
    audited = [r for r in oracles.audit_rows(w) if r["action"].startswith("tool.")]
    assert audited == [], "an invalid call never reaches the gate, so it leaves no gate decision"
    oracles.assert_log_verifies(w)


@pytest.mark.parametrize(
    ("env", "status"),
    [
        pytest.param({}, "failed", id="default-tool-output-cap"),
        pytest.param({"DOCKET_TOOL_MAX_OUTPUT_CHARS": "2500"}, "done", id="capped-tool-output"),
    ],
)
def test_a_small_context_window_fails_loudly_and_a_capped_tool_output_fits(
    world: Callable[..., World],
    fake_model: Callable[..., FakeModel],
    env: dict[str, str],
    status: str,
) -> None:
    model = fake_model(
        script={"implementer": [call("read", path="big.txt", limit=1600), DONE]},
        context_window_chars=12_000,
    )
    w = world(model, env={**FAST_RETRIES, **env})
    (w.repo / "big.txt").write_text(
        "".join(f"line {n:05d} of a long file\n" for n in range(1600)), encoding="utf-8"
    )
    w.git("add", "-A")
    w.git("commit", "-q", "-m", "add a 40 kB file")

    task_id, code = run_one(w)

    assert w.task(task_id)["task"]["status"] == status
    requests = model.by_role("implementer")
    assert len(requests) == 2
    carried = requests[1].tool_result("call-1") or ""
    if status == "failed":
        assert len(carried) > 12_000
        assert code == 1
        assert "request exceeds the available context size" in failure_reason(w, task_id)
    else:
        assert code == 0
        assert 0 < len(carried) <= 2_600
    oracles.assert_log_verifies(w)
