"""The dispatch task ledger inside HEARTBEAT.md.

Guards ``core/memory.py``'s docket-owned dispatch region: rendering, the
insert/replace write path (and its co-authorship contract — everything
outside the two delimiters must survive byte-for-byte), the read-back used
by ``docket doctor``, and the ``TASK_LIST.json -> ledger`` projection
(``sync_dispatch_tasks``). Pure file/text operations — no pod, no daemon.
"""

from __future__ import annotations

from pathlib import Path

from docket.core import memory as _mem


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "demo-lead"
    ws.mkdir()
    return ws


class TestRenderDispatchBlock:
    def test_empty_tasks_renders_bare_delimiters(self) -> None:
        block = _mem.render_dispatch_block([])
        assert block == f"{_mem.DISPATCH_BLOCK_BEGIN}\n{_mem.DISPATCH_BLOCK_END}"

    def test_one_task_renders_a_checkbox_line(self) -> None:
        t = _mem.DispatchHeartbeatTask(
            task_id="task-1", description="Fix the bug", claimed_at="2026-07-31T00:00:00", hops=0
        )
        block = _mem.render_dispatch_block([t])
        assert "- [ ] task-1 — Fix the bug" in block
        assert "0 hops run" in block

    def test_singular_hop_word(self) -> None:
        t = _mem.DispatchHeartbeatTask(task_id="task-1", description="x", claimed_at="t", hops=1)
        assert "1 hop run" in _mem.render_dispatch_block([t])

    def test_plural_hop_word(self) -> None:
        t = _mem.DispatchHeartbeatTask(task_id="task-1", description="x", claimed_at="t", hops=2)
        assert "2 hops run" in _mem.render_dispatch_block([t])

    def test_description_collapses_whitespace_and_truncates(self) -> None:
        desc = "line one\nline two   with   spaces" + ("x" * 300)
        t = _mem.DispatchHeartbeatTask(task_id="task-1", description=desc, claimed_at="t")
        block = _mem.render_dispatch_block([t])
        # Exactly one task line between the two delimiters -- the multi-line,
        # multi-space description collapsed onto it, not spread across lines.
        assert block.count("\n") == 2
        assert "…" in block


