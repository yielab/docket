"""A pod's task queue as typed records: the one door to read it and to change it.

``TaskRepository`` holds a store (``adapters/json_store.py`` is the one implementation) and the
Lead's workspace, where the dispatch ledger of ``HEARTBEAT.md`` lives. Every change runs under the
store's lock, and after every write the ledger is regenerated from the stored records, so no
caller has to remember to.

The lock is the Lead directory's. A function handed to ``update``, ``update_each``, ``add`` or
``claim_next`` runs inside it, so it must not call ``load_pod_settings``, ``meta_get`` or anything
else that reads that directory (the lock is not reentrant: it would wait on itself). Resolve what
it needs before the call."""

from __future__ import annotations

import os as _os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.tasks.application.transitions import apply_to_task
from docket.tasks.domain import state as _state
from docket.tasks.domain.task import HopResult, TaskRecord
from docket.teams import agent_memory as _mem
from docket.teams import pod as _pod
from docket.teams.settings import pod_task_list_path

__all__ = ["Claim", "TaskRepository", "TaskStore"]

Records = list[TaskRecord]

_PRIORITY_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}


class TaskStore(Protocol):
    """What the repository needs of a store: every task, and a locked change of them."""

    def load(self) -> list[TaskRecord]: ...

    def modify(self, fn: Callable[[list[TaskRecord]], bool]) -> list[TaskRecord]: ...


@dataclass(frozen=True)
class Claim:
    """A claimed task. ``gate_override_index`` is the pipeline position a granted approval asked
    the claim to resume at; the stored record no longer holds it (it is single use)."""

    record: TaskRecord
    resume_hops: list[HopResult]
    gate_override_index: int | None


class TaskRepository:
    def __init__(self, store: TaskStore, lead_workspace: Path) -> None:
        self._store = store
        self._lead_workspace = lead_workspace

    @classmethod
    def for_pod(cls, project: str, open_store: Callable[[Path], TaskStore]) -> TaskRepository:
        """The repository of *project*'s queue: the file in its Lead's workspace, opened by
        *open_store*."""
        lead_id = _pod.member_id(project, "lead")
        return cls(open_store(pod_task_list_path(project)), current_home().workspace_dir(lead_id))

    def get(self, task_id: str) -> TaskRecord | None:
        return next((r for r in self._store.load() if r.id == task_id), None)

    def add(self, record: TaskRecord) -> tuple[TaskRecord, bool]:
        """Append *record*, or return the task already queued under its ``idempotency_key``
        (found inside the lock) with ``False``."""
        key = record.idempotency_key
        outcome: list[tuple[TaskRecord, bool]] = []

        def _fn(records: list[TaskRecord]) -> bool:
            queued = next(
                (r for r in records if key is not None and r.idempotency_key == key), None
            )
            if queued is not None:
                outcome.append((queued, False))
                return False
            records.append(record)
            outcome.append((record, True))
            return True

        self._change(_fn)
        return outcome[0]

    def update(self, task_id: str, fn: Callable[[TaskRecord], object]) -> TaskRecord | None:
        """Run *fn* on task *task_id* under the lock and write it back; ``None``, and nothing
        written, when the queue has no such task."""
        found: list[TaskRecord] = []

        def _fn(records: list[TaskRecord]) -> bool:
            record = next((r for r in records if r.id == task_id), None)
            if record is None:
                return False
            fn(record)
            found.append(record)
            return True

        self._change(_fn)
        return found[0] if found else None

    def update_each(self, fn: Callable[[TaskRecord], bool]) -> Records:
        """Run *fn* on every task under the lock; one write if any returned ``True``. Returns
        the tasks *fn* changed."""
        changed: list[TaskRecord] = []

        def _fn(records: list[TaskRecord]) -> bool:
            for record in records:
                if fn(record):
                    changed.append(record)
            return bool(changed)

        self._change(_fn)
        return changed

    def claim_next(self, *, resume: bool, skip: frozenset[str] = frozenset()) -> Claim | None:
        """Claim the next eligible task, highest priority first, in one locked change: it moves
        to ``running`` and its ``gate_override_pipeline_index`` is cleared from the stored record
        and handed back in the ``Claim``. ``pending`` is always eligible; a ``failed`` task with
        a resumable ``failure_kind`` only when *resume*. A task id in *skip* is never picked."""
        claimed: list[Claim] = []

        def _fn(records: list[TaskRecord]) -> bool:
            candidates = [r for r in records if r.id not in skip and _eligible(r, resume=resume)]
            if not candidates:
                return False
            record = min(candidates, key=lambda r: _PRIORITY_RANK.get(r.priority, 1))
            apply_to_task(record, _state.Status.running, now=_clock.iso(), pid=_os.getpid())
            override = record.gate_override_pipeline_index
            record.gate_override_pipeline_index = None
            claimed.append(Claim(record, list(record.hops), override))
            return True

        self._change(_fn)
        return claimed[0] if claimed else None

    def _change(self, fn: Callable[[list[TaskRecord]], bool]) -> None:
        wrote = False

        def _tracked(records: list[TaskRecord]) -> bool:
            nonlocal wrote
            wrote = fn(records)
            return wrote

        records = self._store.modify(_tracked)
        if wrote:
            _mem.sync_dispatch_tasks(
                self._lead_workspace, [r.model_dump(by_alias=True, mode="json") for r in records]
            )

    def list(self) -> Records:
        """Every task, oldest first."""
        return self._store.load()


def _eligible(record: TaskRecord, *, resume: bool) -> bool:
    if record.status == _state.Status.pending:
        return True
    return (
        resume
        and record.status == _state.Status.failed
        and record.failure_kind in _state.RESUMABLE_FAILURE_KINDS
    )
