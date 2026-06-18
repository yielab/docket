# Agent Lifecycle Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2024-01-20

## Purpose

This specification defines the complete lifecycle of docket agents from creation to deletion, including all state transitions and operations.

## Scope

This specification covers:
- Agent creation (`docket add`)
- Agent listing (`docket list`)
- Agent information display (`docket info`)
- Agent deletion (`docket delete`)
- Agent maintenance operations (`docket maintain`)

This specification does NOT cover:
- Agent communication (see telegram-integration.spec.md)
- Agent workflows (see workflow-integration.spec.md)
- Team coordination (see team-coordination.spec.md)

## Requirements

### Agent Creation (docket add)

1. **MUST** create a unique agent identifier
2. **MUST** validate codebase path exists (for repo agents)
3. **MUST** create isolated workspace directory
4. **MUST** generate session key for project isolation
5. **MUST** initialize configuration files (SOUL.md, AGENTS.md, TOOLS.md, HEARTBEAT.md)
6. **MUST** register agent in openclaw.json
7. **MUST** set appropriate file permissions (700 for dirs, 600 for files)
8. **SHOULD** auto-detect project stack
9. **SHOULD** suggest appropriate model profile based on project type
10. **MAY** initialize with custom description
11. **MUST** stamp the active template version into agent metadata so prompt drift is detectable
12. **MAY** provision one or more agents declaratively from a spec file (`docket add --from <file>`)

#### Declarative Provisioning (docket add --from)

1. **MUST** accept a JSON spec; **SHOULD** accept YAML when a YAML parser is available
2. **MUST** support a list of agents, a `{agents: [...]}` mapping, or a single agent mapping
3. **MUST** apply the same defaults as interactive creation (id slugified from name, `task`
   type, default model, stack auto-detection for repo agents) and require only a `name`
4. **MUST** be idempotent: an agent whose workspace already exists is skipped, not recreated
5. **MUST** validate the `type` field (`repo`|`task`) and skip invalid records without aborting
6. **SHOULD** restart the gateway at most once per invocation, after all agents are provisioned

### Agent States

An agent **MUST** be in exactly one of these states:

```
┌─────────┐
│ Created │──────┐
└────┬────┘      │
     │           ▼
     ▼      ┌─────────┐
┌────────┐  │ Deleted │
│ Active │  └─────────┘
└────┬───┘       ▲
     │           │
     ▼           │
┌─────────┐      │
│ Stopped │──────┘
└─────────┘
```

### Agent Listing (docket list)

Output **MUST** include:
- Agent ID (slugified, unique)
- Agent type (repo/task/specialist)
- Codebase path (if applicable)
- Model profile (economy/standard/premium)
- Status indicator (active/stopped/error)
- Last activity timestamp

Format:
```
ID            Type        Codebase                   Model      Status    Last Active
myproject     repo        ~/code/myproject           standard   active    2 hours ago
blog-writer   task        ~/.openclaw/.../blog       economy    active    3 days ago
programmer    specialist  -                          premium    active    1 hour ago
```

### Agent Information (docket info)

**MUST** display:
1. Agent identifier
2. Agent type
3. Workspace path
4. Codebase path (if repo agent)
5. Detected stack (if repo agent)
6. Current model and profile
7. Session key
8. Project key
9. Memory usage (log count and size)
10. Telegram binding status
11. Cost metrics (tokens and dollars)
12. Creation timestamp
13. Last activity timestamp

### Agent Deletion (docket delete)

1. **MUST** prompt for confirmation unless --force flag
2. **MUST** remove workspace directory completely
3. **MUST** unregister from openclaw.json
4. **MUST** remove any Telegram bindings
5. **SHOULD** display deletion summary
6. **MUST NOT** delete if agent has active tasks (unless --force)

### Agent Maintenance (docket maintain)

`docket maintain [agent-id] [mode]` consolidates the retired `reset`, `repair`, and `cleanup`
commands. Five modes **MUST** be supported, in increasing order of impact.

#### check (Default) - Health and Auto-fix
- Verify and fix missing workspace directory → recreate
- Regenerate missing core files from templates
- Reset invalid permissions to 700/600
- Restore corrupted metadata from openclaw.json
- Re-register a missing openclaw registration
- Clean up orphaned Telegram bindings

#### clean - Memory Logs
- Clear `memory/*.md` daily logs
- Preserve SOUL.md, AGENTS.md, TOOLS.md
- Preserve session and project keys
- Preserve .docket-meta.json

