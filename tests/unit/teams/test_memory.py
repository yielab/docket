"""`teams/memory.py`: an entry's identity, its stored shape and the eviction order."""

from __future__ import annotations

from docket.teams import memory as pm

SUBJECT = "docket.teams.memory"


def _entry(
    kind: str = "pitfall",
    subject: str = "dist/a.js",
    status: str = "pending",
    *,
    stale: bool = False,
    evidence: dict[str, int | bool] | None = None,
    note: str = "n",
) -> pm.MemoryEntry:
    return pm.MemoryEntry(
        pm.entry_id(kind, subject, note),
        kind,
        subject,
        note,
        status,
        "",
        {},
        stale=stale,
        evidence=evidence or {},
    )


class TestEntryId:
    def test_the_id_is_stable_for_one_kind_subject_and_note(self) -> None:
        assert pm.entry_id("generated", "dist/a.js", "Built.") == pm.entry_id(
            "generated", "dist/a.js", "Built."
        )
        assert pm.entry_id("generated", "dist/a.js", "Built.") != pm.entry_id(
            "pitfall", "dist/a.js", "Built."
        )

    def test_two_notes_about_one_subject_are_two_ids(self) -> None:
        assert pm.entry_id("pitfall", ".", "Slow tests.") != pm.entry_id(
            "pitfall", ".", "Flaky tests."
        )

    def test_case_and_whitespace_do_not_make_a_new_fact(self) -> None:
        assert pm.entry_id("pitfall", ".", "Slow  tests.\n") == pm.entry_id(
            "pitfall", ".", " slow tests. "
        )


class TestShape:
    def test_every_kind_stores_its_subject_stale_and_evidence(self) -> None:
        for kind in ("tool", "generated", "pitfall", "convention"):
            doc = _entry(kind, "x", evidence={"exit": 1} if kind == "tool" else None).to_dict()

            assert doc["subject"] == "x" and doc["stale"] is False
            assert not {"path", "tool", "command", "exit"} & set(doc)
        assert _entry("tool", "pytest", evidence={"ok": True}).to_dict()["evidence"] == {"ok": True}
        assert _entry().to_dict()["evidence"] == {}

    def test_the_stored_shape_round_trips(self) -> None:
        entry = _entry("tool", "pytest -q", "accepted", stale=True, evidence={"exit": 2})

        assert pm._entry_from_dict(entry.to_dict()) == entry

    def test_the_old_keys_have_no_reader(self) -> None:
        old = {
            "id": "mem-x",
            "kind": "generated",
            "path": "dist/a.js",
            "note": "n",
            "status": "accepted",
            "reason": "",
            "provenance": {},
        }

        assert pm._entry_from_dict(old) is None
        assert pm._entry_from_dict({**old, "subject": "dist/a.js"}) is not None

    def test_evidence_that_is_neither_an_exit_nor_an_ok_is_dropped(self) -> None:
        doc = {**_entry().to_dict(), "evidence": {"exit": True, "other": 1}}

        entry = pm._entry_from_dict(doc)

        assert entry is not None and entry.evidence == {}


class TestTrim:
    def test_a_stale_entry_goes_before_the_oldest_live_accepted(self) -> None:
        entries = [_entry("generated", f"f{i}", "accepted") for i in range(41)]
        entries[20] = _entry("generated", "f20", "accepted", stale=True)

        kept = pm._trim(entries)

        assert len(kept) == 40
        assert "f20" not in [e.subject for e in kept] and kept[0].subject == "f0"

    def test_without_a_stale_entry_the_oldest_accepted_goes(self) -> None:
        entries = [_entry("generated", f"f{i}", "accepted") for i in range(41)]

        assert pm._trim(entries)[0].subject == "f1"

    def test_a_refused_entry_goes_before_an_older_pending_one(self) -> None:
        entries = [_entry("pitfall", f"p{i}", "pending") for i in range(40)]
        entries.insert(5, _entry("pitfall", "r", "refused"))

        kept = pm._trim(entries)

        assert len(kept) == 40
        assert kept[0].subject == "p0" and "r" not in [e.subject for e in kept]

    def test_pending_is_evicted_oldest_first_once_no_refusal_is_left(self) -> None:
        entries = [_entry("pitfall", f"p{i}", "pending") for i in range(41)]

        assert pm._trim(entries)[0].subject == "p1"
