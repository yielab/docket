# Agent Lifecycle Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2024-01-20

## Purpose

This specification defines the complete lifecycle of rack agents from creation to deletion, including all state transitions and operations.

## Scope

This specification covers:
- Agent creation (`rack add`)
- Agent listing (`rack list`)
- Agent information display (`rack info`)
- Agent deletion (`rack delete`)
- Agent reset operations (`rack reset`)
- Agent repair operations (`rack repair`)

This specification does NOT cover:
- Agent communication (see telegram.spec.md)
- Agent workflows (see workflow.spec.md)
- Team coordination (see team-coordination.spec.md)

## Requirements

### Agent Creation (rack add)

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

### Agent Listing (rack list)

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

### Agent Information (rack info)

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

### Agent Deletion (rack delete)

1. **MUST** prompt for confirmation unless --force flag
2. **MUST** remove workspace directory completely
3. **MUST** unregister from openclaw.json
4. **MUST** remove any Telegram bindings
5. **SHOULD** display deletion summary
6. **MUST NOT** delete if agent has active tasks (unless --force)

### Agent Reset (rack reset)

Three levels **MUST** be supported:

#### Level 1 (Default) - Memory Logs
- Clear `memory/*.md` daily logs
- Preserve SOUL.md, AGENTS.md, TOOLS.md
- Preserve session and project keys
- Preserve .rack-meta.json

#### Level 2 - Deep Memory
- Everything from Level 1
- Clear MEMORY.md summary
- Clear HEARTBEAT.md tasks
- Reset conversation context

#### Level 3 - Complete Reset
- Everything from Level 2
- Regenerate SOUL.md from metadata
- Regenerate AGENTS.md from template
- Regenerate TOOLS.md from stack
- Generate new session key
- Reset project key to default

### Agent Repair (rack repair)

**MUST** check and fix:
1. Missing workspace directory → recreate
2. Missing core files → regenerate from templates
3. Invalid permissions → reset to 700/600
4. Corrupted metadata → restore from openclaw.json
5. Missing openclaw registration → re-register
6. Orphaned Telegram bindings → clean up

## Interface Contracts

### CLI Command Signatures

```bash
# Create agent
rack add <agent-id> [codebase-path] [--type repo|task] [--model economy|standard|premium] [--description "text"]

# List agents
rack list [--format table|json|csv] [--filter active|stopped|all]

# Show agent info
rack info <agent-id> [--format detailed|summary|json]

# Delete agent
rack delete <agent-id> [--force] [--keep-logs]

# Reset agent
rack reset <agent-id> [level] # level: 1|2|3

# Repair agent
rack repair <agent-id> [--check-only]
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
$ rack add mywebsite ~/projects/website
[INFO] Creating agent: mywebsite
[INFO] Type: repo (detected)
[INFO] Stack: node (detected: package.json)
[INFO] Workspace: ~/.openclaw/workspaces/projects/mywebsite
[INFO] Session key: agent:mywebsite:default
[SUCCESS] Agent 'mywebsite' created and registered
```

### Resetting an Agent

```bash
$ rack reset mywebsite 2
[WARN] Level 2 reset will clear memory and tasks
Continue? (y/N): y
[INFO] Clearing memory logs...
[INFO] Resetting MEMORY.md...
[INFO] Clearing HEARTBEAT.md...
[SUCCESS] Agent 'mywebsite' reset (level 2)
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
- Agent **MUST** appear in `rack list` output
- Agent **MUST** be registered in openclaw.json

### Invariants
- Agent IDs **MUST** be unique across system
- Session keys **MUST** follow format: `agent:<id>:<project>`
- Workspace permissions **MUST** be 700 for directories, 600 for files
- Metadata **MUST** be synchronized between .rack-meta.json and openclaw.json

## Error Handling

### Common Errors and Recovery

| Error | Cause | Recovery |
|-------|-------|----------|
| Agent already exists | Duplicate ID | Use different ID or delete existing |
| Codebase not found | Invalid path | Verify path exists |
| Permission denied | Insufficient rights | Check ~/.openclaw permissions |
| Workspace corrupted | Missing files | Run `rack repair` |
| Daemon not running | OpenClaw down | Start with `systemctl --user start openclaw-gateway` |

## Performance Criteria

- Agent creation: < 2 seconds
- Agent listing: < 500ms for 100 agents
- Agent deletion: < 1 second
- Reset Level 1: < 500ms
- Reset Level 3: < 3 seconds
- Repair operation: < 5 seconds

## Changelog

### Version 1.0.0 (2024-01-20)
- Initial complete specification
- Full lifecycle operations defined
- Error handling and validation rules
- Performance criteria established