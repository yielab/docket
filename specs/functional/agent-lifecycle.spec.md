# Agent Lifecycle Specification

**Version**: 2.1.0
**Status**: Complete
**Last Updated**: 2026-10-18

## Purpose

This specification defines the complete lifecycle of docket agents from creation to deletion, including all state transitions and operations.

## Scope

This specification covers:
- Agent creation (`docket init` creates a project pod; `docket pod add` adds role agents to an
  existing pod and never creates a project)
- Pod display (`docket pod show`)
- Member removal and reset (`docket pod remove`, `docket pod reset`)
- Pod deletion (`docket pod delete`)

This specification does NOT cover:
- Agent communication (see telegram-integration.spec.md)
- Pipeline definitions (see pipeline-format.spec.md; the retired Lobster YAML surface is gone per ROADMAP D-16)
- Pod delegation and dispatch (see pod-dispatch.spec.md)
- Blueprint selection/composition (which roster, workspace kind, default pipeline, and default
  budget a pod is provisioned with) — see the new pod-blueprints.spec.md (ROADMAP Phase 16 W-7).
  This spec covers the creation/display/removal/reset/deletion lifecycle common to every pod
  member regardless of which blueprint provisioned it.

## Requirements

### Agent Creation (docket init)

1. **MUST** create a unique agent identifier
2. **MUST** validate the codebase path exists, for a `codebase`-kind blueprint (`software`, the
   default). A `workdir`-kind blueprint (`research`/`content`/`ops`) has no codebase to validate
   and instead auto-provisions its shared working directory when none is given (see
   pod-blueprints.spec.md)
3. **MUST** create isolated workspace directory
4. **MUST** generate session key for project isolation
5. **MUST** initialize configuration files (SOUL.md, AGENTS.md, HEARTBEAT.md, and — for a
   standalone agent or a pod Implementer with allocated resources/a verify command — TOOLS.md;
   see workspace-structure.spec.md for the exact per-role file set)
6. **MUST** register agent in docket's fleet registry (`fleet.json`; ROADMAP Phase 19 P19-6 — see
   ../data/docket-meta.spec.md's "Sync contract (retired)" for what this replaced)
7. **MUST** set appropriate file permissions (700 for dirs, 600 for files)
8. **SHOULD** auto-detect project stack (`codebase`-kind blueprints only)
9. **SHOULD** suggest appropriate model profile based on project type
10b. **MUST NOT** bootstrap the workstation home. When `cli/_setup.py::readiness()` reports no model
   endpoint, it **MUST** still build the team and end with a `No model endpoint yet` warning and the
   single next step `docket setup`; the endpoint, baseline policies and security posture are
   `docket setup`'s (api/cli-interface.spec.md).
10. **MAY** initialize with custom description
11. **MUST** stamp the active template version into agent metadata so prompt drift is detectable
12. **MAY** provision one or more agents declaratively from a spec file (`docket init --from <file>`)
13. **MUST** select a pod blueprint (`--blueprint <name>`, default `software`) before provisioning
    and **MUST** fail cleanly, before any interactive prompt, if the name is not registered (see
    pod-blueprints.spec.md)

#### Declarative Provisioning (docket init --from)

1. **MUST** accept a JSON spec; **SHOULD** accept YAML when a YAML parser is available
2. **MUST** support a list of agents, a `{agents: [...]}` mapping, or a single agent mapping
3. **MUST** apply the same defaults as interactive creation (id slugified from name,
   default model, stack auto-detection) and require only a `name`
4. **MUST** be idempotent: an agent whose workspace already exists is skipped, not recreated
5. **MUST** skip invalid records without aborting the rest of the spec file
6. *(Retired.)* ~~**SHOULD** restart the gateway at most once per invocation~~ — docket has no
   gateway process (ROADMAP D-19), so provisioning restarts nothing
7. **MAY** carry a `blueprint` field on any entry, provisioning a pod (see pod-blueprints.spec.md)
   instead of the single flat agent described by requirements 1–6 above; an entry with no
   `blueprint` field is entirely unaffected by this option's existence

