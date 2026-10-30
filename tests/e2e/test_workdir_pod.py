"""A pod with no repository: its hops read working-directory text and its tasks run to done.

The whole product runs for real as ``python -m docket`` subprocesses; only the model is faked.
Every world here is a ``workdir``-kind pod built by ``workdir_pod``, which later worlds reuse.
"""

from __future__ import annotations

import http.server
import json
import sys
import textwrap
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from docket.agent.tools import mcp_client as _mcp_client
from docket.kernel.templates import RECIPES_DIR
from docket.sandbox.landlock import landlock_available
from docket.sandbox.seatbelt import seatbelt_available
from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, Request, call, say, write_file

BRIEF = "# Launch brief\n\nOne page, two claims.\n"
DRAFT_AND_CHECK = """name: draft-and-check
steps:
  - plan: lead
  - draft: writer
  - check:
      run: "cat brief.md"
  - review: critic
    verdict: [APPROVE, REJECT]
    on: {REJECT: {goto: draft, max: 1}}
"""


def workdir_pod(
    world: Callable[..., World],
    model: FakeModel,
    *,
    blueprint: str = "content",
    pipeline_yaml: str | None = None,
    isolation: str = "off",
) -> tuple[World, Path]:
    """A world whose pod is *blueprint* on a fresh, non-repository working directory, and that
    directory. *pipeline_yaml* is written to ``w.pipeline``; without it the blueprint's runs.
    *isolation* ``on`` keeps what ``init`` detected; ``off`` turns the jail off."""
    w = world(model)
    w.pod = "e2e-work"
    work_dir = add_workdir_pod(w, w.pod, blueprint)
    if pipeline_yaml is not None:
        w.pipeline.write_text(pipeline_yaml, encoding="utf-8")
    if isolation == "off":
        w.docket("setup", "sandbox", "off")
    return w, work_dir


def add_workdir_pod(w: World, pod: str, blueprint: str) -> Path:
    """Register pod *pod* on a fresh working directory of its own and return that directory."""
    work_dir = w.root / f"workdir-{pod}"
    work_dir.mkdir()
    spec_file = w.root / f"{pod}.json"
    spec_file.write_text(
        json.dumps(
            {
                "id": pod,
                "blueprint": blueprint,
                "workDir": str(work_dir),
                "description": "A working-directory world.",
            }
        ),
        encoding="utf-8",
    )
    w.docket("init", "--from", str(spec_file))
    return work_dir


def _first_request_text(request: Request) -> str:
    """What the model was told on a role's first turn, tools aside: the system prompt and the task."""
    return f"{request.system_text}\n{request.last_user_text}"


def _queue_record(w: World, task_id: str) -> dict[str, Any]:
    """The task as the pod's queue file holds it: ``task show`` does not print ``failureKind``."""
    queue = w.home / "state" / "workspaces" / "projects" / f"{w.pod}-lead" / "TASK_LIST.json"
    records = json.loads(queue.read_text(encoding="utf-8"))
    tasks = records["tasks"] if isinstance(records, dict) else records
    return next(t for t in tasks if t["id"] == task_id)


def _run(w: World, *flags: str) -> None:
    w.docket("run", "--pod", w.pod, "--timeout", "30", *flags)


def test_a_content_pod_takes_a_task_to_done_with_its_output_in_the_working_directory(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: write brief.md.")],
            "writer": [write_file("brief.md", BRIEF), say("brief.md is written.")],
            "critic": [say("APPROVE")],
        }
    )
    w, work_dir = workdir_pod(world, model)
    head_before = w.head()
    task_id = w.add_task("Write the launch brief")

    _run(w)

    shown = w.task(task_id)["task"]
    assert shown["status"] == "done"
    assert shown.get("worktree") is None
    assert (work_dir / "brief.md").read_text(encoding="utf-8") == BRIEF
    oracles.assert_checkout_untouched(w, head_before)
    lead = _first_request_text(model.by_role("lead")[0])
    assert "working directory" in lead
    for stale in ("repository root", "Implementer", "repository map"):
        assert stale not in lead, stale
    for request in model.requests:
        text = _first_request_text(request).lower()
        assert "repository map" not in text and "codebase readme" not in text, request.role
    writer = model.by_role("writer")[0]
    assert "bash" not in writer.tools
    assert not {"process_output", "process_stop"} & set(writer.tools)
    assert {"write", "edit"} <= set(writer.tools)


