"""`teams/memory.py`: storing, operator decisions and rendering entries against a real git repository."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from tests.support.git import git_identity_flags as _git
from tests.support.pod_memory import PROJECT as _PROJECT
from tests.support.pod_memory import SESSION as _SESSION
from tests.support.pod_memory import TASK as _TASK
from tests.support.pod_memory import link as _link
from tests.support.pod_memory import record as _record
from tests.support.pods import section as _section

from docket.kernel.home import current_home, use_home
from docket.observability import trace as _trace
from docket.teams import memory as pm

SUBJECT = "docket.teams.memory"


# -- the store -----------------------------------------------------------------


class TestStore:
    def test_the_file_is_private_and_shaped_as_documented(self, repo: tuple[Path, str]) -> None:
        root, commit = repo
        _record(
            root, commit, _section("- pitfall: api/schema.proto -- Needs a regenerated client.")
        )

        path = current_home().pod_memory_path(_PROJECT)
        doc = json.loads(path.read_text())

        assert path.parent == current_home().pods_dir / _PROJECT
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        (entry,) = doc["entries"]
        assert entry["path"] == "api/schema.proto" and "command" not in entry
        assert set(entry) >= {"id", "kind", "note", "status", "reason", "provenance"}

    def test_a_repeated_fact_is_stored_once(self, repo: tuple[Path, str]) -> None:
        root, commit = repo
        out = _section("- generated: dist/bundle.js -- Built output.")

        _record(root, commit, out)
        _record(root, commit, out)

        assert len(pm.list_entries(_PROJECT)) == 1

    def test_a_refused_entry_is_not_reopened_by_a_repeat(self, repo: tuple[Path, str]) -> None:
        root, commit = repo
        (entry,) = _record(root, commit, _section("- pitfall: api/schema.proto -- Needs a client."))
        pm.refuse(_PROJECT, entry.id, "not true")

        _record(root, commit, _section("- pitfall: api/schema.proto -- Needs a client."))

        (again,) = pm.list_entries(_PROJECT)
        assert again.status == "refused"

    def test_an_accepted_entry_replaces_a_pending_one_for_the_same_fact(
        self, repo: tuple[Path, str]
    ) -> None:
        root, commit = repo
        out = _section("- generated: dist/bundle.js -- Built output.")
        fetched = _link([("tool_call", {"tool": "fetch", "callId": "c", "arguments": "{}"})])
        _record(root, commit, out, trace=fetched)
        assert [e.status for e in pm.list_entries(_PROJECT)] == ["pending"]

        _record(root, commit, out, task="job-2")

        assert [e.status for e in pm.list_entries(_PROJECT)] == ["accepted"]

    def test_the_oldest_accepted_entry_goes_first_and_pending_cannot_evict_it(
        self, repo: tuple[Path, str]
    ) -> None:
        root, commit = repo
        with use_home(
            dataclasses.replace(
                current_home(), pod_memory_max_accepted=2, pod_memory_max_undecided=2
            )
        ):
            for name in ("dist/bundle.js", "api/schema.proto"):
                _record(root, commit, _section(f"- generated: {name} -- A file."))
            for i in range(5):
                _record(root, commit, _section(f"- pitfall: p{i} -- A thing."))

            by_status = {
                s: [e.subject for e in pm.list_entries(_PROJECT, s)]
                for s in ("accepted", "pending")
            }
            assert by_status["accepted"] == ["dist/bundle.js", "api/schema.proto"]
            assert by_status["pending"] == ["p3", "p4"]

            (root / "dist" / "more.js").write_text("y\n")
            _git(root, "add", ".")
            _git(root, "commit", "-q", "-m", "more")
            _record(
                root,
                _git(root, "rev-parse", "HEAD"),
                _section("- generated: dist/more.js -- A file."),
            )
            assert [e.subject for e in pm.list_entries(_PROJECT, "accepted")] == [
                "api/schema.proto",
                "dist/more.js",
            ]

    def test_every_change_leaves_a_trace_event_and_an_audit_entry(
        self, repo: tuple[Path, str]
    ) -> None:
        root, commit = repo
        _record(
            root,
            commit,
            _section(
                "- generated: dist/bundle.js -- Built output.",
                "- generated: dist/gone.js -- Removed.",
            ),
        )

        events = [
            r
            for r in _trace.read_trace(current_home().traces_dir / _PROJECT / f"{_SESSION}.jsonl")
            if r["event_type"] == "memory_update"
        ]
        audit_text = current_home().audit_log.read_text()

        assert sorted(e["payload"]["status"] for e in events) == ["accepted", "refused"]
        assert all(e["payload"]["task"] == _TASK for e in events)
        assert "Built output" not in json.dumps(events) and "dist/bundle.js" not in json.dumps(
            events
        )
        assert audit_text.count("pod.memory.") == 2
        assert "Built output" not in audit_text and "bundle.js" not in audit_text


class TestOperatorApi:
    def _pending(self, repo: tuple[Path, str]) -> pm.MemoryEntry:
        root, commit = repo
        (entry,) = _record(root, commit, _section("- convention: . -- Types on public functions."))
        return entry

    def test_approve_moves_a_pending_entry_to_accepted(self, repo: tuple[Path, str]) -> None:
        entry = self._pending(repo)

        approved = pm.approve(_PROJECT, entry.id)

        assert approved.status == "accepted"
        assert [e.status for e in pm.list_entries(_PROJECT)] == ["accepted"]

    def test_approve_refuses_what_is_not_pending(self, repo: tuple[Path, str]) -> None:
        root, commit = repo
        (entry,) = _record(root, commit, _section("- generated: dist/bundle.js -- Built output."))

        with pytest.raises(pm.PodMemoryError):
            pm.approve(_PROJECT, entry.id)
        with pytest.raises(pm.PodMemoryError):
            pm.approve(_PROJECT, "mem-nope")

    def test_revert_makes_an_accepted_entry_refused_and_it_stays_refused(
        self, repo: tuple[Path, str]
    ) -> None:
        root, commit = repo
        out = _section("- generated: dist/bundle.js -- Built output.")
        (entry,) = _record(root, commit, out)

        reverted = pm.revert(_PROJECT, entry.id)
        _record(root, commit, out)

        assert reverted.status == "refused"
        assert [e.status for e in pm.list_entries(_PROJECT)] == ["refused"]

    def test_reset_removes_every_entry_and_says_how_many(self, repo: tuple[Path, str]) -> None:
        root, commit = repo
        _record(
            root,
            commit,
            _section("- generated: dist/bundle.js -- Built.", "- convention: . -- Typed."),
        )

        assert pm.reset(_PROJECT) == 2
        assert pm.list_entries(_PROJECT) == []

    def test_each_decision_is_traced_and_audited(self, repo: tuple[Path, str]) -> None:
        entry = self._pending(repo)

        pm.approve(_PROJECT, entry.id, actor="operator")

        text = current_home().audit_log.read_text()
        assert "pod.memory.approved" in text and entry.id in text


# -- what the next task reads --------------------------------------------------


class TestRender:
    def _accept(self, repo: tuple[Path, str], *names: str) -> None:
        root, commit = repo
        _record(root, commit, _section(*[f"- generated: {n} -- A file." for n in names]))

    def test_only_accepted_entries_render_and_each_names_its_subject(
        self, repo: tuple[Path, str]
    ) -> None:
        root, commit = repo
        _record(
            root,
            commit,
            _section(
                "- generated: dist/bundle.js -- Built output.",
                "- pitfall: api/schema.proto -- Needs a client.",
            ),
        )

        text = pm.render_entries(_PROJECT, root, 4000)

        assert "dist/bundle.js" in text and "Built output." in text
        assert "schema.proto" not in text

    def test_an_entry_whose_path_is_gone_is_omitted_but_kept(self, repo: tuple[Path, str]) -> None:
        root, _commit = repo
        self._accept(repo, "dist/bundle.js", "api/schema.proto")
        (root / "dist" / "bundle.js").unlink()

        text = pm.render_entries(_PROJECT, root, 4000)

        assert "bundle.js" not in text and "schema.proto" in text
        assert len(pm.list_entries(_PROJECT, "accepted")) == 2

    def test_a_command_entry_carries_its_exit_status(self, repo: tuple[Path, str]) -> None:
        root, commit = repo
        events = [("command_step", {"step": "t", "cmd": "pytest -q", "exit": 1})]
        _record(
            root,
            commit,
            _section("- tool: pytest -q -- Runs the unit tests."),
            trace=_link(events),
        )

        assert "pytest -q" in pm.render_entries(_PROJECT, root, 4000)
        assert "exit 1" in pm.render_entries(_PROJECT, root, 4000)

    def test_the_byte_cap_drops_the_oldest_whole_entries(self, repo: tuple[Path, str]) -> None:
        root, _commit = repo
        self._accept(repo, "dist/bundle.js", "api/schema.proto")

        one = pm.render_entries(_PROJECT, root, 40)

        assert "schema.proto" in one and "bundle.js" not in one
        assert pm.render_entries(_PROJECT, root, 10) == ""

    def test_nothing_accepted_renders_nothing(self, repo: tuple[Path, str]) -> None:
        root, _commit = repo

        assert pm.render_entries(_PROJECT, root, 4000) == ""

    def test_a_hand_edited_unsafe_path_is_not_probed_or_rendered(
        self, repo: tuple[Path, str]
    ) -> None:
        root, _commit = repo
        path = current_home().pod_memory_path(_PROJECT)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "id": "mem-x",
                            "kind": "generated",
                            "path": "../../etc/passwd",
                            "note": "n",
                            "status": "accepted",
                            "reason": "",
                            "provenance": {},
                        }
                    ]
                }
            )
        )

        assert pm.render_entries(_PROJECT, root, 4000) == ""
