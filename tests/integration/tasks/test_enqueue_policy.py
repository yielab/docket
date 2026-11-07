"""A ``pre_input`` block policy refuses an enqueue over HTTP before anything is persisted."""

from __future__ import annotations

from pathlib import Path

from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.pods import seed_lean_pod, write_policy

from docket.tasks.application.repository import TaskRepository

SUBJECT = "docket.tasks.application.queue"

live_server = _support_http.live_server
pod_home = _support_pods.pod_home_bare


def test_an_operator_block_policy_refuses_an_http_task(
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
