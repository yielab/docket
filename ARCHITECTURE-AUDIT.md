# Architecture & Language Audit — docket

> Independent CTO-level review. Advisory document, not committed product docs.
> Date: 2026-06-22 · Scope: architecture, code health, language-base fitness.

## Verdict in one line

Bash was the **correct starting choice** and is still defensible today, but the
codebase has reached the size and data-model complexity where it is **fighting
its language**. The 135 embedded `python3` calls are the architecture telling you
the core is no longer a shell problem. If a rewrite ever happens, the lowest-risk
target is **Python**, not Go/Rust — and the trigger should be a product
requirement, not aesthetics.

---

## 1. What this project actually is

A ~14.7K-line Bash CLI that provisions and manages autonomous-agent deployments
on top of the OpenClaw daemon. It is fundamentally an **orchestrator of other
CLIs and a manager of JSON state**:

- Shells out to: `openclaw`, `systemctl`, `docker`, `git`, `flock`, Telegram.
- Owns a **dual-source JSON state model** (`.docket-meta.json` per workspace +
  `~/.openclaw/openclaw.json`) that must stay in sync.
- Adds real application logic on top: schema validation, budgets, cost policy,
  trace/audit, drift detection, approval routing, a local HTTP/Prometheus server.

That second and third bullet are the crux of the language question.

## 2. Codebase metrics (measured, not quoted)

| Signal | Value | Read |
|---|---|---|
| Shell LOC | ~14,720 across 55 `.sh` files | Large for Bash; ~5× the usual comfort ceiling |
| Entry point | `bin/docket` 157 lines | Clean, thin dispatcher ✅ |
| `lib/commands/` | 7,121 LOC, 22+ files, one `cmd_*` each | Good modular discipline ✅ |
| `lib/helpers/` | 2,989 LOC, 19 files | Several are **app logic, not glue** ⚠️ |
| Embedded `python3` calls | **135** across **32 files** | The central architectural tension 🔴 |
| `jq` usage | 1 | Python is the JSON engine, not jq |
| Unit assertions | 301 (test-helpers.sh) + lifecycle integration | Strong for a Bash project ✅ |
| Specs | 19 spec files, spec-validation gate in CI | Unusually mature ✅ |
| ShellCheck (warning sev) | effectively clean: 54 info (SC1091 source-follow) + 1 warning | Excellent hygiene ✅ |
| CI | shellcheck gate, spec validation, unit tests, metrics-sync gate, macOS matrix | Better than most Bash repos ✅ |

## 3. What is genuinely well-engineered

This is **not** a naive shell script pile. Notable maturity:

- **Write safety** (`lib/helpers/json.sh`): atomic write via tmp+`os.replace`,
  refuses to write invalid JSON (no truncation on producer failure), rolling
  `.bak`, `0600` enforcement.
- **Concurrency safety**: `with_docket_lock` wraps leaf writers in `flock` with a
  no-nest/no-deadlock discipline and graceful fallback.
- **Strict mode** centralized in `lib/core/init.sh` (`set -euo pipefail`).
- **Schema validation** on metadata writes (`meta_set` → `AGENT_SCHEMA`).
- **Honest metrics gate** in CI — README numbers fail the build if they drift.
- Clean router/command/helper separation; one `cmd_*` per file.

Credit where due: the team has built, by hand, many of the guardrails a real
language would give for free. That discipline is the only reason 14.7K lines of
Bash is maintainable at all.

## 4. The core problem: the language no longer matches the workload

The smoking gun is **135 `python3` invocations**. Every structured operation —
read a field, write a field, emit Prometheus text, compute a budget, validate a
schema — forks a Python interpreter via a heredoc. Consequences:

1. **The real language is "Bash + inline Python," which is two languages with a
   stringly-typed boundary.** Data crosses the boundary as unstructured text;
   neither side type-checks the other. This is the least safe possible seam.
