"""A pod with no repository: its hops read working-directory text and its tasks run to done.

The whole product runs for real as ``python -m docket`` subprocesses; only the model is faked.
Every world here is a ``workdir``-kind pod built by ``workdir_pod``, which later worlds reuse.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, Request, say, write_file

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
) -> tuple[World, Path]:
    """A world whose pod is *blueprint* on a fresh, non-repository working directory, and that
    directory. *pipeline_yaml* is written to ``w.pipeline``; without it the blueprint's runs."""
    w = world(model)
    work_dir = w.root / "workdir"
    work_dir.mkdir()
    w.pod = "e2e-work"
    spec_file = w.root / "pod.json"
    spec_file.write_text(
        json.dumps(
            {
                "id": w.pod,
                "blueprint": blueprint,
                "workDir": str(work_dir),
                "description": "A working-directory world.",
            }
        ),
        encoding="utf-8",
    )
    if pipeline_yaml is not None:
        w.pipeline.write_text(pipeline_yaml, encoding="utf-8")
    w.docket("init", "--from", str(spec_file))
    w.docket("setup", "sandbox", "off")
    return w, work_dir


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
