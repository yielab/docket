"""`core/memory.py`: distillation and the HEARTBEAT.md dispatch ledger.

Distillation: a driver failure or empty reply leaves every file on disk
untouched; a real run archives pending daily logs and appends the reply to
`MEMORY.md`. Ledger: rendering, the write path preserving an agent's own
prose byte-for-byte outside the delimited block, and the read-back.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest
from tests.fakes import FakeDriver

import docket.config as _cfg
from docket.core import memory as _mem
from docket.core.runtime_driver import TurnResult

SUBJECT = "docket.core.memory"

# ── helpers ──────────────────────────────────────────────────────────────────


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "memory").mkdir(parents=True)
    return ws


def _write_log(ws: Path, day: str, text: str = "did stuff\n") -> Path:
    p = ws / "memory" / f"{day}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _empty_output_driver(
    agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None = None
) -> TurnResult:
    """A driver that "succeeds" but replies with nothing usable."""
    return TurnResult(True, "   ", 0.0, {})


# ── pending_daily_logs ───────────────────────────────────────────────────────


class TestPendingDailyLogs:
    def test_no_memory_dir_returns_empty(self, tmp_path: Path) -> None:
        assert _mem.pending_daily_logs(tmp_path / "nope") == []

    def test_lists_logs_oldest_first_and_excludes_archive(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _write_log(ws, "2026-07-02")
        _write_log(ws, "2026-07-01")
        archive = ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME / "2026-06-30"
        archive.mkdir(parents=True)
        (archive / "2026-06-29.md").write_text("old\n", encoding="utf-8")

        logs = _mem.pending_daily_logs(ws)

        assert [p.name for p in logs] == ["2026-07-01.md", "2026-07-02.md"]


# ── distill_memory: nothing pending ─────────────────────────────────────────


class TestDistillMemoryNothingPending:
    def test_skips_without_calling_the_driver(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        fake = FakeDriver()

        result = _mem.distill_memory(
            ws, label="demo", agent_id="demo", session_key="agent:demo:default", driver=fake
        )

        assert result.ok is True
        assert result.skipped is True
        assert result.logs_distilled == 0
        assert fake.calls == []
        assert not (ws / "MEMORY.md").exists()


# ── distill_memory: fail-closed ──────────────────────────────────────────────


class TestDistillMemoryFailsClosed:
    def test_driver_failure_leaves_everything_untouched(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        log = _write_log(ws, "2026-07-01", "important stuff\n")
        fake = FakeDriver(fail_role="demo", error="boom", failure_kind="daemon_error")

        result = _mem.distill_memory(
            ws, label="demo", agent_id="demo", session_key="agent:demo:default", driver=fake
        )

        assert result.ok is False
        assert result.error == "boom"
        assert result.failure_kind == "daemon_error"
        assert result.logs_distilled == 0
        assert result.archived == []
        # Nothing moved, nothing written -- fail-closed.
        assert log.exists()
        assert log.read_text(encoding="utf-8") == "important stuff\n"
        assert not (ws / "MEMORY.md").exists()
        assert not (ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME).exists()

    def test_empty_reply_fails_closed(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        log = _write_log(ws, "2026-07-01")

        result = _mem.distill_memory(
            ws,
            label="demo",
            agent_id="demo",
            session_key="agent:demo:default",
            driver=_empty_output_driver,
        )

        assert result.ok is False
        assert result.failure_kind == "invalid_output"
        assert log.exists()
        assert not (ws / "MEMORY.md").exists()

    def test_corrupted_exact_record_fails_closed(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        log = _write_log(
            ws,
            "2026-07-01",
            "- [exact] MONEY-104: use `(subtotal * basis_points + 5_000) // 10_000`.\n",
        )

        def corrupting_driver(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> TurnResult:
            return TurnResult(
                True,
                "MONEY-104: use `(subtotal * basis_points + 5_000) // 1_000`.",
                0.0,
                {},
            )

        result = _mem.distill_memory(
            ws,
            label="demo",
            agent_id="demo",
            session_key="agent:demo:default",
            driver=corrupting_driver,
        )

        assert result.ok is False
        assert result.failure_kind == "invalid_output"
        assert "exact durable record" in result.error
        assert log.exists()
        assert not (ws / "MEMORY.md").exists()
        assert not (ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME).exists()


# ── distill_memory: success ──────────────────────────────────────────────────


class TestDistillMemorySuccess:
    def test_archives_logs_and_appends_summary(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        (ws / "MEMORY.md").write_text("# MEMORY.md\n\n## Existing\nkeep me\n", encoding="utf-8")
        log1 = _write_log(ws, "2026-07-01", "day one notes\n")
        log2 = _write_log(ws, "2026-07-02", "day two notes\n")
        fake = FakeDriver()

        result = _mem.distill_memory(
            ws,
            label="demo",
            agent_id="demo",
            session_key="agent:demo:default",
            driver=fake,
            day=_dt.date(2026, 7, 3),
        )

        assert result.ok is True
        assert result.skipped is False
        assert result.logs_distilled == 2
        assert result.summary  # FakeDriver's canned "done by demo"

        # Raw logs moved out of memory/*.md.
        assert not log1.exists()
        assert not log2.exists()
        assert _mem.pending_daily_logs(ws) == []
        archive_dir = ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME / "2026-07-03"
        assert sorted(p.name for p in archive_dir.iterdir()) == ["2026-07-01.md", "2026-07-02.md"]
        assert (archive_dir / "2026-07-01.md").read_text(encoding="utf-8") == "day one notes\n"
        assert set(result.archived) == {
            "memory/.distilled/2026-07-03/2026-07-01.md",
            "memory/.distilled/2026-07-03/2026-07-02.md",
        }

        # MEMORY.md gained a dated section; prior content untouched.
        mem_text = (ws / "MEMORY.md").read_text(encoding="utf-8")
        assert "## Existing" in mem_text
        assert "keep me" in mem_text
        assert "## Distilled 2026-07-03" in mem_text
        assert "done by demo" in mem_text

        # One driver call, with both logs' content inlined into the prompt.
        assert len(fake.calls) == 1
        agent_id, session_key, message, timeout, _env = fake.calls[0]
        assert agent_id == "demo"
        assert session_key == "agent:demo:default"
        assert "day one notes" in message
        assert "day two notes" in message
        assert timeout == _cfg.DISTILL_TIMEOUT_S

    def test_creates_memory_md_when_absent(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _write_log(ws, "2026-07-01", "notes\n")
        fake = FakeDriver()

        result = _mem.distill_memory(
            ws, label="demo", agent_id="demo", session_key="agent:demo:default", driver=fake
        )

        assert result.ok is True
        assert (ws / "MEMORY.md").is_file()
        assert "done by demo" in (ws / "MEMORY.md").read_text(encoding="utf-8")

    def test_custom_timeout_overrides_config_default(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _write_log(ws, "2026-07-01")
        fake = FakeDriver()

        _mem.distill_memory(
            ws,
            label="demo",
            agent_id="demo",
            session_key="agent:demo:default",
            driver=fake,
            timeout=7,
        )

        assert fake.calls[0][3] == 7

    def test_exact_records_are_preserved_verbatim(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        exact = "MONEY-104: use `(subtotal * basis_points + 5_000) // 10_000`."
        _write_log(ws, "2026-07-01", f"- [exact] {exact}\n")

        def faithful_driver(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> TurnResult:
            return TurnResult(True, f"Keep {exact}", 0.0, {})

        result = _mem.distill_memory(
            ws,
            label="demo",
            agent_id="demo",
            session_key="agent:demo:default",
            driver=faithful_driver,
        )

        assert result.ok is True
        assert f"## Exact durable records\n\n- {exact}" in result.summary
        assert f"## Exact durable records\n\n- {exact}" in (ws / "MEMORY.md").read_text()

    def test_exact_identifier_survives_summary_reformatting(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        exact = "META-202 supersedes META-201: tenant `cobalt-7`, never `amber-2`."
        _write_log(ws, "2026-07-01", f"- [exact] {exact}\n")

        def reformatted_driver(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> TurnResult:
            return TurnResult(
                True,
                "**META-202**: supersedes META-201; tenant `cobalt-7`, never `amber-2`.",
                0.0,
                {},
            )

        result = _mem.distill_memory(
            ws,
            label="demo",
            agent_id="demo",
            session_key="agent:demo:default",
            driver=reformatted_driver,
        )

        assert result.ok is True
        assert f"- {exact}" in result.summary


# ── the prompt itself is byte-budgeted ──────────────────────────────────────


class TestDistillationMessageBudget:
    def test_message_truncated_at_configured_byte_budget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "DISTILL_MAX_INPUT_BYTES", 200, raising=True)
        ws = _ws(tmp_path)
        _write_log(ws, "2026-07-01", "A" * 2000 + "\n")
        fake = FakeDriver()

        _mem.distill_memory(
            ws, label="demo", agent_id="demo", session_key="agent:demo:default", driver=fake
        )

        message = fake.calls[0][2]
        assert "A" * 2000 not in message
        assert "truncated" in message


# ── the HEARTBEAT.md dispatch ledger ──────────────────────────────────────


def _agent_ws(tmp_path: Path) -> Path:
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
        ws = _agent_ws(tmp_path)
        t = _mem.DispatchHeartbeatTask(task_id="task-1", description="do it", claimed_at="t")
        _mem.write_dispatch_tasks(ws, [t])
        path = ws / _mem.HEARTBEAT_FILE
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert _mem.DISPATCH_BLOCK_BEGIN in text
        assert "task-1" in text
        assert "## Active Tasks" in text

    def test_file_is_0600(self, tmp_path: Path) -> None:
        ws = _agent_ws(tmp_path)
        _mem.write_dispatch_tasks(ws, [])
        mode = (ws / _mem.HEARTBEAT_FILE).stat().st_mode
        assert oct(mode)[-3:] == "600"

    def test_block_inserted_right_after_active_tasks_heading(self, tmp_path: Path) -> None:
        ws = _agent_ws(tmp_path)
        t = _mem.DispatchHeartbeatTask(task_id="task-9", description="d", claimed_at="t")
        _mem.write_dispatch_tasks(ws, [t])
        text = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
        heading_idx = text.index("## Active Tasks")
        block_idx = text.index(_mem.DISPATCH_BLOCK_BEGIN)
        placeholder_idx = text.index("_none yet_")
        assert heading_idx < block_idx < placeholder_idx


class TestWriteDispatchTasksCoAuthorship:
    """The whole point of co-authorship: mechanical writes must never clobber
    an agent's own prose anywhere else in the file."""

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
        ws = _agent_ws(tmp_path)
        original = self._seeded_with_agent_prose(ws)
        t = _mem.DispatchHeartbeatTask(task_id="task-1", description="mechanical", claimed_at="t")
        _mem.write_dispatch_tasks(ws, [t])
        new_text = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")

        assert "my own hand-written task, started 2026-01-01" in new_text
        assert "a sub-step I already did" in new_text
        assert "Should we use Postgres or SQLite?" in new_text
        assert "Remember to check the staging env before merging." in new_text
        # Nothing from the original file is removed -- only the dispatch block is inserted.
        for line in original.splitlines():
            assert line in new_text
        assert "task-1" in new_text

    def test_second_write_with_different_tasks_only_touches_the_block(self, tmp_path: Path) -> None:
        ws = _agent_ws(tmp_path)
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
        ws = _agent_ws(tmp_path)
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
        ws = _agent_ws(tmp_path)
        tasks = [_mem.DispatchHeartbeatTask(task_id="task-1", description="a", claimed_at="t")]
        _mem.write_dispatch_tasks(ws, tasks)
        first = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
        _mem.write_dispatch_tasks(ws, tasks)
        second = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
        assert first == second

    def test_no_active_tasks_heading_appends_a_new_section(self, tmp_path: Path) -> None:
        ws = _agent_ws(tmp_path)
        (ws / _mem.HEARTBEAT_FILE).write_text("# Custom heartbeat\nNo standard headings here.\n")
        t = _mem.DispatchHeartbeatTask(task_id="task-1", description="a", claimed_at="t")
        _mem.write_dispatch_tasks(ws, [t])
        text = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
        assert "No standard headings here." in text
        assert "## Active Tasks" in text
        assert "task-1" in text


