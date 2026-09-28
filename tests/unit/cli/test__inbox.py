"""``docket inbox`` (``cli/_inbox.py``) -- renders `core.inbox.build_inbox` and owns the
on-disk cursor (`config.INBOX_CURSOR_FILE`) that makes a repeat call show only newly-terminal
tasks. `INBOX_CURSOR_FILE` is not yet one of `tests/conftest.py`'s autouse-isolated paths, so
every test below repoints it explicitly, on top of `repoint_docket_home`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _inbox as _cli_inbox
from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.edges import store as _store

SUBJECT = "docket.cli._inbox"


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    monkeypatch.setattr(_cfg, "INBOX_CURSOR_FILE", home / "inbox-cursor.json", raising=True)
    _pod.build_pod(project, ("lead", "implementer"), codebase=f"/src/{project}")
    return home


def _seed_done_task(project: str, task_id: str, completed_at: str) -> None:
    path = _dispatch.pod_task_list_path(project)
    _store.write_json(
        path,
        {
            "tasks": [
                {
                    "id": task_id,
                    "description": "ship it",
                    "status": "done",
                    "created": "2026-09-28T00:00:00+00:00",
                    "completedAt": completed_at,
                }
            ]
        },
    )


class TestJsonOutputMatchesBuildInbox:
    def test_json_flag_prints_the_inbox_view_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _seed_done_task("demo", "task-1", "2026-09-28T01:00:00+00:00")
        capsys.readouterr()  # discard `build_pod`'s own console output

        code = _cli_inbox.run_inbox(["--json", "--peek"])

        assert code == 0
        body = json.loads(capsys.readouterr().out)
        assert set(body.keys()) == {"needsYou", "failed", "doneSince", "running", "next"}
        assert [t["id"] for t in body["doneSince"]] == ["task-1"]


class TestCursorAdvancesOnAPlainCall:
    def test_a_plain_call_advances_the_cursor_to_next(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _seed_done_task("demo", "task-1", "2026-09-28T01:00:00+00:00")

        _cli_inbox.run_inbox([])
        capsys.readouterr()

        cursor = _store.read_json(_cfg.INBOX_CURSOR_FILE)
        assert cursor["since"] == "2026-09-28T01:00:00+00:00"

    def test_a_second_plain_call_shows_no_repeat_done_item(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _seed_done_task("demo", "task-1", "2026-09-28T01:00:00+00:00")

        _cli_inbox.run_inbox(["--json"])
        capsys.readouterr()
        second_code = _cli_inbox.run_inbox(["--json"])
        second_body = json.loads(capsys.readouterr().out)

        assert second_code == 0
        assert second_body["doneSince"] == []


class TestPeekDoesNotAdvance:
    def test_peek_leaves_no_cursor_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _seed_done_task("demo", "task-1", "2026-09-28T01:00:00+00:00")

        _cli_inbox.run_inbox(["--json", "--peek"])
        capsys.readouterr()

        assert not _cfg.INBOX_CURSOR_FILE.exists()


class TestExplicitSinceDoesNotAdvance:
    def test_explicit_since_overrides_and_does_not_write_the_cursor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _seed_done_task("demo", "task-1", "2026-09-28T01:00:00+00:00")
        capsys.readouterr()  # discard `build_pod`'s own console output

        code = _cli_inbox.run_inbox(["--json", "--since", "2026-09-28T05:00:00+00:00"])
        body = json.loads(capsys.readouterr().out)

        assert code == 0
        assert body["doneSince"] == []
        assert not _cfg.INBOX_CURSOR_FILE.exists()
