# Docket JSON Store Specification

**Version**: 3.0.0
**Status**: Implemented
**Last updated**: 2026-10-25

## Purpose

Define the durability and recovery contract for Docket-owned JSON documents. A malformed primary
must not make a valid single-generation backup unusable, and recovery must not hide the malformed
bytes that explain the incident.

## Scope

This specification covers docket-owned JSON objects read and written through the store's public
`read_json` and `write_json` functions and the locked `read_modify_write` transition. It does not
cover append-only JSONL audit or trace files, missing-primary repair, schema migration, remote
backups, or a general filesystem backup service.

## Structure

For a primary path `state.json`, the store owns these bounded siblings:

| Path | Purpose | Retention |
| --- | --- | --- |
| `state.json` | Current JSON object | One current generation |
| `state.json.bak` | Previous complete JSON object | One generation, replaced by a write over a valid primary |
| `state.json.corrupt` | Exact malformed primary bytes, kept when a malformed primary is recovered or overwritten | One generation, replaced by a later recovery or by a write over a malformed primary |
| `state.json.tmp` | Same-directory atomic-write staging | Must not remain after success or failure |

The primary and quarantine files MUST have mode `0600` after successful recovery. The backup is
valid recovery input only when it is UTF-8 JSON whose top-level value is an object. A malformed
primary is one that is not UTF-8 JSON or whose top-level value is not an object. Every sibling is
written at mode `0600`, and a symlink already sitting on a sibling name is removed, never followed.

## Schema

Recovery does not add, remove, or reinterpret document fields. The recovered primary has exactly
the object semantics of the backup. The quarantine is opaque diagnostic bytes rather than JSON.

`read_json(path)` follows this state machine while holding the per-directory store lock (the lock
file `.docket.lock` beside the primary):

1. A missing primary returns `{}` and does not restore a backup.
2. A valid primary returns its object without changing primary, backup, or quarantine bytes, even
   when the backup is stale or malformed.
3. A malformed primary with a valid backup preserves the malformed bytes in the fixed quarantine,
   atomically restores the backup object to the primary, and returns that object.
4. A malformed primary with a missing, unreadable, or malformed backup raises `StoreRecoveryError`.
   The error identifies the primary and backup and describes why recovery cannot proceed. It changes
   no primary, backup, quarantine, or temporary-file bytes.

`write_json(path, data)` applies the same quarantine to a malformed primary before it replaces the
primary with the new object. It leaves the backup unchanged and does not restore the backup.

Backup validation completes before recovery writes begin. If a later filesystem write fails, the
operation raises that I/O error: the malformed primary and valid backup remain intact, the bounded
quarantine may already contain the current malformed bytes, and no temporary file remains. A retry
can therefore perform the same recovery without inventing empty state.

Only one lock owner may inspect recovery inputs, quarantine bytes, restore the primary, or perform
the following write. `read_modify_write` MUST use the same lock boundary without reacquiring the
non-reentrant directory lock. Concurrent readers therefore observe one recovery winner, while a
concurrent locked mutation preserves one complete generation and cannot rotate malformed bytes
over the valid backup.

## Escalation records

The store also owns the second typed record family after the task queue: one durable record per
escalation (`operator-loop.spec.md` "Escalations"), kept under `DOCKET_HOME/escalations/`.

| Path | Purpose |
| --- | --- |
| `escalations/esc-<12 hex>.json` | One `pending` `Escalation` record, the camelCase JSON of the operator contract model |
| `escalations/settled/esc-<12 hex>.json` | A record in any other state (`resolved`, `expired`, `decided`) |
| `escalations/_seq.json` | `{"seq": n}`, the last `seq` handed out |

Both directories are `0700` and every file in them `0600`, written through `write_json`, so the
backup, quarantine and symlink rules above apply to each record. A record lives in `escalations/`
only while it is `pending`; the move to `escalations/settled/` happens under the pending
directory's lock when it settles, so the scan the inbox repeats reads only the live pauses.

1. `next_escalation_seq()` MUST increment the counter under the directory's lock and return the new
   value. The first value is `1`; two calls never return the same value, whichever process makes
   them.
