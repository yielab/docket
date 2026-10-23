"""Two ``use_home`` blocks with different roots in one process keep their files apart.

The home is a value, not module state: work done inside a block lands under that block's root
and nowhere else. Each block does real docket work (a pod, an enqueued task, an audit entry),
so a path that still resolved through a shared module constant would write into the wrong root.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.pods import build_pod

from docket.governance import audit as _audit
from docket.kernel.home import Home, current_home, use_home
from docket.tasks.application import queue as _queue

SUBJECT = "docket.kernel.home"

_PROJECT = "demo"


def _work(root: Path, task: str) -> None:
    """The same pod name in both homes, so only the root tells their files apart."""
    (root / "workspaces" / "projects").mkdir(parents=True)
    (root / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(root)):
        build_pod(_PROJECT, ("lead", "implementer"), codebase=f"/src/{_PROJECT}")
        _queue.enqueue_task_once(_PROJECT, task, channel="cli")
        _audit.audit_log("test.two_homes", task)


def _files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file()}


def test_two_homes_in_one_process_write_disjoint_files(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    bystander = current_home().root

    _work(first, "build the first thing")
    _work(second, "build the second thing")

    in_first, in_second = _files(first), _files(second)
    assert in_first and in_second
    assert all(p.is_relative_to(first) for p in in_first)
    assert all(p.is_relative_to(second) for p in in_second)
    assert not in_first & in_second
    assert not bystander.exists() or not _files(bystander)

    for root, task, other in ((first, "first", "second"), (second, "second", "first")):
        with use_home(Home(root)):
            queued = [t["description"] for t in _queue.read_tasks(_PROJECT)]
            audited = current_home().audit_log.read_text(encoding="utf-8")
        assert [d for d in queued if task in d] == queued != []
        assert task in audited and other not in audited
