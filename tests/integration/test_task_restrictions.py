"""A task's restrictions and token budget narrow the live hop (real driver, stub endpoint)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off, register_local_provider
from tests.integration.llm_stub import _final_response, _ScriptedLLMServer, _tool_call_response
from tests.pods import build_pod

from docket.governance import audit as _audit
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, use_home
from docket.platform import store as _store
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.tasks.domain import task as _task
from docket.teams import fleet as _fleet
from docket.teams import settings as _settings

SUBJECT = "docket.tasks.application.queue"

_IMPLEMENTER_ONLY = """\
name: implementer-only
steps:
  - id: implementer
    role: implementer
"""


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")


@pytest.fixture()
def stub() -> Iterator[Any]:
    servers: list[_ScriptedLLMServer] = []

    def _start(responses: list[dict[str, Any]]) -> _ScriptedLLMServer:
        server = _ScriptedLLMServer(responses)
        servers.append(server)
        return server

    yield _start
    for server in servers:
        server.stop()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@contextmanager
def _seed_pod(tmp_path: Path, base_url: str) -> Iterator[None]:
    codebase = tmp_path / "code"
    codebase.mkdir()
    subprocess.run(["git", "init", str(codebase)], check=True, capture_output=True)
    _git(codebase, "config", "user.email", "t@t.test")
    _git(codebase, "config", "user.name", "T")
    (codebase / "README.md").write_text("hello\n")
    _git(codebase, "add", ".")
    _git(codebase, "commit", "-m", "init")
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        register_local_provider(home, "local", [{"id": "stub"}], base_url=base_url)
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(codebase))
        for role in ("lead", "implementer"):
            _fleet.meta_set(_pod.pod.member_id("demo", role), "model", "local/stub")
        path = _pod.pod.bound_pipeline_path("demo")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_IMPLEMENTER_ONLY, encoding="utf-8")
        digest = hashlib.sha256(_IMPLEMENTER_ONLY.encode("utf-8")).hexdigest()
        _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)
        yield


def _queue_task(**fields: Any) -> str:
    task = _queue.enqueue_task_once("demo", "write a file", channel="cli")[0]

    def _fn(doc: dict[str, Any]) -> dict[str, Any]:
        for entry in doc["tasks"]:
            if entry["id"] == task["id"]:
                entry.update(fields)
        return {"tasks": doc["tasks"]}

    _store.read_modify_write(_settings.pod_task_list_path("demo"), _fn)
    return str(task["id"])


def _run_one() -> _task.TaskResult:
    (result,) = _sweep.dispatch_pod("demo", max_tasks=1)
    return result


def test_a_task_denied_tool_is_refused_in_a_hop(tmp_path: Path, stub: Any) -> None:
    """A task's deniedTools refuses the call under policy id task-restriction and the hop goes on."""
    server = stub(
        [
            _tool_call_response("write", {"path": "out.txt", "content": "x"}),
            _final_response("could not write; done"),
        ]
    )
    with _seed_pod(tmp_path, server.base_url):
        _queue_task(restrictions={"deniedTools": ["write"]})

        result = _run_one()

        assert result.status == "done", result.reason
        denied = [e for e in _audit.read_audit() if e.get("action") == "tool.deny"]
        assert len(denied) == 1
        assert "policy_id='task-restriction'" in denied[0]["detail"]
        assert "tool=write" in denied[0]["detail"]
        assert len(server.requests) == 2
        tool_message = server.requests[1]["messages"][-1]
        assert tool_message["role"] == "tool"
        assert "task-restriction" in tool_message["content"]


def test_a_task_policy_document_blocks_a_matching_call(tmp_path: Path, stub: Any) -> None:
    """A task policy document blocks a call by path and audits it as task-restriction."""
    server = stub(
        [
            _tool_call_response("write", {"path": "secret.txt", "content": "x"}),
            _final_response("done"),
        ]
    )
    with _seed_pod(tmp_path, server.base_url):
        document = {
            "kind": "policy",
            "name": "no-secrets",
            "appliesTo": ["*"],
            "when": {"tool": "write", "path": "secret*"},
            "then": "block",
        }
        _queue_task(restrictions={"policies": [document]})

        result = _run_one()

        assert result.status == "done", result.reason
        (denied,) = [e for e in _audit.read_audit() if e.get("action") == "tool.deny"]
        assert "policy_id='task-restriction'" in denied["detail"]


