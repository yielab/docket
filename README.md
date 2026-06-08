# rack-cli

[![CI](https://github.com/santiagoyie/rack-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/santiagoyie/rack-cli/actions/workflows/ci.yml)

A modular Bash CLI for managing OpenClaw autonomous agents with project isolation and workflow automation.

## Motivation

I built rack to simplify OpenClaw agent orchestration across multiple projects. Instead of manually editing JSON configs and managing workspace directories, rack provides a unified interface with session-based project isolation and automated workspace provisioning.

## Project Status

| Feature | Status | Notes |
|---------|--------|-------|
| Agent lifecycle (add/delete/reset) | ✅ Working | Full CRUD via `rack maintain` |
| Session scoping & isolation | ✅ Working | Multi-project isolation via session keys |
| Specialist agents team | ✅ Working | 6 pre-configured roles |
| Lobster workflow integration | ✅ Working | YAML pipeline support |
| Cost tracking & budget caps | ✅ Working | 3 model tiers, per-agent budget, runaway detection |
| API key management | ✅ Working | Centralized key distribution |
| CI pipeline | ✅ Working | GitHub Actions on every push/PR |
| Telegram integration | ✅ Working | Manual wire: create group, add bot, run `rack wire` |
| Terminal mode | ⚙️ Experimental | `RACK_EXPERIMENTAL=1 rack terminal`; or use `rack mode terminal` |
| Manager coordination | ⚠️ Limited | Basic task queue only; full delegation in backlog |

## Installation

```bash
# Clone repository
git clone https://github.com/santiagoyie/rack-cli.git
cd rack-cli

# Make available in PATH
sudo ln -s "$(pwd)/bin/rack" /usr/local/bin/rack

# Initialize OpenClaw and specialist agents
rack install
```

**Prerequisites:**
- Bash 4.0+
- Python 3.7+
- [OpenClaw](https://openclaw.dev) daemon
- systemctl (for service management)
- fzf (optional, for interactive selection)

## Quick Start

```bash
# Create project agent
rack add myproject ~/code/myproject

# List agents
rack list

# Check agent info
rack info myproject

# Change model profile (economy/standard/premium)
rack profile myproject economy

# Set $5 spending cap
rack profile myproject --budget 5

# Clear agent memory
rack maintain myproject clean

# Delete agent
rack delete myproject
```

## Architecture

The project consists of ~8,900 lines of Bash (CLI + tests):

```
rack-cli/
├── bin/rack                         # Entry point (~110 lines)
├── lib/
│   ├── core/                        # Init, config, routing (3 files)
│   ├── helpers/                     # Reusable utilities (9 files)
│   ├── commands/                    # 22 command implementations
│   └── commands/experimental/       # 3 experimental files (RACK_EXPERIMENTAL=1)
└── tests/
    ├── unit/                        # 77 unit tests (100% passing)
    ├── test-lifecycle.sh            # 12 integration scenarios (60 assertions)
    └── evals/                       # 6 specialist-role eval stubs
```

Each agent maintains an isolated workspace:
- `SOUL.md` - Agent identity and session key
- `AGENTS.md` - Team delegation rules
- `TOOLS.md` - Project-specific commands
- `HEARTBEAT.md` - Active tasks/monitoring
- `.rack-meta.json` - Agent metadata
- `memory/` - Daily conversation logs

Configuration synchronizes between:
- `.rack-meta.json` in each workspace (rack metadata)
- `~/.openclaw/openclaw.json` (OpenClaw daemon config)

## Command Reference

### Core Commands

```bash
rack install              # Bootstrap OpenClaw and agents
rack add [id] [path]      # Create project agent
rack list                 # Show all agents
rack info <id>            # Display agent details
rack delete <id>          # Remove agent
rack maintain <id> clean  # Clear agent memory (see Maintenance below)
```

### Configuration

```bash
rack profile <id> [tier]  # Set model tier (economy/standard/premium)
rack scope <id> set <key> # Change project session key
rack keys                 # Manage API keys
rack cost [id]            # Show token usage and costs
```

### Maintenance

```bash
rack maintain [id] check    # Health check and auto-fix
rack maintain [id] clean    # Clear memory logs
rack maintain [id] reset    # Clear memory + heartbeat
rack maintain [id] rebuild  # Full rebuild from metadata
rack maintain [id] sessions # Archive large/old sessions
rack doctor                 # System-wide diagnostics (budget, drift, runaway)
```

### Context & Memory

```bash
rack context [id]              # Recent activity overview
rack context [id] search <q>   # Search indexed memory
rack context [id] snapshot     # Create SNAPSHOT.md for fast agent context
rack context [id] compress     # Archive logs older than 30 days
```

### Team Delegation

```bash
rack team delegate "Fix the login bug"             # Queue task for manager
rack team delegate --priority high "Security audit" # High-priority task
rack team queue                                     # Show pending tasks
rack team done <task-id>                            # Mark task complete
```

### Advanced Features

```bash
rack workflow <id> create <name>  # Create Lobster pipeline
rack mode <id> terminal           # Switch to terminal mode (zero API cost)
rack profile <id> --budget 5      # Set $5 spending cap
```

### Model Profiles

| Profile | Model | Cost (per MTok) | Use Case |
| ------- | ----- | --------------- | -------- |
| economy | claude-haiku-4-5 | $0.80/$4 | Routine tasks |
| standard | claude-sonnet-4-6 | $3/$15 | Active development |
| premium | claude-opus-4-6 | $15/$75 | Complex architecture |

## Session Isolation

Each agent uses session keys (`agent:<id>:<project>`) to:

- Prevent cross-project contamination
- Enable parallel project work
- Maintain separate memory contexts

```bash
rack scope myproject set alpha    # Switch to alpha context
rack scope myproject reset        # Return to default
```

## Testing

```bash
# Run all tests
./tests/run-all-tests.sh

# Unit tests only (77 tests, 100% passing)
./tests/unit/test-helpers.sh

# Integration tests (12 lifecycle scenarios, 60 assertions)
./tests/test-lifecycle.sh
./tests/test-lifecycle.sh --keep  # Keep test agent for inspection

# Specialist-role evals (6 stubs)
./tests/evals/run-evals.sh
```

**Current status:** all suites green — 77 unit, 60 integration (2 skipped), 5 evals (1 skipped).

## Development

### SSD (Spec-Driven Development) Workflow

This project follows strict SSD practices. All features must be specified before implementation:

1. **Write Specification First** (`specs/`)
   - Functional specs in `specs/functional/`
   - API contracts in `specs/api/`
   - Acceptance criteria in `specs/acceptance/`

2. **Test-Driven Development**
   - Write failing tests based on specs
   - Implement minimal code to pass
   - Refactor while maintaining tests

3. **Validate Specifications**

   ```bash
   ./scripts/validate-specs.sh    # Check spec completeness
   ./scripts/spec-coverage.sh     # Analyze coverage
   ```

4. **Continuous Validation**
   - Pre-commit hooks validate specs
   - CI/CD enforces spec compliance
   - Breaking changes require spec updates

See [specs/README.md](specs/README.md) for complete SSD documentation.

### Adding a Command (SSD Process)

1. **Create specification** in `specs/functional/command-name.spec.md`

2. **Write tests** in `tests/integration/test-command.sh`

3. **Implement command** in `lib/commands/newcommand.sh`:

   ```bash
   cmd_newcommand() {
     local id="${1:-}"
     [[ -z "$id" ]] && id=$(pick_project "Select project")

     # Implementation matching spec
     success "Command executed!"
   }
   ```

4. **Update documentation** and ensure specs are current

### Conventions

- Strict mode: `set -euo pipefail`
- Functions return via echo, exit codes for status
- JSON operations use embedded Python
- Workspace permissions: 700 dirs, 600 files
- Debug output: `DEBUG=1 rack <command>`
- All features require specifications before implementation
- Tests must be written before code (TDD)
- Specifications use RFC 2119 keywords (MUST, SHOULD, MAY)

## What's Next

1. Flesh out the eval harness (`tests/evals/`) — golden task stubs per specialist role exist and pass; expand into real model-routing checks
2. Full manager delegation (currently a basic task queue only)

## Contributing

This project uses pure Bash with modular architecture. PRs welcome for:

- Additional OpenClaw integrations
- Command implementations
- Test coverage improvements
- Documentation

## License

MIT

## Author

Santiago Yie - Backend/Platform Engineer

---

*This is a personal project demonstrating CLI development, system integration, and agent orchestration patterns. Actively used for managing AI agents in development environments.*
