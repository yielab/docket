# docket — Roadmap & Implementation Plan

This is the **single source of truth** for docket's roadmap *and* its executable task plan.
(Consolidated 2026-06-22 from the former root `ROADMAP.md` + `internal-docs/IMPLEMENTATION-PLAN.md`,
which duplicated each other at two altitudes — high-level phases vs. detailed tasks. Now one file.)

It takes docket from a polished single-user CLI to a hardened, portable, operable tool — sequenced
so each phase is independently shippable and raises the bar on **security → reliability →
portability → operability → product**. Earlier phases unblock later ones.

Status legend: ✅ / ☑ done · 🟡 planned-next · 🟠 audit-driven, planned · 🚧 in progress · 🗓️ planned / deferred

**Status:** Phases 0–11 complete ☑ (including the **Bash→Python core migration**, M0–M6, the **agent-pod architecture**, AA-0…AA-9, and **competitive differentiation**, CD-0…CD-9 — see §0 and the Phase 10/11 records). **Phase 12 — Consolidation & hardening is the active phase** 🟠 (audit-driven; source of record `internal-docs/architecture-audit.md`); its executable task board is [TODO.md](TODO.md). Other remaining: the gates default-on flip (unblocked by CD-4, decide after Phase 12), Phase 2 packaging stretch goals, deferred `docket models optimize` + dynamic-routing spike (see Phase 6b notes); plus the §7 Backlog.
**Last Updated:** 2026-07-02

> **Consolidation note (2026-06-23):** this file is now the **single roadmap**. The former
> `ARCHITECTURE-AUDIT.md`, `MIGRATION-PLAN-PYTHON.md`, and `MIGRATION-TASKS.md` were folded in
> here and removed — their durable content lives in §0 (completed migration) and §4.5
> (architectural principles); their executable task boards are spent (the migration shipped).
> Git history retains the originals.

## Tracked decisions (not yet scheduled)

- 🗓️ **Project rename (deferred).** "docket" collides with Ruby Docket, is a generic word, and is
  hard to search. The decision is to **keep "docket" for now but anchor it to "OpenClaw" on every
  public surface** (README first line, repo description, social preview), so a later rename to a
  searchable, namespace-clean name (candidates: `clawfleet`, `docketctl`, `openclaw-docket`) stays
  low-cost. Revisit before any wide public launch. Touch points a rename must update: binary
  name, `install.sh`/`uninstall.sh` paths, Homebrew `Formula/`, docs, and the metrics script.
- 🗓️ **OpenClaw version-pinned CI.** Install the latest OpenClaw weekly, run the integration
  suite, and open an auto-issue on schema break. Until then [COMPATIBILITY.md](COMPATIBILITY.md)
  reflects manual verification.

> This document is self-contained. A developer or AI agent should be able to start from
> here **without reading anything else first** and not lose scope. Read §1–§4 once, then
> work the tasks in §5 top to bottom. Every task has: goal, exact files, technical
> requirements, acceptance criteria, and tests. Do not skip the acceptance criteria.

---

## 0. Completed initiatives (historical record)

> Folded in from the now-removed `ARCHITECTURE-AUDIT.md` + `MIGRATION-PLAN-PYTHON.md` +
> `MIGRATION-TASKS.md`. Kept short — the durable *principles* are in §4.5; this is just the record.

### Bash → Python core migration (M0–M6) — ✅ complete

- **Why it happened:** an architecture audit found docket had outgrown Bash — ~14.7K lines of shell
  with **135 embedded `python3` heredocs** forming a "Bash + inline Python" seam with a stringly-typed
  boundary; `serve`/metrics, dual-source sync, schema validation and budgets were app logic Bash was
  fighting. Verdict: the lowest-risk real-language target was **Python** (already a hard dependency),
  not Go/Rust. The migration was executed as a strangler-fig with a golden-parity net.
- **What shipped:** the three-layer `cli/ → core/ → edges/` package (§2), the single **Anti-Corruption
  Layer** for all OpenClaw formats, Pydantic models replacing the hand-rolled schema, `store.py`
  (atomic + filelocked), `serve.py` on stdlib `http.server`, and `ruff`/`mypy`/`pytest`/golden gates.
  M6 deleted the entire Bash `lib/` tree and collapsed `bin/docket` to a launcher.
- **Result:** 416 pytest tests + 17 golden parity cases; OpenClaw knowledge confined to one module.
- **Reserved (not done, by design):** a Go/Rust single-binary rewrite — revisit **only** if zero-runtime-deps
  single-artifact distribution becomes a hard product requirement (see §4.5). Python is the destination
  until then.

---

## 1. Mission (do not lose this)

Make docket-cli **trustworthy and honest** before adding any new capability. docket is a thin
opinionated wrapper around the OpenClaw gateway; its job is to manage multi-project agent
workspaces with correct state, real cost control, and zero features that lie about what they do.

**The final approach in one sentence:**
> Fix correctness → enforce cost → finish the half-done refactor and resolve/remove the placebo
> "smart routing" → park experiments. Lean on OpenClaw's native features; delete docket code that
> duplicates them.

**Out of scope (do NOT do these now):** new channels, new agent types, rewriting in another
language, replacing OpenClaw, adding features not listed here. If tempted, stop and add it to
§7 "Backlog" instead.

---

## 2. Ground truth about the system (read once)

> **Post-M6 (Python core).** Phases 0–9 below were authored against the **Bash** codebase;
> their file paths (`lib/**/*.sh`) refer to the pre-cutover tree, now **deleted**. They are
> retained verbatim as completed-work record. **For any new work (Phase 10+), the ground truth
> is the Python package described here**, and the canonical source is [CLAUDE.md](CLAUDE.md).

- **Language/stack:** Python 3.11+ (`docket` package under `src/docket/`), Typer + Rich + Pydantic + pydantic-settings + filelock. Installed via `uv`/pip; `bin/docket` is a thin Bash launcher that execs `python -m docket "$@"`. Gated by `ruff` + `mypy --strict` + `pytest`.
- **Three layers, dependencies point inward only** — `cli/` → `core/` → `edges/`. A CLI command may call core and edges; core never imports cli; **nothing imports OpenClaw config except the ACL**.
  - `cli/` ([src/docket/cli/](src/docket/cli/)) — Typer commands; the only layer that talks to the user. `__main__.py` maps aliases/removed-commands then hands to the Typer `app` in `cli/__init__.py`. Larger groups split out (`_install.py`, `_doctor.py`, `_gates.py`, `_trace.py`, …).
  - `core/` ([src/docket/core/](src/docket/core/)) — Pydantic models + pure services: `models.py` (`AgentMeta`, `AgentKind`, `ModelSource`), `oc_models.py`, `policy.py`/`provider.py`/`models_policy.py` (role→model), `sync.py`, `security.py`, `approval.py`, `audit.py`, `trace.py`, `utils.py`.
  - `edges/` ([src/docket/edges/](src/docket/edges/)) — the only side-effecting layer: `store.py` (atomic, filelocked, 0600 JSON I/O — the single chokepoint for docket-owned JSON), `adapters/openclaw.py` (**the ACL**), `adapters/system.py` (typed systemctl/docker/git wrappers, degrade gracefully).
- **Two config sources that must stay in sync** (via the ACL + `core/sync.py`):
  - `~/.openclaw/openclaw.json` — the OpenClaw daemon's truth. **`agents` has subkeys `defaults` and `list`** (an array of `{id, model, workspace, …}`). Reached **only** through `edges/adapters/openclaw.py`.
  - `~/.openclaw/workspaces/projects/<id>/.docket-meta.json` — docket's per-agent truth (`kind`, `type`/`role`, `name`, `codebase`, `stack`, `model`, `modelSource`, `sessionKey`, `projectKey`, …). Read/written **only** through `edges/store.py`. Specialists have one too (`kind: specialist`, under `~/.openclaw/workspaces/<role>/`).
- **The ACL invariant (hard boundary):** `edges/adapters/openclaw.py` is the **only** module that knows OpenClaw's file formats (`openclaw.json`, auth-profiles, provider config). No other module may import or reference those formats. Extend the ACL; never reach around it.
- **Tests** (`tests/`):
  - `tests/python/` — pytest suite (416 tests). `uv run pytest`.
  - `tests/golden/` — byte-parity golden suite (`bash tests/golden/run.sh verify-all`, 17 cases) — the net that catches a behaviour change.
  - `tests/evals/` — specialist-role eval stubs (non-blocking). CI gates on `ruff check` + `ruff format --check` + `mypy src` + `pytest` + goldens.

---

## 3. Conventions (follow exactly)

> Python-core conventions (Phase 10+). The Bash-era rules below this list are preserved inside the
> historical phases; do not apply them to new Python work.

- **Typed, gated:** `ruff check .`, `ruff format --check .`, `mypy src` must all pass. No new `# type: ignore` without a reason.
- **Never write JSON by hand** — docket-owned JSON goes through [edges/store.py](src/docket/edges/store.py) (atomic, filelocked, 0600). `openclaw.json` / auth-profiles / provider config go **only** through the ACL ([edges/adapters/openclaw.py](src/docket/edges/adapters/openclaw.py)).
- **Respect the layer rule:** `cli/` → `core/` → `edges/`, inward only. `core/` has no Typer, no subprocess, no file-format knowledge.
- After any change to `openclaw.json`, restart the gateway **once** via `system.restart_gateway()` ([edges/adapters/system.py](src/docket/edges/adapters/system.py)); it degrades gracefully on non-systemd hosts.
- User-facing status goes through the Rich helpers in [ui.py](src/docket/ui.py) (`info/success/warn/error`); a command aborts by raising `typer.Exit`. Never raw `print` for status.
- Permissions: workspace dirs `700`, files `600`.
- Commit style: `Type: description` (`Add:`/`Fix:`/`Docs:`/`Refactor:`/`Test:`), detailed body. One task ≈ one commit. **Public repo** — scrub real client names, `/home/<user>` paths, and usernames before committing.
- **Every code task adds or updates a test** (pytest; add a golden case when output changes).

---

## 4. Definition of Done (per task)

A task is done when: (a) acceptance criteria all pass, (b) a test covers the change, (c)
`./tests/run-all-tests.sh` is green, (d) `DEBUG=1 docket doctor` runs without regression, (e)
committed with a conventional message. Tick the box in §5 and move on.

---

## 4.5 Architectural principles (durable — read before any structural change)

> Folded from the removed audit/migration docs. These outlive any single phase; a PR that violates
> one needs an explicit decision entry in §6, not a silent exception.

### Build vs. wrap: docket wraps OpenClaw, decisively — but wraps *cleanly*

- **The moat is the control plane, not the engine.** OpenClaw owns the *execution plane* (the agent
  loop, LLM/provider calls + model routing, tool execution + sandbox, the gateway, session/channel
  plumbing, approval-hook enforcement) — large, security-critical, changing *weekly*. docket owns the
  *control plane* (provisioning, multi-project isolation, cost guardrails, opinionated UX,
  Telegram-first ops, fleet health). That control plane is the product's differentiator; none of it
  requires owning the agent loop.
- **Why not rebuild the runtime:** velocity/treadmill risk (LLM runtimes churn; wrapping inherits
  provider support for free), security surface (sandbox + isolation + gates are the most expensive
  things to get right), and time-to-value. "No direct OpenClaw CLI or JSON editing" is itself the
  sellable proposition.
- **The boundary makes it reversible:** the ACL ([edges/adapters/openclaw.py](src/docket/edges/adapters/openclaw.py))
  is the single place OpenClaw's shape lives, so build-vs-wrap stays a *reversible* bet, not a
  load-bearing assumption smeared across the codebase. **Do not build a plugin/`AbstractBackend`
  framework** — there is exactly one runtime; one concrete ACL behind a thin boundary is enough.
- **When standalone *would* become right (triggers, not dates):** OpenClaw stalls / repeatedly breaks
  compatibility / changes license or direction; the roadmap needs runtime-level capabilities upstream
  consistently refuses; or the ACL ends up working *around* OpenClaw more than *with* it. Even then,
  prefer absorbing a thin slice behind the existing ACL port over a full rebuild.
- **Critical consequence for every phase:** docket is **not in the agent execution path**. The daemon
  executes every tool call. So any feature with a runtime aspect splits into *pure-docket* (config,
  provisioning, metadata, templates, policy authoring — ships first, fully testable) vs
  *daemon-gated* (anything that intercepts or spawns at runtime — isolated behind a spike, never
  overclaimed). Phases 8 and 10 are both shaped by this split.

### Anti-overengineering guardrails (the "we will NOT" list)

| We will NOT | Because |
|---|---|
| Add a DI/IoC framework | Plain constructor/function args suffice at this size |
| Build a plugin system / `AbstractBackend` | One backend (OpenClaw); one concrete ACL behind a thin boundary — no speculative generality |
| Use FastAPI/async for `serve` | 3 endpoints; stdlib `http.server` + `prometheus_client`, synchronous |
| Add an ORM / database | JSON files modeled by Pydantic *are* the store (the filesystem is the trace/policy store too) |
| Event sourcing / message bus / CQRS | It's a CLI that edits two JSON files |
| Deep package nesting / DDD ceremony | Keep it flat: `cli/ core/ edges/`. Split a module only when it actually hurts |
| Abstract before the second caller exists | Rule of three. Make it work, then generalize |

The target is **boring, typed, obvious Python.** "Scale" here is not throughput (single-host CLI) —
it's more *commands*, more *agents*, more *contributors*; the three-layer split + types + tests
address exactly those.

---

## 5. The TODO

### PHASE 0 — Truth & correctness  *(blocking; nothing else ships first)*

#### ☑ P0-1 — Fix the `agents.list` vs `agents.registered` key bug

- **Why:** Live config uses `agents.list`. Code that reads `agents.registered` silently sees zero agents.
- **Files & lines:**
  - `lib/commands/install.sh:41` — `agents.registered` → `agents.list` (pre-migration Bash; now `src/docket/cli/_install.py`)
  - `lib/commands/smart.sh:139` — `config.get('agents', {}).get('registered', [])` → `...get('list', [])` (pre-migration Bash; smart routing later removed)
  - `lib/commands/doctor.sh:177` — `for agent in config.get('agents', {}).get('registered', [])` → `...get('list', [])` (pre-migration Bash; now `src/docket/cli/_doctor.py`)
  - Grep the whole repo: `grep -rn "registered" lib/` and fix every agent-list usage. (Leave unrelated uses of the word alone.)
- **Requirements:** Standardize on `agents.list`. Each agent object is `{"id": str, "model": str, ...}`.
- **Acceptance:**
  - `grep -rn "agents'\?\s*\]*.*registered\|get('registered'" lib/` returns nothing agent-list-related.
  - `docket smart status` shows the real agent count (not 0) when agents exist.
  - `docket install` Step "already configured" path prints a correct agent count, not `unknown`.
- **Test:** Add `tests/unit/test-config-keys.sh` (or extend test-helpers.sh) that builds a tmp config with `agents.list=[{id:a},{id:b}]` and asserts a small helper `count_agents()` returns `2`. Wire it into `run-all-tests.sh`.

#### ☑ P0-2 — Add config **drift detection** to `docket doctor`

- **Why:** `.docket-meta.json` and `openclaw.json` can disagree silently (e.g. model changed in one only).
- **File:** `lib/commands/doctor.sh` — add a new check section (after the per-project block, ~line 112). (pre-migration Bash; now `src/docket/cli/_doctor.py`)
- **Requirements:** For each project id, compare:
  - `meta_get id model` vs the agent's `model` in `openclaw.json` `agents.list`.
  - `meta_get id sessionKey` presence vs gateway metadata (best-effort; warn if absent).
  - TG binding in meta (if tracked) vs `get_tg_binding id`.
  - On mismatch: `fail "  <id>: drift — model meta=<x> openclaw=<y>"` and increment `issues`. Print hint: `Fix with: docket doctor --fix`.
- **Acceptance:** Manually set a different model in one source → `docket doctor` reports the drift and exits non-zero. Aligned config → no drift reported.
- **Test:** Integration case (pre-migration `tests/test-lifecycle.sh`; now pytest under `tests/python/`): create agent, mutate `.docket-meta.json` model, assert `docket doctor` output contains `drift` and exit code `1`.

#### ☑ P0-3 — Single audited config write path

- **Why:** Config writes are scattered inline python heredocs with no verification; root cause of drift and the P0-1 bug.
- **File:** new helper functions in `lib/helpers/json.sh` (pre-migration Bash; docket-owned JSON I/O now in `src/docket/edges/store.py`).
- **Requirements:** Implement and document:
  - `oc_get <jsonpath> [default]` — read a dotted path from `openclaw.json`.
  - `oc_set <jsonpath> <json-value>` — write a dotted path; **always** `json.dump(indent=2)`; validate the file parses *after* writing (re-open + `json.load`); on parse failure, restore from a `.bak` and `error`.
  - `set_agent_model <id> <model>` — convenience that updates BOTH `openclaw.json` `agents.list[].model` AND `.docket-meta.json` via `meta_set`, then returns 0 only if both succeeded.
  - Backup rule: before mutating `openclaw.json`, copy to `${CONFIG_FILE}.bak` (single rolling backup).
