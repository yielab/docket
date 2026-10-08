# Session Scoping Specification

**Version**: 3.0.0
**Status**: Complete
**Last Updated**: 2026-10-07

## Purpose

This specification defines the base session scope stored in an agent's docket-owned metadata and
how that base coordinate relates to the step-scoped histories used by pod dispatch. A session key
isolates durable context; a trace key groups audit events and is not implicitly a history key.

## Scope

This specification covers:

- The session-key format and its relationship to the project key
- How base scoped sessions coexist with pod-dispatch step histories

This specification does NOT cover the workspace file layout (see `workspace-structure.spec.md`),
session serialization/compaction (see `session-history.spec.md`), or the complete pipeline-key and
trace contract (see `pod-dispatch.spec.md` W20-C4).

## Requirements

### Session key

1. Every agent's metadata **MUST** have a base session key of the form
   `agent:<id>:<project>`.
2. The `<project>` component **MUST** equal the agent's `projectKey` field.
3. The default project key **MUST** be `default`.
4. `sessionKey` and `projectKey` **MUST** be stored in `.docket-meta.json`, docket's source of
   truth, written once by provisioning. No command changes them afterwards. There is no daemon
   registry or secondary configuration mirror.
5. A pod-dispatch step **MUST NOT** overwrite this base key. It derives a task-and-step-specific
   durable key from member, project, task, and pipeline `step_id` as defined by
   `pod-dispatch.spec.md`.

### Isolation guarantee

1. Two base keys, or two pod-dispatch step keys, **MUST NOT** share durable message history.
2. Distinct pipeline steps **MUST** remain isolated even when they target the same member or role;
   cross-step context travels through the typed handoff contract, not a shared durable replay.
3. A task-wide trace identity **MAY** group events from several isolated step histories without
   granting any step access to another step's stored messages.

## Interface Contracts

No command reads or writes the session key. It is a metadata field provisioning writes once.

## Examples

### A derived key

```json
{"projectKey": "default", "sessionKey": "agent:mywebsite-lead:default"}
```

## Validation

### Invariants

- `sessionKey` **MUST** always equal `agent:<id>:<projectKey>`.
- Nothing after provisioning mutates a pod task's derived step-history or trace identity.

## Changelog

### Version 3.0.0 (2026-10-07)

- Removed the operator-set scope: there is no command that shows, sets or resets an agent's
  project key, and no `scope.set`/`scope.reset` audit entry. The derived `agent:<id>:<project>`
  key provisioning writes stands unchanged.

### Version 2.0.1 (2026-09-18)

- The `reset` example now shows the output `docket scope ... reset` actually prints
  (`src/docket/cli/__init__.py`). No behavior change.

### Version 2.0.0 (2026-08-19)

- **Wave 20, card W20-C4 truth cleanup.** Removed the retired daemon mirror/restart contract,
  distinguished the metadata base key from pod-dispatch step-history and task-trace keys, and
  documented non-destructive compatibility with existing sessions.

### Version 1.0.1 (2026-07-30)

- Truth pass (Platformization baseline): return codes corrected to the real 0/1
  convention (the spec'd codes 2/4 never existed).

### Version 1.0.0 (2026-06-09)

- Initial session-scoping specification
- Defined session-key format, scope operations, and isolation guarantee
