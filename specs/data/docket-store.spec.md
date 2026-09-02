# Docket JSON Store Specification

**Version**: 1.0.0
**Status**: Implemented
**Last updated**: 2026-09-02

## Purpose

Define the durability and recovery contract for Docket-owned JSON documents. A malformed primary
must not make a valid single-generation backup unusable, and recovery must not hide the malformed
bytes that explain the incident.

## Scope

This specification covers JSON objects read and written through `docket.edges.store`, including
the public `read_json` and `write_json` functions and the locked `read_modify_write` transition.
It does not cover append-only JSONL audit or trace files, missing-primary repair, schema migration,
remote backups, or a general filesystem backup service.

## Structure

For a primary path `state.json`, the store owns these bounded siblings:

| Path | Purpose | Retention |
| --- | --- | --- |
| `state.json` | Current JSON object | One current generation |
| `state.json.bak` | Previous complete JSON object | One generation, replaced by a later valid write |
| `state.json.corrupt` | Exact malformed primary bytes retained during recovery | One generation, replaced only by a later recovery |
| `state.json.tmp` | Same-directory atomic-write staging | Must not remain after success or failure |

The primary and quarantine files MUST have mode `0600` after successful recovery. The backup is
valid recovery input only when it is UTF-8 JSON whose top-level value is an object.

## Schema

Recovery does not add, remove, or reinterpret document fields. The recovered primary has exactly
the object semantics of the backup. The quarantine is opaque diagnostic bytes rather than JSON.

`read_json(path)` follows this state machine while holding the existing per-directory store lock:

1. A missing primary returns `{}` and does not restore a backup.
2. A valid primary returns its object without changing primary, backup, or quarantine bytes, even
   when the backup is stale or malformed.
3. A malformed primary with a valid backup preserves the malformed bytes in the fixed quarantine,
   atomically restores the backup object to the primary, and returns that object.
4. A malformed primary with a missing or malformed backup raises `StoreRecoveryError`. The error
   identifies the primary and backup and describes why recovery cannot proceed. It changes no
   primary, backup, quarantine, or temporary-file bytes.

Backup validation completes before recovery writes begin. If a later filesystem write fails, the
operation raises that I/O error: the malformed primary and valid backup remain intact, the bounded
quarantine may already contain the current malformed bytes, and no temporary file remains. A retry
can therefore perform the same recovery without inventing empty state.

Only one lock owner may inspect recovery inputs, quarantine bytes, restore the primary, or perform
the following write. `read_modify_write` MUST use the same lock boundary without reacquiring the
non-reentrant directory lock. Concurrent readers therefore observe one recovery winner, while a
concurrent locked mutation preserves one complete generation and cannot rotate malformed bytes
over the valid backup.

## Validation

The behavioral matrix uses temporary registries created by two real `write_json` calls:

| Initial state | Public action | Result | Durable oracle |
| --- | --- | --- | --- |
| Valid primary; stale or malformed backup | `read_json` | Current object | Every existing data-file byte is identical |
| Malformed primary; valid backup | `read_json` | Previous complete object | Primary is valid `0600` JSON; one quarantine holds the exact malformed bytes; no `.tmp` |
| Malformed runs primary; valid backup | `docket runs list --json` | Prior complete run list | The real CLI-to-core-to-store path performs the same recovery |
| Malformed primary; missing or malformed backup | `read_json` | Typed actionable failure | All input bytes and file presence are unchanged; no quarantine or `.tmp` is invented |
| Two readers released at one barrier | concurrent `read_json` | Both receive the prior object | Exactly one bounded quarantine and one complete primary remain |
| Reader and locked mutation released at one barrier | `read_json` plus `read_modify_write` | Mutation completes without deadlock | Final primary is the complete mutated object; backup is never malformed; no `.tmp` |

Concurrency validation performs twenty deterministic in-test repetitions and gives every
repetition an isolated directory. Tests must fail on the unrecovered malformed primary rather
than on collection or fixture setup.

## Examples

Given these files:

```text
state.json         {broken
state.json.bak     {"generation": 1}
```

`read_json(Path("state.json"))` returns `{"generation": 1}`, restores that object to
`state.json`, and leaves the exact bytes `{broken` in `state.json.corrupt`.

## Changelog

### 1.0.0 — 2026-09-02

- Define locked corrupt-primary recovery, bounded quarantine retention, typed failure atomicity,
  real CLI consumption, and concurrent reader/writer oracles. Implemented at the shared JSON-store
  chokepoint.
