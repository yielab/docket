# Pod Records Specification

**Version**: 1.1.0
**Status**: Implemented in part. The store (`platform/records_store.py`), the `kind: records` document
(`pod update` and `pod export` carry it) and `docket pod records` are implemented. The `rec__*` tools
are specified by their own card and are not shipped: a pod's agent still cannot read or write
records, and only an operator reads them (`docket pod records`).
**Last Updated**: 2026-10-30

## Purpose

A pod that compiles reports, keeps a register or captures data needs somewhere to keep it that is not
a file the model must re-read whole. This specification defines that place: one SQLite file per pod
holding declared, typed tables ("sets"), written by one module, read through a bounded read-only
connection. ADR 0036 decision 15 is the decision; this is the contract of its store.

## Scope

This specification covers:

- The store: declaring a set, adding a column to it, adding and updating rows
- The implicit columns docket fills on every row
- Queries: the read-only connection, the row, character and time bounds
- Exporting a query's rows to CSV or Markdown
- Checking a declaration without applying it
- Which module may import `sqlite3`
- The `kind: records` document, how `pod update` and `pod export` carry it, and `Home.pod_records_path`
- `docket pod records`: listing a pod's sets and reading their rows

This specification does NOT cover:

- The `rec__*` tools, which are the next card: nothing yet lets a pod's agent read or write a row
- Deleting rows, or a set shared between pods (ADR 0036, "Not in this amendment")
- docket's own state (tasks, trace, audit, approvals), which stays where it is

## Requirements

### The store

1. The store **MUST** be one SQLite file whose path the caller names, opened in WAL mode with a busy
   timeout, created mode 0600 in a directory created mode 0700. `platform/records_store.py` **MUST**
   be the only module in `src/docket` that imports `sqlite3`. A SQLite records file is not
   docket-owned JSON: `platform/store.py` remains the only writer of that.
2. A set is declared by `ensure_table(set, columns, key)`. A set name and a column name **MUST** be
   lowercase ASCII letters, digits and underscores, starting with a letter. A column type **MUST** be
   one of `string`, `integer`, `number`, `boolean`, `date`. `key`, when given, **MUST** name a declared
   column and the set **MUST** hold at most one row per key value.
3. The first `ensure_table` for a set **MUST** create its table. A later call with the same set **MUST**
   add every column that is new, keeping the rows, and **MUST** leave unchanged a column that is
   repeated with its type.
4. `ensure_table` **MUST** refuse, raising `RecordsError` that names the column and the set and
   changing nothing, a call that omits a column the set already declares (a removal, and so also a
   rename), repeats one with another type, or changes the key. It never drops, renames or retypes.
5. `add(set, values, meta)` **MUST** refuse a set that is not declared, a value for a column the set
   does not declare, and a value that is not of its column's type, naming the column. A `string` is a
   `str`; an `integer` an `int`; a `number` an `int` or `float`; a `boolean` a `bool`; a `date` a
   `YYYY-MM-DD` string. A `bool` is never an `integer` or a `number`. `None` and an omitted column are
   stored as null, except the key column, which **MUST** be present and not null.
6. When the set has a key and a row with that key value exists, `add` **MUST** write nothing and return
   that row with `created` false; otherwise it **MUST** insert one row and return it with `created`
   true. The check and the insert **MUST** be one transaction, so two adds of one key leave one row.
7. `update(set, match, values, meta)` **MUST** find exactly one row by `{"_id": n}` or by
   `{<key column>: value}` and refuse any other match, a row that does not exist, a value for a column
   that is not declared (an implicit column included) and a change to the key column, each naming what
   it refused. It **MUST** check each value as `add` does and return the updated row.
8. Every row **MUST** carry the implicit columns `_id` (integer, assigned by the store), `_at` (the
   creating time, UTC, from the kernel clock), `_task`, `_session`, `_step` (from `meta`, which the
   hop supplies and the model never does) and `_updated_at` (null until the first update). An update
   **MUST** set `_updated_at` and replace `_task`, `_session` and `_step` with the updating hop's.
   A declared column **MUST NOT** begin with an underscore.
9. A boolean column **MUST** be returned as `bool` and stored as 0 or 1.

### Queries

10. `query(sql, max_rows, max_chars, timeout_s)` **MUST** run on a connection separate from the writer,
    opened `mode=ro`, whose authorizer allows only `SELECT`, reading a column or table, a function and
    recursion. `INSERT`, `UPDATE`, `DELETE`, `ATTACH`, `PRAGMA`, DDL, a second statement and anything
    else **MUST** raise `RecordsError` and leave the data unchanged. A `WITH` query and a join **MUST**
    work.
11. `query` **MUST** return the column names, at most `max_rows` rows, and `cut`, the number of rows
    the query produced that are not returned. Rows are returned in order until adding the next would
    take the total length of their JSON encodings past `max_chars`; the rest count as cut.
12. `query` **MUST** stop a statement that runs past `timeout_s` and raise `RecordsError` saying it was
    stopped, so a recursive query that never ends does not hold the process.
13. `export(sql, path, fmt, timeout_s)` **MUST** run the query as `query` does, without the row or
    character bound, write every row to `path` as `csv` (a header of the column names, then the rows)
    or `markdown` (a table, with `|` and newlines in a cell escaped), and return the number of rows
    written. Another `fmt` **MUST** raise `RecordsError`.

