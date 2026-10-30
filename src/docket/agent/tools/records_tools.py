"""A pod's records as tools: per declared set an ``add`` and an ``update``, per pod a ``query`` and an
``export`` (specs/functional/pod-records.spec.md, "The tools"). **Wired to the live turn path**:
``hops/application/driver_support.py`` loads the pod's sets each turn and hands them here. Every
tool is an ordinary ``Tool``, so each call still passes ``agent.tools.registry.dispatch_tool``; the
handlers run in docket's process and reach the records only through the ``RecordStore`` port, whose
adapter holds the write transaction and the read-only authorizer. docket fills ``_task``, ``_session`` and
``_step`` from the hop and refuses a model argument that names one of them. No tool is ``send``:
records never leave the machine. ``load_records_tools`` never raises."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from docket.agent.tools.builtins.toolbox import PathEscapeError, resolve_within
from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry
from docket.kernel.home import current_home
from docket.kernel.records import RecordsError, RecordSet, records_tool_name
from docket.kernel.records_port import ReadLimits, RecordOrigin, RecordStore, Rows
from docket.kernel.tool_outcome import ToolOutcome, text_outcome

__all__ = ["load_records_tools"]

_RESERVED = ("_id", "_at", "_task", "_session", "_step", "_updated_at")
_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200
_EXPORT = ReadLimits(timeout_s=30.0)
_FORMATS = {"csv": "csv", "md": "markdown"}
_JSON_TYPE: dict[str, dict[str, str]] = {
    "string": {"type": "string"},
    "integer": {"type": "integer"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
}
Handler = Callable[[dict[str, Any], ToolContext], ToolOutcome]


def _fail(message: str) -> ToolOutcome:
    return ToolOutcome(False, error=message)


def _json(payload: object) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False, separators=(",", ":"))


def _origin(ctx: ToolContext) -> RecordOrigin:
    """The hop a write comes from, read from the context and never from the model."""
    return RecordOrigin(
        task=ctx.task_id or None,
        session=ctx.trace_session_key or ctx.session_key or None,
        step=ctx.step_id or None,
    )


def _reserved(names: Sequence[str]) -> ToolOutcome | None:
    for name in names:
        if name in _RESERVED:
            return _fail(f"argument {name!r} is filled by docket and cannot be set")
    return None


def _guarded(call: Callable[[], ToolOutcome]) -> ToolOutcome:
    """*call*'s outcome, or the store's refusal as the tool's error."""
    try:
        return call()
    except RecordsError as exc:
        return _fail(str(exc))


def _properties(record_set: RecordSet, *, skip: str | None = None) -> dict[str, Any]:
    return {
        c.name: {**_JSON_TYPE[c.type], **({"description": c.description} if c.description else {})}
        for c in record_set.columns
        if c.name != skip
    }