def test_a_custom_pipeline_reworks_a_reject_and_runs_a_step_in_the_working_directory(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: write brief.md.")],
            "writer": [
                write_file("brief.md", BRIEF),
                say("first draft"),
                write_file("brief.md", BRIEF + "A third claim.\n"),
                say("second draft"),
            ],
            "critic": [say("REJECT: add a third claim"), say("APPROVE")],
        }
    )
    w, work_dir = workdir_pod(world, model, pipeline_yaml=DRAFT_AND_CHECK)
    task_id = w.add_task("Write the launch brief")

    _run(w, "--pipeline", str(w.pipeline))

    assert w.task(task_id)["task"]["status"] == "done"
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        ("hop_started", "writer", "draft"),
        ("hop_finished", "writer", "ok"),
        ("command_step", "check", "check"),
        ("hop_started", "critic", "review"),
        ("hop_finished", "critic", "reject"),
        ("verdict_rework_started", "critic", ""),
        ("hop_started", "writer", "draft"),
        ("hop_finished", "writer", "ok"),
        ("command_step", "check", "check"),
        ("hop_started", "critic", "review"),
        ("hop_finished", "critic", "approve"),
        ("session_end", "lead", "done"),
    ]
    commands = [
        e["payload"]
        for e in oracles.trace_events(w, w.pod, task_id)
        if e["event_type"] == "command_step"
    ]
    assert [(c["step"], c["cmd"], c["exit"]) for c in commands] == [
        ("check", "cat brief.md", 0),
        ("check", "cat brief.md", 0),
    ]
    assert "A third claim." in (work_dir / "brief.md").read_text(encoding="utf-8")
    plan = _first_request_text(model.by_role("lead")[0])
    assert "the role that follows in the pipeline" in plan and "Implementer" not in plan


def test_a_base_ref_on_a_working_directory_pod_fails_the_task_before_any_hop(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script={"lead": [say("never asked")]})
    w, _work_dir = workdir_pod(world, model)
    task_id = w.add_task("Write the launch brief", "--base-ref", "main")

    w.docket("run", "--pod", w.pod, "--timeout", "30", check=False)

    assert w.task(task_id)["task"]["status"] == "failed"
    assert _queue_record(w, task_id)["failureKind"] == "base_ref"
    assert w.task(task_id)["evidence"]["hops"] == []
    assert model.requests == []


BACKEND = "seatbelt" if sys.platform == "darwin" else "landlock"
needs_jail = pytest.mark.skipif(
    not (seatbelt_available() if sys.platform == "darwin" else landlock_available()),
    reason=f"{BACKEND} is not available on this host",
)


class _Hits(http.server.BaseHTTPRequestHandler):
    """Answers every GET with ``ok`` and counts it on the server."""

    def do_GET(self) -> None:
        self.server.hits += 1  # type: ignore[attr-defined]
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep the test output quiet."""


@pytest.fixture()
def local_server() -> Iterator[http.server.HTTPServer]:
    """A stdlib HTTP server on 127.0.0.1 and an ephemeral port; ``hits`` counts its requests."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _Hits)
    server.hits = 0  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _reach_pipeline(server: http.server.HTTPServer) -> str:
    """A pipeline whose one ``run:`` step fetches the local server from inside the pod."""
    fetch = (
        "import urllib.request as u; "
        f"u.urlopen('http://127.0.0.1:{server.server_port}/', timeout=5).read()"
    )
    command = json.dumps(f'python3 -c "{fetch}"')
    return f"name: reach\nsteps:\n  - plan: lead\n  - reach:\n      run: {command}\n"


def _step_exits(w: World, task_id: str) -> list[int]:
    return [
        e["payload"]["exit"]
        for e in oracles.trace_events(w, w.pod, task_id)
        if e["event_type"] == "command_step"
    ]


def _run_reach(w: World, server: http.server.HTTPServer) -> tuple[str, str, list[int], int]:
    """Queue and run one reach task: its id, its status, the run step's exits, the server hits."""
    hits_before = server.hits  # type: ignore[attr-defined]
    task_id = w.add_task("Fetch the local page")
    w.docket("run", "--pod", w.pod, "--timeout", "30", "--pipeline", str(w.pipeline), check=False)
    status = w.task(task_id)["task"]["status"]
    return task_id, status, _step_exits(w, task_id), server.hits - hits_before  # type: ignore[attr-defined]


