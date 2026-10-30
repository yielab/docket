"""Dispatch mechanically maintains the pod Lead's HEARTBEAT.md task ledger and keeps the
conversation registry current.

``core/dispatch.py``'s ``claim_next_task``/``persist_hop``/``touch_claim``/``_finalize_task``
call ``teams/agent_memory.py``'s ``sync_dispatch_tasks`` at each task-state-persistence point, so the
durable ledger is true whether or not the agent ever wrote anything there itself.
``persist_hop`` also calls ``teams/conversations.py``'s ``touch_for_hop`` so a wired channel
thread's ``last_message``/``task_ref`` reflect the dispatch actually working, not just whatever
``docket setup notify bind`` seeded once. Setup mirrors ``test_dispatch.py``'s hermetic pod fixture (injected
``FakeDriver``/plain runner callables, no real subprocess).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier

import pytest
from tests.support.fakes import FakeDriver
from tests.support.pods import build_pod
from tests.support.pods import lead_ws as _lead_ws

from docket.agent import ports as _rd
from docket.hops.application import executor as _executor_c
from docket.hops.application import steps as _steps_c
from docket.hops.application import sweep as _sweep
from docket.hops.application import usage as _usage
from docket.hops.gates import pre_hop as _pre_hop_c
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, use_home
from docket.kernel.threads import new_thread
from docket.tasks.application import queue as _queue
from docket.tasks.application import record as _record
from docket.tasks.domain import task as _task
from docket.teams import agent_memory as _mem
from docket.teams import conversations as _conv
from docket.teams import settings as _settings

SUBJECT = "docket.hops.application.sweep"

# ── hermetic environment (mirrors test_dispatch.py's _seed_pod) ─────────────────


@contextmanager
def _seed_pod(
    tmp_path: Path,
    project: str = "demo",
    roles: tuple[str, ...] = _pod.pod.DEFAULT_POD_ROLES,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod(project, roles, codebase=f"/src/{project}")
        yield home


# ── HEARTBEAT ledger lifecycle ────────────────────────────────────────────────


class TestHeartbeatLedgerLifecycle:
    def test_entry_written_before_first_hop_and_cleared_after_success(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "Track me", channel="cli")[0]
            ws = _lead_ws()
            seen_mid_flight: list[list[str]] = []

            def runner(
                agent_id: str, session_id: str, message: str, timeout: int, env: dict | None = None
            ) -> _rd.TurnResult:
                seen_mid_flight.append(_mem.read_dispatch_task_ids(ws))
                return _rd.TurnResult(True, f"done by {agent_id}", 0.0, {})

            _sweep.dispatch_pod("demo", runner=runner)

            assert seen_mid_flight[0] == [task.id]  # present before the very first hop
            assert _mem.read_dispatch_task_ids(ws) == []  # cleared once the task finished

    def test_entry_cleared_after_failure_too(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, roles=_pod.pod.FULL_POD_ROLES):
            _queue.enqueue_task_once("demo", "Will fail", channel="cli")
            ws = _lead_ws()
            res = _sweep.dispatch_pod("demo", runner=FakeDriver(fail_role="implementer"))[0]
            assert res.status == "failed"
            assert _mem.read_dispatch_task_ids(ws) == []

    def test_entry_cleared_when_budget_blocks_before_first_hop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "Too expensive", channel="cli")
            monkeypatch.setattr(_settings, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_steps_c, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_executor_c, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_usage, "pod_recorded_cost", lambda _p: 5.0)
            monkeypatch.setattr(_pre_hop_c, "pod_recorded_cost", lambda _p: 5.0)
            ws = _lead_ws()
            res = _sweep.dispatch_pod("demo", runner=FakeDriver())[0]
            assert res.status == "blocked"
            # No hop ever ran (claimed -> immediately finalized as blocked), so the
            # ledger should show nothing in flight.
            assert _mem.read_dispatch_task_ids(ws) == []

    def test_hop_count_increments_between_hops(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, roles=_pod.pod.FULL_POD_ROLES):
            _queue.enqueue_task_once("demo", "multi hop task", channel="cli")
            ws = _lead_ws()
            seen: list[str] = []

            def runner(
                agent_id: str, session_id: str, message: str, timeout: int, env: dict | None = None
            ) -> _rd.TurnResult:
                seen.append((ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8"))
                role = agent_id.rsplit("-", 1)[-1]
                if role == "reviewer":
                    return _rd.TurnResult(True, "APPROVE looks good", 0.0, {})
                return _rd.TurnResult(True, f"done by {agent_id}", 0.0, {})

            res = _sweep.dispatch_pod("demo", runner=runner)[0]
            assert res.status == "done"
            assert len(seen) == 3
            assert "0 hops run" in seen[0]  # before lead's hop, nothing persisted yet
            assert "1 hop run" in seen[1]  # lead's hop persisted before implementer runs
            assert "2 hops run" in seen[2]
            assert _mem.read_dispatch_task_ids(ws) == []

    def test_touch_claim_keeps_the_entry_and_refreshes_it(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "retry me", channel="cli")
            claim = _queue.claim_next_task("demo", resume=False)
            assert claim is not None
            task_id = claim.record.id
            ws = _lead_ws()
            before = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
            assert task_id in before

            _queue.touch_claim("demo", task_id)
            after = (ws / _mem.HEARTBEAT_FILE).read_text(encoding="utf-8")
            assert task_id in after

    def test_touch_claim_on_non_running_task_is_a_no_op_for_the_ledger(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "never claimed", channel="cli")
            ws = _lead_ws()
            # Task is still 'pending' -- never claimed -- so touching an unrelated
            # id must not put anything in the ledger.
            _queue.touch_claim("demo", "task-does-not-exist")
            assert _mem.read_dispatch_task_ids(ws) == []

    def test_two_concurrently_running_tasks_both_appear(self, tmp_path: Path) -> None:
        """Two different tasks can be claimed (by separate dispatch
        calls) at once; the ledger must show both, not just the most recently
        claimed one."""
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "first", channel="cli")
            _queue.enqueue_task_once("demo", "second", channel="cli")
            claim1 = _queue.claim_next_task("demo", resume=False)
            claim2 = _queue.claim_next_task("demo", resume=False)
            assert claim1 is not None and claim2 is not None
            ids = {claim1.record.id, claim2.record.id}
            ws = _lead_ws()
            assert set(_mem.read_dispatch_task_ids(ws)) == ids

    def test_co_authored_heartbeat_survives_dispatch(self, tmp_path: Path) -> None:
        """An agent's own prose elsewhere in HEARTBEAT.md must never be
        clobbered by dispatch's mechanical writes."""
        with _seed_pod(tmp_path):
            ws = _lead_ws()
            hb = ws / _mem.HEARTBEAT_FILE
            text = hb.read_text(encoding="utf-8")
            text = text.replace(
                "## Notes\n_none_\n", "## Notes\n- The human asked us to prioritize billing work.\n"
            )
            hb.write_text(text, encoding="utf-8")

            _queue.enqueue_task_once("demo", "Ship it", channel="cli")
            _sweep.dispatch_pod("demo", runner=FakeDriver())

            final = hb.read_text(encoding="utf-8")
            assert "The human asked us to prioritize billing work." in final


