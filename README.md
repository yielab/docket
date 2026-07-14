# docket — ops/control plane for OpenClaw agent fleets

[![CI](https://github.com/yielab/docket/actions/workflows/ci.yml/badge.svg)](https://github.com/yielab/docket/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-green.svg)](https://www.python.org/)
[![Specs: 100%](https://img.shields.io/badge/spec%20coverage-100%25-success.svg)](specs/)

> **docket** is the ops/control plane for people running [OpenClaw](https://openclaw.dev) agents
> across multiple projects. It solves three problems the field has converged on as genuinely hard:
> **coordinated Lead-owned context** (the anti-fragility pattern vs solo-agent chaos),
> **per-project runtime-resource isolation** (disjoint workspaces, port ranges, and git worktrees
> per Implementer), and a **governance/HITL/audit spine** (approval gates, headless approval
> channel, full audit log, budget caps). One `docket` command keeps it all running.
>
> *An ops/control plane, not an agent framework (vs CrewAI/LangGraph/AutoGen) — and a
> governed multi-project fleet, not a solo personal assistant (vs raw OpenClaw).*

*Independent project. Not affiliated with or endorsed by OpenClaw or the OpenClaw Foundation.*

> [!WARNING]
> **Early-stage / beta software — treat it as a prototype, not a hardened tool.** docket has
> **not** reached a stable release, and every release ships with a `-beta.N` version suffix for
> as long as that stays true. What exists today — agent-pod provisioning, per-project runtime
> isolation (session keys, port ranges, scratch dirs, git worktrees), real pod dispatch with
> budget and verification gates, layered security (approval gates on by default, an audit log,
> three approval channels), cost tracking, and a read-only API — is implemented and covered by
> the automated suite (pytest + golden parity + `ruff`/`mypy --strict`). **Passing tests is not
> the same as production-ready:** none of it has been hardened against real fleets at scale,
> adversarial input, or every OpenClaw version. Expect rough edges and breaking changes between
> versions. **Verify anything important yourself before relying on it**, and treat every dollar
> figure as an estimate, not a bill (see [Cost reporting and its limits](#cost-reporting-and-its-limits)).

<p align="center">
  <img src="docs/assets/hero.gif" alt="docket in action: provision an isolated project pod, delegate a task, check the governance posture, and run a fleet health check" width="760">
</p>

<p align="center"><em>The whole loop in one terminal: <strong>provision → delegate → govern → keep healthy.</strong></em></p>

**Contents:** [Why](#why) · [Telegram](#mobile-control-via-telegram) · [Install](#install) ·
[Tour](#60-second-tour) · [Screenshots](#see-it-in-action) · [vs OpenClaw](#how-it-relates-to-openclaw)
· [Cost](#cost-reporting-and-its-limits) · [Concepts](#concepts) · [Commands](#command-reference)
· [Security](#security) · [Compatibility](#compatibility) · [Roadmap](#whats-next) ·
[Contributing](#contributing)

---

## Why

Running one OpenClaw agent is easy. Running a fleet across several projects surfaces three
problems the field treats as genuinely hard:

### 1 — Coordinated Lead-owned context

A **Lead** agent owns context, memory, and human communication for a project; **workers**
(Implementer, Reviewer, Tester) receive bounded tasks and report back. The Lead never edits
code. This is not multi-agent for its own sake — it is the separation of duties that turns
"an agent changed the code" into "a change was reviewed before it landed."

Every pod member is provisioned with a **startup contract** — the exact files the OpenClaw
runtime re-reads after each context compaction (`WORKFLOW_AUTO.md` + a dated memory log),
seeded so a fresh or just-compacted agent reliably knows its codebase path, its read order,
and what the project actually **is** (a curated `MEMORY.md` product summary), instead of losing
that context and answering from its own scaffolding. `docket doctor` re-seeds any agent whose
contract is missing or stale.

See **[Agent Teams (Pods)](docs/AGENT-TEAMS.md)**, the core reference.

### 2 — Per-project runtime-resource isolation

Three isolation layers, each independent:

- **Context**: each agent gets a session key (`agent:<id>:<project>`) — no cross-project memory
  bleed, even when two pods run the same model.
- **Runtime resources**: each pod gets a **non-overlapping port range** and a **scratch
  directory** (allocated once, freed on delete) so two projects can run dev servers and test
  databases simultaneously without colliding — injected into the Implementer's real process
  environment (`DOCKET_PORT_BASE`/`DOCKET_PORT_COUNT`/`DOCKET_SCRATCH_DIR`), not just documented
  as prose it has to read and remember to follow.
- **Git worktrees**: for repo pods the Implementer works in a dedicated `git worktree` on its
  own branch (`docket/<project>/<member-id>`) — the convergent isolation pattern every major
  coding-agent tool has landed on (Cursor, Codex, etc.). Falls back to the flat workspace
  gracefully when git is unavailable or the codebase isn't a repo.

### 3 — Governance / HITL / audit spine

docket's security model is **layered**: instruction-level constraints, plus enforced
tool-approval gates that are **on by default** for new installs (`docket install`, opt out with
`--no-gates`). Three approval channels work today — a CLI channel (`docket approve`/`docket
deny`), a headless HTTP channel, and Telegram (see [Mobile control via Telegram](#mobile-control-via-telegram)
below) — with a full audit log recording every grant/deny on every channel. Docker workspace
isolation stays opt-in (`docket gates isolate on`). Risky operations not on the curated allowlist
require human sign-off before they execute; the headless channels mean CI jobs and automation can
vote without a Telegram account. Approvals fail closed on timeout.

---

**Everything else** (provisioning, health, cost guardrails) is operational tooling that keeps
this three-layer stack running reliably:

- **One-command provisioning**: `docket add` provisions a pod (Lead + Implementer by default);
  `docket add --from agents.yaml` provisions a declarative, version-controlled fleet.
- **Real pod dispatch**: `docket pod <project> dispatch` runs one full Lead → Implementer →
  Reviewer → Tester pipeline turn, budget-gated and traced. `docket serve --dispatch` drives
  every pod's queue in the background.
- **Config drift detection**: `docket doctor` and `docket maintain check` catch runaway loops,
  stale sessions, and autonomy regressions silently introduced by OpenClaw updates.
- **Budget guardrails**: per-agent USD cap that auto-pauses on breach (from the daemon's
  recorded spend, not a pricing estimate). A role→cheapest-adequate-model policy and
  `docket cost` reporting round it out.
- **Read API for dashboards**: `docket serve` exposes a versioned read-only API
  (`/status.json`, `/metrics`, `/health`) dashboards can consume. docket governs and keeps
  agents healthy; a purpose-built dashboard reads from it.

---

## Mobile control via Telegram

Wiring a pod's Lead to Telegram (`docket wire <id>`) turns your phone into a second control
surface, not just a notification feed:

- **Conversational dispatch** — message the Lead directly ("Fix the login bug," "what's the
  status?") and it runs through the same pipeline `docket pod <id> dispatch` runs from a shell.
  No laptop required to queue or check on work.
- **Approve from your phone** — gates are on by default, so a risky action pings the wired group;
  reply to grant or deny it. Telegram is one of three approval channels, not the only one — a CLI
  channel and a headless HTTP endpoint work too, so automation isn't locked to a chat app.
- **Status without a shell** — ask a Lead what's active, or check in on a fleet, from wherever you
  are.

```bash
docket wire myproject-lead     # bind a pod's Lead to a Telegram group
docket unwire myproject-lead   # remove the binding
```

Setup is manual today (create a bot, add it to a group, run `wire`) — see
[docs/commands.md](docs/commands.md#wire) for the walkthrough.

## Install

```bash
# Homebrew (macOS/Linux) — recommended
brew tap yielab/docket-cli https://github.com/yielab/docket
brew install docket-cli

# Or the install script
curl -fsSL https://raw.githubusercontent.com/yielab/docket/main/install.sh | bash

# Or from source
git clone https://github.com/yielab/docket.git
cd docket && ./install.sh   # installs to ~/.local; DOCKET_PREFIX to override

# Then bootstrap OpenClaw + the specialist team
docket install
```

```bash
uv pip install .   # or: pip install .  — then run `python -m docket --version`
```

> Installs to `~/.local` (no `sudo`); add `~/.local/bin` to `PATH` if it isn't already.

**Prerequisites:** Python 3.11+ · the [OpenClaw](https://openclaw.dev) daemon · `systemctl`
(degrades gracefully on macOS) · `bash` (launcher/installer only) · `fzf` (optional, interactive
picker). The package pulls in Typer, Rich, Pydantic, pydantic-settings, and filelock.

## 60-second tour

```bash
docket add myproject ~/code/myproject    # provision a pod (Lead + Implementer)
docket pod myproject                     # inspect pod members, roles, isolation details
docket pod myproject delegate "Add auth" # queue a task for the pod
docket pod myproject dispatch            # run Lead → Implementer pipeline once
docket list                              # see every agent, scope, and pod at a glance
docket doctor                            # fleet health: drift, runaway, stale sessions
docket gates status                      # governance posture: approval gates, audit log
docket profile myproject --budget 5      # cap spend; auto-pauses on breach
docket cost myproject                    # token usage + recorded dollar spend
```

That's the loop: **provision → delegate → dispatch → keep healthy → keep in budget.**

## See it in action

<table>
<tr>
<td width="50%">

**`docket pod <project>` — pod structure**

<img src="docs/assets/pod.png" alt="docket pod: two members — lead and implementer — with roles, model policy, and isolation details" width="100%">

</td>
<td width="50%">

**`docket models` — role→model policy**

<img src="docs/assets/models.png" alt="docket models: each agent role mapped to the cheapest adequate model with pricing" width="100%">

</td>
</tr>
</table>

> Screenshots are from a real run against a live OpenClaw install; project names are anonymized.
> (Two prior screenshots here, `docket gates status` and `docket doctor`, were pulled because
> they showed pre-0.2.0 output — gates as opt-in/inactive — that no longer matches the
> gates-on-by-default behavior below; see [docs/assets/README.md](docs/assets/README.md) for
> the recapture note.)

## How it relates to OpenClaw

OpenClaw already spawns and coordinates agents (`agents.md`, `@mention` delegation). docket
wraps OpenClaw to add the operational layer a fleet needs:

| Need | OpenClaw native | docket adds |
|------|-----------------|-------------|
| Spawn / coordinate agents | ✅ `agents.md`, `@mention` | (uses it) |
| One-command per-project pod provisioning | — | ✅ `docket add` (stack auto-detect) |
| Project isolation: session keys (no context leak) | partial | ✅ `agent:<id>:<project>` per pod member |
| Project isolation: runtime resources (ports + scratch) | — | ✅ disjoint port range + scratch dir, injected into the Implementer's real env |
| Project isolation: git worktree per Implementer | — | ✅ dedicated branch + worktree; flat-workspace fallback |
| Pod pipeline dispatch (Lead → Implementer → Reviewer → Tester) | — | ✅ `docket pod <p> dispatch` / `serve --dispatch` |
| Declarative fleet from version-controlled YAML | — | ✅ `docket add --from` |
| Drift / health / runaway detection | — | ✅ `docket doctor` |
| Role → cheapest-adequate-model policy | manual | ✅ one-command repolicy |
| Per-agent USD budget cap + auto-pause | — | ✅ `docket profile <id> --budget` |
| Cost reporting (recorded spend + spike detection) | — | ✅ `docket cost [--history]` |
| Approval gates + headless channel + audit log (HITL) | — | ✅ on by default; `GET/POST /approvals`, Telegram routing |
| Pre-merge verification gate | — | ✅ `verifyCmd` per pod + a structural Tester PASS/FAIL gate; either failing → task stays `pending` |
| Scheduled + webhook-triggered pod dispatch | — | ✅ `@every N` / `HH:MM` UTC + `POST /dispatch/<project>` |
| Workflow validate + dry-run plan | — | ✅ `docket workflow <id> validate/plan` |
| Versioned read API for dashboards | — | ✅ `/status.json` v1, `/metrics`, `/health` |

If a row isn't true for your setup, treat it as aspirational — honesty is the point of this table.

**vs agent frameworks (CrewAI/LangGraph/AutoGen):** docket is an ops/control plane — it does
not implement agent reasoning, tool use, or orchestration logic. That's the daemon's job.
docket governs, provisions, isolates, and monitors.

**vs raw OpenClaw:** OpenClaw gives you one agent at a time. docket adds the multi-project fleet
layer: structured pods, runtime isolation, a governance spine, and the operational tooling to
keep everything healthy at scale.

## Cost reporting and its limits

docket's cost numbers come in two flavors:

- **Recorded spend (trustworthy).** Dollar figures in `docket cost` and the budget cap come
  straight from OpenClaw's session usage logs — the daemon records what each call actually cost.
  This does not depend on any pricing table docket maintains, so the budget auto-pause fires on
  real money.
- **Comparative estimates (best-effort).** "What this would cost on a cheaper model" and role→model
  price labels are computed from a **hardcoded pricing table** (~13 models, snapshotted from a known
  OpenClaw catalog). Model prices change; treat these as estimates. Models not in the table show
  `n/a` for the estimate (recorded spend is still tracked). `docket cost` and `docket models` print
  the snapshot date so you can judge staleness. Override or extend in `~/.openclaw/docket-models.json`.

> [!IMPORTANT]
> **No figure docket prints is your provider's invoice.** Even "recorded spend" is an
> *accounting calculation* — it is what OpenClaw's usage logs report, derived from token counts
> and per-model rates. It will **not** match your provider's final bill exactly: prompt caching,
> minimum charges, rounding, taxes, free-tier credits, and provider-side pricing changes all
> drift the real number. Use docket's cost figures for **relative** decisions (which agent is
> expensive, when a run spikes, whether to auto-pause) — and always **reconcile against your
> provider's own billing dashboard** before treating any number as money owed.

Within those limits: the recorded-spend and budget-cap numbers track real usage and are what the
auto-pause fires on; treat model-to-model savings comparisons as directional only.

## Concepts

**Agent teams are the heart of docket.** Everything else (isolation, cost guardrails, health
checks) exists to keep *teams of agents* running reliably. The separation of duties — **Lead
plans, Implementer writes, Reviewer/Tester gate** — turns "an agent changed the code" into "a
change was reviewed and validated before it landed." Full model in **[Agent Teams (Pods)](docs/AGENT-TEAMS.md)**.

- **Project pod** — each project is an isolated pod of project-scoped agents. `docket add`
  provisions a lean **Lead + Implementer** by default; add Reviewer/Tester/extra Implementers
  with `docket pod <project> add <role>` or `--pod full` / `--with`. The **Lead never edits
  code** — it plans, owns context/memory + human comms, and dispatches work. Every member has
  its own permission-locked workspace (`700`/`600`) with `SOUL.md`, `AGENTS.md`,
  `HEARTBEAT.md`, `.docket-meta.json`, and a `memory/` log.
- **Real dispatch** — `docket pod <id> dispatch` runs one complete pipeline turn (Lead →
  Implementer → Reviewer if present → Tester if present), budget-gated, traced, and
  **pod-local** — never crosses pod boundaries. `docket serve --dispatch` drives all pods
  continuously from the background.
- **Pre-merge verification** — set `verifyCmd` with `docket pod <project> add --verify "<cmd>"`
  (or `set-verify` on an existing member); the dispatch pipeline runs it in the Implementer's
  workspace after each Implementer hop and leaves the task `pending` (with a `verification_failed`
  trace event) on non-zero exit. If a pod has a Tester, its hop is gated too: the Tester's first
  line must read `PASS`/`FAIL` — a `FAIL` or unparseable report blocks the pipeline the same way,
  instead of "the Tester agent said it was fine" being taken on faith.
- **Org specialists** — `security`, `knowledge`, and `manager` are created once by `docket install`
  and shared across the fleet (`scope: org`). An optional org **Portfolio Manager**
  (`docket install --portfolio`) adds cross-pod fleet visibility — advisory only, never a pod member.
- **Session key** (`agent:<id>:<project>`) — the isolation primitive; prevents cross-project
  contamination and enables parallel work. Change with `docket scope <id> set <key>`.
- **Role→model policy** — each role maps to the cheapest adequate model; change a role once and
  every policy-following agent re-resolves. Pin one agent with `docket profile`.
- **Lobster workflow** — deterministic YAML pipelines for repeatable, token-efficient runs.

Configuration is kept in two synchronized places: `.docket-meta.json` per workspace (docket's
view) and `~/.openclaw/openclaw.json` (the daemon's view).

---

## Command reference

```bash
docket install [--portfolio] [--no-gates]  # Bootstrap OpenClaw + org specialists
docket add [id] [path]                     # Create a project pod (--from spec.yaml for a fleet)
docket pod <id> [add <role> | remove <m>]  # Inspect/resize a pod
docket pod <id> delegate/queue/dispatch    # Queue and run pod work
docket list / info <id> / delete <id>      # Fleet-wide view / one agent / teardown
docket models / profile <id>               # Role→model policy / pin or budget-cap one agent
docket cost [id] / doctor / maintain <id>  # Spend / fleet health / per-agent upkeep
docket gates status                        # Approval-gate, routing, and audit posture
docket serve [--dispatch]                  # Read-only API, optionally driving pod queues
```

Every command, subcommand, and flag — including `context`, `workflow`, `keys`/`auth`, `gates
enable/isolate/classes`, `approve`/`deny`, `trace`, `audit`, `completions` — is documented in
**[docs/commands.md](docs/commands.md)**, the full reference.

## Engineering

docket practices spec-driven development (specs before implementation, RFC 2119 keywords, real
coverage — see [specs/README.md](specs/README.md)) and is checked by `ruff`, `mypy --strict`,
**813 tests** in the pytest suite, a 16-case golden-parity suite, and specialist-role evals — see
[CONTRIBUTING.md](CONTRIBUTING.md) for how to run them and add a command.

## Security

docket manages autonomous agents that can execute commands. Its safety model is **layered**:
agent-level constraints are instruction-based, and enforced tool-approval gates are **on by
default** for new installs (opt out with `docket install --no-gates`; re-apply or reverse later
with `docket gates enable` / `docket gates disable`). Approvals are answerable via a CLI channel
(`docket approve`/`docket deny`), a headless HTTP channel, or Telegram, and every grant/deny is
audit-logged. Docker workspace isolation (`docket gates isolate on`) stays **opt-in**.

A built-in high-risk action-class policy (`docket gates classes`) always routes money-movement
and secret-access commands to approval. Being honest about its limit: prod-deploy actions that
overlap the curated allowlist (`git`, `npm`) are documented policy, not yet daemon-enforced — the
exec-allowlist gates by binary path, not arguments, so `git push` isn't blocked by this layer
alone. Tracked as an open gap, not glossed over.

**Where you run docket matters.** A trusted homelab is a very different risk profile from a
public VPS — see [SECURITY.md](SECURITY.md) for the homelab-vs-VPS guidance, the privilege and
approval-gate model, what docket does and does **not** protect against, secret-storage backends
(keyring vs 0600 JSON), and the responsible-disclosure policy.

## Compatibility

docket tracks the current OpenClaw release line and the v1 `openclaw.json` schema.

| docket-cli | Tested OpenClaw | `openclaw.json` schema | Notes |
|------------|-----------------|------------------------|-------|
| 0.2.x | current release line (2026.x) | v1 | Manual verification; no version pin yet |

See [COMPATIBILITY.md](COMPATIBILITY.md) for the policy and how breaks are tracked.

## What's next

See [ROADMAP.md](ROADMAP.md) for the full phased plan. Near-term priorities:

1. Expand the eval harness (`tests/evals/`) and feed results into model right-sizing
2. Run integration tests in CI; promote the macOS job to a required check
3. CI-test against pinned OpenClaw versions (auto-issue on schema break)

## Contributing

Python package with a three-layer architecture (`cli/` → `core/` → `edges/`), where
`edges/adapters/openclaw.py` is the Anti-Corruption Layer — the only module that knows the
OpenClaw file formats. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup (`uv`), the
SSD/spec-first flow, code style (`ruff` + `mypy --strict`), and how to add a command. PRs
welcome for OpenClaw integrations, command implementations, test coverage, and docs.

## License

Apache 2.0 — see [LICENSE](LICENSE).