class TestReadDispatchTaskIds:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _mem.read_dispatch_task_ids(_agent_ws(tmp_path)) == []

    def test_no_block_yet_returns_empty(self, tmp_path: Path) -> None:
        ws = _agent_ws(tmp_path)
        (ws / _mem.HEARTBEAT_FILE).write_text(_mem.heartbeat_seed("demo-lead"))
        assert _mem.read_dispatch_task_ids(ws) == []

    def test_round_trips_written_ids(self, tmp_path: Path) -> None:
        ws = _agent_ws(tmp_path)
        tasks = [
            _mem.DispatchHeartbeatTask(task_id="task-a", description="x", claimed_at="t"),
            _mem.DispatchHeartbeatTask(task_id="task-b", description="y", claimed_at="t"),
        ]
        _mem.write_dispatch_tasks(ws, tasks)
        assert sorted(_mem.read_dispatch_task_ids(ws)) == ["task-a", "task-b"]

    def test_cleared_block_returns_empty(self, tmp_path: Path) -> None:
        ws = _agent_ws(tmp_path)
        _mem.write_dispatch_tasks(
            ws, [_mem.DispatchHeartbeatTask(task_id="task-a", description="x", claimed_at="t")]
        )
        _mem.write_dispatch_tasks(ws, [])
        assert _mem.read_dispatch_task_ids(ws) == []


