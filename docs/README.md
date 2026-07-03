# docket Documentation

**docket** is a Python CLI (Typer + Rich + Pydantic) for provisioning and isolating **teams** of
OpenClaw autonomous agents — an isolated per-project pod (Lead + Implementer, optionally Reviewer
+ Tester) for each codebase, not just single agents — with role-based model routing and budget
guardrails.

> New here? Start with the [project README](../README.md) for the overview and install steps,
> then come back for the guides below.

<p align="center">
  <img src="assets/hero.gif" alt="docket in action: provision an isolated project agent, list the fleet, inspect its per-project isolation, run a fleet health check, and set a budget guardrail" width="720">
</p>

---

> [!WARNING]
> **docket is early-stage / beta software.** Features described in these guides are implemented
> and automated-test-backed, but have not been QA-hardened in production — automated tests catch
> regressions, they don't replace hands-on verification. Expect rough edges and breaking changes
> between versions, and **verify anything important against your own OpenClaw install**. All cost
> and dollar figures are accounting estimates, not your provider's bill — see
> [Cost reporting and its limits](../README.md#cost-reporting-and-its-limits).

## Guides

| Doc | What it covers |
|-----|----------------|
| [Quick Start](QUICK-START-DOCKET.md) | 5-minute setup: install, create your first project agent, assign work |
| **[Agent Teams (Pods)](AGENT-TEAMS.md)** | **The core model** — org specialists vs project pods, the Lead/Implementer/Reviewer/Tester roles, and real pipeline dispatch. |
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
docket context <id> snapshot   # Create fast-access context

# Pod teams (see Agent Teams guide)
docket add <project>                       # Provision a pod (Lead + Implementer)
docket pod <project>                       # Inspect / resize the pod
docket pod <project> delegate "<task>"     # Queue a task for the pod
docket pod <project> dispatch              # Run the pod's pipeline once

# Configuration
docket models                  # Role→model policy (set <role> <model>, presets)
docket profile <id> <model>    # Pin an agent (<provider/model>) or 'default' = policy
docket profile <id> --budget 5 # Per-agent spend cap (USD)
docket scope <id> set <key>    # Switch project context

# Maintenance & health
docket maintain <id> check     # Health check + auto-fix
docket cost [id]               # Token usage and cost
docket doctor                  # System-wide diagnostics (add --fix to apply auto-fixes)

# Keys, auth & security (see Command Reference for the full surface)
docket keys setup              # Interactive API key wizard
docket auth status             # Claude model auth profiles
docket gates enable            # (Re-)apply enforced tool-approval gates (on by default at install)
docket audit                   # Recent docket-initiated changes
```

See the [Command Reference](commands.md) for the full set.

---

## File layout

```
~/.openclaw/
├── openclaw.json                  # OpenClaw daemon config
└── workspaces/
    ├── manager/                   # Org specialist: orchestrator (delegation only)
    ├── knowledge/                 # Org specialist: docs / research
    ├── security/                  # Org specialist: security audits
    └── projects/
        └── <project>-<role>/      # Pod member workspace (e.g. myapp-lead, myapp-implementer)
            ├── SOUL.md            # Identity + session key
            ├── AGENTS.md          # Session protocol
            ├── TOOLS.md           # Project commands
            ├── HEARTBEAT.md       # Active tasks
            ├── .docket-meta.json  # docket metadata
            └── memory/            # Daily logs
```

> Org specialists (`manager`, `knowledge`, `security`) have one shared workspace at
> `~/.openclaw/workspaces/<role>/`. Project pod members (`<project>-lead`, `<project>-implementer`,
> etc.) each get an **isolated** workspace under `projects/` — no role is ever shared between
> projects.

---

## Contributing to docs

1. **Accurate over comprehensive** — every example should run against the current CLI
2. **User-focused** — answer "how do I…", link to the [Command Reference](commands.md) for detail
3. **Consistent formatting** — follow the existing style

For questions, run `docket help` or start with the [Quick Start](QUICK-START-DOCKET.md).
