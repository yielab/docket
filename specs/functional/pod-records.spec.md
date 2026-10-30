# Pod Records Specification

**Version**: 1.4.0
**Status**: Implemented in part. The port (`RecordStore`, `kernel/records_port.py`), its SQLite adapter
(`platform/records_sqlite.py`), the `kind: records` document
(`pod update` and `pod export` carry it), `docket pod records` and the `rec__*` tools a hop's agent
reads and writes records with ("The tools") and the two read routes of the HTTP API ("Over HTTP") are
implemented. Nothing is proven against a live model yet.
**Last Updated**: 2026-10-30

## Purpose

A pod that compiles reports, keeps a register or captures data needs somewhere to keep it that is not
a file the model must re-read whole. This specification defines that place: one SQLite file per pod
holding declared, typed tables ("sets"), written by one module, read through a bounded read-only
connection. The consumers speak to a port, not to SQLite, so another engine is one adapter module.
ADR 0036 decision 15 is the decision; this is the contract of its store.

## Scope

This specification covers:

- The store: declaring a set, adding a column to it, adding and updating rows
- The implicit columns docket fills on every row
- Queries: the read-only connection, the row, character and time bounds
- Exporting a query's rows to CSV or Markdown
- Checking a declaration without applying it
- The port a pod's records sit behind, and which module may import `sqlite3`
- The `kind: records` document, how `pod update` and `pod export` carry it, and `Home.pod_records_path`
- `docket pod records`: listing a pod's sets and reading their rows
- The `rec__*` tools: the operations a pod's agent has on its records, and how a role names them
- `GET /pods/<pod>/records` and `GET /pods/<pod>/records/<set>`: reading records over the HTTP API

This specification does NOT cover:

- Sending a record anywhere: records never leave the machine, and no record tool is `send`
- Deleting rows, or a set shared between pods (ADR 0036, "Not in this amendment")
- docket's own state (tasks, trace, audit, approvals), which stays where it is

## Requirements

### The store

1. The SQLite adapter **MUST** be one file whose path the caller names, opened in WAL mode with a busy
   timeout, created mode 0600 in a directory created mode 0700. `platform/records_sqlite.py` **MUST**
   be the only module in `src/docket` that imports `sqlite3`, and `bootstrap.py` **MUST** be the only
   module that imports `platform/records_sqlite.py`: every other module reaches a pod's records
   through the `RecordStore` port, as `records.open(pod)` (`kernel/ports.py`), whose factory
   `bootstrap.bind_adapters` binds. A SQLite records file is not docket-owned JSON: `platform/store.py`
   remains the only writer of that.
2. A set is declared by `declare(record_set)`. A set name and a column name **MUST** be
   lowercase ASCII letters, digits and underscores, starting with a letter. A column type **MUST** be
   one of `string`, `integer`, `number`, `boolean`, `date`. `key`, when given, **MUST** name a declared
   column and the set **MUST** hold at most one row per key value.
3. The first `declare` for a set **MUST** create its table. A later call with the same set **MUST**
   add every column that is new, keeping the rows, and **MUST** leave unchanged a column that is
   repeated with its type.
4. `declare` **MUST** refuse, raising `RecordsError` that names the column and the set and
   changing nothing, a call that omits a column the set already declares (a removal, and so also a
   rename), repeats one with another type, or changes the key. It never drops, renames or retypes.
5. `add(set, values, origin)` **MUST** refuse a set that is not declared, a value for a column the set
   does not declare, and a value that is not of its column's type, naming the column. A `string` is a
   `str`; an `integer` an `int`; a `number` an `int` or `float`; a `boolean` a `bool`; a `date` a
   `YYYY-MM-DD` string. A `bool` is never an `integer` or a `number`. `None` and an omitted column are
   stored as null, except the key column, which **MUST** be present and not null.
6. When the set has a key and a row with that key value exists, `add` **MUST** write nothing and return
   that row with `created` false; otherwise it **MUST** insert one row and return it with `created`
   true. The check and the insert **MUST** be one transaction, so two adds of one key leave one row.
7. `update(set, match, values, origin)` **MUST** find exactly one row by `{"_id": n}` or by
   `{<key column>: value}` and refuse any other match, a row that does not exist, a value for a column
   that is not declared (an implicit column included) and a change to the key column, each naming what
   it refused. It **MUST** check each value as `add` does and return the updated row.
