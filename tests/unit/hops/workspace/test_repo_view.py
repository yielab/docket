"""The base-commit reader a turn registers for its worktree (`hops/workspace/repo_view.py`).

Pins that a registered view is local to the turn that registered it: the children of a
``parallel`` group run concurrently in one task worktree, so one child ending its turn must
never take the view away from a sibling still running, which would send the sibling's reads
to the agent-writable worktree.
"""

from __future__ import annotations

import threading
from pathlib import Path

from docket.hops.workspace import repo_view as _repo_view
from docket.pipeline.domain import plan as _orch

SUBJECT = "docket.hops.workspace.repo_view"


def _view(commit: str) -> _repo_view.RepoView:
    return _repo_view.RepoView(commit, lambda rel: b"x", lambda rel: [])


def test_a_view_is_seen_only_while_registered(tmp_path: Path) -> None:
    view = _view("base")
    token = _repo_view.register(tmp_path, view)
    assert _repo_view.view_for(tmp_path) is view
    _repo_view.unregister(token)
    assert _repo_view.view_for(tmp_path) is None


def test_a_sibling_ending_its_turn_keeps_the_other_siblings_view(tmp_path: Path) -> None:
    both_registered = threading.Barrier(2)
    first_done = threading.Event()
    seen: dict[str, object] = {}

    def turn(name: str) -> None:
        token = _repo_view.register(tmp_path, _view(name))
        both_registered.wait(timeout=5)
        try:
            if name == "slow":
                first_done.wait(timeout=5)
                view = _repo_view.view_for(tmp_path)
                seen[name] = view.commit if view is not None else None
        finally:
            _repo_view.unregister(token)
            if name == "fast":
                first_done.set()

    _orch.run_group(["slow", "fast"], turn)

    assert seen["slow"] == "slow"
    assert _repo_view.view_for(tmp_path) is None
