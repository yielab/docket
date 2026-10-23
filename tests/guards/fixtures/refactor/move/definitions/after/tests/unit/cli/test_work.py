"""Work tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.cli import work
from docket.core import dispatch as _dispatch
from docket.hops import runner as _runner

SUBJECT = "docket.cli.work"


def test_work_runs_the_hop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[Path] = []
    monkeypatch.setattr(_runner, "run_hop", lambda path: seen.append(path) or "")
    monkeypatch.setattr(_dispatch, "finish", lambda path: "done")
    monkeypatch.setattr("docket.tasks.claim.claim_next", lambda path: None)
    assert work.work(tmp_path).startswith("done")
    assert seen == [tmp_path]
