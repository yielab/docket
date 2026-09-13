"""`docket pipeline run <project> --follow`.

`--follow` runs the exact same `_pod_dispatch` call `docket pipeline run` already makes (no
second, drift-prone execution path) on a background thread, while the foreground thread tails
`core/trace.py`'s durable JSONL store — the same one `docket trace tail`/`export` read — for new
events as the dispatch writes them. Proves the dispatch still completes for real, at least one
trace event reaches stdout, and `--follow` is stripped before `_pod_dispatch`'s own
`--resume`/`--timeout` parsing sees the remaining args.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home
from tests.fakes import FakeDriver

import docket.config as _cfg
from docket.cli._pipeline import run_pipeline
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet

SUBJECT = "docket.core"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")

    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps({"agents": [], "bindings": []}))

    repoint_docket_home(monkeypatch, home)


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = _cfg.PROJECTS_DIR / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.rsplit("-", 1)[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "modelSource": "policy",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member_id, meta["model"], meta["sessionKey"], "default")


def _install_fake_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    # `docket pipeline run`'s CLI dispatcher has no `runner=` injection
    # point -- it always resolves the production driver internally, so a
    # real dispatch means monkeypatching that resolution point itself.
    # FakeDriver is the one supported test double for a RuntimeDriver.
    monkeypatch.setattr(
        "docket.edges.adapters.docket_runtime.default_driver",
        lambda: FakeDriver(ok=True, cost=0.0),
    )


class TestPipelineRunFollow:
    def test_follow_dispatches_for_real_and_streams_a_trace_event(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _install_fake_driver(monkeypatch)
        _write_meta("demo-lead")
        _dispatch.enqueue_task("demo", "a task")

        rc = run_pipeline("run", ["demo", "--follow"])

        assert rc == 0
        assert _dispatch.read_tasks("demo")[0]["status"] == "done"
        out = capsys.readouterr().out
        assert "Following dispatch for 'demo'" in out
        # session_start is the first trace event dispatch_task emits, before
        # the hop even runs -- proof this is a live tail of the real trace
        # store dispatch writes to, not just the final `_pod_dispatch` summary.
        assert "session_start" in out

    def test_follow_flag_is_stripped_before_reaching_pod_dispatch_arg_parsing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A stray `--follow` must not be misread as `--timeout`'s value or
        otherwise confuse `_pod_dispatch`'s own flag parsing."""
        _install_fake_driver(monkeypatch)
        _write_meta("demo-lead")
        _dispatch.enqueue_task("demo", "a task")

        rc = run_pipeline("run", ["demo", "--follow", "--timeout", "30"])

        assert rc == 0
        assert _dispatch.read_tasks("demo")[0]["status"] == "done"

    def test_follow_with_no_pending_tasks_is_still_a_warning_not_an_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_meta("demo-lead")
        rc = run_pipeline("run", ["demo", "--follow"])
        assert rc == 0

    def test_follow_on_an_invalid_custom_file_is_still_an_error_before_dispatching(
        self, tmp_path: Path
    ) -> None:
        _write_meta("demo-lead")
        f = tmp_path / "broken.pipeline.yaml"
        f.write_text(
            "name: broken\nsteps:\n  - id: build\n    role: implementer\n    verifyCommand: x\n"
        )
        assert run_pipeline("run", ["demo", "--file", str(f), "--follow"]) == 1
