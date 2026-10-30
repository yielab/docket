"""A pod's record tools: their names, kinds and schemas, and what each handler passes the store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docket.agent.tools import records_tools as _rt
from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry
from docket.kernel.records import RecordColumn, RecordSet
from docket.platform import RecordsError
from docket.platform.records_store import AddResult, QueryResult, RecordMeta

SUBJECT = "docket.agent.tools.records_tools"

_LEADS = RecordSet(
    name="leads",
    key="email",
    description="people we may call",
    columns=[
        RecordColumn(name="email", type="string"),
        RecordColumn(name="score", type="integer", required=True),
        RecordColumn(name="seen", type="date"),
        RecordColumn(name="hot", type="boolean"),
        RecordColumn(name="ratio", type="number"),
    ],
)
_NOTES = RecordSet(name="notes", columns=[RecordColumn(name="body", type="string")])


class _Store:
    """Records what the handlers ask of the store and answers with fixed values."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.error: RecordsError | None = None

    def _note(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if self.error is not None:
            raise self.error

    def add(self, set_name: str, values: dict[str, Any], meta: RecordMeta) -> AddResult:
        self._note("add", set_name, values, meta)
        return AddResult({"_id": 1, **values}, created=True)

    def update(
        self, set_name: str, match: dict[str, Any], values: dict[str, Any], meta: RecordMeta
    ) -> dict[str, Any]:
        self._note("update", set_name, match, values, meta)
        return {"_id": 1, **values}

    def query(self, sql: str, max_rows: int, max_chars: int, timeout_s: float = 5.0) -> QueryResult:
        self._note("query", sql, max_rows, max_chars)
        return QueryResult(("n",), [(1,)], 0)

    def export(self, sql: str, path: Path, fmt: str, timeout_s: float = 30.0) -> int:
        self._note("export", sql, path, fmt)
        return 4


def _load(store: _Store | None = None) -> tuple[ToolRegistry, _Store]:
    held = store or _Store()
    registry = ToolRegistry()
    _rt.load_records_tools(registry, store=held, sets=[_LEADS, _NOTES])  # type: ignore[arg-type]
    return registry, held


def _tool(registry: ToolRegistry, name: str) -> Tool:
    tool = registry.get(name)
    assert tool is not None
    return tool


def _ctx(tmp_path: Path, **more: Any) -> ToolContext:
    return ToolContext(
        roots=(tmp_path,), task_id="t-1", session_key="agent:x:y", step_id="scan", **more
    )


class TestNamesKindsAndSchemas:
    def test_one_add_and_update_per_set_and_one_query_and_export_per_pod(self) -> None:
        registry, _ = _load()

        assert sorted(registry.names()) == [
            "rec__export",
            "rec__leads__add",
            "rec__leads__update",
            "rec__notes__add",
            "rec__notes__update",
            "rec__query",
        ]

    def test_reads_are_read_and_everything_that_writes_is_write(self) -> None:
        registry, _ = _load()

        kinds = {name: _tool(registry, name).kind for name in registry.names()}

        assert kinds["rec__query"] == "read"
        assert {k for n, k in kinds.items() if n != "rec__query"} == {"write"}

    def test_add_takes_the_columns_and_requires_the_key_and_required_columns(self) -> None:
        registry, _ = _load()

        schema = _tool(registry, "rec__leads__add").parameters

        assert schema["properties"] == {
            "email": {"type": "string"},
            "score": {"type": "integer"},
            "seen": {"type": "string", "format": "date"},
            "hot": {"type": "boolean"},
            "ratio": {"type": "number"},
        }
        assert sorted(schema["required"]) == ["email", "score"]

    def test_update_takes_a_match_and_the_values(self) -> None:
        registry, _ = _load()

        schema = _tool(registry, "rec__leads__update").parameters

        assert schema["required"] == ["match", "values"]
        assert sorted(schema["properties"]["match"]["properties"]) == ["_id", "email"]
        assert "score" in schema["properties"]["values"]["properties"]

    def test_a_name_already_held_is_left_alone(self) -> None:
        registry, _ = _load()
        before = _tool(registry, "rec__query")

        _rt.load_records_tools(registry, store=_Store(), sets=[_LEADS])  # type: ignore[arg-type]

        assert _tool(registry, "rec__query") is before


class TestAdd:
    def test_the_hop_fills_the_columns_docket_owns(self, tmp_path: Path) -> None:
        registry, store = _load()

        out = _tool(registry, "rec__leads__add").handler(
            {"email": "a@b.test", "score": 2}, _ctx(tmp_path, trace_session_key="s-9")
        )

        assert out.ok
        assert store.calls[0][1][2] == RecordMeta(task="t-1", session="s-9", step="scan")
        assert json.loads(out.content)["created"] is True

    def test_the_session_key_stands_in_when_the_hop_has_no_trace_session(
        self, tmp_path: Path
    ) -> None:
        registry, store = _load()

        _tool(registry, "rec__leads__add").handler({"email": "a", "score": 1}, _ctx(tmp_path))

        assert store.calls[0][1][2].session == "agent:x:y"

    def test_an_argument_docket_fills_is_refused_without_touching_the_store(
        self, tmp_path: Path
    ) -> None:
        registry, store = _load()

        for name in ("_id", "_at", "_task", "_session", "_step", "_updated_at"):
            out = _tool(registry, "rec__leads__add").handler(
                {"email": "a", "score": 1, name: "x"}, _ctx(tmp_path)
            )
            assert not out.ok
            assert name in out.error

        assert store.calls == []

    def test_a_missing_or_null_required_column_is_refused_naming_it(self, tmp_path: Path) -> None:
        registry, store = _load()
        add = _tool(registry, "rec__leads__add")

        missing = add.handler({"email": "a"}, _ctx(tmp_path))
        null = add.handler({"email": "a", "score": None}, _ctx(tmp_path))

        assert "score" in missing.error and "score" in null.error
        assert store.calls == []

    def test_the_store_s_refusal_is_the_tool_s_error(self, tmp_path: Path) -> None:
        store = _Store()
        store.error = RecordsError("column 'score': 'x' is not a valid integer")
        registry, _ = _load(store)

        out = _tool(registry, "rec__leads__add").handler(
            {"email": "a", "score": "x"}, _ctx(tmp_path)
        )

        assert not out.ok
        assert "not a valid integer" in out.error


class TestUpdate:
    def test_the_match_and_values_reach_the_store_with_the_hop(self, tmp_path: Path) -> None:
        registry, store = _load()

        out = _tool(registry, "rec__leads__update").handler(
            {"match": {"email": "a"}, "values": {"score": 4}}, _ctx(tmp_path)
        )

        assert json.loads(out.content) == {"row": {"_id": 1, "score": 4}}
        assert store.calls[0][1][:3] == ("leads", {"email": "a"}, {"score": 4})

    def test_a_value_docket_fills_is_refused(self, tmp_path: Path) -> None:
        registry, store = _load()

        out = _tool(registry, "rec__leads__update").handler(
            {"match": {"_id": 1}, "values": {"_step": "x"}}, _ctx(tmp_path)
        )

        assert "_step" in out.error
        assert store.calls == []

    def test_a_match_or_values_that_is_not_an_object_is_refused(self, tmp_path: Path) -> None:
        registry, store = _load()
        update = _tool(registry, "rec__leads__update")

        assert not update.handler({"match": 1, "values": {}}, _ctx(tmp_path)).ok
        assert not update.handler({"match": {"_id": 1}, "values": "x"}, _ctx(tmp_path)).ok
        assert store.calls == []


class TestQuery:
    def test_the_default_limit_is_fifty_and_the_character_bound_is_the_turn_s_cap(
        self, tmp_path: Path
    ) -> None:
        registry, store = _load()

        out = _tool(registry, "rec__query").handler(
            {"sql": "SELECT 1"}, _ctx(tmp_path, output_cap=2500)
        )

        assert json.loads(out.content) == {"columns": ["n"], "rows": [[1]], "cut": 0}
        _, (sql, rows, chars) = store.calls[0]
        assert (sql, rows) == ("SELECT 1", 50)
        assert 0 < chars < 2500

    def test_a_limit_above_the_ceiling_is_held_to_it(self, tmp_path: Path) -> None:
        registry, store = _load()

        _tool(registry, "rec__query").handler({"sql": "SELECT 1", "limit": 5000}, _ctx(tmp_path))

        assert store.calls[0][1][1] == 200

    def test_a_limit_that_is_not_a_positive_integer_is_refused(self, tmp_path: Path) -> None:
        registry, store = _load()

        for limit in (0, -1, "x", True):
            out = _tool(registry, "rec__query").handler(
                {"sql": "SELECT 1", "limit": limit}, _ctx(tmp_path)
            )
            assert not out.ok

        assert store.calls == []

    def test_a_statement_the_store_refuses_is_the_tool_s_error(self, tmp_path: Path) -> None:
        store = _Store()
        store.error = RecordsError("the query was refused: not authorized")
        registry, _ = _load(store)

        out = _tool(registry, "rec__query").handler({"sql": "DELETE FROM x"}, _ctx(tmp_path))

        assert not out.ok and "refused" in out.error


class TestExport:
    def test_the_file_is_resolved_in_the_root_and_md_is_markdown(self, tmp_path: Path) -> None:
        registry, store = _load()

        out = _tool(registry, "rec__export").handler(
            {"sql": "SELECT 1", "format": "md", "path": "out/r.md"}, _ctx(tmp_path)
        )

        assert json.loads(out.content) == {"rows": 4, "path": "out/r.md"}
        assert store.calls[0][1] == ("SELECT 1", tmp_path.resolve() / "out" / "r.md", "markdown")

    def test_the_format_defaults_to_csv(self, tmp_path: Path) -> None:
        registry, store = _load()

        _tool(registry, "rec__export").handler({"sql": "SELECT 1", "path": "r.csv"}, _ctx(tmp_path))

        assert store.calls[0][1][2] == "csv"

    def test_a_path_outside_the_roots_is_refused_and_the_store_is_not_asked(
        self, tmp_path: Path
    ) -> None:
        registry, store = _load()

        out = _tool(registry, "rec__export").handler(
            {"sql": "SELECT 1", "path": "../x"}, _ctx(tmp_path)
        )

        assert not out.ok
        assert out.refusal == "path_escape"
        assert store.calls == []

    def test_an_unknown_format_is_refused(self, tmp_path: Path) -> None:
        registry, store = _load()

        out = _tool(registry, "rec__export").handler(
            {"sql": "SELECT 1", "format": "xml", "path": "r"}, _ctx(tmp_path)
        )

        assert not out.ok and "csv" in out.error
        assert store.calls == []
