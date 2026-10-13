# Completed phase records (archived from ROADMAP.md)

Phases 0–22 and the Bash→Python migration, preserved **verbatim** from `ROADMAP.md`. Each phase is
written in the present tense of its own moment because the reasoning is the durable part. Phases
0–9 were authored against the Bash codebase (`lib/**/*.sh` paths refer to a tree deleted in M6);
phases 10–18 predate D-19 and describe a core that still wrapped an external daemon. Where a phase
here contradicts `ROADMAP.md` §2, §2 wins. Verified by `manifest.json` in this directory.

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

## 5. Phase records (historical — every phase below is COMPLETE)

> **This is not a task list.** It was one, once; the name "The TODO" survived long after the work
> did. **Nothing in this section is outstanding** — see the status table at the top of the file.
>
> Each phase is preserved as written, in the present tense of its own moment, because the
> *reasoning* is the durable part: why a thing was built, what was deliberately narrowed, and which
> assumptions turned out wrong. Two conventions to read it with:
>
> - **Phases 0–9 were authored against the Bash codebase.** Their `lib/**/*.sh` paths refer to a tree
>   deleted in M6. Inline `(pre-migration Bash; now …)` notes point at the Python successor.
> - **Phases 10–18 predate D-19**, so they describe a Python core that still wrapped an external
>   daemon behind an Anti-Corruption Layer. That layer is gone too. **Where a phase below contradicts
>   §2, §2 wins.**

### PHASE 0 — Truth & correctness  *(☑ COMPLETE — blocking at the time; nothing else shipped first)*

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

### PHASE 1 — Cost enforcement  *(☑ COMPLETE — the real differentiator at the time)*

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

### PHASE 2 — Finish consolidation & resolve "smart routing"  *(☑ COMPLETE)*

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

### PHASE 3 — Park experiments & finish the edges  *(☑ COMPLETE)*

#### ☑ P3-1 — Move `terminal` (584 LOC) and `browser` (260 LOC) to `experimental/`

- **Requirements:** Create `lib/commands/experimental/`; move files; gate behind `DOCKET_EXPERIMENTAL=1` or a clear "experimental" warning. Fold browser *health* into `doctor` (it already partly is, doctor.sh:114-133). (pre-migration Bash paths; commands now live under `src/docket/cli/`)
- **Acceptance:** Core help no longer lists experimental commands as first-class; they still work when explicitly enabled.

#### ☑ P3-2 — Telegram: finish or document-as-manual

- **Requirements:** Either complete group auto-creation or update docs to "manual wire only" and make `wire` the single supported path. No 🚧 left in README.
- **Acceptance:** README status table has zero 🚧.

**Phase 3 exit:** zero half-features in the main path; README honest.

---

### PHASE 4 — Strengthen & extend  *(☑ COMPLETE)*

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

## PHASE 19 — docket takes the runtime (D-19)  *(☑ COMPLETE — all 13 cards, waves 8–11, closed 2026-08-03)*

> **This section was written retroactively on 2026-08-05**, because the phase that changed docket
> most had no section at all — only scattered references and a record in TODO.md. The per-card
> detail lives in TODO.md's wave 8–11 blocks and in §Changelog; this is the durable summary.

**The decision (D-19): own the loop, rent the protocols.** A clean break — no daemon compatibility
layer, no migration path. docket now owns the turn loop, the tool registry, all three policy hooks,
approvals, audit and sessions. It rents only protocols: an OpenAI-compatible HTTP endpoint (stdlib
`urllib`, zero new deps), MCP for pluggable tool servers, and containers for isolation.

**Why it had to happen, and this is the durable lesson.** docket shipped four `pre_tool_call` policy
templates that had **never once been evaluated**, because the external daemon owned the inside of a
turn. The wrap boundary was not merely limiting the roadmap — it was making the product's central
claim false. *Whoever owns the loop owns the interception points.* That is also why agent frameworks
(LangGraph/CrewAI/AutoGen) are rejected on principle: they own the loop, and therefore the gates.
See §4.5's build-vs-wrap box, which records the reversal rather than deleting the old reasoning.

**The 13 cards:**

| Card | What it delivered |
| --- | --- |
| P19-1 | `core/llm.py` chat port + `edges/adapters/llm.py` — the only module that knows the wire format |
| P19-2 | `core/tools.py` — **the gated tool registry and the single chokepoint** |
| P19-3 | Turned on `pre_tool_call` — the hook whose templates had never run |
| P19-4 | `core/session.py` — durable turn history + compaction that never splits a tool-call/result pair |
| P19-5 | `core/agent_loop.py` + `DocketDriver` — the bounded turn loop |
| P19-6 | docket-native home (`~/.docket`) + fleet registry, single writer |
| P19-7a/b | **The runtime cutover** — the removal spine; `restart_gateway()` and ~15 ceremonial call sites deleted |
| P19-8 | **docket-owned Telegram** — a real approval channel, writing `channel="telegram"` to the audit chain |
| P19-9 | Sandboxed exec for `bash` (docker/bwrap argv) |
| P19-10 | MCP client — pluggable tool servers, gated like a built-in |
| P19-11 | `fetch` tool — domain-allowlisted, **deny-by-default** (D-23 re-scoped: ship `fetch`, defer the lockdown) |
| P19-12 | Per-role tool sets + identity composition — `denied_tools` as **data**, making a Reviewer *unable* to write |
| P19-13 | `docket mcp servers` CLI |

**Acceptance test for the whole phase:** `command grep -ril openclaw src/` returns only comments and
docstrings narrating the removal — zero live string literals.

**What the phase made true:** the four never-evaluated policy templates are live, and Telegram became
a real approval channel — reversing a caveat carried since Phase 15.

**Two of its cards left wires unfinished, and both were closed later** — recorded here because the
pattern repeated: **P19-10 shipped `load_mcp_tools` as a tested but never-called library** (closed by
W17-1, 2026-08-05), and P19-9's sandbox was likewise reachable only if something set
`ToolContext.sandbox`, which nothing did (closed by W18-3, same day). *Machinery implemented, tested,
and not wired to the default path* is this phase's characteristic failure mode — see CLAUDE.md's
review heuristic.

---

## PHASE 20 — Fleet observability  *(☑ COMPLETE at cut scope — D-24 cut ~half; P20-2 shipped, P20-4 was a phantom card)*

**Why after, not before.** Instrumenting code that P19-7 is about to delete is waste. Phase 20
starts once the daemon is gone and the shapes are final.

**Scope after D-24: two small cards, not four.** P20-1 (OpenTelemetry) is **cut** and P20-3 (fleet
trace query + retention) is **deferred**; what remains is P20-2 and P20-4, both S-or-smaller. The
gap list below is kept in full because the gaps are real — being deferred is not the same as being
untrue, and a future trigger should find the measurement already written down.

**What already exists** (do not rebuild it): per-project/session JSONL traces with hop *and*
per-tool-call events (`docket trace`), a hash-chained tamper-evident audit log (`docket audit
verify`), a dispatch run registry with cancellation (`docket runs`), six Prometheus metrics and a
versioned read API (`/status.json`, `/health`, `/runs`, `/runs/<id>`, `/approvals`), token/cost
reporting (`docket cost`), session success-rate metrics (`docket metrics`), and fleet diagnostics
(`docket doctor`). That is a stronger base than either LangGraph or CrewAI ships by default, because
it was built for unattended operation.

**The measured gaps:**

1. **No fleet-wide view.** Traces are per-project files; there is no "every denied tool call across
   all pods this week".
2. **No OpenTelemetry.** The industry standard is absent, so nothing feeds Grafana/Jaeger/Honeycomb
   without docket building a UI it would then have to maintain.
3. ~~**The P19-5 loop is not in the metrics.**~~ — **closed by P20-2** (wave 13): tool-call rate,
   denial rate, approvals by channel and policy-hit counts by id are all exported.
4. **No latency anywhere.** No p50/p95 per role — a slow model and a stuck agent look identical.
   **Partly closed by P20-2**, which exports `docket_turn_duration_seconds` as a `_sum`/`_count`
   summary. Percentiles are still absent, and deliberately so: only `session_start`/`session_end`
   brackets exist, so a p95 would be invented rather than measured. Real percentiles need a
   per-turn timestamp that nothing records yet.
5. ~~`docket runs cancel` still writes **no audit entry**~~ — **already closed by W-4** (`7e9ddab`,
   2026-07-30), which shipped the entry, four tests and the spec bump on the *same day* this gap
   list was written. Recorded as open here, and again as card P20-4 below, because neither was
   re-trued afterwards. The gap was never real; see P20-4.
6. **No trace retention policy.** JSONL grows without bound.
7. **No agent-quality regression detection** — the eval harness is non-blocking spot checks.

**The design rule for this phase: emit spans, do not build a dashboard.** Model one turn as
`turn -> iteration -> tool_call` with the gate decision as a span attribute, export OTLP, and every
existing observability tool works. **Keep telemetry and the audit log separate** — telemetry is
sampled and lossy by design, an audit log must be neither. Conflating them is a common and serious
mistake.

**Golden signals for an agent fleet** (what the metrics cards must cover): turn latency, tool-call
rate, **denial rate**, **approval wait time**, token burn rate, and **cost per completed task** —
per *task*, not per agent, because that is the number that means something.

### Cards

**P20-1 · OpenTelemetry spans + OTLP export** — *❌ CUT (D-24)*
Was: a `turn -> iteration -> tool_call` span tree with the gate decision as an attribute, exported
OTLP. **Cut, reversing the same-day recommendation that proposed it.** The design advice behind it
stays correct — *emit spans, do not build a dashboard* — but it is advice for a fleet with more than
one operator and somewhere to send the spans. docket has JSONL traces carrying hop **and** per-tool-call
events, plus six Prometheus metrics and a versioned read API. **Trigger to re-open:** a second
operator, or a real Grafana/Jaeger/Honeycomb backend that someone will actually watch. Not "it is
the industry standard".

**P20-2 · Guardrail + loop metrics** — *☑ SHIPPED (2026-08-04, wave 13) · S*
Denial rate, approvals granted/denied/timed-out **by channel**, policy-hit counts by policy id,
tool-call rate, turn latency. Extends the existing Prometheus surface; **no new endpoint** and no new
dependency. These are the numbers an operator opens after an incident, which is why this survived the
cut that removed OTel: it is the *signal*, without the *transport project*.

Shipped as four families — `docket_tool_calls_total{decision}`, `docket_policy_hits_total{policy_id,
hook,action}`, `docket_approvals_total{channel,outcome}`, and `docket_turn_duration_seconds` (a
summary with **no** quantiles; there is no per-turn timestamp to build honest percentiles from, only
`session_start`/`session_end` brackets).

**The design call worth keeping:** every number is recomputed from durable records at scrape time —
trace JSONL for tool calls, policy hits and session brackets; the audit log for approvals by channel.
`docket serve` is not a long-lived process holding counters, so an in-memory store would silently
zero on restart and a persisted one would be a second source of truth free to drift from what is on
disk. Deriving means every metric is traceable back to a record an operator can `grep`. Telemetry
still never writes *through* the audit log — it only reads it.

**One `core/tools.py` change, scoped exactly:** `_audit_tool_decision` now takes `policy_id`/
`policy_action` as structured keyword fields instead of burying the hit in free text, so `/metrics`
can attribute a policy hit by id without parsing prose. `evaluate_tool_call` — the gate itself — is
untouched: no decision changes, no second execution path, no reordering of the classifier/policy
sequence, and `audit_log` stays best-effort and never-raising, so recording cannot affect whether a
tool runs.

**Two limits documented rather than implied.** (1) `audit.log` rotates at `AUDIT_LOG_MAX_BYTES` to a
single-generation backup and `read_audit` sees only the current file, so `docket_approvals_total` and
the `pre_tool_call` slice of `docket_policy_hits_total` **lose history on rotation** — and a counter
dropping to a *partial* value is misread by `rate()` as a reset plus real traffic. Fixing that is
retention design, which is P20-3's deferred scope. (2) Scrape cost was **measured, not asserted**: a
927KB / 10,000-event trace corpus plus an audit log at the 5MB ceiling renders in ~60ms. Fine today,
`O(trace + audit bytes)`, no cache added, threshold named.

**P20-3 · Fleet trace query + retention** — *⏸ DEFERRED (D-24)*
Cross-project query (`docket trace --fleet --json`) plus a documented retention/rotation policy, the
way `AUDIT_LOG_MAX_BYTES` already handles the audit log. Both gaps are real; neither is felt yet at
this fleet size, where `grep` over per-project JSONL answers the question. **Trigger:** a disk that
actually fills, or a cross-pod question asked twice.

**P20-4 · `runs cancel` audit entry** — *☑ NO-OP (2026-08-03) · the gap was already closed*
Was: closes the W-4 gap — a cancellation is a human decision that killed running work, so it belongs
in the audit log.

**It was already there.** Dispatched in wave 13 and the agent found the work shipped: `core/runs.py`'s
`cancel_run` has written `audit_log("runs.cancel", run=… project=… was=… killed=…)` since **W-4**
(`7e9ddab`, merged 2026-07-30), with four tests in `test_runs_cli.py::TestRunsCancelAuditEntry`
(entry on success · none on unknown id · none on already-terminal · chain still verifies) and the
change recorded in `audit.spec.md`'s own 2.3.0 changelog. **Zero commits on `pc/p20-4`.**

**Why the board was wrong, which is the part worth keeping.** W-4 closed the gap on 2026-07-30 —
the same day Phase 20's gap list was written recording it as open. The gap list was never re-read
against the tree afterwards, so the false entry was promoted into a card, survived D-24's
prioritization pass (where it was *kept* over OpenTelemetry on the strength of a premise nobody
re-checked), and was scheduled into a wave. **A gap list is a claim about the tree and decays like
any other; re-verify one before you schedule work against it, not after.** The card cost one agent
dispatch to disprove — cheap, but only because the agent checked instead of building a second
`audit_log` call next to the first.

Two design points the agent settled while proving it, both correct as shipped: `cancel_run` is the
single chokepoint (`grep` confirms exactly one caller, `cli/_runs.py:152` — no HTTP, MCP or serve
path cancels), and the entry carries **no** `channel` field, unlike `approval_grant`/`approval_deny`.
With one caller and one possible value, threading a channel today would be speculative generality;
adding an HTTP or MCP cancel path is the trigger, not before.

---

## PHASE 21 — The product substrate  *(☑ COMPLETE at cut scope — P21-1 + P21-5 shipped; the rest cut by D-24)*

**D-20 is answered: a factory for agentic products, so both — factory first, substrate second.**
Phase 21 is therefore live, and **two cards wide, not four**.

**The thesis, now committed:** split into an embeddable `docket-runtime` library plus the `docket`
control plane built on top of it. Every agentic product the company ships then inherits one gated
tool chokepoint, one policy engine, one approval store and one audit chain — rather than each product
team reinventing guardrails badly. Verified 2026-07-31: the runtime slice imports only `pydantic` and
`filelock`, and `core/`/`edges/` contain no CLI dependency at all, so this is packaging and a public
API contract, **not** a rewrite.

**Two sequencing constraints, both hard:**

1. **After Phase 19's removal wave, never before.** Publishing a library that still reaches for
   `openclaw.json` would freeze that coupling into a public contract.
2. **Packaging only.** P21-1 draws a boundary around code that exists and pins it with a test. It
   does **not** design new API surface, add extension points, or generalise anything. A package split
   that grows features is exactly how this becomes the overengineering D-24 cut everything else to
   avoid.

### Cards (Phase 21)

**P21-1 · Package split** — *TODO (unblocked) · M*
`docket-runtime` (library) + `docket` (control plane). Public API contract, versioning policy, and a
test proving the library imports nothing from `cli/` — the same shape as the existing
`test_no_subprocess_in_core.py` boundary guard, and it must be **seen to fail** on a planted
import before it counts as evidence.

**P21-5 · `agentic-product` pod blueprint** — *TODO · XS*
The factory's scaffolding primitive **already exists**: `core/blueprints.py` ships `software`,
`research`, `content` and `ops` as declarative data (`BUILTIN_BLUEPRINTS`, `WORKSPACE_KINDS =
{codebase, workdir}`, `DEFAULT_BLUEPRINT = software`). A product that *ships an agent* is a fifth
row, not new machinery — a pod shape whose scaffolded repo embeds `docket-runtime` and inherits the
gated chokepoint from day one. **Deliberately XS**: if this card starts growing code, it has stopped
being a blueprint and should be stopped. Depends on P21-1 for the embed target.

**P21-2 · Streaming** — *❌ CUT (D-24)*
Was: streaming `ChatBackend.complete` for user-facing agent UX. It only ever earned its place under
the hosted-runtime reading of D-20, which the answered goal rejects — agentic *backends* do not
stream, and an embedding product owns its own serving layer. `ChatBackend.complete` stays
deliberately non-streaming (P19-1). **Trigger to re-open:** a real product with a human watching
tokens arrive.

**P21-3 · Tenant axis** — *❌ CUT (D-22, D-24)*
Was: an end-user/tenant key alongside `project`, threaded through session storage, traces, audit
entries, approval records and budget accounting. Cut for the same reason as P21-2. **The original
warning stays on the record and stays true** — retrofitting the key is expensive, so this is a
genuine bet, not a free cut: the bet is that docket serves *products*, and each product serves its
own customers. **Trigger:** docket itself serving more than one end customer from one host.

**P21-4 · Build-agent profile** — *⏸ DEFERRED (D-24) · M*
Real the moment an Android or Unity product exists, and the measurement behind it is worth keeping:
today's tools are tuned for editing text — `read`/`write`/`edit` are **text-only** so binary assets
are invisible, `bash` defaults to a 120s timeout that a Gradle or Unity build blows straight through,
and tool output caps at 30k characters. A build agent is a different animal from a code-editing agent
(long timeouts, artifact handling, binary-safe file ops, no browser). **Trigger:** a real build to
run. Pre-building it for a hypothetical product is speculative by definition.

### Honest input on product mix (record it; it affects planning, not code)

Agent leverage is **not** uniform across the product types named:

| Product type | Agent leverage | Why |
| --- | --- | --- |
| B2B SaaS backends, APIs, integrations | **High** | Text in, text out, verifiable by tests |
| Web frontends | Medium | Verifiable, but visual judgment is weak |
| **Android / video games** | **Low** | Game feel, art and device QA are not text problems; no emulator or visual QA exists |

Plan capacity accordingly. Expecting the same leverage on a game as on an API backend is the kind of
assumption that quietly wrecks a roadmap.

---

## PHASE 22 — Control-plane write API for an external plan-of-record  *(☑ COMPLETE — all 6 cards, wave 16, 2026-08-04)*

**What triggered this.** The backlog has said since Phase 11 that docket **does not build a
dashboard of its own** — it "competes on the *write/governance* side and **feeds** them via a read
API". That consumer now exists and is ours: **Tack** (a sibling repository, the single-binary
Rust/SolidJS project manager) is adding an agent-factory control center — Phases 33–38 in its
roadmap, with executable cards in its `TODO.md`. Tack holds the plan of record (roadmap, board,
sprints, dependency DAG, per-project vocabulary); docket executes. A reconciler on Tack's side
polls docket and folds runs, approvals, traces and metrics back onto the board.

This phase is docket's half of that contract. It is deliberately **five small cards**, and it is
scored against §4.5 and D-24 the same way everything else is: *does a measured need in this system
ask for it* — here, yes, because a real consumer is blocked on each card, by name, today.

**What already exists and must not be rebuilt.** The read side is essentially complete:
`/status.json`, `/health`, `/metrics`, `/runs`, `/runs/<id>`, `/approvals`, plus
`POST /dispatch/<project>` and `POST /approvals/<token>`. Tack's Phases 33, 34 (partly), 36 and 38
consume that surface **unchanged** and ship without any docket change at all. What follows is only
the asymmetry: things reachable from the CLI or MCP but not over HTTP.