# ── conversation registry auto-population ─────────────────────────────────────


class TestConversationAutoPopulation:
    def _seed_conversation(self, agent_id: str, peer_id: str = "-100") -> None:
        _conv.record_durable(agent_id=agent_id, peer_id=peer_id, now="2026-01-01T00:00:00")

    def test_hop_updates_last_message_and_task_ref(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            self._seed_conversation("demo-lead")
            task = _queue.enqueue_task_once("demo", "Update my conversation", channel="cli")[0]

            _sweep.dispatch_pod("demo", runner=FakeDriver())

            reg = _conv.load()
            conv = _conv.get(reg, _conv.make_id("demo-lead", "-100"))
            assert conv is not None
            assert conv.task_ref == task.id
            assert "done by demo-lead" in conv.last_message
            assert conv.updated != "2026-01-01T00:00:00"

    def test_conversation_for_a_different_member_reflects_its_own_hop(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            self._seed_conversation("demo-lead")
            self._seed_conversation("demo-implementer", peer_id="-200")
            task = _queue.enqueue_task_once("demo", "two wired members", channel="cli")[0]

            _sweep.dispatch_pod("demo", runner=FakeDriver())

            reg = _conv.load()
            lead_conv = _conv.get(reg, _conv.make_id("demo-lead", "-100"))
            impl_conv = _conv.get(reg, _conv.make_id("demo-implementer", "-200"))
            assert lead_conv is not None and impl_conv is not None
            assert lead_conv.task_ref == task.id
            assert impl_conv.task_ref == task.id
            assert "done by demo-lead" in lead_conv.last_message
            assert "done by demo-implementer" in impl_conv.last_message

    def test_concurrent_hop_touches_keep_both_wired_agents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two stale registry snapshots must not let one hop erase the other."""
        with _seed_pod(tmp_path):
            self._seed_conversation("demo-lead")
            self._seed_conversation("demo-implementer", peer_id="-200")
            task = _queue.enqueue_task_once(
                "demo", "concurrent conversation updates", channel="cli"
            )[0]

            original_load = _conv.load
            both_stale = Barrier(2)

            def synchronized_load() -> _conv.ConversationRegistry:
                reg = original_load()
                both_stale.wait(timeout=3)
                return reg

            monkeypatch.setattr(_conv, "load", synchronized_load)
            hops = (
                _task.HopResult(role="lead", member_id="demo-lead", ok=True, output="lead preview"),
                _task.HopResult(
                    role="implementer", member_id="demo-implementer", ok=True, output="impl preview"
                ),
            )
            threads = [
                new_thread(target=_record.persist_hop, args=("demo", task.id, hop)) for hop in hops
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
                assert not thread.is_alive()

            reg = original_load()
            lead = _conv.get(reg, _conv.make_id("demo-lead", "-100"))
            implementer = _conv.get(reg, _conv.make_id("demo-implementer", "-200"))
            assert lead is not None and implementer is not None
            assert lead.last_message == "lead preview"
            assert implementer.last_message == "impl preview"

    def test_unwired_member_never_gets_a_fabricated_conversation(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            # No conversation seeded for anyone.
            _queue.enqueue_task_once("demo", "nobody is watching", channel="cli")
            _sweep.dispatch_pod("demo", runner=FakeDriver())
            reg = _conv.load()
            assert reg.conversations == []

    def test_only_the_wired_agent_is_touched_not_every_pod_member(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            self._seed_conversation("demo-lead")
            _queue.enqueue_task_once("demo", "only lead is wired", channel="cli")
            _sweep.dispatch_pod("demo", runner=FakeDriver())
            reg = _conv.load()
            assert [c.agent_id for c in reg.conversations] == ["demo-lead"]

    def test_topic_and_status_are_left_alone(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _conv.record_durable(
                agent_id="demo-lead",
                peer_id="-100",
                now="2026-01-01T00:00:00",
                topic="release planning",
                status=_conv.ConversationStatus.waiting,
            )

            _queue.enqueue_task_once("demo", "keep my topic", channel="cli")
            _sweep.dispatch_pod("demo", runner=FakeDriver())

            reg2 = _conv.load()
            conv = _conv.get(reg2, _conv.make_id("demo-lead", "-100"))
            assert conv is not None
            assert conv.topic == "release planning"
            # Auto-population only ever touches last_message/task_ref, never status.
            assert conv.status == _conv.ConversationStatus.waiting
