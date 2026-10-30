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
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
    on: {REQUEST-CHANGES: {goto: draft, max: 1}}
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
            "reviewer": [say("APPROVE")],
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


def test_a_custom_pipeline_reworks_a_request_for_changes_and_runs_a_step_in_the_working_directory(
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
            "reviewer": [say("REQUEST-CHANGES: add a third claim"), say("APPROVE")],
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
        ("hop_started", "reviewer", "review"),
        ("hop_finished", "reviewer", "request-changes"),
        ("rework_started", "reviewer", "cycle 1"),
        ("hop_started", "writer", "draft"),
        ("hop_finished", "writer", "ok"),
        ("command_step", "check", "check"),
        ("hop_started", "reviewer", "review"),
        ("hop_finished", "reviewer", "approve"),
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


WRITE_WAIT_REVIEWER = """name: write-wait-reviewer
steps:
  - draft: writer
  - hold: {wait: 1h}
  - review: reviewer
"""


def test_a_task_sleeps_at_a_wait_step_across_runs_and_wakes_on_a_service_tick(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "writer": [write_file("brief.md", BRIEF), say("brief.md is written.")],
            "reviewer": [say("APPROVE")],
        }
    )
    w, work_dir = workdir_pod(world, model, pipeline_yaml=WRITE_WAIT_REVIEWER)
    task_id = w.add_task("Write the launch brief")

    _run(w, "--pipeline", str(w.pipeline))

    assert w.task(task_id)["task"]["status"] == "waiting_input"
    assert (work_dir / "brief.md").read_text(encoding="utf-8") == BRIEF
    inbox = w.docket("inbox", "--peek", "--json").json()
    assert inbox["needsYou"] == []
    (wait,) = inbox["escalations"]
    assert (wait["kind"], wait["policy"], wait["task"]) == ("wait", "machine", task_id)

    _run(w, "--pipeline", str(w.pipeline))

    assert w.task(task_id)["task"]["status"] == "waiting_input"
    assert model.by_role("reviewer") == []

    w.env["DOCKET_CLOCK_OFFSET_S"] = "7200"
    with w.service(dispatch=True):
        w.wait_for(
            lambda: w.task(task_id)["task"]["status"] == "done", what="the wait to end and run on"
        )
    del w.env["DOCKET_CLOCK_OFFSET_S"]

    assert len(model.by_role("reviewer")) == 1
    assert [e["kind"] for e in w.docket("inbox", "--peek", "--json").json()["escalations"]] == []


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
            "reviewer": [say("APPROVE")],
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
    for role in ("researcher", "writer", "reviewer"):
        requests = model.by_role(role)
        assert requests, role
        assert all("mcp__outbox__send" not in r.tools for r in requests), role
    assert "mcp__inbox__lookup" in model.by_role("researcher")[0].tools
    assert all("mcp__outbox__send" in r.tools for r in model.by_role("actor"))
    assert not any("mcp__inbox__lookup" in r.tools for r in model.by_role("actor"))
    oracles.assert_log_verifies(w)


_DETAIL_SERVER = _ACTION_SERVER.replace(
    "def send(to: str, body: str) -> str:",
    "def send(to: str, body: str, phone: str, headers: dict) -> str:",
)
_FAKE_TOKEN = "tkn_" + "Z9y8X7w6" * 4
_DETAIL_ARGS = {
    "to": "ana@example.test",
    "body": "The workshop is on Friday.",
    "phone": "+57 300 1234567",
    "headers": {"Authorization": f"Bearer {_FAKE_TOKEN}"},
}


