# CLI Interface Contract Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2024-01-20

## Purpose

This specification defines the complete CLI interface contract for rack, including all commands, arguments, options, and outputs.

## Scope

This specification covers:
- Command syntax and structure
- Argument parsing and validation
- Option flags and modifiers
- Output formats and structures
- Return codes and error handling
- Environment variables

## Syntax

All rack commands follow a single top-level grammar:

```
rack [global-options] <command> [command-options] [arguments]
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
rack [global-options] <command> [command-options] [arguments]
```

### Global Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| --help | -h | Show help message | - |
| --version | -v | Show version info | - |
| --debug | -d | Enable debug output | false |
| --quiet | -q | Suppress informational output | false |
| --config | -c | Use alternate config file | ~/.openclaw/rack.conf |
| --no-color | - | Disable colored output | false |

## Command Registry

### Core Commands

#### rack install
**Purpose**: Bootstrap OpenClaw and specialist agents
**Syntax**: `rack install [--clean] [--skip-agents] [--profile <tier>]`
**Arguments**: None
**Options**:
- `--clean`: Remove existing configuration
- `--skip-agents`: Don't create specialist agents
- `--profile <tier>`: Default model profile (economy/standard/premium)
**Output**: Progress messages and success confirmation
**Return**: 0 on success, 1-5 on various failures

#### rack add
**Purpose**: Create new project agent
**Syntax**: `rack add <agent-id> [codebase-path] [options]`
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

#### rack list
**Purpose**: Display all agents
**Syntax**: `rack list [options]`
**Arguments**: None
**Options**:
- `--format <table|json|csv>`: Output format (default: table)
- `--filter <active|stopped|all>`: Filter agents (default: all)
- `--sort <id|type|activity>`: Sort order (default: id)
**Output**: Formatted agent list
**Return**: 0 always

#### rack info
**Purpose**: Display detailed agent information
**Syntax**: `rack info <agent-id> [options]`
**Arguments**:
- `agent-id` (required): Agent identifier or interactive selection
**Options**:
- `--format <detailed|summary|json>`: Output detail level
- `--costs`: Include detailed cost breakdown
**Output**: Agent details in requested format
**Return**: 0 on success, 2 if not found

#### rack delete
**Purpose**: Remove agent completely
**Syntax**: `rack delete <agent-id> [options]`
**Arguments**:
- `agent-id` (required): Agent to delete
**Options**:
- `--force`: Skip confirmation prompt
- `--keep-logs`: Preserve memory logs before deletion
**Output**: Deletion confirmation
**Return**: 0 on success, 2 if not found

#### rack maintain
**Purpose**: Clear memory, repair, or rebuild an agent (replaces the retired `reset`/`repair`/`cleanup`)
**Syntax**: `rack maintain [agent-id] [mode]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
- `mode` (optional): Maintenance level (default: `check`)
**Modes**:
- `check`: Health check and auto-fix (was `rack repair`)
- `clean`: Clear memory day-logs (was `rack reset 1`)
- `reset`: Clean + clear MEMORY.md and HEARTBEAT.md (was `rack reset 2`)
- `rebuild`: Deep rebuild — regenerate all files from metadata (was `rack reset 3`)
- `sessions`: Archive large/old session data (was `rack cleanup safe`)
**Output**: Maintenance progress and confirmation
**Return**: 0 on success, 2 if not found, 4 on invalid mode

### Configuration Commands

#### rack profile
**Purpose**: Set model tier for agent
**Syntax**: `rack profile <agent-id> [tier]`
**Arguments**:
- `agent-id` (required): Target agent
- `tier` (optional): economy/standard/premium (shows current if omitted)
**Output**: Profile change confirmation or current profile
**Return**: 0 on success, 2 if not found, 4 on invalid tier

#### rack mode
**Purpose**: Show or set an agent's execution backend
**Syntax**: `rack mode [agent-id] [mode]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
- `mode` (optional): `api`, `terminal`, or `status` (shows current if omitted)
**Modes**:
- `api`: Use the API backend (default; consumes tokens)
- `terminal`: Use local terminal mode (zero API cost)
- `status`: Show the current mode without changing it
**Output**: Current or updated mode
**Return**: 0 on success, 2 if not found, 4 on invalid mode

#### rack scope
**Purpose**: Manage session keys for project isolation
**Syntax**: `rack scope <agent-id> <action> [value]`
**Arguments**:
- `agent-id` (required): Target agent
- `action` (required): show/set/reset
- `value` (conditional): Required for 'set' action
**Output**: Current or updated session key
**Return**: 0 on success, 2 if not found, 4 on invalid action

#### rack keys
**Purpose**: Manage API keys centrally; keys auto-sync to all agents
**Syntax**: `rack keys [action] [key-name]`
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

### Workflow Commands