class TestWriteDispatchTasksFreshFile:
    def test_creates_heartbeat_when_absent(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        t = _mem.DispatchHeartbeatTask(task_id="task-1", description="do it", claimed_at="t")
        _mem.write_dispatch_tasks(ws, [t])
        path = ws / _mem.HEARTBEAT_FILE
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert _mem.DISPATCH_BLOCK_BEGIN in text
        assert "task-1" in text
        assert "## Active Tasks" in text

    def test_file_is_0600(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _mem.write_dispatch_tasks(ws, [])
        mode = (ws / _mem.HEARTBEAT_FILE).stat().st_mode
        assert oct(mode)[-3:] == "600"

    def test_block_inserted_right_after_active_tasks_heading(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        t = _mem.DispatchHeartbeatTask(task_id="task-9", description="d", claimed_at="t")
        _mem.write_dispatch_tasks(ws, [t])
        text = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
        heading_idx = text.index("## Active Tasks")
        block_idx = text.index(_mem.DISPATCH_BLOCK_BEGIN)
        placeholder_idx = text.index("_none yet_")
        assert heading_idx < block_idx < placeholder_idx


class TestWriteDispatchTasksCoAuthorship:
    """The whole point of C-3: mechanical writes must never clobber an agent's
    own prose anywhere else in the file."""

    def _seeded_with_agent_prose(self, ws: Path) -> str:
        text = (
            "# HEARTBEAT.md — demo-lead\n\n"
            "## Active Tasks\n"
            "- [ ] my own hand-written task, started 2026-01-01\n"
            "  - [ ] a sub-step I already did\n\n"
            "## Pending Decisions\n"
            "- Should we use Postgres or SQLite?\n\n"
            "## Notes\n"
            "- Remember to check the staging env before merging.\n"
        )
        (ws / _mem.HEARTBEAT_FILE).write_text(text, encoding="utf-8")
        return text

    def test_first_write_preserves_existing_prose_everywhere(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        original = self._seeded_with_agent_prose(ws)
        t = _mem.DispatchHeartbeatTask(task_id="task-1", description="mechanical", claimed_at="t")
        _mem.write_dispatch_tasks(ws, [t])
        new_text = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")

        assert "my own hand-written task, started 2026-01-01" in new_text
        assert "a sub-step I already did" in new_text
        assert "Should we use Postgres or SQLite?" in new_text
        assert "Remember to check the staging env before merging." in new_text
        # Nothing from the original file was deleted -- only the dispatch
        # block was inserted.
        for line in original.splitlines():
            assert line in new_text
        assert "task-1" in new_text

    def test_second_write_with_different_tasks_only_touches_the_block(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        self._seeded_with_agent_prose(ws)
        _mem.write_dispatch_tasks(
            ws, [_mem.DispatchHeartbeatTask(task_id="task-1", description="a", claimed_at="t")]
        )
        # Agent edits their own section in between dispatch writes.
        path = ws / _mem.HEARTBEAT_FILE
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "## Notes\n- Remember to check the staging env before merging.\n",
            "## Notes\n- Remember to check the staging env before merging.\n"
            "- A brand new note the agent just added.\n",
        )
        path.write_text(text, encoding="utf-8")

        _mem.write_dispatch_tasks(
            ws, [_mem.DispatchHeartbeatTask(task_id="task-2", description="b", claimed_at="t")]
        )
        final = path.read_text(encoding="utf-8")
        assert "task-1" not in final
        assert "task-2" in final
        assert "A brand new note the agent just added." in final
        assert "my own hand-written task, started 2026-01-01" in final

    def test_clearing_tasks_leaves_prose_intact(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        self._seeded_with_agent_prose(ws)
        _mem.write_dispatch_tasks(
            ws, [_mem.DispatchHeartbeatTask(task_id="task-1", description="a", claimed_at="t")]
        )
        _mem.write_dispatch_tasks(ws, [])  # task finished -- ledger cleared
        final = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
        assert "task-1" not in final
        assert "my own hand-written task, started 2026-01-01" in final
        assert _mem.DISPATCH_BLOCK_BEGIN in final and _mem.DISPATCH_BLOCK_END in final


class TestWriteDispatchTasksIdempotent:
    def test_same_tasks_twice_is_byte_identical(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        tasks = [_mem.DispatchHeartbeatTask(task_id="task-1", description="a", claimed_at="t")]
        _mem.write_dispatch_tasks(ws, tasks)
        first = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
        _mem.write_dispatch_tasks(ws, tasks)
        second = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
        assert first == second

    def test_no_active_tasks_heading_appends_a_new_section(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        (ws / _mem.HEARTBEAT_FILE).write_text("# Custom heartbeat\nNo standard headings here.\n")
        t = _mem.DispatchHeartbeatTask(task_id="task-1", description="a", claimed_at="t")
        _mem.write_dispatch_tasks(ws, [t])
        text = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
        assert "No standard headings here." in text
        assert "## Active Tasks" in text
        assert "task-1" in text


class TestReadDispatchTaskIds:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _mem.read_dispatch_task_ids(_ws(tmp_path)) == []

    def test_no_block_yet_returns_empty(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        (ws / _mem.HEARTBEAT_FILE).write_text(_mem.heartbeat_seed("demo-lead"))
        assert _mem.read_dispatch_task_ids(ws) == []

    def test_round_trips_written_ids(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        tasks = [
            _mem.DispatchHeartbeatTask(task_id="task-a", description="x", claimed_at="t"),
            _mem.DispatchHeartbeatTask(task_id="task-b", description="y", claimed_at="t"),
        ]
        _mem.write_dispatch_tasks(ws, tasks)
        assert sorted(_mem.read_dispatch_task_ids(ws)) == ["task-a", "task-b"]

    def test_cleared_block_returns_empty(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _mem.write_dispatch_tasks(
            ws, [_mem.DispatchHeartbeatTask(task_id="task-a", description="x", claimed_at="t")]
        )
        _mem.write_dispatch_tasks(ws, [])
        assert _mem.read_dispatch_task_ids(ws) == []


class TestSyncDispatchTasks:
    def test_filters_to_running_only(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        records = [
            {"id": "task-1", "status": "running", "description": "a", "claimedAt": "t", "hops": []},
            {"id": "task-2", "status": "pending", "description": "b", "claimedAt": "", "hops": []},
            {"id": "task-3", "status": "done", "description": "c", "claimedAt": "t", "hops": []},
            {"id": "task-4", "status": "failed", "description": "d", "claimedAt": "t", "hops": []},
            {"id": "task-5", "status": "blocked", "description": "e", "claimedAt": "t", "hops": []},
            {
                "id": "task-6",
                "status": "waiting_approval",
                "description": "f",
                "claimedAt": "t",
                "hops": [],
            },
        ]
        _mem.sync_dispatch_tasks(ws, records)
        assert _mem.read_dispatch_task_ids(ws) == ["task-1"]

    def test_hop_count_reflected(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        records = [
            {
                "id": "task-1",
                "status": "running",
                "description": "a",
                "claimedAt": "t",
                "hops": [{"role": "lead"}, {"role": "implementer"}],
            }
        ]
        _mem.sync_dispatch_tasks(ws, records)
        text = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
        assert "2 hops run" in text

    def test_empty_running_set_clears_ledger(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _mem.sync_dispatch_tasks(
            ws, [{"id": "task-1", "status": "running", "description": "a", "claimedAt": "t"}]
        )
        assert _mem.read_dispatch_task_ids(ws) == ["task-1"]
        _mem.sync_dispatch_tasks(
            ws, [{"id": "task-1", "status": "done", "description": "a", "claimedAt": "t"}]
        )
        assert _mem.read_dispatch_task_ids(ws) == []

    def test_ignores_malformed_records(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        records = ["not a dict", {"status": "running"}, {"id": "", "status": "running"}]
        _mem.sync_dispatch_tasks(ws, records)  # type: ignore[arg-type]
        assert _mem.read_dispatch_task_ids(ws) == []