- **Acceptance:** Refactor `profile.sh`/`model.sh` to call `set_agent_model`; both sources end up equal. Corrupt-write simulation restores from `.bak`.
- **Test:** Unit test `oc_set`/`oc_get` round-trip on a tmp file; assert indent=2 preserved and invalid value rejected.

#### ☑ P0-4 — Batch gateway restarts (de-couple `restart_gateway`)

- **Why:** Multi-step ops restart the systemd unit repeatedly.
- **Files:** `lib/helpers/service.sh` and callers (pre-migration Bash; service/gateway control now in `src/docket/edges/adapters/system.py`).
- **Requirements:** Introduce a "dirty" flag pattern: helpers that mutate config set `DOCKET_GATEWAY_DIRTY=1` instead of restarting inline; `restart_gateway` is called **once** at the end of a command if dirty. Provide `mark_gateway_dirty` and `restart_gateway_if_dirty`. Update commands that currently call `restart_gateway` mid-flow.
- **Acceptance:** A command that changes 3 config values restarts the gateway exactly once (verify via a log/echo in a dry-run env var `DOCKET_NO_RESTART=1` that prints instead of restarting).
- **Test:** Unit test asserts `restart_gateway_if_dirty` is a no-op when not dirty and prints exactly one restart line when dirty (use `DOCKET_NO_RESTART=1`).

#### ☑ P0-5 — CI pipeline

- **Why:** Nothing currently guards regressions.
- **File:** new `.github/workflows/ci.yml`.
- **Requirements:** On push + PR: checkout, install `python3` + `bash` (ubuntu-latest has them), run `./scripts/validate-specs.sh` (non-blocking warn ok), then `./tests/run-all-tests.sh` (blocking). Cache nothing fancy. Add a status badge to README.
- **Acceptance:** CI runs and is green on a clean branch; a deliberately failing test makes CI red.
- **Test:** N/A (this *is* the test harness) — verify by pushing a branch.

#### ☑ P0-6 — Honest spec/coverage status

- **Why:** [specs/README.md](specs/README.md) claims coverage numbers (e.g. "100%") that aren't measured.
- **Files:** `specs/README.md`, run `./scripts/spec-coverage.sh`.
- **Requirements:** Run the coverage script; update the status table to reflect reality, or mark numbers as "unverified" until a real measurement exists. No fabricated 100%s.
- **Acceptance:** Status table matches `spec-coverage.sh` output (or says "manual estimate").

**Phase 0 exit criteria:** `docket doctor` detects drift and never miscounts agents; all config writes go through `oc_set`/`set_agent_model`; gateway restarts at most once per command; CI green on main; no fabricated coverage claims.

---

### PHASE 1 — Cost enforcement  *(the real differentiator)*

> Context: there have already been billing incidents (a recorded billing error and a runaway-session analysis). Today docket only *reports* cost (`_aggregate_cost`). We need *enforcement*.

#### ☑ P1-1 — Per-agent budget field

- **Files:** `lib/commands/profile.sh`, `.docket-meta.json` schema, `json.sh` (pre-migration Bash; now `src/docket/cli/` + `core/`/`edges/`).
- **Requirements:** Add `docket profile <id> --budget <USD>` storing `budgetUsd` in `.docket-meta.json` (via `meta_set`). `0`/unset = no cap. Show budget in `docket info` and `docket cost`.
- **Acceptance:** `docket profile x --budget 5` then `docket info x` shows `Budget: $5.00`.
- **Test:** Unit: set budget, `meta_get x budgetUsd` returns `5`.

#### ☑ P1-2 — Budget check + auto-pause

- **Files:** new helper `lib/helpers/budget.sh`; hook into `cost.sh` (pre-migration Bash; budget logic now in `src/docket/core/`, cost in `src/docket/cli/`).
- **Requirements:** `check_budget <id>` compares `_aggregate_cost` total vs `budgetUsd`. At ≥100%: pause the agent (preferred: an OpenClaw gateway mechanism — research `openclaw agents` subcommands for disable/pause; fallback: set the agent's model to a sentinel/disabled state and `warn` loudly) and record a flag in meta (`pausedReason=budget`). At ≥80%: `warn`. Must be idempotent.
- **Acceptance:** Simulated usage over cap flips the agent to paused exactly once and reports it; under cap does nothing.
- **Test:** Integration with a fake sessions dir producing a known cost; assert pause triggers at the threshold.

#### ☑ P1-3 — Runaway-session detection

- **Files:** `lib/commands/cost.sh` (or `maintain`), reuse session JSONL parsing from `_aggregate_cost` (pre-migration Bash; now `src/docket/cli/`).
- **Requirements:** Detect burn anomalies: e.g. turns growing past a threshold (the docs mention a 258-turn / ~$28 bloat) or cost-per-hour spike. Surface in `docket doctor` and `docket cost`. Document thresholds as constants in `config.sh`.
- **Acceptance:** A session JSONL with >N turns triggers a warning naming the agent and turn count.
- **Test:** Unit on the parser with a crafted JSONL.

**Phase 1 exit:** an agent hitting its cap is auto-paused and reported; runaway detection fires before the $ threshold; both visible in `doctor` and `cost`.

---

### PHASE 2 — Finish consolidation & resolve "smart routing"

> Context: `router.sh` (pre-migration Bash dispatch; now the alias/removed-command map in `src/docket/__main__.py`) deprecates 10 commands in favor of `maintain, mode, context, cost, profile, doctor`, but ships both. "Smart routing" (`smart.sh`) injects prose into SOUL.md and does not actually change the model — it's placebo.

#### ☑ P2-1 — Complete the new verbs

- **Files:** `maintain.sh`, `mode.sh`, `context.sh`.
- **Requirements:** Ensure every capability of the deprecated commands (`reset, repair, cleanup, model, billing, monitor, memory, browser`) is fully covered by its replacement verb. Make a mapping table (old → new) and verify each path.
- **Acceptance:** Each deprecated command's behavior is reachable through the new verb with parity.

#### ☑ P2-2 — Delete deprecated aliases + dead code

- **Files:** `router.sh` (remove deprecated `case` arms after a deprecation window), delete now-unused command files.
- **Requirements:** Remove only after P2-1 parity is proven and tests updated. Update `help.sh`, README, `bin/docket` header comments.
- **Acceptance:** `docket <oldcmd>` prints a clean "renamed to \<new\>" (or is gone, per decision); no orphaned `cmd_*` files sourced.
- **Test:** Update integration tests to the new verbs; remove tests for deleted paths.

#### ☑ P2-3 — Resolve smart routing (decision required — see §6)

- **Option A (implement real routing):** Move model selection to the gateway/runtime. Requirements: research whether OpenClaw supports per-task model selection / fallback chains in `openclaw.json` (keys like `models`, `agents.defaults.model`); if yes, configure it there instead of SOUL.md prose. Build a **minimal eval harness**: `tests/evals/` with golden tasks per agent role and a script that runs cheap vs premium and scores output; routing ships only if no regression.
- **Option B (cut):** Remove `cmd_smart`, the SOUL.md injection, and all "smart routing" claims from README/help/templates. Keep only the *context/compaction* config IF it maps to real OpenClaw keys (verify against OpenClaw docs); otherwise remove that too.
- **Acceptance:** Either routing demonstrably changes the model used (proven in logs) with eval pass, OR every "smart routing" claim is gone and `docket smart` no longer exists.

#### ☑ P2-4 — Stop reinventing OpenClaw context features

- **Files:** `smart.sh`/`mode.sh` context bits.
- **Requirements:** docket must not write `contextPruning`/`compaction` shapes that disagree with OpenClaw's real schema. Verify the real keys against [docs.openclaw.ai](https://docs.openclaw.ai/); make docket a **thin pass-through** to OpenClaw's native settings or remove the feature.
- **Acceptance:** Any context/compaction value docket writes is read back correctly by `openclaw` and by docket's own status command (read/write schemas match).

**Phase 2 exit:** one command surface; "smart routing" is either real-with-evals or fully removed; no schema drift against OpenClaw.

---

### PHASE 3 — Park experiments & finish the edges

#### ☑ P3-1 — Move `terminal` (584 LOC) and `browser` (260 LOC) to `experimental/`

- **Requirements:** Create `lib/commands/experimental/`; move files; gate behind `DOCKET_EXPERIMENTAL=1` or a clear "experimental" warning. Fold browser *health* into `doctor` (it already partly is, doctor.sh:114-133). (pre-migration Bash paths; commands now live under `src/docket/cli/`)
- **Acceptance:** Core help no longer lists experimental commands as first-class; they still work when explicitly enabled.

#### ☑ P3-2 — Telegram: finish or document-as-manual

- **Requirements:** Either complete group auto-creation or update docs to "manual wire only" and make `wire` the single supported path. No 🚧 left in README.
- **Acceptance:** README status table has zero 🚧.

**Phase 3 exit:** zero half-features in the main path; README honest.

---

### PHASE 4 — Strengthen & extend  *(current)*

#### ☑ P4-0 — Remove dead adapter

- **What:** Moved `lib/adapters/claude-terminal.sh` → `lib/commands/experimental/claude-terminal-adapter.sh`. Removed empty `lib/adapters/` directory. The adapter was never sourced or used.

#### ☑ P4-1 — Fix integration tests for renamed commands

- **What:** `tests/test-lifecycle.sh` TEST 4 (`docket repair`) → `docket maintain check`; TEST 5 (`docket reset`) → `docket maintain clean`. Both were calling deprecated router arms that exit 1.

#### ☑ P4-2 — Basic team delegation (manager task queue)

- **Files:** `lib/commands/team.sh` — added `_team_delegate`, `_team_queue`, `_team_done`, `_task_list_path`, `_ensure_task_list`. (pre-migration Bash; team commands now in `src/docket/cli/`)
- **Interface:** `docket team delegate "<task>"`, `docket team delegate --priority high "<task>"`, `docket team queue`, `docket team done <task-id>`.
- **Storage:** Writes to `~/.openclaw/workspaces/manager/TASK_LIST.json` (per-object array, `{id, description, priority, created, status}`).
- **Acceptance:** delegate → queue shows the task, sorted by priority; `done` marks it complete; idempotent on empty queue.
- **Tests:** 5 unit tests in P4-2 section of `test-helpers.sh` (all passing).

#### ☑ P4-3 — Eval harness skeleton

- **Why:** Prerequisite for any real model routing work; creates the test surface before a single eval exists.
- **Files:** new `tests/evals/` directory; `tests/evals/run-evals.sh` (discovers and runs `*.eval.sh`); one golden eval per specialist role as `*.eval.sh` stubs.
- **Requirements:** `run-evals.sh` exits 0 if all passing, 1 if any fail. Each eval stub contains: inputs, expected output shape, scoring function (grep/python). Stubs may all SKIP initially — the harness must exist and run cleanly.
- **Acceptance:** `./tests/evals/run-evals.sh` runs without error; CI step added to `run-all-tests.sh` (non-blocking warn on failure).

**Phase 4 exit:** delegation round-trip is working; integration tests call only current commands; eval harness exists (even if all stubs skip).

---

## 6. Open decisions (resolve before the dependent task)

| ID | Decision | Needed before | Default if unanswered |
| -- | -------- | ------------- | --------------------- |
| D-1 | Smart routing: implement real (A) or cut (B)? | P2-3 | **B (cut)** — it's placebo today; cutting is safe and honest |
| D-2 | Deprecated commands: hard-remove or keep warning shims one release? | P2-2 | Keep shims one release, then remove |
| D-3 | Budget pause mechanism: native OpenClaw pause vs model-sentinel fallback? | P1-2 | Research native first; fallback to sentinel |
| D-4 | If the daemon can't reach local endpoints (Ollama), what is the "free" preset? | MA-4 | OpenRouter free-tier models, labeled honestly (MA-1 decides) |
| D-5 | Concrete model IDs per preset (openai/google/openrouter/local tiers)? | MA-4 | Pick current cheapest/standard/best per provider from MA-1's verified table; pin in `config.sh` |
| D-6 | Do aborted sessions count against role success rate? (spec Q1) | OBS-11 | **Count them** — O5 already coerces a timed-out trace to `aborted`; excluding them hides the silent-hang failure G4 exists to catch. terminal = success+failure+aborted. |
| D-7 | Where is the trusted/untrusted input boundary marked? (spec Q2) | OBS-7 | A `source` field on queued tasks (`operator` trusted; `telegram\|api\|fetched` untrusted → pre_input/injection policies apply, GR9). |
| D-8 | Does the manager-coordination layer get its own metrics role? (spec Q3) | OBS-4 | **No (v1)** — observe it through the agents it dispatches; manager emits session_start/end for its own planning runs, dispatched work is attributed to the executing agent. Add a `manager` rollup only if delegation overhead becomes a question. |
| D-9 | Per agent field: `synced` to openclaw.json or `local`-only? | CDD-1/CDD-3 | Record per field in the schema table. Proposed: `model`/`sessionKey`/`projectKey` = synced (daemon needs them); `budgetUsd`/`paused`/`pausedReason`/`modelSource`/`templateVersion` = local (docket-only policy/state) — but document them as local so no one expects sync. Revisit if the daemon ever reads a budget/pause. |
| D-10 | `--json` envelope: adopt the spec's `{data,…}` wrapper (A) or delete it and document actual shapes (B)? | CDD-4 | **B (delete + document reality)** — no command emits the wrapper today and external scripts already parse the bare shapes; retrofitting a wrapper is a breaking change for zero benefit. Pin the real shapes in `specs/data/` instead. |
| D-11 | `docket team` (legacy manager queue): retire into pods, or give it real dispatch? | CH-4 | **Retire** — it is a second, manual task queue (`workspaces/manager/TASK_LIST.json`) with **no dispatcher**; pods own delegation (`docket pod <p> delegate/queue/dispatch`, real execution via `core/dispatch.py`) and the opt-in Portfolio Manager owns the cross-pod view. Replace with a removed-command notice mapping each subcommand to its pod equivalent. |
| D-12 | Docket-owned JSON writes: single `store.py` chokepoint, or per-module writers? | CH-1 | **Single chokepoint** — every docket-owned JSON write goes through `edges/store.py` (append-only JSONL logs in `trace.py`/`audit.py` are the one documented exemption, named in the store.py docstring). Removes 8+ hand-rolled atomic-write copies with inconsistent locking. |

---

### PHASE 5 — Channel portability + system snapshot  *(current)*

#### ☑ P5-1 — Channel-aware wire/unwire

- **Why:** `upsert_binding` hardcodes `"channel": "telegram"` and `get_tg_binding` only reads Telegram bindings. OpenClaw supports 50+ channels; docket should not be Telegram-only at the binding layer.
- **Files:** `lib/helpers/json.sh` (generalize `upsert_binding`, add `get_channel_binding`, keep `get_tg_binding` as alias); `lib/helpers/workspace.sh` (`_wire_group` gains `channel` arg); `lib/commands/wire.sh` (detect channels via `openclaw channels list`, offer picker when >1); `lib/commands/unwire.sh` (`--channel` flag). (pre-migration Bash; bindings now go through the ACL `src/docket/edges/adapters/openclaw.py`, commands in `src/docket/cli/`)
- **Requirements:** For Telegram: existing group discovery flow unchanged. For non-Telegram: prompt for peer ID manually (no log-based discovery). `get_tg_binding` remains as a thin wrapper over `get_channel_binding` for backwards compat.
- **Acceptance:** `docket wire myproject` with only Telegram configured behaves identically to today. Adding a second channel (e.g. Discord) would offer a channel picker before the group selection.
- **Tests:** 3 unit tests — `upsert_binding` with explicit channel arg; `get_channel_binding` retrieves correct peer; `get_tg_binding` still works as alias.

#### ☑ P5-2 — `docket snapshot` command

- **Why:** No machine-readable export of system state exists. Teams need to pipe agent status into dashboards, CI artifacts, or monitoring scripts without installing docket.
- **Files:** new `lib/commands/snapshot.sh` (`cmd_snapshot()`); wire into `lib/core/router.sh` and `lib/commands/help.sh`. (pre-migration Bash; now `src/docket/cli/` + the `src/docket/__main__.py` command map)
- **Interface:** `docket snapshot` → JSON to stdout. `docket snapshot --output <file>` → write to file.
- **JSON shape:** `{timestamp, gateway, channels[], agents:[{id,name,type,model,bindings,lastActivity,costUsd}], totalCostUsd}`.
- **Acceptance:** `docket snapshot | python3 -m json.tool` exits 0 (valid JSON). All project + specialist agents appear in the output.
- **Tests:** 1 unit test — snapshot output is valid JSON containing at least one agent.

#### ☑ P5-3 — `docket serve` command

- **Why:** Closes the "multi-user" backlog item with a minimal server that shares live agent state without requiring docket on every machine.
- **Files:** new `lib/commands/serve.sh` (`cmd_serve()`); wire into router and help. (pre-migration Bash; now `src/docket/serve.py`)
- **Interface:** `docket serve [--port 7331] [--interval 30]`. Starts Python built-in HTTP server; refreshes snapshot JSON every `--interval` seconds; Ctrl-C stops cleanly.
- **Requirements:** Uses `python3 -m http.server` in a temp dir. Background loop rewrites `status.json` every interval. `GET /status.json` returns fresh snapshot.
- **Acceptance:** `docket serve` starts without error; `curl localhost:7331/status.json` returns valid JSON; Ctrl-C exits without leaving background processes.
- **Tests:** none (runtime HTTP behaviour, not unit-testable in Bash).

**Phase 5 exit:** bindings are channel-agnostic; system state is exportable as JSON; a team-visible HTTP endpoint exists.

---

### PHASE 6 — Model & provider agnosticism  *(🔴 CRITICAL — work this next, top to bottom)*

> **Why this is critical:** docket currently has a hard dependency on the Claude API.
> A pricing change, outage, regional block, account suspension, or ToS change at one vendor
> breaks every docket deployment. The fix is to make docket **model-agnostic**: any provider the
> OpenClaw daemon supports — **local/free** (Ollama, llama.cpp, LM Studio) or **remote/paid**
> (Anthropic, OpenAI, Google) or **mixed** (OpenRouter, which has free-tier models) — must
> work, and the model in use must be **explicit and visible** in every command output,
> instruction template, README, and help text. Anthropic stays the *default* (it works today),
> but it must become *one option among several*, clearly labeled.
>
> **Where the Claude dependency lives today (verified against source, 2026-06-11; pre-migration Bash paths — the model layer now lives in `src/docket/core/` `models_policy.py`/`policy.py`/`provider.py`, install in `src/docket/cli/_install.py`, list/keys in `src/docket/cli/`):**
>
> | Layer | File / lines | Problem |
> | ----- | ------------ | ------- |
> | Hard whitelist | `lib/helpers/models.sh:5-9` `VALID_MODELS` | `validate_model()` **errors on any non-Anthropic model** — the single hardest blocker |
> | Fallback chain | `lib/helpers/models.sh:55-69` `get_fallback_model` | hardcoded opus→sonnet→haiku IDs |
> | Alias/fix table | `lib/helpers/models.sh:12-22`, `fix_invalid_models()` py heredoc | Claude-only aliases duplicated in bash + python |
> | Default model | `lib/core/config.sh:11` `DEFAULT_MODEL="anthropic/claude-sonnet-4-6"` | fine as a default, but not overridable per install |
> | Tier mapping | `lib/core/config.sh:41-45` `MODEL_PROFILES` | economy/standard/premium → Claude only |
> | Pricing | `lib/core/config.sh:48-54` `MODEL_PRICING` | Claude-only; unknown model silently costs $0 |
> | Install | `lib/commands/install.sh:175-181` `specialist_models` | 6 specialists hardcoded to Claude IDs |
> | Display | `lib/commands/list.sh:158`, `list.sh:219-224` | strips only the `anthropic/claude-` prefix |
> | Key sync | `lib/commands/keys.sh` `PROVIDER_KEYS` (~line 391), `_agent_provider` (~309) | **already half-agnostic** (anthropic/openai/google/openrouter) — extend, don't rewrite |
> | Templates | `lib/templates/SMART-ROUTING.md`, `docket-programmer.md`, `docket-tester.md`, `status-awareness.md`, `SOUL-error-handling.md` | prompts say "haiku/sonnet/opus", link `console.anthropic.com` |
> | Docs | `README.md` (~216-218), `docs/commands.md`, `docs/troubleshooting.md`, `CLAUDE.md`, `lib/commands/help.sh` (now `src/docket/cli/_help.py`) | profile tables and examples are Claude-only; never states other providers work |
>
> **Design rules for this phase (do not violate):**
>
> 1. The **tier abstraction stays** (economy/standard/premium) — users think in tiers; the
>    tier→model mapping becomes data, not code.
> 2. docket **validates format, the daemon validates the model.** A well-formed `provider/model`
>    docket doesn't recognize gets a `warn` (no pricing data, unknown provider key), never an `error`.
> 3. **No silent cost lies.** Unknown pricing → `n/a`, local → `$0 (local)`. Never $0.00 for an
>    unpriced remote model.
> 4. **Anthropic remains the out-of-box default.** This phase adds choice + clarity; it does not
>    change behavior for an existing install that does nothing.
> 5. Every config write goes through the existing audited path (`json_atomic_write` /
>    `oc_set` / `meta_set`); registry writes are no exception.

#### ✅ MA-1 — Spike: verify the OpenClaw daemon's provider contract  *(blocking; do first)*

- **Goal:** Establish ground truth on what model strings/providers the daemon actually accepts, so MA-2…MA-8 build on facts, not guesses.
- **Files:** a scratch findings doc during the spike (not retained in-repo).
- **Requirements:**
  - Check `openclaw --help`, `openclaw models --help` (if it exists), and <https://docs.openclaw.ai/> for: supported providers; model-ID format (`provider/model`?); how a **local / OpenAI-compatible endpoint** (Ollama at `http://localhost:11434`, llama.cpp, LM Studio) is configured (base-URL override? a `models` section in `openclaw.json`? per-agent?); which env var each provider's key uses; fallback-chain support.
  - Inspect the live `~/.openclaw/openclaw.json` `models` top-level key (it exists — see §2) and document its real schema.
  - Record per provider: id prefix, key env var (or "none — local"), free/paid, config snippet docket would need to write.
  - Explicitly answer: **can the daemon talk to an Ollama-style local endpoint, and what exact config enables it?** If the daemon cannot, document the limitation and scope MA-4's `local` preset to whatever the daemon *can* do (e.g. OpenRouter free-tier models as the "free" path) — do not fake it.
- **Acceptance:** `MODEL-AGNOSTIC-NOTES.md` exists with a verified provider table + at least one working non-Anthropic model string proven against the daemon (e.g. set on a test agent, daemon accepts it / responds).
- **Test:** N/A (research). The doc is the deliverable; later tasks cite it.

#### ✅ MA-2 — Data-driven model registry (kill the whitelist)

- **Goal:** Replace hardcoded `VALID_MODELS` / `MODEL_PROFILES` / `MODEL_PRICING` / `DEFAULT_MODEL` with built-in defaults + a user-editable registry file.
- **Files:** `lib/core/config.sh`, `lib/helpers/models.sh`, new registry file `$OPENCLAW_DIR/docket-models.json` (created on first write, not by install). (pre-migration Bash; model layer now `src/docket/core/models_policy.py`/`policy.py`/`provider.py`)
- **Requirements:**
  - Registry schema (all keys optional; absent → built-in default):

    ```json
    {
      "default": "anthropic/claude-sonnet-4-6",
      "profiles": {"economy": "...", "standard": "...", "premium": "..."},
      "pricing": {"<provider>/<model>": {"input": 3.0, "output": 15.0, "cacheWrite": 0.3, "cacheRead": 3.75}},
      "localProviders": ["ollama", "local", "lmstudio"]
    }
    ```

  - Add `load_model_registry()` in `config.sh`, called once at startup after the built-in arrays are declared: if `docket-models.json` exists and parses, overlay it onto `DEFAULT_MODEL`, `MODEL_PROFILES`, `MODEL_PRICING` (one python pass emitting `key=value` lines; same pattern as existing helpers). Corrupt file → `warn` + keep built-ins (loud-on-corruption convention, Phase 1).
  - Rewrite `validate_model()`: well-formed = matches `^[a-z0-9_-]+/[A-Za-z0-9._:-]+$` (verify against MA-1 findings). Known model → pass. Well-formed unknown → `warn "model not in docket's registry — accepted, but no pricing data (cost will show n/a)"` and **return it** (exit 0). Malformed (no `provider/` prefix and not a known alias/tier) → `error` listing current tiers + example IDs from the live registry, not a hardcoded Claude list.
  - Rewrite `get_fallback_model()` to walk the **tier chain** (premium→standard→economy) using the live `MODEL_PROFILES`; a model not in any tier falls back to the economy tier's model.
  - Keep `MODEL_ALIASES` (typo healing) but make `fix_invalid_models()` read the same alias table (generate the python dict from the bash array, or move the table into the registry file) — no more duplicated tables.
- **Acceptance:**
  - `docket profile <id> openrouter/some-model` (or any well-formed non-Anthropic ID) is accepted with a warning, lands in both `.docket-meta.json` and `openclaw.json`.
  - With no `docket-models.json`, every existing command behaves byte-identically to today (defaults unchanged).
  - A `docket-models.json` overriding `profiles.economy` changes what `resolve_model economy` returns.
- **Test:** Unit (extend `tests/unit/test-helpers.sh` or new `test-models-registry.sh` wired into `run-all-tests.sh`): (1) registry overlay changes `resolve_model`; (2) corrupt registry → built-ins survive + warning on stderr; (3) `validate_model` accepts well-formed unknown, rejects malformed; (4) fallback walks tiers from live mapping.

#### ✅ MA-3 — `docket models` command (make the mapping visible and editable)

- **Goal:** One place to see and change which models docket uses — no more silent defaults buried in source.
- **Files:** new `lib/commands/models.sh` (`cmd_models()`); wire into `lib/core/router.sh` and `lib/commands/help.sh`. (pre-migration Bash; now `src/docket/cli/`, the `src/docket/__main__.py` command map, and `src/docket/cli/_help.py`)
- **Interface:**
  - `docket models` / `docket models list` — table: TIER | MODEL | PROVIDER | PRICE (in/out per MTok, or `free/local`, or `n/a`) | SOURCE (`builtin` | `user`). Plus the default model and the registry file path.
  - `docket models set <economy|standard|premium|default> <provider/model>` — validates via `validate_model`, writes `docket-models.json` via `json_atomic_write`, audit-logs (`models.set`), prints the new effective mapping. Note in output: existing agents keep their current model; affects new agents and future `docket profile <tier>` calls.
  - `docket models reset` — delete user overrides (confirm first), back to built-ins.
- **Requirements:** no gateway restart needed (mapping is docket-side; agents change only via `docket profile`). Follow output.sh helpers; never raw echo for status.
- **Acceptance:** `docket models set economy ollama/qwen2.5-coder` → `docket models list` shows it with SOURCE=user and PRICE=free/local; `docket profile <agent> economy` now assigns that model; `docket models reset` restores Claude defaults.
- **Test:** Unit: set → list contains new mapping; reset → restored; audit.log has a `models.set` line; invalid tier name errors.

#### ✅ MA-4 — Provider presets, including a free/local path

- **Goal:** One command to switch the whole tier mapping to a provider, with **free vs paid clearly labeled** at the moment of choice.
- **Files:** `lib/commands/models.sh` (extend), `lib/core/config.sh` (preset tables). (pre-migration Bash; now `src/docket/cli/` + `src/docket/core/`)
- **Requirements:**
  - `docket models preset` (no arg) lists presets with cost class, e.g.:
    - `anthropic` — paid, API key required *(default)*
    - `openai` — paid, API key required
    - `google` — paid, API key required
    - `openrouter` — paid + free-tier models, API key required
    - `local` — **free**, no API key, requires a local runtime (Ollama) — exact mechanics per MA-1 findings; if the daemon can't do local endpoints, this preset maps to the verified free alternative from MA-1 and says so honestly
  - `docket models preset <name>` writes all three tiers + default to that provider's models (concrete model IDs chosen during implementation from MA-1's verified table; pin them in `config.sh` preset arrays with pricing entries where known).
  - Print a post-switch checklist: which key (if any) to add via `docket keys add`, and for `local`: how to verify the runtime is up. If the needed provider key is missing, `warn` immediately.
