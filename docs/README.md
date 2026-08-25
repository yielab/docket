# docket Documentation

**docket** is a Python CLI (Typer + Rich + Pydantic) — a governed runtime and control plane for
provisioning and isolating **teams** of autonomous coding agents: an isolated per-project pod
(Lead + Implementer, optionally Reviewer + Tester) for each codebase, not just single agents —
with role-based model routing, budget guardrails, and every tool call gated through one policy
chokepoint. docket owns the agent turn loop itself; it has no external daemon dependency, and
talks through one non-streaming OpenAI-compatible chat-completions adapter. OpenRouter and Vercel
AI Gateway are built in; other compatible endpoints require explicit registration.

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
> between versions, and **verify anything important against your own install**. All cost
> and dollar figures are accounting estimates, not your provider's bill — see
> [Cost reporting and its limits](../README.md#cost-reporting-and-its-limits).

## Guides

| Doc | What it covers |
|-----|----------------|
| [Quick Start](QUICK-START-DOCKET.md) | 5-minute setup: install, create your first project agent, assign work |
| **[Agent Teams (Pods)](AGENT-TEAMS.md)** | **The core model** — org specialists vs project pods, the Lead/Implementer/Reviewer/Tester roles, and real pipeline dispatch. |
| [Workflow Guide](WORKFLOW-GUIDE.md) | End-to-end examples: project vs. specialist agents, delegation, cost management |
| [Command Reference](commands.md) | Every command with syntax, options, and examples |
| [Models, gateways, and harnesses](MODEL-GATEWAYS.md) | Codex/Claude Code/OpenCode portability; OpenRouter and Vercel AI Gateway setup and limits |
| [Architecture (DOCKET)](DOCKET.md) | Technical deep dive: the `cli`/`core`/`edges` layering and Anti-Corruption Layer, the RuntimeDriver port, dispatch internals (state machine, gates, retries, run registry), durable state, agent roles |
| [Security Model](SECURITY-SIMPLE.md) | The layered, convention-based security model (and what's planned) |
| [Troubleshooting](troubleshooting.md) | Common issues and fixes |
| [Development Harness](DEVELOPMENT-HARNESS.md) | Contributor/agent context routing, repository skills, hooks, and token-efficient validation |

For how features are specified before implementation, see the specs under
[`../specs/`](../specs/) and the [SSD workflow guide](../SSD-WORKFLOW.md).

---

## Most common commands

```bash
# Start a project (also bootstraps shared workstation state on the first run)
docket init                     # Current directory -> Lead + Implementer pod
docket add reviewer             # Add an extra role to the current pod

# Daily use
docket status                  # Current project summary
docket status --all            # Global summary by project
docket list                    # Show all agents
docket info <id>               # Agent details
docket context <id> show       # Recent activity and context stats

# Pod teams (see Agent Teams guide)
docket init <project>                      # Provision a pod (Lead + Implementer)
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
docket auth status             # Which provider credentials are stored (docket keys is the store)
docket gates enable            # (Re-)apply approval routing (the tool-call gate is always on)
docket audit                   # Recent docket-initiated changes
```

See the [Command Reference](commands.md) for the full set.

---

## File layout

Everything docket owns lives under `~/.docket/` (`DOCKET_HOME` to relocate) — there is no external
daemon and no second config file anywhere else:

```
~/.docket/
├── fleet.json                     # Agent registration, channel bindings, gate/isolation flags,
│                                   # provider endpoints, the org default model
├── secrets.json                   # Stored provider API keys (0600)
├── docket-models.json             # Role→model policy overrides
├── docket-roles.json              # User-defined role archetypes
├── docket-conversations.json      # docket's own channel-thread registry
├── docket-runs.json               # docket's own dispatch run registry
├── docket-schedules.json          # Cron/interval pipeline schedules
├── docket-mcp-servers.json        # Configured external MCP tool servers
├── audit.log                      # Hash-chained audit log (docket audit verify)
├── traces/                        # Per-session JSONL execution traces
├── sessions/                      # Durable per-session turn history
├── approvals/                     # docket's own approval-token store
├── policies/                      # Installed guardrail policies
└── workspaces/
    ├── manager/                   # Org specialist: orchestrator (delegation only)
    ├── knowledge/                 # Org specialist: docs / research
    ├── security/                  # Org specialist: security audits
    ├── portfolio-manager/         # Optional org specialist (docket init --portfolio)
    └── projects/
        └── <project>-<role>/      # Pod member workspace (e.g. myapp-lead, myapp-implementer)
            ├── SOUL.md            # Identity + session key (+ optional persona)
            ├── AGENTS.md          # Session protocol
            ├── TOOLS.md           # Project commands
            ├── HEARTBEAT.md       # Durable task ledger (dispatch keeps its own region current)
            ├── WORKFLOW_AUTO.md   # Runtime-forced startup file: codebase path + resume contract
            ├── .docket-meta.json  # docket metadata (sessionKey, projectKey, optional persona)
            ├── memory/            # Daily logs
            └── workflows/         # Optional: docket-native pipeline YAML (docket pipeline run)
```

> Org specialists (`manager`, `knowledge`, `security`, and the opt-in `portfolio-manager`) have
> one shared workspace at `~/.docket/workspaces/<role>/`. Project pod members
> (`<project>-lead`, `<project>-implementer`, etc.) each get an **isolated** workspace under
> `projects/` — no role is ever shared between projects.

---

## Contributing to docs

1. **Accurate over comprehensive** — every example should run against the current CLI
2. **User-focused** — answer "how do I…", link to the [Command Reference](commands.md) for detail
3. **Consistent formatting** — follow the existing style

For questions, run `docket help` or start with the [Quick Start](QUICK-START-DOCKET.md).
