"""Whether an enqueue is trusted input: the channel decides unless the request says so."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.pods import seed_lean_pod, write_policy
from typer.testing import CliRunner

from docket.governance import policy as _policy
from docket.interfaces.cli.app import app as _app
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository

SUBJECT = "docket.tasks.application.queue"

live_server = _support_http.live_server
pod_home = _support_pods.pod_home_bare


@pytest.fixture
def pre_input_trust(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """The ``trusted`` flag of every ``pre_input`` evaluation the enqueue makes."""
    seen: list[bool] = []
    real = _policy.policy_eval_detail

    def spy(role: str, hook: str, text: str, **kwargs: Any) -> Any:
        if hook == "pre_input":
            seen.append(bool(kwargs.get("trusted")))
        return real(role, hook, text, **kwargs)

    monkeypatch.setattr(_policy, "policy_eval_detail", spy)
    return seen


def test_an_http_enqueue_without_trusted_is_untrusted(
    live_server: tuple[str, str], pre_input_trust: list[bool]
) -> None:
    url, token = live_server
    seed_lean_pod("myapp")

    status, _ = _support_http.post(f"{url}/tasks/myapp", {"description": "do it"}, token)

    assert status == 201
    assert pre_input_trust == [False]


def test_an_http_enqueue_that_says_trusted_is_trusted(
    live_server: tuple[str, str], pre_input_trust: list[bool]
) -> None:
    url, token = live_server
    seed_lean_pod("myapp")

    status, _ = _support_http.post(
        f"{url}/tasks/myapp", {"description": "do it", "trusted": True}, token
    )

    assert status == 201
    assert pre_input_trust == [True]


def test_an_operator_block_policy_refuses_an_untrusted_http_task(
    live_server: tuple[str, str], pod_home: Path
) -> None:
    url, token = live_server
    seed_lean_pod("myapp")
    write_policy("no-wire", "pre_input", "wire the money", "block")

    status, body = _support_http.post(
        f"{url}/tasks/myapp", {"description": "wire the money"}, token
    )

    assert status == 400 and "no-wire" in body["error"]
    assert TaskRepository.for_pod("myapp").list() == []


def test_task_add_enqueues_trusted(pre_input_trust: list[bool]) -> None:
    seed_lean_pod("myapp")

    result = CliRunner().invoke(_app, ["task", "add", "fix it", "--pod", "myapp"])

    assert result.exit_code == 0, result.output
    assert pre_input_trust == [True]


@pytest.mark.parametrize(
    ("channel", "expected"), [("cli", True), ("http", False), ("mcp", False), ("routine", True)]
)
def test_the_channel_sets_the_default_and_an_explicit_value_wins(
    channel: str, expected: bool, pre_input_trust: list[bool]
) -> None:
    seed_lean_pod("myapp")

    _queue.enqueue_task_once("myapp", "one", channel=channel)
    _queue.enqueue_task_once("myapp", "two", channel=channel, trusted=not expected)

    assert pre_input_trust == [expected, not expected]