### Checking a declaration

14. `check_table(set, columns, key)` **MUST** do what `ensure_table` would do and change nothing: it
    **MUST** raise the same `RecordsError` for the same refusals, return the same `EnsureResult`
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
    validate every document and `check_table` each set against `Home.pod_records_path(pod)`, and plan
    one item of kind `records` per set: `add` (note `creates the table`) when the set is not yet in
    the file, `replace` (note `adds column x, y`) when it adds columns or the document differs from
    the overlay's copy, `skip` otherwise. A document that omits a column the table declares, retypes
    one or changes the key **MUST** make the whole update refuse, naming the set and the column, with
    the overlay, the table and every other item unwritten. A `--dry-run` **MUST NOT** create the file.
    Applying **MUST** copy each file byte for byte into the overlay's `records/` and call
    `ensure_table`, so a second update plans every item `skip` and a column added to a document keeps
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
    through `query` unchanged, so requirements 10-12 hold: a statement that is not a `SELECT`, a
    second statement and a slow one exit 1 with the store's message and the rows remain. A set no
    document declares exits 1 naming it and the sets there are. `--json` prints `{set, columns, rows,
    cut}` with each row an object.
22. `--csv FILE` **MUST** write every row of the statement, `--limit` ignored, to FILE through
    `export` as CSV, print the number of rows and the file, and print no table.
23. `docket pod records` **MUST** only read: it opens the file read-only, writes nothing and appends
    nothing to the audit log. A pod that has written no row has no file, and reading it prints no
    rows rather than failing for a set the document declares.

## Interface Contracts

### Module API

`docket.platform.records_store`:

- `RecordsStore(path)`: the file's one handle; each call opens and closes its own connection
- `RecordsStore.ensure_table(set_name, columns, key=None) -> EnsureResult` (`created`, `added`)
- `RecordsStore.add(set, values, meta) -> AddResult` (`row`, `created`)
- `RecordsStore.update(set, match, values, meta) -> dict`
- `RecordsStore.query(sql, max_rows, max_chars, timeout_s) -> QueryResult` (`columns`, `rows`, `cut`)
- `RecordsStore.export(sql, path, fmt, timeout_s) -> int`
- `RecordsStore.check_table(set_name, columns, key=None) -> EnsureResult`
- `Column(name, type)`, `RecordMeta(task, session, step)`, `RecordsError(InvalidInput)`
- `COLUMN_TYPES`, `check_value(column, value)`, `render_markdown(columns, rows)`

`docket.kernel.records`: `RecordSet`, `RecordColumn`, `ColumnType` (the typed config, no I/O).

`docket.teams.records`: `RecordsDocument`, `RecordsDocError`, `load_records_document(path)`,
`records_files(directory)`, `pod_record_sets(project)`, `check_sets(project, sets)`,
`ensure_sets(project, sets)`, `row_counts(project, sets)`, `read_rows(project, sql, limit)`.

### Environment

The store reads no environment variable. Where the file lives is the caller's decision.

## Examples

```python
store = RecordsStore(pod_dir / "records.sqlite")
store.ensure_table("listings", [Column("url", "string"), Column("price", "integer")], key="url")
store.add("listings", {"url": "https://a.test/1", "price": 90}, RecordMeta("t-1", "s-1", "scan"))
# AddResult(row={..., "_id": 1, "price": 90}, created=True); the same call again: created=False
store.query("SELECT url, price FROM listings ORDER BY price", 200, 2500, 5.0)
# QueryResult(columns=("url", "price"), rows=[("https://a.test/1", 90)], cut=0)
store.query("DELETE FROM listings", 200, 2500, 5.0)  # RecordsError, nothing deleted
```

## Validation

### Pre-conditions

- The directory of the file **MUST** be writable by the process; the store creates the file and, if
  absent, the directory.

### Post-conditions

- After a refused `ensure_table`, `add`, `update` or `query`, the file **MUST** be as it was.
- After `add` returns `created` true, `query` on a new connection **MUST** see the row.

### Invariants

- No path of the store **MUST** delete a row or a column.
- A value reaches a column only after `check_value` accepted it for that column's type.
- `sqlite3` is imported by `platform/records_store.py` and by no other module of `src/docket`
  (`tests/architecture/test_records_writer.py`).

## Implementation

- `src/docket/platform/records_store.py`: the store; `platform/__init__.py` exports `RecordsStore`,
  `Column` and `RecordsError`, which `teams/records.py` imports
- `src/docket/kernel/records.py`: the typed config of the document
- `src/docket/teams/records.py`: loading, validating and applying a pod's documents
- `src/docket/teams/apply/records.py`: the `records/` plan, write and export
- `src/docket/interfaces/cli/commands/pod_records.py`: `docket pod records`
- `tests/architecture/test_records_writer.py`: requirement 1's import rule
- `tests/integration/platform/test_records_store.py`: requirements 3-13 on a temporary file
- `tests/unit/platform/test_records_store.py`: `check_value`, `render_markdown`, name checks
- `tests/unit/teams/test_records__doc.py`: requirements 15-16 (the document)
- `tests/integration/interfaces/test_pod_records_cli.py`: requirements 17-23 (`pod update`, `pod
  export`, `pod records`)
