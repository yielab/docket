"""Conversation registry (Option B) — docket's durable index of channel threads.

Guards core/conversations.py: pure registry ops + the load/save round-trip, plus
the CLI resolver helpers. OpenClaw keeps no durable transcript, so this registry is
docket's source of truth for what conversations exist and their resume state.
"""

from __future__ import annotations

from pathlib import Path

from docket.cli import _conversations as cli
from docket.core import conversations as C


def _reg(*convs: C.Conversation) -> C.ConversationRegistry:
    return C.ConversationRegistry(conversations=list(convs))


class TestPureOps:
    def test_make_id_is_stable(self) -> None:
        assert C.make_id("docket-lead", "-5344500015") == "telegram:docket-lead:-5344500015"

    def test_upsert_appends_then_replaces(self) -> None:
        r = C.upsert(_reg(), C.Conversation(id="a", agent_id="x"))
        assert len(r.conversations) == 1
        r = C.upsert(r, C.Conversation(id="a", agent_id="x", topic="new"))
        assert len(r.conversations) == 1 and r.conversations[0].topic == "new"

    def test_by_agent_and_get(self) -> None:
        r = _reg(C.Conversation(id="a", agent_id="x"), C.Conversation(id="b", agent_id="y"))
        assert C.get(r, "a") is not None
        assert C.get(r, "missing") is None
        assert [c.id for c in C.by_agent(r, "x")] == ["a"]

    def test_ordered_most_recent_first(self) -> None:
        r = _reg(
            C.Conversation(id="a", updated="2026-07-01"),
            C.Conversation(id="b", updated="2026-07-19"),
        )
        assert [c.id for c in C.ordered(r)] == ["b", "a"]

    def test_record_creates_then_updates_preserving_created(self) -> None:
        conv, r = C.record(_reg(), agent_id="docket-lead", peer_id="-5", now="2026-07-19T00:00:00")
        assert conv.status is C.ConversationStatus.active
        assert conv.created == "2026-07-19T00:00:00"
        # Update later: created stays, updated bumps, unset fields preserved.
        conv2, r = C.record(
            r, agent_id="docket-lead", peer_id="-5", now="2026-07-20T00:00:00", topic="audit"
        )
        assert conv2.created == "2026-07-19T00:00:00"
        assert conv2.updated == "2026-07-20T00:00:00"
        assert conv2.topic == "audit"
        assert len(r.conversations) == 1

    def test_resume_transitions_status(self) -> None:
        _, r = C.record(_reg(), agent_id="a", peer_id="-1", now="t0")
        cid = C.make_id("a", "-1")
        resumed, r = C.resume(r, cid, "t1")
        assert resumed is not None and resumed.status is C.ConversationStatus.in_progress
        assert resumed.updated == "t1"

    def test_resume_unknown_is_noop(self) -> None:
        conv, r = C.resume(_reg(), "nope", "t1")
        assert conv is None and r.conversations == []

    def test_remove_agent(self) -> None:
        r = _reg(C.Conversation(id="a", agent_id="x"), C.Conversation(id="b", agent_id="y"))
        r = C.remove_agent(r, "x")
        assert [c.id for c in r.conversations] == ["b"]


class TestLoadSave:
    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert C.load(tmp_path / "none.json").conversations == []

    def test_round_trip(self, tmp_path: Path) -> None:
        p = tmp_path / "conversations.json"
        _, r = C.record(_reg(), agent_id="docket-lead", peer_id="-5", now="t0", topic="audit")
        C.save(r, p)
        loaded = C.load(p)
        assert len(loaded.conversations) == 1
        c = loaded.conversations[0]
        assert c.agent_id == "docket-lead" and c.topic == "audit"

    def test_corrupt_file_degrades_to_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert C.load(p).conversations == []

    def test_saved_json_uses_aliases(self, tmp_path: Path) -> None:
        p = tmp_path / "c.json"
        _, r = C.record(_reg(), agent_id="a", peer_id="-1", now="t0", task_ref="HEARTBEAT#1")
        C.save(r, p)
        text = p.read_text()
        assert "agentId" in text and "taskRef" in text  # camelCase aliases on disk


class TestCliHelpers:
    def test_flag_space_and_equals(self) -> None:
        assert cli._flag(["--topic", "audit"], "--topic") == "audit"
        assert cli._flag(["--topic=audit"], "--topic") == "audit"
        assert cli._flag(["--other", "x"], "--topic") is None

    def test_find_by_id_or_agent(self) -> None:
        r = _reg(
            C.Conversation(id="telegram:a:-1", agent_id="a", updated="t2"),
            C.Conversation(id="telegram:a:-2", agent_id="a", updated="t9"),
        )
        assert cli._find(r, "telegram:a:-1").id == "telegram:a:-1"  # exact id
        assert cli._find(r, "a").id == "telegram:a:-2"  # bare agent → most recent
        assert cli._find(r, "missing") is None
