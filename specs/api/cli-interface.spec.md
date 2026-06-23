# CLI Interface Contract Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2024-01-20

## Purpose

This specification defines the complete CLI interface contract for docket, including all commands, arguments, options, and outputs.

## Scope

This specification covers:
- Command syntax and structure
- Argument parsing and validation
- Option flags and modifiers
- Output formats and structures
- Return codes and error handling
- Environment variables

## Syntax

All docket commands follow a single top-level grammar:

```
docket [global-options] <command> [command-options] [arguments]
```

- `global-options` MUST precede the command (see [Options](#options)).
- `command` MUST be one of the entries in the Command Registry below.
- `arguments` are positional and command-specific (see [Arguments](#arguments)).

When a required `agent-id` argument is omitted, commands that operate on a single agent
MUST fall back to interactive selection (fzf when available, otherwise a numbered menu).
The per-command entries in the Command Registry are the authoritative source for each
command's exact syntax.

## Arguments

Positional arguments are command-specific; the following conventions apply across commands:

| Argument | Applies to | Rules |
|----------|------------|-------|
| `agent-id` | most commands | MUST match `^[a-z0-9][a-z0-9-]*[a-z0-9]$`; MAY be omitted where an interactive picker can supply it |
| `codebase-path` | `add` | MUST be absolute or tilde-expanded; MUST exist and be readable |
| `tier` | `profile` | MUST be one of `economy`, `standard`, `premium` |
| `action` | `scope`, `keys`, `team`, `workflow` | MUST be a verb from that command's documented action set |

Unrecognized or excess positional arguments MUST produce return code 4 (invalid arguments).

## Options

Options are `--long` flags, some with a `-short` alias. The global options listed above are
accepted by every command; command-specific options are listed per command in the Command
Registry. Conventions:

- Boolean flags default to `false` and take no value (e.g. `--force`, `--debug`).
- Value options take exactly one argument (e.g. `--model <tier>`, `--period <days>`).
- `--help`/`-h` MUST be honored before any other parsing and exit 0.
- Unknown options MUST produce return code 4 (invalid arguments).

## Global Command Structure

### Syntax Pattern

```
docket [global-options] <command> [command-options] [arguments]
```

### Global Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| --help | -h | Show help message | - |
| --version | -v | Show version info | - |
| --debug | -d | Enable debug output | false |
| --quiet | -q | Suppress informational output | false |
| --config | -c | Use alternate config file | ~/.openclaw/docket.conf |
| --no-color | - | Disable colored output | false |

## Command Registry

### Core Commands

#### docket install
**Purpose**: Bootstrap OpenClaw and specialist agents
**Syntax**: `docket install [--clean] [--skip-agents] [--profile <tier>]`
**Arguments**: None
**Options**:
- `--clean`: Remove existing configuration
- `--skip-agents`: Don't create specialist agents
- `--profile <tier>`: Default model profile (economy/standard/premium)
**Output**: Progress messages and success confirmation
**Return**: 0 on success, 1-5 on various failures

#### docket add
**Purpose**: Create new project agent
**Syntax**: `docket add <agent-id> [codebase-path] [options]`
**Arguments**:
- `agent-id` (required): Unique identifier (alphanumeric + dash)
- `codebase-path` (optional): Path to project directory
**Options**:
- `--type <repo|task>`: Agent type (auto-detected if not specified)
- `--model <tier>`: Initial model profile
- `--description <text>`: Agent description
- `--no-autodetect`: Skip stack detection
**Output**: Creation progress and confirmation
**Return**: 0 on success, 3 if exists, 4 on invalid args

#### docket list
**Purpose**: Display all agents
**Syntax**: `docket list [options]`
**Arguments**: None
**Options**:
- `--format <table|json|csv>`: Output format (default: table)
- `--filter <active|stopped|all>`: Filter agents (default: all)
- `--sort <id|type|activity>`: Sort order (default: id)
**Output**: Formatted agent list
**Return**: 0 always

#### docket info
**Purpose**: Display detailed agent information
**Syntax**: `docket info <agent-id> [options]`
**Arguments**:
- `agent-id` (required): Agent identifier or interactive selection
**Options**:
- `--format <detailed|summary|json>`: Output detail level
- `--costs`: Include detailed cost breakdown
**Output**: Agent details in requested format
**Return**: 0 on success, 2 if not found

#### docket delete
**Purpose**: Remove agent completely
**Syntax**: `docket delete <agent-id> [options]`
**Arguments**:
- `agent-id` (required): Agent to delete
**Options**:
- `--force`: Skip confirmation prompt
- `--keep-logs`: Preserve memory logs before deletion
**Output**: Deletion confirmation
**Return**: 0 on success, 2 if not found

#### docket maintain
**Purpose**: Clear memory, repair, or rebuild an agent (replaces the retired `reset`/`repair`/`cleanup`)
**Syntax**: `docket maintain [agent-id] [mode]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
- `mode` (optional): Maintenance level (default: `check`)
**Modes**:
- `check`: Health check and auto-fix (was `docket repair`)
- `clean`: Clear memory day-logs (was `docket reset 1`)
- `reset`: Clean + clear MEMORY.md and HEARTBEAT.md (was `docket reset 2`)
- `rebuild`: Deep rebuild — regenerate all files from metadata (was `docket reset 3`)
- `sessions`: Archive large/old session data (was `docket cleanup safe`)
**Output**: Maintenance progress and confirmation
**Return**: 0 on success, 2 if not found, 4 on invalid mode

### Configuration Commands

#### docket profile
**Purpose**: Pin an agent's model or set a budget cap
**Syntax**: `docket profile <agent-id> [<provider/model> | default] [--budget <USD>]`
**Arguments**:
- `agent-id` (required): Target agent
- `provider/model` (optional): Pin to a specific model (e.g. `anthropic/claude-sonnet-4-6`); shows current if omitted
- `default` (optional): Re-attach to the role policy model (unpin)
**Options**:
- `--budget <USD>`: Set per-agent spend cap; `0` or `--budget 0` removes it
**Output**: Profile change confirmation or current profile
**Return**: 0 on success, 2 if not found, 4 on invalid model

#### docket models
**Purpose**: View and update the role→model policy; switch provider presets
**Syntax**: `docket models [set <role> <provider/model> | preset <name> | reset]`
**Actions**:
- (no args): Show the current role→model table (role, model, price, source, why)
- `set <role> <provider/model>`: Override the model for a specific role
- `preset <name>`: Switch all roles to a preset (e.g. `openai`, `anthropic`, `economy`)
- `reset`: Restore built-in defaults
**Output**: Role→model table or update confirmation
**Return**: 0 on success, 4 on invalid role or preset

#### docket scope
**Purpose**: Manage session keys for project isolation
**Syntax**: `docket scope <agent-id> <action> [value]`
**Arguments**:
- `agent-id` (required): Target agent
- `action` (required): show/set/reset
- `value` (conditional): Required for 'set' action
**Output**: Current or updated session key
**Return**: 0 on success, 2 if not found, 4 on invalid action

#### docket keys
**Purpose**: Manage API keys centrally; keys auto-sync to all agents
**Syntax**: `docket keys [action] [key-name]`
**Actions**:
- `list`: Show all stored keys (values masked) — default
- `setup`: Interactive setup wizard for all keys
- `add <KEY_NAME>`: Add or update a specific key
- `validate [KEY_NAME]`: Test whether keys work
- `remove <KEY_NAME>`: Remove a key
- `export`: Print keys as shell environment variables
**Key names**: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `OPENROUTER_API_KEY`
**Output**: Key status or update confirmation
**Return**: 0 on success, 4 on invalid key name
**Note**: `keys` manages *workspace* secrets (project work, synced to agent `.env`). It does NOT set model auth — use `docket auth` for that.

#### docket auth
**Purpose**: Manage how agents authenticate to the Claude model provider (front-end over `openclaw models auth`). Distinct from `docket keys`, which manages workspace secrets, not model auth.
**Syntax**: `docket auth [action]`
**Actions**:
- `status`: Show configured auth profiles and whether any is usable — default
- `setup`: Interactive chooser — Claude subscription or API key
- `login`: Configure a Claude subscription token (`setup-token`)
- `key`: Configure an API key (`paste-token`)
**Output**: Profile status or setup confirmation
**Return**: 0 on success, non-zero if the underlying flow fails or is cancelled

### Workflow Commands

#### docket workflow
**Purpose**: Manage Lobster YAML pipelines
**Syntax**: `docket workflow <agent-id> <action> [name]`
**Actions**:
- `create <name>`: Generate new workflow template
- `list`: Show agent's workflows
- `show <name>`: Display workflow content
- `delete <name>`: Remove workflow
**Output**: Workflow content or listing
**Return**: 0 on success, 2 if not found

### Team Commands

#### docket team
**Purpose**: Manage team coordination features
**Syntax**: `docket team <action> [args]`
**Actions**:
- `status`: Show specialist health and task summary
- `delegate "<task>" [--priority high]`: Queue a task for the manager
- `queue`: List pending tasks
- `done <task-id>`: Mark a task complete
**Output**: Team status or action confirmation
**Return**: 0 on success, various errors

### Memory and Context Commands

#### docket context
**Purpose**: Inspect and manage an agent's memory/context
**Syntax**: `docket context [agent-id] [action]`
**Actions**:
- `show`: Recent activity overview (default)
- `search <query>`: Search indexed memory
- `snapshot`: Create SNAPSHOT.md for fast agent context
- `index`: Rebuild the memory index
- `compress`: Archive logs older than 30 days
- `project`: Show project-level context
**Output**: Context view or action confirmation
**Return**: 0 on success, 2 if not found

#### docket edit
**Purpose**: Open an agent's workspace files in `$EDITOR`
**Syntax**: `docket edit [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Opens SOUL.md, AGENTS.md, TOOLS.md, HEARTBEAT.md in the editor
**Return**: 0 on success, 2 if not found

#### docket logs
**Purpose**: Show an agent's latest memory log and today's gateway entries
**Syntax**: `docket logs [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Latest memory day-log plus today's gateway log lines for the agent's group
**Return**: 0 on success, 2 if not found

### Maintenance Commands

#### docket doctor
**Purpose**: System diagnostics
**Syntax**: `docket doctor [--verbose]`
**Options**:
- `--verbose`: Detailed diagnostic output
**Output**: System health report
**Checks**:
- OpenClaw daemon status
- Required commands availability
- Configuration validity
- Workspace permissions
- Agent registrations
**Return**: 0 if healthy, count of issues found

#### docket cost
**Purpose**: Display usage and costs
**Syntax**: `docket cost [agent-id] [--period <days>]`
**Arguments**:
- `agent-id` (optional): Specific agent or all
**Options**:
- `--period <days>`: Time window (default: 30)
- `--by-model`: Group by model
- `--csv`: Export as CSV
**Output**: Cost breakdown table
**Return**: 0 always

### Monitoring Commands

#### docket snapshot
**Purpose**: Emit JSON system state for dashboards or CI artifacts
**Syntax**: `docket snapshot [--output <file>]`
**Options**:
- `--output <file>`: Write JSON to a file instead of stdout
**Output**: JSON object (gateway status, channels, agents)
**Return**: 0 on success

#### docket serve
**Purpose**: Serve the live snapshot JSON over HTTP for team dashboards
**Syntax**: `docket serve [--port <n>] [--interval <s>]`
**Options**:
- `--port <n>`: Listen port (default: 7331)
- `--interval <s>`: Snapshot refresh interval in seconds (default: 30)
**Output**: Serves `http://localhost:<port>/status.json`, refreshed on the interval
**Return**: 0 on clean shutdown (Ctrl-C)

### Security and Gates

#### docket gates
**Purpose**: Manage enforced exec-approval gates (opt-in; off by default)
**Syntax**: `docket gates <action>`
**Actions**:
- `status`: Show current gates configuration
- `enable`: Enable exec-approval gates (writes to openclaw.json)
- `disable`: Disable exec-approval gates
- `isolate <on|off>`: Toggle Docker workspace isolation
**Output**: Gates status or update confirmation
**Return**: 0 on success

#### docket audit
**Purpose**: Show recent operator-mutation events (keys, gates, profile, agents)
**Syntax**: `docket audit [N]`
**Arguments**:
- `N` (optional): Number of recent entries to show (default: 20)
**Output**: Timestamped log of mutating operations
**Return**: 0 always

#### docket eval
**Purpose**: Run specialist-role structural checks and optional live golden tasks
**Syntax**: `docket eval [--live]`
**Options**:
- `--live` (env: `DOCKET_EVAL_LIVE=1`): Run live tasks against the daemon (billable)
**Output**: Pass/fail per specialist role; model optimization hints
**Return**: 0 if all pass, 1 if any fail

### Observability (Phase 8)

#### docket trace
**Purpose**: View, tail, export, or ingest agent-action JSONL traces
**Syntax**: `docket trace <session-id | subcommand> [args]`
**Subcommands**:
- `<session-id>`: Render one session's events human-readable
- `tail <project>`: Follow the most-recent open session live
- `export <project> [--since YYYY-MM-DD]`: Print raw JSONL to stdout
- `ingest <project>`: Pull daemon session logs into the trace store
**Output**: Human-readable event log or raw JSONL
**Return**: 0 on success, 2 if session not found

#### docket metrics
**Purpose**: Compute success rate, latency, cost, and guardrail trip counts
**Syntax**: `docket metrics [--role <role>] [--project <project>] [--window <N>]`
**Options**:
- `--role <role>`: Filter to a specific agent role
- `--project <project>`: Filter to a specific project
- `--window <N>`: Rolling window size in sessions (default: `METRICS_WINDOW`)
**Output**: Table of success rate, mean/p95 duration, total/mean cost, guardrail trips
**Return**: 0 always

#### docket policies
**Purpose**: Manage declarative guardrail policies
**Syntax**: `docket policies <subcommand> [args]`
**Subcommands**:
- `list`: List installed policies in `$POLICIES_DIR`
- `show <name>`: Print one policy's JSON
- `init`: Copy baseline policies (block-destructive, prompt-injection, secret-pii-redact)
- `test <hook> <role> <text>`: Dry-run the evaluator (no traces emitted)
**Output**: Policy listing, JSON, or evaluation result
**Return**: 0 on success, 4 on invalid subcommand

#### docket approve
**Purpose**: Grant a pending HITL approval token
**Syntax**: `docket approve <token>`
**Arguments**:
- `token` (required): The `apr-*` token from `approval_create` or Telegram notification
**Output**: Approval confirmation
**Return**: 0 on success, 2 if token not found or already resolved

#### docket deny
**Purpose**: Deny a pending HITL approval token
**Syntax**: `docket deny <token>`
**Arguments**:
- `token` (required): The `apr-*` token from `approval_create` or Telegram notification
**Output**: Denial confirmation
**Return**: 0 on success, 2 if token not found or already resolved

### Telegram Commands

#### docket telegram
**Purpose**: Alias for `docket wire` — bind a Telegram group to an agent
**Syntax**: `docket telegram [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Same as `docket wire`
**Return**: Same as `docket wire`

#### docket wire
**Purpose**: Bind a Telegram group to an agent (see telegram-integration.spec.md)
**Syntax**: `docket wire [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Binding confirmation; restarts gateway
**Return**: 0 on success, 2 if not found

#### docket unwire
**Purpose**: Remove an agent's Telegram binding
**Syntax**: `docket unwire [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Unbind confirmation; restarts gateway
**Return**: 0 on success, 2 if not found

#### docket completions
**Purpose**: Emit a shell completion script for bash or zsh
**Syntax**: `docket completions <bash|zsh>`
**Arguments**:
- `bash` or `zsh` (required): Target shell
**Output**: Shell script — source with `eval "$(docket completions bash)"`
**Return**: 0 on success, 4 on invalid shell

### Help

#### docket help
**Purpose**: Show usage information
**Syntax**: `docket help [command]`
**Arguments**:
- `command` (optional): Show help for a specific command
**Output**: Command list or per-command usage
**Return**: 0 always

## Output Formats

### Standard Output Structure

```
[LEVEL] Message text
```

Levels:
- `[INFO]`: Informational messages (blue)
- `[SUCCESS]`: Operation completed (green)
- `[WARN]`: Warning conditions (yellow)
- `[ERROR]`: Error conditions (red)
- `[DEBUG]`: Debug output (gray, only with --debug)

### JSON Output Schema

When `--json` is specified, commands emit bare JSON objects or arrays — **no envelope wrapper**.
There is no `{success, data, error, version}` outer object. Each command's actual output shape
is documented in [specs/data/cli-json-shapes.spec.md](../data/cli-json-shapes.spec.md).

Key naming: camelCase throughout (`costUsd`, `totalUsd`, `budgetUsd`, `sessionKey`).

### Table Output Format

Default table uses column alignment:
- Left-aligned: text fields
- Right-aligned: numeric fields
- Center-aligned: status fields

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCKET_HOME` | Base directory | `~/.openclaw` |
| `DOCKET_DEBUG` | Enable debug (0/1) | 0 |
| `DOCKET_NO_COLOR` | Disable colors (0/1) | 0 |
| `DOCKET_MODEL_DEFAULT` | Default model tier | standard |
| `DOCKET_EDITOR` | Preferred editor | $EDITOR or nano |
| `OPENCLAW_API` | API endpoint | http://localhost:8000 |

## Return Code Convention

| Code | Meaning | Used By |
|------|---------|---------|
| 0 | Success | All commands |
| 1 | General failure | All commands |
| 2 | Not found | info, delete, maintain |
| 3 | Already exists | add |
| 4 | Invalid arguments | All commands |
| 5 | Permission denied | add, delete, maintain |
| 6 | Corruption detected | maintain, doctor |
| 7 | Daemon error | All commands |
| 8 | Network error | keys, workflow |
| 9 | Timeout | All commands |
| 127 | Command not found | doctor |

## Validation

Input validation rules that every command MUST enforce before performing side effects.
The authoritative rule set lives in [input-validation.spec.md](../validation/input-validation.spec.md);
the contract-level summary follows.

### Agent ID Validation
- Pattern: `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- Length: 3-50 characters
- Reserved IDs: manager, system, docket, openclaw

### Path Validation
- Must be absolute or tilde-expanded
- Must exist (for codebase paths)
- Must be readable

### Model Validation
- Must exist in MODEL_PROFILES
- Case-insensitive matching

### Numeric Validation
- Reset level: 1-3
- Cost period: 1-365
- Timeout values: 1-3600

## Interactive Features

### Project Picker
When agent-id is omitted for commands that need it:
1. Try fzf if available
2. Fall back to numbered menu
3. Allow typing ID directly

### Confirmation Prompts
Required for destructive operations:
- `docket delete` (unless --force)
- `docket maintain` reset/rebuild
- `docket install --clean`

Format: `"Action description. Continue? (y/N): "`

## Error Message Standards

### Format
```
[ERROR] <component>: <description>
        Details: <specifics>
        Suggestion: <how to fix>
```

### Example
```
[ERROR] Agent not found: myproject
        Details: No workspace at ~/.openclaw/workspaces/projects/myproject
        Suggestion: Use 'docket list' to see available agents
```

## Performance Requirements

### Response Times
- Simple queries (list, info): < 500ms
- Creation operations: < 2s
- Deletion operations: < 1s
- Repair operations: < 5s
- Cost calculations: < 3s for 30 days

### Resource Limits
- Max JSON parsing: 10MB
- Max memory log: 100MB
- Max agents: 1000
- Max workflows per agent: 100

## Backwards Compatibility

### Version Detection
- Check ~/.openclaw/version file
- Migrate configs if needed
- Warn on version mismatch

### Deprecated Features
- `docket reset <level>` → Use `docket maintain clean|reset|rebuild`
- `docket repair` → Use `docket maintain check`
- `docket cleanup` → Use `docket maintain sessions`
- `docket model` → Use `docket profile`
- Direct JSON editing → Use docket commands

## Changelog

### Version 1.1.0 (2026-06-09)
- Synced the command registry with the shipped CLI
- Replaced retired `reset`/`repair`/`model` with `maintain` and `mode`
- Added `context`, `edit`, `logs`, `snapshot`, `serve`, `wire`, `unwire`, `help`
- Corrected the `team` action set and return-code usage

### Version 1.0.0 (2024-01-20)
- Complete CLI interface specification
- All commands documented
- Return codes standardized
- Validation rules defined