# Workflow Integration Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-09

## Purpose

This specification defines how rack manages Lobster workflows — deterministic YAML pipelines
stored per agent that allow repeatable, token-efficient execution of multi-step tasks.

## Scope

This specification covers:

- Creating a workflow template (`rack workflow <id> create <name>`)
- Listing an agent's workflows (`rack workflow <id> list`)
- Displaying a workflow (`rack workflow <id> show <name>`)
- Deleting a workflow (`rack workflow <id> delete <name>`)
- The on-disk location and structure of workflow files

This specification does NOT cover:

- The Lobster execution engine itself (owned by OpenClaw)
- Cross-agent orchestration (see team-coordination.spec.md)

## Requirements

### Workflow storage

1. Workflows **MUST** live under the agent's workspace at
   `~/.openclaw/workspaces/projects/<id>/workflows/<name>.yaml`.
2. The `workflows/` directory **MUST** be created on demand if absent.
3. File permissions **MUST** follow the project convention (700 dirs, 600 files).

### Create (rack workflow create)

1. **MUST** generate a valid Lobster YAML template named after the provided workflow name.
2. **MUST** refuse to overwrite an existing workflow of the same name unless explicitly
   confirmed.
3. **SHOULD** include commented placeholders for steps so the file is editable immediately.

### List / Show / Delete

1. `list` **MUST** enumerate all workflows defined for the agent.
2. `show` **MUST** print the raw YAML of the named workflow.
3. `delete` **MUST** remove the named workflow file and confirm removal.
4. `show` and `delete` **MUST** return "not found" when the named workflow does not exist.

### Naming

1. Workflow names **MUST** be slugified to a filesystem-safe form.
2. The `name` argument **MUST** be required for `create`, `show`, and `delete`.

## Interface Contracts

### CLI Command Signatures

```bash
rack workflow <agent-id> create <name>   # Generate a new Lobster template
rack workflow <agent-id> list            # List the agent's workflows
rack workflow <agent-id> show <name>     # Print a workflow's YAML
rack workflow <agent-id> delete <name>   # Remove a workflow
```

### Return Codes

- `0`: Success
- `2`: Agent or workflow not found
- `3`: Workflow already exists (on create)
- `4`: Missing required name argument

## Examples

### Creating and listing a workflow

```bash
$ rack workflow mywebsite create deploy
[INFO] Creating workflow 'deploy' for agent 'mywebsite'
[SUCCESS] Workflow created: workflows/deploy.yaml

$ rack workflow mywebsite list
deploy
release-notes
```

### Showing a workflow

```bash
$ rack workflow mywebsite show deploy
name: deploy
steps:
  - run: echo "configure steps here"
```

## Validation

### Pre-conditions

- The target agent **MUST** exist.
- For `create`, a workflow `name` **MUST** be supplied.

### Post-conditions

- After `create`, a readable `<name>.yaml` **MUST** exist in the agent's `workflows/` dir.
- After `delete`, the named workflow file **MUST NOT** exist.

### Invariants

- Workflow files **MUST** be valid YAML parseable by the Lobster engine.
- A workflow name **MUST** be unique within a single agent.

## Changelog

### Version 1.0.0 (2026-06-09)

- Initial workflow integration specification
- Defined create/list/show/delete contract and on-disk layout