**The design rule for this phase: expose what `core/` already does, add no new behaviour.** Every
card below is a `serve.py` route over an existing `core/` function, with the same Bearer auth, the
same policy hooks and the same audit entries the CLI path produces. A card that starts designing new
semantics has stopped being this phase.

### Cards (Phase 22)

**P22-1 · `POST /tasks/<project>` — enqueue over HTTP** — *TODO · S · **blocks Tack Phase 35***
The gap that matters most: **there is no HTTP way to enqueue a task.** `POST /dispatch/<project>`
dispatches an *existing* queue (`effective_pipeline` → `resolve_variables` → `dispatch_pod`);
creation lives only in `core/dispatch.py::enqueue_task`, reachable from the CLI (`docket pod X
delegate`) and the MCP `delegate` tool. Body `{description, priority, trusted}` → `enqueue_task` →
`{taskId}`. Must honour the `pre_input` policy gate exactly as the CLI path does: a `block` verdict
returns 4xx naming the policy id, and a `require_approval` verdict returns the task in
`waiting_approval` with its token — not a 200 that pretends the task is queued.

**P22-2 · `GET /tasks/<project>` — the pod queue as JSON** — *TODO · XS*
`read_tasks(project)` already returns exactly the normalized shape. A route over it, Bearer-gated.
Tack shows queue depth per pod in its fleet view; today that number is only reachable by shelling
out.

**P22-3 · `GET /traces/<project>?since=<cursor>` — cursor'd trace read** — *TODO · S*
**This is P20-3's trigger firing, and it should be recorded as such rather than quietly
re-litigated.** P20-3 (fleet trace query) was deferred by D-24 on the reasoning that "`grep` over
JSONL is adequate at this fleet size" — which was true for a human operator and is false for a
programmatic consumer that needs to resume from where it stopped. Cursor-based, returning the JSONL
events verbatim. Do **not** build the fleet-wide query UI P20-3 described; one project, one cursor,
raw events out. Tack does the aggregation, which is the whole point of feeding a consumer instead of
building a dashboard.

**P22-4 · `channel="tack"` on approval decisions** — *TODO · XS*
`POST /approvals/<token>` hardcodes `channel="http"`. Accept an optional channel label from a
recognised set and record it. Without this, every approval granted from Tack's board is
indistinguishable in the audit chain from a CI job's — and the audit chain's whole value is that its
provenance is honest. Approvals are already the one place docket tags the channel; this keeps that
true as a fifth surface appears.

