# rack-cli

[![CI](https://github.com/santiagoyie/rack-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/santiagoyie/rack-cli/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Shell: Bash 4+](https://img.shields.io/badge/shell-bash%204%2B-green.svg)](https://www.gnu.org/software/bash/)
[![Specs: 100%](https://img.shields.io/badge/spec%20coverage-100%25-success.svg)](specs/)

A modular Bash CLI for managing OpenClaw autonomous agents with project isolation and workflow automation. Personal R&D project exploring agent orchestration patterns, spec-driven development methodology, and cost-tracking tooling for production-style multi-agent setups.

## Features

**Agent lifecycle & isolation**
- 🚀 **One-command bootstrap** — `rack install` sets up OpenClaw and a 6-member specialist team
- 📦 **Project agents** — create, inspect, maintain, and delete agents, each with a dedicated, permission-locked workspace (`700`/`600`)
- 🔒 **Session-based isolation** — `agent:<id>:<project>` keys keep memory and context from leaking across projects
- 📄 **Declarative provisioning** — `rack add --from agents.yaml` provisions a whole fleet from a version-controlled spec; idempotent re-apply keeps git the source of truth

**Cost control & model routing**

- 🎚️ **Role→model policy** — each agent role (manager, programmer, tester, …) maps to the cheapest adequate model; change a role once with `rack models set` and every policy-following agent updates. Pin individual agents with `rack profile`
- 🌐 **Multi-provider support** — Anthropic (default), OpenAI, Google, OpenRouter (incl. free tier); configure with `rack models preset`
- 💰 **Budget caps & runaway detection** — set a per-agent USD cap; agents auto-pause when it's hit
- 📊 **Cost reporting** — token usage and dollar cost, per agent or aggregated, with a daily `--history` series and spike detection

**Team & automation**
- 👥 **Specialist team** — programmer, reviewer, tester, knowledge, security, and manager roles, shared across projects
- 📋 **Task delegation** — queue work for the manager with `rack team delegate` and track it through to done
- ⚙️ **Lobster workflows** — deterministic YAML pipelines for repeatable, token-efficient runs

**Operations**
- 🔑 **Centralized API keys** — set once with `rack keys`, auto-synced to every agent
- 📱 **Telegram integration** — manage agents and approve actions from your phone
- 🩺 **Health & diagnostics** — `rack doctor` and `rack maintain check` detect drift, budget overruns, and stale sessions; `rack snapshot` emits JSON system state for dashboards/CI

**Engineering discipline**
- 📐 **Spec-driven development** — every command and feature is backed by an RFC 2119 specification (100% spec coverage, checked by `validate-specs.sh` / `spec-coverage.sh`)
- 📏 **Golden-task eval harness** — six specialist-role evals, structural + live (`RACK_EVAL_LIVE=1`) modes; results feed `rack doctor`'s model right-sizing hints
- 🧩 **Modular Bash architecture** — 23 commands and reusable helpers, covered by 241 unit and 60 integration tests

See the [Project Status](#project-status) table below for the maturity of each feature, and the [Command Reference](#command-reference) for full usage.

## Motivation

I built rack to simplify OpenClaw agent orchestration across multiple projects. Instead of manually editing JSON configs and managing workspace directories, rack provides a unified interface with session-based project isolation and automated workspace provisioning.

Rack is also a deliberate exploration of patterns and disciplines outside my day-to-day paid work. Specifically: spec-driven development (features specified before implementation, RFC 2119 keywords, a coverage tool that reports honest gaps), modular Bash architecture at scale, and multi-agent coordination patterns with cost-tracking and role-based model routing.

## Project Status

| Feature | Status | Notes |
|---------|--------|-------|
| Agent lifecycle (add/delete/maintain) | ✅ Working | Full CRUD via `rack maintain` |
| Session scoping & isolation | ✅ Working | Multi-project isolation via session keys |
| Specialist agents team | ✅ Working | 6 pre-configured roles |
| Lobster workflow integration | ✅ Working | YAML pipeline support |
| Cost tracking & budget caps | ✅ Working | Role→model policy, per-agent budget, runaway detection |
| API key management | ✅ Working | Centralized key distribution |
| CI pipeline | ✅ Working | GitHub Actions on every push/PR |
| Telegram integration | ✅ Working | Manual wire: create group, add bot, run `rack wire` |
| Security gates | ✅ Opt-in | Exec-approval enforcement + curated allowlist, Telegram approval routing, and Docker workspace isolation via `rack gates enable` / `isolate`; status in `rack doctor`. Opt-in by design (on-by-default pending headless approval routing) |
| Secret storage backends | ✅ Working | `file` (0600 JSON, default) or `keyring` (libsecret, no plaintext at rest) via `RACK_SECRETS_BACKEND` |
| Manager coordination | ✅ Working | Full delegation state machine (`rack team delegate` → queue → done) |

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

# View / change the role→model policy
rack models

# Pin one agent's model (or 'default' to follow the role policy)
rack profile myproject anthropic/claude-opus-4-6

# Set $5 spending cap
rack profile myproject --budget 5

# Clear agent memory
rack maintain myproject clean

# Delete agent
rack delete myproject
```

## Architecture

The project consists of ~7,200 lines of Bash across the CLI and test suite (~7,800 counting SSD tooling and installers):

Why Bash: rack runs anywhere with Bash 4+ — no runtime install, no compilation step, no dependency hell. The trade-off is verbosity at this size; if rack grows past 10,000 lines I'd migrate the core to Go. The current scope justifies staying in Bash.

```
rack-cli/
├── bin/rack                         # Entry point (~110 lines)
├── lib/
│   ├── core/                        # Init, config, routing (3 files)
│   ├── helpers/                     # Reusable utilities (9 files)
│   ├── commands/                    # 21 command implementations
│   └── commands/experimental/       # 1 experimental command (RACK_EXPERIMENTAL=1)
└── tests/
    ├── unit/                        # 241 unit tests (100% passing)
    ├── test-lifecycle.sh            # 12 integration scenarios (60 assertions)
    └── evals/                       # 6 specialist-role evals (structural + live)
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
rack add [id] [path]      # Create project agent (interactive)
rack add --from spec.yaml # Provision a fleet from a YAML/JSON spec (declarative)
rack list                 # Show all agents
rack info <id>            # Display agent details
rack delete <id>          # Remove agent
rack maintain <id> clean  # Clear agent memory (see Maintenance below)
```

### Configuration

```bash
rack models               # Role→model policy (set <role> <model>, preset, reset)
rack profile <id> [model] # Pin an agent's model (<provider/model>) or 'default' = follow policy
rack scope <id> set <key> # Change project session key
rack keys                 # Manage API keys
rack cost [id]            # Show token usage and costs (--json, --history [--days N])
```

### Maintenance

```bash
rack maintain [id] check    # Health check and auto-fix
rack maintain [id] clean    # Clear memory logs
rack maintain [id] reset    # Clear memory + heartbeat
rack maintain [id] rebuild  # Full rebuild from metadata
rack maintain [id] sessions # Archive large/old sessions
rack doctor                 # System-wide diagnostics (budget, drift, runaway, gates)
```

### Security Gates (opt-in)

```bash
rack gates status           # Exec-approval policy, routing, isolation, audit posture
rack gates enable           # Apply approval gates + curated allowlist + chat routing
rack gates isolate on       # Confine tool execution to a per-agent Docker sandbox
rack gates disable          # Revert gate defaults (escape hatch)
rack install --gates        # Apply gates during install
```

`RACK_SECRETS_BACKEND=keyring` stores key values in the OS keyring (libsecret) instead of the
default 0600 JSON file. Run `rack --version` to print the installed version.

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
rack profile <id> --budget 5      # Set $5 spending cap
rack context <id> snapshot        # Create fast-access context for an agent
```

### Role→Model Policy & Provider Support

rack is provider-agnostic. Each agent **role** maps to the cheapest model that's adequate for its workload — that mapping is the policy, and you can override any role:

| Role | Default (Anthropic) | Why |
| ---- | ------------------- | --- |
| manager, reviewer, tester, knowledge | claude-haiku-4-5 | High-volume, low reasoning-density work |
| programmer, security | claude-sonnet-4-6 | Reasoning-dense generation and audits |
| repo / task (project agents) | sonnet / haiku | Project-agent type defaults |

Stronger models (opus-class) are an explicit per-agent pin, never a standing default. Agents follow the policy by default; changing the policy (or switching provider preset) re-resolves every policy-following agent automatically — pinned agents are never touched.

```bash
rack models                          # Show the role→model policy with pricing
rack models preset openrouter-free   # Switch all roles to OpenRouter free tier (no cost)
rack models preset openai            # Switch to OpenAI (gpt-4.1-nano / gpt-4.1-mini)
rack models preset google            # Switch to Google (gemini flash family)
rack models preset anthropic         # Restore Anthropic defaults
rack models set programmer openai/gpt-4.1   # Override one role
rack profile myproject anthropic/claude-opus-4-6  # Pin one agent
rack profile myproject default       # Re-attach the agent to its role policy
```

The old tier names (economy/standard/premium) are deprecated but still accepted with a warning. Pricing is shown as `n/a` for models not in the built-in table. Custom pricing can be added in `~/.openclaw/rack-models.json`.

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

# Unit tests only (241 tests, 100% passing)
./tests/unit/test-helpers.sh

# Integration tests (12 lifecycle scenarios, 60 assertions)
./tests/test-lifecycle.sh
./tests/test-lifecycle.sh --keep  # Keep test agent for inspection

# Specialist-role evals (6 stubs)
./tests/evals/run-evals.sh
```

**Current status:** all suites green — 241 unit, 60 integration (2 skipped), 5 evals (1 skipped).

## Development

### SSD (Spec-Driven Development) Workflow

Rack is where I'm practicing spec-driven development as a discipline: writing the specification for a feature before the implementation, using RFC 2119 keywords (MUST/SHOULD/MAY) to make requirements testable, and tracking how much of the codebase is actually covered. This is a rollout in progress, not a finished mandate — the specs cover the core lifecycle today and are being extended outward.

1. **Write the specification first** (`specs/`)
   - Functional specs in `specs/functional/` — e.g. [agent-lifecycle.spec.md](specs/functional/agent-lifecycle.spec.md), an example of how a feature is specified (with RFC 2119 keywords) before it's built
   - API/CLI contracts in `specs/api/`
   - Acceptance criteria in `specs/acceptance/`
   - Input-validation rules in `specs/validation/`

2. **Drive implementation from the spec**, then back it with tests in `tests/`

3. **Measure coverage honestly**

   ```bash
   ./scripts/validate-specs.sh    # Validate spec structure/completeness (all specs pass)
   ./scripts/spec-coverage.sh     # Report command/feature/test coverage
   ```

   `validate-specs.sh` passes all 14 specs cleanly; `spec-coverage.sh` reports **100% command coverage (21/21), 100% feature coverage (10/10), 100% of tracked specs test-backed**. "Covered" here means a feature has a structured, validated spec — not that every feature is fully built: `security-gates`, for example, is specified but marked *Planned*, because the tool-approval gates aren't wired up yet. The tooling reports honestly (a heading-level spec, not a passing mention), so the number reflects real specs.

4. **CI runs `validate-specs.sh` on every push** (currently advisory/non-blocking) alongside the unit tests. Making spec validation a blocking CI gate is a tracked next step (see [What's Next](#whats-next)).

See [specs/README.md](specs/README.md) for the full SSD documentation.

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
- New features are specified before implementation where the SSD rollout has reached them
- Behavior is covered by unit and integration tests
- Specifications use RFC 2119 keywords (MUST, SHOULD, MAY)

## What's Next

See [ROADMAP.md](ROADMAP.md) for the full phased plan (security → reliability → portability →
operability → MLOps depth). Near-term highlights:

1. Expand the eval harness (`tests/evals/`) — golden tasks per specialist role run in structural and live modes; grow the task set and feed results into model right-sizing
2. Run integration tests in CI alongside the unit suite (they currently require a local openclaw daemon), and promote the macOS job to a required check
3. Turn security gates on by default — gates are implemented opt-in ([specs/functional/security-gates.spec.md](specs/functional/security-gates.spec.md)); on-by-default is pending headless approval routing

## Contributing

This project uses pure Bash with modular architecture. PRs welcome for:

- Additional OpenClaw integrations
- Command implementations
- Test coverage improvements
- Documentation

---

*A personal R&D project by Santiago Yie, built to manage OpenClaw agent deployments while deepening spec-driven development, multi-agent orchestration, and cost-tracking discipline. Actively used in real development environments.*

## License

Apache-2.0

## Author

Santiago Yie - Backend/Platform Engineer
