"""A pod's task queue as one JSON file: ``{"tasks": [<task record>, ...]}``.

Every change is one locked read-modify-write of ``platform/store.py``, so two dispatchers, a
sweep and an operator never interleave. The records are ``TaskRecord`` models; this module is the
only one that turns them to and from the file's dicts."""

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
        """Run *fn* on the tasks under the file's lock and write them back when it returns
        ``True``; the file is left byte for byte as it was otherwise. Returns the tasks as they
        stand afterwards. *fn* must not read the directory the file lives in (the lock is
        per directory and not reentrant)."""
        records: list[TaskRecord] = []

        def _apply(doc: dict[str, Any]) -> dict[str, Any] | None:
            records[:] = _records(doc)
            if not fn(records):
                return None
            return {"tasks": [r.model_dump(by_alias=True, mode="json") for r in records]}

        read_modify_write(self.path, _apply)
        return records


def _records(doc: dict[str, Any]) -> list[TaskRecord]:
    raw = doc.get("tasks")
    if not isinstance(raw, list):
        return []
    return [TaskRecord.model_validate(t) for t in raw if isinstance(t, dict)]
