# Getting Started with rack

Complete guide to setting up and using rack to manage your OpenClaw agents.

---

## Prerequisites

Before you begin:

- ✅ **OpenClaw** installed (from [openclaw.dev](https://openclaw.dev))
- ✅ **Telegram bot** created (via BotFather)
- ✅ **Bash** 4.0+ (standard on macOS/Linux)
- ✅ **Python** 3.7+ (for JSON operations)

---

## Installation

### 1. Install rack

```bash
# Clone repository
git clone https://github.com/yourusername/rack-cli.git
cd rack-cli

# Install to ~/.local/bin
./install.sh

# Ensure ~/.local/bin is in PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 2. Bootstrap OpenClaw

```bash
# Run once - sets up OpenClaw + specialist agents
rack install
```

This creates:
- OpenClaw configuration
- 6 specialist agents (programmer, reviewer, tester, knowledge, security, manager)
- Workspace directories
- Proper permissions

**Specialist agents are shared resources** - don't delete them!

---

## Understanding Agent Types

### Specialist Agents (The Team)

Created automatically by `rack install`:

| Agent | Role | Model | Purpose |
| --- | --- | --- | --- |
| **programmer** | Code writer | Sonnet 4-6 | Writes code for any project |
| **reviewer** | Quality control | Haiku 4-5 | Reviews code quality |
| **tester** | Testing | Haiku 4-5 | Runs tests, validates |
| **knowledge** | Documentation | Haiku 4-5 | Research, docs, learning |
| **security** | Security audits | Sonnet 4-6 | Finds vulnerabilities |
| **manager** | Coordination | Sonnet 4-6 | Delegates tasks |

**Important**: These work across ALL projects. Don't wire them to individual Telegram groups.

### Project Agents

Created by you with `rack add`:
- One per project/codebase
- Has own workspace, memory, Telegram group
- Examples: `mywebsite`, `mobile-app`, `shopify-store`

**This is what you create for your actual work.**

---

## Directory Structure

```
~/.openclaw/
├── openclaw.json              # Agent registry, Telegram bindings
├── secrets.json               # API keys (managed by 'rack keys')
└── workspaces/
    ├── manager/               # Specialist agent workspace
    ├── programmer/            # Specialist agent workspace
    ├── reviewer/              # ...etc
    └── projects/              # Your project agents
        └── mywebsite/         # Example project agent
            ├── SOUL.md        # Agent identity & instructions
            ├── AGENTS.md      # Team coordination rules
            ├── TOOLS.md       # Available commands
            ├── HEARTBEAT.md   # Active tasks
            ├── .rack-meta.json    # rack metadata
            ├── .env           # Environment variables (auto-synced)
            ├── memory/        # Daily logs
            └── workflows/     # Lobster pipelines (optional)

~/Sites/                       # Your actual codebases
├── mywebsite/                 # Actual code
└── mobile-app/                # Actual code
```

---

## Creating Your First Project Agent

### Repo Agent (For Code Projects)

```bash
# 1. Have your codebase ready
cd ~/Sites
git clone https://github.com/you/mywebsite.git

# 2. Add project agent
rack add
```

**Interactive prompts**:
```
Project type: 1 (repo)
Project ID: mywebsite
Codebase path: /home/you/Sites/mywebsite
Description: My awesome website
Model: [Enter for default sonnet-4-6]
```

**Auto-detection**: rack will detect your stack (Node.js, Python, etc.) from the codebase.

### Task Agent (For Research/Automation)

```bash
rack add
```

**Interactive prompts**:
```
Project type: 2 (task)
Project ID: content-research
Description: Research and content creation
Model: [Enter for default]
```

---

## Connect to Telegram

### 1. Create Telegram Group

1. Open Telegram
2. Create new group: "My Website"
3. Add your OpenClaw bot to the group
4. Send a test message (so group appears in logs)

### 2. Wire Agent to Group

```bash
rack wire mywebsite
```

**What happens**:
- Scans logs for unbound Telegram groups
- Shows you available groups
- Creates binding
- Restarts gateway

Now you can chat with your agent in Telegram!

---

## Working with Your Agent

### Chat in Telegram

Send messages to your group:

```
"What's the current state of the project?"
"Review the authentication code"
"Add a dark mode toggle to the settings page"
"Run the tests"
```

The agent:
- Reads/writes code in your codebase
- Coordinates with specialist agents (programmer, reviewer, etc.)
- Asks for approval before dangerous operations
- Logs all work in memory/

### View Agent Status

```bash
# List all agents
rack list

# Detailed info
rack info mywebsite

# View logs
rack logs mywebsite

# Check costs
rack cost mywebsite
```

### Edit Agent Configuration

```bash
# Edit SOUL.md, AGENTS.md, TOOLS.md, etc.
rack edit mywebsite

# Change model
rack model mywebsite anthropic/claude-opus-4-6

# Or use profiles
rack profile mywebsite premium   # Opus 4-6 (best)
rack profile mywebsite standard  # Sonnet 4-6 (balanced)
rack profile mywebsite economy   # Haiku 4-5 (fast/cheap)
```

---

## Advanced Features

### Multimodal (Images & Videos)

Enable your agent to generate images/videos:

```bash
# 1. Ensure vision-capable model
rack model mywebsite anthropic/claude-sonnet-4-6

# 2. Add Google AI API key
rack keys add GOOGLE_AI_API_KEY
# Get key: https://aistudio.google.com/

# 3. Done! Now ask in Telegram:
# "Generate a hero image for our homepage"
```

See [MULTIMODAL.md](MULTIMODAL.md) for details.

### Session Scoping (Isolation)

Isolate context between projects:

```bash
# View current scope
rack scope mywebsite show

# Change scope
rack scope mywebsite set production

# Reset to default
rack scope mywebsite reset
```

### Lobster Workflows

Create deterministic pipelines:

```bash
# Create workflow from template
rack workflow mywebsite create deploy

# List workflows
rack workflow mywebsite list

# Show workflow content
rack workflow mywebsite show deploy

# Agent can execute: "Run the deploy workflow"
```

### API Key Management

Centralized key storage for all agents:

```bash
# Add key (prompts securely)
rack keys add GOOGLE_AI_API_KEY

# List keys (values masked)
rack keys list

# Remove key
rack keys remove GOOGLE_AI_API_KEY
```

Keys auto-sync to all agent `.env` files.

---

## Common Tasks

### Reset Agent Memory

```bash
# Clear memory, keep identity
rack reset mywebsite
```

### Fix Agent Issues

```bash
# Repair permissions, re-register, fix routing
rack repair mywebsite
```

### Change Agent Model

```bash
# Use Opus 4-6 for complex work
rack model mywebsite anthropic/claude-opus-4-6

# Back to Sonnet for routine work
rack model mywebsite anthropic/claude-sonnet-4-6
```

### Monitor Costs

```bash
# Specific agent
rack cost mywebsite

# All agents
rack cost

# Shows: tokens used, estimated cost, model details
```

### System Health Check

```bash
# Check gateway, agents, config
rack doctor

# Verbose output
rack doctor --debug
```

---

## Troubleshooting

### Agent not responding in Telegram

```bash
# 1. Check gateway is running
rack list  # Look for "gateway up"

# 2. Check agent is wired
rack info mywebsite  # Look for "telegram" status

# 3. Check logs
rack logs mywebsite

# 4. Repair if needed
rack repair mywebsite
```

### Agent can't access codebase

```bash
# Check metadata
rack info mywebsite

# Fix path in workspace
rack edit mywebsite
# Update codebase path in SOUL.md or .rack-meta.json
```

### Permission errors

```bash
# Fix all permissions
rack repair mywebsite
```

---

## Best Practices

### Agent Naming

✅ **Good**: `mywebsite`, `mobile-app`, `api-server`
❌ **Avoid**: `test`, `temp`, `project1` (unclear purpose)

### Model Selection

- **Haiku 4-5** (economy): Research, testing, routine tasks
- **Sonnet 4-6** (standard): Active development, code review
- **Opus 4-6** (premium): Complex architecture, security audits

### Telegram Groups

- One group per project agent
- Name groups clearly: "My Website", "Mobile App"
- Don't wire specialist agents (they work across projects)

### Memory Management

- Reset memory periodically: `rack reset mywebsite`
- Check logs to understand agent behavior: `rack logs mywebsite`
- Use HEARTBEAT.md to track active tasks

---

## Next Steps

1. **Create your first project agent**: `rack add`
2. **Wire to Telegram**: `rack wire mywebsite`
3. **Start chatting**: Send tasks in Telegram
4. **Monitor costs**: `rack cost mywebsite`
5. **Read docs**:
   - [Architecture](architecture.md)
   - [Multimodal Guide](MULTIMODAL.md)
   - [Installation Details](installation.md)

---

## Quick Reference

```bash
# Setup
rack install                    # Bootstrap OpenClaw + specialists

# Project agents
rack add                        # Create project agent
rack list                       # List all agents
rack info <id>                  # Detailed info
rack delete <id>                # Remove agent

# Telegram
rack wire <id>                  # Connect to Telegram
rack unwire <id>                # Disconnect

# Configuration
rack edit <id>                  # Edit workspace files
rack model <id> <model>         # Change model
rack profile <id> <tier>        # Set tier (economy/standard/premium)

# API keys
rack keys add <KEY>             # Add key (prompts securely)
rack keys list                  # List keys (masked)
rack keys remove <KEY>          # Remove key

# Monitoring
rack logs <id>                  # View logs
rack cost <id>                  # Token usage
rack doctor                     # Health check

# Maintenance
rack reset <id>                 # Clear memory
rack repair <id>                # Fix issues
```

---

## Getting Help

- **Documentation**: See [docs/](.) for detailed guides
- **Issues**: Report at GitHub issues
- **Help command**: `rack help`
- **Debug mode**: `rack --debug <command>`
