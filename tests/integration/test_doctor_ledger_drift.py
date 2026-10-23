"""``docket setup --fix``'s TASK_LIST.json <-> HEARTBEAT.md dispatch-ledger
divergence check (``interfaces/cli/commands/setup_check.py``'s ``_check_dispatch_ledger``).

Dispatch itself keeps the two in sync mechanically (see
``test_dispatch_heartbeat_and_conversation_sync.py``); this file proves the *doctor* side: it
detects a workspace whose ledger has drifted from TASK_LIST.json — in either
direction — and ``--fix`` safely re-syncs it without touching an agent's own
prose in the same file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.pods import lead_ws as _lead_ws
from tests.support.pods import seed_pod as _seed_pod

from docket.agent import memory as _mem
from docket.interfaces.cli.commands import setup_check as _setup_check
from docket.interfaces.cli.commands import setup_check_budget as _setup_check_budget
from docket.kernel.home import Home, use_home
from docket.tasks.application import queue as _queue

SUBJECT = "docket.interfaces.cli.app"

# ── hermetic pod fixture (mirrors test_dispatch.py's _seed_pod) ─────────────────


def _claim_a_task(project: str = "demo") -> str:
    """Enqueue + claim a task via the real dispatch state machine (so
    TASK_LIST.json ends up in a genuine 'running' state, ledger written by
    dispatch itself); returns the task id."""
    _queue.enqueue_task_once(project, "some work", channel="cli")
    claim = _queue._claim_next_task(project, resume=False)
    assert claim is not None
    return str(claim[0]["id"])


class TestNoPods:
    def test_no_dispatchable_pods_is_a_silent_no_op(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        (home / "fleet.json").write_text(json.dumps({"agents": []}))
        with use_home(Home(home)):
            assert _setup_check_budget._check_dispatch_ledger(do_fix=False) == 0
            assert "Dispatch task ledger" not in capsys.readouterr().out


class TestInSync:
    def test_in_sync_reports_zero_issues(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed_pod(tmp_path):
            _claim_a_task()
            assert _setup_check_budget._check_dispatch_ledger(do_fix=False) == 0
            out = capsys.readouterr().out
            assert "demo: in sync (1 running)" in out

    def test_no_tasks_at_all_is_in_sync(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed_pod(tmp_path):
            assert _setup_check_budget._check_dispatch_ledger(do_fix=False) == 0
            assert "demo: in sync (0 running)" in capsys.readouterr().out


class TestMissingFromLedger:
    """TASK_LIST.json says a task is running; HEARTBEAT.md's ledger doesn't
    show it (an older docket version, a hand-edited HEARTBEAT.md, ...)."""

    def _corrupt(self, project: str = "demo") -> None:
        # Simulate drift: wipe dispatch's own ledger while the task is still
        # running in TASK_LIST.json.
        _mem.write_dispatch_tasks(_lead_ws(project), [])

    def test_detected_without_fix(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with _seed_pod(tmp_path):
            task_id = _claim_a_task()
            self._corrupt()
            issues = _setup_check_budget._check_dispatch_ledger(do_fix=False)
            out = capsys.readouterr().out
            assert issues == 1
            assert f"missing from ledger: {task_id}" in out
            assert "Fix with: docket setup --fix" in out

    def test_fix_resyncs_and_clears_the_issue(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed_pod(tmp_path):
            task_id = _claim_a_task()
            self._corrupt()
            issues = _setup_check_budget._check_dispatch_ledger(do_fix=True)
            assert issues == 0
            assert "ledger re-synced" in capsys.readouterr().out
            assert _mem.read_dispatch_task_ids(_lead_ws()) == [task_id]


class TestStaleInLedger:
    """HEARTBEAT.md's ledger names a task that TASK_LIST.json no longer shows
    as running (finished since, or never existed) -- the reverse divergence."""

    def test_detected_without_fix(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with _seed_pod(tmp_path):
            # No real running task -- inject a stale ledger entry directly.
            stale = _mem.DispatchHeartbeatTask(
                task_id="task-ghost", description="long finished", claimed_at="t"
            )
            _mem.write_dispatch_tasks(_lead_ws(), [stale])

            issues = _setup_check_budget._check_dispatch_ledger(do_fix=False)
            out = capsys.readouterr().out
            assert issues == 1
            assert "stale in ledger: task-ghost" in out

    def test_fix_clears_the_stale_entry(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed_pod(tmp_path):
            stale = _mem.DispatchHeartbeatTask(
                task_id="task-ghost", description="long finished", claimed_at="t"
            )
            _mem.write_dispatch_tasks(_lead_ws(), [stale])

            issues = _setup_check_budget._check_dispatch_ledger(do_fix=True)
            assert issues == 0
            assert _mem.read_dispatch_task_ids(_lead_ws()) == []

    def test_fix_never_touches_agent_prose_elsewhere_in_the_file(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            ws = _lead_ws()
            hb = ws / _mem.HEARTBEAT_FILE
            text = hb.read_text(encoding="utf-8")
            text = text.replace("## Notes\n_none_\n", "## Notes\n- Don't touch prod on Fridays.\n")
            hb.write_text(text, encoding="utf-8")
            stale = _mem.DispatchHeartbeatTask(
                task_id="task-ghost", description="x", claimed_at="t"
            )
            _mem.write_dispatch_tasks(ws, [stale])

            _setup_check_budget._check_dispatch_ledger(do_fix=True)

            final = hb.read_text(encoding="utf-8")
            assert "Don't touch prod on Fridays." in final
            assert "task-ghost" not in final


class TestDoctorJson:
    def test_dispatch_ledger_key_present_and_flags_divergence(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed_pod(tmp_path):
            task_id = _claim_a_task()
            _mem.write_dispatch_tasks(_lead_ws(), [])  # corrupt: drop the ledger entry

            capsys.readouterr()  # discard pod-provisioning output from setup above
            rc = _setup_check.run_check(json_out=True)
            data = json.loads(capsys.readouterr().out)
            assert rc == 1
            assert data["healthy"] is False
            ledger = data["checks"]["dispatchLedger"]
            assert ledger == [
                {
                    "project": "demo",
                    "ok": False,
                    "missingFromLedger": [task_id],
                    "staleInLedger": [],
                }
            ]

    def test_in_sync_reports_ok_true(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed_pod(tmp_path):
            _claim_a_task()

            capsys.readouterr()  # discard pod-provisioning output from setup above
            _setup_check.run_check(json_out=True)
            data = json.loads(capsys.readouterr().out)
            ledger = data["checks"]["dispatchLedger"]
            assert ledger == [
                {"project": "demo", "ok": True, "missingFromLedger": [], "staleInLedger": []}
            ]
