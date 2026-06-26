# Command Reference

Complete reference for all docket commands with detailed examples and options.

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

Bootstrap a complete OpenClaw setup from scratch, including the shared **org specialists**.

**Syntax:**
```bash
docket install                  # manager, knowledge, security
docket install --portfolio      # + the optional org Portfolio Manager
docket install --gates          # enable enforced tool-approval gates at install time
```

**What it does:**
1. Checks for required dependencies (python3 3.11+, openclaw, systemctl; bash for the launcher)
2. Initializes OpenClaw configuration at `~/.openclaw/openclaw.json`
3. Creates the org specialists (`scope: org`): **manager**, **knowledge**, **security**
4. Sets up specialist agents and best-practice defaults
5. Sets up workspace directories with proper permissions (700)
6. Starts the openclaw-gateway.service systemd unit

**Flags:**
- **`--portfolio`**: also provision the optional org **Portfolio Manager** — one
  `portfolio-manager` agent (`scope: org`) that is an advisory cross-pod planner over fleet
  *metadata* (which pods exist, their queues, budgets, health). It never edits code, never
  dispatches into a pod, and is never a pod member. Opt-in.
- **`--gates`**: turn on the enforced tool-approval gates for dangerous operations (gates are
  otherwise opt-in via `docket gates enable`) — see `specs/functional/security-gates.spec.md`.

**Example:**
```bash
# First-time setup
docket install

# With the org Portfolio Manager and enforced gates
docket install --portfolio --gates

# Output:
# → Checking dependencies...
# ✓ python3 3.11+ found
# ✓ openclaw 0.4.2 found
# → Creating OpenClaw config...
# → Creating org specialists...
# ✓ manager agent created
# ✓ knowledge agent created
# ✓ security agent created
# ...
# ✓ Installation complete!
```

**Aliases:** `setup`

