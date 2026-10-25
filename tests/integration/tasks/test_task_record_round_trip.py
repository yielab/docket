"""A real queue loads into TaskRecords and dumps to the same JSON.

``task_list_2026-10-24.json`` is a scrubbed copy of two pods' queues (every status a task ends in,
with questions, briefs, gates, restrictions, pre-grants, prepared installs, usage and worktrees);
``.normalized.json`` is the same queue with every field a record always writes filled in, minus the
``claimId``, ``source``, ``pregrants``, ``taskGrants`` and ``gateOverridePipelineIndex`` keys that
no longer exist (an older queue still loads; those keys are not written back). Each record's dump must equal it, with two
stated allowances: the hop artifact's retired ``notes`` key (``""`` in every stored hop) is not
written back, and ``task-q``, a hand-written record, has options and a recommendation without their
empty ``risks``, ``estimatedTokens`` and ``evidenceRefs``, which the typed question writes out.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from docket.tasks.application.json_store import JsonTaskStore

SUBJECT = "docket.tasks.application.json_store"

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "task-records"
QUEUE = FIXTURES / "task_list_2026-10-24.json"
NORMALIZED = json.loads((FIXTURES / "task_list_2026-10-24.normalized.json").read_text())["tasks"]


_EMPTY_QUESTION_KEYS = ("risks", "estimatedTokens", "evidenceRefs")


def _allowed(record: dict[str, Any]) -> dict[str, Any]:
    """*record* without the keys the two allowances above leave out of one side."""
    out = json.loads(json.dumps(record))
    for hop in out["hops"]:
        hop["artifact"].pop("notes", None)
    question = out.get("question") or {}
    parts = [*question.get("options", []), question.get("recommendation") or {}]
    for part in parts:
        for key in _EMPTY_QUESTION_KEYS:
            if part.get(key) in ([], None):
                part.pop(key, None)
    return out


@pytest.fixture(scope="module")
def loaded() -> list[Any]:
    return JsonTaskStore(QUEUE).load()


def test_every_record_of_the_queue_loads(loaded: list[Any]) -> None:
    assert [r.id for r in loaded] == [t["id"] for t in NORMALIZED]


@pytest.mark.parametrize("index", range(len(NORMALIZED)), ids=lambda i: NORMALIZED[i]["id"])
def test_a_record_dumps_to_the_normalized_json(loaded: list[Any], index: int) -> None:
    dumped = loaded[index].model_dump(by_alias=True, mode="json")
    assert _allowed(dumped) == _allowed(NORMALIZED[index])


def test_the_queue_covers_the_statuses_and_parts_the_record_must_carry(loaded: list[Any]) -> None:
    statuses = {r.status.value for r in loaded}
    assert {"waiting_input", "waiting_approval", "done", "failed", "cancelled"} <= statuses
    present = {
        part
        for part in ("question", "brief", "gate", "restrictions", "prepared", "usage", "worktree")
        if any(getattr(r, part) is not None for r in loaded)
    }
    assert present == {"question", "brief", "gate", "restrictions", "prepared", "usage", "worktree"}
    assert any(r.consultations for r in loaded)


def test_a_modify_that_changes_nothing_rewrites_nothing(tmp_path: Path) -> None:
    copy = tmp_path / "TASK_LIST.json"
    copy.write_bytes(QUEUE.read_bytes())
    JsonTaskStore(copy).modify(lambda records: False)
    assert copy.read_bytes() == QUEUE.read_bytes()