def _add_tool(store: RecordStore, record_set: RecordSet) -> Tool:
    required = [c.name for c in record_set.columns if c.required or c.name == record_set.key]

    def handler(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        if (refused := _reserved(list(args))) is not None:
            return refused
        if missing := [name for name in required if args.get(name) is None]:
            return _fail(f"set {record_set.name!r}: {', '.join(missing)} is required")

        def add() -> ToolOutcome:
            added = store.add(record_set.name, args, _origin(ctx))
            return text_outcome(_json({"created": added.created, "row": added.row}))

        return _guarded(add)

    key = (
        f" A row with the same {record_set.key} is returned, not added again."
        if record_set.key
        else ""
    )
    return Tool(
        name=records_tool_name(record_set.name, "add"),
        description=f"[records:{record_set.name}] Add a row to {record_set.name}.{key} "
        f"{record_set.description}".strip(),
        parameters={
            "type": "object",
            "properties": _properties(record_set),
            "required": required,
        },
        handler=handler,
        kind="write",
    )


def _update_tool(store: RecordStore, record_set: RecordSet) -> Tool:
    match: dict[str, Any] = {"_id": {"type": "integer"}}
    if record_set.key:
        match[record_set.key] = _properties(record_set)[record_set.key]

    def handler(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        found, values = args.get("match"), args.get("values")
        if not isinstance(found, dict) or not isinstance(values, dict):
            return _fail("match and values must each be an object")
        if (refused := _reserved(list(values))) is not None:
            return refused

        def update() -> ToolOutcome:
            row = store.update(record_set.name, found, values, _origin(ctx))
            return text_outcome(_json({"row": row}))

        return _guarded(update)

    by = "_id" + (f" or {record_set.key}" if record_set.key else "")
    return Tool(
        name=records_tool_name(record_set.name, "update"),
        description=f"[records:{record_set.name}] Change columns of the one row of "
        f"{record_set.name} that `match` names by {by}.",
        parameters={
            "type": "object",
            "properties": {
                "match": {"type": "object", "properties": match},
                "values": {
                    "type": "object",
                    "properties": _properties(record_set, skip=record_set.key),
                },
            },
            "required": ["match", "values"],
        },
        handler=handler,
        kind="write",
    )


def _cap(ctx: ToolContext) -> int:
    return ctx.output_cap or current_home().tool_max_output_chars


def _limit(raw: object) -> int | None:
    if raw is None:
        return _LIMIT_DEFAULT
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1:
        return min(raw, _LIMIT_MAX)
    return None


def _query_tool(store: RecordStore) -> Tool:
    def handler(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        sql, limit = args.get("sql"), _limit(args.get("limit"))
        if not isinstance(sql, str) or not sql.strip():
            return _fail("sql must be a SELECT statement")
        if limit is None:
            return _fail(f"limit must be a whole number from 1 to {_LIMIT_MAX}")
        cap = _cap(ctx)
        return _guarded(lambda: _rows(store.read(sql, ReadLimits(limit, cap)), cap))

    return Tool(
        name=records_tool_name(operation="query"),
        description="[records] Run one read-only SELECT over the pod's record sets. "
        "Columns _id, _at, _task, _session, _step and _updated_at exist on every row.",
        parameters={
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "limit": {"type": "integer", "description": f"At most {_LIMIT_MAX}."},
            },
            "required": ["sql"],
        },
        handler=handler,
    )


def _rows(result: Rows, cap: int) -> ToolOutcome:
    """The result as JSON within *cap*; rows that do not fit count as cut."""
    rows, cut = [list(row) for row in result.rows], result.cut
    while True:
        text = _json({"columns": list(result.columns), "rows": rows, "cut": cut})
        if len(text) <= cap or not rows:
            return text_outcome(text)
        rows.pop()
        cut += 1


def _shown(roots: tuple[Path, ...], target: Path) -> str:
    for root in roots:
        if target.is_relative_to(root.resolve()):
            return target.relative_to(root.resolve()).as_posix()
    return str(target)


def _export_tool(store: RecordStore) -> Tool:
    def handler(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        sql, path, fmt = args.get("sql"), args.get("path"), args.get("format", "csv")
        if not isinstance(sql, str) or not sql.strip() or not isinstance(path, str) or not path:
            return _fail("sql and path are required")
        if fmt not in _FORMATS:
            return _fail("format must be csv or md")
        try:
            target = resolve_within(ctx.roots, path)
        except PathEscapeError as exc:
            return ToolOutcome(False, error=str(exc), refusal="path_escape")
        return _guarded(lambda: _exported(store, sql, target, _FORMATS[fmt], ctx))

    return Tool(
        name=records_tool_name(operation="export"),
        description="[records] Write the rows of one read-only SELECT to a file in the working "
        "directory as csv or md. The rows are not returned, only how many were written.",
        parameters={
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "path": {"type": "string"},
                "format": {"type": "string", "enum": list(_FORMATS)},
            },
            "required": ["sql", "path"],
        },
        handler=handler,
        kind="write",
    )


def _exported(
    store: RecordStore, sql: str, target: Path, fmt: str, ctx: ToolContext
) -> ToolOutcome:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        count = store.export(sql, target, fmt, _EXPORT)
    except OSError as exc:
        return _fail(f"cannot write {target.name}: {exc}")
    return ToolOutcome(True, content=_json({"rows": count, "path": _shown(ctx.roots, target)}))


def load_records_tools(
    registry: ToolRegistry, *, store: RecordStore, sets: Sequence[RecordSet]
) -> list[str]:
    """Register the record tools of *sets* into *registry*: an add and an update for each set, and
    one query and one export for the pod. A name already in *registry* is skipped, never replaced.
    Returns the names registered."""
    tools = [t for s in sets for t in (_add_tool(store, s), _update_tool(store, s))]
    if sets:
        tools += [_query_tool(store), _export_tool(store)]
    fresh = [t for t in tools if t.name not in registry]
    for tool in fresh:
        registry.register(tool)
    return [t.name for t in fresh]
