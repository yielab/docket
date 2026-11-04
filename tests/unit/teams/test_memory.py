"""`teams/memory.py`: an entry's identity and its stored shape."""

from __future__ import annotations

from docket.teams import memory as pm

SUBJECT = "docket.teams.memory"


class TestEntry:
    def test_the_id_is_stable_for_one_kind_and_subject(self) -> None:
        assert pm.entry_id("generated", "dist/a.js") == pm.entry_id("generated", "dist/a.js")
        assert pm.entry_id("generated", "dist/a.js") != pm.entry_id("pitfall", "dist/a.js")

    def test_a_command_is_stored_under_command_and_a_path_under_path(self) -> None:
        def entry(kind: str, subject: str) -> pm.MemoryEntry:
            return pm.MemoryEntry("mem-x", kind, subject, "n", "pending", "", {})

        assert entry("command", "pytest -q").to_dict()["command"] == "pytest -q"
        assert entry("generated", "dist/a.js").to_dict()["path"] == "dist/a.js"
