# Session Scoping Specification

**Version**: 4.0.1
**Status**: Complete
**Last Updated**: 2026-10-23

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
trace contract (see `pod-dispatch.spec.md`).

## Requirements

### Session key

1. Every agent's metadata **MUST** have a base session key of the form `agent:<id>:<project>`,
   where `<id>` is the pod's name.
2. The `<project>` component **MUST** equal the agent's `projectKey` field.
3. The default project key **MUST** be `default`.
4. `sessionKey` and `projectKey` **MUST** be stored in the agent's `.docket-meta.json`, docket's
   source of truth. Provisioning writes both. No command changes either value afterwards; a pod
   apply writes back the values it read. There is no daemon registry or secondary configuration
   mirror.
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

Provisioning writes `sessionKey` and `projectKey` into the metadata of each pod member it
creates, at pod provisioning and pod apply.
No public command reads the base key as a history key, and no command sets it: the pod settings
command rejects both `sessionKey` and `projectKey` as unknown settings.

## Examples

### A pod member's derived key

The Lead of pod `mywebsite` (default project key):

```json
{"projectKey": "default", "sessionKey": "agent:mywebsite:default"}
```

## Validation

### Invariants

- `sessionKey` **MUST** always equal `agent:<id>:<projectKey>`, with `<id>` as defined in
  requirement 1 of "Session key".
- Nothing after provisioning mutates a pod task's derived step-history or trace identity.

## Implementation

- `src/docket/teams/pod.py`: `session_key`, `PodMember.session_key`, `PodSettings.KEYS`
- `src/docket/teams/pod_provisioning.py`: `provision_member` (writes `sessionKey` and `projectKey` for each pod member)
- `src/docket/teams/apply/plan.py`: pod apply reads `projectKey` from the Lead and re-derives each member's key
- `src/docket/hops/application/runner.py`: `step_session_key` (the per-hop durable history key)
- `src/docket/teams/fleet.py`: `meta_set` (generic metadata write; no caller sets either key)
- `src/docket/teams/models.py`: `AgentMeta.session_key`, `AgentMeta.project_key`
