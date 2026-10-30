"""A pod's records are tools of a live turn: an add is idempotent on the key and stamped by the hop,
a model cannot set the columns docket fills, a query reads, an export writes a file in the workdir
without the rows passing through the model, and the records file is outside the hop's roots. The
oracle is the real driver, a scripted model and the SQLite file the pod owns."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.llm import RecordingScriptedBackend as _ScriptedBackend
from tests.support.llm import final as _final
from tests.support.llm import tool_calls
from tests.support.pods import write_meta_overrides as _write_meta
from tests.support.roles import write_role_overlay
from tests.support.trace import audit_entries
from tests.support.turns import run_turn, tool_replies

from docket.agent.ports import DOCKET_HOP_STEP
from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry
from docket.hops.application.builtin_tools import builtin_registry
from docket.hops.application.driver import DocketDriver
from docket.kernel.home import current_home
from docket.kernel.ports import records
from docket.kernel.records import RecordColumn, RecordSet
from docket.kernel.records_port import ReadLimits, RecordStore
from docket.kernel.tool_outcome import ToolOutcome
from docket.teams import fleet as _fleet
from docket.teams import records as _records

SUBJECT = "docket.agent.tools.records_tools"

_LEADS = RecordSet(
    name="leads",
    key="email",
    columns=[
        RecordColumn(name="email", type="string", required=True),
        RecordColumn(name="score", type="integer"),
    ],
)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    _fleet.disable_sandbox_isolation()
    work = tmp_path / "work"
    work.mkdir()
    _write_meta("impl-1", role="implementer", work_dir=str(work))
    folder = current_home().pod_config_dir("acme") / "records"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "leads.yaml").write_text(
        "kind: records\nname: leads\nkey: email\ncolumns:\n"
        "  - {name: email, type: string, required: true}\n  - {name: score, type: integer}\n"
    )
    _records.ensure_set("acme", _LEADS)
    return work


def _store() -> RecordStore:
    return records.open("acme")


def _rows() -> list[tuple[Any, ...]]:
    return (
        _store()
        .read("SELECT email, _task, _step FROM leads ORDER BY _id", ReadLimits(50, 9999))
        .rows
    )


def _turn(backend: _ScriptedBackend, task: str = "t-1", step: str = "scan") -> None:
    run_turn(backend, {DOCKET_HOP_STEP: step}, trace_project="acme", trace_task_id=task)


def _add(email: str, **more: Any) -> tuple[str, dict[str, Any]]:
    return "rec__leads__add", {"email": email, **more}


class TestAdd:
    def test_two_adds_of_one_key_leave_one_row_and_the_second_says_it_was_not_created(
        self, workdir: Path
    ) -> None:
        backend = _ScriptedBackend(
            [tool_calls(_add("a@b.test", score=3), _add("a@b.test", score=9)), _final()]
        )

        _turn(backend, task="t-7", step="scan")

        first, second = (json.loads(r) for r in tool_replies(backend))
        assert (first["created"], second["created"]) == (True, False)
        assert second["row"]["score"] == 3
        assert _rows() == [("a@b.test", "t-7", "scan")]

    def test_a_column_docket_fills_is_refused_and_nothing_is_written(self, workdir: Path) -> None:
        backend = _ScriptedBackend([tool_calls(_add("a@b.test", _task="forged")), _final()])

        _turn(backend)

        (reply,) = tool_replies(backend)
        assert "_task" in reply
        assert _rows() == []

    def test_a_missing_required_column_is_refused_naming_it(self, workdir: Path) -> None:
        backend = _ScriptedBackend([tool_calls(("rec__leads__add", {"score": 1})), _final()])

        _turn(backend)

        assert "email" in tool_replies(backend)[0]
        assert _rows() == []


class TestUpdate:
    def test_an_update_by_key_changes_the_row_and_stamps_the_hop(self, workdir: Path) -> None:
        backend = _ScriptedBackend(
            [
                tool_calls(
                    _add("a@b.test", score=1),
                    (
                        "rec__leads__update",
                        {"match": {"email": "a@b.test"}, "values": {"score": 5}},
                    ),
                ),
                _final(),
            ]
        )

        _turn(backend, task="t-2", step="rescore")

        assert json.loads(tool_replies(backend)[1])["row"]["score"] == 5
        assert _rows() == [("a@b.test", "t-2", "rescore")]


class TestQueryAndExport:
    def test_query_returns_the_rows(self, workdir: Path) -> None:
        backend = _ScriptedBackend(
            [
                tool_calls(
                    _add("a@b.test", score=3), ("rec__query", {"sql": "SELECT email FROM leads"})
                ),
                _final(),
            ]
        )

        _turn(backend)

        result = json.loads(tool_replies(backend)[1])
        assert result == {"columns": ["email"], "rows": [["a@b.test"]], "cut": 0}

    def test_a_statement_that_writes_is_refused(self, workdir: Path) -> None:
        backend = _ScriptedBackend(
            [tool_calls(_add("a@b.test"), ("rec__query", {"sql": "DELETE FROM leads"})), _final()]
        )

        _turn(backend)

        assert "refused" in tool_replies(backend)[1]
        assert len(_rows()) == 1

    def test_export_writes_the_file_and_the_rows_stay_out_of_the_reply(self, workdir: Path) -> None:
        backend = _ScriptedBackend(
            [
                tool_calls(
                    _add("secret@b.test"),
                    ("rec__export", {"sql": "SELECT email FROM leads", "path": "report.csv"}),
                ),
                _final(),
            ]
        )

        _turn(backend)

        reply = tool_replies(backend)[1]
        assert json.loads(reply)["rows"] == 1
        assert "secret@b.test" not in reply
        assert (workdir / "report.csv").read_text().splitlines() == ["email", "secret@b.test"]

    def test_export_as_markdown(self, workdir: Path) -> None:
        backend = _ScriptedBackend(
            [
                tool_calls(
                    _add("a@b.test"),
                    (
                        "rec__export",
                        {"sql": "SELECT email FROM leads", "format": "md", "path": "r.md"},
                    ),
                ),
                _final(),
            ]
        )

        _turn(backend)

        assert (workdir / "r.md").read_text().startswith("| email |")

    def test_a_path_outside_the_workdir_is_refused_and_writes_nothing(self, workdir: Path) -> None:
        backend = _ScriptedBackend(
            [
                tool_calls(
                    _add("a@b.test"),
                    ("rec__export", {"sql": "SELECT email FROM leads", "path": "../x"}),
                ),
                _final(),
            ]
        )

        _turn(backend)

        assert "outside the allowed roots" in tool_replies(backend)[1]
        assert not (workdir.parent / "x").exists()
        assert audit_entries("tool.refused")[-1]["detail"].count("path_escape") == 1


class TestWhatTheRoleSees:
    def _offered(self, backend: _ScriptedBackend) -> set[str]:
        return {spec.name for spec in backend.tools_seen[0]}

    def test_a_role_denying_write_is_offered_only_the_query(self, workdir: Path) -> None:
        write_role_overlay("acme", "implementer", ["write"])
        backend = _ScriptedBackend([_final()])

        _turn(backend)

        offered = self._offered(backend)
        assert "rec__query" in offered
        assert offered.isdisjoint({"rec__leads__add", "rec__leads__update", "rec__export"})

    def test_a_role_naming_the_set_is_offered_its_add_and_update_alone(self, workdir: Path) -> None:
        write_role_overlay("acme", "implementer", [], extra="tools: [read, rec__leads]\n")
        backend = _ScriptedBackend([_final()])

        _turn(backend)

        offered = {n for n in self._offered(backend) if n.startswith("rec__")}
        assert offered == {"rec__leads__add", "rec__leads__update"}

    def test_a_pod_with_no_set_is_offered_no_record_tool(self, workdir: Path) -> None:
        _write_meta("impl-1", role="implementer", work_dir=str(workdir))
        backend = _ScriptedBackend([_final()])

        run_turn(backend, {}, trace_project="bare", trace_task_id="t-1")

        assert not [n for n in self._offered(backend) if n.startswith("rec__")]

    def test_a_document_that_does_not_validate_is_left_out_and_audited(self, workdir: Path) -> None:
        bad = current_home().pod_config_dir("acme") / "records" / "broken.yaml"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("name: broken\ncolumns: []\n")
        backend = _ScriptedBackend([_final()])

        _turn(backend)

        (entry,) = audit_entries("records.unavailable")
        assert "broken.yaml" in entry["detail"]
        assert "rec__leads__add" in self._offered(backend)


class TestTheJail:
    def test_the_records_file_is_under_no_root_the_hop_hands_its_commands(
        self, workdir: Path
    ) -> None:
        seen: list[ToolContext] = []

        def probe(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
            seen.append(ctx)
            return ToolOutcome(True, content="ok")

        def registry() -> ToolRegistry:
            base = builtin_registry()
            base.register(Tool(name="probe", description="p", parameters={}, handler=probe))
            return base

        backend = _ScriptedBackend([tool_calls(("probe", {})), _final()])
        res = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=registry
        ).run_turn("impl-1", "agent:impl-1:default", "go", 60, {}, trace_project="acme")
        assert res.ok, res.error

        (ctx,) = seen
        granted = [*ctx.roots, *ctx.read_only, *([ctx.cache_dir] if ctx.cache_dir else [])]
        records = current_home().pod_records_path("acme").resolve()
        assert granted
        assert not [g for g in granted if g.resolve() in (records, *records.parents)]