class TestSyncDispatchTasks:
    def test_filters_to_running_only(self, tmp_path: Path) -> None:
        ws = _agent_ws(tmp_path)
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
        ws = _agent_ws(tmp_path)
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
        ws = _agent_ws(tmp_path)
        _mem.sync_dispatch_tasks(
            ws, [{"id": "task-1", "status": "running", "description": "a", "claimedAt": "t"}]
        )
        assert _mem.read_dispatch_task_ids(ws) == ["task-1"]
        _mem.sync_dispatch_tasks(
            ws, [{"id": "task-1", "status": "done", "description": "a", "claimedAt": "t"}]
        )
        assert _mem.read_dispatch_task_ids(ws) == []

    def test_ignores_malformed_records(self, tmp_path: Path) -> None:
        ws = _agent_ws(tmp_path)
        records = ["not a dict", {"status": "running"}, {"id": "", "status": "running"}]
        _mem.sync_dispatch_tasks(ws, records)  # type: ignore[arg-type]
        assert _mem.read_dispatch_task_ids(ws) == []


# ── WORKFLOW_AUTO.md's manual-path header ───────────────────────────────────


class TestWorkflowAutoManualPathHeader:
    """Both flavors must name their `cd`/write-HEARTBEAT instructions as the
    manual-path contract, right after the file's own intro -- Docket's live turn
    loop never sends this raw file, projecting a read-only summary instead."""

    def test_codebase_flavor_names_the_manual_path(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _mem.seed_contract(ws, project="demo", codebase="/src/demo", stack="Python")
        text = (ws / _mem.REQUIRED_STARTUP_FILE).read_text(encoding="utf-8")
        assert "Manual-path contract" in text
        assert text.index("Manual-path contract") < text.index("## Your codebase")

    def test_workdir_flavor_names_the_manual_path(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _mem.seed_contract(ws, project="demo", work_dir="/tmp/demo")
        text = (ws / _mem.REQUIRED_STARTUP_FILE).read_text(encoding="utf-8")
        assert "Manual-path contract" in text
        assert text.index("Manual-path contract") < text.index("## Your working directory")
