# Development Guide

Guide for developers contributing to rack or extending it for custom needs.

## Table of Contents

- [Development Setup](#development-setup)
- [Codebase Structure](#codebase-structure)
- [Adding New Commands](#adding-new-commands)
- [Testing](#testing)
- [Code Style](#code-style)
- [Contributing](#contributing)

## Development Setup

### Prerequisites

- **bash** 4.0+
- **python3** 3.7+
- **git**
- **openclaw** (latest)
- **fzf** (optional, recommended)

### Clone and Setup

```bash
# Clone repository
git clone https://github.com/yourusername/rack-cli.git
cd rack-cli

# Make executable
chmod +x bin/rack

# Add to PATH for development
export PATH="$PWD/bin:$PATH"

# Or use symlink
sudo ln -s "$PWD/bin/rack" /usr/local/bin/rack

# Verify
rack --help
```

### Run Tests

```bash
# Full lifecycle test
./tests/test-lifecycle.sh

# Keep test agent for inspection
./tests/test-lifecycle.sh --keep

# Clean install + test
./tests/test-lifecycle.sh --clean

# Debug mode
DEBUG=1 ./tests/test-lifecycle.sh
```

### Development Workflow

```bash
# Create feature branch
git checkout -b feature/my-feature

# Make changes to bin/rack
vim bin/rack

# Test changes
./tests/test-lifecycle.sh

# Debug specific command
DEBUG=1 rack mycommand

# Commit with conventional commits
git commit -m "feat: add new command for X"

# Push and create PR
git push origin feature/my-feature
```

## Codebase Structure

### Current Structure

```
rack-cli/
├── bin/
│   └── rack                    # 2,591 lines - entire CLI
├── docs/
│   ├── README.md
│   ├── architecture.md
│   ├── installation.md
│   ├── commands.md
│   └── development.md          # This file
├── tests/
│   └── test-lifecycle.sh       # Integration tests
├── examples/
│   ├── workflows/
│   │   ├── ci-pipeline.lobster.yml
│   │   └── code-review.lobster.yml
│   └── configs/                # (to be created)
├── CLAUDE.md                   # AI assistant instructions
├── README.md
└── LICENSE
```

### Module Organization

The CLI follows a modular architecture with clear separation:

**Core** (`lib/core/`):
- `init.sh` - Strict mode and debug settings
- `config.sh` - Configuration (paths, colors, models, pricing)
- `router.sh` - Command dispatcher

**Helpers** (`lib/helpers/`):
- `output.sh` - Output formatting (info, success, warn, error)
- `json.sh` - JSON manipulation (meta_get, meta_set, bindings)
- `session.sh` - Session key management
- `picker.sh` - Interactive project picker (fzf or fallback)
- `service.sh` - Service control (restart_gateway)
- `utils.sh` - Utilities (slugify, detect_stack, etc.)
- `workspace.sh` - Workspace creation and management

**Commands** (`lib/commands/`):
- Each file contains one `cmd_*` function
- 19 commands total (list, add, info, delete, reset, repair, etc.)

**Entry Point** (`bin/rack`):
- Sources all modules
- Parses arguments
- Calls router

This makes navigation easy:

```bash
# Find specific function
grep -r "cmd_list" lib/commands/

# View a specific module
cat lib/helpers/session.sh
```

## Adding New Commands

### Step 1: Create Command File

Create a new file in `lib/commands/`:

```bash
# lib/commands/mycommand.sh
#!/usr/bin/env bash
# Command: mycommand

cmd_mycommand() {
  local id="${1:-}"

  # Interactive picker if ID omitted
  [[ -z "$id" ]] && id=$(pick_project "Select project")

  # Validate agent exists
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Agent '$id' not found"

  # Your implementation here
  info "Processing agent '$id'..."

  # Example: Read metadata
  local agent_name; agent_name=$(meta_get "$id" "name" "Unknown")
  local agent_type; agent_type=$(meta_get "$id" "type" "repo")

  # Example: Update metadata
  meta_set "$id" "lastRun" "$(date -Iseconds)"

  # Example: Show success
  success "Command executed successfully"
}
```

### Step 2: Source in Entry Point

Add to `bin/rack`:

```bash
# Source command modules
source "$LIB_DIR/commands/mycommand.sh"
```

### Step 3: Add to Router

Add to `lib/core/router.sh`:

```bash
route_command() {
  local cmd="${1:-list}"
  shift || true

  case "$cmd" in
    # ... existing commands ...
    mycommand|mc)      cmd_mycommand "$@" ;;  # mc is an alias
    # ... more commands ...
  esac
}
```

### Step 3: Update Help Text

Add your command to the help output:

```bash
cmd_help() {
  cat <<HELP
${BOLD}rack${RESET} — OpenClaw project agent manager

${BOLD}LIFECYCLE${RESET}
  ${GREEN}list${RESET}                      List all project agents
  ${GREEN}add${RESET}                       Add a new project agent
  # ... existing commands ...

${BOLD}CUSTOM${RESET}
  ${GREEN}mycommand${RESET} [id]            Description of your command
                              Alias: ${DIM}mc${RESET}

${BOLD}UTILITIES${RESET}
  # ... existing commands ...
HELP
}
```

### Step 4: Add Tests

Add test cases to `tests/test-lifecycle.sh`:

```bash
# At the end of the test file, before cleanup

section "TEST 15: rack mycommand"
OUTPUT=$("$RACK" mycommand test-agent 2>&1)
if echo "$OUTPUT" | grep -q "Command executed successfully"; then
  pass "mycommand works"
else
  fail "mycommand failed: $OUTPUT"
fi
```

### Step 5: Update Documentation

Add documentation to `docs/commands.md`:

```markdown
### mycommand

Short description of what it does.

**Syntax:**
```bash
rack mycommand <agent-id>
rack mycommand             # Interactive picker
```

**Example:**
```bash
rack mycommand myproject
# Output: Command executed successfully
```

**Aliases:** `mc`

**Notes:**
- Additional notes here
```

## Testing

### Test Structure

```bash
tests/test-lifecycle.sh
├── Preamble (colors, helpers)
├── Setup (create test agent)
├── Test sections
│   ├── TEST 1: rack list
│   ├── TEST 2: rack info
│   ├── TEST 3: rack scope
│   ├── ... more tests
│   └── TEST N: rack delete
└── Cleanup (remove test agent if --keep not passed)
```

### Running Tests

```bash
# Standard test
./tests/test-lifecycle.sh

# Keep test agent after run
./tests/test-lifecycle.sh --keep

# Clean install first
./tests/test-lifecycle.sh --clean

# Debug mode
DEBUG=1 ./tests/test-lifecycle.sh

# Test specific command manually
DEBUG=1 rack mycommand test-agent
```

### Writing Tests

Test template:

```bash
section "TEST N: Description"
OUTPUT=$("$RACK" command arg 2>&1)
if echo "$OUTPUT" | grep -q "expected text"; then
  pass "test passed"
else
  fail "test failed: $OUTPUT"
fi
```

Example:

```bash
section "TEST 10: rack scope set"
OUTPUT=$("$RACK" scope test-agent set alpha 2>&1)
if echo "$OUTPUT" | grep -q "Session key updated"; then
  pass "scope set works"
else
  fail "scope set failed: $OUTPUT"
fi

# Verify the change
SESSION_KEY=$(meta_get test-agent sessionKey)
if [[ "$SESSION_KEY" == "agent:test-agent:alpha" ]]; then
  pass "session key correctly updated"
else
  fail "session key mismatch: expected agent:test-agent:alpha, got $SESSION_KEY"
fi
```

### Test Coverage

Current coverage:

- ✅ Installation and bootstrap
- ✅ Agent lifecycle (add, list, info, delete)
- ✅ Session scoping (show, set, reset)
- ✅ Team coordination (status, init, check)
- ✅ Workflow management (create, list, show, delete)
- ✅ Cost tracking and model profiles
- ✅ Repair and health checks
- ⬜ Telegram wire/unwire (requires real Telegram setup)
- ⬜ Edge cases (missing files, corrupted JSON, etc.)

## Code Style

### Bash Best Practices

```bash
# Use strict mode
set -euo pipefail

# Quote variables
local name="$1"           # Good
local name=$1             # Bad (breaks with spaces)

# Use [[ ]] for conditionals
[[ -f "$file" ]]          # Good
[ -f $file ]              # Bad (deprecated, unquoted)

# Check array length
[[ ${#args[@]} -gt 0 ]]   # Good

# Use || true for commands that may fail
optional_check || true    # Good (won't exit on failure)
optional_check            # Bad (will exit if set -e)
```

### Naming Conventions

```bash
# Functions: snake_case
cmd_list() { ... }
generate_session_key() { ... }
_create_workspace() { ... }   # Leading _ for internal functions

# Variables: snake_case
local agent_id="myproject"
local workspace_dir="/path"

# Constants: UPPER_CASE
OPENCLAW_DIR="$HOME/.openclaw"
DEFAULT_MODEL="anthropic/claude-sonnet-4-6"

# Arrays: plural names
declare -a project_ids
declare -A MODEL_PRICING
```

### Output Helpers

```bash
# Use semantic helpers
info "Starting process..."        # Blue arrow →
success "Done!"                    # Green checkmark ✓
warn "Potential issue"             # Yellow warning ⚠
error "Fatal error"                # Red X ✗ + exit 1
fail "Non-fatal error"             # Red X ✗ (no exit)
dbg "Debug info"                   # Gray [dbg] (only if DEBUG=1)

# Use headers for sections
header "Section Title"             # Bold text with newline

# Use dim for secondary info
dim "Additional details"           # Gray dimmed text
```

### Error Handling

```bash
# Exit on fatal errors
[[ ! -f "$config" ]] && error "Config file not found"

# Provide hints
error_hint "Agent not found" "Run: rack list"

# Non-fatal warnings
[[ ! -f "$optional_file" ]] && warn "Optional file missing (not critical)"

# Silent failures for optional features
fzf_available=$(command -v fzf &>/dev/null && echo "yes" || echo "no")
```

### Permissions

```bash
# Directories: 700 (owner only)
mkdir -p "$workspace"
chmod 700 "$workspace"

# Files: 600 (owner read/write only)
touch "$metadata_file"
chmod 600 "$metadata_file"
```

### JSON Manipulation

Use embedded Python for JSON operations:

```bash
# Read JSON field
meta_get() {
  local id="$1"
  local key="$2"
  local default="${3:-}"
  local meta_file="$PROJECTS_DIR/$id/$META_FILE"

  [[ ! -f "$meta_file" ]] && echo "$default" && return

  python3 - "$meta_file" "$key" "$default" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    print(data.get(sys.argv[2], sys.argv[3]))
except:
    print(sys.argv[3])
PY
}

# Write JSON field
meta_set() {
  local id="$1"
  local key="$2"
  local value="$3"
  local meta_file="$PROJECTS_DIR/$id/$META_FILE"

  python3 - "$meta_file" "$key" "$value" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}

data[sys.argv[2]] = sys.argv[3]

with open(sys.argv[1], 'w') as f:
    json.dump(data, f, indent=2)
PY
}
```

### Debug Mode

Support DEBUG mode in all functions:

```bash
cmd_mycommand() {
  local id="$1"

  dbg "Entered cmd_mycommand with id='$id'"

  local workspace="$PROJECTS_DIR/$id"
  dbg "Workspace path: $workspace"

  [[ ! -d "$workspace" ]] && error "Agent '$id' not found"

  dbg "Agent found, proceeding..."

  # Implementation
}
```

## Contributing

### Commit Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: Add new command for workflow execution
fix: Repair session key sync issue
docs: Update commands.md with new examples
refactor: Extract JSON helpers to lib/helpers/json.sh
test: Add unit tests for session key generation
chore: Update dependencies
```

### Pull Request Process

1. **Fork** the repository
2. **Create feature branch**: `git checkout -b feature/my-feature`
3. **Make changes** with clear, focused commits
4. **Run tests**: `./tests/test-lifecycle.sh`
5. **Update docs** if adding features
6. **Push**: `git push origin feature/my-feature`
7. **Create PR** with description of changes

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Ran `./tests/test-lifecycle.sh` successfully
- [ ] Added new test cases
- [ ] Tested manually

## Checklist
- [ ] Code follows project style
- [ ] Self-reviewed code
- [ ] Updated documentation
- [ ] No breaking changes (or documented)
```

### Code Review Criteria

Reviewers will check:

1. **Functionality**: Does it work as intended?
2. **Tests**: Are there tests? Do they pass?
3. **Style**: Follows code style guidelines?
4. **Documentation**: Is it documented?
5. **Security**: No vulnerabilities introduced?
6. **Backwards compatibility**: Does it break existing features?

## Next Steps

- [Architecture Documentation](architecture.md)
- [Command Reference](commands.md)
- [Installation Guide](installation.md)
- [Main README](../README.md)

## Resources

- [Bash Guide](https://mywiki.wooledge.org/BashGuide)
- [ShellCheck](https://www.shellcheck.net/) - Static analysis tool
- [Google Shell Style Guide](https://google.github.io/styleguide/shellguide.html)
- [Defensive Bash Programming](https://kfirlavi.herokuapp.com/blog/2012/11/14/defensive-bash-programming/)
