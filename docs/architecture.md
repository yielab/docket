# Architecture Documentation

Comprehensive guide to rack's internal architecture, design decisions, and extension points.

## Overview

rack is a **single-file Bash CLI** (~2600 lines) that manages OpenClaw autonomous agents through a dual-source configuration model. It prioritizes:

- **Simplicity**: Pure Bash, no compilation or dependencies beyond Python 3
- **Maintainability**: Clear separation of concerns with marked sections
- **Extensibility**: Easy to add new commands and features
- **Safety**: Defensive coding with permission controls and approval gates

## System Architecture

```
┌────────────────────────────────────────────────────────────┐
│                        User Interface                       │
│  CLI Commands (rack add, rack list, rack cost, etc.)      │
└──────────────────┬─────────────────────────────────────────┘
                   │
┌──────────────────┴─────────────────────────────────────────┐
│                    Configuration Layer                      │
│  ┌──────────────────────┐    ┌────────────────────────┐  │
│  │  .rack-meta.json     │◄──►│  openclaw.json         │  │
│  │  (per-project)       │    │  (global daemon)       │  │
│  │  - name, type        │    │  - agents.list[]       │  │
│  │  - model, stack      │    │  - bindings[]          │  │
│  │  - sessionKey        │    │  - security config     │  │
│  └──────────────────────┘    └────────────────────────┘  │
└──────────────────┬─────────────────────────────────────────┘
                   │
┌──────────────────┴─────────────────────────────────────────┐
│                    Workspace Layer                          │
│  ~/.openclaw/workspaces/projects/<agent-id>/               │
│  ├── SOUL.md          ← Identity + session key             │
│  ├── AGENTS.md        ← Delegation rules                   │
│  ├── TOOLS.md         ← Project commands                   │
│  ├── HEARTBEAT.md     ← Active tasks                       │
│  ├── .rack-meta.json  ← Metadata                           │
│  ├── memory/          ← Daily logs (YYYY-MM-DD.md)         │
│  └── workflows/       ← Lobster pipelines (.lobster.yml)   │
└────────────────────────────────────────────────────────────┘
                   │
┌──────────────────┴─────────────────────────────────────────┐
│                   OpenClaw Daemon                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  openclaw-gateway.service (systemd)                 │  │
│  │  - Routes messages to agents via sessionKey         │  │
│  │  - Enforces tool approval gates                     │  │
│  │  - Logs to audit trail                              │  │
│  └─────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Command Router

Location: `bin/rack` lines 2550-2583

The router dispatches commands to their handlers with alias support:

```bash
case "$CMD" in
  install|setup)     cmd_install ;;
  list)              cmd_list ;;
  add|create|new)    cmd_add ;;
  info|show)         cmd_info "$ARG" ;;
  # ... more commands
esac
```

**Design Decision**: Case statement over function table for clarity and grep-ability.

### 2. Metadata Management

#### Dual-Source Strategy

rack maintains two configuration sources that must stay synchronized:

1. **`.rack-meta.json`** (per-project)
   - Source of truth for rack CLI
   - Stored in workspace directory
   - Contains: name, type, codebase, stack, model, sessionKey, projectKey
   - Managed via `meta_get()` and `meta_set()` helpers

2. **`openclaw.json`** (global)
   - Source of truth for OpenClaw daemon
   - Located at `~/.openclaw/openclaw.json`
   - Contains: agents.list[], bindings[], security config
   - Modified via embedded Python scripts

**Sync Functions**:
- `meta_get()` / `meta_set()`: Read/write project metadata
- `sync_session_key()`: Propagate session keys to openclaw.json
- `restart_gateway()`: Apply changes to running daemon

### 3. Session Scoping

**Purpose**: Prevent agents from mixing information across projects

**Implementation**:

```bash
# Session key format: agent:<id>:<project>
generate_session_key() {
  local id="$1"
  local project_key="${2:-default}"
  echo "agent:${id}:${project_key}"
}
```

**Flow**:
1. User runs: `rack scope myproject set alpha`
2. rack updates `.rack-meta.json` with new sessionKey
3. rack calls `sync_session_key()` to write to `openclaw.json`
4. rack embeds session key in `SOUL.md` for agent awareness
5. rack calls `restart_gateway()` to reload config
6. Agent reads session key from SOUL.md and respects boundary

### 4. Team Coordination

**Manager Agent Architecture**:

```
Manager (agent:manager:orchestrator)
├── Role: Orchestration only (no code editing)
├── Files:
│   ├── SOUL.md           ← Delegation rules
│   ├── AGENTS.md         ← Mailbox protocol
│   ├── TOOLS.md          ← Task management commands
│   ├── HEARTBEAT.md      ← 30-min check interval
│   └── TASK_LIST.json    ← Shared task queue
└── Delegation:
    ├── programmer → Code implementation
    ├── reviewer → Code review
    ├── tester → Testing
    ├── knowledge → Memory/patterns
    └── security → Security audits