### Agent States

An agent is either **registered** (workspace + `.docket-meta.json` + a `fleet.json` entry all
present) or **deleted**. There is no separate stopped state; the docket-local `paused` flag
(cost-tracking.spec.md) marks an agent that dispatch must refuse, without unregistering it.

### Pod Information (docket pod show)

`docket pod show [member] [--json]` **MUST** display, for the pod:
1. The pod name and, per member, its id, role and model with where the model comes from (`policy`,
   or `pod overlay` when the pod's own role overlay defines the role)
2. Each implementer's `verifyCmd`
3. Every pod setting with its value and source (`set` or `default`), the approval mode the
   dispatcher will resolve for this caller (`core.dispatch.pod_approval_mode`), the pipeline
   source and the network mode and scope
4. `configSource`, `configDigest` and `drift` when the pod was applied from a directory

`docket pod show <member>` **MUST** display that member's whole effective configuration: workspace
path, role, model, endpoint readiness, provider, composed prompt sections, allowed and denied
tools, MCP servers, applicable policies, skills, project instructions and exporters. A name that
is not a member of the pod **MUST** exit 1. A pod whose stored settings are invalid **MUST**
refuse (exit 1, the key named) and never show a default in its place. The command **MUST NOT**
write anything.

### Member Removal (docket pod remove)

1. **MUST** confirm: on a terminal a `y/N` prompt; off a terminal it **MUST** exit 1 naming
   `--yes` and change nothing
2. **MUST** refuse the pod's Lead (exit 1, "delete the pod instead"), leaving the pod unchanged
3. **MUST** refuse an id that is not a member of the pod
4. **MUST** deregister the member from `fleet.json`, remove its workspace and its task
   worktrees (requirement 9 of Pod Deletion applies to its branch), write one `pod.remove` audit
   entry, and free the pod's runtime resources when it was the last implementer

### Member Reset (docket pod reset)

1. **MUST** confirm exactly as `pod remove` does
2. **MUST NOT** call a model: there is no distillation turn (ADR 0028 point 7; the daily-log
   pipeline it served had no writer in a pod task)
3. **MUST NOT** read, move, delete or clear `memory/`, `MEMORY.md` (the operator's notes) or the
   pod's `memory.json` (workspace-structure.spec.md "Pod memory"); a pod's learned memory is
   decided per entry, never by a member reset
4. **MUST** reset HEARTBEAT.md. For a pod Lead the reset also clears the docket-owned
   dispatch ledger region, so the ledger and `TASK_LIST.json` disagree until the next dispatch
   event or `docket setup --fix` re-syncs it
5. **MUST** rebuild SOUL.md, AGENTS.md and (for an implementer with resources or a verify command)
   TOOLS.md from the member's metadata, and stamp the template version. It **MUST NOT** touch
   `INSTRUCTIONS.md`, `.docket-meta.json`, the fleet registration or the session keys
6. **MUST** write one `pod.reset` audit entry

### Pod Deletion (docket pod delete)

1. **MUST** require the pod's name: typed at a prompt on a terminal, or `--confirm <name>` off one.
   Off a terminal without `--confirm`, or with a `--confirm` that is not the pod's name, it **MUST**
   exit 1 naming `--confirm <name>` and delete nothing. There is no picker, and an agent or member
   id is refused as "not a pod"
2. **MUST** remove the workspace directory completely for every pod member
3. **MUST** unregister from docket's fleet registry (`fleet.json`)
4. **MUST** remove any Telegram bindings and conversation-registry entries
5. **SHOULD** display a deletion summary before asking
6. Deleting a pod **MUST** tear down every pod member and free the pod's
   allocated resources (port range, scratch dir)
7. Deleting a pod **MUST** remove its Docket-owned runtime directory, durable session histories,
   and JSONL trace directories for both the project id and its member ids. It **MUST NOT** delete
   or rewrite the global audit log; the deletion record remains as durable evidence.
8. The pre-deletion summary **MUST** list each member with its role.
9. An Implementer's git-worktree branch **MUST** be deleted at member teardown only when it is
   fully merged into the codebase's current branch (`edges/adapters/system.py`'s
   `git_branch_merged` against `git_current_branch(codebase)`, deleted with `git_branch_delete`'s
   `-d`, never `-D`). An unmerged branch, or a missing/failing git, **MUST** be left in place; the
   caller prints a one-line manual `git branch -D <branch>` note naming it rather than losing the
   work silently. A worktree-remove failure **MUST NOT** block workspace/fleet cleanup either way.
10. Deleting a pod **MUST** write one `pod.delete` audit entry.
11. Pod-level provisioning state **MUST NOT** outlive the pod: `free_pod_resources` (whole-pod
    teardown) **MUST** remove that project's `.pod-provision-locks/<hex>/` directory, once its own
    lock is released (never while held).

## Interface Contracts

### CLI Command Signatures

```bash
# Create a project pod from a blueprint; with no arguments the id, path and stack come
# from the cwd. --blueprint defaults to `software`. --pod full/--with apply only to it.
docket init [<project>] [location] [--blueprint <name>] [--pod full | --with reviewer,tester]

# Create one or more agents (or, with a `blueprint` field, pods) declaratively
# from a spec file (JSON, or YAML when PyYAML is present)
docket init --from <agents.yaml|agents.json>

# The roster. The pod comes from --pod, DOCKET_POD, then the current directory.
docket pod show [<member-id>] [--json]
docket pod add <role> [--count N] [--verify "<cmd>"]
docket pod remove <member-id> [--yes]
docket pod reset <member-id> [--yes]
docket pod delete [--confirm <pod>]
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown agent, invalid arguments, permission problems, driver failures —
  docket's CLI-wide convention; see ../api/cli-interface.spec.md)
- `2`: A usage error — an unknown option, command or verb (Click)

## Examples

### Creating a Project Pod

```bash
$ docket init mywebsite ~/projects/website
→ Provisioning 'software' pod 'mywebsite' (lead, implementer)...
✓   mywebsite-lead  [lead]  anthropic/claude-haiku-4-5
✓   mywebsite-implementer  [implementer]  anthropic/claude-sonnet-4-6

✓ Pod 'mywebsite' created with 2 members!
```

### Resetting a Member

```bash
$ docket pod reset mywebsite-implementer --yes
✓ Reset mywebsite-implementer: ledger cleared, workspace files rebuilt
→ Next: docket pod show
```

## Validation

### Pre-conditions
- User **MUST** have write permissions to `~/.docket`.
- Python 3.11+ **MUST** be available (docket's runtime requirement)

### Post-conditions
After successful creation:
- Workspace directory **MUST** exist at expected path
- All core files **MUST** be present and valid
- Agent **MUST** appear in `docket status` output
- Agent **MUST** be registered in docket's fleet registry (`fleet.json`)

### Invariants
- Agent IDs **MUST** be unique across system
- Session keys **MUST** follow format: `agent:<id>:<project>`
- Workspace permissions **MUST** be 700 for directories, 600 for files
- Model and session key **MUST** exist in exactly one place: `.docket-meta.json` (ROADMAP Phase 19
  P19-6 — `fleet.json` tracks the bare registration fact only, never a copy of either field; see
  ../data/docket-meta.spec.md's "Sync contract (retired)")

## Error Handling

### Common Errors and Recovery

| Error | Cause | Recovery |
|-------|-------|----------|
| Agent already exists | Duplicate ID | Use different ID or delete existing |
| Codebase not found | Invalid path | Verify path exists |
| Permission denied | Insufficient rights | Check ~/.docket permissions |
| Workspace corrupted | Missing files | Run `docket setup --fix`, or `docket pod reset <member>` to rebuild its files |

## Performance Criteria

- Agent creation: < 2 seconds
- Agent listing: < 500ms for 100 agents
- Pod deletion: < 1 second
- Member reset: a local file operation, no model call
