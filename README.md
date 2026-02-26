# rack — OpenClaw Agent Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-98.9%25-brightgreen.svg)](tests/)
[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/yourusername/rack-cli)

**rack** is a production-ready CLI for managing OpenClaw autonomous agent deployments. It provides enterprise-grade features like multi-project isolation, team coordination, deterministic workflows, and cost management — without requiring direct OpenClaw CLI interaction or JSON editing.

## ✨ Features

- **🚀 Clean Install**: Bootstrap a complete OpenClaw setup from scratch with `rack install`
- **🔒 Session Scoping**: Multi-project isolation via `agent:<id>:<project>` coordinates
- **👥 Team Coordination**: Manager agent with delegation and task orchestration
- **⚙️ Lobster Workflows**: Deterministic YAML pipelines for token-efficient execution
- **🛡️ Security Sentinel**: Tool approval gates, workspace isolation, audit logging
- **💰 Cost Management**: Tiered model profiles with real-time usage tracking
- **📱 Mobile-First**: Telegram integration for approvals and monitoring
- **🔍 Health Monitoring**: Proactive checks and autonomous recovery

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [Architecture](#architecture)
- [Commands](#commands)
- [Configuration](#configuration)
- [Development](#development)
- [Testing](#testing)
- [Contributing](#contributing)
- [License](#license)

## 🚀 Quick Start

### Prerequisites

- **OpenClaw**: Install from [openclaw.dev](https://openclaw.dev)
- **Bash**: 4.0+ (ships with macOS/Linux)
- **Python**: 3.7+ (for JSON manipulation)
- **systemctl**: For service management
- **fzf** (optional): For enhanced interactive pickers

### Install

```bash
# Clone the repository
git clone https://github.com/yourusername/rack-cli.git
cd rack-cli

# Run the installer (copies to ~/.local/bin and ~/.local/lib/rack)
./install.sh

# Ensure ~/.local/bin is in your PATH
# For bash:
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# For zsh:
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Bootstrap OpenClaw with rack
rack install
```

### Uninstall

```bash
# From the repository directory
./uninstall.sh
```

### First Project

```bash
# Add your first project agent
rack add

# View all agents
rack list

# Get detailed info
rack info <agent-id>

# Wire to Telegram (optional)
rack wire <agent-id>

# Check system health
rack doctor
```

## 📦 Installation

### Option 1: Quick Install (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/yourusername/rack-cli/main/install.sh | bash
```

### Option 2: Manual Install

```bash
# Clone repository
git clone https://github.com/yourusername/rack-cli.git
cd rack-cli

# Run installation
./bin/rack install
```

### Option 3: Development Install

```bash
# Clone with symlink
git clone https://github.com/yourusername/rack-cli.git
cd rack-cli
ln -s "$(pwd)/bin/rack" /usr/local/bin/rack

# Run tests
./tests/test-lifecycle.sh
```

## 💡 Usage

### Basic Workflow

```bash
# 1. Bootstrap OpenClaw (first time only)
rack install

# 2. Add a project agent
rack add
#   → Choose type: repo or task
#   → Enter project name
#   → Select codebase path
#   → Choose model profile

# 3. View agents
rack list

# 4. Get detailed info
rack info myproject

# 5. Manage costs
rack cost                    # All agents
rack cost myproject          # Single agent
rack profile myproject economy  # Switch to cheaper model

# 6. Configure session scope
rack scope myproject set alpha    # Isolate to "alpha" context
rack scope myproject reset        # Reset to default

# 7. Team coordination (optional)
rack team init              # Create manager agent
rack team status            # View team state

# 8. Create workflows (optional)
rack workflow myproject create ci-pipeline
rack workflow myproject list
```

### Telegram Integration

```bash
# 1. Create Telegram group
# 2. Add your OpenClaw bot
# 3. Send a test message
# 4. Wire the agent
rack wire myproject

# 5. Get group ID from logs
tail -f /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log

# 6. Approve actions from mobile
# Bot will send notifications for dangerous operations
```

### Cost Optimization

```bash
# View current usage
rack cost

# Switch to economy mode (saves ~75%)
rack profile myproject economy

# View potential savings
rack cost myproject
```

## 🏗️ Architecture

### Directory Structure

```
rack-cli/
├── bin/
│   └── rack                 # Main executable (2600 lines)
├── docs/
│   ├── installation.md      # Detailed install guide
│   ├── commands.md          # Command reference
│   ├── architecture.md      # System design
│   └── development.md       # Developer guide
├── tests/
│   └── test-lifecycle.sh    # Integration tests
├── examples/
│   ├── workflows/           # Example Lobster workflows
│   └── configs/             # Sample configurations
├── CLAUDE.md                # AI assistant instructions
├── README.md                # This file
└── LICENSE                  # MIT license
```

### How rack Works

```
┌─────────────┐
│   rack CLI  │  ← User interface (Bash)
└──────┬──────┘
       │
       ├─→ .rack-meta.json    ← Per-project metadata
       │   (name, type, model, sessionKey, etc.)
       │
       ├─→ openclaw.json      ← OpenClaw daemon config
       │   (agents, bindings, security, etc.)
       │
       └─→ Workspace Files
           ├── SOUL.md        ← Agent identity + session key
           ├── AGENTS.md      ← Delegation rules
           ├── TOOLS.md       ← Project commands
           ├── HEARTBEAT.md   ← Active tasks
           ├── memory/        ← Daily logs
           └── workflows/     ← Lobster pipelines
```

### Session Isolation

Each agent has a **session key** (`agent:<id>:<project>`) that:
- Prevents cross-project contamination
- Isolates workspace memory
- Enforces routing boundaries
- Enables parallel project work

```bash
rack scope myproject set alpha    # agent:myproject:alpha
rack scope myproject set beta     # agent:myproject:beta
```

### Team Coordination

The **Manager agent** orchestrates work across specialists:

```
Manager (Sonnet 4.6)
├─→ programmer (Sonnet 4.6)    # Code implementation
├─→ reviewer (Haiku 4.5)        # Code review
├─→ tester (Haiku 4.5)          # Testing
├─→ knowledge (Haiku 4.5)       # Memory/patterns
└─→ security (Sonnet 4.6)       # Security audits
```

The manager uses `TASK_LIST.json` for coordination and cannot edit code directly — it only plans and delegates.

## 📚 Commands

### Setup

```bash
rack install              # Bootstrap OpenClaw with best practices
```

### Lifecycle

```bash
rack list                 # List all project agents
rack add                  # Add new project agent (interactive)
rack info <id>            # Detailed agent status
rack delete <id>          # Remove agent (with confirmation)
rack reset <id>           # Clear memory (3 levels)
rack repair <id>          # Fix permissions and routing
```

### Team Coordination

```bash
rack team status          # View team state
rack team init            # Create manager agent
rack team check           # Health check for specialists
```

### Session Management

```bash
rack scope <id> show             # Display current scope
rack scope <id> set <project>    # Change project scope
rack scope <id> reset            # Reset to default
```

### Workflows

```bash
rack workflow <id> list                 # List workflows
rack workflow <id> create <name>        # Create from template
rack workflow <id> show <name>          # Display workflow
rack workflow <id> delete <name>        # Remove workflow
```

### Telegram

```bash
rack wire <id>            # Wire Telegram group
rack unwire <id>          # Remove binding
```

### Utilities

```bash
rack logs <id>            # View memory logs
rack edit <id>            # Open workspace in $EDITOR
rack model <id> [model]   # View/change model
rack profile <id> [tier]  # Set model profile
rack cost [id]            # Token usage and costs
rack doctor               # System health check
```

### Model Profiles

| Profile | Model | Cost | Use Case |
|---------|-------|------|----------|
| `economy` | claude-haiku-4-5 | $0.80/$4 per MTok | Routine tasks, triage, simple Q&A |
| `standard` | claude-sonnet-4-6 | $3/$15 per MTok | Active development, code review |
| `premium` | claude-opus-4-6 | $15/$75 per MTok | Complex architecture, security |

## ⚙️ Configuration

### OpenClaw Config Location

`~/.openclaw/openclaw.json` — Managed by rack, no manual editing needed

### Project Metadata

`~/.openclaw/workspaces/projects/<id>/.rack-meta.json`

```json
{
  "type": "repo",
  "name": "My Project",
  "codebase": "/home/user/Sites/myproject",
  "stack": "Node.js, React, TypeScript",
  "model": "anthropic/claude-sonnet-4-6",
  "description": "My awesome project",
  "created": "2026-02-25T10:00:00Z",
  "sessionKey": "agent:myproject:default",
  "projectKey": "default"
}
```

### Security Sentinel (Auto-configured)

Tool approval gates for:
- `rm` — File deletion
- `git push` — Code deployment
- `docker stop` — Container management
- `kubectl delete` — Kubernetes operations
- `npm publish` — Package publishing
- `pip install` — Package installation
- `curl`, `wget` — Network requests

## 🔧 Development

### Project Structure

```
rack-cli/
├── bin/
│   └── rack                  # Entry point (~100 lines)
├── lib/
│   ├── core/                 # Core initialization & config
│   │   ├── init.sh          # Strict mode, debug
│   │   ├── config.sh        # Paths, colors, models, pricing
│   │   └── router.sh        # Command dispatcher
│   ├── helpers/              # Reusable utilities
│   │   ├── output.sh        # Output formatting
│   │   ├── json.sh          # JSON manipulation
│   │   ├── session.sh       # Session management
│   │   ├── picker.sh        # Interactive picker
│   │   ├── service.sh       # Service control
│   │   ├── utils.sh         # Utilities
│   │   └── workspace.sh     # Workspace management
│   └── commands/             # Command implementations (19 files)
│       ├── install.sh, add.sh, list.sh, info.sh
│       ├── delete.sh, reset.sh, repair.sh
│       ├── team.sh, workflow.sh, scope.sh
│       └── wire.sh, unwire.sh, logs.sh, etc.
├── tests/
│   ├── unit/                 # Unit tests (27 tests)
│   └── test-lifecycle.sh     # Integration tests (62 tests)
├── docs/
│   ├── architecture.md
│   ├── commands.md
│   ├── development.md
│   └── installation.md
└── examples/
    ├── configs/              # Example configurations
    └── workflows/            # Example Lobster workflows
```

### Adding a New Command

1. Create `lib/commands/mycommand.sh`:
```bash
# lib/commands/mycommand.sh

cmd_mycommand() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Select project")

  # Your implementation
  success "Command executed!"
}
```

2. Source in `bin/rack`:
```bash
source "$LIB_DIR/commands/mycommand.sh"
```

3. Add to `lib/core/router.sh`:
```bash
case "$cmd" in
  # ...
  mycommand) cmd_mycommand "$@" ;;
  # ...
esac
```

4. Update help text in `cmd_help()`

### Code Style

- **Naming**: `snake_case` for functions and variables
- **Globals**: `UPPER_CASE` for constants
- **Error handling**: Use `error()`, `warn()`, `fail()` helpers
- **Debugging**: Support `DEBUG=1` for verbose output
- **Permissions**: 700 for dirs, 600 for files
- **Exit codes**: 0 = success, 1 = error

## 🧪 Testing

### Run Full Test Suite

```bash
# Run all tests (unit + integration)
./tests/run-all-tests.sh

# Run unit tests only
./tests/unit/test-helpers.sh

# Run integration tests only
./tests/test-lifecycle.sh

# Keep test agent for inspection
./tests/test-lifecycle.sh --keep
```

### Test Coverage

- ✅ Installation and bootstrap
- ✅ Agent lifecycle (add, list, info, delete)
- ✅ Session scoping (show, set, reset)
- ✅ Team coordination (status, init)
- ✅ Workflow management (create, list, delete)
- ✅ Cost tracking and model profiles
- ✅ Repair and health checks

### Manual Testing

```bash
# Test install
DEBUG=1 rack install

# Test agent creation
DEBUG=1 rack add

# Test scope management
rack scope test-agent set alpha
rack info test-agent  # Should show new session key

# Test cleanup
rack delete test-agent
```

## 🤝 Contributing

Contributions are welcome! Please read our [Contributing Guidelines](CONTRIBUTING.md).

### Development Setup

```bash
# Fork and clone
git clone https://github.com/yourusername/rack-cli.git
cd rack-cli

# Create feature branch
git checkout -b feature/my-feature

# Make changes and test
./tests/test-lifecycle.sh

# Commit with conventional commits
git commit -m "feat: add new command for X"

# Push and create PR
git push origin feature/my-feature
```

### Commit Convention

```
feat: New feature
fix: Bug fix
docs: Documentation changes
refactor: Code refactoring
test: Test updates
chore: Maintenance tasks
```

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [OpenClaw](https://openclaw.dev) — Autonomous agent framework
- [Anthropic Claude](https://claude.ai) — AI models
- Community contributors and testers

## 📞 Support

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/yourusername/rack-cli/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/rack-cli/discussions)

## 🗺️ Roadmap

- [ ] Web dashboard for monitoring
- [ ] Multi-user support with RBAC
- [ ] Custom skill integration
- [ ] Cost budget alerts
- [ ] Automated heartbeat monitoring
- [ ] BM25 + Vector hybrid retrieval
- [ ] Event-driven recovery protocols

---

**Made with ❤️ for autonomous development**