```

**Task List Format**:
```json
{
  "tasks": [
    {
      "id": "task-001",
      "description": "Implement user authentication",
      "assignedTo": "programmer",
      "status": "pending|in_progress|blocked|completed",
      "priority": "high|medium|low",
      "dependencies": ["task-000"],
      "created": "2026-02-25T10:00:00Z"
    }
  ],
  "lastUpdated": "2026-02-25T12:00:00Z"
}
```

### 5. Lobster Workflow Integration

**Deterministic Execution Model**:

Lobster workflows save tokens by avoiding re-planning for each step:

```yaml
name: ci-pipeline
description: "Continuous integration pipeline"

steps:
  - id: check-status
    type: shell              # Zero tokens (pure shell)
    command: |
      cd /path/to/project
      git status --short

  - id: run-tests
    type: shell              # Zero tokens
    command: |
      cd /path/to/project
      npm test
    continueOnError: false

  - id: llm-analysis
    type: llm                # Consumes tokens
    prompt: |
      Analyze test results and suggest fixes.
    approval: required       # Pause for human approval

  - id: apply-fixes
    type: shell              # Zero tokens
    command: |
      # Apply automated fixes
      npm run fix

outputs:
  - testResults
  - analysis

notifications:
  onComplete: telegram
  onError: telegram