#### rack workflow
**Purpose**: Manage Lobster YAML pipelines
**Syntax**: `rack workflow <agent-id> <action> [name]`
**Actions**:
- `create <name>`: Generate new workflow template
- `list`: Show agent's workflows
- `show <name>`: Display workflow content
- `delete <name>`: Remove workflow
**Output**: Workflow content or listing
**Return**: 0 on success, 2 if not found

### Team Commands

#### rack team
**Purpose**: Manage team coordination features
**Syntax**: `rack team <action> [args]`
**Actions**:
- `status`: Show specialist health and task summary
- `delegate "<task>" [--priority high]`: Queue a task for the manager
- `queue`: List pending tasks
- `done <task-id>`: Mark a task complete
**Output**: Team status or action confirmation
**Return**: 0 on success, various errors

### Memory and Context Commands

#### rack context
**Purpose**: Inspect and manage an agent's memory/context
**Syntax**: `rack context [agent-id] [action]`
**Actions**:
- `show`: Recent activity overview (default)
- `search <query>`: Search indexed memory
- `snapshot`: Create SNAPSHOT.md for fast agent context
- `index`: Rebuild the memory index
- `compress`: Archive logs older than 30 days
- `project`: Show project-level context
**Output**: Context view or action confirmation
**Return**: 0 on success, 2 if not found

#### rack edit
**Purpose**: Open an agent's workspace files in `$EDITOR`
**Syntax**: `rack edit [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Opens SOUL.md, AGENTS.md, TOOLS.md, HEARTBEAT.md in the editor
**Return**: 0 on success, 2 if not found

#### rack logs
**Purpose**: Show an agent's latest memory log and today's gateway entries
**Syntax**: `rack logs [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Latest memory day-log plus today's gateway log lines for the agent's group
**Return**: 0 on success, 2 if not found

### Maintenance Commands

#### rack doctor
**Purpose**: System diagnostics
**Syntax**: `rack doctor [--verbose]`
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

#### rack cost
**Purpose**: Display usage and costs
**Syntax**: `rack cost [agent-id] [--period <days>]`
**Arguments**:
- `agent-id` (optional): Specific agent or all
**Options**:
- `--period <days>`: Time window (default: 30)
- `--by-model`: Group by model
- `--csv`: Export as CSV
**Output**: Cost breakdown table
**Return**: 0 always

### Monitoring Commands

#### rack snapshot
**Purpose**: Emit JSON system state for dashboards or CI artifacts
**Syntax**: `rack snapshot [--output <file>]`
**Options**:
- `--output <file>`: Write JSON to a file instead of stdout
**Output**: JSON object (gateway status, channels, agents)
**Return**: 0 on success

#### rack serve
**Purpose**: Serve the live snapshot JSON over HTTP for team dashboards
**Syntax**: `rack serve [--port <n>] [--interval <s>]`
**Options**:
- `--port <n>`: Listen port (default: 7331)
- `--interval <s>`: Snapshot refresh interval in seconds (default: 30)
**Output**: Serves `http://localhost:<port>/status.json`, refreshed on the interval
**Return**: 0 on clean shutdown (Ctrl-C)

### Telegram Commands

#### rack wire
**Purpose**: Bind a Telegram group to an agent (see telegram-integration.spec.md)
**Syntax**: `rack wire [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Binding confirmation; restarts gateway
**Return**: 0 on success, 2 if not found

#### rack unwire
**Purpose**: Remove an agent's Telegram binding
**Syntax**: `rack unwire [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Unbind confirmation; restarts gateway
**Return**: 0 on success, 2 if not found

### Help

#### rack help
**Purpose**: Show usage information
**Syntax**: `rack help [command]`
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

When `--format json` is specified:

```json
{
  "success": boolean,
  "data": object | array,
  "error": string | null,
  "timestamp": "ISO-8601",
  "version": "1.0.0"
}
```

### Table Output Format

Default table uses column alignment:
- Left-aligned: text fields
- Right-aligned: numeric fields
- Center-aligned: status fields

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `RACK_HOME` | Base directory | `~/.openclaw` |
| `RACK_DEBUG` | Enable debug (0/1) | 0 |
| `RACK_NO_COLOR` | Disable colors (0/1) | 0 |
| `RACK_MODEL_DEFAULT` | Default model tier | standard |
| `RACK_EDITOR` | Preferred editor | $EDITOR or nano |
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
- Reserved IDs: manager, system, rack, openclaw

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
- `rack delete` (unless --force)
- `rack maintain` reset/rebuild
- `rack install --clean`

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
        Suggestion: Use 'rack list' to see available agents
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
- `rack reset <level>` → Use `rack maintain clean|reset|rebuild`
- `rack repair` → Use `rack maintain check`
- `rack cleanup` → Use `rack maintain sessions`
- `rack model` → Use `rack profile`
- Direct JSON editing → Use rack commands

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