- **Acceptance:** `docket models preset local` → `docket models list` shows all tiers free/local; `docket models preset anthropic` restores the default mapping; preset with a missing key warns and names the exact `docket keys add <KEY>` command.
- **Test:** Unit: each preset round-trips through the registry file; `local` preset + `docket keys sync` produces no missing-key warning (see MA-6); unknown preset name errors listing valid presets.

#### ✅ MA-5 — Cost honesty for unknown and local models

- **Goal:** Never report a made-up $0.00 for a model docket can't price.
- **Files:** `lib/helpers/workspace.sh` (`_aggregate_cost`, `_estimate_cost`), `lib/commands/cost.sh`, `lib/commands/list.sh`, `lib/helpers/budget.sh`. (pre-migration Bash; now `src/docket/cli/` + `src/docket/core/`)
- **Requirements:**
  - Model in `MODEL_PRICING` → price as today. Model whose provider is in `localProviders` → `$0 (local)`. Otherwise → display `n/a (no pricing data)`; in `--json` output emit `"costUsd": null, "pricingKnown": false` (not `0`).
  - Budget enforcement (`check_budget`): if an agent's model is unpriced and a budget is set, `warn` once that the budget **cannot be enforced** for that agent (and say why) instead of silently never triggering.
  - Display code in `list.sh` stops assuming the `anthropic/claude-` prefix: show `provider/short-name` generically (strip provider for width, keep it in `info`/`--json`).
- **Acceptance:** An agent on an unpriced model shows `n/a` in `docket cost` and `null` in `docket cost --json`; a local-provider agent shows `$0 (local)`; budget + unpriced model produces the explicit warning.
- **Test:** Unit on the pricing resolution function with: priced, local, unknown. Integration: fake sessions dir + unpriced model → `cost --json` has `pricingKnown: false`.

#### ✅ MA-6 — Provider-agnostic key plumbing & doctor checks

- **Goal:** Scoped key sync and health checks work for every registry provider; local providers don't nag about keys.
- **Files:** `lib/commands/keys.sh` (`PROVIDER_KEYS` py dict ~line 391, `_agent_provider`, help text ~44-51), `lib/commands/doctor.sh`, `lib/commands/install.sh`. (pre-migration Bash; now `src/docket/cli/` + `src/docket/cli/_doctor.py`/`_install.py`)
- **Requirements:**
  - Single source of truth for provider→key-env mapping (extend per MA-1 findings; at minimum anthropic, openai, google, openrouter + the local set needing none). Generate the python `PROVIDER_KEYS` dict from it rather than a second hardcoded copy, or document why the duplication stays.
  - `docket keys sync`: agent on a local provider gets no provider key and **no warning**. Agent on provider X with no X key stored → one clear `warn` naming `docket keys add <KEY>`.
  - `docket doctor`: per-agent check "model `<provider>/…` but `<PROVIDER>_API_KEY` not stored" (skip local providers). Also surface the active default model + tier mapping in doctor's summary so the model in use is visible during diagnosis.
  - `docket install`: stop implying only `ANTHROPIC_API_KEY` matters — prompt/hint based on the active preset's provider.
- **Acceptance:** Agent on `openrouter/...` with no OpenRouter key → doctor flags it precisely; agent on `ollama/...` → no key warnings anywhere; keys help lists all supported providers + where to get each key.
- **Test:** Unit: provider→key resolution for each provider incl. local→none; doctor check fires/skips correctly (extend the existing doctor drift test pattern).

#### ✅ MA-7 — Neutralize Claude-isms in agent templates

- **Goal:** Agent instruction prompts speak in **tiers**, not Claude model names, and don't hardcode Anthropic URLs — so a fleet on any provider gets correct instructions.
- **Files:** `lib/templates/SMART-ROUTING.md`, `lib/templates/docket-programmer.md`, `lib/templates/docket-tester.md`, `lib/templates/status-awareness.md`, `lib/templates/SOUL-error-handling.md`; `lib/helpers/workspace.sh` (`_create_workspace`); `lib/core/config.sh` (`TEMPLATE_VERSION`). (pre-migration Bash; templates now ship under `src/docket/templates/`, provisioning in `src/docket/cli/`/`core/`)
- **Requirements:**
  - Replace literal `haiku-4-5`/`sonnet-4-6`/`opus-4-6` and their prices with placeholders rendered at workspace-creation time from the live registry: `{{MODEL_ECONOMY}}`, `{{MODEL_STANDARD}}`, `{{MODEL_PREMIUM}}`, `{{PRICE_…}}` (render via the existing template-emission path in `_create_workspace`; portable sed or the python pass). Prose should say "the economy tier (currently {{MODEL_ECONOMY}})".
  - `console.anthropic.com` links become provider-resolved: a small provider→billing/console URL table; unknown provider → generic "check your provider's billing console".
  - Bump `TEMPLATE_VERSION` so `docket doctor` flags every existing agent for `docket maintain <id> rebuild` (this is exactly what the drift mechanism is for).
- **Acceptance:** `docket add` on a `local`-preset install produces SOUL/AGENTS/instruction files that mention the actual configured models and **zero** Claude model names; `grep -ri "sonnet\|haiku\|opus\|console.anthropic" ~/.openclaw/workspaces/projects/<new-agent>/` returns nothing on a non-Anthropic preset.
- **Test:** Unit: render a template with a non-default registry → placeholders substituted, no `{{` left; integration: new agent's SOUL.md contains the mapped economy model string.

#### ✅ MA-8 — Docs, help & README truth pass

- **Goal:** A new user reading any entry point learns within one screen: docket is model-agnostic, what the default is, what the free option is, and how to switch.
- **Files:** `README.md`, `docs/QUICK-START-DOCKET.md`, `docs/commands.md`, `docs/troubleshooting.md`, `docs/DOCKET.md`, `CLAUDE.md`, `lib/commands/help.sh` (now `src/docket/cli/_help.py`).
- **Requirements:**
  - README gains a **"Model support"** section near the top: explicit statement that docket works with any OpenClaw-supported provider — local/free (per MA-1/MA-4 reality) or remote/paid; the default mapping table gains a PROVIDER column and a row/callout for the free option; `docket models` + `docket models preset` documented with copy-paste examples.
  - The existing profile table (README ~216-218) is regenerated from the *current* built-in registry and labeled "default (Anthropic) — change with `docket models`".
  - `help.sh`: add `models` to command list; the profile/cost help text stops naming Claude models as the only options.
  - `CLAUDE.md`: update "Model profiles" bullet + architecture notes to describe the registry and `docket models`.
  - Every doc claiming or implying "requires Anthropic API key" is corrected to "requires the API key for your configured provider (none for local)".