8. Every row **MUST** carry the implicit columns `_id` (integer, assigned by the store), `_at` (the
   creating time, UTC, from the kernel clock), `_task`, `_session`, `_step` (from `origin`, which the
   hop supplies and the model never does) and `_updated_at` (null until the first update). An update
   **MUST** set `_updated_at` and replace `_task`, `_session` and `_step` with the updating hop's.
   A declared column **MUST NOT** begin with an underscore.
9. A boolean column **MUST** be returned as `bool` and stored as 0 or 1.

### Queries

The statement of `read` and `export` is a read-only statement in the backend's own SQL dialect: for the
SQLite adapter, SQLite's. docket does not translate it.

10. `read(statement, limits)` **MUST** run on a connection separate from the writer,
    opened `mode=ro`, whose authorizer allows only `SELECT`, reading a column or table, a function and
    recursion. `INSERT`, `UPDATE`, `DELETE`, `ATTACH`, `PRAGMA`, DDL, a second statement and anything
    else **MUST** raise `RecordsError` and leave the data unchanged. A `WITH` query and a join **MUST**
    work.
11. `read` **MUST** return the column names, at most `limits.max_rows` rows, and `cut`, the number of rows
    the query produced that are not returned. Rows are returned in order until adding the next would
    take the total length of their JSON encodings past `limits.max_chars`; the rest count as cut.
12. `read` **MUST** stop a statement that runs past `limits.timeout_s` and raise `RecordsError` saying it was
    stopped, so a recursive query that never ends does not hold the process.
13. `export(statement, target, fmt, limits)` **MUST** run the statement as `read` does (only
    `limits.timeout_s` applies), without the row or
    character bound, write every row to `target` as `csv` (a header of the column names, then the rows)
    or `markdown` (a table, with `|` and newlines in a cell escaped), and return the number of rows
    written. Another `fmt` **MUST** raise `RecordsError`.

### Checking a declaration

14. `plan(record_set)` **MUST** do what `declare` would do and change nothing: it
    **MUST** raise the same `RecordsError` for the same refusals, return the same `SetChange`
    (`created` true when the file or the set does not exist, else the columns it would add), open the
    file read-only and **MUST NOT** create the file or the directory.

### The document

