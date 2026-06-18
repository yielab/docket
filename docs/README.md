# docket Documentation

**docket** is a modular Bash CLI for managing OpenClaw autonomous agents with project
isolation, role-based model routing, and cost tracking.

> New here? Start with the [project README](../README.md) for the overview and install steps,
> then come back for the guides below.

---

## Guides

| Doc | What it covers |
|-----|----------------|
| [Quick Start](QUICK-START-DOCKET.md) | 5-minute setup: install, create your first project agent, assign work |
| [Workflow Guide](WORKFLOW-GUIDE.md) | End-to-end examples: project vs. specialist agents, delegation, cost management |
| [Command Reference](commands.md) | Every command with syntax, options, and examples |
| [Architecture (DOCKET)](DOCKET.md) | Technical deep dive: routing, context management, agent roles |
| [Security Model](SECURITY-SIMPLE.md) | The layered, convention-based security model (and what's planned) |
| [Troubleshooting](troubleshooting.md) | Common issues and fixes |

For how features are specified before implementation, see the specs under
[`../specs/`](../specs/) and the [SSD workflow guide](../SSD-WORKFLOW.md).

---

## Most common commands

```bash
# Setup (once)
docket install                 # Install OpenClaw + specialist agents

# Daily use
docket add                     # Create a project agent
docket list                    # Show all agents
docket info <id>               # Agent details
docket context snapshot <id>   # Create fast-access context

# Configuration
docket models                  # Role→model policy (set <role> <model>, presets)
docket profile <id> <model>    # Pin an agent (<provider/model>) or 'default' = policy
docket profile <id> --budget 5 # Per-agent spend cap (USD)
docket scope <id> set <key>    # Switch project context

# Maintenance & health
docket maintain <id> check     # Health check + auto-fix
docket cost [id]               # Token usage and cost
docket doctor                  # System-wide diagnostics
```

See the [Command Reference](commands.md) for the full set.

---

## File layout

```
~/.openclaw/
├── openclaw.json                  # OpenClaw daemon config
└── workspaces/
    ├── manager/                   # Specialist: orchestrator (delegation only)
    ├── programmer/                # Specialist: implementation
    ├── reviewer/                  # Specialist: review
    ├── tester/                    # Specialist: validation
    ├── knowledge/                 # Specialist: docs / research
    ├── security/                  # Specialist: security audits
    └── projects/
        └── <agent-id>/            # Project agent workspace
            ├── SOUL.md            # Identity + session key
            ├── AGENTS.md          # Session protocol
            ├── TOOLS.md           # Project commands
            ├── HEARTBEAT.md       # Active tasks
            ├── .docket-meta.json    # docket metadata
            └── memory/            # Daily logs
```

---

## Contributing to docs

1. **Accurate over comprehensive** — every example should run against the current CLI
2. **User-focused** — answer "how do I…", link to the [Command Reference](commands.md) for detail
3. **Consistent formatting** — follow the existing style

For questions, run `docket help` or start with the [Quick Start](QUICK-START-DOCKET.md).
