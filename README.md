# docket — a governed runtime and control plane for agent fleets

[![CI](https://github.com/yielab/docket/actions/workflows/ci.yml/badge.svg)](https://github.com/yielab/docket/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-green.svg)](https://www.python.org/)
[![Specs: 100%](https://img.shields.io/badge/spec%20coverage-100%25-success.svg)](specs/)

> **docket** runs teams of autonomous coding agents across multiple projects, and governs what
> they are allowed to do. It solves three problems the field has converged on as genuinely hard:
> **coordinated Lead-owned context** (the anti-fragility pattern vs solo-agent chaos),
> **per-project runtime-resource isolation** (disjoint workspaces, port ranges, and git worktrees
> per Implementer), and a **governance/HITL/audit spine** — where *every* tool call an agent makes
> passes through one policy chokepoint before it executes. One `docket` command keeps it all running.
>
> *Not an agent framework (vs CrewAI/LangGraph/AutoGen): docket owns the loop precisely so it can
> intercept it, and rents only open protocols — OpenAI-compatible HTTP, MCP, containers.*

> [!WARNING]
> **Early-stage / beta software — treat it as a prototype, not a hardened tool.** docket has
> **not** reached a stable release, and every release ships with a `-beta.N` version suffix for
> as long as that stays true. What exists today — agent-pod provisioning, per-project runtime
> isolation (session keys, port ranges, scratch dirs, git worktrees), docket's own gated agent
> turn loop, real pod dispatch with budget and verification gates, layered security (approval
> gates, an audit log, four approval channels), token accounting, and a read-only API — is
> implemented and covered by the automated suite (pytest + golden parity + `ruff`/`mypy --strict`).
> **Passing tests is not the same as production-ready:** none of it has been hardened against real
> fleets at scale or adversarial input. Expect rough edges and breaking changes between versions.
> **Verify anything important yourself before relying on it**, and treat every dollar figure as an
> estimate, not a bill (see [Cost reporting and its limits](#cost-reporting-and-its-limits)).

<p align="center">
  <img src="docs/assets/hero.gif" alt="docket in action: provision an isolated project pod, delegate a task, check the governance posture, and run a fleet health check" width="760">
</p>

<p align="center"><em>The whole loop in one terminal: <strong>provision → delegate → govern → keep healthy.</strong></em></p>

**Contents:** [Why](#why) · [The gated turn](#the-gated-turn) · [Telegram](#mobile-control-via-telegram)
· [Install](#install) · [Tour](#60-second-tour) · [Screenshots](#see-it-in-action) ·
[Cost](#cost-reporting-and-its-limits) · [Concepts](#concepts) · [Commands](#command-reference)
· [Security](#security) · [Tack integration](#integrating-with-a-control-plane-tack) ·
[Embedding the runtime](#embedding-the-runtime) ·
[Compatibility](#compatibility) · [Roadmap](#whats-next) · [Contributing](#contributing)

---

## Why

Running one coding agent is easy. Running a fleet across several projects, unattended, surfaces
three problems the field treats as genuinely hard:

### 1 — Coordinated Lead-owned context

A **Lead** agent owns context, memory, and human communication for a project; **workers**
(Implementer, Reviewer, Tester) receive bounded tasks and report back. The Lead never edits
code. This is not multi-agent for its own sake — it is the separation of duties that turns
"an agent changed the code" into "a change was reviewed before it landed."

The separation is **structural, not advisory**. A Reviewer is not merely *told* not to edit code:
its tool registry is composed from its role archetype and does not contain `write`, `edit`, or
`bash` at all, so an attempt to call one comes back as a tool-not-found denial. Being unable to
do a thing is a strictly stronger guarantee than being instructed not to.

Every pod member is provisioned with a **startup contract** — the exact files re-read after each
context compaction (`WORKFLOW_AUTO.md` + a dated memory log), seeded so a fresh or just-compacted
agent reliably knows its codebase path, its read order, and what the project actually **is** (a
curated `MEMORY.md` summary), instead of losing that context and answering from its own
scaffolding. `docket doctor` re-seeds any agent whose contract is missing or stale.

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

**Every tool call goes through one chokepoint.** `core/tools.py`'s dispatcher is the single place
a tool can execute, and three policy hooks run there: `pre_input`, `pre_tool_call`, and
`pre_output`. A call is allowed, denied, or routed to a human for approval *before* the handler
ever runs — and the decision is traced.

The classifier is **argument-aware**: it reads the whole command line, including every segment
behind a `;`, `&&`, `||`, or pipe. So `git status` is allowed and `git push origin production`
asks, which a binary-path allowlist structurally cannot do.

docket's approval store is answerable through **four channels** — a CLI channel
(`docket approve`/`docket deny`), a headless HTTP endpoint, MCP, and Telegram — and every grant,
deny, or timeout writes an entry to the hash-chained, tamper-evident audit log, tagged with the
channel it came from. The headless channels mean CI jobs and automation can vote without a chat
account. **Approvals fail closed on timeout.**

**Workspace isolation** (`docket gates isolate on`) confines tool execution to a per-agent Docker or
`bwrap` sandbox. It stays **opt-in**, and it **fails closed**: if isolation is on and neither backend
is usable, the turn is refused outright and the refusal is audit-logged — it does not quietly fall
back to running unsandboxed.

---

**Everything else** (provisioning, health, cost guardrails) is operational tooling that keeps
this three-layer stack running reliably:

- **One-command provisioning**: `docket init` lazily prepares shared workstation state and
  provisions the current project's pod (Lead + Implementer by default); `docket init --from
  agents.yaml` provisions a declarative, version-controlled fleet.
- **Real pod dispatch**: `docket pod <project> dispatch` runs one full Lead → Implementer →
  Reviewer → Tester pipeline turn, budget-gated and traced. `docket serve --dispatch` drives
  every pod's queue in the background.
- **Config drift detection**: `docket doctor` and `docket maintain check` catch runaway loops,
  stale sessions, and drifted or missing startup contracts.
- **Budget guardrails**: per-pod USD cap that auto-pauses the pod's Lead on breach. It fires on a
  **clearly labelled token-based estimate** — docket does not relabel an estimate as spend (see
  [Cost reporting and its limits](#cost-reporting-and-its-limits)). Dispatch refuses a paused
  pod's tasks outright; `docket profile <id> --resume` clears the pause. A role→cheapest-adequate-
  model policy and `docket cost` reporting round it out.
- **An API for an external plan-of-record**: `docket serve` exposes a versioned, Bearer-gated API —
  reads (`/status.json`, `/metrics`, `/health`, `/runs`, `/approvals`, `GET /tasks/<project>`,
  `GET /traces/<project>?since=`) and writes (`POST /tasks/<project>` to enqueue,
  `POST /dispatch/<project>` to run a queue, `POST /approvals/<token>` to decide one).
  **docket deliberately does not build a dashboard** — it competes on the write and governance side
  and feeds a planner that holds the roadmap, board and sprints. The trace read is cursor'd so a
  consumer resumes exactly where it stopped; docket aggregates nothing on its behalf.
  See [Integrating with a control plane (Tack)](#integrating-with-a-control-plane-tack) for the
  full route table, the poll loop and the limits.

## The gated turn

docket runs the agent turn itself, which is what makes the guardrails real rather than advisory:

```
        docket pod <p> dispatch
                 │
                 ▼
   ┌─────────────────────────────┐
   │ core/agent_loop.py          │  bounded: max iterations, max tool calls,
   │  the turn loop              │  wall-clock timeout, measured-token budget
   └──────────────┬──────────────┘
                  │ model asks for a tool
                  ▼
   ┌─────────────────────────────┐
   │ core/tools.py::dispatch_tool│  ◀── THE chokepoint. Nothing executes
   │  pre_tool_call policy hook  │      around it; an AST test enforces that.
   │  high-risk classifier       │
   └──────┬───────────┬──────────┘
          │           │
      allow│      ask │ ──▶ approval store ──▶ CLI · HTTP · MCP · Telegram
          │           │                              │
          ▼           ▼                              ▼
    tool handler   denied (fail-closed)        hash-chained audit log
```

**Built-in tools:** `read`, `write`, `edit`, `glob`, `grep`, `bash` (sandboxed when
`docket gates isolate on`), and `fetch`
(domain-allowlisted, size-capped, timeout-bounded).

> [!NOTE]
> **External MCP tools reach a live turn, and a role's capability denial reaches them back.**
> `docket mcp servers add` registers a server; its tools are namespaced `mcp__<server>__<tool>` (so a
> remote server can never shadow `bash`), screened for prompt injection before they are ever
> advertised, and dispatched through the same chokepoint as a built-in.
>
> **The part worth knowing:** a role's `denied_tools` lists built-in *names*, and no namespaced MCP
> name can ever match one — so a naive wire would hand a Reviewer `mcp__fs__write_file` and silently
> void the guarantee above. Denials are therefore enforced by **capability**, not name: an adapted
> tool is registered write-capable (nothing can prove a remote tool is read-only), so a role that
> denies `write` denies it too. The honest consequence is that **a read-only role currently gets zero
> MCP tools** rather than a correctly narrowed subset. That is the fail-closed answer given what is
> knowable today, not an oversight.
>
> Cost is measured, not assumed: with no servers configured the path adds ~0.004ms and spawns
> nothing; each configured stdio server costs roughly 0.6s per turn, since there is no listing cache
> yet. Configuring a server is the opt-in.

The model wire is a non-streaming **OpenAI-compatible** chat-completions API with function tools.
OpenRouter and Vercel AI Gateway have built-in endpoint/key resolution; other hosted or local
llama.cpp / vLLM / LM Studio endpoints can be registered explicitly. The adapter is stdlib
`urllib`; no vendor SDK is pulled in, and no per-vendor client is hand-rolled. See
[Models, gateways, and coding harnesses](docs/MODEL-GATEWAYS.md).

## Mobile control via Telegram

Wiring a pod's Lead to Telegram (`docket wire <id>`) turns your phone into a second **control
surface**. It is a command channel, not a chat with an assistant — there are exactly four commands:

| Command | What it does |
| --- | --- |
| `/status` | What is pending for the bound pod |
| `/delegate <task description>` | Queue a task for that pod |
| `/approve <token>` | Grant a gated action |
| `/deny <token>` | Refuse one |

**Anything else is refused with an "unrecognized command" reply — including plain prose.** That is
deliberate, not a missing feature. A bot handle is effectively a public endpoint, so an inbound
message is untrusted input from the open internet; docket refuses rather than guessing what the
sender meant, and free text only becomes agent input through `/delegate`, after passing the
`pre_input` prompt-injection policy. Only a chat explicitly bound with `docket wire` can do
anything at all, and an unauthorized attempt is refused **and** audit-logged.

A Telegram decision lands in the same hash-chained audit log as a CLI or HTTP one, tagged
`channel="telegram"` — that is what makes this a real approval channel rather than a notification
feed.

**Two limits worth knowing before you rely on it:**

- **docket never messages you first.** There is no outbound notification: a gated action does not
  ping the group, and a finished task does not report back. `send_message` is only ever called as
  the reply to a message you sent. Poll it with `/status`.
- **`/delegate` returns a task id, not an answer.** It replies `Queued for pod '<project>':
  [task-...]`; the pipeline's actual output is read through `docket pod <p> queue`, `docket trace`,
  or the [control-plane API](#integrating-with-a-control-plane-tack). If you want the result on your
  phone, that is the piece to build.

```bash
docket keys add TELEGRAM_BOT_TOKEN   # stored 0600, redacted from traces
docket wire myproject-lead           # bind a pod's Lead to a Telegram group
docket serve --telegram              # REQUIRED to poll -- plain `docket serve` does not
docket unwire myproject-lead         # remove the binding
```

Add `--dispatch` if you want a delegated task to actually run rather than sit queued.

Setup is guided: create a bot, add it to a group, then run `wire` and send the one-time command it
shows—no numeric Telegram ID lookup is required. See
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

# Then, from a project, initialize everything Docket needs + its minimum pod
cd ~/code/myproject && docket init
```

```bash
uv pip install .   # or: pip install .  — then run `python -m docket --version`
```

> Installs to `~/.local` (no `sudo`); add `~/.local/bin` to `PATH` if it isn't already.

**Prerequisites:** Python 3.11+ · an **OpenAI-compatible chat-completions endpoint** (a built-in
OpenRouter/Vercel gateway key, or a registered compatible/local server) · `git` · `bash` (launcher and
installer only). Optional: `fzf` (interactive picker), `docker` (workspace isolation),
`systemctl` (nothing requires it; docket degrades gracefully without it). The package pulls in
Typer, Rich, Pydantic, pydantic-settings, and filelock; MCP support is the optional `[mcp]` extra.

Use `docket keys add OPENROUTER_API_KEY` plus `docket models preset openrouter`, or
`docket keys add AI_GATEWAY_API_KEY` plus `docket models preset ai-gateway`. Register other
compatible endpoints with `docket models provider add`; reserve `DOCKET_LLM_BASE_URL` /
`DOCKET_LLM_API_KEY` for a process-wide override. Everything docket owns lives under
`~/.docket/` (`DOCKET_HOME` to relocate).

## 60-second tour

```bash
docket init                              # in a repo: provision its pod (Lead + Implementer)
docket add reviewer                     # expand the current pod with another role
docket pod myproject                     # inspect pod members, roles, isolation details
docket pod myproject delegate "Add auth" # queue a task for the pod
docket pod myproject dispatch            # run Lead → Implementer pipeline once
docket status                            # current project: members, tasks, readiness
docket status --all                      # global summary, one row per project
docket list                              # detailed global agent inventory
docket doctor                            # workstation health: drift, runaway, stale sessions
docket gates status                      # governance posture: approval gates, audit log
docket profile myproject --budget 5      # cap spend; auto-pauses the pod on breach
docket profile myproject --resume        # clear an auto-pause, unblock the pod's queue
docket cost myproject                    # measured token usage + a labelled estimate
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

> Screenshots are from a real run; project names are anonymized. They were captured before the
> Phase 19 runtime cutover, so panes showing a dollar figure or daemon state are stale — see
> [docs/assets/README.md](docs/assets/README.md) for the standing recapture list.

## What docket does that a bare agent CLI does not

| Need | Typical agent CLI | docket adds |
|------|-------------------|-------------|
| Run one agent turn with tools | ✅ | (owns its own loop, so it can gate it) |
| **Every tool call through one policy chokepoint** | — | ✅ `pre_input`/`pre_tool_call`/`pre_output`, AST-enforced single path |
| **Argument-aware command classification** | allowlist by binary, if any | ✅ reads the whole line and every `;`/`&&`/`\|` segment |
| **Role→toolset as data** | prompt-level instruction | ✅ a Reviewer's registry has no `write`/`edit`/`bash` to call |
| One-command per-project pod provisioning | — | ✅ `docket init` (lazy global bootstrap + stack auto-detect) |
| Project isolation: session keys (no context leak) | — | ✅ `agent:<id>:<project>` per pod member |
| Project isolation: runtime resources (ports + scratch) | — | ✅ disjoint port range + scratch dir, injected into the real env |
| Project isolation: git worktree per Implementer | partial | ✅ dedicated branch + worktree; flat-workspace fallback |
| Pod pipeline dispatch (Lead → Implementer → Reviewer → Tester) | — | ✅ `docket pod <p> dispatch` / `serve --dispatch` |
| Declarative fleet from version-controlled YAML | — | ✅ `docket init --from` |
| Drift / health / runaway detection | — | ✅ `docket doctor` |
| Role → cheapest-adequate-model policy | manual | ✅ one-command repolicy |
| Per-agent USD budget cap + auto-pause | — | ✅ `docket profile <id> --budget` |
| Approval gates + headless channels + audit log (HITL) | — | ✅ CLI / HTTP / MCP / Telegram, each audit-logged |
| Hash-chained tamper-evident audit log | — | ✅ `docket audit verify` — the chain continues across rotation, so a deleted generation is detected |
| Pre-merge verification gate | — | ✅ `verifyCmd` per pod + a structural Tester PASS/FAIL gate |
| Scheduled + webhook-triggered pod dispatch | — | ✅ `@every N` / `HH:MM` UTC + `POST /dispatch/<project>` |
| Versioned read API for dashboards | — | ✅ `/status.json` v1, `/metrics`, `/health`, `/runs`, `/approvals` |
| External tools without writing code | varies | ✅ MCP servers reach a live turn, gated identically to built-ins — and a role's capability denial applies to them |

If a row isn't true for your setup, treat it as aspirational — honesty is the point of this table.

**vs agent frameworks (CrewAI/LangGraph/AutoGen):** those frameworks own the loop, which means they
own the interception points. docket owns the loop for the opposite reason — to put a policy gate
inside it. What docket does *not* implement is agent reasoning or prompt-engineering opinion; it
implements the governed execution substrate underneath.

## Cost reporting and its limits

> [!IMPORTANT]
> **docket reports measured tokens, not recorded dollar spend.** Agent turns run on docket's own
> loop, and token counts come back **measured** from the model endpoint's usage field — those
> numbers are real. Dollar figures do not: docket will not multiply tokens by a price table and
> call the result spend. `docket cost` therefore shows tokens plus a clearly labelled estimate
> (`~$X.XX (estimated)`), and **budget auto-pause fires on that labelled estimate.**

- **Token counts (measured, real).** Reported by the endpoint per call and accumulated per turn,
  per hop, and per agent. The turn loop's own token budget is enforced against these real counts.
- **Dollar estimates (best-effort).** Computed from a **hardcoded pricing table** (~13 models,
  snapshotted from a known catalog). Model prices change; treat these as estimates. Models not in
  the table show `n/a`. `docket cost` and `docket models` print the snapshot date so you can judge
  staleness. Override or extend in `~/.docket/docket-models.json`.
- **Context-size estimates are a third, weaker thing.** The static-context guards in
  `docket maintain check` use a stated characters-per-token approximation. docket never presents
  those as exact token counts, and never mixes them with the measured counts above.

> [!WARNING]
> **No figure docket prints is your provider's invoice.** Prompt caching, minimum charges,
> rounding, taxes, free-tier credits, and provider-side pricing changes all drift the real number.
> Use docket's cost figures for **relative** decisions (which agent is expensive, when a run
> spikes, whether to auto-pause) — and always **reconcile against your provider's own billing
> dashboard** before treating any number as money owed. Treat model-to-model savings comparisons
> as directional only.

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
  workspace after each Implementer hop and **fails** the task (with a `verification_failed`
  trace event) on non-zero exit. If a pod has a Tester, its hop is gated too: the Tester's first
  line must read `PASS`/`FAIL` — a `FAIL` or unparseable report ends the task the same way
  (a rework-eligible verdict is retried first, bounded by `maxReworkCycles`),
  instead of "the Tester agent said it was fine" being taken on faith.
- **Org specialists** — `security`, `knowledge`, and `manager` are created lazily by the first
  `docket init` and shared across the fleet (`scope: org`).
- **Session key** (`agent:<id>:<project>`) — the isolation primitive; prevents cross-project
  contamination and enables parallel work. Change with `docket scope <id> set <key>`.
- **Role→model policy** — each role maps to the cheapest adequate model; change a role once and
  every policy-following agent re-resolves. Pin one agent with `docket profile`.

Configuration lives in two places docket owns: `.docket-meta.json` per workspace (per-agent
model, session key, persona, budget) and `~/.docket/fleet.json` (agent registration, channel
bindings, gate/isolation flags, provider endpoints, the org default model).

### Declarative orchestration

- **Pipelines** — `docket pipeline validate/plan/run`. One dialect, defined in `core/pipeline.py`
  and executed by `core/orchestrator.py` over the same pod-dispatch state machine, so `plan`
  renders from the real executor rather than a second pretty-printer that can drift from it.
- **Roles are data** — `docket roles list/show/add/validate`. Role archetypes are declarative
  definitions rather than hardcoded branches — including each role's **denied tools**, which is
  what makes a Reviewer structurally unable to write. **Pod blueprints** provision a named pod
  shape (software, research, content, ops, agentic-product) in one step. Pods are not limited to
  "build a web app".
- **Typed handoffs** — hops exchange a structured artifact (summary, changed files, diff ref,
  verdict) instead of concatenating raw text, and a **context compiler** fits each hop's message
  to a per-role budget, shedding artifact fields in a documented priority order.
- **Runs and cancellation** — `docket runs list/show` keeps one record per dispatch invocation;
  `docket runs cancel` kills the in-flight hop's process group. Scheduled (cron) and webhook
  triggers can drive pipelines, and `--follow` tails one live.

### Durable state docket owns

Nothing else keeps a durable transcript, so docket owns the state that has to survive a restart or
a context reset — all of it under `~/.docket/`:

- **Session history** — durable per-session turn history with compaction that never splits a
  tool-call/tool-result pair apart.
- **Task ledger** — dispatch mechanically maintains a delimited docket-owned region inside each
  Lead's `HEARTBEAT.md`, so the ledger is true whether or not the agent wrote its own entries.
  Only text between the delimiters is ever rewritten, so the agent's prose survives.
  `docket doctor` flags divergence from `TASK_LIST.json` and re-syncs under `--fix`.
- **Conversation registry** — `docket conversations list/show/resume/set`, seeded when you wire a
  channel and kept current by dispatch after every hop.
- **Memory distillation** — `docket maintain distill` summarizes memory logs into `MEMORY.md` and
  archives the originals. `clean` and `reset` distill **first** by default, so memory is never
  bare-deleted; if distillation fails, the delete is aborted rather than proceeding.
- **Audit log** — hash-chained and tamper-evident (`docket audit verify`), with rotation.

---

## Command reference

```bash
docket init [id] [path]                    # Bootstrap if needed + create a minimum project pod
docket add <role> [--project <id>]         # Add role agent(s) to an existing pod
docket pod <id> [add <role> | remove <m>]  # Inspect/resize a pod
docket pod <id> delegate/queue/dispatch    # Queue and run pod work
docket list / info <id> / delete <id>      # Fleet-wide view / one agent / teardown
docket models / profile <id>               # Role→model policy / pin or budget-cap one agent
docket cost [id] / doctor / maintain <id>  # Tokens / fleet health / per-agent upkeep
docket gates status                        # Approval-gate, routing, and audit posture
docket serve [--dispatch] [--telegram]     # Control-plane API; queues; Telegram (opt-in flag)
docket pipeline validate/plan/run <file>   # Declarative pipelines, run by the dispatch engine
docket roles list/show/add/validate        # Declarative role archetypes
docket runs list/show/cancel               # Dispatch run registry; cancel an in-flight hop
docket conversations list/show/resume      # The conversation registry docket owns
docket audit verify                        # Verify the audit log's tamper-evidence chain
docket trace [id] / metrics                # Execution traces / session success-rate and drift
docket mcp serve | servers add/list/remove # Expose the control plane, or add external tool servers
```

Every command, subcommand, and flag — including `context`, `keys`/`auth`, `gates
enable/isolate/classes`, `policies`, `persona`, `approve`/`deny`, `completions` — is documented in
**[docs/commands.md](docs/commands.md)**, the full reference.

## Engineering

docket practices spec-driven development (specs before implementation, RFC 2119 keywords, real
coverage — see [specs/README.md](specs/README.md)) and is checked by `ruff`, `mypy --strict`, a
pytest suite, and an 18-case golden-parity suite — see
[CONTRIBUTING.md](CONTRIBUTING.md) for how to run them and add a command.

By the numbers:

- **2,429 tests** in the pytest suite (`tests/python/`)
- **~30,396 lines** of Python in the shipped `docket` package
- **24 specifications** (RFC 2119), validated in CI
- **37 commands**, each documented in [docs/commands.md](docs/commands.md)

```bash
uv run python scripts/smoke_workflow.py                # observable full workflow, no credentials
uv run python scripts/smoke_workflow.py --live-model   # realistic memory-backed repair on :8081
uv run pytest                                        # 2,429-test Python suite
bash tests/golden/run.sh verify-all                  # 18-case byte-parity suite
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

The smoke command provisions a temporary four-role pod, talks to a deterministic loopback
OpenAI-compatible endpoint through the real HTTP adapter, executes a gated file write, passes a
mechanical check and Reviewer verdict, pauses for CLI approval, resumes, passes Tester, then verifies
sessions, typed handoffs, traces, audit, usage, and run records. Add `--workdir <empty-path>` to keep
the generated world for inspection. `--live-model` defaults to a realistic scenario: it distills
dated memory with a superseded decision, requires that decision to cross the Lead handoff, repairs
a Git-worktree checkout module after proving its existing regressions fail for the intended defects,
and runs project plus hidden behavioral acceptance against that effective worktree. Sparse
`- [exact]` memory records preserve normative IDs/formulas literally and fail closed before archive
if the model corrupts them; ordinary log narration remains summarized. Genuine
tool-policy prompts are answered through
`docket approve` in the isolated canary home; the pipeline approval
remains a separate pause. Use `--scenario basic` for the smaller W23 live workflow, or
`--endpoint <loopback-url>`/`--model <id>` when discovery needs an override. The live canary uses
un-scripted inference from `http://127.0.0.1:8081/v1`, sends no API key, and stays opt-in.

Every live turn receives one runtime-safe startup contract with its already-resolved project roots,
plus the current private HEARTBEAT/AGENTS/TOOLS/MEMORY state. It does not replay the generated
manual instructions to open or maintain those files: HEARTBEAT authoring scaffolding and AGENTS'
startup block are projected away while actual state, red lines, and custom rules remain. Higher-
priority work is retained first under the existing static-context budget, cuts are visibly marked,
and Docket—not the model—owns private reads and turn durability.

Every figure above is drift-guarded in CI by `uv run python scripts/metrics.py --check`, which
fails the build when this list and the tree disagree — and fails just as loudly if the prose stops
stating them, so the guard cannot quietly end up verifying nothing.

CI also runs the suite against the **lowest dependency versions `pyproject.toml` actually permits**
(`uv pip compile --resolution lowest-direct`), so the declared floors are a tested promise rather
than an assumption. That job exists because they were neither: two of the six advertised bounds
turned out to be unusable when first measured.

## Security

docket manages autonomous agents that can execute commands. Its safety model is **layered**, and
the enforcing layer is real: every tool call passes through one dispatcher where the policy engine
and the high-risk action classifier run before the handler does. Grants, denials and timeouts are
audit-logged with the channel they came from — CLI, HTTP, MCP, Telegram, or a board.

Being honest about the limits:

- **`--no-gates` does not disable the tool-call gate.** The policy engine and the high-risk command
  classifier are **always** active — `cli/_install.py` says so in its own docstring. What
  `--no-gates` skips is the automatic setup of approval *routing*. An `"ask"` verdict still creates
  an approval token and still blocks the call, timing out to **denied**. The gate is stronger than
  the flag's name suggests, which is the safe direction — but it is not what "opt out" reads like.
- **Network egress is not locked down.** `fetch` is domain-allowlisted and **refuses everything by
  default** until you opt a domain in (`FETCH_ALLOWED_DOMAINS`) — but `bash` can still reach the
  network through interpreters and package managers on the curated allowlist. `fetch` is the
  *inspectable* path, not yet the *only* path.
- **The audit log keeps one generation of history, and erasure beyond that is evident, not
  prevented.** Rotation carries the previous generation's final `seq` and hash forward, so a chain
  declares what it continues from and `docket audit verify` reports a break when that predecessor
  cannot be produced. But only **one** rotation back is verifiable, and anyone who can delete both
  the log and its backup at once leaves something indistinguishable from a fresh install. What
  survives further back is the *fact* that history existed, not its content.
- **Enforcement covers the tool calls docket dispatches.** That is every tool call in a docket
  agent turn. It is not a system-wide enforcement daemon: a process a user starts outside docket is
  outside its scope.

**Where you run docket matters.** A trusted homelab is a very different risk profile from a
public VPS — see [SECURITY.md](SECURITY.md) for the homelab-vs-VPS guidance, the privilege and
approval-gate model, what docket does and does **not** protect against, secret-storage backends
(keyring vs 0600 JSON), and the responsible-disclosure policy.

## Integrating with a control plane (Tack)

**docket executes; something else holds the plan of record.** docket has said since Phase 11 that it
does not build a dashboard of its own — it competes on the write and governance side and *feeds*
one. [**Tack**](https://github.com/yielab/tack) is that consumer: a single-binary project manager
that owns the roadmap, board, sprints and dependency DAG. It **polls** docket and folds runs,
approvals, traces and metrics back onto the board.

**Tack polls; docket never pushes.** There is no webhook and no callback, deliberately: a poll loop
survives a restart or an outage on either side with no replay logic anywhere, and the cursor below
is the whole recovery mechanism.

### 1. Run the server

```bash
docket serve --port 7331 --token-file ~/.docket/serve.token --dispatch
```

- **Binds `127.0.0.1` only.** It is not reachable off the host. Run Tack on the same machine, or
  front it with your own TLS terminator / SSH tunnel — docket does not terminate TLS.
- `--token-file` writes the bearer token `0600` instead of printing it to stdout. Prefer it over
  copying the token out of a log.
- `--dispatch` also drives every pod's queue through the Lead → Implementer → Reviewer → Tester
  pipeline on each sweep. Those are **real, costed agent turns** — leave it off for a read-only
  monitor and drive dispatch explicitly with `POST /dispatch/<project>` instead.
- `--telegram` additionally long-polls docket's own bot, so approvals can be answered from a phone.

### 2. Authentication

Every route is `Authorization: Bearer <token>` **except three**, which are deliberately open so a
health check or a Prometheus scrape needs no credential:

| Open (no token) | Bearer required |
| --- | --- |
| `GET /status.json` · `GET /metrics` · `GET /health` | everything else |

A missing or wrong token is a `401`. The comparison is timing-safe.

### 3. The routes Tack uses

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/status.json` | Fleet snapshot — `apiVersion`, `agents`, `channels`, `totalCostUsd` |
| `GET` | `/health` | Liveness for the poller |
| `GET` | `/metrics` | Prometheus text format |
| `GET` | `/tasks/<project>` | The pod queue, with each task's hops, status and timestamps |
| `POST` | `/tasks/<project>` | Enqueue a task — `{"description": "...", "priority": "normal"}` |
| `POST` | `/dispatch/<project>` | Run that pod's queue now; returns a run id immediately |
| `GET` | `/runs` · `/runs?project=<p>` · `/runs/<id>` | One record per dispatch invocation |
| `GET` | `/approvals` | Everything currently blocking on a human |
| `POST` | `/approvals/<token>` | Decide one — `{"action": "grant"\|"deny", "channel": "tack"}` |
| `GET` | `/traces/<project>?since=<cursor>` | Cursor'd raw trace events |
| `POST` | `/pods` | Provision a pod — `{"project", "path", "blueprint", "pod", "budget", "verifyCmd"}` |

**Tag approvals with `channel: "tack"`.** It is a first-class value in the closed vocabulary
`core/approval.py` owns (`cli`, `http`, `mcp`, `telegram`, `timeout`, `tack`), so a board-granted
approval is distinguishable in the hash-chained audit log from a CI job's or a phone's. An
unrecognised channel is rejected with a `400` rather than let free text into a record whose entire
value is honest provenance.

### 4. The poll loop

```bash
TOKEN=$(cat ~/.docket/serve.token)
CURSOR=""                       # empty on the first poll only

while :; do
  PAGE=$(curl -s -H "Authorization: Bearer $TOKEN" \
    --get --data-urlencode "since=$CURSOR" \
    "http://127.0.0.1:7331/traces/myproject")

  echo "$PAGE" | jq -c '.events[]' | while read -r EVENT; do
    :                           # fold the event onto the board
  done

  CURSOR=$(echo "$PAGE" | jq -r '.next')   # persist this; it is the resume point
  sleep 10
done
```

`.events` are **verbatim JSONL strings** — docket does no reformatting, no filtering by event
type/role/session, and aggregates nothing on the consumer's behalf. They arrive **in timestamp
order**, across every session file the project has.

`.next` is the cursor. Store it durably next to whatever you ingested, and hand it back as `since`.
Round-tripping it delivers **each event exactly once**: nothing re-ingested, nothing skipped. It is
a compound `<ts>:<n>` value rather than a bare timestamp because trace `ts` is second-granularity —
a bare timestamp would either replay a whole second or silently drop later events within it. Treat
it as opaque; a bare timestamp is also accepted, but only the value docket hands back carries the
tie-break count.

Polling with an unchanged cursor and nothing new written returns `{"events": [], "next": <same>}` —
a no-op, not a duplicate.

### 5. Enqueue and dispatch

```bash
# Queue work. Returns the task id; the CLI sees it immediately -- one path, not two.
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"description": "Add a health endpoint", "priority": "high"}' \
  http://127.0.0.1:7331/tasks/myproject

# Run the queue. Returns a run id straight away; the pipeline continues async.
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:7331/dispatch/myproject
```

**`POST /tasks` honours the `pre_input` policy gate exactly as the CLI does.** A blocking policy
returns a `4xx` **naming the policy** — never swallowed into a `500`. A policy demanding approval
returns the task as `"status": "waiting_approval"` **with its `approvalToken`**, rather than a `200`
implying it is queued to run. Poll `/approvals`, decide with `POST /approvals/<token>`, and the
gated task genuinely resumes or dies — it is not merely a record update.

`POST /dispatch` hands back the run id **before** any dispatch work is attempted, so the outcome
always lands in the run registry rather than vanishing behind a fire-and-forget thread.

### 6. What this integration deliberately is not

The design rule for the whole write API is **expose what `core/` already does, add no new
behaviour** — same auth, same policy hooks, same audit entries the CLI path produces. A route that
starts growing flags the CLI does not have has stopped being this feature.

- **Not multi-tenant.** Tack is one operator's control center, not a tenant. There is no per-caller
  identity, no quota and no isolation between callers — a valid bearer token can do anything the CLI
  can. Multi-tenancy is **cut**, not deferred.
- **No streaming.** Poll; there is no SSE or WebSocket surface.
- **Tack must ingest traces durably.** `docket trace expire` (30-day default) treats docket's JSONL
  as a cache once an external consumer holds the durable copy. If Tack does not persist what it
  reads, retention will eventually delete it.
- **`/metrics` counters are not monotonic.** They are lifetime-of-current-storage counts: audit-log
  rotation and trace retention both drop history, so a `rate()` over one can misread a partial value
  as a reset. Do not build an alert that assumes otherwise.
- **`cost_usd` is always `0.0`.** Token counts are measured and real; dollars are a clearly labelled
  estimate rendered by `docket cost`. Do not surface an estimate as billed spend
  (see [Cost reporting and its limits](#cost-reporting-and-its-limits)).

## Embedding the runtime

The governed runtime ships as a second, standalone package: **`docket-runtime`** (under
[`packages/docket-runtime/`](packages/docket-runtime/)). It is the turn loop, the gated tool
registry, the policy engine, the approval store and the audit chain — without the CLI, so a
product can embed the guardrails instead of reinventing them. Verified standalone: a clean
install pulls only `pydantic` and `filelock`.

This is **packaging and a public API contract, not a rewrite** — the control plane and the runtime
build from the same source tree, so they cannot drift apart. What it is deliberately *not* is a
hosted product runtime: multi-tenancy, authentication for external callers, queues, streaming and
per-customer quota are out of scope, and the embedding product owns its own serving layer.

## Compatibility

docket has no external daemon dependency. Its compatibility surface is the model endpoint.

| docket-cli | Model endpoint | MCP | Notes |
|------------|----------------|-----|-------|
| 0.2.x | Non-streaming OpenAI-compatible `/chat/completions` (function tools) | stdio servers, optional `[mcp]` extra | Hermetic wire coverage for OpenRouter/Vercel plus compatible registered endpoints; no live-provider CI |

An endpoint that does not implement tool calling will run text-only turns; anything requiring a
tool will fail cleanly rather than silently. See [COMPATIBILITY.md](COMPATIBILITY.md) for the
policy and how breaks are tracked.

## What's next

See [ROADMAP.md](ROADMAP.md) for the full phased plan.

**Phase 22 — a control-plane write API, so an external planner can drive docket.** docket has said
since Phase 11 that it does not build a dashboard of its own; it competes on the write and
governance side and feeds one. That consumer now exists, so the work is closing the CLI/HTTP
asymmetry — things reachable from the CLI or MCP but not over HTTP.

| Route | What it closes | Status |
| --- | --- | --- |
| `POST /tasks/<project>` | Enqueue a task | ✅ shipped |
| `GET /tasks/<project>` | The pod queue as JSON | ✅ shipped |
| `GET /traces/<project>?since=` | Cursor'd trace read, raw events out | ✅ shipped |
| approval `channel` label | So a board-granted approval is distinguishable in the audit chain from a CI job's | ✅ shipped |
| `POST /pods` | Provisioning over HTTP — `docket add` was CLI-only | ✅ shipped |

The design rule is deliberately narrow: **expose what `core/` already does, add no new behaviour** —
same auth, same policy hooks, same audit entries the CLI path produces. `POST /tasks` honours the
`pre_input` gate exactly as the CLI does: a blocking policy returns a 4xx naming the policy, and a
policy demanding approval returns the task as `waiting_approval` with its token rather than a 200
pretending it is queued to run.

**Trace retention** also shipped (`docket trace expire`, 30-day default). The reasoning changed
rather than being re-argued: once an external consumer durably ingests trace events, docket's JSONL
becomes a cache rather than the only copy, which makes expiring it safe rather than lossy. Two
consequences worth knowing: retention is measured from when a session *ended*, not from last
activity, and `/metrics` counters derived from traces are now lifetime-of-current-storage counts
rather than monotonic totals — don't build an alert that assumes otherwise. The audit log is
deliberately excluded; telemetry may be lossy, an audit log may not.

Still open: **closing the egress gap** so `fetch` is the only network path rather than merely the
inspectable one; **caching MCP tool listings** so a configured stdio server is not re-spawned every
turn; and **telling a genuinely read-only remote tool from a write-capable one**, without which a
read-only role can be handed no MCP tools at all rather than the right subset.

## Contributing

Python package with a three-layer architecture (`cli/` → `core/` → `edges/`), dependencies
pointing inward only: `cli/` renders, `core/` decides, `edges/` is the only layer that performs
I/O. Two invariants matter most — **every tool call goes through `core/tools.py`'s single
dispatcher** (an AST test enforces it), and **docket-owned JSON goes through `edges/store.py`**
(atomic, filelocked, 0600). See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup (`uv`), the
SSD/spec-first flow, code style (`ruff` + `mypy --strict`), and how to add a command. PRs welcome
for tool handlers, command implementations, test coverage, and docs.

## License

Apache 2.0 — see [LICENSE](LICENSE).
