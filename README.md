# rack-cli — the cost-aware ops layer for OpenClaw agent fleets

[![CI](https://github.com/santiagoyie/rack-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/santiagoyie/rack-cli/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Shell: Bash 4+](https://img.shields.io/badge/shell-bash%204%2B-green.svg)](https://www.gnu.org/software/bash/)
[![Specs: 100%](https://img.shields.io/badge/spec%20coverage-100%25-success.svg)](specs/)

> Stop your [OpenClaw](https://openclaw.dev) agents from burning budget and leaking context
> across projects. **rack** is a single Bash CLI that adds per-agent budget caps, hard project
> isolation, and drift detection on top of OpenClaw — the ops layer for people running more
> than one agent.

*Independent project. Not affiliated with or endorsed by OpenClaw or the OpenClaw Foundation.*

<!-- DEMO: a 30-second asciinema cast (create agent → set budget → see cost) belongs here,
     above the fold. Highest-ROI asset; record with `asciinema rec` and embed the SVG/player. -->

## Why

Running one OpenClaw agent is easy. Running a fleet surfaces three problems OpenClaw doesn't
solve for you:

- **Runaway API cost.** Autonomous agents loop, retry, and call expensive models without
  asking. rack gives every agent a per-agent USD budget cap that auto-pauses on breach, a
  role→cheapest-adequate-model policy, and spike detection in `rack cost`.
- **Context leak across projects.** One agent's memory bleeding into another's is the
  "noisy neighbor" problem. rack assigns each agent a session key (`agent:<id>:<project>`)
  so memory and context stay isolated.
- **Config drift.** OpenClaw updates and autonomy regressions silently change behavior.
  `rack doctor` and `rack maintain check` detect drift, budget overruns, runaway loops, and
  stale sessions; `rack add --from agents.yaml` keeps the fleet declarative and reproducible.

## Install

```bash
# Homebrew (macOS/Linux) — recommended
brew tap santiagoyie/rack-cli https://github.com/santiagoyie/rack-cli
brew install rack-cli

# Or the install script (review it before piping to a shell)
curl -fsSL https://raw.githubusercontent.com/santiagoyie/rack-cli/main/install.sh | bash

# Or from source
git clone https://github.com/santiagoyie/rack-cli.git
cd rack-cli && ./install.sh        # installs to ~/.local by default; RACK_PREFIX to override

# Then bootstrap OpenClaw + the specialist team
rack install
```

> Installs to `~/.local` (no `sudo`); add `~/.local/bin` to `PATH` if it isn't already. The old
> `sudo ln -s` symlink method is retired.

**Prerequisites:** Bash 4.0+ · Python 3.7+ · the [OpenClaw](https://openclaw.dev) daemon ·
`systemctl` (service management) · `fzf` (optional, interactive picker).

## 60-second tour

```bash
rack add myproject ~/code/myproject   # create an isolated project agent
rack profile myproject --budget 5     # cap it at $5; it auto-pauses on breach
rack list                             # see every agent at a glance
rack cost myproject                   # token usage + dollar cost, with spike detection
rack doctor                           # fleet health: drift, budget, runaway, gates
```

That's the loop rack is built around: **create → cap → watch → keep healthy.**

## How it relates to OpenClaw

OpenClaw already spawns and coordinates agents (`agents.md`, `@mention` delegation). rack does
**not** reinvent that — it wraps OpenClaw to add the operational layer a fleet needs:

| Need | OpenClaw native | rack adds |
|------|-----------------|-----------|
| Spawn / coordinate agents | ✅ `agents.md`, `@mention` | (uses it) |
| Per-agent USD budget cap + auto-pause | — | ✅ `rack profile <id> --budget` |
| Cost reporting + spike detection | — | ✅ `rack cost [--history]` |
| Project isolation (no context leak) | partial | ✅ session keys |
| Declarative fleet from version-controlled YAML | — | ✅ `rack add --from` |
| Drift / health / runaway detection | — | ✅ `rack doctor` |
| Role → cheapest-adequate-model policy | manual | ✅ one-command repolicy |

If a row isn't genuinely true for your setup, treat it as aspirational — honesty is the point
of this table.

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

## Concepts

- **Project agent** — one agent bound to one codebase/project, with a permission-locked
  workspace (`700`/`600`) holding `SOUL.md` (identity + session key), `AGENTS.md`,
  `TOOLS.md`, `HEARTBEAT.md`, `.rack-meta.json`, and a `memory/` log.
- **Specialist team** — shared programmer, reviewer, tester, knowledge, security, and manager
  agents, created once by `rack install` and used across all projects.
- **Session key** (`agent:<id>:<project>`) — the isolation primitive; prevents cross-project
  contamination and enables parallel work. Change with `rack scope <id> set <key>`.
- **Role→model policy** — each role maps to the cheapest adequate model; change a role once and
  every policy-following agent re-resolves. Pin one agent with `rack profile`.
- **Lobster workflow** — deterministic YAML pipelines for repeatable, token-efficient runs.

Configuration is kept in two synchronized places: `.rack-meta.json` per workspace (rack's
view) and `~/.openclaw/openclaw.json` (the OpenClaw daemon's view).

## Command reference

<details>
<summary><strong>Core lifecycle</strong></summary>

```bash
rack install              # Bootstrap OpenClaw and the specialist team
rack add [id] [path]      # Create project agent (interactive)
rack add --from spec.yaml # Provision a fleet from a YAML/JSON spec (declarative)
rack list                 # Show all agents
rack info <id>            # Display agent details
rack delete <id>          # Remove agent
```
</details>

<details>
<summary><strong>Cost & configuration</strong></summary>

```bash
rack models               # Role→model policy (set <role> <model>, preset, reset)
rack profile <id> [model] # Pin an agent's model (<provider/model>) or 'default' = follow policy
rack profile <id> --budget 5  # Set a $5 spending cap (auto-pause on breach)
rack scope <id> set <key> # Change project session key
rack keys                 # Manage API keys
rack cost [id]            # Token usage and costs (--json, --history [--days N])
```
</details>

<details>
<summary><strong>Maintenance & health</strong></summary>

```bash
rack maintain [id] check    # Health check and auto-fix
rack maintain [id] clean    # Clear memory logs
rack maintain [id] reset    # Clear memory + heartbeat
rack maintain [id] rebuild  # Full rebuild from metadata
rack maintain [id] sessions # Archive large/old sessions
rack doctor                 # System-wide diagnostics (budget, drift, runaway, gates)
```
</details>

<details>
<summary><strong>Security gates (opt-in)</strong></summary>

```bash
rack gates status           # Exec-approval policy, routing, isolation, audit posture
rack gates enable           # Apply approval gates + curated allowlist + chat routing
rack gates isolate on       # Confine tool execution to a per-agent Docker sandbox
rack gates disable          # Revert gate defaults (escape hatch)
rack install --gates        # Apply gates during install
```
</details>

<details>
<summary><strong>Context, team & workflows</strong></summary>

```bash
rack context [id]              # Recent activity overview
rack context [id] search <q>   # Search indexed memory
rack context [id] snapshot     # Create SNAPSHOT.md for fast agent context
rack context [id] compress     # Archive logs older than 30 days

rack team delegate "Fix login bug"   # Queue task for manager (--priority high)
rack team queue                       # Show pending tasks
rack team done <task-id>              # Mark task complete

rack workflow <id> create <name>      # Create a Lobster pipeline
```
</details>

### Role→model policy & provider support

rack is provider-agnostic. Each agent **role** maps to the cheapest model adequate for its
workload — that mapping is the policy, and you can override any role:

| Role | Default (Anthropic) | Why |
| ---- | ------------------- | --- |
| manager, reviewer, tester, knowledge | claude-haiku-4-5 | High-volume, low reasoning-density work |
| programmer, security | claude-sonnet-4-6 | Reasoning-dense generation and audits |
| repo / task (project agents) | sonnet / haiku | Project-agent type defaults |

Stronger models (opus-class) are an explicit per-agent pin, never a standing default. Changing
the policy (or switching provider preset) re-resolves every policy-following agent
automatically — pinned agents are never touched.

```bash
rack models preset openrouter-free   # All roles to OpenRouter free tier (no cost)
rack models preset openai            # OpenAI (gpt-4.1-nano / gpt-4.1-mini)
rack models preset google            # Google (gemini flash family)
rack models preset anthropic         # Restore Anthropic defaults
rack models set programmer openai/gpt-4.1          # Override one role
rack profile myproject anthropic/claude-opus-4-6   # Pin one agent
rack profile myproject default       # Re-attach the agent to its role policy
```

The old tier names (economy/standard/premium) are deprecated but still accepted with a
warning. Custom pricing can be added in `~/.openclaw/rack-models.json`.

## Engineering: spec-driven development

rack is where I practice spec-driven development as a discipline: write the specification for a
feature before the implementation, use RFC 2119 keywords (MUST/SHOULD/MAY) to make requirements
testable, and measure how much of the codebase is actually covered. The rollout is in progress —
specs cover the core lifecycle today and are extended outward.

```bash
./scripts/validate-specs.sh    # Validate spec structure/completeness (blocking in CI)
./scripts/spec-coverage.sh     # Report command/feature/test coverage (informational)
./scripts/metrics.sh           # Single source of truth for LOC / command / test counts
```

`spec-coverage.sh` reports **100% command coverage (25/25), 100% feature coverage (10/10),
100% of tracked specs test-backed**. "Covered" means a feature has a structured, validated
spec — not that every feature is fully built (e.g. `security-gates` is specified and shipped
opt-in). The tooling reports honestly, so the number reflects real specs.

See [specs/README.md](specs/README.md) for the full SSD documentation and
[CONTRIBUTING.md](CONTRIBUTING.md) for how to add a command.

### By the numbers

All figures are generated by [`scripts/metrics.sh`](scripts/metrics.sh) — there is no
hand-maintained count to drift out of sync:

- **~8,800 lines** of Bash in the shipped CLI (`lib` + `bin`); ~12,600 including tests and tooling
- **26 commands** (one `cmd_*` per file) + 1 experimental, over **12 helper modules**
- **276 unit tests** + 12 integration scenarios (60 assertions) + 6 specialist-role evals
- **15 specifications** (RFC 2119), validated in CI

```bash
./tests/run-all-tests.sh           # everything
./tests/unit/test-helpers.sh       # 276 unit tests
./tests/test-lifecycle.sh          # 12 integration scenarios (60 assertions)
./tests/evals/run-evals.sh         # 6 specialist-role evals
```

## Security

rack manages autonomous agents that can execute commands. Its safety model is **layered**:
agent-level constraints are instruction-based by default, and enforced tool-approval gates,
Telegram approval routing, and Docker workspace isolation are available **opt-in** via
`rack gates enable` / `rack gates isolate on` (or `rack install --gates`).

**Where you run rack matters.** A trusted homelab is a very different risk profile from a
public VPS — see [SECURITY.md](SECURITY.md) for the homelab-vs-VPS guidance, the privilege and
approval-gate model, what rack does and does **not** protect against, secret-storage backends
(keyring vs 0600 JSON), and the responsible-disclosure policy.

## Compatibility

rack tracks the current OpenClaw release line and the v1 `openclaw.json` schema. It is not yet
pinned to or CI-tested against specific OpenClaw versions — automated weekly compatibility
testing is a tracked roadmap item.

| rack-cli | Tested OpenClaw | `openclaw.json` schema | Notes |
|----------|-----------------|------------------------|-------|
| 0.1.x    | current release line (developed against the 2026.x line) | v1 | Manual verification; no version pin yet |

See [COMPATIBILITY.md](COMPATIBILITY.md) for the policy and how breaks are tracked.

## What's next

See [ROADMAP.md](ROADMAP.md) for the full phased plan. Near-term highlights:

1. Expand the eval harness (`tests/evals/`) and feed results into model right-sizing
2. Run integration tests in CI; promote the macOS job to a required check
3. Turn security gates on by default once headless approval routing lands
4. CI-test against pinned OpenClaw versions (auto-issue on schema break)

## Contributing

Pure Bash, modular architecture. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, the
SSD/spec-first flow, code style (`set -euo pipefail`), and how to add a command. PRs welcome for
OpenClaw integrations, command implementations, test coverage, and docs.

---

*Built and run by Santiago Yie — an 18-year-old backend engineer — to manage his own OpenClaw
fleets, and as a deliberate exploration of spec-driven development, modular Bash at scale, and
cost-aware multi-agent operations. The "rack" name is OpenClaw-anchored on every public surface;
a searchable rename (e.g. `clawfleet`) is a tracked, deferred decision (see ROADMAP).*

## License

Apache 2.0 — see [LICENSE](LICENSE).
