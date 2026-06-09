# Workspace Structure Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-09

## Purpose

This specification defines the on-disk layout of an agent workspace: the files rack creates,
their roles, and the permission and synchronization rules that keep a workspace valid.

## Scope

This specification covers:

- The directory and files that make up a project-agent workspace
- The special manager-agent layout
- Permission and metadata-sync invariants

This specification does NOT cover the `.rack-meta.json` field schema in detail
(see ../data/rack-meta.spec.md).

## Requirements

### Project-agent workspace

1. Each agent **MUST** have a workspace at
   `~/.openclaw/workspaces/projects/<agent-id>/` containing:
   - `SOUL.md` — agent identity, scope, and session key
   - `AGENTS.md` — session protocol and delegation rules
   - `TOOLS.md` — project-specific commands
   - `HEARTBEAT.md` — active tasks/decisions for proactive monitoring
   - `.rack-meta.json` — rack metadata (see data spec)
   - `memory/` — daily logs named `YYYY-MM-DD.md`
2. A `workflows/` directory **MAY** exist for Lobster pipelines.
3. Repo agents and task agents **MUST** use different templates: repo agents have a codebase
   path and auto-detected stack; task agents have a work directory and no fixed codebase.

### Permissions

1. Workspace directories **MUST** be `700`.
2. Workspace files **MUST** be `600`.

### Manager agent

1. The manager workspace at `~/.openclaw/workspaces/manager/` **MUST** contain
   `TASK_LIST.json` (the shared task queue).
2. The manager **MUST** operate in delegation mode and **MUST NOT** be able to edit code.

### Synchronization

1. `.rack-meta.json` and `openclaw.json` **MUST** stay synchronized for each agent.

## Interface Contracts

Workspaces are created and repaired through commands, not edited by hand:

```bash
rack add <agent-id> [codebase-path]     # Provision a workspace
rack maintain <agent-id> check          # Verify/repair structure and permissions
rack maintain <agent-id> rebuild        # Regenerate all files from metadata
```

## Examples

### A provisioned repo-agent workspace

```text
~/.openclaw/workspaces/projects/mywebsite/
├── SOUL.md
├── AGENTS.md
├── TOOLS.md
├── HEARTBEAT.md
├── .rack-meta.json
├── memory/
│   └── 2026-06-09.md
└── workflows/
```

## Validation

### Pre-conditions

- `~/.openclaw` **MUST** be writable.

### Post-conditions

- After `rack add`, all required core files **MUST** exist with `700`/`600` permissions.
- After `rack maintain rebuild`, core files **MUST** be regenerated from metadata.

### Invariants

- Directory permissions **MUST** be `700` and file permissions `600`.
- The manager agent **MUST** never hold code-edit tools.

## Changelog

### Version 1.0.0 (2026-06-09)

- Initial workspace-structure specification
- Documented the project and manager layouts, permissions, and sync invariants
