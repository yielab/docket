# Session Scoping Specification

**Version**: 2.0.0
**Status**: Complete
**Last Updated**: 2026-08-19

## Purpose

This specification defines the base session scope stored in an agent's docket-owned metadata and
how that base coordinate relates to the step-scoped histories used by pod dispatch. A session key
isolates durable context; a trace key groups audit events and is not implicitly a history key.

## Scope

This specification covers:

- The session-key format and its relationship to the project key
- Showing, setting, and resetting an agent's scope (`docket scope`)
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
   truth. There is no daemon registry or secondary configuration mirror.
5. A pod-dispatch step **MUST NOT** overwrite this base key. It derives a task-and-step-specific
   durable key from member, project, task, and pipeline `step_id` as defined by
   `pod-dispatch.spec.md`.

### Scope operations (docket scope)

1. `show` **MUST** display the current session and project keys (default action).
2. `set <project-key>` **MUST** update both the session key and project key in agent metadata.
3. `reset` **MUST** return the agent to the `default` project key.
4. A scope change **MUST** be audit-logged as `scope.set` or `scope.reset`.
5. A scope change **MUST NOT** delete any history stored under the previous base key or under a
   task's step-scoped key.

### Isolation guarantee

1. Two base keys, or two pod-dispatch step keys, **MUST NOT** share durable message history.
2. Changing scope **MUST NOT** delete existing memory; it switches the active context.
3. Distinct pipeline steps **MUST** remain isolated even when they target the same member or role;
   cross-step context travels through the typed handoff contract, not a shared durable replay.
4. A task-wide trace identity **MAY** group events from several isolated step histories without
   granting any step access to another step's stored messages.

## Interface Contracts

### CLI Command Signatures

```bash
docket scope <agent-id> show           # Show current session/project key
docket scope <agent-id> set <project>  # Switch to a project context
docket scope <agent-id> reset          # Return to the default context
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown agent, invalid action or project key — CLI-wide convention,
  see ../api/cli-interface.spec.md)

## Examples

### Switching project context

```bash
$ docket scope mywebsite set alpha
[SUCCESS] Session scope updated: default → alpha
[SUCCESS] Session key: agent:mywebsite:alpha
[INFO] Update SOUL.md to reflect the new scope if needed.

$ docket scope mywebsite reset
[SUCCESS] Scope reset to 'default' for 'mywebsite'
```

## Validation

### Pre-conditions

- The target agent **MUST** exist.
- For `set`, a project-key argument **MUST** be supplied and valid.

### Post-conditions

- After `set`, `sessionKey` and `projectKey` in `.docket-meta.json` **MUST** reflect the new
  project.
- After `reset`, the project key **MUST** be `default`.
- Existing durable session files **MUST** remain readable after either operation.

### Invariants

- `sessionKey` **MUST** always equal `agent:<id>:<projectKey>`.
- A metadata scope change **MUST NOT** mutate a pod task's derived step-history or trace identity.

## Changelog

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
