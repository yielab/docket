"""The fake model speaks the wire docket's real chat client parses.

Each reply builder is served by a ``FakeModel`` and read by ``OpenAIChatClient.complete``; the
outcome asserted is what the client gives today, so a drift in either side fails here.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from tests.support.model_server import (
    FakeModel,
    Reply,
    call,
    calls,
    fail,
    hang,
    hold,
    not_json,
    say,
    truncated,
)

from docket.agent.ports import ChatResponse, Endpoint, FailureKind, ToolCall, system, user
from docket.models.adapters.openai_http import OpenAIChatClient, probe_models

SUBJECT = "docket.models.adapters.openai_http"

_ROLE_LINE = "You are the **{role}** of the **demo** pod (agent id `demo-{role}`)."


@dataclass(frozen=True)
class Outcome:
    ok: bool = True
    failure_kind: FailureKind | None = None
    retry_after_s: float | None = None
    finish_reason: str = "stop"
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default=())
    error_has: str = ""


_CASES: list[tuple[str, Reply, Outcome]] = [
    ("say", say("hello"), Outcome(content="hello")),
    (
        "call",
        call("write", "c1", path="a.txt", content="x"),
        Outcome(
            finish_reason="tool_calls",
            tool_calls=(ToolCall("c1", "write", json.dumps({"path": "a.txt", "content": "x"})),),
        ),
    ),
    (
        "calls",
        calls([("read", {"path": "a"}), ("read", {"path": "b"}, "second")]),
        Outcome(
            finish_reason="tool_calls",
            tool_calls=(
                ToolCall("call-1", "read", json.dumps({"path": "a"})),
                ToolCall("second", "read", json.dumps({"path": "b"})),
            ),
        ),
    ),
    ("fail 400", fail(400), Outcome(False, "nonzero_exit", finish_reason="", error_has="HTTP 400")),
    (
        "fail 429",
        fail(429, retry_after=1),
        Outcome(False, "daemon_error", retry_after_s=1, finish_reason="", error_has="HTTP 429"),
    ),
    ("fail 503", fail(503), Outcome(False, "daemon_error", finish_reason="", error_has="HTTP 503")),
    ("hang", hang(3), Outcome(False, "timeout", finish_reason="", error_has="timed out")),
    (
        "not_json",
        not_json(),
        Outcome(False, "invalid_output", finish_reason="", error_has="non-JSON"),
    ),
    ("truncated", truncated("cut o"), Outcome(finish_reason="length", content="cut o")),
]


def _client(model: FakeModel) -> OpenAIChatClient:
    return OpenAIChatClient(Endpoint(base_url=model.base_url, model_id="e2e-model"))


def _ask(model: FakeModel, text: str = "hi", timeout: int = 1) -> ChatResponse:
    return _client(model).complete([user(text)], timeout=timeout)


@pytest.mark.parametrize(("reply", "want"), [c[1:] for c in _CASES], ids=[c[0] for c in _CASES])
def test_the_real_client_reads_each_reply_builder(
    fake_model: Callable[..., FakeModel], reply: Reply, want: Outcome
) -> None:
    got = _ask(fake_model(sequence=[reply]))

    assert (got.ok, got.failure_kind, got.retry_after_s) == (
        want.ok,
        want.failure_kind,
        want.retry_after_s,
    )
    assert got.finish_reason == want.finish_reason
    assert want.error_has in got.error
    assert got.message.content == want.content
    assert tuple(got.message.tool_calls) == want.tool_calls


def test_a_request_past_the_context_window_is_refused_with_the_body_in_the_error(
    fake_model: Callable[..., FakeModel],
) -> None:
    model = fake_model(sequence=[say("fits")], context_window_chars=100)

    over = _ask(model, "x" * 101)
    fits = _ask(model, "x" * 100)

    assert (over.ok, over.failure_kind) == (False, "nonzero_exit")
    assert "request exceeds the available context size" in over.error
    assert fits.ok and fits.message.content == "fits"


def test_a_held_reply_is_withheld_until_the_event_is_set(
    fake_model: Callable[..., FakeModel],
) -> None:
    release = threading.Event()
    model = fake_model(sequence=[hold(release, say("released"))])
    done: list[ChatResponse] = []
    worker = threading.Thread(target=lambda: done.append(_ask(model, timeout=10)))
    worker.start()

    assert not done and not release.is_set()
    release.set()
    worker.join(timeout=10)

    assert [r.message.content for r in done] == ["released"]


def test_usage_counts_message_characters_and_the_reply(
    fake_model: Callable[..., FakeModel],
) -> None:
    got = _ask(fake_model(sequence=[say("x" * 40)]), "y" * 80)

    assert (got.usage.input_tokens, got.usage.output_tokens) == (20, 10)


def test_each_role_reads_its_own_script_from_the_system_prompt(
    fake_model: Callable[..., FakeModel],
) -> None:
    model = fake_model({"lead": [say("plan")], "implementer": [say("built"), say("rebuilt")]})
    client = _client(model)

    def ask(role: str) -> str:
        return client.complete(
            [system(_ROLE_LINE.format(role=role)), user("go")], timeout=5
        ).message.content

    assert [ask("implementer"), ask("lead"), ask("implementer")] == ["built", "plan", "rebuilt"]
    assert [r.last_user_text for r in model.by_role("implementer")] == ["go", "go"]


@pytest.mark.parametrize("role", ["lead", "reviewer"], ids=["exhausted role", "unscripted role"])
def test_a_role_without_a_step_left_fails_loudly(
    fake_model: Callable[..., FakeModel], role: str
) -> None:
    model = fake_model({"lead": [say("once")]})
    client = _client(model)
    messages = [system(_ROLE_LINE.format(role=role)), user("go")]
    first = client.complete(messages, timeout=5)

    got = client.complete(messages, timeout=5)

    assert (got.ok, got.failure_kind) == (False, "nonzero_exit")
    assert "fake model:" in got.error
    assert first.ok == (role == "lead")


def test_a_request_with_no_role_line_is_refused_in_script_mode(
    fake_model: Callable[..., FakeModel],
) -> None:
    got = _ask(fake_model({"lead": [say("never")]}))

    assert (got.ok, got.failure_kind) == (False, "nonzero_exit")
    assert "no role line" in got.error


def test_an_exhausted_sequence_fails_loudly_unless_the_last_reply_repeats(
    fake_model: Callable[..., FakeModel],
) -> None:
    strict = fake_model(sequence=[say("one")])
    repeating = fake_model(sequence=[say("one")], repeat_last=True)

    assert [_ask(strict).ok, _ask(strict).ok] == [True, False]
    assert [_ask(repeating).message.content for _ in range(3)] == ["one"] * 3


def test_a_step_may_react_to_the_request_it_answers(
    fake_model: Callable[..., FakeModel],
) -> None:
    model = fake_model(
        sequence=[lambda req: say("gate failed" if "GATE FAILED" in req.last_user_text else "ok")]
        * 2
    )

    assert [_ask(model, "GATE FAILED: tests").message.content, _ask(model).message.content] == [
        "gate failed",
        "ok",
    ]


def test_the_models_listing_is_served_to_the_real_probe_and_other_paths_are_404(
    fake_model: Callable[..., FakeModel],
) -> None:
    model = fake_model(models=("alpha", "beta"))

    probe = probe_models(Endpoint(base_url=model.base_url, model_id="alpha"))
    missing = probe_models(Endpoint(base_url=model.base_url + "/elsewhere", model_id="alpha"))

    assert (probe.status, probe.model_ids, model.models_calls) == (200, ["alpha", "beta"], 1)
    assert missing.status == 404