```

**Token Savings**: ~90% for pipelines with mostly shell steps

### 6. Security Sentinel

**Defense Layers**:

1. **Tool Approval Gates**
   ```json
   {
     "tools": {
       "approval": {
         "enabled": true,
         "requireApprovalFor": [
           "rm", "git push", "docker stop",
           "kubectl delete", "npm publish"
         ],
         "notificationChannel": "telegram"
       }
     }
   }
   ```

2. **Workspace Isolation**
   ```json
   {
     "security": {
       "workspaceAccess": {
         "mode": "isolated",
         "allowCrossProject": false
       }
     }
   }
   ```

3. **Audit Logging**
   ```json
   {
     "security": {
       "auditLog": {
         "enabled": true,
         "path": "/tmp/openclaw/audit.log"
       }
     }
   }
   ```

4. **Permission Model**
   - Workspace directories: 700 (owner only)
   - Workspace files: 600 (owner read/write only)

## Code Organization

### File Structure (Current: Monolithic)

```
bin/rack (2600 lines)
├── Lines 1-30: Header, shebang, usage
├── Lines 30-70: Global configuration
│   ├── Paths (OPENCLAW_DIR, PROJECTS_DIR)
│   ├── Color palette
│   ├── Telegram group mappings
│   └── Model pricing data
├── Lines 70-220: Helper functions
│   ├── Output (info, success, warn, error)
│   ├── Slugify, session key generation
│   ├── Project picker (fzf integration)
│   └── Service control (restart_gateway)
├── Lines 220-1650: Command functions
│   ├── cmd_install      (200 lines)
│   ├── cmd_team         (300 lines)
│   ├── cmd_workflow     (150 lines)
│   ├── cmd_scope        (100 lines)
│   ├── cmd_list         (150 lines)
│   ├── cmd_add          (200 lines)
│   ├── cmd_info         (80 lines)
│   ├── cmd_delete       (60 lines)
│   ├── cmd_reset        (70 lines)
│   ├── cmd_repair       (100 lines)
│   ├── cmd_wire         (40 lines)
│   ├── cmd_unwire       (40 lines)
│   ├── cmd_logs         (50 lines)
│   ├── cmd_edit         (30 lines)
│   ├── cmd_model        (60 lines)
│   ├── cmd_profile      (80 lines)
│   └── cmd_cost         (150 lines)
├── Lines 1650-2400: Internal functions
│   ├── _create_workspace
│   ├── _wire_group
│   ├── _show_unbound_groups
│   ├── _aggregate_cost
│   └── _estimate_cost
├── Lines 2400-2500: Help text
└── Lines 2500-2583: Router
```

### Future Structure (Modular - Recommended)

```
rack-cli/
├── bin/
│   └── rack                      # Entry point (100 lines)
├── lib/
│   ├── config/
│   │   ├── paths.sh             # Directory paths
│   │   ├── colors.sh            # Output colors
│   │   └── models.sh            # Model profiles & pricing
│   ├── helpers/
│   │   ├── output.sh            # info, success, warn, error
│   │   ├── meta.sh              # meta_get, meta_set
│   │   ├── telegram.sh          # Telegram helpers
│   │   ├── session.sh           # Session key management
│   │   └── service.sh           # restart_gateway
│   └── commands/
│       ├── install.sh           # cmd_install
│       ├── list.sh              # cmd_list
│       ├── add.sh               # cmd_add
│       ├── team.sh              # cmd_team
│       ├── workflow.sh          # cmd_workflow
│       ├── scope.sh             # cmd_scope
│       └── ...                  # Other commands
├── docs/
│   └── ...
└── tests/
    └── ...
