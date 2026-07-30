# Agent Lifecycle Specification

**Version**: 1.3.1
**Status**: Complete
**Last Updated**: 2026-07-30

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
- Pipeline definitions (see pipeline-format.spec.md; `docket workflow`, the retired Lobster YAML
  surface it replaced, is gone per ROADMAP D-16 — see cli-interface.spec.md's Pipeline Commands
  section)
- Pod delegation and dispatch (see pod-dispatch.spec.md)

## Requirements

### Agent Creation (docket add)

1. **MUST** create a unique agent identifier
2. **MUST** validate the codebase path exists
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
3. **MUST** apply the same defaults as interactive creation (id slugified from name,
   default model, stack auto-detection) and require only a `name`
4. **MUST** be idempotent: an agent whose workspace already exists is skipped, not recreated
5. **MUST** skip invalid records without aborting the rest of the spec file
6. **SHOULD** restart the gateway at most once per invocation, after all agents are provisioned

### Agent States

An agent is either **registered** (workspace + metadata + openclaw.json entry all present)
or **deleted**. There is no separate stopped state; the docket-local `paused` flag
(cost-tracking.spec.md) marks an agent that dispatch must refuse, without unregistering it.

### Agent Listing (docket list)

Output **MUST** include:
- Agent ID (slugified, unique)
- Kind/scope (project agent vs org specialist; pod role where applicable)
- Codebase path (if applicable)
- Current model and source (policy or pinned)
- Telegram binding status
- Session key / project scope

The exact table rendering is pinned by the golden suite; the machine-readable shape by
../data/cli-json-shapes.spec.md.

### Agent Information (docket info)

**MUST** display:
1. Agent identifier
2. Kind/scope (and pod role where applicable)
3. Workspace path
4. Codebase path (if set)
5. Detected stack (if set)
6. Current model and profile
7. Session key
8. Project key
9. Memory usage (log count and size)
10. Telegram binding status
11. Cost metrics (tokens and dollars)
12. Creation timestamp
13. Last activity timestamp

### Agent Deletion (docket delete)

1. **MUST** prompt for confirmation (interactive; there is no `--force` bypass flag)
2. **MUST** remove workspace directory completely
3. **MUST** unregister from openclaw.json
4. **MUST** remove any Telegram bindings and conversation-registry entries
5. **SHOULD** display deletion summary
6. Deleting a pod project **MUST** tear down every pod member and free the pod's
   allocated resources (port range, scratch dir)

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
# Create a project pod (interactive or with args)
docket add <project> [codebase-path] [--pod full | --with reviewer,tester] [--model <id>] [--count N]

# Create one or more agents declaratively from a spec file (JSON, or YAML when PyYAML is present)
docket add --from <agents.yaml|agents.json>

# List agents
docket list [--json]

# Show agent info
docket info <agent-id> [--json]

# Delete agent (or a whole pod, by project name)
docket delete <agent-id>

# Maintain agent (replaces reset/repair/cleanup)
docket maintain <agent-id> [check|clean|reset|rebuild|sessions]
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown agent, invalid arguments, permission problems, daemon failures —
  docket's CLI-wide convention; see ../api/cli-interface.spec.md)

## Examples

### Creating a Project Agent

```bash
$ docket add mywebsite ~/projects/website
[INFO] Creating agent: mywebsite
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
- Python 3.11+ **MUST** be available (docket's runtime requirement)

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

### Version 1.3.1 (2026-07-30)
- Retargeted the "does NOT cover" workflow cross-reference at pipeline-format.spec.md — the old
  `docket workflow` / Lobster surface it named (workflow-integration.spec.md) was retired per
  ROADMAP D-16 (Phase 16 W-3); that spec file was deleted.

### Version 1.3.0 (2026-07-30)
- Truth pass (Platformization baseline): removed every remnant of the deleted repo/task
  dual-type model (`--type` flag, `type` field validation, per-type template MUSTs — the
  `type` field no longer exists); fixed the header version (was 1.0.0 while the changelog
  said 1.2.0); replaced the fictional return codes 2–7 with the real 0/1 convention;
  corrected `list`/`info`/`delete` signatures to the shipped flags (`--json` only; no
  `--format/--filter/--force/--keep-logs`); replaced the Created/Active/Stopped state
  diagram with the real registered/deleted + docket-local `paused` model; retargeted the
  team-coordination cross-reference at pod-dispatch.spec.md.

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