**P22-5 · `POST /pods` — provisioning over HTTP** — *TODO · M · **blocks Tack Phase 37***
`docket add` is CLI-only. Tack's "one click creates a product" flow needs `{project, path,
blueprint, pod, budget, verifyCmd}` → the pod roster. **This is the one card here that can grow, and
it should be watched:** provisioning touches workspace creation, port-range and scratch allocation,
git worktrees and the startup contract. Constraint — it calls the same `core/` provisioning path
`cli/_agents.py` calls, and adds no options that the CLI does not already have. If it starts
growing its own flags, stop and reconsider. A partial failure must leave nothing behind; Tack rolls
back its own project on a non-2xx, and cannot roll back a half-created pod for us.

**P22-6 · Trace retention** — *TODO · S*
Un-defers the retention half of P20-3, and the reasoning has genuinely changed rather than merely
been re-argued: once Tack durably ingests trace events (P22-3), docket's JSONL becomes a cache
rather than the only copy, which makes deleting it **safe** rather than lossy. Bounded by age, with
the audit log explicitly out of scope — telemetry is sampled and lossy by design, an audit log must
be neither, and conflating them is the mistake Phase 20's design rule already names.

**P22-7 · MCP tools in a live turn** — *not new scope; recorded for its consequence*
The known defect (CL-wave record: `load_mcp_tools` is never called, `DocketDriver.registry_factory`
defaults to `builtin_registry`) means **docket's agents cannot call Tack's MCP server from inside a
turn**, so they cannot self-report progress onto the board. Tack's design deliberately does not
depend on this — its reporting comes from the dispatch lifecycle (runs + traces), and its
`orch_tasks` link table makes agent self-reporting a drop-in the day the wire lands. Recorded here
so the dependency is visible, not to re-card work that is already tracked.

**P22-8 · `pipeline validate` over HTTP** — *TODO · S · found by Tack card D3 (2026-08-05)*
`docket pipeline validate <file>` (`cli/_pipeline.py::_validate`) is a thin CLI wrapper over
`core.pipeline.validate_pipeline(text) -> list[str]` — pure, already UI-free, already the single
source of truth for "is this a valid docket pipeline." `serve.py` exposes no route for it (checked
every `do_GET`/`do_POST` branch directly; the closest existing thing, `POST /dispatch/<project>`,
*runs* a pipeline, it doesn't just check one). Tack wants to validate a template's stored pipeline
YAML at save time (its "pipeline library," task 37.3) without maintaining a second, drift-prone copy
of `PipelineSpec`'s schema in Rust — exactly the mistake P20-3-style client reimplementation already
cost this project once (Tack's own B2/R1 history). Today Tack can only check that stored YAML
*parses*, not that it's a valid pipeline, and says so explicitly rather than claiming a stronger
guarantee it can't back up.

A route is a small, low-risk addition: `POST /pipeline/validate` (or a query-string variant of an
existing path), body = raw YAML text, `{ok: bool, errors: [str]}` — no project, no pod, no auth
even, mirroring `validate_pipeline`'s own signature exactly (it takes no project argument today).
Unlike P22-5, this one genuinely cannot grow: `validate_pipeline` already exists, already takes
exactly one argument, and already returns exactly the list Tack wants to show the operator. The
route is a `do_POST` branch and nothing else.

**Acceptance:** `POST /pipeline/validate` with a well-formed pipeline body returns `{ok: true,
errors: []}`; a body with a duplicate step id, an unknown rework target, or invalid YAML returns
`{ok: false, errors: [...]}` with `core.pipeline.validate_pipeline`'s own messages, unchanged. Tack's
card D3 should switch its template save-time check from a bare `serde_yaml` parse to this route the
day it ships (see TODO.md's Tack repo, §6 "D3" handoff, for the client-side half of this gap).

### What this phase does *not* do

- **No dashboard.** Unchanged from the Phase 11 backlog ruling. Tack renders; docket serves data.
- **No push/webhook to Tack.** Tack polls. Pull survives docket restarts, missed deliveries and Tack
  downtime with no queue and no replay logic on either side. Revisit only if a measured latency
  complaint appears — one poll interval (10s default) has not produced one.
- **No auth model change.** Same single Bearer token, same 0600 token file. Tack stores it
  write-only, the way it already stores its S3 secret.
- **No tenant axis.** D-22/D-24 stand. Tack is one operator's control center, not a tenant.

**Definition of done:** Tack's Phase 35 sprint dispatch drives a real pod through Lead → Implementer
→ Reviewer → Tester and the card lands in Done by itself; a Tack-granted approval shows up in
`docket audit verify` tagged `channel="tack"`; `docket list` and Tack's fleet view agree after a
wizard-provisioned product.

---

### PHASE 5 — Channel portability + system snapshot  *(☑ COMPLETE)*

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

### PHASE 6 — Model & provider agnosticism  *(☑ COMPLETE)*

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

### PHASE 8 — Agent observability, guardrails & drift (HITL)  *(☑ COMPLETE)*

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

### PHASE 9 — Contract integrity: close the spec↔runtime gap (de-ceremony)  *(☑ COMPLETE)*

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

### PHASE 10 — Agent architecture: project pods (scope ≠ role ≠ lifecycle)  *(☑ COMPLETE)*

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

### PHASE 12 — Consolidation & hardening  *(☑ COMPLETE 2026-07-02)*

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

> **☑ Phase 12 shipped 2026-07-02 — all 14 cards CH-0…CH-13 DONE, full suite green.** Every
> exit criterion above was met, with one negotiated deviation: `cli/__init__.py` landed at
> **1,702 lines**, not ≤1,500 — the CH-7 card's own Do-list named 5 extraction targets
> (`_keys.py`, `_context.py`, `_workflow.py`, `_cost.py`, `_agents.py`) and none of the
> remaining commands, so no 6th stage was invented purely to force the number under the target.
> `docket` **0.2.0** was drafted in CHANGELOG/`VERSION`/`pyproject.toml`/`uv.lock`/`__version__`
> at this point, but not yet tagged — Phase 13 landed on top before the tag was cut, and the
> release actually shipped as **`0.2.0-beta.1`** (see the Phase 13 completion note and §8) once
> the operator clarified every release from this project carries a SemVer `-beta.N` suffix. The
> TODO board was cleared per convention; this note is the durable record. Full findings:
> `internal-docs/architecture-audit.md`; execution trail: TODO.md's CH-0…CH-13 cards (kept, per
> this phase's own convention, until the next phase overwrites them).

---

### PHASE 13 — Close the differentiation gaps  *(☑ COMPLETE 2026-07-02)*

> **Source of record:** `internal-docs/competitive-analysis.md` (2026-06-25 research pass) named
> three "Tier 1 — Now" bets as docket's highest-leverage, no-daemon-change differentiators: **P1**
> pod-level runtime-resource isolation, **O2** a deterministic pre-merge verification gate, **S1**
> high-risk action classes + a headless approval channel. A 2026-07-02 grounding pass (three
> parallel code investigations, file:line-cited) found the framing had gone stale: **Phase 11's
> own CD-1/CD-2/CD-3/CD-4 cards already built most of this** the same week the analysis was
> written. Executable board: [TODO.md](TODO.md).

**Why this phase.** Re-checking the three bets against the current tree:

- **P1** — `AgentMeta` already has `port_range_start/count`, `scratch_dir` (`core/models.py:75-77`);
  `core/resources.py` allocates ports/scratch dirs per pod; `_pod.py` documents them into TOOLS.md.
  What's missing: none of it reaches the implementer's actual **process environment** —
  `edges/adapters/openclaw.py`'s `agent_run` (~L971-976) shells out with no `env=` override, so an
  implementer can only *read about* its port range/scratch dir as prose in TOOLS.md, never rely on
  it being set. The disposable DB/cache "namespace" is a naming convention only (`_pod.py:116-117`),
  no real provisioning — that stays out of scope (no DB engine assumption; see keeps below).
- **O2** — this *is* CD-2, already shipped 2026-06-25: `dispatch.py` runs `verifyCmd` via
  `edges/adapters/system.py`'s `run_verify_cmd` after the implementer hop and hard-fails on
  non-zero. Two real gaps remain: (a) there is no way to **set** `verifyCmd` short of the internal
  `meta-set` debug command — no TOOLS.md field, no public `docket pod add --verify` flag, despite
  `specs/data/docket-meta.spec.md:74` already (incorrectly) documenting one; (b) the Tester hop's
  PASS/FAIL is prose the pipeline never parses — only adapter-level `run_res.ok` gates it, so a
  Tester agent that writes "FAIL" in its response can still advance the pipeline.
- **S1** — `docket approve`/`docket deny` (CLI channel) and `serve.py`'s `POST /approvals/<token>`
  (HTTP channel) both already work end-to-end (`cli/_approve.py`, `serve.py` ~L321-368). The
  headless approval routing that `specs/functional/security-gates.spec.md` says gates-default-on
  is blocked on already exists in code — the spec just hasn't caught up. Two real gaps remain:
  (a) no "high-risk action class" concept exists anywhere — `core/security.py` is a flat binary
  allowlist, no always-route category for money/prod-deploy/secret-access actions; (b) approval
  grants/denials only emit trace events, never `audit_log()` — so an approval channel other than
  Telegram leaves no audit trail.

**The bet (one line):** don't build three features from scratch — close the five specific,
file:line-identified gaps that stand between "the substrate exists" and "the differentiation claim
is true," then flip gates-default-on now that its own spec's blocking condition is actually met.

**Cards (detail + acceptance in [TODO.md](TODO.md)):** FD-0 inject pod resources into the
implementer's process env (completes P1) · FD-1 TOOLS.md verify-command field + public
`--verify` flag (completes O2a) · FD-2 structural Tester PASS/FAIL gate in dispatch (completes O2b)
· FD-3 high-risk action-class always-approve policy (completes S1a) · FD-4 audit-log parity for
approval grant/deny across all channels (completes S1b) · FD-5 security-gates.spec.md truth pass +
flip gates-default-on · FD-6 spec/data truth pass for the fields touched above · FD-7
docs/positioning pass — claim the closed gaps, correct the stale competitive-analysis framing.

**Explicit keeps (do NOT build in this phase):** a real disposable DB/cache namespace (stays a
naming convention — no docket-owned DB engine to provision against); microVM/gVisor isolation,
multi-host provisioning, cross-runtime adapters (all still §7 Backlog, deferred); the existing
CLI/HTTP approval channels themselves (already correct — this phase documents and hardens them,
does not rebuild them).

**Phase 13 exit criteria:** an implementer subprocess's real environment contains its allocated
port range + scratch dir (test-verified, not just TOOLS.md prose); `verifyCmd` is settable via a
public CLI flag and documented in TOOLS.md; a Tester hop reporting FAIL (or an unparseable result)
blocks pipeline advancement; a defined high-risk action-class list always routes to approval
regardless of the allowlist; every approval grant/deny (any channel) writes an audit-log entry;
`security-gates.spec.md` reflects the real channel set and states the on-by-default condition is
met; `docket install`'s gates default flips; full suite + goldens green throughout.

> **☑ Phase 13 shipped 2026-07-02 — all 8 cards FD-0…FD-7 DONE, full suite green (795 tests).**
> Every exit criterion above was met, with one honest narrowing: the high-risk action-class
> policy (FD-3) is **fully enforced only for money-movement and secret-access** (their bins were
> never in the curated allowlist); prod-deploy's `git`/`npm` overlap is documented policy, not
> daemon-enforced — an initial implementation that excluded `git`/`npm` wholesale was rejected
> during review because the daemon's exec-allowlist gates by binary path only, and would have
> forced every benign invocation (`git status`, `npm test`) to also require approval. Per-argument
> enforcement for allowlisted bins is now a tracked backlog item, not silently claimed as shipped.
> `internal-docs/competitive-analysis.md` (gitignored, local-only) was corrected with per-bet
> status notes so its Tier-1 framing — which had already gone stale by the time this phase started,
> since Phase 11's CD-1…CD-4 had built most of the substrate the same week it was written — doesn't
> mislead a future planning pass the same way. Full findings: this section above; execution trail:
> TODO.md's FD-0…FD-7 cards (kept until the next phase overwrites them, per convention).

---

### PHASE 14 — Platformization I: runtime truth & dispatch hardening  *(☑ COMPLETE 2026-07-30)*

> **Source of record:** `internal-docs/agent-platform-audit-and-build-plan.md` (2026-07-29, four
> parallel code-grounded audit passes, file:line-cited; gitignored local rationale — this section is
> self-contained). The audit measured docket against eight agent-platform pillars (runtime driver,
> workflow engine, MCP, gateway, context/memory, governance, orchestration, role diversity) and found
> a disciplined config layer over a dispatch lane that is **not crash-safe, not race-free, and not
> honest about three of its own specs**. Phases 15–18 all execute through this lane — it hardens
> first. Executable board: [TODO.md](TODO.md).

**Why this phase (code-verified defects, the audit's §8 register):** the pod task queue has an
unlocked read-modify-write — the serve webhook, scheduler, and sweeper threads can all dispatch the
same pod concurrently and double-run a task (`dispatch.py` read→write vs `store.py`'s write-only
lock). There is no persisted `running` state, so a crash mid-task re-runs every hop from the lead.
A budget-`blocked` task is rewritten to `pending` and retries forever. No retries, no cancellation,
no per-task timeout (one hardcoded 300s constant shared with verify commands). The serve dispatch
lane swallows every exception (`contextlib.suppress`) and the webhook returns 200 before any work,
with no run id. The Reviewer role is mechanically decorative (its APPROVE/REQUEST-CHANGES is never
parsed; only the Tester gate is real). Auto-pause at budget cap **does not exist** — no code writes
`paused=True` (the Phase 1 claim was Bash-era; the port dropped it), and display code compares the
flag as a string while writers use a bool. `verifyCmd` runs in `codebase` instead of the member's
`worktreeDir`, `shell=True`, with no independent timeout. `_hop_message` concatenates every prior
hop's full output unbounded. And the spec surface overclaims: `audit.spec.md` is "Complete" at ~1/6
coverage; `security-gates.spec.md`'s `[GATE] → docket approve` worked example cannot happen today.

**Cards (detail + acceptance in [TODO.md](TODO.md)):** R-1 task state machine v2 — persisted
`running`, locked claims, retries with `attempts`, per-task timeout, uuid task ids, crash sweep +
resume-from-hop; kill the `blocked→pending` rewrite · R-2 retries + configurable timeouts (turn vs
verify decoupled) · R-3 run registry + job API (`docket runs`, `GET /runs/<id>`), ban
`suppress(Exception)` in the dispatch lane (D-17) · R-4 Reviewer verdict gate + bounded rework loop
back to the implementer · R-5 budget honesty — implement auto-pause for real, fix the string/bool
bug, token-based *estimate* (clearly labeled, never "recorded spend") when the daemon writes no cost
· R-6 verifyCmd correctness (worktree cwd, bounded shell surface, audit on set-verify) · R-7 bounded
hop prompts (cap + truncation marker — stopgap until Phase 17's compiler) · R-8 spec/docs truth pass
(audit.spec.md re-status, security-gates `[GATE]` example marked daemon-gated, `_provider.py`
guidance bugs, eval-harness schema drift, durable scheduler last-run state).

**Explicit keeps (do NOT build here):** no asyncio rewrite, no FastAPI, no message bus (threads +
filelock + persisted claims only, per §4.5); no new pillars (workflow spec, archetypes, MCP, driver
port all wait for 15–18); no daemon changes.

**Phase 14 exit criteria:** two concurrent dispatchers cannot double-run a task (thread-race test);
a killed-mid-task dispatch resumes from the last completed hop without re-paying earlier hops; a
budget-capped agent is actually `paused` and dispatch refuses it; REQUEST-CHANGES from a Reviewer
blocks (and one bounded rework cycle runs); every serve-lane dispatch has a queryable run id and no
silenced exceptions; every spec Status line matches the code; full suite + goldens green.

> **☑ Phase 14 shipped 2026-07-30 — all 8 cards R-1…R-8 DONE, full suite green (1,112 tests, 18
> goldens).** Every exit criterion above was verified against the shipped code and its tests,
> not just claimed:
>
> - Two concurrent `dispatch_pod` calls cannot double-run a task — `edges/store.py`'s new
>   `with_lock`/`read_modify_write` makes the claim (`pending`→`running`, `startedAt`/`claimId`/
>   `claimedAt` persisted) one locked read-modify-write; test-pinned
>   (`TestConcurrentDispatch.test_two_concurrent_dispatch_pod_calls_never_double_run_a_task`,
>   `tests/python/test_dispatch.py`).
> - A killed-mid-task dispatch resumes from the last completed hop, not hop 0 — hops persist
>   incrementally (`_persist_hop`); a stale `running` claim is swept to `failed`
>   (`failureKind: "stale_claim"`) and only `--resume` reclaims it, replaying pipeline position
>   (including mid-rework) via `_replay_pipeline_position`; test-pinned
>   (`test_resume_skips_already_completed_hops`, `test_stale_claim_sweep_emits_trace_event`).
> - A budget-capped agent is genuinely `paused` and dispatch refuses it — `_pause_lead_for_budget`
>   writes `paused=true, pausedReason="budget"` on the pod's Lead the first time the cap is
>   reached; `_claim_next_task` refuses every further claim for that pod outright (a
>   `paused_refused` trace event); `docket profile <id> --resume` clears it; test-pinned
>   (`tests/python/test_autopause.py`, 26 cases).
> - REQUEST-CHANGES from a Reviewer blocks and drives one bounded rework cycle (default
>   `maxReworkCycles=1`) before a second rejection fails the task — test-pinned
>   (`tests/python/test_reviewer_gate.py`, 25 cases, incl. `TestReviewerReworkResume` for the
>   resume-mid-rework case).
> - Every serve-lane dispatch (CLI, webhook, schedule, sweep) has a queryable run id via
>   `core/runs.py`/`docket runs`, and the four `contextlib.suppress(Exception)` sites around
>   dispatch that used to swallow every exception are gone — grep-pinned
>   (`tests/python/test_no_suppressed_dispatch.py`).
> - Every spec Status line matches the code: R-8's sweep rewrote `pod-dispatch.spec.md` to
>   v2.0.0 (the full state machine) and trued up `docket-meta.spec.md`, `serve-read-api.spec.md`,
>   `cli-json-shapes.spec.md`, `audit.spec.md`, and `cli-interface.spec.md` — see TODO.md's R-8
>   card for the exact per-file diffs, several of which were pre-existing drift unrelated to R-1…
>   R-7 caught along the way (a stale `apiVersion` example, a phantom `type` JSON field, two
>   missing audit action families). `specs/README.md`'s status table now mirrors every spec's
>   real header.
> - Full suite + goldens green throughout: 1,112 pytest cases, 18 golden-parity cases,
>   `scripts/validate-specs.sh`, `uv run python scripts/metrics.py --check`.
>
> **What was narrowed or deferred (stated here so it isn't quietly re-claimed later):**
> cancellation of an in-flight hop and parallel hop execution are **not implemented** — both stay
> Phase 16 W-2, same as before this phase; `maxReworkCycles` has no dedicated CLI setter yet
> (set via the internal `meta-set` debug path), noted in R-4's own card and in
> `docket-meta.spec.md`; the Reviewer/Tester verdict gates and the budget/pause mechanism remain
> scoped to the pod-dispatch lane only — an agent's spend outside dispatch (a raw Telegram
> session, direct daemon use) is still entirely unenforced, per D-9's "docket orchestrates hops"
> boundary; the governance gaps this phase was never meant to close are unchanged and explicitly
> still open — docket's approval store still has no production producer (Phase 15 G-1/G-5),
> `docket models set/preset/reset` still write no audit entry (Phase 15 G-4 follow-up), and
> enforcement outside the dispatch lane (e.g. per-argument high-risk matching for allowlisted
> bins) still does not exist (Phase 15 G-3). One card (R-6) had shipped correctly but its own
> TODO.md status line and acceptance boxes were left at `TODO` through an oversight in an earlier
> merge — corrected as part of this phase's board-truth pass, not a late functional change.
> Execution trail: TODO.md's R-1…R-8 cards (kept until the next phase overwrites them, per
> convention).

---

### PHASE 15 — Platformization II: deterministic governance, wired  *(☑ COMPLETE — all 6 cards G-1…G-6 shipped; G-3 closed it 2026-07-31)*

> **The audit's single most damning pattern:** three governance organs are fully built, tested, and
> documented — and connected to nothing. `approval_create` has **zero** production callers (the
> daemon's exec prompt and docket's `apr-*` store are disconnected systems); the policy engine's
> only caller is its own dry-run printer (`docket policies test`), and `docket install` never even
> installs the six shipped policy templates; `resolve_command_action` — the one function implementing
> "high-risk always asks" — has no caller. Meanwhile the audit log covers ~1/6 of its spec (keys/
> profile/scope/agent-lifecycle mutations write nothing), has no tamper evidence, and
> `DOCKET_NO_AUDIT=1` is an unauthenticated kill switch whose suppression looks identical to success.

**Cards:**

- **G-1 · Approval-gated dispatch** *(the approval store's missing producer — pure docket)*: a
  `require_approval` gate evaluated pre-hop (from policy match, pod `requireApprovalRoles`, or a
  pipeline `approval` step). Task enters persisted `waiting_approval`; `docket approve/deny` and the
  HTTP endpoint genuinely resume/kill the run; the timeout sweep resolves to **denied** (matching the
  spec's fail-closed language, not today's read-by-nobody `expired`).
- **G-2 · Policy engine on the live path**: `install` runs `policies init`; `pre_input` evaluated at
  enqueue, `pre_output` (redact/warn/block) on every hop output before carry-forward/storage;
  `require_approval` action feeds G-1; emit `guardrail_check`/`guardrail_block` trace events (giving
  `_metrics.py`'s existing reader a producer). In-turn `pre_tool_call` stays **daemon-gated** —
  documented, never claimed.
- **G-3 · High-risk classes enforced where docket can**: wire `resolve_command_action` into every
  process docket itself launches (verifyCmd, future pipeline `shell` steps) and G-2's pre-output
  scan. Per-argument daemon enforcement stays the tracked backlog item (Phase 13's honest narrowing).
- **G-4 · Audit v2** *(DONE — pulled forward on `pc/g-4`, no Phase 14 dependency)*: coverage to
  spec (`keys.* profile.* scope.* agent.add/delete pod.* persona.*`); per-line `seq` +
  `prev_hash` chain + `docket audit verify`; ms timestamps; size-capped rotation
  (`AUDIT_LOG_MAX_BYTES`); `DOCKET_NO_AUDIT` removed entirely (not TTY-gated — would force
  interactive I/O into `core/`); suppressed trace writes return a distinct status (never a fake
  `True`). `runs.cancel` stays a tracked gap — no run registry exists yet (Phase 14 R-3 /
  Phase 16 W-2); `models.*` (role→model policy changes) also stays out of scope. See
  audit.spec.md v2.0.0.
- **G-5 · [daemon-gated spike] the `[GATE]` seam**: can the daemon's exec-approval prompt notify an
  external hook? Yes → bridge daemon prompts into docket approval tokens (the spec's example becomes
  true). No → file upstream, spec example stays labeled future.
- **G-6 · Serve auth hardening** *(DONE — pulled forward on `pc/l-2`, no Phase 14 dependency)*:
  `secrets.compare_digest` (timing-safe Bearer-token comparison, `serve.py`'s `_check_auth`),
  a `--token-file`/`token_file=` option to write the approval/dispatch token to a 0600 file
  instead of stdout, and documented bind rules (loopback-only by default, an explicit warning
  printed for any non-loopback bind). Landed in the same merge as L-2 below. See
  `tests/python/test_serve_auth.py`.

**Exit criteria:** every control in the audit's "enforced vs documented" table is either on a live
path or explicitly labeled *convention* in SECURITY docs; a `require_approval` policy visibly pauses
a real dispatched task until granted; `docket audit verify` detects a tampered line; suite green.

---

### PHASE 16 — Platformization III: declarative orchestration & diverse role archetypes  *(☑ COMPLETE — all 8 cards W-1…W-8 shipped 2026-07-30)*

> **Why:** the pipeline is a hardcoded constant and the role system knows exactly one objective —
> shipping code. `POD_ROLES` is a closed 4-tuple (`core/pod.py:21`), every role identity is a
> hardcoded Python string (`_pod.py:44-97`), gates are code-shaped (verify-cmd → implementer only,
> PASS/FAIL → tester only), and since the task-agent type was deleted, every agent is assumed to
> have a codebase. A research pod, a content pod, an ops pod are **inexpressible**. The operator's
> explicit requirement: pods must orchestrate *diverse objectives, not just build a web site* —
> with roles and scope declared as data. Scope itself (org vs project, per-pod isolation substrate:
> session keys, port ranges, scratch dirs, worktrees) already generalizes and is reused untouched.

**Cards:**

- **W-1 · docket-native pipeline spec**: one Pydantic-modeled, unknown-key-rejecting YAML — ordered
  steps (`role|agent`), per-step `retries/timeout/gate` (mechanical-check | verdict | approval),
  bounded rework edges, `parallel` groups (finally using `--count N` members), variables. Steps
  reference W-6 archetypes. No pipeline file ⇒ today's built-in order (zero migration).
- **W-2 · Executor**: `core/orchestrator` runs W-1 specs over R-1's state machine — bounded worker
  pool (threads; hops are subprocess-bound), join semantics, per-step trace spans, `docket runs
  cancel` kills the in-flight hop's process group. `docket workflow plan` renders the plan **from
  the real executor** (no drift-prone second pretty-printer). Determinism contract: same spec +
  same queue ⇒ same step DAG.
- **W-3 · Lobster retirement (D-16)**: `docket workflow` → removed-command notice mapping to the
  pipeline commands (the D-11 `docket team` pattern); `core/lobster.py` + templates deleted.
- **W-4 · Durable scheduling + event triggers**: persisted last-run (no restart re-fires), cron
  specs, webhook params → pipeline variables, `dispatch --follow` streaming from the trace.
- **W-5 · Structured handoff artifacts**: steps exchange a typed record (`{summary, files_changed,
  diff_ref, verdict, notes}`) persisted per hop — replaces raw-text concatenation between hops.
- **W-6 · Declarative role archetypes**: a role becomes a versioned YAML definition — `name`,
  `scope` (org|pod), `modelClass` (cheap|strong, slotting into the existing role→model policy),
  `soulTemplate`/`agentsTemplate` (variables: project, objective, codebase?, workDir),
  `gateContract` (`none|verdict(regexes)|mechanical(cmd)|approval`), `editRights`, `toolProfile`.
  Today's four roles ship as built-in archetypes with **byte-identical output** (golden-tested);
  starter library: `researcher`, `analyst`, `writer`, `critic`, `operator`, `monitor`. `docket
  roles list/show/add/validate`; user archetypes overlay built-ins (the `docket-models.json`
  registry pattern). `normalize_role`/`member_id`/`POD_ROLE_POLICY` rewritten against the registry —
  the closed set opens without changing a single existing id.
- **W-7 · Pod blueprints — objective-scoped provisioning**: blueprint = archetype roster + default
  pipeline + workspace kind (`codebase|workdir`) + org-vs-pod scope per role + default gates/
  budgets. Built-ins: `software` (today's pod, unchanged default), `research`, `content`, `ops`.
  `docket add <p> --blueprint <name>` + extended `--from spec.yaml`; restores a non-codebase
  workspace path for `workdir` blueprints.
- **W-8 · Generalized gates**: verdict parsing and mechanical checks detach from tester/implementer
  and become gate types any step declares (per-archetype verdict regex sets — PASS/FAIL,
  APPROVE/REQUEST-CHANGES, SOURCES-VERIFIED/UNVERIFIED…); cwd resolves from workspace kind.

**Hard sequencing rule:** W-6/7/8 land **with** the executor, not after — an executor that hardcodes
roles a second time forces a second migration. **Anti-overengineering rule (new "we will NOT" row):**
no fifth role ever lands as a hardcoded string; archetype *prose and rosters* are user-extensible,
but gate contracts, edit rights, and scope stay closed typed sets docket can reason about.

**Exit criteria:** a `research` blueprint pod provisions, dispatches through a custom pipeline, and
**blocks on an unverified-sources verdict exactly the way a software pod blocks on failing tests**;
the four legacy roles produce byte-identical workspaces (goldens); `docket workflow` prints the
removed-command notice; suite green.

> **☑ Wave 7 shipped 2026-07-31 — the last 3 branches, and the Platformization program is
> COMPLETE.** Phases 14–18 all closed. `platform` green: **1,735 tests** (`pytest` exit 0, zero
> FAILED/ERROR), 18/18 goldens, 21 specs / 0 warnings, 37 commands, ~22,880 lines, `ruff` +
> `ruff format` + `mypy --strict` (62 files) clean, `metrics.py --check` in sync across all five
> claims. Merge order `c-3-c-5 → g-3 → cl-3`.
>
> **C-3 + C-5 · one durable task state, and a self-maintaining conversation registry** (Phase 17,
> closes it). Shipped as **one branch, not two** — the queued board offered "one dispatch owner or
> a function-level carve-out" and neither fit: these two write from the *same five* lifecycle
> functions (`_claim_next_task`, `_persist_hop`, `_touch_claim`, `_finalize_task`,
> `_apply_result`), so a carve-out between them was not available and splitting them would have
> manufactured a conflict in the file that cost the most to merge all program. `HEARTBEAT.md` was
> the documented durable ledger that only an agent's own compliance ever wrote to; dispatch now
> maintains a delimited docket-owned region inside it, and `docket doctor` flags TASK_LIST⇄ledger
> divergence and re-syncs under `--fix`. The delimiters are the point: writes only ever replace
> text between them, so the file stays co-authored and the agent's prose survives — pinned by
> tests, not by convention. `serve.py` needed **zero** changes, verified rather than assumed: all
> three of its dispatch triggers funnel through `_persist_hop`.
>
> **G-3 · high-risk classes on real paths** (Phase 15, closes it) — and a lesson about what
> "wire the unused function" can mean. The card said to wire `resolve_command_action`. Wiring it
> proved it was the *wrong* function: it resolves `ask` vs `allow` for a command string, and that
> decision belongs to the daemon's exec gate (D-15), which keys on binary path and has no hook to
> consult docket — it could never have had a caller. `match_high_risk` was the one that could, and
> it now guards `run_verify_cmd` (the single docket-launched subprocess built from free-form
> operator text through a real shell — a match refuses outright, since a synchronous dispatch hop
> has no approver reachable to answer an "ask") and dispatch's `pre_output` scan. **The other three
> helpers were deleted on merge** rather than left beside the wired one: keeping a never-called
> ask/allow resolver one function away from the code that fixed exactly that defect would have
> been the wrong lesson to leave in the tree. What stays advisory is unchanged and stated plainly:
> the daemon's allowlist still gates by binary path, so a live agent's `git push origin production`
> is still not daemon-blocked.
>
> **CL-3 · post-program dead-code sweep** — 97 new symbols across ~4,100 inserted lines examined,
> **4 deleted** (`step_id_of`, `BlueprintRegistry.__contains__`/`.items()`,
> `BUILTIN_BLUEPRINT_ORDER`). The restraint is the result: `handoff.notes` (reserved schema),
> `from_legacy_output` (2 real callers) and `build_pod` (not superseded — its replacement calls it)
> were all correctly kept. Findings inside sibling-owned files were **deferred to the register
> rather than edited across the line**, and both were then resolved by the integrator:
> `DistillResult.failure_kind` gained its consumer (a blocked delete now says *why* it was
> blocked), and `CancelOutcome.killed_pids` was kept with a dated reason.
>
> **Two guard defects found by chasing numbers that did not match**, both the same shape as
> Phase 14's vacuous `metrics.py --check`: (1) **the dependency floors were false** — `typer>=0.12`
> fails 216 tests against a modern click, `pydantic>=2` fails 56 test modules at import; corrected
> to `>=0.13`/`>=2.1` and now held by a new `floors` CI job that resolves `--resolution
> lowest-direct` and runs the suite. (2) **`metrics.py` and `validate-specs.sh` disagreed on how
> many specs exist** — the validator globs `specs/acceptance/*.md`, the metrics script used an
> `*.spec.md` suffix filter and structurally could not see `user-stories.md`, so README published
> 20 where the blocking gate counted 21. The two are now pinned against each other by a test that
> shells out to the validator.
>
> **☑ Wave 6 shipped 2026-07-30 — 5 cards. Phase 18 closed, Phase 17 opened and is 3 of 5,
> Phase 15 down to one open card.** `platform` green: **1,684 tests** (`pytest` exit 0, zero
> FAILED/ERROR), 18/18 goldens, 20 specs, 37 commands, `ruff` + `mypy --strict` clean,
> `metrics.py --check` in sync.
>
> **G-2 · Policy engine on the live path** — closes the audit's built-but-disconnected defect,
> the same shape G-1 fixed for the approval store. `install` seeds the baseline policies,
> `pre_input` evaluates once at enqueue, `pre_output` on every hop output, and a hit can route to
> G-1's real `approval_create`. **The existing `cli/_metrics.py` reader needed no changes** — the
> producer was built to fit it rather than orphaning it. G-2 also *declined a stale instruction*:
> `_policy_requires_approval`'s docstring claimed it was the place to change, which would have
> re-tripped a `"*"`-scoped policy once per role instead of once per task.
>
> **C-1 · Context compiler** — per-role token budgets (`RoleArchetype.token_budget`) via
> `core/context.py`, retiring R-7's blind head+tail byte cap rather than layering on it. Reused
> the existing `config.CONTEXT_BYTES_PER_TOKEN` instead of introducing a second tunable ratio for
> the same quantity; the approximation is documented as an approximation.
>
> **C-2 · Memory distillation** — `maintain distill`, and `clean`/`reset` distill first by
> default so memory is never bare-deleted. docket's **first self-originated LLM call**, through
> the driver per D-18 with **zero new dependencies** (verified: the branch's `pyproject.toml`/
> `uv.lock` diff is empty). **Fails closed** — a driver timeout, daemon error or empty reply
> aborts before anything is unlinked, proven by a hermetic test running the real driver with
> `PATH=/nonexistent`, not a mock.
>
> **W-5b · Artifact diff producer** — closes the seam W-5 declared honestly. `git_current_branch`,
> which CL-2 kept a wave earlier with a dated "the primitive a near-term feature will need" note,
> turned out to be exactly that caller. All four degrade paths (non-Implementer, `workdir` pod,
> non-repo codebase, missing `git`) are pinned end-to-end through real `dispatch_task` calls.
>
> **L-5 · Wrapped gateway spike** — answered **yes**, and better: docket already ships the
> mechanism. `docket models provider add` writes an arbitrary `models.providers.<name>` block, and
> the "local" framing is cosmetic (`127.0.0.1:8080` is only `DEFAULT_BASE_URL`). No code needed.
> Recorded honestly alongside it: per-call USD metering does **not** come free — this daemon
> reports token counts only, so a sidecar's spend API is a separate integration.
>
> **Integrator cleanup done on merge, not deferred:** C-1's carve-out forbade it from deleting
> R-7's now-dead `_hop_carryover_budget`/`_truncate_carryover` helpers, so it correctly left them
> and flagged them. Since that dead code existed only as an artifact of the rule, the integrator
> removed them, `HOP_CARRYOVER_BYTES`, and the two test classes pinning them, on merge. One
> truncation mechanism now exists in the tree.
>
> **The carve-out worked, and the one conflict it did produce was the dangerous kind.**
> `core/dispatch.py` took edits from three branches; C-1 (`_hop_message` only) and W-5b (one new
> function plus one call site) auto-merged with zero conflicts. G-2 conflicted at the artifact
> construction site, and **neither side was correct**: G-2 introduced `hop_ok`/`hop_output` (the
> post-policy values) while W-5b's side still read `run_res.ok`/`run_res.output`. Taking W-5b's
> side verbatim would have sourced the artifact summary from raw subprocess output and **silently
> undone `pre_output`'s redaction** — a leak, not a style difference. Resolved to `hop_output` for
> the summary and `hop_ok` for both the verdict and the diff probe, with the reasoning left as
> comments at the call site.
>
> **The completions goldens were the exact case the standing rule exists for:** C-2 added
> `distill`, G-2 added `validate`, and no side held both. Git auto-merged them — which is not
> evidence of correctness — so `verify-all` was re-run against the real CLI and both additions
> confirmed present.
>
> **What was narrowed or deferred:** `pre_tool_call` (in-turn interception) stays daemon-gated —
> docket orchestrates *between* hops and is not inside a turn to intercept a tool call; G-3 (the
> high-risk action classes wired into docket-launched processes) is still open and is Phase 15's
> last card; `HandoffArtifact.notes` still has no producer and is now documented as reserved;
> the **dependency floors remain unverified** for lack of network access. G-2 also found real
> test-hygiene damage: two install fixtures left `DOCKET_HOME`/`POLICIES_DIR` at their real
> unpatched defaults — harmless until something in `run_install` touched them, at which point a
> test run would have written into the real environment.

> **☑ Wave 5 shipped 2026-07-30 — 5 cards, and Phase 16 is COMPLETE.** `platform` green at each
> merge: **1,600 tests**, 18/18 goldens, 20 specs, 37 commands, `ruff` + `ruff format` +
> `mypy --strict` clean, `metrics.py --check` in sync.
>
> **W-5 · Structured handoff artifacts** — hops exchange a typed `HandoffArtifact`
> (`core/handoff.py`) instead of concatenated raw text. The shape is the deliverable because Phase
> 17's C-1 must budget tokens against it: `summary` is required and `DROP_ORDER` gives a
> size-constrained consumer a typed shedding order, with `summary` deliberately excluded so it can
> never be dropped. `render()` returns exactly `summary` when nothing else is set, so the common
> case is byte-identical to the old behaviour, and `from_legacy_output()` degrades a pre-W-5 or
> malformed hop record instead of failing a resume. **This unblocks C-1**, and with it Phase 17.
> `pod-dispatch.spec.md` → 4.0.0: the persisted hop record format changed, with a documented
> degrade path.
>
> **W-4 · Durable scheduling + event triggers** — stdlib-only cron parser, webhook payload bound
> into pipeline variables (rejected with 400 *before* a run record exists), `pipeline run --follow`
> tailing the durable trace, and the `runs.cancel` audit entry. Its first deliverable needed **no
> code**: Phase 14's R-3 had already shipped and test-pinned persisted last-run, and the card
> verified that rather than rebuilding it.
>
> **G-4b · `models.*` audit coverage** — closes the gap G-4 named two waves earlier. `set` writes
> one entry; `preset`/`reset` can rewrite every role at once and each write a single entry naming
> every role's before→after pair. Both values are read around the write, so a repeated change logs
> the real prior value rather than a constant.
>
> **CL-2 · Dead-code register, non-dispatch half** — `core/sync.py` kept as the single
> implementation with `cli/_doctor.py` pointed at it (rather than deleting a module whose logic
> belongs in `core/`); `read_modify_write` rebuilt on `with_lock`; `HEARTBEAT_FILE` used across all
> nine files; two zero-caller ACL functions deleted. **Three rows were deliberately kept** with
> dated in-code reasons — notably `validate_policy()`, where wiring a command would have changed
> the completions goldens this card had to keep byte-identical, and deleting it would have dropped
> schema coverage two test files already get by calling it directly.
>
> **L-4 · Daemon MCP registry spike** — answered **yes upstream, absent here**: the `mcp.servers`
> registry and its CLI family are real and were exercised live against `openclaw@2026.7.1`, but the
> daemon this fleet targets (`2026.2.23`, independently confirmed) predates them. No production
> code, per the card's own rule. Its isolated probe had a **real side effect on the host** — a
> one-time upstream state migration escaped the scratch state dir and renamed
> `~/.openclaw/exec-approvals.json`; restored, with the sandboxing lesson recorded in the spec.
>
> **Dead code cleared this wave:** the `AgentRunResult` alias and all ~76 call sites across ten
> test families, `dispatch_all_pods` (deleted, not wired — R-3 had already replaced its only call
> site and pins that removal), the last `print()` in `core/`, `meta_write`,
> `set_agent_project_key`, and `core/sync.py`'s dead-module status. An AST-based test now pins that
> **no `print(` call exists anywhere in `core/` or `edges/`**.
>
> **What was narrowed or deferred:** `files_changed`/`diff_ref` ship as real artifact fields with
> **no producer** — populating them needs a git probe through `edges/adapters/system.py`, which
> CL-2 owned this wave; declared as an explicit seam in both the module docstring and the spec, not
> quietly claimed. `notes` likewise has no producer. G-2 and G-3 did not run (G-2 needs the
> dispatch file W-5 owned), so the policy engine still has no live-path producer. The
> **dependency floors in `pyproject.toml` remain unverified** — CI only ever resolves the locked
> versions, and testing the floors needs network access this environment lacks.
>
> **A fourth neither-side-is-correct conflict** appeared in `audit.spec.md`: G-4b's draft said
> `models.*` shipped and `runs.cancel` was the open gap; W-4's said the reverse. Both shipped in the
> same wave, so neither card could see the other's merge, and either side alone would have published
> a spec claiming a shipped feature was missing. The index cross-check separately caught **four**
> stale rows after W-4 alone.

> **☑ Waves 3–4 shipped 2026-07-30 — 11 cards across Phases 15/16/18, plus one standing cleanup
> card. `platform` at `7fc6233`: 1,512 tests (1,509 passed / 3 skipped), 18/18 goldens, 20 specs,
> 37 commands, `ruff` + `ruff format` + `mypy --strict` clean, `metrics.py --check` in sync.**
>
> **Wave 3** (six cards, merged in contention order): G-1 approval-gated dispatch — `approval_create`
> finally has a production caller · G-5 the `[GATE]` seam spike, answered **no** with a dated
> evidence trail against a live daemon · W-1 pipeline format · W-6 declarative role archetypes,
> legacy roles byte-identical · L-1 RuntimeDriver port (D-14) · L-3 MCP server, 10 tools.
>
> **Wave 4** (five cards, merged `cl-1 → l-6 → w-3 → w-7 → w-2`): CL-1 dead-code sweep (register
> below) · L-6 `mcp` SDK 1.x→2.x migration, pin now `mcp>=2.0.0` · W-3 Lobster retirement (D-16) —
> `core/lobster.py`, `cli/_workflow.py`, `test_cd7_lobster.py` and `workflow-integration.spec.md`
> **deleted**, `docket workflow` is a removed-command notice · W-7 pod blueprints (four built-ins,
> `workdir` workspace kind restored) · W-2 + W-8 the executor and generalized gates.
>
> **Phase 16 exit criteria: met.** A `research` blueprint pod provisions, dispatches through a
> custom pipeline, and blocks on an unverified-sources verdict by the same executor path a software
> pod blocks on failing tests — because after W-8 the executor branches on the resolved gate's
> **type**, never on a role name (four hardcoded verdict helpers deleted). The four legacy roles
> stayed byte-identical throughout (goldens). Two cards remain open (**W-4**, **W-5**) — they extend
> the phase rather than gate its criteria.
>
> **W-2 found and fixed cancellation's real root cause** rather than working around it: `agent_run`
> used a blocking `subprocess.run` and never created a process group, so there was nothing to kill —
> which is why cancellation had never existed. It is now `Popen(start_new_session=True)` with
> process-group SIGTERM → grace → SIGKILL, proven against a real spawned subprocess rather than a mock.
>
> **What was narrowed or deferred (stated here so it isn't quietly re-claimed later):**
> `runs.cancel` writes **no audit entry** (W-4's card now owns it) · resuming a task that crashed
> mid-parallel-group **re-runs the whole group**, not just the incomplete members · approval gates
> are **rejected inside a parallel group** as a configuration error, not supported · W-4 (durable
> scheduling, event triggers, `dispatch --follow`) and W-5 (structured handoff artifacts) are not
> started, so hops still exchange concatenated raw text and Phase 17's C-1 stays blocked ·
> `maxReworkCycles` still has no dedicated CLI setter · every Phase 14 carried-forward gap in
> TODO.md's "Known-open gaps" list is still true unless named above.
>
> **Two integration defects were caught by cross-checking, not by the gates**, and both would have
> shipped silently: a golden conflict whose either-side resolution deletes a shipped command from
> the completion surface (twice — `roles`/`mcp`, then `pipeline`/`workflow`; no single side ever had
> the right set, so the golden must be **regenerated**, never picked), and `specs/README.md`'s index
> table taking a stale side that downgraded three spec versions and dropped a row. Both are now
> standing integrator checks in TODO.md.
>
> **A CI-blocking guard was found failing open.** `scripts/metrics.py --check` combined comma-blind
> `(\d+)` claim regexes with a silent skip for unmatched claims, so once the suite crossed 1,000
> tests it verified **nothing** while still reporting success — and an earlier README cleanup had
> removed 3 of its 4 claims from the prose. Every "metrics in sync" line reported during Phase 14 was
> therefore meaningless (the test counts themselves came from pytest and were accurate). Fixed:
> claims accept thousands separators, and a README stating **none** of the tracked metrics is now a
> hard failure rather than a silent pass. The repaired guard immediately caught real drift.

---

### PHASE 17 — Platformization IV: context engineering & memory management  *(☑ COMPLETE — all 5 cards C-1…C-5 shipped; C-3/C-5 closed it 2026-07-31)*

> **Why:** the audit found no tokenizer, no retrieval, no summarization anywhere — context is
> markdown written once plus prose contracts the *daemon's* forced-read enforces, and the only
> prompt docket composes grows unbounded. Memory lifecycle ops are destructive deletes. Durable task
> state is split-brained: `TASK_LIST.json` (machine-read) vs `HEARTBEAT.md` (what the reset contract
> points the model at) — disjoint, never reconciled. Org specialists get no contract files at all
> and doctor never heals them.

**Cards:** **C-1 · context compiler** — pure function (task, role, artifacts, workspace) → hop
message under a per-role token budget; priority order, deterministic truncation, chars/4 estimator
(tokenizer optional extra); composition logged per hop · **C-2 · memory distillation** — `maintain
distill` summarizes daily logs into MEMORY.md and archives originals; `clean/reset` gain
`--distill-first` (default on) — never bare-delete; the summarization turn runs **through the
driver** (D-18), docket's first self-originated LLM use, zero new SDK deps · **C-3 · one durable
task state** — dispatch writes HEARTBEAT entries mechanically at enqueue/start/finish; doctor flags
TASK_LIST⇄HEARTBEAT divergence; the durability contract stops being pure prose · **C-4 ·
specialists join the contract** *(DONE — pulled forward on `pc/c-4`, no Phase 14 dependency)* —
org specialists (security, knowledge, manager, and the opt-in Portfolio Manager) now get the
same full workspace contract (HEARTBEAT.md, WORKFLOW_AUTO.md, memory/) as project agents, and
`docket doctor` heals a specialist workspace left bare by a pre-C-4 install, closing the
projects-only healer gap; see `workspace-structure.spec.md` v1.2.0's own changelog · **C-5 ·
conversation registry auto-population** — dispatch/serve update `last_message`/`task_ref` (the
deferred TC item).

**Exit criteria:** no dispatch prompt exceeds its configured budget (test-pinned); `maintain reset`
on a workspace with content produces a distilled MEMORY.md + archive, not a void; a mid-task
context reset finds the task in HEARTBEAT because docket wrote it there; doctor heals a specialist
workspace; suite green.

---

### PHASE 18 — Platformization V: runtime-driver port, LLM agnosticism & MCP  *(☑ COMPLETE — L-1/L-2/L-3/L-6 shipped; L-4 and L-5 both answered as spikes, 2026-07-30)*

> **Why:** provider-agnosticism was declared complete (Phase 6) but the audit found Anthropic
> hardcoded in the rank anchors (non-overridable), the auth commands, and the preset/pricing gaps —
> and the runtime coupling half-escapes the ACL. MCP is entirely absent while it has become the
> ecosystem's tool-interop standard. Decisions D-14/D-18 govern this phase.

**Cards:**

- **L-1 · RuntimeDriver port (D-14)**: typed protocol — `run_turn / provision / teardown /
  list_sessions / usage / capabilities`. Session-JSONL/`trace_ingest` format knowledge moves
  **inside** the OpenClaw driver (closing the biggest ACL leak); the ACL guard test extends to
  session-format parsing; a fake driver replaces ad-hoc test shims. **One shipped driver.**
- **L-2 · Finish provider agnosticism** *(DONE — pulled forward on `pc/l-2`, no Phase 14
  dependency)*: registry-overridable rank anchors; `--provider` on auth commands; `local`/
  `ollama` presets; OpenRouter/local pricing rows or an explicit `n/a` row type; deleted the
  dead-end guidance strings (`cli/_provider.py`'s `models set task` reference and its raw-
  openclaw instruction) and single-sourced the duplicated `openclaw-gateway.service` constant
  (`core/utils.py` now forwards to `edges/adapters/system.py`'s `GATEWAY_UNIT`); reconciled the
  eval harness's daemon-JSON parser (`tests/evals/lib/eval-helpers.sh`) to the ACL's real
  `result.payloads[0].text`/`result.meta.agentMeta.usage` shape. See
  `tests/python/test_provider_agnosticism.py`; `model-profiles.spec.md` v2.3.0 and
  `cli-interface.spec.md` v1.6.0 already carry this card's spec updates.
- **L-3 · docket as an MCP server** *(pure docket, high leverage)*: `docket mcp serve` (stdio,
  official `mcp` SDK pinned) exposing the control plane as tools — `status, pods, queue, delegate,
  dispatch, runs, approvals list/grant/deny, cost` — every call audit-logged, approvals unchanged.
  Claude Code/Codex/any MCP client can drive docket *through* its governance spine, not around it.
- **L-4 · [daemon-gated spike] MCP config plumbing for agents**: if the daemon consumes MCP server
  config, `docket mcp add <agent> <server>` writes it via the driver + doctor checks it; if not,
  file upstream (L-3 ships regardless).
- **L-5 · [spike] wrapped gateway (D-18)**: evaluate a LiteLLM-class sidecar the daemon's provider
  config points at — central keys (ending plaintext `.env` fan-out), per-call metering (fixing cost
  observability at the root), failover, caching. Ship only if the daemon tolerates a base-url swap
  cleanly; otherwise metering stays L-1 `usage()` + R-5 estimates. Hand-rolled provider clients:
  banned (D-18).

**Exit criteria:** `core/` contains zero OpenClaw on-disk-format knowledge (guard-tested); an MCP
client can list pods, delegate a task, and approve a gated action end-to-end with audit entries for
each; `docket models` shows no hardcoded-Anthropic residue for a non-Anthropic fleet; suite green.

**Full-program scope guard (all five phases):** a full MCP *host* (docket executing MCP tools inside
agent turns) is the standalone-runtime trap — refuse it; microVM/multi-host/dashboards stay §7
Backlog; every control keeps its one-word label (*docket-enforced / daemon-enforced / convention*).

---

---

## Planned program — PHASE 25: human maintainability (D-36)

**Status:** ☑ COMPLETE (2026-09-12) · **Decision:** D-36 (§6) · **Executable detail:** Wave 31 in
[TODO.md](TODO.md) · **Contract:** `specs/test-framework.md` §"Lanes and placement" (2.13.0) ·
**Activation:** the maintainer deferred W29-C7 and Wave 30 behind this wave on 2026-09-11, so the
repository is made maintainable before it is published further; W29-C7's publication approval
stands and only its ordering changed. **Ordering rule:** W31-C0–C3 run sequentially, because C1
moves every test file and C2/C3 rewrite headers and comments across the tree; after C3 merges,
W31-C4+ fan out and Wave 30 becomes claimable, scheduled by file contention.

### Why this phase is scheduled

The 2026-09-11 maintainability audit (`internal-docs/maintainability-audit-2026-09-11.md`, measured
on the working tree at `0d3720a`) asked one question: can a person who did not write this repository
understand and maintain it in ordinary time? The product code can — `src/` carries no archaeology,
the layer rule holds and is AST-guarded. The envelope around it cannot: per line of product there
are 2.6 lines of tests, specs, docs and board, and that envelope is shaped for an agent without
memory, not for a reader. Each row is a measured trigger with its locator:

| Measured gap | Locator | Observed | Threshold |
| --- | --- | --- | --- |
| Default suite wall time | `uv run pytest -q --durations=15` | 8 min 12 s; the 15 slowest tests (~257 s) are all release/evidence/adapter tests | < 90 s, with those tests in a separate CI job |
| Tests that verify prose, release artifacts or the agent's own hook scripts, inside the default suite | `scripts/maint/test_inventory.py` | 35 files, 8,313 lines, 227 tests | a bounded `tests/agent/` lane, ≤ 4,000 lines, header-declared reason and retirement condition, guarded |
| Test files per subject | `rg -l` | `serve` 19 files, `runs` 17, `tools` 12; 33 duplicate test names; files named for events (`_v2`, `_migration`, `_removed`, `_deferred_gaps`) | one unit file per `src/` module, name = module, guarded |
| Archaeology in comments/docstrings | `scripts/maint/comment_lint.py src tests` | `src` 20, `tests` 69; §3's rule has no CI reader | 0, ratcheted by a guard with a committed baseline |
| `subprocess` in tests | `rg -c 'subprocess\.'` | 91 sites in 40 files spawning the whole CLI | 0 in `unit/`; boundary tests only |
| Board and roadmap volume | `wc -l` | `TODO.md` 4,628 lines, active wave at line 1642 between closed waves; `ROADMAP.md` 3,541 | TODO ≤ 200, ROADMAP ≤ 500, history byte-preserved in `CHANGELOG.md`, long decisions as ADRs |
| Hand-written reference that can be generated | `docs/commands.md` | 2,247 lines, no drift check, while `metrics.py` already introspects the Typer app | generated, `--check` in CI; `mkdocs build --strict` replaces hand-written link tests |
| Functions over 500 lines | `core/agent_loop.py::run_agent_turn` 789, `core/dispatch.py::dispatch_task` 703, `::_execute_unit` 501 | 3 (42 over 80) | 0 over 500; tests per extracted phase |

The root cause is recorded so it is not repeated: **every defect an agent produced received a
test that stops a later agent from reproducing it.** That defends against the agent's lack of
memory, not the product. The human answer to "docs have lied five times" is less prose that
claims capabilities, plus generated reference, not tests that read the README.

### Product boundary and exit contract

Phase 25 ships, in this order:

1. **Lanes** (`unit/`, `integration/`, `guards/`, `golden/`, `agent/`), the agent lane out of the
   default run and into its own CI job, `--import-mode=importlib`, and every path reference moved
   mechanically by script.
2. **Structural guards**: unit file ↔ module mapping, lane headers, agent-lane budget, no
   `subprocess` in `unit/`, per-lane duration ceilings — each seen to fail before it ships; the four
   removed-command test files collapse into one parametrized guard.
3. **Comment hygiene** with a ratchet: `scripts/maint/comment_lint.py --check` against a committed
   baseline; counts only go down.
4. **One unit file per module** (merges by packet) and **in-process CLI tests** (`CliRunner`),
   bringing the default suite under 90 s.
5. **Generated documentation**: CLI reference from Typer with `--check`, `docket-runtime` API from
   docstrings, `mkdocs build --strict` in CI, duplicated deep-dive docs folded into specs/guides.
6. **Board and roadmap to size**: closed sections archived verbatim to `docs/cycles-ended/` (shipped 2026-09-11 by `scripts/maint/split_board.py`: 49 sections, hash-verified), decisions
   longer than a row to `docs/adr/`, README ≤ 150 lines, CONTRIBUTING owns the working rules.
7. **The three 500-line functions split into named phases**, one per branch, behaviour-identical.

Phase 25 does **not** set a coverage-percentage target, rewrite assertions, change product
behaviour, add a test framework or plugin dependency, delete history (every archived section is
byte-preserved), or relax any existing gate. The mechanical steps (moves, path rewrites, header
skeletons, board archive) are scripts, not model work; model work is bounded to one module or one
file per packet.

### Wave 31 — human maintainability (planned 2026-09-11)

| Card | Outcome | Dependency / parallel boundary |
| --- | --- | --- |
| W31-C0 | Baseline artefacts committed; `scripts/maint/test_inventory.py` and `comment_lint.py` in the tree | Ready |
| W31-C1 | Suite moved into lanes; agent lane out of `testpaths` and into CI job `agent-lane`; every path reference rewritten by `apply_moves.sh`; CONTRIBUTING count fixed, not the script | After C0; **exclusive** — owns every test path |
| W31-C2 | Five structural guards seen red then green; lane headers; one removed-commands guard; agent lane ≤ 4,000 lines | After C1; exclusive on `tests/**` headers |
| W31-C3 | Zero archaeology, docstring budget, committed baseline + ratchet guard | After C2; comment/docstring lines only |
| W31-C4 | One unit file per module (packets: serve, runs, memory, archetypes, tools, pipeline, history-named files) | After C3; per-module, parallel with C5/W30 on disjoint files |
| W31-C5 | `CliRunner` in-process; `subprocess` only at process boundaries. Nine files converted, seven kept at the boundary, one shared `repoint_docket_home` helper replacing eight partial copies. **Suite 152-162 s to 117-122 s: the < 90 s target was not met and the card closed anyway**, since what remains is not `subprocess` overhead | After C1; per-file |
| W31-C6 | `gen_cli_docs.py --check`, `mkdocs build --strict`, deep-dive docs folded, hand-written link tests retired | After C0; docs/scripts only |
| W31-C7 | `split_board.py` and the `docs/cycles-ended/` archive (shipped); remaining: TODO ≤ 200 after W30/W31 close, ROADMAP ≤ 500, ADRs, README ≤ 150 | Integrator; when no other card is open |
| W31-C8a | **Done 2026-09-12.** `run_agent_turn`'s own body 328 to 75 lines over eight named phases; every bound evaluated at the same point, verified independently of the card's table. Three phases are pure and module-level with nine new unit tests; five stay nested closures over shared turn state and remain end-to-end covered only. `docket.core.agent_loop` leaves the layout ratchet | After C4; was parallel with C8b |
| W31-C8b | **Done 2026-09-12.** `dispatch_task` 703 to ~125 lines; the nested `_execute_unit` closure lifted to module level and 501 to 52, over named phases. Captured state inventoried first; the two mutated captures pinned by a test. No behaviour change, goldens byte-identical | After C4; was parallel with C8a |
| W31-C9 | `trace.redact` backtracking bounded; 40,000 characters from 10.68 s to 0.03 s, redacted set unchanged | Opened by a defect W31-C2 hit and worked around |
| W31-C10 | **Done 2026-09-12.** Every test repoints through one shared helper; 50 files converted. The partial-copy count was wrong by an order of magnitude: 21 private helpers, not two, and not one covered all sixteen constants. Guarded per function, not per module, and proved by planting drift | After C5; classification was required before conversion and a rate limit forced it afterwards |

---

## Planned program — PHASE 24: harness mode (D-35)

**Status:** ◇ PLANNED (2026-09-11) · **Decision:** D-35, reasoned in
[docs/adr/0001-harness-mode.md](docs/adr/0001-harness-mode.md) · **Executable detail:** Wave 30 in
[TODO.md](TODO.md) · **Activation gate:** Wave 31 closes. Nothing here touches release state, so
the gate is about one integrator owning one board marker at a time — and about files: W31-C1 moves
every test file each Wave 30 card would own, so starting Wave 30 first would merge against a moved
tree.

### Why this phase is scheduled

The 2026-09-08 request paired two ADRs across two repositories: docket's D-35 and Tack's ADR 0066,
which adds `docket` as a third runner harness beside two closed vendor CLIs and **builds nothing
until docket publishes a versioned non-interactive contract**. The 2026-09-11 audit
(`internal-docs/harness-mode-audit.md`, read at `4032133`) verified every "true today" row of the
ADR and found five places where the ADR described as existing something the code does not do.
Those are the measured triggers; each names its locator:

| Measured gap | Locator | Observed | Threshold |
| --- | --- | --- | --- |
| A cancellation request does not reach an in-flight `bash` command | `edges/adapters/toolbox.py::run_bash` blocks in `communicate(timeout)`; children start with `start_new_session=True`; the `bash` registration in `core/tools.py` does not pass `ctx.cancellation_check`; `DocketDriver` never reports a pid, so `runs.cancel_run` has nothing to kill | cancel at 0.2 s into `bash sleep 30` → handler returns at 30 s or at the tool timeout (default: the whole turn's wall clock) | handler returns within 2 s and the child process group is gone |
| A gated tool call waits, then the loop continues | `core/tools.py::dispatch_tool` `ask` branch → `wait_for_approval` (`TOOL_APPROVAL_TIMEOUT`=120 s) → `approval_timeout` denial → loop continues up to `max_consecutive_tool_denials`=3 | ≥120 s per gated call, terminal `tool_denials`/`invalid_output` with no policy id; `tool_result` trace has no `policyId` | zero wait, terminal on the first gated call, result names tool/call/policy/reason |
| No event stream seam | `core/trace.py::trace_event` validates, redacts and appends; no subscriber | zero | one synchronous subscriber seam; zero-subscriber path byte-identical |
| No published contract | `docs/contracts/` does not exist; no versioned event/result shape; no fixtures | zero | generated JSON Schema pinned by test + NDJSON fixtures for ok/blocked/cancelled/refused |
| No non-interactive entry point | `cli/` has no command that runs one agent in a caller-owned home and exits; `POST /dispatch/` returns before the work | zero | `docket harness run` / `status` |

This is the fourth recorded instance of the repository's named failure shape — machinery built,
tested and never wired to a caller — arriving *before* it ships rather than after: three of the
five gaps are seams whose absence would have been discovered by the first real Tack run.

### Product boundary and exit contract

Phase 24 ships, in this order:

1. **Truthful cancellation inside a turn:** a persisted cancellation request stops an in-flight
   `bash` command by killing its process group, and `docket runs cancel` gains the same reach.
   D-30 is amended for the `bash` handler only; HTTP requests and Python handlers keep D-30's
   "may finish" rule.
2. **Non-interactive approval outcome:** a caller that cannot answer an approval gets a typed,
   immediate, terminal `approval_unavailable` result that names the rule, instead of a two-minute
   wait and a retry loop.
3. **The contract before the command:** the trace gains a subscriber seam; the harness
   event/result shapes exist as Pydantic models, a generated schema and fixtures; the spec says
   "defined, command not yet shipped" until it is.
4. **The command:** `docket harness run` composes `core/runs.py`, `DocketDriver`, the trace
   subscriber and a `SIGTERM` handler into one synchronous process with NDJSON on stdout, a
   single versioned `result`, three exit codes and a refusal to touch the default `DOCKET_HOME`.
5. **Closure and consumer handoff:** D-35 dated, D-14 corrected, public claims scoped to what
   shipped, and the schema/fixture paths plus exact commit handed to Tack so ADR 0066's
   decision 4 can proceed.

Phase 24 does **not** add a second driver, driver discovery, a pod-shaped harness, a server or
background thread, an interactive approval protocol over stdin/stdout, a remote docket, a new
event vocabulary, a new persisted store, or any change to `docket-runtime`'s public facade beyond
the optional `approval_mode` field the runtime closure already carries.

### Wave 30 — harness mode seams and contract (planned 2026-09-11)

| Card | Outcome | Dependency / parallel boundary |
| --- | --- | --- |
| W30-C1 | `run_bash` observes cancellation and kills the child group; `docket runs cancel` reaches an in-flight command | Ready. Owns `toolbox.py::run_bash` and only the `bash` handler lambda in `core/tools.py`; parallel-safe with C2 at function level (Phase 19 precedent); merge before C2 |
| W30-C2 | `ToolContext.approval_mode="refuse"` → immediate `approval_unavailable`, terminal `stop_reason`, `policyId` in the `tool_result` trace | Ready. Owns `ToolContext`/`ToolResult`/`ToolDenialKind`, the `ask` branch of `dispatch_tool`, and `agent_loop.py`'s denial accounting/`StopReason`; no `toolbox.py` |
| W30-C3 | `trace.subscribe()` seam; `core/harness.py` models + preflight + result mapping; generated `docs/contracts/harness-v1/schema.json`; NDJSON fixtures; new `specs/api/harness-mode.spec.md` | Ready. New files plus `core/trace.py` only; disjoint from C1/C2 |
| W30-C4 | `docket harness run \| status` over C1–C3, with the stub-endpoint oracle (ok / blocked / cancelled / refused / status) and one live local-model run | After C1+C2+C3. Owns `cli/_harness.py`, one command block in `cli/__init__.py`, `docs/commands.md`, the `help` golden (new surface, diff explained) |
| W30-C5 | Closure: D-35 dated, ROADMAP/TODO/README/`specs/README.md`/metrics rollups, `cli-interface.spec.md` exit-code exception, consumer handoff packet | Integrator only, after C4 |

Execution graph: C1, C2 and C3 start together; C4 is the fan-in; C5 is integrator closure. The
only shared hot file is `core/tools.py`, split at function level between C1 (one lambda) and C2
(the dataclasses and the `ask` branch). No card owns `core/runs.py`, `core/approval.py` or
`core/dispatch.py`, and `edges/adapters/docket_runtime.py` changes only by one env-coordinate read
in C4 (the `DOCKET_PIPELINE_WORKTREE` precedent): the whole point of the design is that those are
consumed unchanged.

No live provider or subscription is a gate: every oracle runs against the loopback
OpenAI-compatible stub the approval tests already use, and the one real llama.cpp run is handoff
evidence, not a fixture. Cost stays `null`; token counts are the session's measured totals.

---

## PHASE 23 — Product truth and ecosystem proof  *(☑ COMPLETE 2026-09-14 — Waves 26–29; W29-C7's closing half removed by D-39)*

**Status:** ☑ COMPLETE (2026-09-14; active 2026-08-30, paused 2026-09-11) · **Decisions:** D-25, D-39 ·
**Board record:** Waves 26–29 in `docs/cycles-ended/todo-waves.md` · **Coordinator packet:**
[`docs/cycles-ended/handoffs/phase-23-productization.md`](docs/cycles-ended/handoffs/phase-23-productization.md) (Wave 26 closure packet; Waves 27–29 are recorded below)

### Why this phase is scheduled

The 2026-08-30 read-only audit inspected the live `platform` tree, its release surfaces, 24
current-state specs, 2,374 collected tests, and current open-source peers. The core governed loop,
durable pipeline, role-narrowed registry, typed handoffs, and one `dispatch_tool` policy chokepoint
are valuable. Adoption is nevertheless blocked before those strengths are reached:

- the default `anthropic/claude-sonnet-4-6` onboarding path stores a key but resolves no built-in
  endpoint, while only OpenRouter and Vercel have built-in compatible URLs;
- the recommended Homebrew formula has an all-zero SHA and the wrong license, the installer reads
  mutable `main`, the root wheel exposes `docket-py` rather than the documented `docket`, and the
  release workflow publishes no installable Python artifacts;
- `docket-runtime` and the full distribution install overlapping `docket/*` files;
- audit append, approval resolution, and port/conversation allocation contain unlocked
  read-modify-write transitions reachable from parallel dispatch or the threaded API;
- verdict gates depend on marker placement in free-form model prose, and shipped in-process
  cancellation changes state without interrupting the active turn.

These are deterministic findings from this repository, not generic market-feature requests. They
fire D-24's measured-need rule. The user explicitly requested the resulting productization and
ecosystem plan on 2026-08-30.

### Product boundary and exit contract

Phase 23 ships in this order:

1. **Trustworthy first use:** a clean install reaches one deterministic governed tool turn using a
   provider configuration the onboarding path can actually resolve.
2. **Truthful local governance:** concurrent decisions preserve one audit chain and one state
   transition; verdict and cancellation outcomes match what actually happened.
3. **Hardened single-host operation:** isolation, recovery, secrets, provider compatibility, MCP,
   and parameterized pipelines are improved only from measured Wave 26 evidence.
4. **Portable enforcement proof:** two external runtimes demonstrate the same policy, approval,
   budget, trace identity, and handoff contract before Docket claims framework neutrality.
5. **Adoption evidence:** reproducible releases, a starter integration, failure/chaos cases, and
   published completion/cost/safety/recovery measurements.

Phase 23 is complete only when those claims have executable evidence. It does not add a tenant
axis, hosted scheduler, Docket-owned dashboard, no-code workflow builder, provider-SDK zoo, or a
second orchestration graph language.

### Activation gate — satisfied 2026-08-30

Wave 25's 45 attributed paths landed in `6b925f0` after W25-C7's single authorized live acceptance.
The integrated commit passed 2,377 tests with five contract-labelled skips, Ruff, format, strict
mypy, 24 specs, 18 goldens, metrics, and deterministic smoke. The active-board marker changed once;
Wave 26 then completed on 2026-08-31. Central files (`ROADMAP.md`, `TODO.md`, `README.md`,
`specs/README.md`) remain integrator-owned.

### Wave 26 — first-use and governance truth (complete 2026-08-31)

Wave 26 contains independently shippable cards rather than one release-sized branch. Its initial
ready pool after activation is W26-C1, C2, and C6–C10; C0 is an integrator/maintainer decision, C3
depends on C0+C2, C4 depends on C1–C3, C5 depends on C2, and C11 is the final truth/release
integrator. The detailed trigger, non-goals, live paths, RED cases, acceptance oracles, gates, and
contention boundaries live once in `TODO.md`.

| Card | Outcome | Dependency / parallel boundary |
| --- | --- | --- |
| W26-C0 | One public release source/commit lineage | Done; `main` is canonical and synchronized without history rewrite |
| W26-C1 | Clean configuration reaches the first governed turn | Done; resolvable provider/onboarding path proven |
| W26-C2 | Canonical installable `docket` wheel/sdist | Done; root artifact owns the documented CLI distribution |
| W26-C3 | Immutable, checksummed release artifacts | Done (`0251972`, `5bb106a`); tagged package assets are verified before install/publish |
| W26-C4 | Clean-install-to-first-turn CI release oracle | Done (`f8f897e`, `6c52df7`); exact wheel reaches a governed turn on Ubuntu/macOS |
| W26-C5 | Non-overlapping, documented runtime distribution | Done; artifact boundary and ownership checks pass |
| W26-C6 | Atomic, durable audit append | Done; concurrent append/rotation preserves the chain |
| W26-C7 | Compare-and-set approval resolution | Done; contradictory concurrent winners are rejected |
| W26-C8 | Collision-free pod resource allocation | Done; allocation and rollback remain isolated |
| W26-C9 | Lost-update-free conversation mutation | Done; concurrent hop mutation preserves updates |
| W26-C10 | Cancellation scope split only | Planning-complete; superseded by C10a → C10b → C10c |
| W26-C10a | Persisted cancellation request/observe/stop lifecycle | Done (`0d24f7a`, `dc69142`); typed cross-process signal and atomic terminal winner |
| W26-C10b | Cooperative driver/loop/approval/tool checkpoints | Done (`3244fb2`, `d6eca09`); typed safe-boundary stop with atomic tool history |
| W26-C10c | Durable task/run reconciliation and truthful public surfaces | Done; whole-path oracle and cancellation wording agree |
| W26-C11 | Public branch, quickstart, installer, and claims match shipped behavior | Done (`dcce5b2`, `f9a4086`); Wave 26 closure truth and gates pass |

### Wave 27 — bounded post-W26 hardening and public front door (complete 2026-09-01)

Post-W26 triage activated exactly two independent cards. W27-C1 follows GitHub's high-severity
CVE-2026-69247 alert from the supported optional MCP graph to `cryptography` 49.0.0 and requires a
patched lock plus MCP compatibility evidence. W27-C2 follows the maintainer's explicit 2026-09-01
request and the measured 773-line README/stale-asset audit to a smaller public front door and one
reproducible current visual set. Detailed acceptance and ownership live in `TODO.md`.

Both cards closed on 2026-09-01. The lock now excludes the reported advisory range, and the public
front door is a compact, tested README backed by one reproducible three-asset terminal visual set.

The remaining Wave 27 candidate measurements are still unscheduled: an isolated coding profile and
scoped egress/secrets without silently changing D-23; recovery from corrupt or old persisted state;
real pipeline-variable injection; provider structured-output/streaming needs; MCP transport/cache/
capability metadata; and a supported local service/TLS-proxy/backup profile. Each needs a
representative fixture and a measured failure or explicit request. A built-in dashboard and tenant
model remain out of scope.

### Wave 28 — portable governance proof (complete 2026-09-02)

The bounded pass selected the standard OpenHands SDK `Agent` as the coding runtime and PydanticAI as
the general Python framework. OpenHands ACP is excluded from the proof because the ACP subprocess
owns its tools, context, approvals, and execution; Docket could delegate to it but could not prove
that every relevant action crossed Docket's chokepoint. PydanticAI's custom toolset seam is selected
over LangGraph's second graph language and Agno's broader hook/concurrency surface. Decisions D-32
and D-33 record the selection and evidence contract; detailed executable cards live once in
`TODO.md`.

Both adapters consume one artifact-installed governed-execution envelope and one scenario table.
The proof uses deterministic, credential-free models: a loopback OpenAI-compatible fake for
OpenHands and PydanticAI `FunctionModel`. It covers exclusive tool registration, native-bypass
absence, policy deny, approval deny/grant, Docket-owned reported-token/tool-call budgeting before
mutation, paired trace identity, existing audit semantics, and a typed terminal handoff. The base
runtime stays Python 3.11 compatible and dependency-light; the isolated OpenHands fixture uses
Python 3.12 because that SDK requires it. Port 8081 remains an optional local-model canary, never a
closure gate.

| Card | Outcome | Dependency / parallel boundary |
| --- | --- | --- |
| W28-C1 | Shared public execution envelope + common fixture contract | Done (`9f6a79c`, `d2e1b33`, `2e37361`); bounded facade and shared oracle shipped |
| W28-C2 | Standard OpenHands SDK adapter and coding fixture | Done (`071a744`, `c7d6a59`, `fbb4084`); nine Python 3.12 artifact cases pass |
| W28-C3 | PydanticAI custom-toolset adapter and general fixture | Done (`648dec5`, `a6c9197`); seven Python 3.11 artifact cases pass |
| W28-C4 | Cross-adapter installed-artifact parity, public truth, closure | Done (`3294f58`, `b1c9f44`, `739b1ca`); 37 focused tests, 2,490 collected tests, scoped claims, and Ubuntu/macOS artifact journeys pass |

No A2A card is activated because the selected coding proof is in-process and needs no remote task
discovery/state/cancellation. No OTLP card is activated because the fixture is explicitly required
to first prove whether the existing JSONL trace identity is sufficient. No plugin framework
precedes the two concrete callers.

### Wave 29 — adoption evidence and public release (complete 2026-09-14)

The bounded activation at exact commit `de08206` found zero extractable starter directories and zero
benchmark/baseline files. It reproduced a concrete recovery defect: `edges.store.write_json`
created a valid `.bak`, but corrupting the primary still made `read_json` raise `JSONDecodeError`.
Thirty-one existing policy-template, crash-resume, and release-contract tests passed, proving the
underlying mechanics should be reused rather than rewritten. `SECURITY.md` has a main-only security
support statement, but there is no deprecation, governance, or succession policy; CODEOWNERS and the
90-day Git history resolve to one human owner. Finally, current workflow code already builds wheel,
sdist, checksums, SPDX SBOM, and provenance, while the public `v0.2.0-beta.1` release predates it and
contains only a tarball plus checksum. Decision D-34 freezes these measurements and the activation
boundary.

Wave 29 therefore ships: safe JSON backup recovery; one copied-outside-checkout, credential-free
ten-minute starter; a deterministic and redacted benchmark schema/runner; adversarial plus
crash/recovery journeys using existing governance; truthful support/deprecation/governance/
succession policy; and one reproducible published baseline. The final current beta publication is
separate and explicit-approval-gated. It verifies existing supply-chain machinery rather than
building it again.

| Card | Outcome | Dependency / parallel boundary |
| --- | --- | --- |
| W29-C1 | Corrupt-primary/valid-backup recovery at the JSON-store chokepoint | Done (`4b796de`, `b673645`); 11 focused recovery/atomicity cases pass |
| W29-C2 | Extractable artifact-installed ten-minute starter | Done (`b138f25`, `16ef7bc`); copied artifact-installed public CLI journey passes |
| W29-C3 | Adoption benchmark schema and deterministic runner | Done (`a556fdc`, `2bf46a5`); 11 deterministic schema/runner cases pass |
| W29-C4 | Adversarial governance and crash/recovery benchmark scenarios | Done (`fcdff9a`, `0c8dac7`); 21 isolated C3-valid journeys pass |
| W29-C5 | Support, deprecation, governance, and succession truth | Done (`ac05dc3`, `c480e97`); 8 policy truth/counterexample cases pass |
| W29-C6 | Reproducible baseline and scoped public interpretation | Done (`82a3239`, `033bb4b`, `f789bc6`); exact hash and hosted closure pass in run `33812881329` |
| W29-C7 | Provenance-complete public beta and Phase 23 closure | Published `v0.2.0-beta.2` (2026-09-07; wheel, sdist, installer archive, checksums, SPDX SBOM, provenance attestation). The remaining half, a newer beta plus public-URL install on Linux and macOS, was removed on 2026-09-14 by D-39 |

No live provider or subscription is a gate; port 8081 stays optional. Deterministic results prove
contracts, not model quality. Dollar values are estimates with versioned assumptions or remain
`null`; failed attempts stay in the denominator. There is no leaderboard, competitor ranking,
savings claim, telemetry/A2A work, new adapter, or feature-count exit criterion.

---

## ⇢ STATUS AT A GLANCE — every phase, one line each

**Last updated: 2026-10-13.** **Phase 42 (lights-out profile and external gate, D-61, ADR 0025) opened and closed 2026-10-13**; paragraph below. **Phase 39 (one CLI surface, D-57) closed 2026-10-08** (paragraph below, after D-56), followed the same day by **Wave 96** (no phase: the live run's card A, `init` as a real Typer command, the linter gaps, the docs sweep) and **Wave 97** (the triage's cards B–E: `status` knows a parked question and the sandbox, help and messages tell the truth, the progress view names the hop, provider add records the advertised model). **Phase 40 (harden the agent boundary, D-58, ADR 0023) closed 2026-10-12** — the 2026-10-12 security audit's open items: thirteen cards over Waves 98–100; D-59 was answered (ADR 0024 §6) and Wave 100 shipped it (P40-5, P40-13), closing the phase at thirteen cards. **Phase 41 (one execution envelope, D-60, ADR 0024) closed 2026-10-13**: Landlock + seccomp on Linux, Seatbelt on macOS, Docker only when chosen, verify and `run:` steps inside the jail, a per-pod cache dir as the jailed home, the sandbox visible in `init`/`status`/`setup sandbox`/doctor, bwrap and `isolate: false` deleted, and an escape matrix that gates release; eight cards over Waves 100–103. Every numbered phase 0–42 is complete; no phase is planned. **Phase 26 (the configuration contract, D-42) closed 2026-09-26** (Waves 38–40, 20/20 cards): governance fails closed, pod settings are typed and writable (nine `pod config` keys), pipelines and prompt budgets are configurable per pod, and three shipped recipes prove the surface end to end. **Wave 37 closed 2026-09-25** (D-41): a triage that ran the product on six surfaces found twelve defects, fixed by six cards in two batches — the worst stalled every unattended dispatch whose command began with `cd`, and the sixth unwired-machinery instance (the installed console script skipped aliases and removed-command notices) is closed. **Wave 36 closed 2026-09-21** (opened 2026-09-19, D-40): eleven cards for the code-side defects the documentation audit of `v0.2.0-beta.3` found, run as three batches of one-card Sonnet workers under one integrator; the fifth unwired-machinery instance (blueprint pipelines) is wired, `POST /pods` validates project ids, and `--debug` is retired. **Phase 25
(human maintainability, D-36) and Phase 24 (harness mode, D-35) both completed on 2026-09-12**, the
first as Wave 31's thirteen cards and the second as Wave 30's five. **Wave 32 closed the same day** (2026-09-12): a
documentation truth pass over the drift those two phases left, plus the two follow-ups Wave 31
measured and deferred. **Waves 33 and 34 closed 2026-09-13**: an audit of the Wave 32 closure, repository hygiene, a docstring-only comment sweep (558/112 to 372/40 without changing a line of code), then the D-36 function split finished under a new function-span ratchet, two measured fixes, and a read-only audit that found the fourth unwired-machinery instance. **Wave 35 closed the same day**: a second docstring sweep (372/40 to 229/29), the dead `gatesEnabled` flag retired, and the integration lane's `SUBJECT` line given a rule and a guard. **Phase 23 closed 2026-09-14** (D-39): its release evidence is the `v0.2.0-beta.2` publication of
2026-09-07, and the card that would have published a newer beta was removed from the board.
**`v0.2.0-beta.3` was published 2026-09-18** as a maintainer action, the first with harness mode,
after CI on `main` went green again on the dependency floor and on macOS. The next release is
likewise a maintainer action, not a card. **Phase 27 (per-pod configuration and portable teams, D-43) shipped 2026-09-26**, ten cards
over Waves 41–43 (eight planned plus two defects found inside the phase: pod-overlay roles
dropped from the roster, `apply` skipping policies): roles, policies and MCP selection resolve
per pod above a global structural base, an MCP server declares its kind and tools, the Lead's
instruction is data, and the recipe directory is a manifest with `docket pod <p> apply|export`
proven by a round trip; reasoning in
[docs/adr/0009-per-pod-configuration-and-portable-teams.md](docs/adr/0009-per-pod-configuration-and-portable-teams.md).
**Phase 28 (configuration format v1 and the two extension points, D-44) shipped 2026-09-26**,
eight cards over Waves 44–46, one Sonnet worker per card under one integrator: a `kind` envelope
and one `docket validate`, short forms for roles, pipelines and policies over the unchanged
canonical form (each normaliser proven by a round trip), control flow as bounded data (`on`,
`until`, closed `when` predicates, command steps; the executor is `core/dispatch.py`, which the ADR
had mislocated), hashed, operator-applied Python predicate plugins for policies that are never
imported from the codebase, generated JSON Schemas and a short-form `export`; reasoning in
[docs/adr/0010-config-format-v1-and-extension-points.md](docs/adr/0010-config-format-v1-and-extension-points.md).
**Phase 29 (the provider catalog, D-45) shipped 2026-09-27**, seven cards over Waves 47–49, one
Sonnet worker per card under one integrator: model providers are `kind: provider` documents in two
scopes (fourteen built-in in the wheel, global for the operator) from which every provider table
derives, a closed `dialect` field selects the adapter, credentials are referenced by name only
(bearer, a named header, or none, plus static headers), registration verifies *with* the
credential and classifies the answer (only a transport failure refuses), `provider
add/list/show/remove/export` round-trip a document, `Retry-After` is honoured up to a 60 s ceiling,
`docket auth` is a removed command and `keys setup` walks the catalog, and `config explain` names
the provider, its scope and where the credential came from; reasoning in
[docs/adr/0011-provider-catalog.md](docs/adr/0011-provider-catalog.md).
**Phase 30 (the team lives in the repo, D-46) shipped 2026-09-27**, seven cards over Waves
50–51 (four Sonnet workers in parallel, then the integrator): a repository's `.docket/` directory
is the team's configuration of record — `docket init` validates it before provisioning and
applies it after (or `--recipe <name|dir>`; `--no-apply`), `apply`/`export` default to it, the
pod records `configSource`/`configDigest` so `config explain` reports drift, nothing is applied
without an operator command; a pipeline step may name its `model` for that hop only; `editRights`
is retired; running the product for the new assets found that a recipe's role applied into a pod
fell to the compiled-in default model on a local fleet (fixed: the archetype resolves in its
pod's registry, the fallback is the registry default); the three terminal assets were
re-captured from one real run under the `docket` wordmark and the README was rebuilt on the
tagline *agent teams as configuration, your rules, in YAML*, with its prose tests rebuilt from
that README rather than carried forward; reasoning in
[docs/adr/0012-the-team-lives-in-the-repo.md](docs/adr/0012-the-team-lives-in-the-repo.md).
**Phase 31 (recipes as a library, and the repository's standards, D-47) shipped 2026-09-27**, seven
cards over Waves 53–55 (four Sonnet workers in parallel, then two, then the integrator): a recipe's
scope is derived from its directory and shown by `validate`, `apply --dry-run`, `init --recipe` and
the new `docket recipes list|show`; `pod.yaml` gains `description`; `apply` records the source on
every validated apply; a name resolves against a path, `~/.docket/recipes/`, then the shipped
library, now twelve recipes of three kinds (teams, four policy packs on structured predicates,
five methodology pipelines: `tdd`, `spec-first`, `reflexion`, `dual-review`, `frugal`); the
repository's `AGENTS.md` composes by default as screened project instructions; skills follow the
Agent Skills shape in three scopes with a prompt index and one `skill` tool through the chokepoint
(three shipped recipes carry one); `docs/recipes.md` is generated from the recipes and checked in
CI. Running the suite found two unwired seams inside the phase (the `skill` tool's kind missing
from `BUILTIN_TOOL_KINDS`; `core/skills.py` absent from the runtime wheel's file list), both
closed in P31-6; reasoning in
[docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md](docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md).
**Phase 32 (observability as configuration, D-48) shipped 2026-09-28**, nine cards over Waves
56–59 (two, three and three Sonnet workers in parallel, then the integrator): the trace gains an
`llm_call` event with measured latency and a spec of its own; a neutral `Span`/`SpanEvent` model
in `core/telemetry.py` projects the existing vocabulary once with deterministic ids; a
destination is a `kind: exporter` document (built-in + global, closed `dialect`, credentials by
name) whose dialect selects the one edge module that knows the wire, v1 = `otlp-http` over stdlib
`urllib`; five ready built-ins (local collector, Jaeger, Langfuse, Honeycomb, Phoenix) that
`docket exporters enable <name>` authenticates and probes; a bounded pipeline that never blocks a
turn, started lazily by `run_turn`; `payload: metadata` by default so repository content never
leaves the host unless the operator says so; `pod.yaml` may name destinations; `config
explain`/`doctor` read the exporter's own health. Verified live 2026-09-28: a real dispatch
against a real `otel/opentelemetry-collector` produced real `gen_ai.chat` spans with measured
token counts, matching `docket trace` and a non-zero `exported` health counter; Langfuse's
round-trip stays open, named in `observability-export.spec.md` §"External verification" as
blocked on the operator's own credentials rather than skipped silently. Three independent cards
across the phase version-bumped the same still-Draft spec from the same base and conflicted on
merge — reconciled by hand each time, a predictable cost of two workers targeting one Draft
file, not a process failure. D-24's cut of the OpenTelemetry SDK stands; reasoning in
[docs/adr/0014-observability-export.md](docs/adr/0014-observability-export.md).
Board archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
**Phase 33 (export privacy levels, D-49) shipped 2026-09-28** (opened and closed the same day), six
cards over Waves 60–63 (one Sonnet worker, then two, two, then the integrator), triggered by the live Langfuse
run: every generation's Input/Output was empty, `payload: full` changed nothing a destination
renders, and the `metadata` denylist already let an approval's command line and run error text
leave the host. What a destination may see becomes a set of content classes (`toolArguments`,
`errors`, `toolResults`, `completions`, `prompts`, `instructions`) chosen per exporter as a level
(`minimal` default, `actions`, `conversation`, `full`) or an explicit `share:` list; an allowlist
where spans are built maps every attribute to one class and filters conversations per message
part; the model call records its content only when an enabled exporter asks; widening is a
confirmed, audited command; the level shows in `list`/`show`/`explain`/`doctor`, on the root
span, and in an offline `docket exporters preview`. Content uses the OTel GenAI `Opt-In`
attribute names, which Langfuse reads natively; reasoning in
[docs/adr/0015-export-privacy-levels.md](docs/adr/0015-export-privacy-levels.md).
Verified live at `minimal`/`actions`/`conversation` against a local collector and Langfuse with
canaries (none at `minimal`); that run found `tool_result` never recording its output and fixed
it. Follow-up recorded, not scheduled: the pipeline's idle flush can emit a session's root span
twice. Board archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
**Phase 34 (the operator loop, D-50) shipped 2026-09-29** (opened 2026-09-28), seventeen cards
over Waves 64–70 (one worker per card, Sonnet or Haiku, in isolated worktrees under one
integrator), triggered by the operator's request and three facts found reading the live path:
the only four real approvals expired unanswered, an in-turn `ask` under `serve --dispatch`
stalls every pod, and the Lead cannot ask anything although its prompt said it owns human
communication. Work that needs a human **parks** (`approvalMode: park`, a new `waiting_input`
state, single-use pre-grants matched by a stable args digest) instead of blocking a thread; the
Lead's intake is an opt-in pipeline pattern (a typed `TaskBrief`, a new `input` step, the
`intake` recipe, a deterministic resource pre-check); one derived inbox (`docket inbox`,
`GET /inbox`, the MCP `inbox` tool, Telegram `/status`) feeds every surface; notifications are
CloudEvents delivered by `kind: channel` documents (console, desktop, webhook signed per
Standard Webhooks, command, ntfy, email, Telegram by amendment of its Command grammar 7 and a new
`/answer` verb); questions and answers take the MCP elicitation shape and task states map one to
one onto A2A 1.0.0. Reasoning in
[docs/adr/0016-operator-loop-and-interop-standards.md](docs/adr/0016-operator-loop-and-interop-standards.md).
**The integrator's close (P34-17) added three seam tests no card owned alone** — the real HTTP
`POST /approvals/<token>` write route threaded into the pre-grant mechanism and a real
re-dispatch; `content: minimal` vs `actions` enforced at a real local `webhook` delivery, not
either card's own unit test; the operator's exact typed answer reaching the Lead's own re-entry
message via `## Operator answers` — and found two real defects by running the product rather
than reading it: the operator-loop scenario's own `eventsDelivered` counter read a
`channels-health.json` key that never existed, always `0` since it was written; `--live-model`
registered its provider after `docket init`, so that path had never actually completed `init`.
sweepBlockedSeconds dropped from the pre-Wave-65 baseline of ~12-13s to under a second
(deterministic, park removing the blocking wait) but measured 138.0s under the real local model —
real per-hop generation latency serialized across one sweep worker, a different cost than the one
`park` targets, named for a maintainer rather than acted on. Both named deferred triggers this
phase carries were evaluated at the close and did not fire: fewer than 10 real parked approvals
exist on this machine to measure the mid-turn-resume trigger against, and the one-worker-per-pod
trigger's scripted-backend condition does not hold (see the ADR's own "Deferred with named
triggers" section for the full reasoning). Board archived in
[docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md); packets stay in
[.agents/handoffs/wave-64-worker-packets.md](.agents/handoffs/wave-64-worker-packets.md). Nothing
is parked, except `cli-interface.spec.md` coverage for `docket inbox`/`channels`/`notify`/
`pregrant`/`explain interruptions`, named there for a follow-up card rather than backfilled under
this close's time budget.
**Phase 35 (docket in a harness-agnostic factory, D-51) opened 2026-09-29, closed 2026-10-04**: ten
cards over Waves 71–75. Carried to the next phase: the process-wide approval timeout for a run and
the answer reader's daemon thread (both in the archived Wave 73 block). It was triggered by the maintainer's request to architect docket's part of the
structured-agentic-engineering plan, and by facts read in the consumer:
- Tack runs docket as one of four interchangeable harnesses and no longer polls its HTTP API;
- Tack's U8 is blocked because no `harness-v1.1` exists;
- Tack declares docket's decisions `Unsupported`.

What the phase ships:
- an opt-in harness contract v1.1 carrying exactly Tack's four M3 items: process lifecycle
  events with cancellable process groups, questions on stdout answered on stdin, a written-path
  list, and `--token-file`;
- the caller's limits (`--max-tokens`, `--policy`);
- a recipe pipeline run in place (`--recipe`);
- pod dispatch keeps its evidence (verify output, commit, base, diffstat, `requireVerify`);
- two measured defects fixed (`guardrail_block.action`; pod-scoped `tokenBudget`).

docket executes and records but never certifies its own work; merge readiness and autonomy
belong to an independent verifier. Phases 36–38 (consultation and evidence packs,
verification-ready execution, the L4 envelope) are outlined in `TODO.md` and not claimable.
Reasoning and reversals in
[docs/adr/0017-docket-in-a-harness-agnostic-factory.md](docs/adr/0017-docket-in-a-harness-agnostic-factory.md);
packets in [.agents/handoffs/wave-71-worker-packets.md](.agents/handoffs/wave-71-worker-packets.md).

**Phase 36 (consultation packs and evidence-v1, D-53) opened 2026-10-04, closed 2026-10-04.** Eleven
cards over Waves 76–81: operator-v1.1 (`Question.kind`, `options[]`, `recommendation`, `Answer.optionId`),
`reason`/`actor` on approval grant and deny, approval packs (the model's rationale plus three
options), a `consult` built-in tool for every role capped by `maxConsultationsPerTask`, a per-pod
corrections ledger, evidence-v1 (one document behind the CLI, HTTP and the harness), and escalation
metrics. Wave 76 is a Phase 35 follow-up: the harness `files` list stops reporting verify artifacts
and paths dirty before the run. Carried to the next phase, by name: the parked consult question
crosses to the answering process through an in-process registry (it fails closed out of process);
`approve_task` is scoped to one turn; `question.taskId` in a single-turn harness consult is the
session key; options are not rendered in Telegram or channel notifications. A live run on the local
endpoint called `consult` and showed an approval pack, and a live pod dispatch parked a Lead's
`consult`, took the operator's non-recommended option and finished `done` on it (ADR 0018 "Live
run"). Reasoning in
[docs/adr/0018-consultation-packs-and-evidence-v1.md](docs/adr/0018-consultation-packs-and-evidence-v1.md).

**Phase 37 (verification-ready execution, D-54) opened 2026-10-04, closed 2026-10-04.** Nine
cards over Waves 82–84:
- one git worktree per task, created at claim and recorded on the task, instead of one per
  Implementer, so a task's evidence counts only its own change;
- `pre_input` screening of MCP tool results;
- the task's id and evidence commits as environment for command steps;
- a `no_progress` stop reason;
- recipe-declared, pod-scoped MCP servers, which a turn starts in its own root;
- the `anti-tautology`, `mutation`, `spec-writer`, `cross-family-review` and `code-intel`
  recipes.

Re-verifying the outline found two false claims ("recipes, no core change" and "an MCP pack as
recipes"), which the ADR corrects. A live run on the local endpoint dispatched two tasks back to
back with nothing merged. The second ran in its own worktree, on the new HEAD, and its `diffStat`
counted only its own change.

Carried to the next phase, by name:
- the redaction pattern in `core/trace.py` matches `sk=` inside `task=`;
- finished task worktrees have no retention policy;
- `fetch` results are not screened;
- the check recipes read their overrides from the process environment;
- the four Phase 36 items: the in-process consult registry, the turn scope of `approve_task`,
  the session key as a single-turn consult's `question.taskId`, and options not rendered in
  Telegram or channel notifications.

Reasoning in
[docs/adr/0019-verification-ready-execution.md](docs/adr/0019-verification-ready-execution.md).

**Phase 38 (the execution envelope, D-55) opened 2026-10-05, closed 2026-10-05.** Isolation on by default (bwrap
first, with a preflight that names the fix, and a jail in which a task worktree can commit); an
opt-in network lockdown mode; stdio MCP servers in the same jail; file tools that never follow a
symlink out of their roots; `pre_input` on `fetch` results; no docket credential in a task's
processes; one sweep worker per pod; a left boundary on the redaction pattern. Re-verifying the
outline corrected three claims (file tools are not moved into a subprocess, the lockdown does not
change ADR 0004's default, and docket has no issuer to mint per-task credentials from), and
deferred `kind: autonomy` until a verifier produces one. Reasoning in
[docs/adr/0020-the-execution-envelope.md](docs/adr/0020-the-execution-envelope.md).

Eleven cards over Waves 85–88. Two came from running the product: the live run found a posture
refusal retried three times (P38-10), and a measurement found `code-intel`'s `ast-grep` server
unable to start in the jail (P38-11). Integration found three more defects the workers' own suites
could not: 95 tests that depended on the host having bwrap, a jail escape through a writable
`.git/hooks`, and a symlink fix that still followed a symlinked directory. Two live runs on the
local endpoint (ADR 0020 "Live run"): a default-isolated task committed from inside bwrap,
`network none` failed name resolution and an MCP `dial` with `ENETUNREACH`, a lockdown with
isolation off was refused before any model call, and only `--no-isolate` let an MCP server write
outside the roots.

Carried to the next phase, by name: `doctor` does not list a pod's unjailed MCP servers; a
submodule's hooks are not overlaid read-only; docker's default image cannot commit and `--network
none` has no real-docker oracle; stopping `serve` waits for in-flight sweeps; worktree retention,
the check recipes' environment overrides and the four Phase 36 items; `kind: autonomy` and
credential minting stay deferred to their triggers. No phase is planned after this one.

**Waves 89–90 (no phase, 2026-10-05): the carried items, closed.** The operator asked to close
every item carried out of Phases 36–38; for the two deferred to a trigger (task-worktree retention,
options in channels) that request was the trigger. Ten cards: unjailed MCP servers visible per pod,
the jail unable to write a submodule's or a linked worktree's git metadata, a two-stage `serve`
stop, `docket pod <p> worktrees prune`, options in `conversation`-level notifications and Telegram
`/answer <task> <id>`, a real-docker oracle, `env:` on `run:` steps, the parked consult question
persisted, and `approve_task` across a task's later hops of the asking role on all four approval
channels. Review found the sixth unwired-machinery instance (the inbox never carried a task's
question) and five card defects; the live run found two more (a jailed commit with no git
identity, and a verify command's `__pycache__/` blocking every prune), and the documentation
capture a third (a policy `ask` on `consult` asked approval to ask the operator). Reasoning and the run in ADR 0020 "Closed by Waves 89–90". `kind: autonomy` and
credential minting stay deferred. No phase is planned.

**Isolation is opt-in again (D-56, 2026-10-06, no phase).** The first CI run on hosts with no
sandbox (macOS) refused every turn, and the quick start had never named a sandbox as a
requirement. The operator decided isolation is opt-in: `docket gates isolate on` turns it on,
and once on it still fails closed. Everything else Phase 38 shipped stands. The feature and its
host requirements are documented in `docs/SECURITY-SIMPLE.md` "Workspace isolation (opt-in)".
Reasoning in [docs/adr/0021-isolation-is-opt-in.md](docs/adr/0021-isolation-is-opt-in.md).

**`v0.2.0-beta.4` was published 2026-10-06** as a maintainer action, from `develop` with CI green
on every job (pre-release; wheel, sdist, installer tarball, SHA256SUMS and SBOM all attested): the team in the repository, eighteen recipes, the provider catalog, trace export with
privacy levels, the operator loop, consultations and evidence, and opt-in isolation since
`v0.2.0-beta.3`. The Homebrew formula is pinned to the published asset (`3665dc25`).

**Phase 40 (harden the agent boundary, D-58, [ADR 0023](docs/adr/0023-harden-the-agent-boundary.md)) opened and closed 2026-10-12: thirteen cards over Waves 98–100; D-59 was answered in ADR 0024 and P40-5/P40-13 shipped it in Wave 100 (a repository's commands need the operator's OK, remembered until they change; `docket run` picks changes up; `pod apply` is `pod update`).** A
five-lane security audit on 2026-10-12 (plan and evidence in the gitignored
`internal-docs/security-audit-2026-10-12.md`) ran docket against a hostile repository on the
local model. It fixed eleven contained defects in the working tree in the same session — the
newline command-separator bypass, the `git -c … push origin main` regex, the approval-token path
traversal, the bwrap jail masking `DOCKET_HOME`, the store symlink and exclusive-temp hardening,
the Telegram poison-update wedge, the control-plane JSON body guard, trace redaction of
env-sourced and bare vendor tokens, `docket init` installing the baseline policies, pod-scoped
`on: input` policies reaching every screen, and the skill-body screen (specs security-gates
0.38.0, trace-store 1.7.0, mcp-client 1.10.0, agent-loop 1.33.0, telegram-integration 2.6.0).
Phase 40 schedules the open items as twelve cards for a multi-agent wave: audit every refused
tool call, a channel on enqueue/dispatch audit, an audit tail-truncation anchor, bounded audit
volume, the `docket init` apply-confirmation (P40-5, **blocked on D-59** because it narrows ADR
0012), a non-dumpable process so `/proc/<pid>/environ` cannot leak credentials to an unjailed
child, an untrusted frame around repository text in the system prompt, a same-host redirect lock
for authenticated requests, dropping the Telegram chat ids from the unauthenticated
`/status.json`, a real `fetch` deadline and timeout clamp, 0700 directory modes, and the
supply-chain pins (`code-intel` MCP server, `pyjwt`, `uv sync --locked`, SHA-pinned actions).
Model susceptibility itself is out of scope: the phase judges containment, not whether a model
obeys. The isolation-default and broad argument-path-containment questions stay deferred (ADR
0020/0021, D-56). Reasoning in [docs/adr/0023-harden-the-agent-boundary.md](docs/adr/0023-harden-the-agent-boundary.md);
cards archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). Integration findings at the Wave 100 close: the review code grew from 6 to 16 hex (a 24-bit code let a repository brute-force a change that matches a script's `--accept`), and the quick start and configuration guide had a bare `pod apply` applying `.docket/`, which ADR 0022 decision 5 had changed to a re-sync.

**Phase 42 (lights-out profile and external gate, D-61, [ADR 0025](docs/adr/0025-lights-out-profile-and-external-gate.md)) opened 2026-10-13.** docket is one of three tools (an orchestrator such as Tack, this runtime, an independent verifier) meant to run a lights-out factory at L3, L4 or L5, each usable alone. docket adds what lets an operator run it unattended without learning who the verifier is and without changing a fresh install: a `type: external` gate that maps an outside command's exit code to `pass`/`fail`/`needs_human`/`error` and routes each through the existing `on:` map (a human is an existing `input` step); the gate's output carried into the reworked hop, for mechanical gates too (a backward route re-ran its target blind); the repository's `AGENTS.md` and skills read from the task's `baseCommit`, not the agent-writable worktree; a `lights-out` profile that refuses to start a pod dispatch without isolation, network `none`, an external gate on every Implementer step, no HTTP MCP server and no secret-named injected variable; and evidence `1.1.0` with `gate` and `directives`. Accepted with amendments that cut the `exec` gate and profile flags, the override pack, risk and domain, the corrections export and the new ids, each with a named trigger (ADR 0025, last section). Seven cards over four sub-waves, scheduled by contention on `core/dispatch.py`: **A** P42-1 ∥ P42-3 · **B** P42-2 · **C** P42-4 ∥ P42-5 · **D** P42-6 ∥ P42-7. **Sub-wave A closed in Wave 104** (merges `5498d4b1` P42-1, `a0d58ede` P42-3): a gate that sends a task back now says why, and repository instructions and codebase skills come from the base commit; integration fixed a cross-thread registry race (a `ContextVar` now) and a false `GATE FAILED` on a backward `pass` route. **Sub-wave B closed in Wave 105** (merge `563c6508`, P42-2): the external gate; integration closed a gate bypass (the exit code came from a jail-writable file; now the process's own status via `system.run_command`) and a short-form `input` step that dropped its `on:` map. **Sub-wave C closed in Wave 106** (merges `44fe0a2e` P42-5, `30f56be3` P42-4): evidence 1.1.0 (`gate`, `directives`; the harness result stays 1.0.0) and the `lights-out` profile (`setup profile`, pod `profile`, a refusal before the first hop audited `profile.refused`). **Sub-wave D closed in Wave 107, and with it the phase** (merge `68c03f6d` P42-7: the network is reported as not enforced while isolation is off, on every surface including `pod show`; P42-6 docs `e29a996d`). **The live run found what the suites did not** (P42-8, `e9317013`): a `needs_human` question hid the verifier's reasons, the operator's answer never reached the retried Implementer, and a pass walked straight into the `input` step and re-parked the task (now refused at `validate` for a mechanical- or external-gated step unless `pass` is routed); `pod validate` also masked every error of a pipeline with an unquoted `on:`. Across the phase, adversarial review of green worker commits found a cross-thread registry race, a false GATE FAILED on a backward `pass` route, a gate bypass through a jail-writable exit-code file, and a dropped short-form `on:`. **Carried, unscheduled:** `core/profile.py` reads the injected variables through the private `dispatch._hop_env`; the inbox prints a multi-line question unindented; a `waiting_input` task can only be declined, not cancelled; the verifier's unannounced product name is in unpushed history from `e8774fad` until `e29a996d` (a maintainer decision before any push). **Deferred with triggers (ADR 0025 amendments):** `exec` gate and profile flags, a gate override, risk and domain, the corrections export, attempt ids and trace digests, a gate network grant.

**Phase 41 (one execution envelope, D-60, [ADR 0024](docs/adr/0024-one-execution-envelope.md)) opened 2026-10-12 and closed 2026-10-13 (sub-wave D, P41-8, in Wave 103: the escape matrix; Landlock keeps hooks and config read-only and refuses a root holding a `.git` directory; host-side git names the recorded git dirs); sub-wave A (P41-1 Landlock + seccomp jail, P41-6 the gate rule and network `none`) closed in Wave 100; sub-wave B (P41-5 a per-pod cache dir as the jailed home, P41-4 verify and `run:` inside the jail, P41-2 Seatbelt on macOS) closed in Wave 101 on 2026-10-13; sub-wave C (P41-3 bwrap and `isolate: false` deleted, Docker only when chosen; P41-7 the sandbox visible in `init`, `status`, `setup sandbox`, doctor and `install.sh`) closed in Wave 102 the same day.** Integration finding: since the gate now allows off-allowlist binaries on the promise of a jail, a sandboxed `bash` call that finds no backend at call time runs nothing instead of falling back to the host. Landlock cannot make a sub-path of a writable root read-only, so the bwrap `.git` overlay has no counterpart; P41-8 gained the row that proves an agent-rewritten `.git` file cannot make host-side git run its code. Wave 101 integration: the two parallel cards met at one function, `system.jail_launch`, which takes the pod cache dir as a read-write root; the seam test is a jailed verify whose `$HOME` write lands in the pod cache. Seatbelt is unit-pinned only until P41-8's macOS job runs it. Wave 102 finding: deleting bwrap removed the only Linux backend with read-only `.git/hooks`/`config` overlays; the Landlock jail grants the whole git dir read-write, an escape for an isolated agent, closed by P41-8 (RED on the base for hooks, config, the `.git` file, `commondir` and `config.worktree`). **Carried, unscheduled:** the jail keeps `refs` writable, so an isolated agent can move another branch's ref (no code runs); the trusted-worktree record is registered by dispatch only, so CLI-side git (`task diff`) still reads the `.git` file; `docket exec` has no pod cache dir; Seatbelt and the macOS rows run only in CI; `docs/assets/isolation.png` still shows bwrap (re-capture).
The audit left the structural gap the cards could not close: the sandbox jails the agent's
`bash` only, while `verifyCmd`, `run:` steps and `isolate: false` servers run on the host, the
jail reads the whole disk with the network open, and bwrap is a system dependency CI containers
cannot satisfy. The maintainer's decisions, after comparing Claude Code, Codex CLI and OpenHands:
one envelope for everything the project runs; Landlock + seccomp on Linux (kernel >= 5.13, no
package, no user namespace), Seatbelt on macOS (ships with the OS), Docker only when chosen,
bwrap deleted; inside the envelope every command but a high-risk class is allowed and the
allowlist applies only outside it; the sandbox stays off by default (D-56) but is visible at the
end of `init`, the top of `status` and in `doctor`; network `none` by default inside the
envelope; `isolate: false` deleted in favour of a per-pod cache directory. Eight cards over four
sub-waves (contention: `edges/adapters/system.py`), with an escape matrix on real backends as
the release gate. Packets: `.agents/handoffs/phase-41-worker-packets.md`.

**Phase 39 (one CLI surface, D-57) opened 2026-10-07, closed 2026-10-08.** A read-only audit of the CLI (command
inventory, six journeys run live in a throwaway home, sourced best practices) found 46 flat
commands over 161 entry points with no real sub-command, 23 commands parsing their own action
word so that `--help` never works below the top level and an unknown flag is silently dropped
(`pod <p> dispatch --dry-run` ran for real), the pod named seven ways, three off-TTY policies for
destructive commands, bare `gates isolate` writing a security setting, and a `done` task's change
sitting in a worktree no command names. Re-verifying it found the **seventh unwired-machinery
instance**: the three org specialists and the portfolio manager are provisioned, listed and
health-checked and nothing ever runs one. The maintainer's decision, reached over three rounds
(the audit's 32, a cut to 22 on "does the noun answer its own question", a cut to eleven on
"does the name explain itself, and what owns it"; `pod` discussed and kept): `init status inbox
task run pod log setup start stop exec`, the pod resolved from the directory, approvals under the
task, the roster and the configuration under the pod, the machine's pieces under `setup`, one
interaction contract, one role vocabulary, and every redundant or agent-era command, the
per-agent pin, the persona layer and the specialists deleted outright with no alias, notice or
migration, with that rule written into `CONTRIBUTING.md`, `AGENTS.md` and §3 below. Twenty-four
cards over Waves 91–95 (foundation; the mechanical registry split; the groups; help, guards,
docs and assets; the live re-measurement). Reasoning in
[docs/adr/0022-one-cli-surface.md](docs/adr/0022-one-cli-surface.md); packets in
`.agents/handoffs/wave-91-worker-packets.md`.

**Wave 96 (no phase, 2026-10-08): the live run's card A, closed.** The Phase 39 live run left
eighteen locators; a read-only triage (gitignored `internal-docs/cli-ux-audit-2026-10-07/
triage-2026-10-08.md`) found nine defects, nine by design, and proposed five cards A–E. The
operator asked to continue and A was the only one where a spec MUST was false: `task approve
<apr-token>` ended without the run hint, and a deny's reason reached trace and audit but never its
task (the correction was keyed by a field no gate wrote; the task's reason was the fixed `approval
denied`). One card, `50da5d59`: the pod comes from the approval record, the reason rides into the
task as `approval denied: <reason>` and the correction carries the task's id (operator-loop 1.5.2,
pod-dispatch 6.36.2, cli-interface 2.1.1). The same day, with no card: `docket init` became a real
Typer command with a one-screen help (`a49abba0`, cli-interface 2.1.0), the invocation linter
closed its two gaps (`ebbc7b64`) and six docs were swept of pre-Phase-39 names in prose
(`d8be1e24`). B–E followed as Wave 97 (next paragraph).

**Wave 97 (no phase, 2026-10-08): the live run's cards B–E, closed.** The operator asked to close
every pending item; the four remaining triage cards ran as one worker each in isolated worktrees
off the claim commit (`c540afcc`), packets in `.agents/handoffs/wave-97-worker-packets.md`,
merged E, B, C, D. B (`48b10796`): `status` counts a `waiting_input` task (`tasks.waitingInput`,
`N waiting input`, pod `waiting`) and its `Isolation:` line reports the sandbox posture from the
`setup sandbox` reader instead of a fixed phrase (cli-json-shapes 1.27.0, cli-interface 2.1.2).
C (`7b8b14ae`): the five task-verb examples pass a task id, `pod set` says `invalid value` for a
rejected value, the forecast pluralises and a policy interruption is described by its predicate
kinds, never the regex (operator-loop 1.5.3, pod-dispatch 6.36.3). D (`f99bbf9a`, decision on the
card): the progress view names the task on its session lines and prints an indented `▶ <hop> …`
as each hop starts, from dispatch's existing hop marker; no trace event was added (cli-interface
2.1.3). E (`805b44fc`): `setup provider add` without `--model` records the first id the one
registration probe advertises (model-profiles 3.3.0). Every gate green on the rollup. Nothing
from the live-run triage is open; the two maintainer-owned items (Tack's string, the asset
re-capture) stay with the maintainer; no phase is planned.

Twenty-five cards over Waves 91–95 (P39-25, the invocation guard, was added in Wave 95 from a
Wave 94 lesson: a rename guard proves the old names gone, and only a check against the live tree
proves the new lines true). Sonnet workers in isolated worktrees, Haiku for the documentation
sweeps, one integrator. Integration found what the workers' suites could not: a seam between the
pod resolver and the groups that each card had passed alone, a conflict where two cards deleted
the same function, and about twenty invocations in the documentation sweeps naming verbs the tree
lacks. The live re-measurement (ADR 0022 "Live run", 2026-10-08): none of the audit's sixteen
defects reproduces, the newcomer path types no pod name, a fresh machine reaches `Ready` through
`docket setup` alone, every help level has an example, and the checklist scores 18 of 20 (the
bare-name library readers; no hint switch).

Carried, by name: Tack's one string (`"harness", "run"` to `"exec"`) and the live asset
re-capture, both refused by the integrating session's permission classifier and the maintainer's
to run; the landing page after the release that ships the names; the eighteen live-run locators as
a triage list; two gaps in the invocation linter. No phase is planned after this one.

> **How to read the rest of this file.** Nothing below is a task list; executable cards are in
> `TODO.md`. **The completed phase records (0–25, the Bash→Python migration) and this file's
> decision changelog were moved verbatim to [docs/cycles-ended/](docs/cycles-ended/README.md)** (`roadmap-phases.md`,
> `roadmap-changelog.md`, SHA-256 manifest). **This table is the authority; a phase heading is not.**

| Phase | What it was | Status |
| --- | --- | --- |
| 0–4 | Truth & correctness, cost enforcement, consolidation, park experiments, strengthen | ☑ done |
| 5 | Channel portability + system snapshot | ☑ done |
| 6 / 6b | Model & provider agnosticism · tier-less role→model policy | ☑ done |
| 7 | *Renumbered away* — the former "Product & community"; folded into 11–13 | — n/a |
| 8 | Agent observability, guardrails & drift (HITL) | ☑ done |
| 9 | Contract integrity: spec↔runtime gap | ☑ done |
| 10 | Agent architecture: project pods | ☑ done |
| 11 | Competitive differentiation | ☑ done (2026-06-25) |
| 12 | Consolidation & hardening | ☑ done (2026-07-02) |
| 13 | Close the differentiation gaps | ☑ done (2026-07-02) |
| 14–18 | **Platformization I–V** — dispatch hardening, wired governance, declarative orchestration, context/memory, runtime-driver port + MCP | ☑ done (38 cards, 7 waves, closed 2026-07-31) |
| 19 | **docket takes the runtime (D-19)** — owns the loop, registry, all three policy hooks, approvals, audit, sessions. No daemon. | ☑ done (13 cards, waves 8–11) — **record in `docs/cycles-ended/todo-waves.md` + §Changelog; this file has no Phase 19 section** |
| 20 | Fleet observability | ☑ done **at cut scope** — D-24 cut ~half; P20-2 shipped, P20-4 was a phantom card |
| 21 | The product substrate (`packages/docket-runtime/`) | ☑ done **at cut scope** — P21-1, P21-5 shipped; rest cut by D-24 |
| 22 | Control-plane write API for an external plan-of-record | ☑ done (6 cards, wave 16, 2026-08-04) |
| 23 | **Product truth and ecosystem proof (D-25)** — first successful turn, trustworthy release, atomic governance, then portable enforcement evidence | ☑ **complete (2026-09-14)** — Waves 26–29. Release evidence is the public `v0.2.0-beta.2` (wheel, sdist, installer archive, checksums, SPDX SBOM, provenance attestation); W29-C7's remaining half, a newer beta, was removed by D-39. Record in `docs/cycles-ended/roadmap-phases.md` |
| — | **Waves 17–18** (not phases): MCP-tools-in-a-turn, config single-owner, audit chain across rotation, isolation actually wired | ☑ done (2026-08-05) |
| — | **Wave 19** (not a phase): the defects a *real* dispatch on a *real* small-context endpoint found — worktree members told an unreachable root, tool-output ceiling unreachable from config | ☑ done (2026-08-05) — its remaining session-compaction finding was carried into and closed by Wave 20 |
| — | **Wave 20** (not a phase): bounded contributor harness + live-turn context efficiency | ☑ done (2026-08-19) — repo skills/hooks, MCP output parity, live fail-closed and hierarchical compaction, measured cross-hop redundancy, and step-scoped durable history shipped |
| — | **Wave 21** (not a phase): daemon-free current-state truth pass | ☑ done (2026-08-19) — current contracts, docs, source prose, and hermetic fixtures now describe only Docket-owned runtime/state; explicit migration history preserved |
| — | **Wave 22** (not a phase): observable whole-product workflow proof | ☑ done (2026-08-19) — one hermetic command crosses CLI subprocesses, loopback HTTP, the runtime/tool/gate path, approval resume, and durable observability state |
| — | **Wave 23** (not a phase): real local-model workflow + reachable startup state | ☑ done (2026-08-19) — an opt-in Qwen canary crosses the full workflow; bounded HEARTBEAT/AGENTS/TOOLS/MEMORY context now reaches every live turn without widening tool roots |
| — | **Wave 24** (not a phase): realistic memory-backed Git maintenance | ☑ done (2026-08-19) — exact durable memory fails closed on corruption; real worktree code continuity reaches Reviewer/Tester; public plus hidden acceptance passes on the local model |
| — | **Wave 25** (not a phase): live-model request and outcome truth | ☑ done (2026-08-30) — all 11 cards and the live private-boundary canary passed; integrated at `6b925f0` with full commit-level gates green |
| — | **Wave 26** (not a phase): first-use, release, atomic-governance, cancellation, and public truth | ☑ done (2026-08-31) — all cards through C11 shipped; artifact journeys, public docs, and full closure gates pass |
| — | **Wave 27** (not a phase): dependency safety and public front door | ☑ done (2026-09-01) — advisory closed and reproducible public assets/README shipped |
| — | **Wave 28** (not a phase): portable governance proof | ☑ done (2026-09-02) — installed-artifact parity, scoped public truth, and Linux/macOS closure evidence pass |
| — | **Wave 29** (not a phase): adoption evidence and public release | ☑ complete (2026-09-14) — C1–C6 shipped; C7 published `v0.2.0-beta.2` on 2026-09-07 and its closing half was removed from the board by D-39 |
| 24 | **Harness mode (D-35)** — docket as a governed, non-interactive execution harness a plan-of-record (Tack) spawns as a subprocess | ☑ **complete (2026-09-12)** — Wave 30, five cards. `docket harness run`/`status` ship with a published, versioned, test-pinned contract; the three seams it needed are wired and proved reached by a real subprocess |
| 25 | **Human maintainability (D-36)** — test lanes with a budgeted agent lane, one unit file per module, zero-archaeology comments ratcheted in CI, generated CLI/API docs, board and roadmap cut to size | ☑ **complete (2026-09-12)** — Wave 31, thirteen cards. The board and roadmap reached their line targets on 2026-09-14, when the Wave 29 and Phase 23 sections archived |
| — | **Wave 31** (not a phase): baseline → lane move → structural guards → comment hygiene → per-module merges → in-process CLI tests → generated docs → board archive → split the three 500-line functions | ☑ complete (2026-09-11 to 2026-09-12) — thirteen cards W31-C0…C10, C8 split in two; C9 and C10 opened by defects the work surfaced |
| — | **Wave 30** (not a phase): in-flight bash cancellation, non-interactive approval outcome, trace subscriber, harness contract + command | ☑ complete (2026-09-12) — five cards W30-C1…C5. C1 merged on a second pass after a pipe-drain regression; C2 and C3 formed a seam that emptied the contract's blocked payload until a round-trip test was added |
| — | **Wave 32** (not a phase): documentation truth pass — four parallel audits over disjoint doc groups, then seven cards splitting the drift Phases 24 and 25 left | ☑ complete (2026-09-12) — removed a script, CI workflow and hook that never existed; swept a repeat of defect W19-5 from the quick start; and found one anti-pattern in three places, a spec index, an env-var table and a blueprint list each checked against retyped rather than derived reference data |
| — | **Wave 33** (not a phase): audit of the Wave 32 closure, repository hygiene, docstring-only comment sweep | ☑ complete (2026-09-13) — the closure held (gates, baselines, metrics all in sync); fifteen merged worktrees, eight merged branches, a spent migration script and two never-running skips retired; thirteen bounded docstring packets merged, each proved AST-identical with docstrings stripped, and the comment baseline ratcheted to 372/40. Found the gitignored CLAUDE.md still calling session compaction unwired two waves after W20-C2 wired it |
| — | **Wave 34** (not a phase): finish the D-36 function split behind a function-span ratchet, two measured fixes, one read-only audit | ☑ complete (2026-09-13) — `tests/guards/test_function_span.py` (150-line ceiling, closures included) listed seven functions; C1 to C4 split `run_agent_turn` (909 lines, twenty closures), `compact_session`, `do_POST` and `_doctor_json` with zero behaviour change, each proved by an unchanged public API and untouched tests, leaving one deliberate entry; C5 made the harness cancellation test deterministic under load; C6 gave the duplicated provider credential table one owner; A1 found the fourth unwired-machinery instance, `docket gates enable/disable` writing a flag nothing on the live path reads while spec, README and command help claimed it changed delivery, and C7 made those claims true (wire or retire stays an open maintainer decision) |
| — | **Wave 35** (not a phase): second docstring sweep, one dead flag, one lane rule | ☑ complete (2026-09-13) — six docstring-only packets (C1 to C6) over twenty-five modules, each proved AST-identical with docstrings stripped, took the comment baseline from 372/40 to 229/29; C7 retired `FleetSecurity.gatesEnabled`, a flag with no live-path reader and no product writer (spec 0.19.2); C8 made every integration test's `SUBJECT` an importable `docket` path, guarded by `test_layout.py` (spec 2.17.0, seen red on seven free-text values). Two things the wave found on the way: `scripts/gen_cli_docs.py --check`, a CI job, had raised ImportError since the Wave 34 credential-table merge because the integrator's batch gates never ran it (fixed, and added to the gates), and the `maintain sessions` banner still said sessions are never compacted (corrected) |
| — | **Wave 36** (not a phase): eleven code-side defects found by the 2026-09-19 documentation audit (D-40) | ☑ complete (2026-09-21) — three batches by file contention, ten code fixes and one prose sweep, all eleven merged with RED tests; C6 proved live on the local endpoint (research pod 5 hops to done, ops pod reaches `waiting_approval`). Batch 1: project-id validation at the core provisioning boundary (C1), `docket mcp servers add` unreachable through Click (C2), MCP approvals that never resume a dispatch task (C4), `maintain rebuild` bare-deleting memory (C5), blueprint pipelines never executed — the fifth unwired-machinery instance (C6), verify-command orphans on timeout (C7). Batch 2: HTTP approval-channel forgery (C3), CLI `--json` types (C8), the inert `--debug` flag and PRICE-override claim (C9), budget warnings that read a cost that is always zero (C10). Batch 3: a docstring and spec sweep (C11). Cards in [TODO.md](TODO.md); worker packets in [.agents/handoffs/wave-36-worker-packets.md](.agents/handoffs/wave-36-worker-packets.md) |
| — | **Wave 37** (not a phase): defects found by running the product (D-41) | ☑ complete (2026-09-25) — opened and closed the same day from a six-surface triage; all six cards merged with RED tests, full gates green, and live evidence on the local endpoint (the journey dispatch reaches `done — 3 hop(s)` with `APPROVE`; a `cd`-prefixed production push still asks). Two batches by file contention: bash allowlist + `policies test` parity (C1), exactly-once trace cursor and HTTP contract gaps (C2), console script bypassing aliases and removed-command notices — sixth unwired-machinery instance — plus `help <command>` (C3), harness-v1 schema references (C4); batch 2: approval conflict vs not-found and the measured flake (C5), `cost <id> --json` and unknown-flag rejection (C6). Archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md); packets in [.agents/handoffs/wave-37-worker-packets.md](.agents/handoffs/wave-37-worker-packets.md) |
| 26 | **The configuration contract (D-42)** — every operator-facing setting has one writer, is validated at write, has a live consumer on the default path, fails closed (governance) or loud (everything else), is observable with provenance, and survives regeneration | ✅ **complete 2026-09-26** (opened 2026-09-25; Waves 38–40, 20/20 cards, one integrator + Sonnet workers in isolated worktrees). A live E2E connection audit (pod → config → custom-role pipeline run, two tasks to `done`) added P26-18 (membership guessed from the id string breaks hyphenated custom roles), P26-19 (a deterministic refusal orphans the task as `running`) and P26-20 (shipped, CI-validated recipes). Governance first: a malformed `block` policy currently fails **open** (P26-1). Context budgets follow the model window instead of a fixed ~24 KB (P26-2/P26-3). Reasoning: [ADR 0008](docs/adr/0008-configuration-contract.md) |

**Deliberately NOT scheduled**, and not a queue to work down — each is cut or deferred behind a named
trigger (see §4.5's prioritization rule, D-24, and §7):

| Not doing | Why |
| --- | --- |
| Multi-tenancy / the tenant axis | **CUT** (D-22, D-24). Trigger to revisit: docket itself serving more than one end customer from one host. |
| Streaming · browser automation | **CUT** by D-24 — no measured need in *this* system. Use MCP for browser tooling. |
| OpenTelemetry **SDK** | Still cut (D-24). What Phase 32 (D-48) schedules is a projection of docket's own trace vocabulary to OTLP/HTTP behind a `kind: exporter` document, with zero dependencies; the SDK, OTLP metrics/logs, sampling and context propagation stay out. D-25's two-runtime trigger governs anything beyond that. |
| Egress lockdown | Shipped as an opt-in mode in Phase 38 (D-55): `docket gates network none`; the default stays open (D-23), and `fetch` remains the inspectable path. |
| A dashboard of our own | Ruled out since Phase 11 and reaffirmed by 22 — docket feeds one. |
| Build-agent profile · MCP listing cache · Go/Rust rewrite | Deferred behind named triggers. |

Session compaction is no longer in this deferred table: its trigger fired and W20-C2/C2b shipped
the live fail-closed and hierarchical paths. W20-C3 then measured material cross-hop duplication,
and W20-C4 closed it with step-scoped durable histories while preserving typed handoffs.

**Known-true limits live in [README.md](README.md#known-limits)**, not here — they change faster
than this file.

**Release:** `v0.2.0-beta.3`, cut 2026-09-18 and published by `release.yml` with wheel, sdist,
installer archive, checksums, SPDX SBOM and a GitHub provenance attestation. Changes after it
land under `CHANGELOG.md` `[Unreleased]`; cutting the next beta is a maintainer action through
`release.yml`, not a board card. Every release carries a SemVer `-beta.N` suffix until the project is field-hardened enough to
drop it (see README's beta warning).

Status legend used in the older sections below: ✅ / ☑ done · 🟡 planned-next · 🟠 audit-driven,
planned · 🚧 in progress · 🗓️ planned / deferred

> **Consolidation note (2026-06-23):** this file is now the **single roadmap**. The former
> `ARCHITECTURE-AUDIT.md`, `MIGRATION-PLAN-PYTHON.md`, and `MIGRATION-TASKS.md` were folded in
> here and removed — their durable content lives in `docs/cycles-ended/roadmap-phases.md` (completed migration) and §4.5
> (architectural principles); their executable task boards are spent (the migration shipped).
> Git history retains the originals.

## Tracked decisions (not yet scheduled)

- 🗓️ **Project rename (deferred).** "docket" collides with Ruby Docket, is a generic word, and is
  hard to search. The decision is to **keep "docket" as an independent product name for now** and
  revisit a searchable, namespace-clean rename (candidate: `docketctl`) before any wide public
  launch. Do not anchor positioning to the retired runtime: D-19 made Docket own the loop and
  removed that compatibility relationship. Touch points a rename must update: binary
  name, `install.sh`/`uninstall.sh` paths, Homebrew `Formula/`, docs, and the metrics script.
- ☑ **Version-pinned CI for the retired daemon — CUT (2026-08-19).** Superseded by D-19's clean
  break: Docket has no daemon binary, adapter, shared schema, package dependency, or compatibility
  layer to test. Current compatibility is the OpenAI-compatible model endpoint plus optional MCP,
  as recorded in [COMPATIBILITY.md](COMPATIBILITY.md). Installing an unrelated runtime weekly would
  add a false signal rather than protect a live contract.
- ☑ **Telegram conversation memory (TC-1…TC-7, shipped 2026-07-20).** A live investigation
  (triggered by the docket Telegram group dropping an accepted task across a context reset) found
  three gaps *beyond* the memory-durability fix (WORKFLOW_AUTO `CONTRACT_VERSION` v3): split
  identity from leftover external-runtime scaffolding, no durable conversation persistence, and no
  registry. **Delivered:** docket-owned identity — optional `Persona` on `AgentMeta` rendered into
  `SOUL.md`, `docket persona`, and `docket doctor` quarantine of `IDENTITY.md`/`BOOTSTRAP.md`
  (`core/identity.py`); a docket-owned **conversation registry** (`core/conversations.py`,
  `docket conversations list/show/resume/set`, seeded at `docket wire`); and a doctor advisory on
  the memory index. TC-3 established the retired runtime's per-agent sqlite as a rebuildable RAG
  index (not a transcript), so durability is docket-owned by design. Full record:
  [internal-docs/telegram-conversation-memory.md](internal-docs/telegram-conversation-memory.md)
  and [agent-structure-analysis.md §6](internal-docs/agent-structure-analysis.md). Deferred:
  `--persona` at `docket add` time; auto-populating `last_message`/`task_ref` from dispatch/serve.
- ☑ **External "opencode" audits evaluated + dismissed (2026-07-20).** Two agent-generated audits
  (`DESIGN-PATTERN-AUDIT.md`, `SECURITY-AUDIT-REPORT.md`) were reviewed against the code and
  **deleted** as net-negative: they fabricated non-existent functions (`_create_agent_meta`,
  `exec_in_workspace`), flagged a dispatch "layer violation" that doesn't exist (`core/dispatch.py`
  delegates execution through the runtime driver and system adapter, no raw subprocess), cited a stale
  `_install.py` size, and otherwise recommended cargo-cult OOP against the deliberate
  functional style. The **one** actionable idea — a boundary guard — was implemented as the true
  invariant: `tests/guards/test_no_subprocess_in_core.py` (core/ must be process-free),
  a sibling of the CH-3 no-UI-in-core test. Its optional adapter-split suggestion became moot when
  D-19 deleted the external-runtime adapter outright.

> Read §1–§4.5 once for mission, ground truth, conventions and principles; then take work only
> from `TODO.md`. Completed phase records are in `docs/cycles-ended/roadmap-phases.md`.

---

### Build vs. wrap: ~~docket wraps OpenClaw, decisively~~ — **REVERSED by D-19**

> **Read this box before the section it introduces.** D-19 (2026-07-31) **took the runtime**. docket
> now owns the turn loop, the tool registry, all three policy hooks, approvals, audit and sessions,
> and rents protocols only. The ACL is gone; so is the daemon. The section below is kept **because
> the reasoning was sound and the trigger it named is exactly what fired** — not as live guidance.
>
> **What actually forced the reversal, and it is the durable lesson:** docket shipped four
> `pre_tool_call` policy templates that had **never once been evaluated**, because the daemon owned
> the inside of a turn. The wrap boundary was not merely limiting the roadmap; it was making the
> product's central claim false. *Whoever owns the loop owns the interception points* — which is
> also why agent frameworks (LangGraph/CrewAI/AutoGen) are rejected on principle: they own the loop,
> and therefore the gates.
>
> **What survived the reversal, unchanged:** the "one typed port, one shipped driver" discipline
> (`core/runtime_driver.py`, `DocketDriver` — **not** a plugin framework), no DI/ORM/event-bus,
> boring typed Python, and the rule that a *second* driver needs a named trigger. The
> anti-overengineering table below still governs, with its "one backend (OpenClaw)" row read as
> "one runtime, ours".

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
- **The boundary makes it reversible:** the ACL (`edges/adapters/openclaw.py`, deleted by P19-7b when
  D-19 took the runtime) was the single place OpenClaw's shape lives, so build-vs-wrap stays a *reversible* bet, not a
  load-bearing assumption smeared across the codebase. **Do not build a plugin/`AbstractBackend`
  framework** — there is exactly one runtime; one concrete ACL behind a thin boundary is enough.
- **When standalone *would* become right (triggers, not dates):** OpenClaw stalls / repeatedly breaks
  compatibility / changes license or direction; the roadmap needs runtime-level capabilities upstream
  consistently refuses; or the ACL ends up working *around* OpenClaw more than *with* it. Even then,
  prefer absorbing a thin slice behind the existing ACL port over a full rebuild.
- **Critical consequence for every phase** *(revised 2026-07-30 per D-15)*: **docket orchestrates
  hops; the daemon executes every tool call inside a turn.** Since AA-7's real dispatch, docket *is*
  in the execution path for the dispatch lane and is accountable for its queue/state/retry
  correctness — the old "docket is not in the agent execution path" phrasing is retired. What
  survives unchanged is the split every feature must still declare: *pure-docket* (config,
  provisioning, metadata, templates, policy authoring, hop orchestration — ships first, fully
  testable) vs *daemon-gated* (anything that intercepts **inside** a turn — isolated behind a spike,
  never overclaimed). Phases 8, 10, and 14–18 are all shaped by this split.

> **Platformization amendment (2026-07-30, decisions D-14…D-18):** the Phases 14–18 program revises
> two lines above, deliberately and narrowly. (1) The `AbstractBackend` ban becomes "one typed
> **RuntimeDriver port**, one shipped driver" — formalizing the execution slice the ACL already
> half-owns, because the 2026-07-29 audit found that coupling leaking around it (session-JSONL cost
> parsing in `core/`, 11 argv shapes) rather than contained by it. A *second* driver still needs a
> trigger from the list above. (2) "Not in the execution path" is rewritten per D-15. Everything
> else in this section — wrap-don't-rebuild, no DI/ORM/event-bus, boring typed Python — stands and
> governs Phases 14–18 too.