2. **Performance**: a single `docket doctor` forks Python ~18 times; `list` ~4×.
   Interpreter startup dominates. Fine at human scale, poor for the
   `serve`/metrics-scrape path.
3. **Python is already a hard dependency.** The project's stated "Bash + python3"
   dependency means you pay the Python runtime cost *without* getting Python's
   ergonomics — the worst of both worlds for the data layer.
4. **`lib/helpers/` has outgrown "glue."** `budget.sh`, `policy.sh`, `drift.sh`,
   `trace.sh`, `audit.sh`, `approval.sh`, `security.sh`, `serve.sh` are
   application logic. Building a Prometheus exporter and an HTTP status server in
   Bash-wrapping-Python is past Bash's competence zone.
5. **Dual-source sync is a state-machine problem.** Keeping two JSON sources
   consistent under concurrency is exactly the class of problem where types,
   transactions, and tests pay off — and exactly where Bash is weakest.

Where Bash is still genuinely *right* here: the install/bootstrap path
(`install.sh`, `uninstall.sh`, `curl | bash`), and thin shell-outs to
`systemctl`/`docker`/`git`. Those should stay Bash regardless.

## 5. Language options, ranked for THIS project

### Option A — Stay Bash, but consolidate (lowest cost, recommended now)
Keep Bash as the orchestration shell; stop the bleeding on the Python seam:
- Replace the 135 inline heredocs with **one Python helper module/script**
  (`docket-json <verb> ...`) that the shell calls — fewer forks, one place to
  test, typed internally. Or adopt `jq` for read-only paths.
- Net: removes the worst maintainability tax without a rewrite. **Do this
  regardless of any longer-term decision.**

### Option B — Migrate the core to Python (best strategic fit)
Python is already a mandatory dependency and already does all the heavy lifting.
A Typer/Click CLI would make the data model, schema validation, budgets,
trace/audit, Telegram and the HTTP server **first-class and testable**, while a
thin Bash bootstrap stays for install. Lowest-friction "real language" path; no
new runtime added. This is the natural destination if the project keeps growing.

### Option C — Go or Rust (only if single-binary distribution becomes a product requirement)
A static binary removes the Bash *and* Python runtime deps and ships one
artifact — compelling for distribution and the `serve` daemon. But it's a full
rewrite of 14.7K lines, loses the "readable, hackable, no build step" property
that suits a sysadmin tool, and is **not justified by code quality alone**.
Choose this only when "no runtime deps / one binary / a real long-running daemon"
becomes a hard requirement.

### Not recommended
Node/TypeScript (adds a heavier runtime than Python for no domain advantage);
staying on 135 inline heredocs (status quo is the one clearly wrong option).

## 6. Recommendation

1. **Now (cheap, high value):** Option A — collapse inline Python into a single
   tested helper. This alone resolves most of the architectural smell.
2. **Set a trigger, not a date, for Option B:** migrate the core to Python when
   *any* of these fire — LOC crosses ~20K, the `serve`/daemon path needs to be
   long-running, or contributor onboarding stalls on the Bash+Python seam.
3. **Reserve Option C** for an explicit distribution requirement (single binary,
   zero runtime deps). Don't rewrite for purity.
4. **Keep** the install/bootstrap and pure shell-outs in Bash permanently.

## 7. Smaller findings (independent of language)

- Dual-source JSON is the highest-risk design element; the `flock`+atomic-write
  work mitigates but doesn't eliminate drift risk. The existing `drift.sh` is the
  right instinct — keep investing there.
- `serve.sh` building HTTP/Prometheus output in Bash is the weakest module by
  fitness; first candidate to move to Python under Option B.
- Test depth is good for helpers (301 assertions) but integration tests need the
  live daemon and don't run in CI — acceptable, but the dual-source sync paths
  deserve more hermetic coverage.
- CI is a genuine strength; the metrics-sync gate is a best-practice most teams
  lack.

