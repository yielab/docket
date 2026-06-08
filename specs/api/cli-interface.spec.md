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

#### rack reset
**Purpose**: Clear agent memory/state
**Syntax**: `rack reset <agent-id> [level]`
**Arguments**:
- `agent-id` (required): Agent to reset
- `level` (optional): Reset depth 1-3 (default: 1)
**Validation**: Level must be 1, 2, or 3
**Output**: Reset progress and confirmation
**Return**: 0 on success, 2 if not found, 4 on invalid level

### Configuration Commands

#### rack profile
**Purpose**: Set model tier for agent
**Syntax**: `rack profile <agent-id> [tier]`
**Arguments**:
- `agent-id` (required): Target agent
- `tier` (optional): economy/standard/premium (shows current if omitted)
**Output**: Profile change confirmation or current profile
**Return**: 0 on success, 2 if not found, 4 on invalid tier

#### rack model
**Purpose**: Set specific model version
**Syntax**: `rack model <agent-id> <model-name>`
**Arguments**:
- `agent-id` (required): Target agent
- `model-name` (required): Specific model identifier
**Validation**: Model must exist in MODEL_PROFILES
**Output**: Model change confirmation
**Return**: 0 on success, 2 if not found, 4 on invalid model

#### rack scope
**Purpose**: Manage session keys for project isolation
**Syntax**: `rack scope <agent-id> <action> [value]`
**Arguments**:
- `agent-id` (required): Target agent
- `action` (required): get/set/reset
- `value` (conditional): Required for 'set' action
**Output**: Current or updated session key
**Return**: 0 on success, 2 if not found, 4 on invalid action

#### rack keys
**Purpose**: Manage API keys centrally
**Syntax**: `rack keys [action] [provider] [value]`
**Actions**:
- `list`: Show all configured keys
- `set <provider> <key>`: Set provider key
- `remove <provider>`: Remove provider key
- `sync`: Propagate to all agents
**Providers**: anthropic, openai, google, groq, openrouter
**Output**: Key status or update confirmation
**Return**: 0 on success, 4 on invalid provider

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
- `init`: Create manager agent
- `status`: Show team status and tasks
- `assign <task> <agent>`: Delegate task
- `sync`: Update task states
**Output**: Team status or action confirmation
**Return**: 0 on success, various errors

### Maintenance Commands

#### rack repair
**Purpose**: Fix workspace issues
**Syntax**: `rack repair <agent-id> [--check-only]`
**Options**:
- `--check-only`: Report issues without fixing
**Output**: Issues found and fixes applied
**Return**: 0 if healthy/fixed, 6 if corrupted

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
| 2 | Not found | info, delete, reset, repair |
| 3 | Already exists | add |
| 4 | Invalid arguments | All commands |
| 5 | Permission denied | add, delete, repair |
| 6 | Corruption detected | repair, doctor |
| 7 | Daemon error | All commands |
| 8 | Network error | keys, workflow |
| 9 | Timeout | All commands |
| 127 | Command not found | doctor |

## Input Validation Rules

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
- `rack reset` level 2/3
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
- `rack terminal` → Use native terminal
- `rack maintain` → Use `rack repair`
- Direct JSON editing → Use rack commands

## Changelog

### Version 1.0.0 (2024-01-20)
- Complete CLI interface specification
- All commands documented
- Return codes standardized
- Validation rules defined