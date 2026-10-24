"""JsonTaskStore: a pod's task file read and changed as TaskRecords, under the store's lock."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from docket.kernel.threads import new_thread
from docket.tasks.adapters.json_store import JsonTaskStore
from docket.tasks.domain.task import TaskRecord

SUBJECT = "docket.tasks.adapters.json_store"


def _seed(path: Path, *tasks: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tasks": list(tasks)}, indent=2) + "\n")


def _append(records: list[TaskRecord], description: str) -> bool:
    records.append(TaskRecord(description=description))
    return True


def test_an_absent_file_holds_no_tasks(tmp_path: Path) -> None:
    assert JsonTaskStore(tmp_path / "TASK_LIST.json").load() == []


def test_load_reads_each_task_as_a_record(tmp_path: Path) -> None:
    path = tmp_path / "TASK_LIST.json"
    _seed(path, {"id": "task-1", "description": "a", "status": "running", "claimPid": 4})
    (record,) = JsonTaskStore(path).load()
    assert isinstance(record, TaskRecord)
    assert (record.id, record.status.value, record.claim_pid) == ("task-1", "running", 4)


def test_a_task_the_model_refuses_fails_the_load(tmp_path: Path) -> None:
    path = tmp_path / "TASK_LIST.json"
    _seed(path, {"id": "task-1", "description": "a", "status": "in_progress"})
    with pytest.raises(ValidationError):
        JsonTaskStore(path).load()


def test_modify_writes_back_what_the_function_changed(tmp_path: Path) -> None:
    path = tmp_path / "TASK_LIST.json"
    _seed(path, {"id": "task-1", "description": "a"})

    def _rename(records: list[TaskRecord]) -> bool:
        records[0].description = "b"
        records.append(TaskRecord(id="task-2", description="c"))
        return True

    after = JsonTaskStore(path).modify(_rename)
    assert [r.id for r in after] == ["task-1", "task-2"]
    stored = json.loads(path.read_text())["tasks"]
    assert [t["description"] for t in stored] == ["b", "c"]
    assert stored[0]["startedAt"] is None


def test_a_function_that_returns_false_leaves_the_bytes_alone(tmp_path: Path) -> None:
    path = tmp_path / "TASK_LIST.json"
    _seed(path, {"id": "task-1", "description": "a"})
    before = path.read_bytes()

    def _look(records: list[TaskRecord]) -> bool:
        records[0].description = "changed in memory only"
        return False

    JsonTaskStore(path).modify(_look)
    assert path.read_bytes() == before


def test_a_function_that_returns_false_on_an_absent_file_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "TASK_LIST.json"
    JsonTaskStore(path).modify(lambda records: False)
    assert not path.exists()


def test_concurrent_modifies_never_lose_a_task(tmp_path: Path) -> None:
    """The claim-race pattern: N threads each add one task through a locked read-modify-write."""
    path = tmp_path / "TASK_LIST.json"
    store = JsonTaskStore(path)
    n = 20
    barrier = threading.Barrier(n)

    def _add(i: int) -> None:
        barrier.wait(timeout=5)
        store.modify(lambda records: _append(records, f"t{i}"))

    threads = [new_thread(target=_add, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sorted(r.description for r in store.load()) == sorted(f"t{i}" for i in range(n))
