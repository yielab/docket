# docket-cli — the cost-aware ops layer for OpenClaw agent fleets

[![CI](https://github.com/santiagoyie/docket-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/santiagoyie/docket-cli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Shell: Bash 4+](https://img.shields.io/badge/shell-bash%204%2B-green.svg)](https://www.gnu.org/software/bash/)
[![Specs: 100%](https://img.shields.io/badge/spec%20coverage-100%25-success.svg)](specs/)

> Stop your [OpenClaw](https://openclaw.dev) agents from burning budget and leaking context
> across projects. **docket** is a single Bash CLI that adds per-agent budget caps, hard project
> isolation, and drift detection on top of OpenClaw — the ops layer for people running more
> than one agent.

*Independent project. Not affiliated with or endorsed by OpenClaw or the OpenClaw Foundation.*

<!-- DEMO: a 30-second asciinema cast (create agent → set budget → see cost) belongs here,
     above the fold. Highest-ROI asset; record with `asciinema rec` and embed the SVG/player. -->

## Why

Running one OpenClaw agent is easy. Running a fleet surfaces three problems OpenClaw doesn't
solve for you:

- **Runaway API cost.** Autonomous agents loop, retry, and call expensive models without
  asking. docket gives every agent a per-agent USD budget cap that auto-pauses on breach, a
  role→cheapest-adequate-model policy, and spike detection in `docket cost`.
- **Context leak across projects.** One agent's memory bleeding into another's is the
  "noisy neighbor" problem. docket assigns each agent a session key (`agent:<id>:<project>`)
  so memory and context stay isolated.
- **Config drift.** OpenClaw updates and autonomy regressions silently change behavior.
  `docket doctor` and `docket maintain check` detect drift, budget overruns, runaway loops, and
  stale sessions; `docket add --from agents.yaml` keeps the fleet declarative and reproducible.

## Install

```bash
# Homebrew (macOS/Linux) — recommended
brew tap santiagoyie/docket-cli https://github.com/santiagoyie/docket-cli
brew install docket-cli

# Or the install script (review it before piping to a shell)
curl -fsSL https://raw.githubusercontent.com/santiagoyie/docket-cli/main/install.sh | bash

# Or from source
git clone https://github.com/santiagoyie/docket-cli.git
cd docket-cli && ./install.sh        # installs to ~/.local by default; DOCKET_PREFIX to override

# Then bootstrap OpenClaw + the specialist team
docket install
```

> Installs to `~/.local` (no `sudo`); add `~/.local/bin` to `PATH` if it isn't already. The old
> `sudo ln -s` symlink method is retired.

**Prerequisites:** Bash 4.0+ · Python 3.7+ · the [OpenClaw](https://openclaw.dev) daemon ·
`systemctl` (service management) · `fzf` (optional, interactive picker).

## 60-second tour

```bash
docket add myproject ~/code/myproject   # create an isolated project agent
docket profile myproject --budget 5     # cap it at $5; it auto-pauses on breach
docket list                             # see every agent at a glance
docket cost myproject                   # token usage + dollar cost, with spike detection
docket doctor                           # fleet health: drift, budget, runaway, gates
```

That's the loop docket is built around: **create → cap → watch → keep healthy.**

## How it relates to OpenClaw

OpenClaw already spawns and coordinates agents (`agents.md`, `@mention` delegation). docket does
**not** reinvent that — it wraps OpenClaw to add the operational layer a fleet needs:

| Need | OpenClaw native | docket adds |
|------|-----------------|-----------|
| Spawn / coordinate agents | ✅ `agents.md`, `@mention` | (uses it) |
| Per-agent USD budget cap + auto-pause | — | ✅ `docket profile <id> --budget` |
| Cost reporting + spike detection | — | ✅ `docket cost [--history]` |
| Project isolation (no context leak) | partial | ✅ session keys |
| Declarative fleet from version-controlled YAML | — | ✅ `docket add --from` |
| Drift / health / runaway detection | — | ✅ `docket doctor` |
| Role → cheapest-adequate-model policy | manual | ✅ one-command repolicy |

If a row isn't genuinely true for your setup, treat it as aspirational — honesty is the point
of this table.

## Project Status

| Feature | Status | Notes |
|---------|--------|-------|
| Agent lifecycle (add/delete/maintain) | ✅ Working | Full CRUD via `docket maintain` |
| Session scoping & isolation | ✅ Working | Multi-project isolation via session keys |
| Specialist agents team | ✅ Working | 6 pre-configured roles |
| Lobster workflow integration | ✅ Working | YAML pipeline support |
| Cost tracking & budget caps | ✅ Working | Role→model policy, per-agent budget, runaway detection |
| API key management | ✅ Working | Centralized key distribution |
| CI pipeline | ✅ Working | GitHub Actions on every push/PR |
| Telegram integration | ✅ Working | Manual wire: create group, add bot, run `docket wire` |
| Security gates | ✅ Opt-in | Exec-approval enforcement + curated allowlist, Telegram approval routing, and Docker workspace isolation via `docket gates enable` / `isolate`; status in `docket doctor`. Opt-in by design (on-by-default pending headless approval routing) |
| Secret storage backends | ✅ Working | `file` (0600 JSON, default) or `keyring` (libsecret, no plaintext at rest) via `DOCKET_SECRETS_BACKEND` |
| Manager coordination | ✅ Working | Full delegation state machine (`docket team delegate` → queue → done) |

## Concepts

- **Project agent** — one agent bound to one codebase/project, with a permission-locked
  workspace (`700`/`600`) holding `SOUL.md` (identity + session key), `AGENTS.md`,
  `TOOLS.md`, `HEARTBEAT.md`, `.docket-meta.json`, and a `memory/` log.
- **Specialist team** — shared programmer, reviewer, tester, knowledge, security, and manager
  agents, created once by `docket install` and used across all projects.
- **Session key** (`agent:<id>:<project>`) — the isolation primitive; prevents cross-project
  contamination and enables parallel work. Change with `docket scope <id> set <key>`.
- **Role→model policy** — each role maps to the cheapest adequate model; change a role once and
  every policy-following agent re-resolves. Pin one agent with `docket profile`.
- **Lobster workflow** — deterministic YAML pipelines for repeatable, token-efficient runs.

Configuration is kept in two synchronized places: `.docket-meta.json` per workspace (docket's
view) and `~/.openclaw/openclaw.json` (the OpenClaw daemon's view).

## Command reference

<details>
<summary><strong>Core lifecycle</strong></summary>

```bash
docket install              # Bootstrap OpenClaw and the specialist team
docket add [id] [path]      # Create project agent (interactive)
docket add --from spec.yaml # Provision a fleet from a YAML/JSON spec (declarative)
docket list                 # Show all agents
docket info <id>            # Display agent details
docket delete <id>          # Remove agent
```
</details>

<details>
<summary><strong>Cost & configuration</strong></summary>

```bash
docket models               # Role→model policy (set <role> <model>, preset, reset)
docket profile <id> [model] # Pin an agent's model (<provider/model>) or 'default' = follow policy
docket profile <id> --budget 5  # Set a $5 spending cap (auto-pause on breach)
docket scope <id> set <key> # Change project session key
docket keys                 # Manage API keys
docket cost [id]            # Token usage and costs (--json, --history [--days N])
```
</details>

<details>
<summary><strong>Maintenance & health</strong></summary>

```bash
docket maintain [id] check    # Health check and auto-fix
docket maintain [id] clean    # Clear memory logs
docket maintain [id] reset    # Clear memory + heartbeat
docket maintain [id] rebuild  # Full rebuild from metadata
docket maintain [id] sessions # Archive large/old sessions
docket doctor                 # System-wide diagnostics (budget, drift, runaway, gates)
```
</details>

<details>
<summary><strong>Security gates (opt-in)</strong></summary>

```bash
docket gates status           # Exec-approval policy, routing, isolation, audit posture
docket gates enable           # Apply approval gates + curated allowlist + chat routing
docket gates isolate on       # Confine tool execution to a per-agent Docker sandbox
docket gates disable          # Revert gate defaults (escape hatch)
docket install --gates        # Apply gates during install
```
</details>

<details>
<summary><strong>Context, team & workflows</strong></summary>

```bash
docket context [id]              # Recent activity overview
docket context [id] search <q>   # Search indexed memory
docket context [id] snapshot     # Create SNAPSHOT.md for fast agent context
docket context [id] compress     # Archive logs older than 30 days

docket team delegate "Fix login bug"   # Queue task for manager (--priority high)
docket team queue                       # Show pending tasks
docket team done <task-id>              # Mark task complete

docket workflow <id> create <name>      # Create a Lobster pipeline
```
</details>

### Role→model policy & provider support

docket is provider-agnostic. Each agent **role** maps to the cheapest model adequate for its
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
docket models preset openrouter-free   # All roles to OpenRouter free tier (no cost)
docket models preset openai            # OpenAI (gpt-4.1-nano / gpt-4.1-mini)
docket models preset google            # Google (gemini flash family)
docket models preset anthropic         # Restore Anthropic defaults
docket models set programmer openai/gpt-4.1          # Override one role
docket profile myproject anthropic/claude-opus-4-6   # Pin one agent
docket profile myproject default       # Re-attach the agent to its role policy
```

The old tier names (economy/standard/premium) are deprecated but still accepted with a
warning. Custom pricing can be added in `~/.openclaw/docket-models.json`.

## Engineering: spec-driven development

docket is where I practice spec-driven development as a discipline: write the specification for a
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
- **270+ unit tests** + 12 integration scenarios (60 assertions) + 6 specialist-role evals
  (the exact unit count varies by environment — optional-dep tests for `libsecret`/`fzf` skip
  when those aren't installed; `scripts/metrics.sh` prints the count for your machine)
- **15 specifications** (RFC 2119), validated in CI

```bash
./tests/run-all-tests.sh           # everything
./tests/unit/test-helpers.sh       # 270+ unit tests
./tests/test-lifecycle.sh          # 12 integration scenarios (60 assertions)
./tests/evals/run-evals.sh         # 6 specialist-role evals
```

## Security

docket manages autonomous agents that can execute commands. Its safety model is **layered**:
agent-level constraints are instruction-based by default, and enforced tool-approval gates,
Telegram approval routing, and Docker workspace isolation are available **opt-in** via
`docket gates enable` / `docket gates isolate on` (or `docket install --gates`).

**Where you run docket matters.** A trusted homelab is a very different risk profile from a
public VPS — see [SECURITY.md](SECURITY.md) for the homelab-vs-VPS guidance, the privilege and
approval-gate model, what docket does and does **not** protect against, secret-storage backends
(keyring vs 0600 JSON), and the responsible-disclosure policy.

## Compatibility

docket tracks the current OpenClaw release line and the v1 `openclaw.json` schema. It is not yet
pinned to or CI-tested against specific OpenClaw versions — automated weekly compatibility
testing is a tracked roadmap item.

| docket-cli | Tested OpenClaw | `openclaw.json` schema | Notes |
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
cost-aware multi-agent operations. The "docket" name is OpenClaw-anchored on every public surface;
a searchable rename (e.g. `clawfleet`) is a tracked, deferred decision (see ROADMAP).*

## License

MIT — see [LICENSE](LICENSE).