def test_a_task_without_restrictions_writes_normally(tmp_path: Path, stub: Any) -> None:
    """The same scripted write is not refused when the task carries no restrictions."""
    server = stub(
        [_tool_call_response("write", {"path": "out.txt", "content": "x"}), _final_response("ok")]
    )
    with _seed_pod(tmp_path, server.base_url):
        _queue_task()

        result = _run_one()

        assert result.status == "done", result.reason
        assert [e for e in _audit.read_audit() if e.get("action") == "tool.deny"] == []


def test_a_task_policy_that_does_not_block_refuses_the_hop(tmp_path: Path, stub: Any) -> None:
    """A non-block task document is refused before the hop and no model call is made."""
    server = stub([_final_response("never reached")])
    with _seed_pod(tmp_path, server.base_url):
        document = {
            "kind": "policy",
            "name": "soft",
            "appliesTo": ["*"],
            "when": {"tool": "write"},
            "then": "warn",
        }
        _queue_task(restrictions={"policies": [document]})

        result = _run_one()

        assert result.status == "failed"
        assert result.failure_kind == "dispatch_refused"
        assert server.requests == []


def test_a_task_network_none_is_refused_when_nothing_can_cut_it(tmp_path: Path, stub: Any) -> None:
    """Network none with isolation off fails closed before any model call, scope task."""
    server = stub([_final_response("never reached")])
    with _seed_pod(tmp_path, server.base_url):
        _queue_task(restrictions={"network": "none"})

        result = _run_one()

        assert result.status == "failed"
        assert server.requests == []
        refused = [e for e in _audit.read_audit() if e.get("action") == "network.refused"]
        assert len(refused) == 1 and "scope=task" in refused[0]["detail"]


def test_the_jail_network_is_none_for_a_task_whatever_the_pod_records(
    tmp_path: Path, stub: Any
) -> None:
    """The computed hop network is cut by a task's none and open for the same pod without it."""
    from docket.agent.isolation_posture import _resolve_network
    from docket.teams import fleet as fleet

    with _seed_pod(tmp_path, stub([_final_response("x")]).base_url):
        fleet.set_network_mode("open")
        member = "demo-implementer"

        assert _resolve_network(member, "implementer", True) == (True, None)
        assert _resolve_network(member, "implementer", True, task_none=True) == (False, None)


def test_a_task_max_tokens_stops_the_task_with_failure_kind_budget(
    tmp_path: Path, stub: Any
) -> None:
    """A maxTokens the first call overruns fails the task as budget after at most one call."""
    server = stub([_final_response("this answer costs 60 tokens")])
    with _seed_pod(tmp_path, server.base_url):
        _queue_task(maxTokens=10)

        result = _run_one()

        assert result.status == "failed", result.reason
        assert result.failure_kind == "budget"
        assert len(server.requests) <= 1
        (task,) = _queue.read_tasks("demo")
        assert task["failureKind"] == "budget"


def test_a_spent_max_tokens_refuses_the_next_hop_without_a_call(tmp_path: Path, stub: Any) -> None:
    """A task whose persisted hops used the whole cap starts no further hop."""
    server = stub([_final_response("never reached")])
    with _seed_pod(tmp_path, server.base_url):
        spent_hop = {
            "role": "lead",
            "member": "demo-lead",
            "ok": True,
            "usage": {"input": 5, "output": 5},
        }
        _queue_task(maxTokens=10, hops=[spent_hop])

        result = _run_one()

        assert result.status == "failed"
        assert result.failure_kind == "budget"
        assert "maxTokens=10" in result.reason
        assert server.requests == []


def test_each_hop_runs_with_what_the_cap_has_left(tmp_path: Path, stub: Any) -> None:
    """The turn's token budget handed to the driver is maxTokens less the persisted usage."""
    seen: list[str | None] = []

    def runner(*args: Any, **_: Any) -> Any:
        from docket.agent.ports import DOCKET_TURN_TOKEN_BUDGET, TurnResult

        seen.append((args[4] or {}).get(DOCKET_TURN_TOKEN_BUDGET))
        return TurnResult(True, "done", 0.0, {})

    with _seed_pod(tmp_path, stub([_final_response("x")]).base_url):
        spent_hop = {
            "role": "lead",
            "member": "demo-lead",
            "ok": True,
            "usage": {"input": 30, "output": 10},
        }
        _queue_task(maxTokens=1000, hops=[spent_hop])

        (result,) = _sweep.dispatch_pod("demo", runner=runner, max_tasks=1)

        assert result.status == "done", result.reason
        assert seen == ["960"]
