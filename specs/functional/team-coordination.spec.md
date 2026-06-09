# Team Coordination Specification

**Version**: 1.0.0
**Status**: Partial
**Last Updated**: 2026-06-09

## Purpose

This specification defines rack's team-coordination surface: a manager agent and a shared
task queue that let work be delegated to specialist agents. The current implementation is a
task queue; richer routing is tracked as future work.

## Scope

This specification covers:

- Showing team status (`rack team status`)
- Queuing a task for the manager (`rack team delegate`)
- Listing pending tasks (`rack team queue`)
- Marking a task complete (`rack team done`)
- The shared task store (`TASK_LIST.json`)

This specification does NOT cover:

- Autonomous task execution by specialists (out of scope for the queue)
- Workflow pipelines (see workflow-integration.spec.md)

## Requirements

### Manager and task store

1. The manager agent **MUST** own a shared task list at
   `~/.openclaw/workspaces/manager/TASK_LIST.json`.
2. The manager **MUST NOT** edit project code directly; it only plans and delegates.
3. Each task **MUST** carry a stable id, a description, a priority, and a state.

### Delegate (rack team delegate)

1. **MUST** append a new task to `TASK_LIST.json` with state `pending`.
2. **MUST** accept an optional `--priority` (e.g. `high`); priority **SHOULD** default to a
   normal level when omitted.
3. **MUST** return the new task's id so it can be referenced later.

### Queue (rack team queue)

1. **MUST** list tasks that are not yet complete, showing id, priority, and description.

### Done (rack team done)

1. **MUST** transition the referenced task to state `complete`.
2. **MUST** return "not found" if the task id does not exist.

### Status (rack team status)

1. **MUST** show the specialist roster and a summary of outstanding tasks.

## Interface Contracts

### CLI Command Signatures

```bash
rack team status                                  # Specialist health + task summary
rack team delegate "<task>" [--priority high]     # Queue a task for the manager
rack team queue                                   # Show pending tasks
rack team done <task-id>                           # Mark a task complete
```

### Return Codes

- `0`: Success
- `2`: Task id or manager not found
- `4`: Missing task description

## Examples

### Delegating and completing a task

```bash
$ rack team delegate "Fix the login bug" --priority high
[SUCCESS] Queued task T-014 (priority: high)

$ rack team queue
T-014  high    Fix the login bug
T-013  normal  Update API docs

$ rack team done T-014
[SUCCESS] Task T-014 marked complete
```

## Validation

### Pre-conditions

- The manager agent **MUST** exist (created during `rack install`).
- For `delegate`, a non-empty task description **MUST** be supplied.

### Post-conditions

- After `delegate`, `TASK_LIST.json` **MUST** contain the new `pending` task.
- After `done`, the referenced task's state **MUST** be `complete`.

### Invariants

- Task ids **MUST** be unique within `TASK_LIST.json`.
- The manager agent **MUST** remain delegation-only and never gain code-edit tools.

## Changelog

### Version 1.0.0 (2026-06-09)

- Initial team coordination specification
- Documented the task-queue contract; marked richer routing as future work