@pytest.mark.skipif(not _mcp_client._sdk_available(), reason="the optional mcp SDK is absent")
def test_the_approver_of_a_send_sees_the_whole_call_and_every_other_copy_stays_redacted(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "researcher": [say("Nothing to look up.")],
            "writer": [write_file("draft.md", INVITATION), say("draft.md is written.")],
            "reviewer": [say("APPROVE")],
            "actor": [
                call("mcp__outbox__send", "a1", **_DETAIL_ARGS),
                call("mcp__outbox__send", "a2", **_DETAIL_ARGS),
                say("The invitation was sent."),
            ],
        }
    )
    w, _work_dir = workdir_pod(world, model)
    script = w.root / "action_server.py"
    script.write_text(_DETAIL_SERVER, encoding="utf-8")
    log = w.root / "actions.jsonl"
    server = ("--env", f"ACTION_LOG={log}", "--", sys.executable, str(script))
    w.docket("setup", "mcp", "add", "inbox", "--kind", "read", "--tools", "lookup", *server)
    w.docket("setup", "mcp", "add", "outbox", "--kind", "send", "--tools", "send", *server)
    w.docket("pod", "update", str(RECIPES_DIR / "outward"), "--pod", w.pod)
    task_id = w.add_task("Invite the guest to the workshop")
    w.docket("run", "--pod", w.pod, "--timeout", "30", check=False)
    assert w.task(task_id)["task"]["status"] == "waiting_approval", w.task(task_id)

    escalation = w.docket("inbox", "--peek", "--json").json()["escalations"][0]
    esc_id = escalation["id"]
    assert escalation["outward"] is True and "call" not in escalation

    def approval_files() -> list[dict[str, Any]]:
        return [json.loads(p.read_text("utf-8")) for p in w.home.rglob("approvals/apr-*.json")]

    # the operator's own views show the address and the phone, never the credential
    for ref in (esc_id, task_id):
        shown = w.docket("task", "show", ref, "--pod", w.pod).out
        assert "What leaves" in shown and "action leaves the pod" in shown, shown
        assert "ana@example.test" in shown and "+57 300 1234567" in shown
        assert _FAKE_TOKEN not in shown
    with w.service(dispatch=False) as svc:
        status, one = svc.get(f"/escalations/{esc_id}")
        assert status == 200 and one["outward"] is True and one["state"] == "pending"
        assert "ana@example.test" in one["call"] and "+57 300 1234567" in one["call"]
        assert _FAKE_TOKEN not in one["call"] and "mcp__outbox__send" in one["call"]
        copies = [svc.get("/escalations")[1], svc.get("/inbox")[1]]
        assert svc.get("/escalations/esc-000000000000")[0] == 404
    copies += [
        w.docket("inbox", "--peek").out,
        w.docket("inbox", "--peek", "--json").out,
        w.docket("task", "trace", task_id, "--pod", w.pod, "--export").out,
        w.docket("log", "--json").out,
    ]
    for copy in copies:
        text = copy if isinstance(copy, str) else json.dumps(copy)
        assert "ana@example.test" not in text and _FAKE_TOKEN not in text
        assert '"call":' not in text.replace(" ", "")
    pending = [r for r in approval_files() if r["state"] == "pending"]
    assert len(pending) == 1 and _FAKE_TOKEN not in pending[0]["call"]

    # one yes lets the call run; the settled approval no longer holds it
    w.docket("task", "answer", esc_id, "--option", "approve_once", "--pod", w.pod)
    assert all("call" not in r for r in approval_files())
    _run(w)

    assert w.task(task_id)["task"]["status"] == "done"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    rows = oracles.audit_rows(w)
    assert [r["action"] for r in rows].count("tool.send") == 1
    with w.service(dispatch=False) as svc:
        status, settled = svc.get(f"/escalations/{esc_id}")
    assert status == 200 and settled["state"] == "resolved" and "call" not in settled


_QUOTA_ARGS = [{"to": "guest@example.test", "body": f"Invitation {n}"} for n in (1, 2, 3)]


