"""A pod's task queue as one JSON file: ``{"tasks": [<task record>, ...], "rev": <counter>}``.

Every change is one locked read-modify-write of ``platform/store.py``, so two dispatchers, a
sweep and an operator never interleave. The records are ``TaskRecord`` models; this module is the
only one that turns them to and from the file's dicts. It is also the one place that stamps
``rev``: a task whose content changed in a write (or that is new) takes the next counter value."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from docket.platform import read_json, read_modify_write
from docket.tasks.domain.task import TaskRecord

__all__ = ["JsonTaskStore"]


class JsonTaskStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[TaskRecord]:
        """Every task in the file, oldest first; none when the file is absent."""
        return _records(read_json(self.path))

    def modify(self, fn: Callable[[list[TaskRecord]], bool]) -> list[TaskRecord]:
        """Run *fn* on the tasks under the file's lock; write them back only if it returns ``True``
        (otherwise the bytes are untouched). Returns the tasks as they stand afterwards."""
        # *fn* must not read the directory the file lives in: the lock is per directory and not
        # reentrant.
        records: list[TaskRecord] = []

        def _apply(doc: dict[str, Any]) -> dict[str, Any] | None:
            records[:] = _records(doc)
            before = {r.id: _content(r) for r in records}
            if not fn(records):
                return None
            counter = _counter(doc, records)
            for r in records:
                if before.get(r.id) != _content(r):
                    counter += 1
                    r.rev = counter
            out: dict[str, Any] = {
                "tasks": [r.model_dump(by_alias=True, mode="json") for r in records]
            }
            if counter:
                out["rev"] = counter
            return out

        read_modify_write(self.path, _apply)
        return records


def _records(doc: dict[str, Any]) -> list[TaskRecord]:
    raw = doc.get("tasks")
    if not isinstance(raw, list):
        return []
    return [TaskRecord.model_validate(t) for t in raw if isinstance(t, dict)]


def _content(record: TaskRecord) -> dict[str, Any]:
    """The record's dump without its ``rev``: what a change is judged on."""
    return record.model_dump(by_alias=True, mode="json", exclude={"rev"})


def _counter(doc: dict[str, Any], records: list[TaskRecord]) -> int:
    """The last value handed out: the file's counter, or the highest ``rev`` a task holds."""
    stored = doc.get("rev")
    top = max((r.rev for r in records), default=0)
    return max(stored if isinstance(stored, int) else 0, top)