- **Acceptance:**
  - `grep -rn "claude" README.md docs/` shows Claude only as *one labeled option/default*, never as a requirement.
  - README status/feature tables contain no 🚧 introduced by this phase; all examples runnable as written.
- **Test:** Docs task — acceptance is the grep audit above + `./tests/run-all-tests.sh` still green (help.sh changes are exercised by integration tests).

**Phase 6 exit criteria:** a user can run a whole fleet on a non-Anthropic provider (including the verified free/local path) using only documented `docket` commands; no command errors on a well-formed non-Claude model; cost output never invents $0 for unpriced models; templates/docs/help name the *configured* models, not Claude unconditionally; Anthropic defaults unchanged for users who do nothing.

### PHASE 6b — Tier-less role→model policy: unified agent/model architecture  *(✅ complete 2026-06-12)*

> **Why:** Phase 6 made the tier→model layer agnostic, but **model assignment still bypasses it**
> in three places, and the agent taxonomy is implicit:
>
> | Gap | Where | Symptom |
> | --- | ----- | ------- |
> | Specialists hardcode literal Anthropic IDs | `lib/commands/install.sh:175-182` (now `src/docket/cli/_install.py`) | `docket models preset openai` then `docket install` → specialists still get Claude models |
> | `docket add` ignores agent type | `lib/commands/add.sh:139`, `add.sh:247-248` (now `src/docket/cli/`) | `repo` and `task` agents both get `$DEFAULT_MODEL`; no per-kind default |
> | Agents store a resolved model, not an intent | `.docket-meta.json` `model` field; `models.sh` "existing agents keep their current model" notices | Remapping silently strands every existing agent on the old model (drift) |
> | Specialists outside the meta system | no `.docket-meta.json` under `~/.openclaw/workspaces/<spec>/` | `docket list`/`profile`/`doctor` don't see them; two tooling paths |
>
> **Root design flaws:** (a) agents remember a *model* when they should remember an *intent*
> (follow my role's policy), resolved through the registry at apply time; (b) the
> economy/standard/premium **tier ladder is a price abstraction, not a workload one** — it
> forces every provider catalog into 3 symmetric rungs and can't say *why* an agent gets a
> model (a manager on the cheap model isn't "economy", it's "high-volume/low-reasoning work").
>
> **Decided architecture (2026-06-11, with user): tiers are removed from the UX.**
>
> 1. **Role is the only user-facing model concept.** Resolution chain (highest wins):
>    `explicit pin (raw model ID)` → `role policy (role→model)` → `DEFAULT_MODEL`.
> 2. **Role policy is global-only** — one `roles:` map (role → model ID); built-in defaults
>    in `config.sh` (`ROLE_MODELS`), user-overridable in `docket-models.json` via the existing
>    overlay pattern. No per-project policy (per-agent pins cover exceptions).
>    Built-in defaults chosen for **token efficiency** (cheapest adequate model per workload),
>    anthropic preset: manager→haiku (chatty coordination, shallow reasoning),
>    reviewer→haiku (triage), tester→haiku (run+report), knowledge→haiku (retrieve/summarize),
>    programmer→sonnet (generation), security→sonnet (audit depth),
>    repo→sonnet, task→haiku (project-agent type defaults). Opus is an explicit per-agent
>    pin, not a standing rung.
> 3. **Presets become role→model tables** per provider (each preset picks its own
>    efficient mapping; no forced 3-rung symmetry). Tier names economy/standard/premium
>    survive only as **deprecated aliases** (warn + resolve via a hidden per-preset rank
>    list) so existing commands/scripts don't break during migration.
> 4. **Auto re-resolve on policy change** — `docket models set <role> <model>` /
>    `docket models preset <name>` re-resolves every policy-following agent (updates both
>    config sources, one gateway restart, per-agent change summary, audit-logged);
>    pinned agents are never touched. Policy is live, not a creation-time template.
> 5. **Specialists unify into the meta system** — `.docket-meta.json` with `kind: specialist`,
>    `role: <name>`; project agents get `kind: project` (existing `type` repo/task stays,
>    doubling as their policy role). One taxonomy visible in `docket list`, one tooling path.
> 6. **Fallback** becomes a per-preset ranked model list (walk down to next-cheaper);
>    replaces the premium→standard→economy tier walk in `get_fallback_model`.
>
> **Explicitly deferred (decided 2026-06-11):**
>
> - `docket models optimize` — data-driven right-sizing per role (join Phase 5 cost history ×
>   eval-harness pass/fail → "reviewer passes evals on a cheaper model, −$X/mo" suggestions,
>   never auto-applied). **Later phase**, after the role policy has accumulated usage history.
> - **Per-task dynamic routing** (manager escalates/downgrades model per task at runtime).
>   Blocked on a spike: does the OpenClaw daemon support per-session model override?
>   (Extend MODEL-AGNOSTIC-NOTES.md.) Do **not** reintroduce prompt-level SMART-ROUTING
>   (cut in Phase 2) as a substitute.

#### ✅ MA-9 — Role→model policy map (taxonomy + policy data, tiers out)

- **Goal:** A single data structure answers "what model should this kind of agent run on, and why", replacing every hardcoded per-agent model choice *and* the tier ladder.
- **Files:** `lib/core/config.sh` (`ROLE_MODELS` replaces `MODEL_PROFILES`; registry overlay), `lib/commands/models.sh` (presets become role→model tables; deprecated tier aliases), `lib/helpers/models.sh` (`validate_model`, `get_fallback_model`), `lib/commands/install.sh` (kill `specialist_models` array), `lib/commands/add.sh` (default by type), `lib/commands/profile.sh`, templates touched by MA-7 (`{{MODEL_ECONOMY}}`-style placeholders → role-based). (pre-migration Bash; model layer now `src/docket/core/models_policy.py`/`policy.py`, commands in `src/docket/cli/`, templates under `src/docket/templates/`)
- **Requirements:**
  - `declare -A ROLE_MODELS` in config.sh with the built-in defaults above + a short WHY string per role (shown in `docket models`); `docket-models.json` `roles:` key (role → model ID) overlaid by `load_model_registry` (same validation as today; unknown role names ignored with a warn). Old `profiles:` key still read → migrated to nearest roles with a deprecation warn.
  - `resolve_role_model <role>` helper: policy → model; unknown role → `DEFAULT_MODEL`.
  - Tier names (economy/standard/premium) accepted everywhere a model is accepted, but **deprecated**: warn + resolve through a hidden per-preset rank list (cheapest…strongest). `get_fallback_model` walks that rank list instead of tier IDs.
  - install.sh: delete the parallel arrays; each specialist resolves through `resolve_role_model`. Preset switched before install → specialists install on that provider.
  - add.sh: default model for a new agent = `resolve_role_model <type>` (repo/task); interactive prompt shows role default + resolved model.
  - `docket models` lists ROLE | MODEL | PRICE | WHY | SOURCE (builtin/user); `docket models set <role> <model>` replaces `set <tier>`.
  - MA-7 template placeholders: `{{MODEL_ECONOMY}}` etc. replaced by role-resolved placeholders (e.g. `{{MODEL_SELF}}`, `{{MODEL_PROGRAMMER}}`…); bump `TEMPLATE_VERSION` so doctor flags drift.
- **Acceptance:** `docket models preset openai && docket install` on a clean system registers all six specialists with OpenAI models; `docket add` of a task agent defaults to a cheaper model than a repo agent; `grep -n "anthropic/claude" lib/commands/install.sh` returns nothing (pre-migration Bash check; now `src/docket/cli/_install.py`); `docket profile <id> economy` still works but prints a deprecation warning.
- **Test:** Unit: `resolve_role_model` per built-in role + unknown + user-overridden; tier-alias resolution warns and resolves; fallback walks the rank list. Integration: repo vs task agents get different default models.

#### ✅ MA-10 — Policy-following agents + auto re-resolve

- **Goal:** Agents record *intent* — follow role policy or an explicit pin — and re-resolve when policy changes; drift becomes impossible by construction.
- **Files:** `lib/helpers/json.sh` / meta schema, `lib/commands/profile.sh`, `lib/commands/models.sh` (`_models_set`, `_models_preset`), `lib/commands/add.sh`, migration in `lib/commands/doctor.sh` or `maintain check`. (pre-migration Bash; meta schema now `src/docket/core/models.py`, commands in `src/docket/cli/`/`_doctor.py`)
- **Requirements:**
  - `.docket-meta.json` gains `modelSource` (`policy` | `pinned`); `model` stays as the resolved cache. `docket profile <id> <provider/model>` → pin; `docket profile <id> default` → back to policy; bare `docket profile <id>` shows role, model, source, budget.
  - `docket models set/preset` after writing the registry: iterate all agents (specialist + project), re-resolve every `modelSource: policy` agent via `set_agent_model`, single `restart_gateway()` at the end; per-agent change summary; `audit_log` each change. Pinned agents untouched.
  - Migration: agents without `modelSource` get one inferred — model equals their role's policy model → `policy`; else `pinned`. Lazy on read + a `doctor` fix.
  - Eval harness recommendations rephrase to "change role X's model" / "pin agent Y" (no tier vocabulary).
- **Acceptance:** `docket models preset google` updates every policy-following agent in both `openclaw.json` and `.docket-meta.json` with one gateway restart; a pinned agent survives untouched; `docket profile <id>` displays source (policy/pinned).
- **Test:** Unit: `modelSource` inference both ways; integration: 2 agents (policy + pinned) → `docket models set repo <other-model>` → first updated, second untouched, audit entries present.

#### ✅ MA-11 — Specialists join the meta system (one taxonomy)

- **Goal:** `docket list`/`profile`/`doctor` manage specialists and project agents through the same metadata, making "what kinds of agents exist and what type" answerable from one command.
- **Files:** `lib/commands/install.sh` (write meta at creation), `lib/commands/list.sh`, `lib/commands/profile.sh`, `lib/commands/doctor.sh` (backfill), `lib/helpers/workspace.sh`. (pre-migration Bash; now `src/docket/cli/`/`_install.py`/`_doctor.py` + `src/docket/core/`)
- **Requirements:**
  - Specialist workspaces get `.docket-meta.json` with `kind: specialist`, `role`, `modelSource`, `model`, `sessionKey`; written by `docket install`, backfilled by `docket doctor` for existing installs.
  - Project agent meta gains `kind: project` (backfilled the same way); `type` (repo/task) unchanged and doubles as the policy role.
  - `docket list --all` (or a `KIND` column) shows: kind, role/type, model, source (policy/pinned). Specialists excluded from project-only flows (delete, wire) with a clear error.
  - `docket profile <specialist> …` works — pinning one specialist (e.g. reviewer → a stronger model) without touching the global policy.
- **Acceptance:** on an existing install, `docket doctor` backfills meta for all six specialists; `docket list --all` shows the complete taxonomy; `docket profile reviewer anthropic/claude-opus-4-6` changes only the reviewer.
- **Test:** Integration: fresh install → list shows 6 specialists with policy-derived models; doctor on a meta-less specialist workspace creates valid meta; delete/wire on a specialist errors.

**Phase 6b exit criteria:** no hardcoded model ID outside `config.sh`/`models.sh` data tables; no tier vocabulary in UX except deprecation warnings; switching provider preset retargets the whole fleet (minus pins) in one command; `docket list --all` answers "what agents exist, what kind, what model, why" at a glance; per-role defaults are the cheapest adequate model, with the WHY visible in `docket models`.

---

### PHASE 8 — Agent observability, guardrails & drift (HITL)  *(🟡 new — work top to bottom)*

> **Source spec — goals:** every agent action leaves a durable, queryable trace (G1); destructive
> actions are gated behind explicit human approval (G2); untrusted input is guard-railed before it
> reaches an agent (G3); role success-rate degradation surfaces without manual inspection (G4) —
> all in docket's idiom (Bash + python-for-JSON, flat JSONL, systemctl, Telegram), **no new runtime
> services** (G5).
>
> **Non-goals (hold the line — reject PRs that cross these):** no external observability stack
> (no OTel collector / Prometheus / Grafana); no trace database (the filesystem **is** the store,
> queried with jq/python); no ML detection in v1 (prompt-injection & PII are heuristic/regex —
> a classifier is a deferred MAY); single-operator (no multi-tenant RBAC); no new real-time
> transport ("live" = `tail -f` + the existing Telegram channel).
>
> **The one constraint that shapes this phase:** docket is a provisioning/config CLI — it does
> **not** sit in the agent execution path. The OpenClaw daemon executes every tool call (verified:
> `workflow.sh` shells to `lobster run`; the security-gates spec already states the daemon must own
> the approval hook). So the spec splits cleanly:
>
> | Spec goal | Pure-docket? | How |
> | --------- | ------------ | --- |
> | G1 traces · G4 drift · O7 metrics | ✅ yes | docket already reads daemon `~/.openclaw/agents/<id>/sessions/*.jsonl` for cost (`_aggregate_cost`); project those into the trace format and append docket-mediated events. No daemon change. |
> | G2 destructive gate | ⚠ partly | the enforcement hook already exists, opt-in: `exec-approvals.json` + `approvals.exec` routing (`docket gates`, `security.sh`). docket owns policy/config; the **daemon owns the block**. |
> | G3 untrusted-input guard (inline) | ❌ daemon | inline `pre_input`/`pre_output` interception of a live agent needs the daemon. docket enforces at the **one ingress it owns** (the manager task queue) and files a daemon-hook request for the rest. |
>
> Work order de-risks that daemon dependency: foundations → observability (zero behavior change,
> ships first) → policy engine (pure, fully testable) → enforcement+HITL (the only hard daemon
> dependency, isolated so the rest is not held hostage) → drift (needs only traces). **Reuse, do
> not reinvent:** `audit_log`'s append + never-log-secrets idiom (`lib/helpers/audit.sh`; now `src/docket/core/audit.py`) → `trace_event`;
> `json_atomic_write` / `with_docket_lock` (`lib/helpers/json.sh`; now `src/docket/edges/store.py`); `_aggregate_cost` / `check_budget` for
> cost→trace; the `exec-approvals.json` gate (`lib/helpers/security.sh`; now `src/docket/core/security.py`) for G2; `get_tg_binding` /
> `upsert_binding` for routing; the `docket serve` background loop (`lib/commands/serve.sh`; now `src/docket/serve.py`) for the
> timeout watcher — **no new service** (G5).
>
> **Collision decisions (the spec's CLI clashes with shipped commands — resolved):**
>
> 1. **`docket audit` already exists** (renders the operator-mutation log, Phase 4). The spec's
>    "export raw trace JSONL" becomes **`docket trace export <project> [--since DATE]`**. Keep the
>    split: `audit` = "what the *operator* changed"; `trace`/`metrics` = "what the *agents* did".
> 2. **`$DOCKET_HOME` is undefined** (base is `OPENCLAW_DIR`) → add `DOCKET_HOME="${DOCKET_HOME:-$OPENCLAW_DIR}"`
>    alias so spec paths read literally. Traces at `$DOCKET_HOME/traces/<project>/<session_id>.jsonl`,
>    policies at `$DOCKET_HOME/policies/<name>.json`.
> 3. **No per-run `session_id` exists** (only the persistent session *key* `agent:<id>:<project>`)
>    → OBS-0 spike decides the derivation (deterministic from the daemon session file; docket-minted
>    fallback).
>
> Spec open questions resolved in §6 (D-6…D-8). Spec tests T1–T6 map to the OBS task `Test` fields.

#### Sub-phase 8.0 — Foundations *(no user-visible behavior)*

#### ✅ OBS-0 — `session_id` spike + base wiring

- **Why:** Everything keys off a per-run `session_id` that does not exist yet (O2/O5).
- **Files:** `lib/core/config.sh` (pre-migration Bash; config now `src/docket/config.py`).
- **Requirements:** Inspect a live `~/.openclaw/agents/<id>/sessions/` dir; confirm whether one file == one bounded run. Decide `session_id` = `s_<sha1(agent,project,basename)>` derived from the session file (no daemon change) if so; docket-minted id at dispatch/workflow-run if not. Add to `config.sh`: `DOCKET_HOME`, `TRACES_DIR`, `POLICIES_DIR` and the knobs with defaults — `SESSION_TIMEOUT`, `APPROVAL_TIMEOUT=900` (15 m, H5), `METRICS_WINDOW=50` (O8), `BASELINE_WINDOW=100`, `DRIFT_THRESHOLD=15`, `DRIFT_COOLDOWN=86400` (D1–D3). All env-overridable (CI hermeticity).
- **Acceptance:** notes doc records the verified session→run mapping + chosen `session_id` rule; new config vars resolve and are overridable.
- **Test:** Unit: each new config var has its documented default and honors an env override.

#### ✅ OBS-1 — `redact` + `trace_event` helpers

- **Why:** Single source of truth for the O3 event shape and GR8 redaction; sibling to `audit_log`.
- **Files:** new `lib/helpers/redact.sh`, new `lib/helpers/trace.sh`; source both in `bin/docket`. (pre-migration Bash; redact/trace now in `src/docket/core/trace.py`)
- **Requirements:** `redact <text>` — strip API-key/token shapes, emails, and every value in the `docket keys` registry; pure, no I/O. `trace_event <project> <session_id> <agent_role> <event_type> <payload-json> [cost_usd] [duration_ms]` — build the O3 record (UTC `ts`, all required fields), run `payload` through `redact`, validate `event_type` against the O4 closed set (`session_start, tool_call, tool_result, guardrail_check, guardrail_block, approval_requested, approval_granted, approval_denied, cost_charged, budget_warning, budget_exceeded, drift_alert, error, session_end`), append one line to `$TRACES_DIR/<project>/<session_id>.jsonl` (mkdir -p, 0600, `DOCKET_NO_TRACE=1` escape hatch). One file per session = atomic vs concurrent sessions (O1).
- **Acceptance:** event is valid one-line JSON with all required fields; unknown `event_type` rejected; a secret in `payload` is redacted on disk.
- **Test:** Unit (seeds T4): each assertion above; `redact` positive per pattern + negative on clean text.

#### Sub-phase 8.1 — Observability §5 *(G1, G5; data for G4 — ships first, zero behavior change)*

#### ✅ OBS-2 — Session lifecycle + cost folded into traces (O5, O6)

- **Why:** A trace must open with `session_start` and close with a terminal `session_end`; cost stops being a parallel system.
- **Files:** `lib/commands/team.sh` (dispatch), `lib/helpers/budget.sh`, `lib/commands/cost.sh`. (pre-migration Bash; now `src/docket/cli/` + `src/docket/core/`)
- **Requirements:** Where docket initiates a bounded run it owns (`docket team delegate` dispatch, `docket workflow … run` if invoked through docket), emit `session_start` (first line) and `session_end` carrying `status: success|failure|aborted` (O5). In the cost path emit `cost_charged` per accounted turn (O6); in `check_budget` emit `budget_warning` (≥80%) and `budget_exceeded` (≥100%) **into the trace** instead of only flipping `paused`. Offset-track per session file (reuse `.cost-index.json` discipline) so re-runs don't double-emit.
- **Acceptance:** a run produces `session_start`…`session_end`; a costed session emits `cost_charged`; crossing the cap emits exactly one `budget_exceeded`.
- **Test:** Integration: fake sessions dir → expected event sequence; cap crossing emits one `budget_exceeded`.

#### ✅ OBS-3 — Ingestion bridge + timeout sweep (O5)

- **Why:** Most runs are started by the daemon, not docket — G1 must cover them without a daemon change.
- **Files:** `lib/helpers/trace.sh` (`trace_ingest <project>`), `lib/commands/serve.sh` (sweep in the existing loop). (pre-migration Bash; now `src/docket/core/trace.py` + `src/docket/serve.py`)
- **Requirements:** `trace_ingest` reads the project's agents' `sessions/*.jsonl`, projects each into trace events (`tool_call`/`tool_result` where the daemon log distinguishes them, else a coarse `tool_call` per turn), idempotently (offset-tracked), redacted. Document the fidelity ceiling (reconstructed from logs; richer events are a daemon enhancement). The `docket serve` loop marks any trace with no `session_end` after `SESSION_TIMEOUT` as `status: aborted` (synthetic `session_end`) — no new service (G5).
- **Acceptance:** ingesting a sample sessions dir yields a valid trace per session; a stale open trace is coerced to `aborted` by the sweep.
- **Test:** Unit: ingestion is idempotent (second run adds nothing); sweep writes exactly one synthetic `session_end`.

#### ✅ OBS-4 — `docket trace` + `docket metrics` (O7, O8, O9)

- **Why:** The CLI surface that makes traces queryable and metrics derivable from traces alone (NG1/NG2).
- **Files:** new `lib/commands/trace.sh` (`cmd_trace`), new `lib/commands/metrics.sh` (`cmd_metrics`); wire both into `lib/core/router.sh`, `bin/docket` (explicit `source`, not a glob), `lib/commands/help.sh`. (pre-migration Bash; now `src/docket/cli/_trace.py`/`_metrics.py`, the `src/docket/__main__.py` command map, and `src/docket/cli/_help.py`)
- **Requirements:** `docket trace <session_id>` renders one trace human-readable (ts · event_type · summary · cost/duration, colorized via `output.sh`); `docket trace tail <project>` follows the most-recent session (`tail -f`); `docket trace export <project> [--since DATE]` is raw JSONL passthrough filtered by `ts` (the §2.1 accountability artifact). `docket metrics [--role R] [--project P] [--window N]` computes over the rolling window (default `METRICS_WINDOW=50` terminal sessions): success rate (`session_end{success}` / terminal), mean & p95 `duration_ms`, total & mean `cost_usd`, guardrail trip count by action — pure python-over-JSONL, no store.
- **Acceptance:** `docket trace <id>` renders; `trace tail` follows live; `trace export --since` filters; `docket metrics` returns correct numbers on a synthetic trace set; `scripts/metrics.sh --check` passes (README command count bumped).
- **Test:** Unit: synthetic traces → known success rate, p95, cost, trip counts (T-style).

**Sub-phase 8.1 exit:** full agent-action visibility from flat JSONL; `trace`/`metrics`/`trace export` ship; cost lives in the trace. Zero behavior change. Flip the new spec file's Status → Implemented (Phase 1). **Shippable.**

#### Sub-phase 8.2a — Policy engine §6 *(G2/G3 logic, no enforcement — pure docket, fully testable)*

#### ✅ OBS-5 — Policy schema, loader & most-restrictive-wins evaluator (GR1–GR6)

- **Why:** Guardrails must be declarative flat files, not hardcoded (GR1); the evaluator is pure and testable before any daemon work.
- **Files:** new `lib/helpers/policy.sh` (pre-migration Bash; now `src/docket/core/policy.py`/`security.py`).
- **Requirements:** Load `$POLICIES_DIR/*.json`; each policy = `id`, `applies_to[]` (roles + `*`, GR2), `hook` ∈ {pre_input,pre_tool_call,pre_output} (GR3), `match` ({type:"regex",pattern} — leave `type` open for a future `classifier`, F1), `action` ∈ {allow,warn,redact,require_approval,block} (GR4), `message`. Validate on load (bad policy = loud error, not silent skip). `policy_eval <role> <hook> <text>` returns the single winning action by `block > require_approval > redact > warn > allow` (GR5). Every eval emits `guardrail_check`; any non-allow additionally emits the matching event (`guardrail_block`/`approval_requested`/…) via `trace_event` (GR6).
- **Acceptance:** overlapping policies resolve to the most restrictive; every eval leaves a `guardrail_check` in the trace.
- **Test:** Unit — overlapping-policy resolution (**T2**); malformed policy errors on load.

#### ✅ OBS-6 — Baseline policies + `docket policies` command (GR7, GR9)

- **Why:** Ship the required default policy set and a way to author/inspect/dry-run it.
- **Files:** new `lib/templates/policies/*.json` (baselines), new `lib/commands/policies.sh` (`cmd_policies`); wire into router/bin/help; install via `docket policies init` (and optionally `docket install`). (pre-migration Bash; now `src/docket/templates/` + `src/docket/cli/_policies.py`)
- **Requirements:** Baselines — `block-destructive.json` (pre_tool_call, require_approval: `rm -rf`, `git push --force`, `DROP|TRUNCATE`, `systemctl stop|disable`, mass deletion, credential-file writes — aligned with the `_GATES_SAFE_BINS` exclusions); `prompt-injection.json` (pre_input, warn by default / block configurable: instruction-override + exfiltration phrasings) — **untrusted inputs only (GR9)**; `secret-pii-redact.json` (pre_output, redact: keys, tokens, emails, key-registry values — wired to `redact`, GR8). `docket policies`: `list`, `show <id>`, `init` (install baselines), `test <hook> <role> "<text>"` (dry-run the evaluator).
- **Acceptance:** each baseline trips on a positive case and passes a negative; `policies test` dry-runs without side effects.
- **Test:** Unit per baseline — positive trips, negative passes (**T1**).

#### ✅ OBS-7 — Trust boundary on the task queue (GR9; answers spec Q2 / D-7)

- **Why:** Injection heuristics must run on untrusted input only; the queue is the ingress docket owns.
- **Files:** `lib/commands/team.sh` (TASK_LIST.json schema). (pre-migration Bash; now `src/docket/cli/`)
- **Requirements:** Add `source` ∈ {operator,telegram,api,fetched} to each task. `operator` = trusted → pre_input/injection policies skip it; everything else = untrusted → they run. `docket team delegate` defaults `source=operator`; the field is settable for ingested tasks.
- **Acceptance:** an `operator` task bypasses injection policies; a `fetched` task is evaluated.
- **Test:** Unit: schema accepts `source`; evaluator gating honors trusted vs untrusted.

#### Sub-phase 8.2b — Enforcement + HITL §6/§7 *(G2, G3 ingress — ⚠ the only hard daemon dependency)*

#### ✅ OBS-8 — pre_input enforcement at the queue + DAEMON gate binding

- **Why:** Deliver G3 at the ingress docket controls now; map G2 onto the daemon hook that already exists.
- **Files:** `lib/commands/team.sh`, `lib/helpers/security.sh` (translate policy → `exec-approvals.json`). Record what is native vs pending inline in this task. (pre-migration Bash; now `src/docket/cli/` + `src/docket/core/security.py`)
- **Requirements:** In `docket team delegate`, for untrusted `source` run `policy_eval <role> pre_input <task-text>`: `block` → reject; `warn` → annotate; `require_approval` → HITL (OBS-10). **DAEMON:** translate the `block-destructive` policy into `apply_exec_approval_gates` allowlist/deny + `approvals.exec` routing (reuse the opt-in mechanism). Where exec-approval is too coarse (regex on full command; pre_output redaction), file an upstream daemon-hook request and document the gap. Do **not** claim inline `pre_output` redaction until the daemon supports it — until then pre_output redaction applies to docket-written traces + outbound Telegram only (still satisfies GR8 for those sinks).
- **Acceptance:** an untrusted task matching a `block` policy is rejected before dispatch; a destructive command maps to the daemon gate; the feasibility doc states precisely what is enforced natively vs pending.
- **Test:** Unit: queue rejects a `block` match; integration: gate config written matches the policy.

#### ✅ OBS-9 — Approval store + Telegram send (H1, H2; GR8)

- **Why:** HITL needs a durable pending-approval record and an outbound channel — docket has no send function today.
- **Files:** new `lib/helpers/approval.sh`, new `lib/helpers/telegram.sh`. (pre-migration Bash; approval now `src/docket/core/approval.py`, Telegram routing via the ACL `src/docket/edges/adapters/openclaw.py`)
- **Requirements:** `approval_create <project> <role> <action>` mints an opaque `approval_token`, persists `{token,project,role,action,state:pending,created}` to `$DOCKET_HOME/approvals/<token>.json` (atomic, 0600), emits `approval_requested` + a pause marker (H1/H2). `tg_send <agent_id> <text>` resolves `get_tg_binding`, POSTs via bot `sendMessage` (curl), **always `redact` first** (GR8); message carries project, role, redacted action, token. If no send capability is configured, degrade to CLI-only approval — never hard-fail.
- **Acceptance:** an approval persists with state `pending` and an opaque token; the Telegram message contains no secret; missing bot config degrades gracefully.
- **Test:** Unit: token minted + persisted; **T4** — secret reaches neither the trace nor a captured `tg_send` payload.

#### ✅ OBS-10 — Grant/deny + fail-safe timeout (H3, H4, H5)

- **Why:** Approvals must be grantable two ways, and silence must never authorize.
- **Files:** new `lib/commands/approve.sh` + `lib/commands/deny.sh` (wire into router/bin/help), `lib/commands/serve.sh` (timeout watcher). (pre-migration Bash; now `src/docket/cli/_approve.py`/`_deny.py` + `src/docket/serve.py`)
- **Requirements:** CLI (authoritative): `docket approve <token>` / `docket deny <token>` → validate, transition state, emit `approval_granted` / `approval_denied` (H4), write resume/abort marker. Telegram reply `approve <token>`/`deny <token>` is **DAEMON**-routed — until the daemon routes replies to docket, document Telegram as notify-only and CLI as the grant path. Fail-safe: the `docket serve` watcher expires any `pending` approval older than `APPROVAL_TIMEOUT` → state `expired`, treated as **denied** (emit `approval_denied`) (H5; G5 — reuse serve loop).
- **Acceptance:** granted resumes; denied aborts; a pending approval past timeout becomes denied.
- **Test:** Integration — granted / denied / timeout-defaults-to-denied (**T3**).

#### Sub-phase 8.3 — Drift §8 *(G4 — needs only traces)*

#### ✅ OBS-11 — Baseline tracker, drift alert & cooldown (D1–D3)

- **Why:** Role degradation must self-surface, computed from traces with no extra store (NG2).
- **Files:** new `lib/helpers/drift.sh`; hooked from wherever `session_end` is written (OBS-2 + serve sweep); surfaced in `lib/commands/metrics.sh` and `serve` `/status.json`. (pre-migration Bash; now `src/docket/core/` + `src/docket/cli/_metrics.py` + `src/docket/serve.py`)
- **Requirements:** Per `agent_role`, baseline success rate over the trailing `BASELINE_WINDOW=100` terminal sessions (D1). After each `session_end`, compare the current rolling window (O8) to baseline; if current < baseline − `DRIFT_THRESHOLD` (15 pp), emit `drift_alert` (naming the role + before/after rates) and `tg_send` a notification (D2). Rate-limit to ≤1 alert per role per `DRIFT_COOLDOWN=24h` (D3; persist last-alert ts per role). Aborted sessions **count** against success rate (D-6).
- **Acceptance:** synthetic traces crossing the threshold emit exactly one alert; a second within cooldown is suppressed.
- **Test:** Integration — threshold crossing → one alert + cooldown suppression (**T5**).

#### ✅ OBS-12 — Spec, CI suite & docs (T6, G5 truth pass)

- **Why:** The repo gates on spec coverage + metrics counts + ShellCheck; the work isn't done until CI proves it.
- **Files:** new `specs/functional/observability-guardrails.spec.md`, [tests/run-all-tests.sh](tests/run-all-tests.sh), [.github/workflows/ci.yml](.github/workflows/ci.yml), `scripts/metrics.sh`, README + `docs/` + `lib/commands/help.sh` (now `src/docket/cli/_help.py`) + [CLAUDE.md](CLAUDE.md).
- **Requirements:** Commit the spec (hard gate — `scripts/validate-specs.sh` blocks on missing coverage), Status flipped per sub-phase. Add the guardrail + observability suites to `run-all-tests.sh`; CI runs them on every push/PR (**T6**); keep `-S warning` ShellCheck clean. Update `scripts/metrics.sh` expected counts + README for the new commands (`trace`, `metrics`, `policies`, `approve`, `deny`). Document the new commands honestly, including the daemon-dependency caveat for inline pre_tool_call/pre_output and Telegram reply-routing.
- **Acceptance:** CI green with the new suites; `validate-specs.sh` + `metrics.sh --check` pass; docs name what is enforced natively vs pending daemon support.
- **Test:** the CI run itself (**T6**); `grep` audit that docs don't overclaim inline enforcement.

**Phase 8 exit criteria:** every agent action docket can observe leaves a queryable JSONL trace; `docket trace`/`metrics`/`trace export` work over the filesystem store (no DB, no collector); destructive commands route through the opt-in daemon gate and `require_approval` policies pause behind a token that fails closed on timeout; untrusted task input is guard-railed at the queue; role success-rate drift self-surfaces with cooldowned alerts; the daemon-dependent items (inline pre_tool_call/pre_output, Telegram reply-routing) are documented as such, not overclaimed; full suite green in CI.

---

### PHASE 9 — Contract integrity: close the spec↔runtime gap (de-ceremony)  *(🟠 new — audit-driven)*

> **Audit verdict (blunt):** docket's contract discipline is **partly ceremonial**. The `specs/`
> tree is well-authored and CI runs `validate-specs.sh` + `spec-coverage.sh` on every push — but
> those tools validate *markdown structure and file presence*, not *that the running code matches
> the contract*. The real schema in this project — the dual-source agent config — is **hand-
> duplicated across 6+ command files with no single definition and almost no drift detection**.
> Several spec promises are already lies the toolchain can't catch. This phase makes the contracts
> load-bearing or strips the parts that only perform rigor.
>
> **Scope correction (what the generic CDD/SDD audit asked vs. what docket is):** docket is a pure
> Bash CLI. There is **no** OpenAPI/Swagger/AsyncAPI file, **no** code-generation toolchain
> (datamodel-codegen / openapi-generator / stainless), and **no** database or migrations
> (Alembic/Flyway/Knex/Liquibase) — verified by `git ls-files`. So the audit's "dead codegen loop"
> (§1) and "migration rigor" (§3) pillars are **N/A by construction** — there is nothing to be
> hollow. The audit's *spirit* maps onto docket's three actual contracts: (a) the markdown specs
> under `specs/`, (b) the dual-source config that "must stay in sync" — each agent's
> `.docket-meta.json` ↔ the daemon's `openclaw.json`, and (c) the `--json` / HTTP output shapes.
> Findings below are against those.
>
> **Verified findings (file:line):**
>
> | # | Finding | Evidence |
> | - | ------- | -------- |
> | F1 | **`--json` wrapper the spec promises is emitted by zero commands.** The spec defines a `{success, data, error, timestamp, version}` envelope; no `cmd_*` ever produces it — each hand-assembles its own ad-hoc shape inline in a python heredoc. | promised: [specs/api/cli-interface.spec.md:340-350](specs/api/cli-interface.spec.md#L340); `grep -rn '"success"' lib/commands/` → **0 hits** (pre-migration Bash; commands now `src/docket/cli/`) |
> | F2 | **Drift detection covers one field.** `docket doctor` compares only `model` (meta vs openclaw). `budgetUsd`, `paused`, `pausedReason`, `modelSource`, `name`, `stack` can diverge silently. | `doctor.sh:187-197` (json path), `doctor.sh:515-526` (human path) (pre-migration Bash; now `src/docket/cli/_doctor.py`) |
> | F3 | **No schema; no validation on write.** `_meta_set` writes `data[field]=value` with zero type/enum checks — `meta_set <id> budgetUsd "not-a-number"` succeeds and is later swallowed by a `try/float()` with no error. The field list lives only in prose. | `lib/helpers/json.sh` `_meta_set` (now `src/docket/edges/store.py` + `src/docket/core/models.py`); schema prose only in [specs/data/docket-meta.spec.md](specs/data/docket-meta.spec.md) |
> | F4 | **Coverage % is cosmetic.** `spec-coverage.sh` scores a command "covered" if a markdown heading mentions it or a same-named file exists — it never checks args/flags/return codes against the code. | [scripts/spec-coverage.sh:19-45](scripts/spec-coverage.sh#L19) |
> | F5 | **Spec registry is stale & incomplete.** `gates`, `audit`, `eval`, `models`, `completions` are routed but absent from the spec's command registry; `input-validation.spec.md` still lists removed `reset`/`repair` as live; `profile` spec documents `economy/standard/premium` as args though tiers are deprecated. Nothing cross-checks `router.sh` against the spec. | router arms in `lib/core/router.sh` (now the command map in `src/docket/__main__.py`) vs [specs/api/cli-interface.spec.md](specs/api/cli-interface.spec.md); [specs/validation/input-validation.spec.md:19](specs/validation/input-validation.spec.md#L19) |
>
> **Principle for this phase:** every fix either makes a contract *mechanically enforced* (CI fails
> on divergence, or the runtime refuses bad data) or *deletes the ceremony* (fix the spec to match
> reality, drop a misleading metric). No new prose that code can ignore.

#### ✅ CDD-1 — Single source of truth for the agent schema (kills the hand-duplication)

- **Why:** F2/F3 — the `.docket-meta.json` field set is redefined implicitly in every command that touches it; nothing declares it once.
- **Files:** new `lib/core/schema.sh` (or a `declare -A AGENT_FIELDS` block in `lib/core/config.sh`); consumed by `lib/helpers/json.sh`, `lib/commands/doctor.sh`; cross-checked against [specs/data/docket-meta.spec.md](specs/data/docket-meta.spec.md). (pre-migration Bash; the schema now lives in `src/docket/core/models.py`, consumed by `src/docket/edges/store.py` + `src/docket/cli/_doctor.py`)
- **Requirements:** Declare each field once with: name, type (`string|number|enum|bool`), enum values (e.g. `modelSource ∈ {policy,pinned}`, `kind ∈ {project,specialist}`), and a **sync class** — `synced` (mirrored to `openclaw.json`) vs `local` (docket-only). This table is the authority `validate_model`/`meta_set`/`doctor` all read. A CI test asserts the table and the `## Schema` section of `docket-meta.spec.md` list the same fields (spec can't drift from the table).
- **Acceptance:** adding a field to the spec but not the table (or vice-versa) fails a unit test; `doctor` and `meta_set` enumerate fields from the table, not from inline literals.
- **Test:** Unit: table↔spec field-set equality; type/enum/sync-class present for every field.

#### ✅ CDD-2 — Validated `meta_set` (reject bad writes at the boundary)

- **Why:** F3 — silent acceptance of malformed values is the kind of "looks fine until it isn't" bug specs are supposed to prevent.
- **Files:** `lib/helpers/json.sh` (`_meta_set`). (pre-migration Bash; now `src/docket/edges/store.py` + `src/docket/core/models.py` validation)
- **Requirements:** Before writing, look the field up in the CDD-1 table: unknown field → `error` (typo guard); type mismatch (`budgetUsd` non-numeric or negative, `paused` non-bool, `modelSource` outside its enum) → `error` naming the field and the rule. Keep `DOCKET_NO_*` escape hatches consistent with existing helpers. Do **not** loosen the atomic-write/lock path.
- **Acceptance:** `meta_set x budgetUsd not-a-number` and `meta_set x bugdetUsd 5` (typo) both fail loudly; valid writes unchanged.
- **Test:** Unit: each invalid type/enum/unknown-field rejected; valid round-trips.

#### ✅ CDD-3 — Sync completeness + full-field drift in `doctor`

- **Why:** F2 — drift detection that checks 1 of ~12 fields gives false confidence; the spec implies more is synced than is.
- **Files:** `lib/commands/doctor.sh`, `lib/helpers/session.sh`/`lib/helpers/json.sh` (sync writers), [specs/data/docket-meta.spec.md](specs/data/docket-meta.spec.md). (pre-migration Bash; now `src/docket/cli/_doctor.py` + `src/docket/core/sync.py` + `src/docket/edges/store.py`)
- **Requirements:** Using CDD-1's sync class: `doctor` compares **every `synced` field** (meta ↔ openclaw), not just `model`, and reports each divergence; `local` fields are explicitly documented as docket-only in the spec (so no one expects them in `openclaw.json`). Decide and record per field whether it should be `synced` or `local` (D-9). `--fix` re-syncs from the documented source of truth.
- **Acceptance:** mutating any `synced` field in one source surfaces in `docket doctor`; `local` fields are labeled and not flagged.
- **Test:** Integration: extend the existing drift test (P0-2 pattern) to a non-`model` synced field.

#### ✅ CDD-4 — Resolve the `--json` output contract (F1)

- **Why:** A documented envelope that nothing emits is a lie in the API spec; consumers parse undocumented ad-hoc shapes.
- **Files:** [specs/api/cli-interface.spec.md](specs/api/cli-interface.spec.md), the `--json` emitters (`list.sh`, `cost.sh`, `info.sh`, `doctor.sh`, `snapshot.sh` — pre-migration Bash; now `src/docket/cli/`), `lib/commands/serve.sh` (`/status.json`, `/metrics`, `/health`; now `src/docket/serve.py`).
- **Requirements:** Pick one (D-10): **(A)** adopt the `{data, …}` envelope across all read commands, or **(B)** delete the unused envelope from the spec and instead document each command's *actual* shape in `specs/data/`. Either way: pin every output shape in a spec, enforce key-name consistency (`costUsd`/`budgetUsd` camelCase everywhere — no `cost_usd` in JSON), and add a test that each `--json` command's keys match its documented shape.
- **Acceptance:** spec and emitted JSON agree for every read command; a renamed field breaks a test.
- **Test:** Unit/integration: `<cmd> --json | jq` keys equal the documented set; naming-consistency assertion across commands.

#### ✅ CDD-5 — Mechanical spec↔code linter (replace the cosmetic coverage %)

- **Why:** F4/F5 — CI should fail when the command surface and the spec disagree, not report a misleading 92–100%.
- **Files:** rewrite/extend [scripts/spec-coverage.sh](scripts/spec-coverage.sh); wire as a **blocking** step in [.github/workflows/ci.yml](.github/workflows/ci.yml).
- **Requirements:** Extract the real command set from `router.sh` `case` arms (+ `cmd_*` functions); extract the documented command set from `specs/api/cli-interface.spec.md`. Fail on either-way mismatch: a routed command with no spec entry (catches `gates`/`audit`/`eval`/`models`/`completions`), or a spec'd command not routed (catches stale `reset`/`repair`). Drop the percentage; emit a concrete diff. (Optional stretch: assert documented flags exist in the handler.)
- **Acceptance:** today's repo makes this linter **red** (it surfaces the 5 missing + the stale refs); after CDD-6 it's green; adding a command without a spec turns it red again.
- **Test:** the linter is the test; a fixture proves it fails on an injected mismatch.

#### ✅ CDD-6 — De-stale the specs (one-time truth pass)

- **Why:** F5 — make the specs match the shipped CLI so CDD-5 can go green and stay green.
- **Files:** [specs/api/cli-interface.spec.md](specs/api/cli-interface.spec.md) (add `gates`, `audit`, `eval`, `models`, `completions`; correct `profile` args to model-id/`default`, drop tier-as-arg), [specs/validation/input-validation.spec.md](specs/validation/input-validation.spec.md) (remove `reset`/`repair` from "Used By"), any functional spec describing removed behavior.
- **Acceptance:** `grep` audit shows no removed command described as live; CDD-5 linter passes; `validate-specs.sh` stays green.
- **Test:** CDD-5 linter green; spec-section structure intact.

**Phase 9 exit criteria:** the `.docket-meta.json` schema is declared **once** and drives validation + drift; `meta_set` refuses malformed/unknown fields; `docket doctor` detects drift on every synced field (and the spec is honest about local-only ones); every `--json`/HTTP shape is documented and test-pinned with consistent naming; CI **fails** when `router.sh` and the spec registry disagree (no more cosmetic coverage %); no spec describes a removed command as live. Net: the contracts that remain are enforced; the ones that only performed rigor are gone.

---

### PHASE 10 — Agent architecture: project pods (scope ≠ role ≠ lifecycle)  *(🟡 active — Python core; work top to bottom)*

> **Executable task board:** [TODO.md](TODO.md) (self-contained
> cards, claimable by separate agents). **Rationale long-form:** `internal-docs/agent-structure-analysis.md`.
> This section is the authoritative plan; the task board is the how/claim/status surface.
>
> **The problem (three structural defects in today's agent model).** docket has two agent kinds that
> overlap and contradict:
>
> - **Project agents** (`docket add`) — one per codebase, persistent, full read/write/edit on their
>   own repo. Template says it "knows this project deeply" **and** "Delegate: implementation → programmer."
> - **Specialist agents** (`docket install`) — manager, programmer, reviewer, tester, knowledge,
>   security ([config.py:45-46](src/docket/config.py#L45-L46)) — single **shared** instances at
>   `~/.openclaw/workspaces/<role>/`, used by every project.
>
> | # | Defect | Evidence |
> | - | ------ | -------- |
> | A | **Two doers, neither complete.** The repo project agent has write access + deep context but is told to delegate; the shared programmer "implements an exact <500-tok brief" in a sandbox with **no git** and "does NOT investigate or design." The knower can't build; the builder doesn't know. | `templates/docket-programmer.md`; repo SOUL at [cli/__init__.py:533-563](src/docket/cli/__init__.py#L533) |
> | B | **Shared specialists break the core isolation guarantee.** docket's headline is context isolation via session keys (`agent:<id>:<project>`, [cli/__init__.py:702](src/docket/cli/__init__.py#L702)). But specialists are **singletons with hardcoded keys** (`specialist:<role>:…`, `manager:atlas:coordination`). One programmer instance serves project A and B in the *same* session — the exact cross-project contamination the product exists to prevent. | `_provision_specialists` writes one shared workspace per role ([cli/_install.py:288-325](src/docket/cli/_install.py#L288)) |
> | C | **"Delegation" is instruction-only; no runtime exists.** `TASK_LIST.json` is written *only* by CLI commands; no code makes the manager read it, route work, or message specialists. The "team" is markdown hoping agents talk over Telegram. | `team delegate/queue/done` are the only `TASK_LIST.json` writers ([cli/__init__.py](src/docket/cli/__init__.py)); `grep TASK_LIST templates/` → nothing |
>
> **Root cause:** the design flattens **three independent dimensions** into one "agent type" —
> **role** (what it does) · **scope** (whose data it may see) · **lifecycle** (persistent vs per-task).
> "Programmer" is modeled as a global persistent singleton when it is really a *role* that should be
> instantiated *per project, per task*. The role *definitions* are good; their *deployment* is wrong.
>
> **Target structure — pods (one team per product, roles inside, a small shared platform layer):**
>
> ```text
> ORG layer — shared by design, persistent, FEW (read-only / advisory)
>   • Portfolio Manager  — cross-project queue/budgets/priorities (sees metadata, not code)   [optional]
>   • Security Auditor    — cross-cutting, read-only; WANTS the global view
>   • Knowledge/Librarian — shared standards, templates, post-mortems
>
> PER PRODUCT — one isolated pod, session-scoped to agent:<id>:<project>
>   • Lead / Orchestrator (persistent, 1)  — owns context+memory+human comms; decomposes & dispatches; NEVER edits code
>   └ Workers (EPHEMERAL — spawned per task, inherit the pod's session key)
>       • Implementer (was: programmer) — runs INSIDE the product workspace, so it knows the code
>       • Reviewer    — read-only veto, scoped to the diff
>       • Tester      — behaviour-only PASS/FAIL
> ```
>
> **Mapping from today's six specialists:** security + knowledge → stay **org-scoped persistent**
> (cross-cutting is correct); programmer/reviewer/tester → **project-scoped ephemeral roles** (same
> templates, different deployment); manager → splits into a **per-product Lead** (the common case) +
> an optional single **org Portfolio Manager**.
>
> **The constraint that shapes this phase (same as Phase 8):** docket is **not in the agent execution
> path** — the daemon spawns and runs agents. So the work splits:
>
> | Capability | Pure-docket? | How |
> | ---------- | ------------ | --- |
> | Scope axis on the taxonomy (org vs project) | ✅ yes | `AgentMeta` field + install/add provisioning + `list`/`doctor` |
> | Project-scoped role workers inherit the pod session key | ✅ yes | workspace provisioning + templates → **fixes Defect B** |
> | Lead merges manager; Implementer runs in the workspace | ✅ yes | templates + provisioning → **fixes Defect A** |
> | Ephemeral per-task spawning + runtime dispatch | ❌ daemon | needs OpenClaw sub-agent spawn / per-task session override → spike (AA-0), gated (AA-7) → **Defect C** |
>
> Work order de-risks the daemon dependency: **spike → taxonomy → provisioning (ships the isolation
> fix) → Lead/Implementer roles → org agents → dispatch (daemon-gated, isolated last) → list/doctor →
> docs.** Reuse, don't reinvent: the `AgentMeta`/`AgentKind` model, the `kind`/`role`/`modelSource`
> precedent, `core/sync.py`, `_create_workspace`, the role→model policy, and the Phase-8 trace for
> dispatch events.

#### 🟡 AA-0 — Spike: daemon capabilities for pods & ephemeral workers  *(blocking; do first)*

- **Why:** AA-7 (real dispatch) and the ephemeral-worker model hinge on what the OpenClaw daemon can do; everything else must not assume a capability that isn't there (the Defect-C trap that produced today's instruction-only "delegation").
- **Files:** scratch findings doc `internal-docs/POD-DAEMON-NOTES.md` (not shipped in the wheel).
- **Requirements:** Against `openclaw --help`, the live `~/.openclaw/openclaw.json`, and <https://docs.openclaw.ai/>, answer with evidence: (a) can the daemon **spawn a sub-agent / ephemeral agent** on demand, or are all agents statically registered? (b) can one agent **send a message / dispatch work** to another through the daemon (not just Telegram), and is that programmable from docket? (c) can a single registered role run **multiple concurrent isolated sessions** keyed by different session keys (the multi-tenant programmer question), or is session state per-agent-singleton? (d) how is a **per-task session** created/torn down? Record each as supported / not-supported / unknown, with the exact config or CLI that enables it. Explicitly decide the AA-7 path: **real daemon dispatch** vs **operator-driven queue** (documented honestly).
- **Acceptance:** `POD-DAEMON-NOTES.md` exists with a verified capability table and a one-line AA-7 verdict; at least one claim proven against the live daemon (e.g. a second session key on one role accepted, or shown impossible).
- **Test:** N/A (research). The doc is the deliverable; AA-2…AA-7 cite it.

#### 🟡 AA-1 — Add the `scope` axis to the taxonomy (the root fix)

- **Why:** Defect root cause — scope is conflated with role/kind. Make scope a first-class, validated field so "shared vs project-isolated" is data, not convention.
- **Files:** [src/docket/core/models.py](src/docket/core/models.py) (`AgentScope` enum + `scope` field on `AgentMeta`, alias-preserving; `AgentKind`/`ModelSource` are the precedent at lines 14/24/29), [src/docket/cli/_install.py](src/docket/cli/_install.py) + [src/docket/cli/__init__.py](src/docket/cli/__init__.py) (write it at creation), `specs/data/docket-meta.spec.md` (schema doc — keep spec↔model in sync per Phase 9 CDD-1).
- **Requirements:** `scope ∈ {org, project}` (default `project` for project agents; `org` for shared specialists). Validation rejects unknown values. Backfill rule for existing installs (lazy on read + a `doctor` fix): `kind==specialist` → derive from the role table in AA-2; `kind==project` → `project`. Document the field as `local` (docket-only) sync-class. Do **not** remove `kind`/`role` — `scope` is orthogonal to both.
- **Acceptance:** a new agent's `.docket-meta.json` carries a valid `scope`; an unknown `scope` is rejected at the boundary; existing metas without `scope` resolve to a correct value on read.
- **Test:** pytest: model round-trip + validation error for bad scope; backfill inference both ways.

#### 🟡 AA-2 — Reclassify the six specialists: org vs project-role

- **Why:** Fix Defect B at the source — only genuinely cross-cutting roles stay shared singletons.
- **Files:** [src/docket/config.py](src/docket/config.py) (`SPECIALIST_ROLES`/`SPECIALIST_ORDER` at lines 45-77 → split into `ORG_ROLES = {security, knowledge}` + `PROJECT_ROLES = {programmer, reviewer, tester}`; `manager` handled by AA-5/AA-6), [src/docket/cli/_install.py](src/docket/cli/_install.py) (`_provision_specialists` installs only the org set as shared workspaces).
- **Requirements:** `docket install` provisions **only** org-scoped agents (security, knowledge, + optional Portfolio Manager per AA-6) as shared singletons with `scope: org`. programmer/reviewer/tester are **no longer installed as global workspaces** — they become per-pod role templates instantiated by AA-3/AA-4. Migration: an existing install keeps its old specialist workspaces working (don't break running fleets) but `doctor` flags the project-roles as "to be re-scoped into pods" with guidance. Preserve the role→model policy mapping for every role regardless of scope.
- **Acceptance:** fresh `docket install` registers the org set only; `docket list --all` shows them with `scope: org`; no global `programmer`/`reviewer`/`tester` singleton is created on a clean install.
- **Test:** pytest/integration: clean install → org roles present, project-roles absent as singletons; existing-install migration path doesn't delete live workspaces.

#### 🟡 AA-3 — Pod provisioning in `docket add` + a configurable pod (decided 2026-06-23)

- **Why:** A project must come up as an isolated pod, not a lone agent told to delegate to a global singleton. But a full 4-agent pod is overkill (and over-cost) for many projects — so the pod is **configurable with a lean default**.
- **Pod composition (the options, made explicit):**
  - **Default (`docket add <project>`):** a **2-agent lean pod** — **Lead + Implementer**. The Lead orchestrates; the Implementer runs *in* the project workspace and writes code. This is enough to be useful and cheap.
  - **Extend later (`docket pod <project> add <role> [--count N]`):** add **Reviewer**, **Tester**, or **another Implementer** to an existing pod with one clear command. Roles may be **duplicated** — e.g. two Implementers — provisioned as indexed agent ids (`<project>-implementer`, `<project>-implementer-2`).
  - **Inspect (`docket pod <project>`):** show the pod's members, roles, models, scope.
  - **Opt-in full pod:** `docket add <project> --pod full` (or `--with reviewer,tester`) provisions the 4-role pod up front for those who want it.
- **Files:** [src/docket/cli/__init__.py](src/docket/cli/__init__.py) (`cmd_add` / `_create_workspace`, ~516-770; new `pod` command group), [src/docket/edges/adapters/openclaw.py](src/docket/edges/adapters/openclaw.py) (provision/teardown via `openclaw agents add --workspace` / `agents delete`), [src/docket/core/sync.py](src/docket/core/sync.py).
- **Requirements:** Per the AA-0 verdict, provision each pod member as a **distinct registered agent** (own workspace — the real isolation primitive), id `<project>-<role>[-N]`, `kind: project`, `scope: project`, `role: <lead|implementer|reviewer|tester>`, model from the role→model policy, session key in the `agent:<project>:…` namespace. The load-bearing guarantee: **no worker agent serves two projects.** One gateway restart per command. `docket delete <project>` tears down **every** pod member; `docket pod <project> remove <member-id>` removes one. Adding a role requires its template (AA-4/AA-5) to exist — refuse with a clear message otherwise.
- **Acceptance:** `docket add demo` yields a 2-member pod (`demo-lead`, `demo-implementer`), each `scope: project`, own workspace; `docket pod demo add implementer` creates `demo-implementer-2`; `docket pod demo add reviewer` adds a reviewer; `docket pod demo` lists them; `docket delete demo` removes all, both config sources clean.
- **Test:** integration: default add → 2 members with correct ids/scope/role + distinct workspaces; `pod add` (incl. duplicate implementer → indexed id); `pod remove`; delete → none remain, no orphan bindings.

#### 🟡 AA-4 — Project-scoped role templates (Implementer knows the code)

- **Why:** Fix Defect A — the role that implements must run *in* the project workspace with real context, not from a 500-token brief in a sandbox.
- **Files:** `src/docket/templates/docket-programmer.md` → an in-pod **Implementer** template; `docket-reviewer.md`, `docket-tester.md` re-scoped; the workspace-emission path in `_create_workspace`.
- **Requirements:** Re-author the three role templates as **pod members**: identity bound to the project + pod session key (inherit the workspace's `SOUL.md` context, not a compressed brief); the Implementer has read/write/edit on the project codebase (it *is* in the workspace) and the agreed git posture; Reviewer stays read-only veto on the diff; Tester stays behaviour-only PASS/FAIL. Remove the "shared specialist / `specialist:<role>:…` key" language and the sandbox-only/no-context framing. Bump the template version so `doctor` flags existing agents for `maintain rebuild`.
- **Acceptance:** a freshly added pod's role files reference the project + pod session key and contain **zero** "shared specialist" / hardcoded-`specialist:` language; the Implementer template grants in-workspace code access.
- **Test:** pytest: render each role template into a pod → asserts session-key/scope substitution and absence of the old singleton phrasing.

#### 🟡 AA-5 — The Lead role (merge project-agent + manager)

- **Why:** Collapse the "two doers" into one clear orchestrator per pod; the global Atlas manager becomes a per-product Lead.
- **Files:** `src/docket/templates/docket-manager.md` → reworked into a per-pod **Lead** template; project repo/task SOUL/AGENTS emission in [cli/__init__.py:533-643](src/docket/cli/__init__.py#L533).
- **Requirements:** The Lead is the persistent, project-scoped orchestrator: owns the pod's context/memory and human comms, decomposes work, dispatches to pod workers, and **never edits code** (keep the manager's no-edit/HITL constraints). It replaces the standalone "project agent that may implement OR delegate" — implementation is always a worker's job. The Lead's `role: lead`, `scope: project`, shares the pod session key. Keep `type` (repo/task) as the policy role for model resolution.
- **Acceptance:** an added pod has exactly one Lead with the no-edit constraint and the pod session key; the old "delegate → global programmer" instruction is gone from the project SOUL.
- **Test:** pytest: Lead template renders with no-edit constraint + pod session key; integration: added pod has one `role: lead` member.

#### 🟡 AA-6 — Org Portfolio Manager (optional, single)

- **Why:** Cross-product prioritization/budget needs *one* org view — but it must not be the per-pod bottleneck the single global Atlas is today.
- **Files:** [src/docket/cli/_install.py](src/docket/cli/_install.py), [src/docket/config.py](src/docket/config.py).
- **Requirements:** Optionally provision **one** `scope: org`, `role: portfolio-manager` agent that sees fleet metadata/queue/budgets (not project code). It does **not** dispatch into pods at runtime in v1 (that's AA-7/daemon); it's the cross-pod planning/visibility surface. Gate behind an install flag if you want it opt-in. Keep it distinct from per-pod Leads.
- **Acceptance:** with the flag, install creates one org Portfolio Manager visible in `docket list --all` with `scope: org`; without it, none exists and pods still function.
- **Test:** integration: flag on → one portfolio-manager; flag off → none; it never appears as a pod member.

#### 🟡 AA-7 — Real dispatch (DAEMON-gated; decision from AA-0)

- **Why:** Turn Defect C's instruction-only delegation into something reliable — *if* the daemon supports it; otherwise document the ceiling honestly instead of overclaiming.
- **Files:** [src/docket/serve.py](src/docket/serve.py) (dispatch loop), [src/docket/cli/__init__.py](src/docket/cli/__init__.py) (`team`/`TASK_LIST.json`), [src/docket/core/trace.py](src/docket/core/trace.py) (emit dispatch events, reuse Phase 8).
- **Requirements:** **If AA-0 says yes:** the `docket serve` loop reads the pod's `TASK_LIST.json`, dispatches each task to the right pod worker via the daemon (Lead → Implementer → Reviewer → Tester pipeline), collects completion markers, and emits trace events at each hop. **If AA-0 says no:** keep the queue + Lead as the operator-driven surface, file an upstream daemon-hook request, and **document** in help/README that runtime routing is operator-mediated (the Phase 8 honesty rule — no overclaiming inline enforcement). Either way, dispatch happens **within a pod** (shared session key), never across pods.
- **Acceptance:** (yes-path) a queued pod task is dispatched and traced end-to-end without manual Telegram relay; (no-path) docs state precisely that dispatch is operator-driven and the queue is the contract.
- **Test:** (yes) integration with a faked daemon dispatch → trace shows the pipeline; (no) docs grep audit asserts no "automatic routing" overclaim.

#### 🟡 AA-8 — `docket list` / `doctor` taxonomy view + migration

- **Why:** "What agents exist, what scope, what role, in which pod" must be answerable at a glance, and existing installs must migrate safely.
- **Files:** [src/docket/cli/__init__.py](src/docket/cli/__init__.py) (`list`), [src/docket/cli/_doctor.py](src/docket/cli/_doctor.py).
- **Requirements:** `docket list --all` gains SCOPE and POD columns (org agents listed once; pod members grouped under their project). `doctor` backfills `scope` for pre-Phase-10 metas (AA-1 rule), flags legacy global programmer/reviewer/tester singletons with the re-scope guidance from AA-2, and verifies pod members share one session key (drift check, reuse the Phase 9 pattern). `--fix` performs the safe backfills.
- **Acceptance:** on a pre-Phase-10 install, `doctor` backfills scope and flags legacy singletons; `list --all` renders the org/pod taxonomy correctly.
- **Test:** integration: meta-less-scope install → doctor backfills + flags; list groups pods.

#### 🟡 AA-9 — Docs / help / CLAUDE.md truth pass

- **Why:** The current docs describe the flawed shared-specialist model; they must teach the pod model and stay honest about pure-docket vs daemon-gated.
- **Files:** `CLAUDE.md` ("Agent Types" + architecture), `README.md`, `docs/` (WORKFLOW-GUIDE, DOCKET), [src/docket/cli/_help.py](src/docket/cli/_help.py).
- **Requirements:** Rewrite the agent-type narrative to **pods**: org-scoped shared agents (security, knowledge, optional Portfolio Manager) vs per-product pods (Lead + project-scoped Implementer/Reviewer/Tester). State plainly what's enforced by provisioning/isolation (scope, session-key inheritance) vs what's daemon-gated (runtime dispatch, per AA-7). Remove "specialists are shared resources that work across all projects" for the project-roles. Keep claims honest (no dollar-savings, no overclaimed runtime routing).
- **Acceptance:** `grep -ri "shared resource" CLAUDE.md docs/` no longer describes programmer/reviewer/tester as global; docs describe pods + the daemon caveat; tests green.
- **Test:** docs grep audit + `uv run pytest` green.

**Phase 10 exit criteria:** scope is a validated first-class axis on every agent; a clean install creates only org-scoped shared agents; `docket add` provisions an isolated pod whose Lead + Implementer/Reviewer/Tester share one session key (no shared singleton serves two projects); the Implementer runs in the project workspace (knower == builder); the single global Atlas manager is replaced by per-pod Leads + an optional org Portfolio Manager; runtime dispatch is either real-via-daemon or documented as operator-driven (never overclaimed); `docket list`/`doctor` show and migrate the org/pod taxonomy; docs teach the pod model honestly.

---

### PHASE 11 — Competitive differentiation (OpenClaw fleet-management space)  *(☑ COMPLETE 2026-06-25)*

> Source of record: `internal-docs/competitive-analysis.md` (deep-research pass + a
> GitHub-verified competitor sweep, 2026-06-25). Read it before claiming a CD-task — it has the
> full competitor map, the verified star counts, and the per-axis gap analysis. Executable board:
> [TODO.md](TODO.md).

**Why this phase.** A verified sweep of the OpenClaw-native ecosystem shows it is **crowded but
bifurcated**: monitoring *dashboards* (read side — `builderz-labs/mission-control` ~5.4k★,
`abhi1693/openclaw-mission-control` ~4.1k★, plus several `openclaw-dashboard`s) and one-shot *setup
scripts* (`shenhao-stu/openclaw-agents` ~445★). The **only** true CLI lifecycle+governance peer is
`oguzhnatly/fleet` — and it's ~13★, written in Bash, with no pods / role→model cost policy /
workspace isolation. The broader category (OpenHands, Cursor, Codex, E2B/Modal, Conductor, Bernstein)
confirms three things the field treats as **unsolved**: (1) runtime-resource isolation between
parallel agents (ports, scratch DBs, caches), (2) anti-fragile *shared* context for multi-agent work
(Cognition's "Don't Build Multi-Agents"), (3) a real HITL/audit/approval spine. docket already owns
(2) via Lead-owned context + session scoping, and has the bones of (3). This phase doubles down on
the trio no inner- or outer-ring competitor integrates, and closes the two most visible gaps
(no dashboard-feed API; gates are opt-in / Telegram-only).

**The bet (one line):** docket is the *governed, coordinated, isolated* control plane on the **write
side** — it should **feed** the dashboards, not try to out-UI them, and lead on **pod-level resource
isolation (CD-1), a real verification gate (CD-2), and on-by-default governance (CD-3/CD-4)**.

**Cards (detail + acceptance in [TODO.md](TODO.md)):**
- **CD-0** — Confirm the live `openclaw agent --json` result schema (esp. cost) and tighten
  `agent_run` parsing. *(carried-forward AA-0 follow-up; unblocks honest cost in CD-1/CD-2.)*
- **CD-1** — **Pod-level runtime-resource isolation** (allocated port range + scratch data dir per
  pod, injected into the Implementer's env). *Flagship — attacks the field's acknowledged unsolved
  problem; pure provisioning, no daemon change.*
- **CD-2** — **Deterministic pre-merge verification gate** (run the project's lint/type/test command
  via the system adapter; hard-fail the hop on non-zero). Turns "Tester agent says ok" into "tests
  passed." Matches Bernstein's Janitor bar.
- **CD-3** — **High-risk action classes** in the policy engine (money / prod-deploy / secret-access
  → *always* route to approval, regardless of allowlist).
- **CD-4** — **Headless approval channel** (web/CLI/webhook) so gates can finally be recommended
  on-by-default for non-Telegram operators (unblocks the long-deferred "Phase 0 gates default-on").
- **CD-5** — **Git-worktree-native Implementer isolation** for repo pods (the convergent industry
  pattern; composes with CD-1). *Daemon-path sensitive — validate first.*
- **CD-6** — **Scheduled & webhook-triggered dispatch** in `serve` (cron + inbound webhook →
  OpenHands Automation-Server parity; turns the poller into an event-driven control plane).
- **CD-7** — **Lobster workflow validate + dry-run/plan** (narrow the gap to Conductor without
  claiming docket executes the workflow).
- **CD-8** — **Stable read API + minimal status surface** so docket *feeds* the dashboard cluster
  rather than competing on UI (harden `serve`'s `/status.json`/`/metrics`, document the contract,
  optional single-file HTML).
- **CD-9** — **Positioning/docs truth pass**: lead with coordinated-context + isolation; add
  "ops layer, not a framework" (vs CrewAI/LangGraph) and "governed fleet, not a solo assistant"
  (vs raw openclaw) lines; keep the no-dollar-savings discipline as a *trust* differentiator.

**Phase 11 exit criteria:** a pod gets isolated runtime resources (CD-1); a pod task cannot be marked
done unless a mechanical verification gate passes (CD-2); high-risk actions always require approval
and there is at least one headless approval channel so gates can ship on-by-default (CD-3/CD-4);
`serve` can be triggered on a schedule/webhook and exposes a documented read API a dashboard can
consume (CD-6/CD-8); public docs lead with the verified differentiators and make no unfalsifiable
claims (CD-9). Out of scope (→ §7 Backlog): a full web UI of our own, microVM/gVisor isolation,
multi-host/remote provisioning, cross-runtime (non-OpenClaw) adapters.

> **☑ Phase 11 shipped 2026-06-25 — all cards CD-0…CD-9 DONE, full suite green (693 passed).**
> Every exit criterion above was met: disjoint per-pod runtime resources with reclaim (CD-1),
> git-worktree Implementer isolation with documented fallback (CD-5), the `verifyCmd` mechanical
> gate blocking task-done on failure (CD-2), always-approve high-risk policy classes (CD-3), the
> headless `serve` approval channel unblocking gates-default-on (CD-4), scheduled + webhook
> dispatch (CD-6), Lobster `validate`/`plan` without execution overclaim (CD-7), the versioned
> read API pinned by `specs/data/serve-read-api.spec.md` (CD-8), and the positioning truth pass
> (CD-9). The TODO board was cleared per convention; this note is the durable record.

---

### PHASE 12 — Consolidation & hardening  *(🟠 active — audit-driven; work the board in TODO.md)*

> **Source of record:** `internal-docs/architecture-audit.md` (2026-07-02 full-repo audit — four
> parallel passes over architecture invariants, docs↔code sync, feature value, and dead
> code/hardcoded data; every finding carries file:line evidence). Read it before claiming a
> CH-card. Executable board: [TODO.md](TODO.md).

**Why this phase.** Eleven phases of feature work landed with the architecture *mostly* honest:
the audit confirmed the cli→core→edges direction holds (nothing in core/edges imports cli) and
the ACL really is the only OpenClaw-format parser. But it also found (a) **invariant breaches** —
`.docket-meta.json`/registry writes bypassing `store.py` with the atomic-write dance hand-copied
8+ times, raw `openclaw` shell-outs outside the ACL, `core/provider.py` printing Rich UI from the
domain layer; (b) **a 4,194-line `cli/__init__.py`** (32% of the codebase); (c) **carried features
that no longer earn their keep** — `core/drift.py` (one caller, feeds an unimplemented
notification), the legacy `team` manual queue (no dispatcher; pods own delegation), hand-written
completions already drifted, overdue tier/`profiles:` deprecation shims, three dead template
files; (d) **docs/specs drifted from the CLI** — 8 commands missing from the command reference,
wrong extensions/exit codes/state names in specs, contradictory test counts, a changelog missing
Phases 10–11; and (e) **broken Bash-era scripts still wired into CI** (`spec-coverage.sh`,
`metrics.sh` count the deleted `lib/` tree — which is why the README drift-guard went blind).

**The bet (one line):** before any new capability, make the codebase *match its own documentation
and principles* — one JSON chokepoint, one OpenClaw boundary, one delegation system, specs that
are current-state contracts rather than historical patches, and a re-armed drift guard so it
stays that way.

**Cards (detail + acceptance in [TODO.md](TODO.md)):** CH-0 quick truth/dead-file sweep · CH-1
store.py single-writer rule (D-12) · CH-2 `openclaw` shell-outs behind the ACL · CH-3 core/edges
UI-printing violations · CH-4 retire `team` (D-11) · CH-5 delete `core/drift.py` · CH-6 remove
tier/`profiles:` shims (D-2 exit) · CH-7 split `cli/__init__.py` · CH-8 drift-proof completions ·
CH-9 fix/retire Bash-era scripts + re-arm the CI drift guard · CH-10 spec (SDD) truth pass ·
CH-11 docs completeness pass · CH-12 changelog backfill + 0.2.0 prep · CH-13 local test-harness
hygiene.

**Explicit keeps (audited, do NOT cut):** the ACL + `store.py` + dual-source `sync.py` (documented
architecture); the audit log, approval store, and opt-in gates (substrate of CD-3/CD-4); the
`serve` read API incl. `/metrics` and scheduled/webhook dispatch (CD-6/CD-8 differentiators,
spec-pinned); Lobster `validate`/`plan` (CD-7); `resources.py` (small, CD-1 substrate); the
`policy.py`/`models_policy.py`/`provider.py` trio (distinct concerns — naming, not duplication).

**Phase 12 exit criteria:** zero docket-owned JSON writes outside `store.py` (except the named
JSONL exemption, D-12); zero `openclaw` shell-outs outside the ACL; zero `ui` imports in
`core/`/`edges/`; no module over ~1,500 lines in `cli/`; `team`, `drift.py`, tier/`profiles:`
shims and the three dead templates gone (with removed-command notices where user-facing);
`docs/commands.md` covers every live command and flag; every spec's Status line and contract
matches code (extension, exit codes, state strings); CHANGELOG documents Phases 10–11 and cuts
0.2.0; the README-numbers drift guard runs green in CI against the Python tree; full suite +
goldens green throughout.

---

## 7. Backlog (deferred indefinitely)

- New channel auth flows (Discord OAuth, Slack app install) — OpenClaw owns this entirely; docket just writes bindings.
- Rewrite in Go/TS — no benefit until docket reaches complexity that Bash can't handle.
- Multi-tenant agent sharing — requires identity layer not present in OpenClaw today.
- **A full web UI / dashboard of our own** (deferred from Phase 11) — the OpenClaw space already has
  4–5k★ mission-control UIs; docket competes on the *write/governance* side and **feeds** them via a
  read API (Phase 11 CD-8) rather than building a worse dashboard.
- **microVM / gVisor workspace isolation** (deferred from Phase 11) — competitors running *untrusted*
  code use Firecracker (E2B/Vercel) or gVisor (Modal); docket's optional Docker shares the host
  kernel. Revisit only if docket targets untrusted-code execution; large lift.
- **Multi-host / remote provisioning** (deferred from Phase 11) — manage agents across more than one
  daemon/host (OpenHands-style). The ceiling on the "fleet" claim; defer until single-host value is
  saturated.
- **Cross-runtime (non-OpenClaw) adapters** (deferred from Phase 11) — Fleet/builderz-labs span
  Claude Code/Codex/CrewAI/etc. A trend to watch, not a near-term bet; docket stays OpenClaw-anchored.

---

## 8. How to start (current — Phase 12)

Phases 0–11 are complete (§5 + the Phase 10/11 records). The active work is **Phase 12 —
Consolidation & hardening**; read `internal-docs/architecture-audit.md` first (the audit every
CH-card traces back to), then claim tasks from [TODO.md](TODO.md).

```bash
git checkout -b pc/ch-0-truth-sweep          # one branch per CH-task
# CH-0 first — cheap, zero-risk truth fixes; independent of everything else.
uv run pytest                                # baseline green before you start
# ...do the task, add tests, then:
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
bash tests/golden/run.sh verify-all          # byte-parity net
git commit -m "Fix: CH-0 — truth sweep (stale claims, dead templates, dangling pointers)"
```

Work CH-tasks **in dependency order** (the map is at the top of TODO.md): the independent cards
(CH-0, CH-5, CH-9, CH-13) any time; the invariant repairs (CH-1/CH-2/CH-3) in parallel; the
surface changes (CH-4 team, CH-6 shims) **before** the module split (CH-7) and before the
completions/spec/docs cards (CH-8/CH-10/CH-11); CH-12 (changelog + 0.2.0) last. When a decision
blocks you, record it (§6 pattern) and apply the documented default.

---

### Changelog

- **2026-07-02** — **Marked PHASE 11 complete** (CD-0…CD-9 all DONE 2026-06-25, suite green at 693;
  durable record added to the Phase 11 section, TODO board cleared per convention) and **added
  PHASE 12 — Consolidation & hardening** (CH-0…CH-13), driven by `internal-docs/architecture-audit.md`
  (2026-07-02: four parallel audit passes — architecture invariants, docs↔code sync, feature value,
  dead code/hardcoded data). Verified findings baked into the plan: store.py bypassed by
  `.docket-meta.json`/registry writes (atomic-write logic hand-copied 8+×), raw `openclaw` shell-outs
  outside the ACL, `core/provider.py` printing UI from the domain layer, `cli/__init__.py` at 4,194
  lines, `core/drift.py` with one caller feeding an unimplemented notification, the legacy `team`
  queue duplicating pod dispatch with no dispatcher, drifted hand-written completions, overdue D-2
  deprecation shims, 3 dead templates, 8 commands missing from docs/commands.md, spec/code mismatches
  (workflow extension + exit codes, team done-state), contradictory test counts (416/694 vs actual
  688), and the Bash-era `scripts/spec-coverage.sh`/`metrics.sh` still in CI while counting the
  deleted `lib/` tree. Decisions D-11 (retire `team` → pods) and D-12 (store.py single-writer rule,
  JSONL logs exempt) added. Explicit keeps recorded so the phase doesn't over-cut: the CD-6/7/8
  differentiators, ACL/store/sync, audit+approval, `resources.py`, and the policy/models_policy/
  provider trio (naming collision, not duplication).
- **2026-06-25** — **Added PHASE 11 — Competitive differentiation**, and marked Phase 10 complete in
  the status header. Driven by `internal-docs/competitive-analysis.md`: a deep-research pass (12
  sources, load-bearing claims re-fetched and confirmed verbatim) + a **GitHub-verified** sweep of the
  OpenClaw-native ecosystem. Findings: the space is bifurcated into monitoring dashboards
  (`builderz-labs/mission-control` ~5.4k★, `abhi1693/openclaw-mission-control` ~4.1k★, several
  `openclaw-dashboard`s) and setup scripts (`shenhao-stu/openclaw-agents` ~445★); the only true CLI
  lifecycle+governance peer is `oguzhnatly/fleet` (~13★, Bash, no pods/cost-policy/isolation). The
  broader field treats three things as unsolved — runtime-resource isolation, anti-fragile shared
  context, and a real HITL/audit spine — and docket already owns the second. Phase 11 cards CD-0…CD-9
  double down on the trio and close the two visible gaps (no dashboard-feed API; gates opt-in /
  Telegram-only). Backlog gained explicit deferrals: own web UI, microVM/gVisor isolation, multi-host,
  cross-runtime adapters. The deferred "Phase 0 gates default-on flip" is now sequenced under CD-4.
- **2026-06-24** — **Repointed stale `lib/` references to the Python layout.** Converted the
  now-dead clickable `lib/commands/*.sh`, `lib/helpers/*.sh`, `lib/core/*.sh`, and
  `tests/test-lifecycle.sh` markdown links (deleted in the M6 Bash→Python cutover) to plain text
  and annotated each with its current `src/docket/` location (`cli/` Typer commands, `core/`
  domain, `edges/` I/O incl. the ACL + `store.py`; tests now pytest under `tests/python/` + the
  golden suite). Historical phase content and plan meaning unchanged — only file pointers corrected.
- **2026-06-23** — **Consolidation + PHASE 10 added.** Folded the three standalone planning docs into
  this roadmap and removed them: `ARCHITECTURE-AUDIT.md` (language verdict — *migrate to Python* —
  executed by M6; build-vs-wrap + the language reasoning survive in §4.5/§0), `MIGRATION-PLAN-PYTHON.md`
  and `MIGRATION-TASKS.md` (the Bash→Python strangler-fig plan + task board — fully shipped; recorded in
  §0). Refreshed the stale Bash ground-truth (§2) and conventions (§3) to the Python three-layer/ACL
  reality; added §0 (completed migration) and §4.5 (durable architectural principles + anti-overengineering
  guardrails). **Added PHASE 10 — Agent architecture (pods)** (AA-0 … AA-9): fixes the three structural
  defects in the agent model — (A) "two doers" split between project agent and shared programmer, (B)
  shared specialist singletons break the session-key isolation guarantee, (C) "delegation" is instruction-only
  with no runtime. Plan: make **scope** a first-class axis (org vs project), reclassify the six specialists
  (security/knowledge → org; programmer/reviewer/tester → project-scoped pod roles; manager → per-pod Lead +
  optional org Portfolio Manager), provision each project as an isolated **pod** sharing one session key, and
  gate runtime dispatch behind a daemon-capability spike (AA-0). Executable cards in
  [TODO.md](TODO.md); rationale in `internal-docs/agent-structure-analysis.md`.
- **2026-06-22** — **PHASE 9 complete** (CDD-1 … CDD-6) *(pre-migration Bash paths below; the schema/validation/doctor logic now lives in `src/docket/core/` + `src/docket/cli/`)*: `lib/core/schema.sh` declares the full
  `.docket-meta.json` field set once (name/type/enum/sync-class); `meta_set` validates every write
  against it (unknown field → error, type mismatch → error, enum violation → error); `docket doctor`
  now diffs all `synced` fields (model + sessionKey) not just model, and `--fix` re-syncs from
  `.docket-meta.json`; phantom `{success,data,error,version}` envelope removed from spec, real per-
  command shapes documented in `specs/data/cli-json-shapes.spec.md`; `scripts/spec-coverage.sh`
  rewritten as a mechanical linter (router.sh case arms vs cli-interface.spec.md headings, exits 1
  on mismatch); spec de-staled — gates/audit/eval/models/completions/telegram/trace/metrics/
  policies/approve/deny added, profile tier-as-arg corrected to model-id/`default`, reset/repair
  stale "Used By" entries removed. 17 new unit tests; 325 total, all green.
- **2026-06-22** — Added **PHASE 9 — Contract integrity / de-ceremony** (CDD-1 … CDD-6), from a
  Contract-/Schema-Driven-Development audit. Scope-corrected the generic web-CDD brief to docket's
  reality: no OpenAPI/DB/codegen exist (so the "dead codegen loop" and "migration rigor" pillars
  are N/A by construction), so the audit targets docket's three real contracts — the markdown
  specs, the dual-source `.docket-meta.json` ↔ `openclaw.json` config, and the `--json`/HTTP
  shapes. Verified findings: the spec's `{success,data,error,version}` JSON envelope is emitted by
  **zero** commands (cli-interface.spec.md:340 vs no `"success"` in lib/commands/); `docket doctor`
  drift checks **only** `model` (doctor.sh:187-197/515-526) so budget/paused/modelSource drift
  silently; `_meta_set` does no type/enum validation; `spec-coverage.sh` scores presence not
  contract conformance; `gates`/`audit`/`eval`/`models`/`completions` are missing from the spec
  registry and `reset`/`repair` linger as live in input-validation.spec.md. Decisions D-9/D-10
  added. (This consolidated doc is now the roadmap.)
- **2026-06-22** — Added **PHASE 8 — Agent observability, guardrails & drift (HITL)** (OBS-0 …
  OBS-12), derived from the durable-trace / gated-destructive-action / guardrailed-untrusted-input /
  self-surfacing-drift spec (goals G1–G5) and an audit of the current cost, gates, Telegram, serve,
  task-queue and test subsystems. Key finding baked into the plan: **docket is not in the agent
  execution path** (the OpenClaw daemon executes tool calls), so the phase is sequenced
  observability (pure docket, ships first) → policy engine (pure, testable) → enforcement+HITL
  (the only hard daemon dependency, isolated) → drift. Collisions resolved: spec's `docket audit`
  → `docket trace export` (existing `audit` = operator-mutation log kept); `$DOCKET_HOME` aliased
  to `OPENCLAW_DIR`; per-run `session_id` derivation deferred to the OBS-0 spike. Spec open
  questions Q1–Q3 resolved as decisions D-6…D-8. Non-goals (no OTel/Prometheus/DB, no ML v1, no
  RBAC, filesystem-is-the-store) recorded as hard guardrails.
- **2026-06-12** — **PHASE 6b complete** (MA-9 ✅ MA-10 ✅ MA-11 ✅): `ROLE_MODELS`/`ROLE_WHY`
  policy in config.sh with registry `roles:` overlay (legacy `profiles:` still re-derives);
  `docket models` shows ROLE|MODEL|PRICE|SOURCE|WHY and `set <role>` / presets / reset all
  auto re-resolve policy-followers (`reapply_role_policy`, pins untouched, one restart,
  audit-logged); `.docket-meta.json` gains `kind` + `modelSource` (policy|pinned) with lazy
  inference for pre-existing agents (model ≠ policy → pinned, so nothing silently
  downgrades); `docket profile` is now pin/`default` semantics and covers specialists;
  install.sh resolves specialists through the policy and stamps their meta; doctor
  backfills taxonomy metadata; delete guards specialists; tier names everywhere are
  deprecated aliases with warnings; templates tier-neutral (TEMPLATE_VERSION=3); eval
  recommendations rephrased to role-policy actions; README/CLAUDE.md/docs/commands.md
  (incl. new `### models` section)/QUICK-START/DOCKET.md/WORKFLOW-GUIDE updated.
  Tests: 241 unit (18 new MA-9/MA-10) + 63 integration, all green.
- **2026-06-11** — Added PHASE 6b — Tier-less role→model policy (MA-9 … MA-11): unified
  agent/model architecture decided with user — tiers removed from UX (deprecated aliases
  only); global-only role→model policy map with per-role WHY, defaults picked for token
  efficiency (manager/reviewer/tester/knowledge/task on the cheap class, programmer/
  security/repo on the strong class, opus-class = explicit pin); agents store intent
  (`modelSource: policy|pinned`) and `docket models set/preset` auto re-resolves
  policy-followers; specialists join the `.docket-meta.json` system (`kind`/`role`, one
  taxonomy in `docket list`). Deferred: `docket models optimize` (eval × cost-history
  right-sizing, later phase) and per-task dynamic routing (needs daemon spike). Closes
  the install.sh hardcoded-specialist-models and model-drift gaps left open by Phase 6.
- **2026-06-11** — Added PHASE 6 — Model & provider agnosticism (MA-1 … MA-8, 🔴 critical):
  remove the hard Claude-API dependency; model registry, `docket models` command, provider
  presets incl. free/local, cost honesty, key plumbing, template + docs neutralization.
  (Phase 6 of this roadmap; the former "Product & community" is Phase 7.)
  Claude-dependency inventory verified against source this date.
- **2026-06-08** — Initial executable plan derived from the v2 product plan and source review. `agents.list` confirmed against live `~/.openclaw/openclaw.json`.