@needs_jail
def test_a_pod_reaches_the_network_only_after_the_operators_recorded_yes(
    world: Callable[..., World],
    fake_model: Callable[..., FakeModel],
    local_server: http.server.HTTPServer,
) -> None:
    model = fake_model(script={"lead": [say("Plan: reach the page.")] * 4})
    w, _work_dir = workdir_pod(world, model, isolation="on")
    w.pipeline.write_text(_reach_pipeline(local_server), encoding="utf-8")
    first_pod = w.pod
    machine = w.docket("setup", "sandbox", "status", "--json").json()
    assert machine["isolationEnabled"] is True and machine["backend"] == BACKEND
    w.docket("setup", "sandbox", "network", "none")

    # 1. the machine is at none and the pod holds no grant: the step fails and nothing arrives
    task_id, status, exits, hits = _run_reach(w, local_server)
    assert status != "done"
    assert len(exits) == 1 and exits[0] != 0
    assert hits == 0

    # 2. the operator's recorded yes widens this pod: the same step now reaches the server
    w.docket("pod", "set", "network", "open", "--widen", "--yes", "--pod", first_pod)
    widened = [r["detail"] for r in oracles.audit_rows(w) if r["action"] == "pod.network_widen"]
    assert len(widened) == 1 and first_pod in widened[0]
    task_id, status, exits, hits = _run_reach(w, local_server)
    assert status == "done", w.task(task_id)
    assert exits == [0]
    assert hits == 1

    # 3. a second pod on the same machine holds no grant and is still cut off
    second = "e2e-work-two"
    add_workdir_pod(w, second, "content")
    w.pod = second
    task_id, status, exits, hits = _run_reach(w, local_server)
    assert status != "done"
    assert len(exits) == 1 and exits[0] != 0
    assert hits == 0
    machine = w.docket("setup", "sandbox", "status", "--json").json()
    assert machine["isolationEnabled"] is True


_ACTION_SERVER = textwrap.dedent(
    """
    import json
    import os
    from mcp.server.mcpserver import MCPServer

    app = MCPServer("world")

    @app.tool()
    def lookup(topic: str) -> str:
        return f"{topic}: the venue holds 80 people"

    @app.tool()
    def send(to: str, body: str) -> str:
        with open(os.environ["ACTION_LOG"], "a", encoding="utf-8") as log:
            log.write(json.dumps({"to": to, "body": body}) + "\\n")
        return "sent"

    app.run("stdio")
    """
)
INVITATION = "To: guest@example.test\n\nThe workshop is on Friday; the venue holds 80 people.\n"
SEND_ARGS = {"to": "guest@example.test", "body": "The workshop is on Friday."}


@pytest.mark.skipif(not _mcp_client._sdk_available(), reason="the optional mcp SDK is absent")
def test_an_outward_pod_sends_once_and_only_after_a_person_approves(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "researcher": [
                call("mcp__inbox__lookup", "r1", topic="venue"),
                say("The venue holds 80 people."),
            ],
            "writer": [write_file("draft.md", INVITATION), say("draft.md is written.")],
            "critic": [say("APPROVE")],
            "actor": [
                call("mcp__outbox__send", "a1", **SEND_ARGS),
                call("mcp__outbox__send", "a2", **SEND_ARGS),
                say("The invitation was sent."),
            ],
        }
    )
    w, _work_dir = workdir_pod(world, model)
    script = w.root / "action_server.py"
    script.write_text(_ACTION_SERVER, encoding="utf-8")
    log = w.root / "actions.jsonl"
    server = ("--env", f"ACTION_LOG={log}", "--", sys.executable, str(script))
    w.docket("setup", "mcp", "add", "inbox", "--kind", "read", "--tools", "lookup", *server)
    w.docket("setup", "mcp", "add", "outbox", "--kind", "send", "--tools", "send", *server)
    w.docket("pod", "update", str(RECIPES_DIR / "outward"), "--pod", w.pod)
    task_id = w.add_task("Invite the guest to the workshop")

    # the actor's send parks the task for a person; nothing has left the machine
    w.docket("run", "--pod", w.pod, "--timeout", "30", check=False)
    shown = w.task(task_id)["task"]
    assert shown["status"] == "waiting_approval", w.task(task_id)
    assert not log.exists()

    # one yes lets that one call run, and the task ends done
    token = next(e["id"] for e in w.docket("inbox", "--peek", "--json").json()["escalations"])
    w.docket("task", "answer", token, "--option", "approve_once", "--pod", w.pod)
    _run(w)

    assert w.task(task_id)["task"]["status"] == "done"
    assert [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] == [
        SEND_ARGS
    ]
    for role in ("researcher", "writer", "critic"):
        requests = model.by_role(role)
        assert requests, role
        assert all("mcp__outbox__send" not in r.tools for r in requests), role
    assert "mcp__inbox__lookup" in model.by_role("researcher")[0].tools
    assert all("mcp__outbox__send" in r.tools for r in model.by_role("actor"))
    assert not any("mcp__inbox__lookup" in r.tools for r in model.by_role("actor"))
    oracles.assert_log_verifies(w)
