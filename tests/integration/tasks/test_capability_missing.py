"""A configuration gap ends the step with `capability_missing`: the task fails, nobody is asked.

Real dispatch over a scripted chat backend; nothing touches the real DOCKET_HOME.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.home import record_isolation_off
from tests.support.llm import final as _final
from tests.support.llm import tool_calls as _tool_calls
from tests.support.pods import build_pod

from docket.agent.ports import ChatMessage, ChatResponse
from docket.hops.application import driver as _dr
from docket.hops.application import sweep as _sweep
from docket.hops.application.driver import DocketDriver
from docket.kernel.home import Home, use_home
from docket.platform import list_escalations
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod

SUBJECT = "docket.tasks.application.record"

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "operator-v2"
_PIPELINE = "name: draft\nsteps:\n  - lead: lead\n  - writer: writer\n"
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        yield


class _Backend:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def complete(self, messages: list[ChatMessage], **_: Any) -> ChatResponse:
        self.calls.append(list(messages))
        return self._responses.pop(0)


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: _Backend) -> TaskRecord:
    workspace = tmp_path / "codebase"
    workspace.mkdir()
    build_pod("demo", ("lead", "writer"), codebase=str(workspace))
    digest = hashlib.sha256(_PIPELINE.encode("utf-8")).hexdigest()
    bound = _pod.bound_pipeline_path("demo")
    bound.parent.mkdir(parents=True, exist_ok=True)
    bound.write_text(_PIPELINE, encoding="utf-8")
    _fleet.meta_set("demo-lead", "pipeline", digest)
    driver = DocketDriver(backend_factory=lambda model_name: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    queued = _queue.enqueue_task_once("demo", "Draft the proposals", channel="cli")[0]
    _sweep.dispatch_pod("demo", turn_timeout=60, max_tasks=1)
    task = TaskRepository.for_pod("demo").get(str(queued.id))
    assert task is not None
    return task


def _projection(task: TaskRecord) -> dict[str, Any]:
    """The part of the task answer this rule owns, with times replaced by a placeholder."""
    answer = task.model_dump(by_alias=True, mode="json")
    (hop,) = answer["hops"]
    shown = {
        "status": answer["status"],
        "failureKind": answer["failureKind"],
        "reason": answer["reason"],
        "escalations": answer.get("escalations", []),
        "hop": {k: hop[k] for k in ("role", "ok", "error", "capabilityMissing")},
    }
    return json.loads(_TIME.sub("<time>", json.dumps(shown)))


def test_a_lead_calling_an_undeclared_record_set_fails_the_task_and_the_writer_never_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gap is the hop's `capabilityMissing`; the task fails with it, and nobody is asked."""
    backend = _Backend(
        [_tool_calls(("rec__tack_proposals__add", {"title": "x"})), _final("never asked for")]
    )

    task = _run(tmp_path, monkeypatch, backend)

    fix = (
        "declare records/tack_proposals.yaml in the pod's configuration, "
        "then run `docket pod update --pod demo`"
    )
    assert task.status == "failed"
    assert task.failure_kind == "capability_missing"
    assert task.reason == f"lead needs records 'tack_proposals': {fix}"
    assert [h.role for h in task.hops] == ["lead"]
    gap = task.hops[0].capability_missing
    assert gap is not None
    assert (gap.kind, gap.name, gap.fix) == ("records", "tack_proposals", fix)
    assert list_escalations() == []
    assert len(backend.calls) == 1

    actual = _projection(task)
    if record := os.environ.get("OPERATOR_RECORD_DIR"):
        Path(record, "task-capability-missing.json").write_text(
            json.dumps(actual, indent=2) + "\n", encoding="utf-8"
        )
    assert actual == json.loads((FIXTURES / "task-capability-missing.json").read_text("utf-8"))
