# Team Coordination Specification

**Version**: 2.0.0
**Status**: Implemented
**Last Updated**: 2026-06-24

## Purpose

This specification defines docket's `team` surface: the **org manager's shared task queue**.
`docket team` delegates work to the Manager agent and tracks each task through its lifecycle.
Specialist/pod health and rosters are out of scope here — those are covered by `docket list`,
`docket doctor`, and `docket pod <project>`.

## Scope

This specification covers:

- Queuing a task for the manager (`docket team delegate`)
- Listing pending tasks (`docket team queue`, `--all`)
- Transitioning a task (`docket team start` / `done` / `cancel`)
- The shared task store (`TASK_LIST.json`)

This specification does NOT cover:

- Specialist/pod rosters or health (see `docket list`, `docket doctor`, `docket pod`)
- Autonomous task execution by specialists (out of scope for the queue)
- Workflow pipelines (see workflow-integration.spec.md)

## Requirements

### Manager and task store

1. The manager agent **MUST** own a shared task list at
   `~/.openclaw/workspaces/manager/TASK_LIST.json`.
2. The manager **MUST NOT** edit project code directly; it only plans and delegates.
3. Each task **MUST** carry a stable id, a description, a priority, and a state.

### Delegate (docket team delegate)

1. **MUST** append a new task to `TASK_LIST.json` with state `pending`.
2. **MUST** accept an optional `--priority` (e.g. `high`); priority **SHOULD** default to a
   normal level when omitted.
3. **MUST** return the new task's id so it can be referenced later.

### Queue (docket team queue)

1. **MUST** list tasks that are not yet complete, showing id, priority, and description.
2. **SHOULD** accept `--all` to include completed and cancelled tasks.

### Transition (docket team start / done / cancel)

1. `start` **MUST** transition the referenced task to state `in_progress`.
2. `done` **MUST** transition the referenced task to state `complete`.
3. `cancel` **MUST** transition the referenced task to state `cancelled`.
4. Each **MUST** return "not found" if the task id does not exist.

## Interface Contracts

### CLI Command Signatures

```bash
docket team delegate "<task>" [--priority high]     # Queue a task for the manager
docket team queue [--all]                            # Show pending (or all) tasks
docket team start <task-id>                          # Mark a task in progress
docket team done <task-id>                           # Mark a task complete
docket team cancel <task-id>                         # Cancel a task
```

### Return Codes

- `0`: Success
- `2`: Task id or manager not found
- `4`: Missing task description

## Examples

### Delegating and completing a task

```bash
$ docket team delegate "Fix the login bug" --priority high
[SUCCESS] Queued task T-014 (priority: high)

$ docket team queue
T-014  high    Fix the login bug
T-013  normal  Update API docs

$ docket team done T-014
[SUCCESS] Task T-014 marked complete
```

## Validation

### Pre-conditions

- The manager agent **MUST** exist (created during `docket install`).
- For `delegate`, a non-empty task description **MUST** be supplied.

### Post-conditions

- After `delegate`, `TASK_LIST.json` **MUST** contain the new `pending` task.
- After `done`, the referenced task's state **MUST** be `complete`.

### Invariants

- Task ids **MUST** be unique within `TASK_LIST.json`.
- The manager agent **MUST** remain delegation-only and never gain code-edit tools.

## Changelog

### Version 2.0.0 (2026-06-24)

- Reframed `team` as the org manager's task queue only (pod model retired the legacy
  specialist-coordination surface)
- Removed `docket team status`; specialist/pod health now lives in `docket list`,
  `docket doctor`, and `docket pod <project>`
- Documented `--all`, `start`, and `cancel` task transitions
- Status: Implemented

### Version 1.0.0 (2026-06-09)

- Initial team coordination specification
- Documented the task-queue contract; marked richer routing as future work
