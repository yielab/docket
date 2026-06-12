# Command Reference

Complete reference for all rack commands with detailed examples and options.

## Table of Contents

- [Setup Commands](#setup-commands)
- [Lifecycle Commands](#lifecycle-commands)
- [Session Management](#session-management)
- [Team Coordination](#team-coordination)
- [Workflow Management](#workflow-management)
- [Telegram Integration](#telegram-integration)
- [Utility Commands](#utility-commands)
- [Global Options](#global-options)

## Setup Commands

### install

Bootstrap a complete OpenClaw setup from scratch.

**Syntax:**
```bash
rack install
```

**What it does:**
1. Checks for required dependencies (bash, python3, openclaw, systemctl)
2. Initializes OpenClaw configuration at `~/.openclaw/openclaw.json`
3. Creates specialist agents (programmer, reviewer, tester, knowledge, security)
4. Sets up specialist agents and best-practice defaults (enforced security gates are planned — see specs/functional/security-gates.spec.md)
5. Sets up workspace directories with proper permissions (700)
6. Starts the openclaw-gateway.service systemd unit

**Example:**
```bash
# First-time setup
rack install

# Output:
# → Checking dependencies...
# ✓ bash 5.1.16 found
# ✓ python3 3.10.12 found
# ✓ openclaw 0.4.2 found
# → Creating OpenClaw config...
# → Creating specialist agents...
# ✓ programmer agent created
# ✓ reviewer agent created
# ...
# ✓ Installation complete!
```

**Aliases:** `setup`

**Notes:**
- Safe to run multiple times (idempotent)
- Preserves existing agents
- Recommended on clean systems

---

## Lifecycle Commands

### list

Display all project agents with status, model, and Telegram binding info.

**Syntax:**
```bash
rack list
```

**Output format:**
```
┌──────────────────────────────────────────────────────────────┐
│ ID              Type   Model        Telegram      Session    │
├──────────────────────────────────────────────────────────────┤
│ myproject       repo   sonnet (policy) ✓ Wired    default     │
│ taskagent       task   haiku (policy)  ✗ Not wired alpha      │
└──────────────────────────────────────────────────────────────┘
```

**Example:**
```bash
rack list

# With DEBUG mode
DEBUG=1 rack list
```

**Aliases:** None

**Notes:**
- Shows project agents only (excludes specialists and manager)
- Telegram status checks openclaw.json bindings
- Session shows current project key

---

### add

Interactively create a new project agent.

**Syntax:**
```bash
rack add
```

**Interactive prompts:**
1. **Agent type:** `repo` (codebase-based) or `task` (general work)
2. **Project name:** Display name for the agent
3. **Codebase path:** (repo type only) Absolute path to codebase
4. **Description:** Optional description
5. **Tech stack:** Auto-detected or manual entry
6. **Model selection:** Choose from available models or profiles
7. **Telegram group:** Optional group ID for wiring

**Example:**
```bash
rack add

# Interactive session:
# → Select agent type:
#   1) repo (codebase-based project)
#   2) task (general work)
# Choice: 1
#
# → Enter project name: My Awesome Project
# → Enter codebase path: /home/user/Sites/myproject
# → Detecting stack...
# ✓ Detected: Node.js, React, TypeScript
# → Model [policy: anthropic/claude-sonnet-4-6]:
#   (Enter = follow the role policy; type a provider/model ID to pin)
#
# ✓ Agent 'myawesomeproject' created
```

**Aliases:** `create`, `new`

**Notes:**
- Agent ID auto-generated via slugification
- Creates workspace at `~/.openclaw/workspaces/projects/<id>/`
- Generates SOUL.md, AGENTS.md, TOOLS.md, HEARTBEAT.md
- Sets permissions to 700 (dirs) and 600 (files)
- Restarts gateway after creation

---

### info

Display detailed information about a specific project agent.

**Syntax:**
```bash
rack info <agent-id>
rack info             # Interactive picker if ID omitted
```

**Output:**
```
Agent: myproject
─────────────────────────────────────────────────
Type:              repo
Name:              My Awesome Project
Codebase:          /home/user/Sites/myproject
Stack:             Node.js, React, TypeScript
Model:             anthropic/claude-sonnet-4-6
Description:       My project description
Session Key:       agent:myproject:default
Project Key:       default
Created:           2026-02-25T10:00:00Z
Workspace:         ~/.openclaw/workspaces/projects/myproject/
Telegram:          ✓ Wired to group -1001234567890
```

**Example:**
```bash
# With agent ID
rack info myproject

# Interactive picker
rack info
# → Select project:
#   1) myproject - My Awesome Project
#   2) taskagent - Task Agent
# Choice: 1
```

**Aliases:** `show`

**Notes:**
- Uses fzf for interactive selection if available
- Falls back to numbered list otherwise
- Displays metadata from .rack-meta.json

---

### delete

Remove an agent and optionally its workspace.

**Syntax:**
```bash
rack delete <agent-id>
rack delete           # Interactive picker
```

**Interactive prompts:**
1. Confirm deletion (yes/no)
2. Delete workspace files (yes/no)

**Example:**
```bash
rack delete myproject

# Prompts:
# ⚠ Delete agent 'myproject'? (yes/no): yes
# ⚠ Also delete workspace directory? (yes/no): yes
# ✓ Agent deleted
# ✓ Workspace removed
```

**Aliases:** `remove`, `rm`

**Notes:**
- Removes agent from openclaw.json
- Optionally deletes `~/.openclaw/workspaces/projects/<id>/`
- Restarts gateway after deletion
- Cannot be undone (backup first if unsure)

---

### maintain

Clear memory, repair, or rebuild an agent. Consolidates the retired `reset`, `repair`, and
`cleanup` commands into one.

**Syntax:**
```bash
rack maintain [agent-id] [mode]
```

**Modes:**
- **`check`** (default): Health check and auto-fix — permissions (700/600), missing workspace
  files, session-key sync between `.rack-meta.json` and `openclaw.json`, Telegram bindings
- **`clean`**: Clear memory logs only (`memory/*.md`)
- **`reset`**: Clear memory + MEMORY.md + HEARTBEAT.md
- **`rebuild`**: Deep rebuild — regenerate SOUL.md, AGENTS.md, TOOLS.md from metadata
- **`sessions`**: Archive large/old session data

**Example:**
```bash
# Health check and auto-fix (was: rack repair)
rack maintain myproject
rack maintain myproject check

# Clear memory logs (was: rack reset 1)
rack maintain myproject clean

# Clear memory + heartbeat (was: rack reset 2)
rack maintain myproject reset

# Deep rebuild (was: rack reset 3)
rack maintain myproject rebuild

# Archive old sessions (was: rack cleanup safe)
rack maintain myproject sessions
```

**Migration (deprecated → current):**

| Old | New |
|-----|-----|
| `rack repair [id]` | `rack maintain [id] check` |
| `rack reset [id]` / `reset [id] 1` | `rack maintain [id] clean` |
| `rack reset [id] 2` | `rack maintain [id] reset` |
| `rack reset [id] 3` | `rack maintain [id] rebuild` |
| `rack cleanup [id]` | `rack maintain [id] sessions` |

**Notes:**
- Preserves identity (`.rack-meta.json`, `openclaw.json`)
- `reset`/`rebuild` are destructive and prompt for confirmation
- Restarts the gateway after structural changes

---

## Session Management

### scope

Manage session keys for multi-project isolation.

**Syntax:**
```bash
rack scope <agent-id> show                    # Display current scope
rack scope <agent-id> set <project-key>       # Set new project scope
rack scope <agent-id> reset                   # Reset to default
```

**Session key format:** `agent:<id>:<project>`

**Example:**
```bash
# Show current scope
rack scope myproject show
# Output: agent:myproject:default

# Set scope to "alpha"
rack scope myproject set alpha
# ✓ Session key updated: agent:myproject:alpha

# Reset to default
rack scope myproject reset
# ✓ Session key reset: agent:myproject:default
```

**Aliases:** None

**Notes:**
- Prevents cross-project contamination
- Updates .rack-meta.json, openclaw.json, and SOUL.md
- Restarts gateway to apply changes
- Use different keys for parallel project work

---

## Team Coordination

### team

Manage the Manager agent and specialist team.

**Syntax:**
```bash
rack team status      # View team state and health
rack team init        # Create Manager agent
rack team check       # Health check for specialists
```

**Subcommands:**

#### status
Display team coordination state.

```bash
rack team status

# Output:
# Team Coordination Status
# ────────────────────────────────────────
# Manager:         ✓ Running (agent:manager:orchestrator)
# Specialists:
#   programmer     ✓ Active
#   reviewer       ✓ Active
#   tester         ✓ Active
#   knowledge      ✓ Active
#   security       ✓ Active
# Task List:       3 pending, 2 in progress, 5 completed
```

#### init
Create the Manager agent.

```bash
rack team init

# Output:
# → Creating Manager agent...
# ✓ Manager workspace created
# ✓ Delegation rules configured
# ✓ TASK_LIST.json initialized
# ✓ Manager agent ready
```

#### check
Verify specialist agents exist and are healthy.

```bash
rack team check

# Output:
# → Checking specialist agents...
# ✓ programmer - OK
# ✓ reviewer - OK
# ⚠ tester - Missing HEARTBEAT.md
# ✓ knowledge - OK
# ✓ security - OK
```

**Aliases:** None

**Notes:**
- Manager lives at `~/.openclaw/workspaces/manager/`
- Uses TASK_LIST.json for coordination
- Manager cannot edit code (delegation mode only)
- Specialists run on the role→model policy (cheap class for manager/reviewer/tester/knowledge, strong class for programmer/security)

---

## Workflow Management

### workflow

Manage Lobster deterministic workflows.

**Syntax:**
```bash
rack workflow <agent-id> list                 # List all workflows
rack workflow <agent-id> create <name>        # Create from template
rack workflow <agent-id> show <name>          # Display workflow
rack workflow <agent-id> delete <name>        # Remove workflow
```

**Subcommands:**

#### list
Show all workflows for an agent.

```bash
rack workflow myproject list

# Output:
# Workflows for 'myproject':
#   - ci-pipeline.lobster.yml
#   - code-review.lobster.yml
#   - deploy.lobster.yml
```

#### create
Generate a new workflow from template.

```bash
rack workflow myproject create ci-pipeline

# Output:
# → Creating workflow 'ci-pipeline'...
# ✓ Template created: workflows/ci-pipeline.lobster.yml
# → Edit with: rack edit myproject
```

#### show
Display workflow contents.

```bash
rack workflow myproject show ci-pipeline

# Output: (displays YAML contents)
```

#### delete
Remove a workflow.

```bash
rack workflow myproject delete ci-pipeline

# Prompt:
# ⚠ Delete workflow 'ci-pipeline'? (yes/no): yes
# ✓ Workflow deleted
```

**Aliases:** `wf`

**Notes:**
- Workflows stored in `<workspace>/workflows/*.lobster.yml`
- Templates include ci-pipeline and code-review
- Saves ~90% tokens vs. ad-hoc planning
- Supports shell steps (zero tokens) and LLM steps

---

## Telegram Integration

### wire

Bind an agent to a Telegram group for notifications and approvals.

**Syntax:**
```bash
rack wire <agent-id>
rack wire             # Interactive picker
```

**Interactive prompts:**
1. Enter Telegram group ID (get from logs)

**Example:**
```bash
# Step 1: Create Telegram group and add bot
# Step 2: Send test message
# Step 3: Get group ID from logs
tail -f /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log
# Look for: "New group: -1001234567890"

# Step 4: Wire agent
rack wire myproject
# → Enter Telegram group ID: -1001234567890
# ✓ Agent wired to group -1001234567890
```

**Aliases:** None

**Notes:**
- Updates openclaw.json bindings
- Enables mobile approvals for dangerous operations
- Sends notifications for workflow steps
- Restarts gateway after wiring

---

### unwire

Remove Telegram binding from an agent.

**Syntax:**
```bash
rack unwire <agent-id>
rack unwire           # Interactive picker
```

**Example:**
```bash
rack unwire myproject
# ✓ Telegram binding removed
```

**Aliases:** None

**Notes:**
- Removes entry from openclaw.json bindings
- Agent can still function without Telegram
- Approvals will require CLI interaction
- Restarts gateway after unwiring

---

## Utility Commands

### logs

View memory logs and gateway entries for an agent.

**Syntax:**
```bash
rack logs <agent-id>
rack logs             # Interactive picker
```

**What it shows:**
1. Recent memory logs from `memory/YYYY-MM-DD.md`
2. Gateway log entries for the agent
3. Active tasks from HEARTBEAT.md

**Example:**
```bash
rack logs myproject

# Output:
# Memory Logs (2026-02-25)
# ────────────────────────────────────────
# 10:00 - Started work on authentication
# 10:15 - Implemented JWT middleware
# 10:30 - Added tests for auth flow
#
# Gateway Logs
# ────────────────────────────────────────
# [10:00:12] Message received from myproject
# [10:05:34] Tool approval requested: git push
# [10:06:01] Approval granted
#
# Active Tasks (HEARTBEAT.md)
# ────────────────────────────────────────
# - Refactor authentication module
# - Add integration tests
```

**Aliases:** `log`

**Notes:**
- Tails last 50 lines by default
- Use `tail -f` on log files for live monitoring
- Memory logs rotate daily

---

### edit

Open agent workspace files in $EDITOR.

**Syntax:**
```bash
rack edit <agent-id>
rack edit             # Interactive picker
```

**What it opens:**
- SOUL.md (identity and session key)
- AGENTS.md (delegation rules)
- TOOLS.md (project commands)
- HEARTBEAT.md (active tasks)
- .rack-meta.json (metadata)

**Example:**
```bash
# Uses default editor
rack edit myproject

# Set custom editor
EDITOR=vim rack edit myproject
EDITOR=code rack edit myproject
```

**Aliases:** None

**Notes:**
- Respects $EDITOR environment variable
- Falls back to `vi` if $EDITOR not set
- Opens workspace directory in most editors
- Be careful editing .rack-meta.json (use `rack maintain <id> check` to fix)

---

### model (retired)

`rack model <id> <model-id>` has been retired. Use [`rack profile`](#profile) to pin a
model on one agent, or `rack models` to change the role→model policy — see the next section.

---

### profile

Pin an agent's model, or re-attach it to the role→model policy. Also sets per-agent budget caps.

Every agent follows its role's policy model by default (`modelSource: policy`). Pinning
(`modelSource: pinned`) detaches it: policy and preset changes will no longer touch it.

**Syntax:**
```bash
rack profile <agent-id>                    # Show current model, role, source, budget
rack profile <agent-id> <provider/model>   # Pin this agent to a model
rack profile <agent-id> default            # Follow the role policy again
rack profile <agent-id> --budget <USD>     # Set a per-agent spend cap (0 = none)
```

**Example:**
```bash
# Show current model and intent
rack profile myproject
# Current model:  anthropic/claude-sonnet-4-6
# Role:           repo (project default for repo agents)
# Source:         policy — follows the role's model (rack models)

# Pin a stronger model for a hard problem
rack profile myproject anthropic/claude-opus-4-6
# ✓ Model pinned: anthropic/claude-sonnet-4-6 → anthropic/claude-opus-4-6

# Back to the policy when done
rack profile myproject default
```

**Aliases:** `tier` (deprecated)

**Notes:**
- Tier names (economy/standard/premium) are deprecated but still accepted with a warning; they resolve to the internal rank anchors and create a pin
- Updates .rack-meta.json and openclaw.json
- Restarts gateway after change

---

### models

View and change the role→model policy — the single place that decides which model each
kind of agent runs on. Built-in defaults put high-volume/low-reasoning roles (manager,
reviewer, tester, knowledge, task) on the cheap model class and reasoning-dense roles
(programmer, security, repo) on the strong class.

**Syntax:**
```bash
rack models                            # Show the role→model policy with pricing and WHY
rack models set <role> <provider/model> # Change one role's model
rack models set default <provider/model> # Change the fallback default model
rack models preset [name]              # List or apply a provider preset
rack models reset                      # Restore built-in defaults
```

**Presets:** `anthropic` (default), `openai`, `google`, `openrouter-free` (zero per-token cost), `openrouter`

**Example:**
```bash
rack models set programmer openai/gpt-4.1
# ✓ programmer → openai/gpt-4.1
# → Re-resolving policy-following agents...
#   (every agent with role 'programmer' that follows the policy is updated)
```

**Notes:**
- Policy changes are **live**: every policy-following agent is re-resolved and the gateway restarts once. Pinned agents (`rack profile <id> <model>`) are never touched
- Overrides persist in `~/.openclaw/rack-models.json` (`roles:` map); delete it or run `rack models reset` to restore built-ins
- Unknown models are accepted if well-formed (`provider/model`) — the daemon validates the actual model; pricing shows `n/a`

---

### cost

Display token usage and cost breakdown.

**Syntax:**
```bash
rack cost              # All agents (aggregate)
rack cost <agent-id>   # Single agent
```

**Output format:**
```
Token Usage & Costs
────────────────────────────────────────
Agent: myproject
Model: anthropic/claude-sonnet-4-6

Input:     125,000 tokens ($0.38)
Output:     45,000 tokens ($0.68)
Cache Write: 10,000 tokens ($0.04)
Cache Read:  50,000 tokens ($0.01)
─────────────────────────────────
Total:    $1.11

Estimated savings with economy profile:
~$0.83 (75% reduction)
```

**Example:**
```bash
# Single agent
rack cost myproject

# All agents
rack cost

# Output:
# Token Usage (All Agents)
# ────────────────────────────────────────
# myproject:     $1.11
# taskagent:     $0.45
# Total:         $1.56
```

**Aliases:** `usage`

**Notes:**
- Reads from OpenClaw usage logs
- Pricing from global MODEL_PRICING config
- Shows profile savings estimates
- Useful for budget management

---

### doctor

System-wide health check and diagnostics.

**Syntax:**
```bash
rack doctor
```

**What it checks:**
1. Required dependencies (bash, python3, openclaw, systemctl)
2. OpenClaw config file exists and is valid JSON
3. Gateway service status
4. Workspace permissions (700/600)
5. Specialist agents present
6. Telegram bindings
7. Session key consistency
8. Missing or corrupted files

**Example:**
```bash
rack doctor

# Output:
# System Health Check
# ════════════════════════════════════════
# Dependencies
# ✓ bash 5.1.16
# ✓ python3 3.10.12
# ✓ openclaw 0.4.2
# ✓ systemctl available
#
# OpenClaw
# ✓ Config file exists
# ✓ Valid JSON
# ✓ Gateway service running
#
# Specialists
# ✓ programmer OK
# ✓ reviewer OK
# ✓ tester OK
# ✓ knowledge OK
# ⚠ security - Missing HEARTBEAT.md (run: rack maintain security check)
#
# Projects
# ✓ myproject - OK
# ⚠ taskagent - Permission issue (run: rack maintain taskagent check)
#
# Summary
# ────────────────────────────────────────
# Status: Healthy (2 warnings)
# Recommendations:
#   - Fix security agent HEARTBEAT.md
#   - Repair taskagent permissions
```

**Aliases:** `check`

**Notes:**
- Run after installation to verify setup
- Provides fix commands for issues
- Non-destructive (read-only checks)
- Useful for troubleshooting

---

## Global Options

### --debug

Enable verbose debug output.

**Syntax:**
```bash
rack --debug <command>
DEBUG=1 rack <command>
```

**Example:**
```bash
rack --debug list
DEBUG=1 rack add
```

**Output:**
```
[dbg] Loading config from /home/user/.openclaw/openclaw.json
[dbg] Found 3 project agents
[dbg] Reading metadata for myproject
...
```

### --help / -h

Show help text.

**Syntax:**
```bash
rack --help
rack -h
rack help
```

---

## Command Aliases

| Command | Aliases |
|---------|---------|
| install | setup |
| add | create, new |
| info | show |
| delete | remove, rm |
| repair | fix |
| profile | tier (deprecated) |
| workflow | wf |
| logs | log |
| cost | usage |
| doctor | check |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (generic) |
| 2 | Missing dependency |
| 3 | Invalid argument |
| 4 | Permission denied |
| 5 | Service failure |

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug output | `0` |
| `EDITOR` | Text editor for `rack edit` | `vi` |
| `OPENCLAW_DIR` | OpenClaw directory | `~/.openclaw` |

---

## Tips & Tricks

### Interactive Pickers

If you have fzf installed, omit the agent-id for fuzzy search:

```bash
rack info      # Opens fzf picker
rack delete    # Opens fzf picker
rack logs      # Opens fzf picker
```

### Batch Operations

Use bash loops for batch operations:

```bash
# Reset all agents
for id in $(rack list | awk '{print $1}' | tail -n +2); do
  rack maintain "$id" clean
done

# Cheaper models fleet-wide: change the policy once — every
# policy-following agent updates automatically (pins are untouched)
rack models preset openrouter-free
```

### Cost Monitoring

Track daily costs:

```bash
# Add to crontab
0 23 * * * rack cost >> ~/rack-costs-$(date +%Y-%m).log
```

### Backup Strategy

Regular backups:

```bash
# Backup script
#!/bin/bash
tar -czf ~/backups/openclaw-$(date +%s).tar.gz \
  ~/.openclaw/openclaw.json \
  ~/.openclaw/workspaces/
```

---

## Next Steps

- [Architecture Documentation](architecture.md)
- [Development Guide](development.md)
- [Installation Guide](installation.md)
- [Main README](../README.md)
