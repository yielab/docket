# Agent Lifecycle Specification

**Version**: 3.0.0
**Status**: Complete. Pods and their members are created, shown, added to, reset, removed and
deleted as described below; `docket init --from` provisions pods from a spec file (see
Declarative Provisioning).
**Last Updated**: 2026-10-22

## Purpose

This specification defines the lifecycle of docket agents from creation to deletion: a project pod
and its members are created, shown, extended, reset, shrunk and deleted.

## Scope

This specification covers:
- Pod creation (`docket init` creates a project pod; `docket pod add` adds role members to an
  existing pod and never creates a project)
- Declarative provisioning (`docket init --from`)
- Pod display (`docket pod show`)
- Member addition, removal and reset (`docket pod add`, `docket pod remove`, `docket pod reset`)
- Pod deletion (`docket pod delete`)

This specification does NOT cover:
- Agent communication (see telegram-integration.spec.md)
- Pipeline definitions (see pipeline-format.spec.md)
- Pod delegation and dispatch (see pod-dispatch.spec.md)
- Blueprint selection and composition (which roster, workspace kind, default pipeline and default
  budget a pod is provisioned with) — see pod-blueprints.spec.md. This spec covers the
  creation, display, addition, removal, reset and deletion lifecycle common to every pod member
  regardless of which blueprint provisioned it.

## Requirements

### Pod Creation (docket init)

