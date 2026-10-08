"""``docket inbox``: renders `core.inbox.build_inbox`, owns the on-disk cursor and puts the
exact `docket task ...` command on every item. `INBOX_CURSOR_FILE` is not one of
`tests/conftest.py`'s autouse-isolated paths, so every test repoints it explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _pod
from docket.cli import app as _app
from docket.core import approval as _approval
from docket.core import dispatch as _dispatch
from docket.edges import store as _store

SUBJECT = "docket.cli._inbox"

runner = CliRunner()


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    monkeypatch.setattr(_cfg, "INBOX_CURSOR_FILE", home / "inbox-cursor.json", raising=True)
    _pod.build_pod(project, ("lead", "implementer"), codebase=f"/src/{project}")
    return home


def _tasks(project: str, *tasks: dict[str, Any]) -> None:
    base = {"description": "ship it", "created": "2026-09-28T00:00:00+00:00"}
    _store.write_json(
        _dispatch.pod_task_list_path(project), {"tasks": [{**base, **t} for t in tasks]}
    )


def _inbox(*args: str) -> Any:
    return runner.invoke(_app, ["inbox", *args])


class TestHumanView:
    def test_a_waiting_input_task_prints_its_question_options_and_answer_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _tasks(
            "demo",
            {
                "id": "task-q",
                "status": "waiting_input",
                "question": {
                    "id": "q-1",
                    "taskId": "task-q",
                    "pod": "demo",
                    "step": "lead",
                    "message": "Where is README.md?",
                    "requestedSchema": {
                        "type": "object",
                        "properties": {"note": {"type": "string"}},
                    },
                    "createdAt": "2026-09-28T00:00:00Z",
                    "kind": "clarification",
                    "options": [
                        {"id": "opt1", "label": "Root", "description": "At the root."},
                        {"id": "opt2", "label": "Search", "description": "Search."},
                    ],
                    "recommendation": {"optionId": "opt2", "rationale": "safer"},
                },
            },
        )

        out = _inbox("--peek").output

        assert "Q: Where is README.md?" in out
        assert "opt2 (Search) (recommended)" in out
        assert "docket task answer task-q" in out

    def test_a_held_approval_prints_the_whole_command_and_both_decisions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        action = "tool call 'bash': git push origin production --force-with-lease " + "x" * 300
        token = _approval.approval_create(
            "demo", "implementer", action, context={"tool": "bash", "parked": True}
        )
        _tasks("demo", {"id": "task-a", "status": "waiting_approval", "approvalToken": token})

        out = _inbox("--peek").output

        assert action in out
        assert "docket task approve task-a" in out
        assert "docket task deny task-a" in out
        assert token not in out


class TestJsonView:
    def test_items_carry_state_and_command_and_no_escape_codes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _tasks(
            "demo",
            {"id": "t-done", "status": "done", "completedAt": "2026-09-28T01:00:00+00:00"},
            {"id": "t-failed", "status": "failed", "reason": "boom"},
        )

        result = _inbox("--json", "--peek")

        assert "\x1b" not in result.stdout
        body = json.loads(result.stdout)
        assert set(body) == {"needsYou", "failed", "doneSince", "running", "next"}
        assert body["doneSince"][0]["state"] == "done"
        assert body["failed"][0]["command"] == "docket task retry t-failed"

    def test_a_granted_task_is_approved_ready_and_points_at_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _tasks("demo", {"id": "t-ok", "status": "pending", "gateOverridePipelineIndex": 2})

        body = json.loads(_inbox("--json", "--peek").stdout)

        item = body["needsYou"][0]
        assert item["state"] == "approved_ready"
        assert item["command"] == "docket run --pod demo"

    def test_a_plain_pending_task_is_not_listed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _tasks("demo", {"id": "t-new", "status": "pending"})
        assert json.loads(_inbox("--json", "--peek").stdout)["needsYou"] == []


class TestUsage:
    def test_an_unknown_flag_exits_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed(tmp_path, monkeypatch)
        result = _inbox("--bogus")
        assert result.exit_code == 2
        assert "--bogus" in result.output


class TestCursor:
    def test_a_plain_call_advances_it_and_a_repeat_shows_no_done_item(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _tasks("demo", {"id": "t1", "status": "done", "completedAt": "2026-09-28T01:00:00+00:00"})

        first = json.loads(_inbox("--json").stdout)
        second = json.loads(_inbox("--json").stdout)

        assert [t["id"] for t in first["doneSince"]] == ["t1"]
        assert second["doneSince"] == []
        assert _store.read_json(_cfg.INBOX_CURSOR_FILE)["since"] == "2026-09-28T01:00:00+00:00"

    def test_peek_and_explicit_since_leave_no_cursor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _tasks("demo", {"id": "t1", "status": "done", "completedAt": "2026-09-28T01:00:00+00:00"})

        _inbox("--json", "--peek")
        body = json.loads(_inbox("--json", "--since", "2026-09-28T05:00:00+00:00").stdout)

        assert body["doneSince"] == []
        assert not _cfg.INBOX_CURSOR_FILE.exists()