2. `write_escalation(escalation)` MUST give a record whose `seq` is `0` the next `seq`, keep the
   stored `seq` of a record already written, persist it in the directory its `state` names (and
   remove its copy in the other directory, so a record is never in both), and return the record as stored. An `id`
   that is not `esc-` plus twelve lower-case hex characters cannot be built (the model refuses
   it), so it never becomes a filename.
3. `read_escalation(id)` MUST return the record wherever it lives, pending or settled, or `None` for
   a malformed id, an absent file or a file that is not a valid `Escalation`; a settled record is
   still found by id until retention removes it.
4. `list_escalations(state=None, since_seq=None)` MUST return the valid records ordered by `seq`,
   keeping only those in `state` when given and only those with `seq` strictly greater than
   `since_seq` when given. It MUST skip the counter, a stray file and an invalid record rather than
   fail. With `state="pending"` it MUST open no file under `escalations/settled/`; with any other
   state it MUST open no pending file.
5. `mark_escalation_applied(id, at)` MUST stamp `resolution.appliedAt` with `at` on a record in
   state `resolved` whose `appliedAt` is unset, under the record's lock, and return whether it did;
   a record of any other state, one already stamped and an absent one are left as they are
   (`False`), so two callers racing to apply one resolution see exactly one `True`.
6. `settle_escalation(id, state)` MUST move the pending record *id* to `state` under the record's
   lock and return whether it was moved. A record
   that is no longer `pending` is left as it is. A record settled by `settle_escalation` or by
   `resolve_escalation` leaves `escalations/` for `escalations/settled/`, keeping its `seq`.
7. `prune_settled_escalations(retention_s=None, dry_run=False, now=None)` MUST delete the files under
   `escalations/settled/` whose modification time is older than the retention window (default
   `Home.trace_retention_s`, the knob that bounds traces) and return the count removed (or, under
   `dry_run`, that would be). A `resolved` record whose `appliedAt` is unset is kept whatever its
   age, because the task's claim has not applied it yet. A pending record is never touched, and the
   counter file is never deleted, so a `seq` is never handed out twice. The `serve` sweep that
   expires traces MUST call it.

## Validation

The behavioral matrix uses temporary registries created by two real `write_json` calls:

| Initial state | Public action | Result | Durable oracle |
| --- | --- | --- | --- |
| Valid primary; stale or malformed backup | `read_json` | Current object | Every existing data-file byte is identical |
| Malformed primary; valid backup | `read_json` | Previous complete object | Primary is valid `0600` JSON; one quarantine holds the exact malformed bytes; no `.tmp` |
| Malformed runs registry (`docket-runs.json`); valid backup | `docket task prune --traces --dry-run` | Prior complete run list | The real CLI-to-core-to-store path performs the same recovery |
| Malformed primary; missing or malformed backup | `read_json` | Typed actionable failure | All input bytes and file presence are unchanged; no quarantine or `.tmp` is invented |
| Two readers released at one barrier | concurrent `read_json` | Both receive the prior object | Exactly one bounded quarantine and one complete primary remain |
| Five records settled, one pending | `list_escalations(state="pending")` | Only the pending record | No file under `escalations/settled/` is opened; `read_escalation` still finds a settled id |
| Settled records older than the window, one resolved but not applied | `prune_settled_escalations` | The old applied or expired records are gone | The unapplied one and the pending one remain; the next `seq` continues the counter |
| Reader and locked mutation released at one barrier | `read_json` plus `read_modify_write` | Mutation completes without deadlock | Final primary is the complete mutated object; backup is never malformed; no `.tmp` |

Concurrency validation performs twenty in-test repetitions and gives every repetition an isolated
directory. Tests must fail on the unrecovered malformed primary rather than on collection or
fixture setup.

## Examples

Given these files:

```text
state.json         {broken
state.json.bak     {"generation": 1}
```

`read_json(Path("state.json"))` returns `{"generation": 1}`, restores that object to
`state.json`, and leaves the exact bytes `{broken` in `state.json.corrupt`.

## Implementation

- `src/docket/platform/store.py`: `read_json`, `write_json`, `read_modify_write`, `StoreRecoveryError`,
  `next_escalation_seq`, `write_escalation`, `read_escalation`, `list_escalations`,
  `settle_escalation`, `resolve_escalation`, `mark_escalation_applied`, `prune_settled_escalations`
- `src/docket/interfaces/cli/commands/task.py`: the `docket task prune` command, which reads the run registry through the store