15. A `kind: records` document **MUST** declare one set: `name` (`^[a-z][a-z0-9_]*$`), an optional
    `description`, an optional `key` and `columns`, at least one and at most 40, each with `name`
    (`^[a-z][a-z0-9_]*$`, unique within the set), `type` (`string`, `integer`, `number`, `boolean` or
    `date`), `required` (default false) and an optional `description`. `key`, when given, **MUST** name
    one of the columns. Any other key is refused. A column name that starts with `_` **MUST** be
    refused (`_id`, `_at`, `_task`, `_session`, `_step` and `_updated_at` are docket's), as **MUST** an
    unknown type, a repeated column, a `key` that is no column and a 41st column, each naming the
    file and the first failing field. `required` is carried and published; the store does not enforce
    it (only the key column is non-null), and the tools will.
16. A set belongs to one pod. The document is read from `records/*.yaml|yml` of the directory
    `pod update` applies and from the pod's own overlay (`records/` beside `roles/`); no operator or
    global file exists, and two files naming one set **MUST** be refused.
17. `docket pod update <directory>` with a `records/` directory **MUST**, before writing anything,
    validate every document and `plan` each set against `Home.pod_records_path(pod)`, and plan
    one item of kind `records` per set: `add` (note `creates the table`) when the set is not yet in
    the file, `replace` (note `adds column x, y`) when it adds columns or the document differs from
    the overlay's copy, `skip` otherwise. A document that omits a column the table declares, retypes
    one or changes the key **MUST** make the whole update refuse, naming the set and the column, with
    the overlay, the table and every other item unwritten. A `--dry-run` **MUST NOT** create the file.
    Applying **MUST** copy each file byte for byte into the overlay's `records/` and call
    `declare`, so a second update plans every item `skip` and a column added to a document keeps
    the rows. Each file **MUST** be an `applied.lock` item (kind `records`, applied as
    `records/<file>`) and an add in the operator's review.
18. `docket pod export` **MUST** write the pod's `records/` documents back byte for byte as
    `records/<file>`. It **MUST NOT** write a row, and **MUST** say so: the records document is
    exported, the rows stay in the pod's `records.sqlite`.
19. `docket pod validate` **MUST** validate every `records/*.yaml|yml` file as a `kind: records`
    document. `Home.pod_records_path(pod)` **MUST** be `pods/<pod>/records.sqlite`, beside
    `memory.json`.

### The CLI

20. `docket pod records` with no set **MUST** list the sets the pod's `records/` documents declare,
    one row each: name, rows (0 for a set whose table does not exist yet), columns, key (`-` for
    none) and description. `--json` prints a list of `{name, rows, columns, key, description}`. A pod
    with no set prints `No records in pod '<pod>'.` and exits 0; a document that no longer validates
    is listed with its error and the command exits 1.
21. `docket pod records <set>` **MUST** print the set's rows (`SELECT * FROM <set> ORDER BY _id`) as a
    table, at most `--limit N` of them (default 50, N at least 1), and a line saying how many rows
    were left out when there are some. `--sql "<SELECT>"` replaces that statement and **MUST** run
    through `read` unchanged, so requirements 10-12 hold: a statement that is not a `SELECT`, a
    second statement and a slow one exit 1 with the store's message and the rows remain. A set no
    document declares exits 1 naming it and the sets there are. `--json` prints `{set, columns, rows,
    cut}` with each row an object.
22. `--csv FILE` **MUST** write every row of the statement, `--limit` ignored, to FILE through
    `export` as CSV, print the number of rows and the file, and print no table.
23. `docket pod records` **MUST** only read: it opens the file read-only, writes nothing and appends
    nothing to the audit log. A pod that has written no row has no file, and reading it prints no
    rows rather than failing for a set the document declares.

### The tools

30. A hop of a pod that declares at least one valid set **MUST** be offered, beside the MCP and service
    tools and before the role narrows them, `rec__<set>__add` and `rec__<set>__update` for each set,
    and `rec__query` and `rec__export` once. A hop of a pod with no set, or with no pod, **MUST** be
    offered none. A name the registry already holds **MUST** be left as it is. A document that does not
    validate **MUST** contribute no tool and **MUST** append a `records.unavailable` event to the
    audit log naming the file. Loading **MUST NOT** raise. Every call **MUST** pass `dispatch_tool`,
    like any tool, so the pod's policies and the role's kinds apply.
31. `rec__<set>__add` **MUST** be a `write` tool whose parameters are the set's columns: a `string` and
    a `date` as a JSON string (a `date` with `format: date`), an `integer`, a `number` and a `boolean`
    as their JSON types, with `required` naming the columns declared `required` and the key. It
    **MUST** call `RecordStore.add` and return JSON `{"created": <bool>, "row": {...}}`. An add whose
    key exists returns that row with `created` false and writes nothing, so a resumed hop that repeats
    its call leaves one row. A required column that is missing or null **MUST** be refused naming the
    column, writing nothing.
32. `rec__<set>__update` **MUST** be a `write` tool with two parameters, both required: `match`, an
    object holding `_id` or the key column (one of them), and `values`, an object of the set's columns.
    It **MUST** call `RecordStore.update` and return `{"row": {...}}`. A refusal the store makes
    (a missing row, a change to the key, a wrong type, an undeclared column) **MUST** come back as the
    tool's error text, with the file unchanged.
33. docket **MUST** fill `_task` (the hop's task id), `_session` (the hop's trace session, else its
    session key) and `_step` (the hop's pipeline step) from the hop and **MUST NOT** take them from
    the model. An argument named `_id`, `_at`, `_task`, `_session`, `_step` or `_updated_at`, at the
    top level of an add or inside `values` of an update, **MUST** be refused naming it, writing
    nothing. A column of the set is the only other name an add accepts.
34. `rec__query` **MUST** be a `read` tool with `sql` (required) and `limit` (optional, default 50,
    at most 200). It **MUST** call `RecordStore.read` unchanged, so requirements 10-12 hold, bound
    its rows by `limit` and the characters of its result by the turn's tool-output cap
    (`DOCKET_TOOL_MAX_OUTPUT_CHARS`), and return `{"columns": [...], "rows": [[...]], "cut": n}`. A
    statement the store refuses, or a pod that has written no row, **MUST** come back as the tool's
    error text.
35. `rec__export` **MUST** be a `write` tool with `sql` and `path` (required) and `format` (`csv`, the
    default, or `md`). `path` **MUST** resolve as the `write` tool resolves it: relative to the hop's
    first root, inside one of its roots; a path that resolves outside them **MUST** be refused with
    the `path_escape` refusal and nothing written. It **MUST** call `RecordStore.export` and return
    `{"rows": n, "path": <path>}` only: the exported rows **MUST NOT** pass through the model.
36. No result of a record tool **MUST** exceed the turn's tool-output cap.
37. A role's `tools` allow-list names record tools as `rec__<set>` (that set's add and update),
    `rec__query`, `rec__export`, or `rec` (every record tool of the pod); a role with no allow-list
    holds them all. A role that denies `write`, by its own `deniedTools` or its pod's, **MUST** lose
    add, update and export, by their kind, and keep `rec__query`. The `minimal` surface **MUST** keep
    a record tool the allow-list in force names. `role-archetypes.spec.md` is the contract of those
    rules.
38. No record tool **MUST** be `send`, and none has an approval of its own: a policy `ask` on `rec__*`
    is the operator's choice, through the ordinary approval path.
39. The tools run in docket's process. The records file **MUST NOT** be under any root, cache or
    read-only directory a hop's jail is given, so a command the model runs reads and writes no
    record.

### Over HTTP

50. `GET /pods/<pod>/records` **MUST** answer `200` with `{"records": [...], "problems": [...]}`:
    one object per set the pod's `records/` documents declare -- `name`, `description`, `key` (null
    for none), `rows` (0 for a set whose table does not exist yet) and `columns`, each `{name, type,
    required}` -- and one message for each document that does not validate. The set list is
    `pod_record_sets` and the count is `row_count`, the functions `docket pod records` calls.