@pytest.mark.skipif(not _mcp_client._sdk_available(), reason="the optional mcp SDK is absent")
def test_an_outward_pod_over_its_send_quota_is_refused_and_audited_and_status_shows_the_count(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    first, second, third = _QUOTA_ARGS
    model = fake_model(
        script={
            "researcher": [say("Nothing to look up.")],
            "writer": [write_file("draft.md", INVITATION), say("draft.md is written.")],
            "reviewer": [say("APPROVE")],
            "actor": [
                call("mcp__outbox__send", "a1", **first),
                call("mcp__outbox__send", "a2", **first),
                call("mcp__outbox__send", "a3", **second),
                call("mcp__outbox__send", "a4", **second),
                call("mcp__outbox__send", "a5", **third),
                say("The invitations that fit the quota were sent."),
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
    quota = w.home / "config" / "policies" / "two-a-day.yaml"
    quota.parent.mkdir(parents=True, exist_ok=True)
    quota.write_text(
        "kind: policy\nname: two-a-day\nappliesTo: [actor]\n"
        "limit: {kind: send, count: 2, per: day}\nthen: block\n",
        encoding="utf-8",
    )
    task_id = w.add_task("Invite the guest to the workshop")

    # each distinct send parks for a person; one yes lets that call and its twin run
    for _ in range(2):
        w.docket("run", "--pod", w.pod, "--timeout", "30", check=False)
        assert w.task(task_id)["task"]["status"] == "waiting_approval", w.task(task_id)
        token = next(e["id"] for e in w.docket("inbox", "--peek", "--json").json()["escalations"])
        w.docket("task", "answer", token, "--option", "approve_once", "--pod", w.pod)
    _run(w)

    # the fifth call is over 2/2: refused before anyone is asked, so the task is done
    assert w.task(task_id)["task"]["status"] == "done", w.task(task_id)
    assert [json.loads(line) for line in log.read_text("utf-8").splitlines()] == [first, second]
    rows = oracles.audit_rows(w)
    sends = [r for r in rows if r["action"] == "tool.send"]
    assert ["decision=allow" in r["detail"] for r in sends] == [True, True, False]
    assert "decision=deny" in sends[-1]["detail"]
    assert "policy_id='two-a-day' policy_action='block'" in sends[-1]["detail"]
    refused = [r for r in rows if r["action"] == "tool.deny" and "2/2 per day" in r["detail"]]
    assert len(refused) == 1
    assert not w.docket("inbox", "--peek", "--json").json()["escalations"]

    shown = w.docket("status", "--pod", w.pod)
    assert "send 2/2 today" in shown.out, shown.out
    assert w.docket("status", "--pod", w.pod, "--json").json()["quotas"] == [
        {"scope": "send", "used": 2, "count": 2, "per": "day"},
        {"scope": "send", "used": 2, "count": 10, "per": "day"},
    ]
    oracles.assert_log_verifies(w)


ROUTINE_PIPELINE = """name: heartbeat
steps:
  - plan: lead
"""

ROUTINE = """kind: routine
name: heartbeat
schedule: "@every 1h"
task:
  description: Write the heartbeat note
"""


def test_a_routine_creates_its_task_and_the_service_runs_it_to_done(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script={"lead": [say("Heartbeat noted.")]})
    w, _work_dir = workdir_pod(world, model, pipeline_yaml=ROUTINE_PIPELINE)
    w.docket("pod", "set", "pipeline", str(w.pipeline), "--pod", w.pod)
    folder = w.home / "config" / "pods" / w.pod / "routines"
    folder.mkdir(parents=True)
    (folder / "heartbeat.yaml").write_text(ROUTINE, encoding="utf-8")

    def listed() -> list[dict[str, str]]:
        tasks = w.docket("task", "list", "--pod", w.pod, "--json").json()["tasks"]
        assert isinstance(tasks, list)
        return tasks

    with w.service(interval=1):
        w.wait_for(lambda: listed() and listed()[0]["status"] == "done", 60, "the routine's task")

    (summary,) = listed()
    task = _queue_record(w, summary["id"])
    assert task["channel"] == "routine"
    assert task["idempotencyKey"].startswith("routine:heartbeat:")
    (row,) = w.docket("pod", "routine", "list", "--pod", w.pod, "--json").json()
    assert row["last"] is not None and task["idempotencyKey"] == f"routine:heartbeat:{row['last']}"
    actions = {(e["action"], e["detail"]) for e in oracles.audit_rows(w)}
    assert any(
        a == "routine.fire" and f"task={summary['id']}" in d and f"slot={row['last']}" in d
        for a, d in actions
    )
    assert any(
        a == "task.enqueue" and f"task={summary['id']}" in d and "channel=routine" in d
        for a, d in actions
    )
    oracles.assert_log_verifies(w)