1. **MUST** create a unique pod identifier: the slug of the project name argument (or of the
   current directory's name), refusing with exit 1 when a project or pod with that id already
   exists, and with exit 2, before anything is created, when the slug is empty or longer than 64
   characters (input-validation.spec.md section 1). `docket init` asks nothing interactively
2. **MUST** take the codebase (for a `codebase`-kind blueprint, `software` by default) or the
   working directory (for a `workdir`-kind blueprint: `research`/`content`/`ops`) from the
   `location` argument, defaulting to the current directory, and **MUST** store it absolute (a
   relative path is taken from the current directory). A `codebase` that is not an existing
   directory is refused with exit 2 before anything is created; `docket init` does not check that
   it is a git repository. A `workdir` location is created when missing, and provisioning
   **MUST NOT** change the mode of a working directory it did not create. A
   `--from` entry for a `workdir`-kind blueprint with no `workDir` auto-provisions the pod's own
   working directory (see pod-blueprints.spec.md)
3. **MUST** create an isolated workspace directory for every member
4. **MUST** give every member of a pod the session key `agent:<pod>:<projectKey>` (`projectKey`
   defaults to `default`); the key is metadata, and dispatch derives its per-task history keys
   from it
5. **MUST** initialize configuration files per member: SOUL.md, AGENTS.md, HEARTBEAT.md,
   MEMORY.md, WORKFLOW_AUTO.md and a `memory/` directory, plus TOOLS.md for an Implementer with
   allocated resources or a verify command (see workspace-structure.spec.md for the exact
   per-role file set)
6. **MUST** register every member in docket's fleet registry (`fleet.json`), which holds the bare
   registration fact (the member id) and nothing else
7. **MUST** set file permissions 700 for directories and 600 for files
8. **SHOULD** auto-detect the project stack (`codebase`-kind blueprints only; `unknown` when no
   marker file is found)
9. **SHOULD** give each member the model the role-to-model policy resolves for its role at
   provisioning time, shown in the creation output (model-profiles.spec.md)
10. **MUST NOT** bootstrap the workstation home. When no model endpoint is ready, `docket init`
    **MUST** still build the team and end with a `No model endpoint yet` warning and the single
    next step `docket setup`; the endpoint, baseline policies and security posture are
    `docket setup`'s (api/cli-interface.spec.md)
11. **MAY** initialize a pod with a custom description, only through a `--from` entry's
    `description` field; `docket init` has no description option
12. **MUST** stamp the active template version into each member's metadata so prompt drift is
    detectable
13. **MAY** provision one or more pods declaratively from a spec file
    (`docket init --from <file>`)
14. **MUST** select a pod blueprint (`--blueprint <name>`, default `software`) before
    provisioning and **MUST** fail cleanly with exit 1, before anything is created, if the name is
    not registered (see pod-blueprints.spec.md)

#### Declarative Provisioning (docket init --from)

`--from` excludes every other option and argument of `docket init`.

1. **MUST** accept a JSON spec; a file ending in `.yaml` or `.yml` is read as YAML
2. **MUST** support a list of entries, a `{agents: [...]}` mapping, or a single entry mapping
3. **MUST** require an `id` on every entry; an entry without one is skipped with a warning. The
   id is not derived from a `name`
4. **MUST** be idempotent: an entry whose pod already has members is skipped with a warning, not
   recreated
5. **MUST** skip an entry with an unknown blueprint, an invalid pod id, an unusable location or an
   existing target without aborting the rest of the spec file; an invalid pod id makes the command
   exit 1 once every entry has been processed
6. **MAY** carry a `telegram` field on any entry, binding the pod's Lead to that Telegram group
7. **MUST** carry a `blueprint` field on every entry; the entry provisions a pod (see
   pod-blueprints.spec.md) with its `codebase` (or `workDir` for a `workdir`-kind blueprint),
   `stack`, `description`, `projectKey` and `budgetUsd`. An entry with no `blueprint` is refused
   and nothing is created for it, and a location that is not usable is refused the same way; the
   command exits 2 once every entry has been processed

### Agent States

A pod member is either **registered** (workspace + `.docket-meta.json` + a `fleet.json` entry all
present) or **deleted**. There is no separate stopped state; the `paused` flag
(cost-tracking.spec.md), kept in the pod Lead's `.docket-meta.json`, makes dispatch refuse the pod
without unregistering anyone.

### Pod Information (docket pod show)

`docket pod show [member] [--json]` **MUST** display, for the pod:
1. The pod name and, per member, its id, role and model with where the model comes from (`policy`,
   or `pod overlay` when the pod's own role overlay defines the role)
2. Each implementer's `verifyCmd`
3. Every pod setting with its value and source (`set` or `default`), the approval mode the
   dispatcher will resolve for this caller, the pipeline source and the network mode and scope
4. `configSource`, `configDigest` and `drift` when the pod was applied from a directory

`docket pod show <member>` **MUST** display that member's whole effective configuration: workspace
path, role, model, endpoint readiness, provider, composed prompt sections, allowed and denied
tools, MCP servers, applicable policies, skills, project instructions and exporters. A name that
is not a member of the pod **MUST** exit 1. A pod whose stored settings are invalid **MUST**
refuse (exit 1, the key named) and never show a default in its place. The command **MUST NOT**
write anything.

### Member Addition (docket pod add)

`docket pod add <role> [--count N] [--verify "<cmd>"]`:
1. **MUST** refuse with exit 1 a pod that does not exist and a role that is not a known role
   archetype (the message lists the valid roles)
2. **MUST** add `--count` members (default 1), numbering ids after the existing members of that
   role (`<pod>-reviewer`, `<pod>-reviewer-2`, ...), each registered like a creation member
3. **MUST** have each new member inherit the pod's codebase, stack, description, working directory
   and blueprint from an existing member
4. **MUST** allocate the pod's port range and scratch directory when the new member is an
   Implementer (reusing the allocation when it exists); `--verify` applies to Implementers only
   and is ignored with a warning for any other role
5. **MUST** write one `pod.add` audit entry naming the pod, the role and the new member ids

### Member Removal (docket pod remove)

1. **MUST** confirm: on a terminal a `y/N` prompt; off a terminal it **MUST** exit 1 naming
   `--yes` and change nothing
2. **MUST** refuse the pod's Lead (exit 1, "delete the pod instead"), leaving the pod unchanged
3. **MUST** refuse an id that is not a member of the pod
4. **MUST** deregister the member from `fleet.json`, remove its workspace and its task
   worktrees (requirement 9 of Pod Deletion applies to its branch), write one `pod.remove` audit
   entry, and, when it was the last implementer, release the pod's port range and remove its
   scratch and cache directories. It **MUST NOT** remove the pod's `memory.json`, its `config/`
   directory or its working directory

### Member Reset (docket pod reset)

1. **MUST** confirm exactly as `pod remove` does
2. **MUST NOT** call a model: there is no distillation turn (ADR 0028)
3. **MUST NOT** read, move, delete or clear `memory/`, `MEMORY.md` (the operator's notes) or the
   pod's `memory.json` (workspace-structure.spec.md "Pod memory"); a pod's learned memory is
   decided per entry, never by a member reset
4. **MUST** replace HEARTBEAT.md with a fresh ledger. For a pod Lead this also drops the
   docket-owned dispatch ledger region, so the ledger and `TASK_LIST.json` disagree until the next
   dispatch event or `docket setup --fix` re-syncs it
5. **MUST** rebuild SOUL.md, AGENTS.md and (for an implementer with resources or a verify command)
   TOOLS.md from the member's metadata, and stamp the template version in `.docket-meta.json`. It
   **MUST NOT** touch `INSTRUCTIONS.md`, any other `.docket-meta.json` field, the fleet
   registration or the session keys
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
   fully merged into the codebase's current branch (checked with `git branch --merged`, deleted
   with `git branch -d`, never `-D`). An unmerged branch, or a missing/failing git, **MUST** be
   left in place; the caller prints a one-line manual `git branch -D <branch>` note naming it
   rather than losing the work silently. A worktree-remove failure **MUST NOT** block
   workspace/fleet cleanup either way.
10. Deleting a pod **MUST** write one `pod.delete` audit entry.
11. Pod-level provisioning state **MUST NOT** outlive the pod: whole-pod teardown **MUST** remove
    that project's `workspaces/.pod-provision-locks/<hex of the pod name>/` directory, once its own
    lock is released (never while held).

## Interface Contracts

### CLI Command Signatures

```bash
# Create a project pod from a blueprint; with no arguments the id and path come from the cwd and
# the stack from the code there. --blueprint defaults to `software`. --pod full/--with apply only
# to it. The recipe and apply options are pod-blueprints.spec.md's.
docket init [<project>] [location] [--blueprint <name>] [--pod full | --with reviewer,tester]

# Provision one or more pods declaratively from a spec file; excludes every other option
docket init --from <agents.yaml|agents.json>

# The roster. The pod comes from --pod/-p, DOCKET_POD, then the current directory.
docket pod show [<member-id>] [--json] [--pod <pod>]
docket pod add <role> [--count N] [--verify "<cmd>"] [--pod <pod>]
docket pod remove <member-id> [--yes] [--pod <pod>]
docket pod reset <member-id> [--yes] [--pod <pod>]
docket pod delete [--confirm <pod>] [--pod <pod>]
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown member, invalid arguments, a refused confirmation, permission problems —
  docket's CLI-wide convention; see ../api/cli-interface.spec.md)
- `2`: A usage error — an unknown option, command or verb (Click)

## Examples

### Creating a Project Pod

```bash
$ docket init mywebsite ~/projects/website
-> Provisioning 'software' pod 'mywebsite' (lead, implementer)...
ok   mywebsite-lead  [lead]  anthropic/claude-haiku-4-5
ok   mywebsite-implementer  [implementer]  anthropic/claude-sonnet-4-6

ok Pod 'mywebsite' created with 2 members!
```

### Resetting a Member

```bash
$ docket pod reset mywebsite-implementer --yes
ok Reset mywebsite-implementer: ledger cleared, workspace files rebuilt
-> Next: docket pod show
```

## Validation

### Pre-conditions
- User **MUST** have write permissions to `DOCKET_HOME` (`~/.docket` by default).
- Python 3.11+ **MUST** be available (docket's runtime requirement)

### Post-conditions
After successful creation:
- Every member's workspace directory **MUST** exist at the expected path
- All core files **MUST** be present and valid
- The pod **MUST** appear in `docket status --all`
- Every member **MUST** be registered in docket's fleet registry (`fleet.json`)

### Invariants
- Member ids **MUST** be unique across the system
- A pod member's session key **MUST** follow the format `agent:<pod>:<projectKey>`
- Workspace permissions **MUST** be 700 for directories, 600 for files
- A member's model and session key **MUST** exist in exactly one place: its `.docket-meta.json`;
  `fleet.json` tracks the bare registration fact only, never a copy of either field

## Error Handling

### Common Errors and Recovery

| Error | Cause | Recovery |
|-------|-------|----------|
| A project or pod already exists | Duplicate id | Use a different name or delete the existing pod |
| Unknown blueprint / unknown pod role | Name not registered | Use one of the valid names the message lists |
| Not a member of the pod | Wrong member id or pod | `docket pod show` lists the members |
| Needs confirmation | Off a terminal without `--yes` / `--confirm <pod>` | Re-run with the flag the message names |
| Permission denied | Insufficient rights | Check `DOCKET_HOME` permissions |
| Workspace corrupted | Missing files | Run `docket setup --fix`, or `docket pod reset <member>` to rebuild its files |

## Implementation

Where the names above live today; the only place this spec names a path.

- `src/docket/cli/_agents.py`: `run_init`, `InitRequest`, `cmd_init`, the declarative path
  (`_cmd_add_declarative`, `_provision_pod_from_spec`), `_stored_location`
- `src/docket/cli/_pod.py`: `cmd_show`, `cmd_add`, `cmd_remove`, `cmd_reset`, `cmd_delete`,
  `add_members`, `remove_member`, `reset_member`, `build_pod_from_blueprint`
- `src/docket/cli/_contract.py`: `confirm`
- `src/docket/core/pod_provisioning.py`: `provision_pod`, `provision_members`, `teardown_member`,
  `allocate_pod_resources`, `release_implementer_resources`, `free_pod_resources`, `purge_pod_history`, `rendered_member_files`,
  `POD_TEMPLATE_VERSION`
- `src/docket/core/pod.py`: `session_key`, `plan_added_member`, `normalize_role`
- `src/docket/core/pod_report.py`: `pod_report`, `member_report`
- `src/docket/core/provisioning.py`: `slugify`, `validate_project_id`, `detect_stack`
- `src/docket/core/dispatch.py`: `pod_approval_mode`
- `src/docket/core/fleet.py`: `fleet.json` registration, bindings
- `src/docket/core/conversations.py`: `remove_agent_durable`
- `src/docket/edges/adapters/system.py`: `git_current_branch`, `git_branch_merged`,
  `git_branch_delete`
