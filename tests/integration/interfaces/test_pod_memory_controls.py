"""The operator's controls over a pod's memory: the inbox, `docket pod memory ...` and the prompt."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.pods import build_pod
from typer.testing import CliRunner

from docket.governance import audit as _audit
from docket.interfaces.cli.app import app as _app
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, current_home, use_home
from docket.platform import store as _store
from docket.teams import identity as _identity
from docket.teams import memory as _pm

SUBJECT = "docket.interfaces.cli.commands.pod"

_MEMBER = "demo-implementer"
_PITFALL = _pm.entry_id("pitfall", "dist/bundle.js")
_runner = CliRunner()


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_HINTS", "1")


@pytest.fixture
def root(tmp_path: Path) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        repo = tmp_path / "origin"
        (repo / "dist").mkdir(parents=True)
        (repo / "dist" / "bundle.js").write_text("x\n")
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(repo))
        yield repo


def _entry(kind: str, subject: str, status: str, note: str = "A fact.") -> dict[str, Any]:
    return {
        "id": _pm.entry_id(kind, subject),
        "kind": kind,
        "command" if kind == "command" else "path": subject,
        "note": note,
        "status": status,
        "reason": "awaits operator approval" if status == "pending" else "ok",
        "provenance": {"task": "t1", "date": "2026-10-18", "commit": ""},
    }


def _seed(*entries: dict[str, Any]) -> None:
    path = current_home().pod_memory_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(path, {"entries": list(entries)})


def _pitfall() -> dict[str, Any]:
    return _entry("pitfall", "dist/bundle.js", "pending", "Rebuilt on every install.")


def _run(*args: str) -> Any:
    return _runner.invoke(_app, list(args))


def _prompt(repo: Path) -> str:
    return _identity.compose_agent_prompt(_MEMBER, project_roots=(repo,)).text


def _statuses() -> dict[str, str]:
    return {e.id: e.status for e in _pm.list_entries("demo")}


class TestInbox:
    def test_a_pending_pitfall_is_listed_with_its_approve_and_refuse_commands(
        self, root: Path
    ) -> None:
        _seed(_pitfall(), _entry("generated", "dist/bundle.js", "accepted"))

        result = _run("inbox", "--peek")

        assert result.exit_code == 0, result.output
        assert f"memory {_PITFALL}  pod=demo  pitfall" in result.output
        assert "dist/bundle.js" in result.output and "Rebuilt on every install." in result.output
        assert f"docket pod memory approve {_PITFALL} --pod demo" in result.output
        assert f"docket pod memory refuse {_PITFALL} --pod demo --reason" in result.output
        assert result.output.count("memory mem-") == 1

    def test_json_carries_the_item_in_needs_you_with_state_and_command(self, root: Path) -> None:
        _seed(_pitfall())

        result = _run("inbox", "--peek", "--json")

        body = json.loads(result.output)
        assert [i for i in body["needsYou"] if i["kind"] == "memory"] == [
            {
                "kind": "memory",
                "pod": "demo",
                "id": _PITFALL,
                "entryKind": "pitfall",
                "subject": "dist/bundle.js",
                "note": "Rebuilt on every install.",
                "reason": "awaits operator approval",
                "task": "t1",
                "state": "needs_memory_approval",
                "command": f"docket pod memory approve {_PITFALL} --pod demo",
            }
        ]

    def test_an_approved_entry_leaves_the_inbox(self, root: Path) -> None:
        _seed(_pitfall())

        assert _run("pod", "memory", "approve", _PITFALL, "--pod", "demo").exit_code == 0

        assert "memory mem-" not in _run("inbox", "--peek").output

    def test_nothing_pending_is_nothing_needing_you(self, root: Path) -> None:
        _seed(_entry("generated", "dist/bundle.js", "accepted"))

        assert "Nothing needs you." in _run("inbox", "--peek").output


class TestApprove:
    def test_approve_accepts_the_entry_and_the_next_prompt_carries_it(self, root: Path) -> None:
        _seed(_pitfall())
        assert "Rebuilt on every install." not in _prompt(root)

        result = _run("pod", "memory", "approve", _PITFALL, "--pod", "demo")

        assert result.exit_code == 0, result.output
        assert _statuses() == {_PITFALL: "accepted"}
        assert "- pitfall dist/bundle.js: Rebuilt on every install." in _prompt(root)
        assert any(
            e["action"] == "pod.memory.approved"
            and _PITFALL in e["detail"]
            and "actor=cli" in e["detail"]
            for e in _audit.read_audit()
        )

    def test_the_pod_comes_from_the_working_directory(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(_pitfall())
        monkeypatch.chdir(root)

        assert _run("pod", "memory", "approve", _PITFALL).exit_code == 0

        assert _statuses() == {_PITFALL: "accepted"}

    def test_refuse_records_the_reason_and_keeps_it_out_of_the_prompt(self, root: Path) -> None:
        _seed(_pitfall())

        result = _run("pod", "memory", "refuse", _PITFALL, "--reason", "not true", "--pod", "demo")

        assert result.exit_code == 0, result.output
        [entry] = _pm.list_entries("demo")
        assert (entry.status, entry.reason) == ("refused", "not true")
        assert "Rebuilt on every install." not in _prompt(root)

    def test_refuse_without_a_reason_is_a_usage_error(self, root: Path) -> None:
        _seed(_pitfall())

        assert _run("pod", "memory", "refuse", _PITFALL, "--pod", "demo").exit_code == 2
        assert _statuses() == {_PITFALL: "pending"}


class TestRevert:
    def test_revert_removes_it_from_the_prompt_and_audits(self, root: Path) -> None:
        _seed(_entry("pitfall", "dist/bundle.js", "accepted", "Rebuilt on every install."))
        assert "Rebuilt on every install." in _prompt(root)

        result = _run("pod", "memory", "revert", _PITFALL, "--pod", "demo")

        assert result.exit_code == 0, result.output
        assert _statuses() == {_PITFALL: "refused"}
        assert "Rebuilt on every install." not in _prompt(root)
        assert any(
            e["action"] == "pod.memory.reverted" and _PITFALL in e["detail"]
            for e in _audit.read_audit()
        )

    def test_reverting_a_pending_entry_is_refused_and_changes_nothing(self, root: Path) -> None:
        _seed(_pitfall())

        result = _run("pod", "memory", "revert", _PITFALL, "--pod", "demo")

        assert result.exit_code == 1
        assert "pending" in result.output
        assert _statuses() == {_PITFALL: "pending"}


class TestReset:
    def test_it_asks_first_and_an_answer_of_no_keeps_every_entry(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(_pitfall(), _entry("generated", "dist/bundle.js", "accepted"))
        monkeypatch.setattr("docket.interfaces.cli.commands.contract.is_tty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")

        result = _run("pod", "memory", "reset", "--pod", "demo")

        assert result.exit_code == 1
        assert len(_pm.list_entries("demo")) == 2

    def test_off_a_terminal_it_needs_yes(self, root: Path) -> None:
        _seed(_pitfall())

        result = _run("pod", "memory", "reset", "--pod", "demo")

        assert result.exit_code == 1
        assert "--yes" in result.output
        assert len(_pm.list_entries("demo")) == 1

    def test_yes_empties_the_pods_memory_and_audits(self, root: Path) -> None:
        _seed(_pitfall(), _entry("generated", "dist/bundle.js", "accepted"))

        result = _run("pod", "memory", "reset", "--yes", "--pod", "demo")

        assert result.exit_code == 0, result.output
        assert _pm.list_entries("demo") == []
        assert "Built output" not in _prompt(root)
        assert any(
            e["action"] == "pod.memory.reset" and "entries=2" in e["detail"]
            for e in _audit.read_audit()
        )


class TestListAndErrors:
    def test_list_prints_every_entry_and_filters_by_status(self, root: Path) -> None:
        _seed(_pitfall(), _entry("generated", "dist/bundle.js", "accepted"))

        everything = _run("pod", "memory", "list", "--pod", "demo")
        pending = _run("pod", "memory", "list", "--status", "pending", "--pod", "demo")

        assert everything.exit_code == 0, everything.output
        assert "pending" in everything.output and "accepted" in everything.output
        assert "pitfall" in pending.output and "accepted" not in pending.output

    def test_list_json_is_the_stored_entries(self, root: Path) -> None:
        _seed(_pitfall())

        result = _run("pod", "memory", "list", "--json", "--pod", "demo")

        [entry] = json.loads(result.output)
        assert (entry["id"], entry["kind"], entry["path"], entry["status"]) == (
            _PITFALL,
            "pitfall",
            "dist/bundle.js",
            "pending",
        )

    def test_list_with_nothing_says_so_and_json_is_an_empty_array(self, root: Path) -> None:
        assert "No memory" in _run("pod", "memory", "list", "--pod", "demo").output
        assert json.loads(_run("pod", "memory", "list", "--json", "--pod", "demo").output) == []

    def test_an_unknown_status_exits_1(self, root: Path) -> None:
        assert _run("pod", "memory", "list", "--status", "bogus", "--pod", "demo").exit_code == 1

    @pytest.mark.parametrize("verb", ["approve", "revert"])
    def test_an_unknown_id_exits_non_zero_naming_it(self, root: Path, verb: str) -> None:
        _seed(_pitfall())

        result = _run("pod", "memory", verb, "mem-nope", "--pod", "demo")

        assert result.exit_code == 1
        assert "mem-nope" in result.output
        assert _statuses() == {_PITFALL: "pending"}

    def test_an_unknown_pod_exits_1(self, root: Path) -> None:
        result = _run("pod", "memory", "list", "--pod", "ghost")

        assert result.exit_code == 1
        assert "ghost" in result.output

    def test_there_is_still_no_top_level_memory_command(self, root: Path) -> None:
        assert _run("memory", "list").exit_code == 2