## 8. Build vs. wrap: why OpenClaw and not a standalone app

This is the most consequential architectural decision in the project, so it
deserves an explicit defense rather than an assumption.

### What each side actually owns
- **OpenClaw (the runtime / execution plane):** the autonomous agent loop, LLM
  provider calls + model routing, tool execution and its sandbox, the gateway
  service, session/channel plumbing, tool-approval gates. This is large,
  security-critical, and changes *weekly* (new models, providers, tool-calling
  formats, prompt caching).
- **docket (the management / control plane):** provisioning, multi-project
  isolation, cost guardrails, opinionated UX, Telegram-first ops, fleet health.
  This is the product's actual differentiator (per its own positioning:
  provisioning + isolation first, cost as a guardrail).

### Verdict: wrap, decisively — but wrap *cleanly*
Rebuilding the runtime would be a multi-engineer-year effort to re-create
**undifferentiated, dangerous, fast-moving** machinery — and it is *not* where
docket's value lives. Five reasons wrapping is correct here:

1. **The moat is the control plane, not the engine.** Users pick docket for
   provisioning/isolation/cost UX. None of that requires owning the agent loop.
   Owning it would dilute the one thing that differentiates the product.
2. **Velocity / treadmill risk.** LLM runtimes churn constantly. Wrapping inherits
   upstream model/provider support for free; rebuilding signs you up to chase it
   forever with a small team.
3. **Security surface.** The tool sandbox, execution isolation, and approval
   gates are the most expensive things to get right and the most damaging to get
   wrong. Reusing a runtime that already has them beats re-implementing them.
4. **Time-to-value.** Wrapping ships a useful tool now; a standalone runtime
   delays everything behind a year of plumbing before the first differentiated
   feature.
5. **Right level of abstraction.** "No direct OpenClaw CLI or JSON editing" is a
   real, sellable value proposition. That is precisely what a good wrapper is.

### The honest counter-arguments (and why they don't flip the verdict)
- **Single-vendor coupling.** docket lives or dies by OpenClaw's cadence and
  compatibility. *Mitigation:* the ACL (§1, and the Python plan) — keep OpenClaw
  behind one adapter so it is *replaceable*, not load-bearing in 29 files.
- **The wrap is leaky today** (29 files know `openclaw.json`). That is an argument
  to **fix the boundary**, not to rebuild the runtime. The ACL is that fix.
- **Differentiation ceiling.** You can only expose what OpenClaw permits. *True,
  but* the unmet needs so far are control-plane features (isolation, cost,
  policy) that sit *above* the runtime — not runtime features. Re-evaluate only
  if the roadmap starts demanding execution-level changes upstream won't take.
- **Install friction** (openclaw + python + systemctl). Real, but a packaging
  problem, not an architecture one.

### When standalone *would* become the right call (decision triggers)
Wrapping is right **until** one of these fires — at which point revisit, and even
then prefer absorbing a *thin slice* behind the existing ACL port, not a full
rebuild:
- OpenClaw stalls, breaks compatibility repeatedly, or changes license/direction.
- The roadmap needs runtime-level capabilities upstream consistently refuses.
- The ACL ends up working around OpenClaw more than working with it.

### Architectural consequence
Treat OpenClaw as a **pluggable runtime port** *conceptually* — define the ACL
interface in docket's own domain terms — but **do not build a plugin framework
now** (there is exactly one runtime; that would be overengineering, see the Python
plan's "we will NOT" list). The single clean adapter both justifies wrapping today
and buys the option to swap or partially in-source later. Build-vs-wrap is not a
one-time bet; the ACL keeps it a reversible one.

### Bottom line
The engineering quality here is high — this is a top-decile Bash codebase. The
issue isn't *how* it's written, it's that the **problem has outgrown the
language's strengths**, and the 135 Python shell-outs prove it. Consolidate the
Python seam now; plan a Python core migration on a trigger; reserve Go/Rust for a
distribution mandate.