#### reset - Deep Memory
- Everything from `clean`
- Clear MEMORY.md summary
- Clear HEARTBEAT.md tasks
- Reset conversation context

#### rebuild - Complete Rebuild
- Everything from `reset`
- Regenerate SOUL.md from metadata
- Regenerate AGENTS.md from template
- Regenerate TOOLS.md from stack
- Generate new session key
- Reset project key to default

#### sessions - Session Hygiene
- Archive large or old session data
- Preserve all configuration and identity files

`reset` and `rebuild` are destructive and **MUST** prompt for confirmation unless forced.

## Interface Contracts

### CLI Command Signatures

```bash
# Create agent (interactive)
docket add <agent-id> [codebase-path] [--type repo|task] [--model economy|standard|premium] [--description "text"]

# Create one or more agents declaratively from a spec file (JSON, or YAML when PyYAML is present)
docket add --from <agents.yaml|agents.json>

# List agents
docket list [--format table|json|csv] [--filter active|stopped|all]

# Show agent info
docket info <agent-id> [--format detailed|summary|json]

# Delete agent
docket delete <agent-id> [--force] [--keep-logs]

# Maintain agent (replaces reset/repair/cleanup)
docket maintain <agent-id> [check|clean|reset|rebuild|sessions]
```

### Return Codes

- `0`: Success
- `1`: General error
- `2`: Agent not found
- `3`: Agent already exists
- `4`: Invalid arguments
- `5`: Permission denied
- `6`: Workspace corruption
- `7`: OpenClaw daemon error

## Examples

### Creating a Repository Agent

```bash
$ docket add mywebsite ~/projects/website
[INFO] Creating agent: mywebsite
[INFO] Type: repo (detected)
[INFO] Stack: node (detected: package.json)
[INFO] Workspace: ~/.openclaw/workspaces/projects/mywebsite
[INFO] Session key: agent:mywebsite:default
[SUCCESS] Agent 'mywebsite' created and registered
```

### Maintaining an Agent

```bash
$ docket maintain mywebsite reset
[WARN] 'reset' will clear memory and tasks
Continue? (y/N): y
[INFO] Clearing memory logs...
[INFO] Resetting MEMORY.md...
[INFO] Clearing HEARTBEAT.md...
[SUCCESS] Agent 'mywebsite' maintained (reset)
```

## Validation

### Pre-conditions
- OpenClaw daemon **MUST** be running
- User **MUST** have write permissions to ~/.openclaw
- Python 3.7+ **MUST** be available for JSON operations

### Post-conditions
After successful creation:
- Workspace directory **MUST** exist at expected path
- All core files **MUST** be present and valid
- Agent **MUST** appear in `docket list` output
- Agent **MUST** be registered in openclaw.json

### Invariants
- Agent IDs **MUST** be unique across system
- Session keys **MUST** follow format: `agent:<id>:<project>`
- Workspace permissions **MUST** be 700 for directories, 600 for files
- Metadata **MUST** be synchronized between .docket-meta.json and openclaw.json

## Error Handling

### Common Errors and Recovery

| Error | Cause | Recovery |
|-------|-------|----------|
| Agent already exists | Duplicate ID | Use different ID or delete existing |
| Codebase not found | Invalid path | Verify path exists |
| Permission denied | Insufficient rights | Check ~/.openclaw permissions |
| Workspace corrupted | Missing files | Run `docket maintain check` |
| Daemon not running | OpenClaw down | Start with `systemctl --user start openclaw-gateway` |

## Performance Criteria

- Agent creation: < 2 seconds
- Agent listing: < 500ms for 100 agents
- Agent deletion: < 1 second
- Maintain (clean): < 500ms
- Maintain (rebuild): < 3 seconds
- Maintain (check): < 5 seconds

## Changelog

### Version 1.2.0 (2026-06-11)
- Added template-version stamping requirement (drift surfaced in `docket doctor`)
- Added declarative provisioning (`docket add --from <file>`): JSON/YAML specs, fleet lists,
  idempotent re-apply, shared defaults with interactive creation

### Version 1.1.0 (2026-06-09)
- Replaced the retired `docket reset`/`docket repair` with `docket maintain` and its five modes
- Updated interface signatures, examples, and recovery steps to match the shipped CLI

### Version 1.0.0 (2024-01-20)
- Initial complete specification
- Full lifecycle operations defined
- Error handling and validation rules
- Performance criteria established