51. `GET /pods/<pod>/records/<set>` **MUST** answer `200` with `{"set", "columns", "rows", "cut"}`,
    the shape `docket pod records <set> --json` prints (`columns` the names, each row an object),
    through `read_rows`: with no `sql` the statement is `SELECT * FROM <set> ORDER BY _id DESC` (newest
    first, so `limit` keeps the latest rows; the CLI's default stays `_id` order), with
    `sql=<SELECT>` it runs through `read` unchanged, so requirements 10-12 hold over HTTP. `limit`
    defaults to 50, is at least 1 and at most 1000; any other value is `400`. A pod that has
    written no row reads as no rows.
52. A statement `read` refuses (not one `SELECT`, a second statement, a slow one) **MUST** be `400`
    with `{"ok": false, "error": <the store's message>}` and the rows remain. A set no document of
    the pod declares is `404` naming it and the sets there are; a pod that is not dispatchable is
    `404`; a pod id that fails `validate_project_id` is `400`; a missing or wrong Bearer token is
    `401` before anything is read.
53. Both routes **MUST** only read: nothing is written to the records file or the audit log, and a
    set is read from the one pod the path names, never from another pod's file.

## Interface Contracts

### Module API

`docket.kernel.records_port`, the port. `RecordStore` is a `Protocol`; its operations are the contract
of "The store", "Queries" and "Checking a declaration", and none names an engine:

- `declare(record_set) -> SetChange`: create the set or add its new columns; refuse the rest
- `plan(record_set) -> SetChange`: what `declare` would do, changing nothing
- `has(set_name) -> bool`: whether the set is declared; false before the first write
- `add(set_name, values, origin) -> AddOutcome` (`row`, `created`), idempotent by key
- `update(set_name, match, values, origin) -> Row`
- `read(statement, limits) -> Rows` (`columns`, `rows`, `cut`): one read-only statement, bounded
- `export(statement, target, fmt, limits) -> int`: every row to a file as `csv` or `markdown`
- the values they exchange: `RecordOrigin(task, session, step)`, `SetChange(created, added)`,
  `AddOutcome`, `Rows`, `ReadLimits(max_rows, max_chars, timeout_s)` and `Row`

`docket.kernel.records`: `RecordSet`, `RecordColumn`, `ColumnType`, `COLUMN_TYPES` (the typed config, no
I/O), `RecordsError(InvalidInput)`, `RECORDS_TOOL_PREFIX` (`rec__`) and `records_tool_name(set, op)`.

`docket.kernel.records_rules`: the rules every backend shares, pure: `check_value(column, kind, value)`,
`check_add`, `check_update`, `plan_change(current, wanted)`, `bound_rows`, `check_format`,
`write_export` and `EXPORT_FORMATS`.

`docket.kernel.ports`: `records_port` (a `Binding` whose value is a factory, pod name to `RecordStore`),
`bind_records(factory)` and `records.open(pod)`. The backend is per pod, so the binding holds the
factory and no store. `bootstrap.bind_adapters` binds the SQLite factory, the one place a later backend
is chosen; a test swaps it with `records_port.use(factory)`.

`docket.platform.records_sqlite`: `SqliteRecordStore(path)`, the adapter. It is built from the pod's
file path, each call opens and closes its own connection, and it keeps only what is SQLite: the
connection, WAL and the write transaction, the SQL type map and DDL, the `_declared` table, the
read-only authorizer and the progress-handler time bound. A second backend is one adapter module, one
line in the factory and one entry in the conformance suite's `store` fixture.

`docket.agent.tools.records_tools`: `load_records_tools(registry, *, store, sets)`, which registers the
tools of "The tools" into a `ToolRegistry`; `store` is a `RecordStore`.

`docket.teams.records`: `RecordsDocument`, `RecordsDocError`, `load_records_document(path)`,
`records_files(directory)`, `pod_records_dir(pod)`, `pod_record_sets(pod)`, `find_set(pod, name)`,
`check_set(pod, record_set)`, `ensure_set(pod, record_set)`, `row_count(pod, record_set)`,
`default_sql(record_set)`, `read_rows(pod, record_set, sql, limit)`, `export_csv(pod, record_set, sql,
path)` and `rows_payload(record_set, result)` (the `{set, columns, rows, cut}` object the CLI's `--json`
and `GET /pods/<pod>/records/<set>` share). All reach the records through `records.open(pod)`.

### Environment

The store reads no environment variable. Where the file lives is the caller's decision.

## Examples

```python
store = records.open("shop")  # the SQLite adapter, bound by bootstrap
listings = RecordSet(name="listings", key="url", columns=[
    RecordColumn(name="url", type="string"), RecordColumn(name="price", type="integer")])
store.declare(listings)
store.add("listings", {"url": "https://a.test/1", "price": 90}, RecordOrigin("t-1", "s-1", "scan"))
# AddOutcome(row={..., "_id": 1, "price": 90}, created=True); the same call again: created=False
store.read("SELECT url, price FROM listings ORDER BY price", ReadLimits(200, 2500, 5.0))
# Rows(columns=("url", "price"), rows=[("https://a.test/1", 90)], cut=0)
store.read("DELETE FROM listings", ReadLimits(200, 2500, 5.0))  # RecordsError, nothing deleted
```

## Validation

### Pre-conditions

- The directory of the file **MUST** be writable by the process; the store creates the file and, if
  absent, the directory.

### Post-conditions

- After a refused `declare`, `add`, `update` or `read`, the file **MUST** be as it was.
- After `add` returns `created` true, `read` on a new connection **MUST** see the row.

### Invariants

- No path of the store **MUST** delete a row or a column.
- A value reaches a column only after `check_value` accepted it for that column's type.
- `sqlite3` is imported by `platform/records_sqlite.py` and by no other module of `src/docket`
  (`tests/architecture/test_records_writer.py`), and `bootstrap.py` is the only importer of that
  module (`tests/architecture/test_records_adapter.py`).

## Implementation

- `src/docket/kernel/records_port.py`: the `RecordStore` port and the values it exchanges
- `src/docket/kernel/records_rules.py`: the engine-independent rules (names, values, the
  declaration check, the row and character bound, the export rendering)
- `src/docket/kernel/records.py`: the typed config of the document and `RecordsError`
- `src/docket/kernel/ports.py`: the `records` binding (`records.open(pod)`)
- `src/docket/platform/records_sqlite.py`: the SQLite adapter, built by `bootstrap.py`
- `src/docket/teams/records.py`: loading, validating and applying a pod's documents
- `src/docket/teams/apply/records.py`: the `records/` plan, write and export
- `src/docket/agent/tools/records_tools.py`: the tools; `hops/application/driver_support.py` loads them
  each turn (`_load_records_tools`); `teams/roles.py`, `teams/role_composer.py` and
  `teams/apply/check.py` carry the role rules
- `src/docket/interfaces/cli/commands/pod_records.py`: `docket pod records`
- `src/docket/interfaces/http/routes/pod_records.py`: `GET /pods/<pod>/records[/<set>]`
- `tests/architecture/test_records_writer.py`: requirement 1's `sqlite3` rule
- `tests/architecture/test_records_adapter.py`: requirement 1's rule that only `bootstrap.py` names the adapter
- `tests/integration/platform/test_record_store_conformance.py`: requirements 3-14 on every backend
  (one `store` fixture entry per backend)
- `tests/integration/platform/test_records_sqlite.py`: what only the SQLite file has (mode, WAL, stored
  booleans, no file created by a read)
- `tests/unit/kernel/test_records_rules.py`: the shared rules
- `tests/unit/teams/test_records__doc.py`: requirements 15-16 (the document)
- `tests/unit/agent/tools/test_records_tools.py`: requirements 31-36 on the tool objects
- `tests/integration/agent/tools/test_records_tools.py`: requirements 30-39 through `DocketDriver`
  and a scripted model
- `tests/integration/interfaces/test_pod_records_cli.py`: requirements 17-23 (`pod update`, `pod
  export`, `pod records`)
- `tests/integration/interfaces/test_pod_records_api.py`: requirements 50-53 (the two routes)