```

## Extension Points

### Adding a New Command

1. **Create Command Function** (`bin/rack` or new file)
   ```bash
   cmd_mycommand() {
     local id="${1:-}"
     [[ -z "$id" ]] && id=$(pick_project "Select project")

     # Your logic here
     success "Command executed"
   }
   ```

2. **Add to Router**
   ```bash
   case "$CMD" in
     # ...
     mycommand|mc) cmd_mycommand "$ARG" ;;
     # ...
   esac
   ```

3. **Update Help**
   ```bash
   cmd_help() {
     cat <<HELP
   ${BOLD}NEW SECTION${RESET}
     ${GREEN}mycommand${RESET} [id]  Description of command
   HELP
   }
   ```

4. **Add Tests**
   ```bash
   # tests/test-lifecycle.sh
   section "TEST X: rack mycommand"
   OUTPUT=$("$RACK" mycommand test-agent 2>&1)
   if echo "$OUTPUT" | grep -q "expected"; then
     pass "mycommand works"
   else
     fail "mycommand failed"
   fi
   ```

### Adding New Metadata Fields

1. **Update metadata structure** in `cmd_add`:
   ```bash
   meta_set "$AGENT_ID" "newField" "$NEW_VALUE"
   ```

2. **Sync to OpenClaw** if needed:
   ```bash
   python3 - "$CONFIG_FILE" "$AGENT_ID" "$NEW_VALUE" <<'PY'
   import json, sys
   # Update openclaw.json
   PY
   ```

3. **Display in `cmd_info`**:
   ```bash
   local new_field; new_field=$(meta_get "$id" "newField" "default")
   printf "  ${BOLD}%-18s${RESET} %s\n" "New Field:" "$new_field"
   ```

### Adding New Model Profiles

1. **Update MODEL_PROFILES** dictionary:
   ```bash
   declare -A MODEL_PROFILES=(
     [economy]="anthropic/claude-haiku-4-5"
     [standard]="anthropic/claude-sonnet-4-6"
     [premium]="anthropic/claude-opus-4-6"
     [custom]="anthropic/claude-custom-1-0"  # New profile
   )
   ```

2. **Update MODEL_PRICING**:
   ```bash
   declare -A MODEL_PRICING=(
     ["anthropic/claude-custom-1-0"]="2.50:12.00:0.25:3.00"
   )
   ```

3. **Update help text** with new profile info

## Design Decisions

### Why Bash?

**Pros**:
- Universal availability (ships with all Unix systems)
- Direct system access (no subprocess overhead)
- Easy to debug (set -x for trace)
- Simple dependency model (just Python 3 for JSON)

**Cons**:
- Limited data structures (workaround: Python for JSON)
- Error handling requires discipline (set -euo pipefail)
- Slower than compiled languages (acceptable for CLI)

### Why Dual-Source Configuration?

**Rationale**: rack needs project-specific metadata (name, description, stack) that OpenClaw doesn't care about, while OpenClaw needs runtime config (bindings, security) that rack shouldn't duplicate.

**Trade-off**: Must maintain sync, but allows independent evolution.

### Why Embedded Python?

**Alternative Considered**: Pure Bash with jq

**Decision**: Python 3 is more universal than jq, handles complex JSON mutations, and is likely already installed for OpenClaw.

### Why Monolithic File?

**Current State**: Single 2600-line file for ease of distribution.

**Future**: Plan to modularize into lib/ structure as project matures (see "Future Structure" above).

## Performance Considerations

### JSON Operations

- **Optimization**: Cache frequently-read values in local variables
- **Trade-off**: Python subprocess overhead (~10ms) vs. parsing speed

### fzf Integration

- **Graceful Degradation**: Falls back to numbered list if fzf unavailable
- **Performance**: fzf handles thousands of items with <100ms response time

### Gateway Restarts

- **Strategy**: Only restart when necessary (model, binding, scope changes)
- **Cost**: ~2 seconds downtime per restart

## Security Architecture

### Threat Model

**Protected Against**:
- Accidental cross-project contamination (session keys)
- Unauthorized file access (700/600 permissions)
- Dangerous operations without approval (tool gates)
- Credential leaks (audit logging)

**Not Protected Against**:
- Malicious system admin (runs as user)
- Compromised OpenClaw binary
- Host-level vulnerabilities

### Permission Model

```
~/.openclaw/              (700 drwx------)
├── openclaw.json         (600 -rw-------)
└── workspaces/
    └── projects/
        └── myproject/    (700 drwx------)
            ├── SOUL.md   (600 -rw-------)
            └── ...
```

## Monitoring & Observability

### Log Locations

- **Gateway logs**: `/tmp/openclaw/openclaw-YYYY-MM-DD.log`
- **Audit logs**: `/tmp/openclaw/audit.log` (if enabled)
- **Agent memory**: `~/.openclaw/workspaces/projects/<id>/memory/YYYY-MM-DD.md`

### Health Checks

```bash
rack doctor  # System-wide health check
rack team check  # Specialist agent verification
rack info <id>  # Single agent status
```

### Cost Monitoring

```bash
rack cost  # All agents
rack cost <id>  # Single agent with savings estimate
```

## Future Improvements

1. **Modularize codebase** into lib/ structure
2. **Add configuration file** (~/.rackrc) for user preferences
3. **Implement plugins** for custom commands
4. **Add bash completion** for better UX
5. **Web dashboard** for visual monitoring
6. **Multi-user support** with RBAC
7. **Automated heartbeat** via cron/systemd timer

## References

- [OpenClaw Documentation](https://openclaw.dev/docs)
- [Bash Best Practices](https://mywiki.wooledge.org/BashGuide)
- [Lobster Workflow Syntax](https://openclaw.dev/docs/lobster)