**Notes:**
- Safe to run multiple times (idempotent)
- Preserves existing agents
- Recommended on clean systems
- Project pods are created separately with [`docket add`](#add); see
  [Agent Teams (Pods)](AGENT-TEAMS.md)

---

## Lifecycle Commands

### list

Display all project agents with status, model, and Telegram binding info.

**Syntax:**
```bash
docket list
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
docket list

# With DEBUG mode
DEBUG=1 docket list
```

**Aliases:** None

**Notes:**
- Shows all registered agents: org specialists (manager, knowledge, security) and all pod members
- Telegram status checks openclaw.json bindings
- Session shows current project key

---

### add

Create a new project **pod** — an isolated team of project-scoped agents that owns one codebase.
The default pod is **lean: a Lead + an Implementer**. See [Agent Teams (Pods)](AGENT-TEAMS.md).

**Syntax:**
```bash
docket add                               # interactive
docket add <project> [path]              # lean pod: <project>-lead + <project>-implementer
docket add <project> [path] --pod full   # full pod: + reviewer + tester
docket add <project> [path] --with reviewer,tester   # lean pod + named roles
```

**Flags:**
- **`--pod full`**: provision the full pod — Lead, Implementer, Reviewer, and Tester.
- **`--with <roles>`**: start from the lean pod and add the named roles (comma-separated:
  `reviewer`, `tester`, `implementer`). E.g. `--with reviewer` adds a review gate only.

Member ids are predictable: `myapp-lead`, `myapp-implementer`, `myapp-reviewer`, `myapp-tester`
(duplicated roles get `-2`, `-3` suffixes). A pod has **exactly one Lead**. Resize the pod later
with [`docket pod`](#pod), and tear the whole pod down with [`docket delete`](#delete).

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
# Lean pod (Lead + Implementer) for a codebase
docket add myapp ~/code/myapp

# Full pod with a review + test gate
docket add myapp ~/code/myapp --pod full

# Lean pod plus a reviewer
docket add myapp ~/code/myapp --with reviewer

# Interactive session:
# → Select agent type:
#   1) repo (codebase-based project)
#   2) task (general work)
# Choice: 1
#
# → Enter project name: My Awesome Project
# → Detecting stack...
# ✓ Detected: Node.js, React, TypeScript
# → Model [policy: anthropic/claude-sonnet-4-6]:
#   (Enter = follow the role policy; type a provider/model ID to pin)
#
# ✓ Pod 'myapp' created (myapp-lead, myapp-implementer)
```

**Aliases:** `create`, `new`

**Notes:**
- Member ids auto-generated via slugification (`<project>-<role>[-N]`)
- Each member gets its own workspace at `~/.openclaw/workspaces/projects/<member-id>/`
- Generates SOUL.md, AGENTS.md, TOOLS.md, HEARTBEAT.md per member
- Sets permissions to 700 (dirs) and 600 (files)
- Restarts gateway after creation
- Pod members are ordinary registered agents, so `docket list`/`info`/`cost`/`doctor` see them

---

### info

Display detailed information about a specific project agent.

![docket info output: type, workspace, codebase, model, budget cap, session key, and workspace files](assets/info.png)

**Syntax:**
```bash
docket info <agent-id>
docket info             # Interactive picker if ID omitted
```

**Output:**
```
Agent: myproject-implementer
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
Workspace:         ~/.openclaw/workspaces/projects/myproject-implementer/
Telegram:          ✓ Wired to group -1001234567890
```

**Example:**
```bash
# With agent ID
docket info myproject

# Interactive picker
docket info
# → Select project:
#   1) myproject - My Awesome Project
#   2) taskagent - Task Agent
# Choice: 1
```

**Aliases:** `show`

**Notes:**
- Uses fzf for interactive selection if available
- Falls back to numbered list otherwise
- Displays metadata from .docket-meta.json

---

### delete

Remove an agent and optionally its workspace.

**Syntax:**
```bash
docket delete <agent-id>
docket delete           # Interactive picker
```

**Interactive prompts:**
1. Confirm deletion (yes/no)
2. Delete workspace files (yes/no)

**Example:**
```bash
docket delete myproject

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

![docket maintain check output: permissions, workspace files, session-key sync, and memory all healthy](assets/maintain.png)

**Syntax:**
```bash
docket maintain [agent-id] [mode]
```

**Modes:**
- **`check`** (default): Health check and auto-fix — permissions (700/600), missing workspace
  files, session-key sync between `.docket-meta.json` and `openclaw.json`, Telegram bindings
- **`clean`**: Clear memory logs only (`memory/*.md`)
- **`reset`**: Clear memory + MEMORY.md + HEARTBEAT.md
- **`rebuild`**: Deep rebuild — regenerate SOUL.md, AGENTS.md, TOOLS.md from metadata
- **`sessions`**: Archive large/old session data

**Example:**
```bash
# Health check and auto-fix (was: docket repair)
docket maintain myproject
docket maintain myproject check

# Clear memory logs (was: docket reset 1)
docket maintain myproject clean

# Clear memory + heartbeat (was: docket reset 2)
docket maintain myproject reset

# Deep rebuild (was: docket reset 3)
docket maintain myproject rebuild

# Archive old sessions (was: docket cleanup safe)
docket maintain myproject sessions
```

**Migration (deprecated → current):**

| Old | New |
|-----|-----|
| `docket repair [id]` | `docket maintain [id] check` |
| `docket reset [id]` / `reset [id] 1` | `docket maintain [id] clean` |
| `docket reset [id] 2` | `docket maintain [id] reset` |
| `docket reset [id] 3` | `docket maintain [id] rebuild` |
| `docket cleanup [id]` | `docket maintain [id] sessions` |

**Notes:**
- Preserves identity (`.docket-meta.json`, `openclaw.json`)
- `reset`/`rebuild` are destructive and prompt for confirmation
- Restarts the gateway after structural changes

---

## Session Management

### scope

Manage session keys for multi-project isolation.

**Syntax:**
```bash
docket scope <agent-id> show                    # Display current scope
docket scope <agent-id> set <project-key>       # Set new project scope
docket scope <agent-id> reset                   # Reset to default
```

**Session key format:** `agent:<id>:<project>`

**Example:**
```bash
# Show current scope
docket scope myproject show
# Output: agent:myproject:default

# Set scope to "alpha"
docket scope myproject set alpha
# ✓ Session key updated: agent:myproject:alpha

# Reset to default
docket scope myproject reset
# ✓ Session key reset: agent:myproject:default
```

**Aliases:** None

**Notes:**
- Prevents cross-project contamination
- Updates .docket-meta.json, openclaw.json, and SOUL.md
- Restarts gateway to apply changes
- Use different keys for parallel project work

---

## Team Coordination

> docket has **two** queues, and they are not the same thing:
>
> - [`docket pod <project> delegate`/`dispatch`](#pod) — the **per-project pipeline**. Queues
>   and runs work for one project's pod (Lead → Implementer → Reviewer → Tester), pod-local and
>   budget-gated.
> - [`docket team`](#team) — the **org manager queue**. Cross-cutting coordination work for the
>   shared org Manager specialist (delegate / queue / start / done / cancel). It is a task
>   tracker, not a pipeline runner.
>
> See [Agent Teams (Pods)](AGENT-TEAMS.md) for the full team model.

### pod

Manage a project's **pod** (its members) and run its **dispatch pipeline**. A pod is the isolated
team of project-scoped agents created by [`docket add`](#add); every member has its own
permission-locked workspace, so no role is ever shared between projects.
See [Agent Teams (Pods)](AGENT-TEAMS.md).

**Syntax:**
```bash
docket pod <project>                                   # list the pod's members (default)
docket pod <project> list                              # same as above
docket pod <project> add <role> [--count N]            # add member(s): implementer|reviewer|tester
docket pod <project> remove <member-id>                # remove one member
docket pod <project> delegate [--priority high|normal|low] "<task>"   # queue a task
docket pod <project> queue                             # show the pod's task queue
docket pod <project> dispatch                          # run the pending tasks through the pipeline
```

**Subcommands:**

#### list (default)
Show the pod's members and their roles. Runs when no subcommand is given.

```bash
docket pod myapp

# Output:
# Pod: myapp
# ────────────────────────────────────────
# myapp-lead          lead          (orchestrator)
# myapp-implementer   implementer
# myapp-reviewer      reviewer
```

#### add
Add a member to the pod. Role is one of `implementer`, `reviewer`, `tester` (the Lead is unique —
a pod always has exactly one). Duplicated roles get `-2`, `-3` ids. `--count N` adds several at
once.

```bash
docket pod myapp add implementer          # adds myapp-implementer-2
docket pod myapp add reviewer             # add a review gate later
docket pod myapp add implementer --count 2 # two more parallel implementers
```

#### remove
Remove one member by id.

```bash
docket pod myapp remove myapp-tester
# ✓ Removed myapp-tester from pod 'myapp'
```

#### delegate
Queue a task on the **pod's** task queue (which lives in the Lead's workspace). Optional
`--priority high|normal|low` (default `normal`). This queues only; run it with `dispatch`.

```bash
docket pod myapp delegate "Fix the null-token login crash"
docket pod myapp delegate --priority high "Patch the auth bypass"
# ✓ Queued task for pod 'myapp' (priority: high)
```

#### queue
Show the pod's task queue with per-task status and recorded cost.

```bash
docket pod myapp queue

# Output:
# Queue: myapp
# ────────────────────────────────────────
# t-002  pending   high    Patch the auth bypass            $0.00
# t-001  done      normal  Fix the null-token login crash   $0.42
```

#### dispatch
Run the pod's **pending** tasks through its pipeline — **one real agent turn per hop**:
`Lead → Implementer → Reviewer (if present) → Tester (if present)`. Only the roles the pod
actually has take part (a lean pod runs two hops). docket invokes each hop via the OpenClaw
daemon, captures the result, and threads it to the next role.

```bash
docket pod myapp dispatch
# → Dispatching pod 'myapp' (1 pending task)...
#   Lead → Implementer → Reviewer
# ✓ t-002 complete
```

Three guarantees hold on every dispatch:

- **Budget-gated.** Before *each* hop, docket checks the pod's recorded spend against the Lead's
  budget cap (`docket profile <project>-lead --budget N`). Over budget → the task is left
  **pending**, not run.
- **Traced.** Every hop emits a trace event (`docket trace`) on a per-task session
  `agent:<project>:<task_id>`, so a run is fully auditable.
- **Pod-local.** Dispatch only ever targets the project's own pod members. There is **no cross-pod
  dispatch path** — one pod can never run another pod's agents.

> Each hop is a real, costed LLM turn, so dispatch is explicit (`docket pod … dispatch`) or
> opt-in (`docket serve --dispatch`) — never silent. Plain `docket serve` does not dispatch.

**Aliases:** None

**Notes:**
- The pod's queue lives in the Lead's workspace; org-level work uses [`docket team`](#team) instead
- Resize a pod with `add`/`remove`; provision one with [`docket add`](#add); tear it down with
  [`docket delete`](#delete)
- Run every pod's queue continuously in the background with [`docket serve --dispatch`](#serve)

---

### team

The **org** manager's shared task queue. `docket team` delegates cross-cutting work to the shared
Manager specialist and tracks it through to completion. This is the **org** queue — for a single
project's pipeline use [`docket pod <project>`](#pod) instead.

> To see specialist + pod health, use `docket list` (shows org specialists and pods
> with scope) and `docket doctor` (health check). To inspect a project's pod and its
> roles, use `docket pod <project>`.

**Syntax:**
```bash
docket team delegate "<task>" [--priority high]   # Queue a task for the manager
docket team queue [--all]                          # List pending (or all) tasks
docket team start <task-id>                         # Mark a task in progress
docket team done <task-id>                           # Mark a task complete
docket team cancel <task-id>                         # Cancel a task
```

**Subcommands:**

#### delegate
Queue a task for the Manager agent.

```bash
docket team delegate "Fix the login bug" --priority high

# Output:
# ✓ Queued task T-014 (priority: high)
```

#### queue
List outstanding tasks (add `--all` to include completed/cancelled).

```bash
docket team queue

# Output:
# T-014  high    Fix the login bug
# T-013  normal  Update API docs
```

#### start / done / cancel
Transition a queued task.

```bash
docket team start T-014    # → in progress
docket team done T-014     # → complete
docket team cancel T-013   # → cancelled
```

**Aliases:** None

**Notes:**
- Manager lives at `~/.openclaw/workspaces/manager/` and owns `TASK_LIST.json`
- Manager cannot edit code (delegation mode only)
- The manager runs on the role→model policy (cheap class)

---

## Workflow Management

### workflow

Manage Lobster deterministic workflows.

**Syntax:**
```bash
docket workflow <agent-id> list                 # List all workflows
docket workflow <agent-id> create <name>        # Create from template
docket workflow <agent-id> show <name>          # Display workflow
docket workflow <agent-id> delete <name>        # Remove workflow
```

**Subcommands:**

#### list
Show all workflows for an agent.

```bash
docket workflow myproject list

# Output:
# Workflows for 'myproject':
#   - ci-pipeline.lobster.yml
#   - code-review.lobster.yml
#   - deploy.lobster.yml
```

#### create
Generate a new workflow from template.

```bash
docket workflow myproject create ci-pipeline

# Output:
# → Creating workflow 'ci-pipeline'...
# ✓ Template created: workflows/ci-pipeline.lobster.yml
# → Edit with: docket edit myproject
```

#### show
Display workflow contents.

```bash
docket workflow myproject show ci-pipeline

# Output: (displays YAML contents)
```

#### delete
Remove a workflow.

```bash
docket workflow myproject delete ci-pipeline

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
docket wire <agent-id>
docket wire             # Interactive picker
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
docket wire myproject
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
docket unwire <agent-id>
docket unwire           # Interactive picker
```

**Example:**
```bash
docket unwire myproject
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
docket logs <agent-id>
docket logs             # Interactive picker
```

**What it shows:**
1. Recent memory logs from `memory/YYYY-MM-DD.md`
2. Gateway log entries for the agent
3. Active tasks from HEARTBEAT.md

**Example:**
```bash
docket logs myproject

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
docket edit <agent-id>
docket edit             # Interactive picker
```

**What it opens:**
- SOUL.md (identity and session key)
- AGENTS.md (delegation rules)
- TOOLS.md (project commands)
- HEARTBEAT.md (active tasks)
- .docket-meta.json (metadata)

**Example:**
```bash
# Uses default editor
docket edit myproject

# Set custom editor
EDITOR=vim docket edit myproject
EDITOR=code docket edit myproject
```

**Aliases:** None

**Notes:**
- Respects $EDITOR environment variable
- Falls back to `vi` if $EDITOR not set
- Opens workspace directory in most editors
- Be careful editing .docket-meta.json (use `docket maintain <id> check` to fix)

---

### model (retired)

`docket model <id> <model-id>` has been retired. Use [`docket profile`](#profile) to pin a
model on one agent, or `docket models` to change the role→model policy — see the next section.

---

### profile

Pin an agent's model, or re-attach it to the role→model policy. Also sets per-agent budget caps.

Every agent follows its role's policy model by default (`modelSource: policy`). Pinning
(`modelSource: pinned`) detaches it: policy and preset changes will no longer touch it.

**Syntax:**
```bash
docket profile <agent-id>                    # Show current model, role, source, budget
docket profile <agent-id> <provider/model>   # Pin this agent to a model
docket profile <agent-id> default            # Follow the role policy again
docket profile <agent-id> --budget <USD>     # Set a per-agent spend cap (0 = none)
```

**Example:**
```bash
# Show current model and intent
docket profile myproject
# Current model:  anthropic/claude-sonnet-4-6
# Role:           repo (project default for repo agents)
# Source:         policy — follows the role's model (docket models)

# Pin a stronger model for a hard problem
docket profile myproject anthropic/claude-opus-4-6
# ✓ Model pinned: anthropic/claude-sonnet-4-6 → anthropic/claude-opus-4-6

# Back to the policy when done
docket profile myproject default
```

**Aliases:** `tier` (deprecated)

**Notes:**
- Tier names (economy/standard/premium) are deprecated but still accepted with a warning; they resolve to the internal rank anchors and create a pin
- Updates .docket-meta.json and openclaw.json
- Restarts gateway after change

---

### models

View and change the role→model policy — the single place that decides which model each
kind of agent runs on. Built-in defaults put high-volume/low-reasoning roles (manager,
reviewer, tester, knowledge, task) on the cheap model class and reasoning-dense roles
(programmer, security, repo) on the strong class.

![docket models output: role→model policy table with pricing, source, and rationale](assets/models.png)

**Syntax:**
```bash
docket models                            # Show the role→model policy with pricing and WHY
docket models set <role> <provider/model> # Change one role's model
docket models set default <provider/model> # Change the fallback default model
docket models preset [name]              # List or apply a provider preset
docket models reset                      # Restore built-in defaults
```

**Presets:** `anthropic` (default), `openai`, `google`, `openrouter-free` (zero per-token cost), `openrouter`

**Example:**
```bash
docket models set programmer openai/gpt-4.1
# ✓ programmer → openai/gpt-4.1
# → Re-resolving policy-following agents...
#   (every agent with role 'programmer' that follows the policy is updated)
```

**Notes:**
- Policy changes are **live**: every policy-following agent is re-resolved and the gateway restarts once. Pinned agents (`docket profile <id> <model>`) are never touched
- Overrides persist in `~/.openclaw/docket-models.json` (`roles:` map); delete it or run `docket models reset` to restore built-ins
- Unknown models are accepted if well-formed (`provider/model`) — the daemon validates the actual model; pricing shows `n/a`

---

### cost

Display token usage and cost breakdown, with per-agent budget caps and runaway-session detection.

![docket cost output: per-agent token usage, dollar cost, budget caps, and a runaway-session warning](assets/cost.png)

**Syntax:**
```bash
docket cost              # All agents (aggregate)
docket cost <agent-id>   # Single agent
```

**Output format:**
```
Token Usage: myproject
────────────────────────────────────────
Model:            anthropic/claude-sonnet-4-6
Source:           builtin
Turns:            42

Input:            125,000 tokens
Output:            45,000 tokens
Cache read:        50,000 tokens
Cache write:       10,000 tokens

Total cost:       $1.11 (recorded)
```

The dollar total is the **recorded** spend reported by the OpenClaw daemon — not an estimate.
docket does not print a projected "savings if you switched models" figure: that would depend on
its hand-maintained pricing table, which has no live feed. For model choice, see `docket models`.

**Example:**
```bash
# Single agent
docket cost myproject

# All agents
docket cost

# Output:
# Token Usage (All Agents)
# ────────────────────────────────────────
# myproject:     $1.11
# taskagent:     $0.45
# Total:         $1.56
```

**Aliases:** `usage`

**Notes:**
- Dollar total is the **recorded** spend reported by the OpenClaw daemon — not an estimate
- Pricing from the bundled MODEL_PRICING snapshot (manual; not a live feed)
- docket does not print projected savings — exact spend depends on your models and pricing
- Useful for budget management and detecting runaway sessions

---

### doctor

System-wide health check and diagnostics.

**Syntax:**
```bash
docket doctor
```

**What it checks:**
1. Required dependencies (openclaw, python3; fzf optional)
2. OpenClaw config file exists and is valid JSON
3. Gateway service status
4. Workspace permissions (700/600)
5. Specialist agents present
6. Telegram bindings
7. Session key consistency
8. Missing or corrupted files

**Example:**
```bash
docket doctor

# Output:
# System Health Check
# ════════════════════════════════════════
# Dependencies
# ✓ openclaw: /usr/local/bin/openclaw
# ✓ python3: /usr/bin/python3
# ✓ fzf: /usr/bin/fzf
#
# OpenClaw
# ✓ Config file exists
# ✓ Valid JSON
# ✓ Gateway service running
#
# Specialists
# ✓ knowledge OK
# ⚠ security - Missing HEARTBEAT.md (run: docket maintain security check)
#
# Projects
# ✓ myproject - OK
# ⚠ taskagent - Permission issue (run: docket maintain taskagent check)
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

### serve

Run docket's background loop, refreshing fleet status, metrics, and health on an interval.
By default it is **read-only**: it observes and reports, it does not run any agents.

**Syntax:**
```bash
docket serve                # read-only monitor (status / metrics / health only)
docket serve --dispatch     # also drive every pod's queue through its pipeline each refresh
```

**Flags:**
- **`--dispatch`**: on each refresh, also run every pod's **pending** tasks through its pipeline
  (the same `Lead → Implementer → Reviewer → Tester` hops as [`docket pod <project> dispatch`](#pod)).
  These are **real, costed LLM turns** and are **budget-gated** per hop (against each pod's Lead
  budget cap) and traced. Each pod's dispatch is **pod-local** — there is no cross-pod path.

Plain `docket serve` never dispatches; driving agents is opt-in via `--dispatch`. See
[Agent Teams (Pods)](AGENT-TEAMS.md) for the dispatch model.

**Example:**
```bash
# Just watch the fleet (no agent turns)
docket serve

# Autonomous operation: drive every pod's queue continuously
docket serve --dispatch
```

**Aliases:** None

**Notes:**
- Read-only by default — safe to leave running for monitoring
- `--dispatch` spends real budget; over-budget tasks are left pending (not run)
- Per-task dispatch is traced (`docket trace`) for auditability

---

## Global Options

### --debug

Enable verbose debug output.

**Syntax:**
```bash
docket --debug <command>
DEBUG=1 docket <command>
```

**Example:**
```bash
docket --debug list
DEBUG=1 docket add
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
docket --help
docket -h
docket help
```

---

## Command Aliases

| Command | Aliases |
|---------|---------|
| install | setup |
| add | create, new |
| info | show |
| delete | remove, rm |
| profile | tier (deprecated) |
| workflow | wf |
| logs | log |
| cost | usage |
| doctor | check |
| context | memory (deprecated, shows redirect) |

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
| `EDITOR` | Text editor for `docket edit` | `vi` |
| `OPENCLAW_DIR` | OpenClaw directory | `~/.openclaw` |

---

## Tips & Tricks

### Interactive Pickers

If you have fzf installed, omit the agent-id for fuzzy search:

```bash
docket info      # Opens fzf picker
docket delete    # Opens fzf picker
docket logs      # Opens fzf picker
```

### Batch Operations

Use bash loops for batch operations:

```bash
# Reset all agents
for id in $(docket list | awk '{print $1}' | tail -n +2); do
  docket maintain "$id" clean
done

# Cheaper models fleet-wide: change the policy once — every
# policy-following agent updates automatically (pins are untouched)
docket models preset openrouter-free
```

### Cost Monitoring

Track daily costs:

```bash
# Add to crontab
0 23 * * * docket cost >> ~/docket-costs-$(date +%Y-%m).log
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

## Observability Commands

### trace

View, follow, and export agent action traces. Every dispatch hop emits a JSONL trace event; use `trace` to inspect them.

**Syntax:**
```bash
docket trace <session-id>                     # Render one session human-readable
docket trace tail <project>                   # Follow the latest open session live
docket trace export <project> [--since DATE]  # Raw JSONL passthrough
docket trace ingest <project>                 # Pull daemon logs into trace store
```

**Example:**
```bash
# See the most recent dispatch run for "myapp"
docket trace tail myapp

# Export all traces since a date
docket trace export myapp --since 2026-06-01
```

**Notes:**
- Traces stored at `~/.openclaw/traces/<project>/<session-id>.jsonl`
- Each dispatch hop writes events: `tool_call`, `cost_charged`, `approval_requested`, etc.

---

### metrics

Compute success rate, latency, cost, and guardrail trip counts from trace data.

**Syntax:**
```bash
docket metrics [--role <role>] [--project <project>] [--window <N>]
```

**Options:**
- **`--role`**: Filter to a specific agent role
- **`--project`**: Filter to a specific project
- **`--window N`**: Rolling window size in sessions (default from config)

---

### policies

Manage declarative guardrail policies evaluated on each agent turn.

**Syntax:**
```bash
docket policies list                     # List installed policies
docket policies show <name>              # Print one policy's JSON
docket policies init                     # Copy baseline policies (block-destructive, prompt-injection, secret-pii-redact)
docket policies test <hook> <role> <text> # Dry-run the evaluator (no traces emitted)
```

---

### approve / deny

Grant or deny a pending HITL approval token (from `approval_create` or a Telegram notification).

**Syntax:**
```bash
docket approve <token>   # Grant the pending approval
docket deny <token>      # Deny the pending approval
```

**Notes:**
- Token format: `apr-*`
- Returns exit 2 if the token is not found or already resolved
- Telegram approval buttons call these automatically; use CLI when Telegram is unavailable

---

## Next Steps

- [Agent Teams (Pods)](AGENT-TEAMS.md)
- [Workflow Guide](WORKFLOW-GUIDE.md)
- [Main README](../README.md)
