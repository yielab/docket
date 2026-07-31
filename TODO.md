# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> *Phase 13 (Close the differentiation gaps, FD-0…FD-7) is **COMPLETE** (2026-07-02).*
> *Phase 14 (Platformization I: runtime truth & dispatch hardening, R-1…R-8) is **COMPLETE**
> (2026-07-30) — its durable record lives in ROADMAP.md's Phase 14 section, including the honest
> "what was narrowed or deferred" list. Its board was cleared per the convention above. The two
> defects R-8 found but left unfixed (a stray merge-conflict marker in `serve.py`'s docstring and a
> backwards precedence comment in `config.py`) were fixed on `platform` in `facc78c`.*
>
> ---
>
> ## Active: PHASES 15 · 16 · 18 — Platformization II/III/V, executed in waves
>
> Executable board for **Phases 15, 16 and 18** in [ROADMAP.md](ROADMAP.md) (read those sections
> first — the defect rationale, the anti-overengineering rules, and each phase's exit criteria; also
> decisions **D-14/D-16/D-18** in §6 and the 2026-07-30 Platformization amendment in §4.5). Source of
> record: `internal-docs/agent-platform-audit-and-build-plan.md` (2026-07-29 four-pass platform audit,
> gitignored local rationale — every defect below was code-verified with file:line evidence and is
> restated self-containedly here).
>
> **Why three phases at once.** ROADMAP marks Phase 18 *"independent of 15–17 except L-5"* and Phase 16
> *"after 14; G-1 for approval steps"*. With Phase 14 green, the genuine blockers are narrow, so cards
> are scheduled by **file contention** rather than by phase number. Phase 17 stays out of this wave:
> C-1 depends on Phase 16's W-5, and C-2/C-3/C-5 all want `core/dispatch.py`, which is spoken for.
>
> **Scheduling rule learned in Phase 14 (keep it):** `core/dispatch.py` is the contention hotspot —
> nine remaining cards touch it. **At most one in-flight card may own `core/dispatch.py` per wave.**
> Phase 14 proved the payoff: cards with disjoint file footprints (R-6, R-7) auto-merged onto the big
> R-1 rewrite with zero code conflicts, while the two cards that both edited `serve.py`'s dispatch
> call sites (R-2, R-3) produced the only genuinely dangerous merge of the phase — each had to be
> hand-reconciled or one card's feature would have been silently dropped.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (always):** ROADMAP.md's section for the card's phase, §2 (Python ground truth), §4.5
   (architectural principles, incl. the 2026-07-30 Platformization amendment), [CLAUDE.md](CLAUDE.md),
   and the task's own "Read" list.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. OpenClaw formats live **only**
   in `edges/adapters/openclaw.py` (the ACL). docket-owned JSON goes **only** through `edges/store.py`
   (JSONL append logs are the one D-12 exemption). Every shell-out goes through `edges/adapters/`.
   `core/`/`edges/` never import `ui.py` or print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds new
   CLI surface — those cards say so and require regenerated goldens with the diff explained.
   **Regenerating a golden to paper over an unintended behaviour change is never acceptable**; W-6 in
   particular must prove the four legacy roles still emit byte-identical workspaces.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `bash scripts/validate-specs.sh` green · the card's own spec updated with a version bump +
   changelog entry, **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** this program lives on the long-running **`platform`** branch (a deliberate
fork-candidate line — see ROADMAP §8). One short-lived `pc/<card-id>` branch per task → merged into
`platform`, never directly into `main`.

---

## ▶ CURRENT STATE

**Waves 5 and 6 are both COMPLETE.** `platform` green: **1,684 tests** (`pytest` exit 0, zero
FAILED/ERROR), 18/18 goldens, 20 specs valid, 37 commands, `ruff` + `ruff format` + `mypy --strict`
clean, `metrics.py --check` in sync (and the guard itself is repaired — see below).

**Phases 16 and 18 are COMPLETE.** Phase 15 is down to its last card (G-3); Phase 17 is 3 of 5
(C-3, C-5 open). Durable per-card records: the `☑ Wave 5 shipped` and `☑ Wave 6 shipped` blocks in
ROADMAP.md's Phase 16 section. **Wave 7 is queued below.**

**Waves 3 and 4 are fully merged (11 cards).** Their durable record — what shipped, what was
narrowed, and the two integration defects that the gates did *not* catch — is the
`☑ Waves 3–4 shipped` block in ROADMAP.md's Phase 16 section. Per the board convention their
per-card entries were cleared from here; ROADMAP holds the history.

**Phase status:** Phase 16 **COMPLETE** (W-1…W-8) · Phase 18 **COMPLETE** (L-4/L-5 answered as
spikes) · Phase 15 at 5 of 6 (only **G-3**) · Phase 17 at 3 of 5 (**C-3**, **C-5**).
**Four cards remain in the entire Platformization program.**

### Two standing integrator checks (both earned the hard way)

1. **Never resolve a conflict in a roll-up table by picking a side.** `specs/README.md`'s status
   table, README's metric counts and the golden completion lists are edited by several branches at
   once, so *no side holds every change*. Regenerate from ground truth — the spec headers, the real
   CLI (`bash tests/golden/run.sh capture <case> <shell>`), the actual suite — and read the diff.
   This caught real regressions on three consecutive merges, including two that would have deleted a
   shipped command from the completion surface and one that silently downgraded three spec versions.
2. **A green guard is not evidence until you have seen it fail.** `scripts/metrics.py --check` spent
   all of Phase 14 reporting success while verifying nothing (comma-blind `(\d+)` claim regexes plus
   a silent skip for unmatched claims, against a README that had lost 3 of its 4 claims). Fixed:
   thousands separators are matched, and a README stating none of the tracked metrics is now a hard
   failure. When adding a guard, add a test that proves it fails on bad input.

---

## Wave 5 — ☑ COMPLETE (2026-07-30, all five merged; Phase 16 finished with it)

Merge order `l-4 → g-4b → w-4 → cl-2 → w-5`. Durable record: the `☑ Wave 5 shipped` block in
ROADMAP.md's Phase 16 section. **Tree: 1,512 → 1,600 tests**, 18/18 goldens byte-identical
throughout, 20 specs, 37 commands.

☑ **W-5** (`0d91b51`) typed `HandoffArtifact` replaces raw-text hop concatenation — **unblocks C-1**
· ☑ **W-4** (`9e6cd04`) cron, webhook→pipeline variables, `--follow`, `runs.cancel` audit
· ☑ **G-4b** (`fe7af1c`) `models.*` audit family · ☑ **CL-2** (`dac85c8`) dead-code register,
non-dispatch half · ☑ **L-4** (`312787e`) daemon-MCP-registry spike, answered with dated evidence.

**Three lessons this wave, all of them cheap to forget:**

1. **A fourth neither-side-is-correct conflict** (`audit.spec.md`): G-4b's draft said `models.*`
   shipped and `runs.cancel` was open; W-4's said the reverse. Both shipped the same wave, so
   neither card could see the other's merge. Either side alone publishes a spec claiming a shipped
   feature is missing. **Cards that close sibling gaps in one wave will always do this** — read both
   sides against the code, never pick.
2. **Worktrees start on `main`.** Three of five agents branched from `main` instead of `platform`
   and caught it themselves. **Name the base branch in every card prompt.**
3. **`CLAUDE.md` is gitignored on purpose** (`.gitignore:56`). It cannot travel on a card branch —
   a worktree agent's correction is invisible in the diff and must be applied by hand. Any card
   whose work makes CLAUDE.md untrue must say so in its report.

---

## Wave 6 — ☑ COMPLETE (2026-07-30, all five merged)

Merge order `l-5 → w-5b → c-1 → c-2 → g-2`. Durable record: the `☑ Wave 6 shipped` block in
ROADMAP.md's Phase 16 section. **Tree: 1,600 → 1,684 tests.**

☑ **G-2** policy engine on the live dispatch path · ☑ **C-1** context compiler (per-role token
budgets; R-7's byte cap retired **and its dead helpers deleted on merge**) · ☑ **C-2** memory
distillation, fail-closed, zero new deps · ☑ **W-5b** artifact diff producer · ☑ **L-5** gateway
spike, answered yes with no code needed.

**The carve-out experiment worked, and is worth repeating.** Three branches edited
`core/dispatch.py`. C-1 (`_hop_message` only) and W-5b (one function + one call site) auto-merged
with **zero** conflicts. G-2 conflicted once — at the artifact construction site — and it was the
dangerous kind: **neither side was correct**, and taking W-5b's verbatim would have silently undone
`pre_output`'s redaction by sourcing the artifact summary from raw subprocess output. **Function-level
ownership is a workable narrowing of the one-owner rule, provided every card reports exactly which
functions it touched** — which is what made this reconcilable.

**Fifth neither-side-is-correct conflict** (after `audit.spec.md`, `role-archetypes.spec.md`,
`specs/README.md`, `pod-dispatch.spec.md`). This is now a *predictable* consequence of running
sibling cards concurrently, not bad luck. Budget merge time for it.

---

## Wave 7 — queued (the last four cards of the Platformization program)

| Card | Phase | Blocked on | Note |
| --- | --- | --- | --- |
| **G-3 · High-risk classes enforced** | 15 | ready (G-2 landed) | Wire `resolve_command_action` — still **zero callers** — into every process docket itself launches, and into G-2's `pre_output` scan. Closes Phase 15. |
| **C-3 · One durable task state** | 17 | dispatch owner | Dispatch writes HEARTBEAT entries mechanically; `doctor` flags TASK_LIST⇄HEARTBEAT divergence. |
| **C-5 · Conversation registry auto-population** | 17 | dispatch owner | Dispatch/serve update `last_message`/`task_ref`. Closes Phase 17. |
| **CL-3 · Post-program dead-code sweep** | standing | after the above | Re-run CL-1's full-tree sweep against the ~5,000 lines waves 3–6 added. The register below is closed for its original scope; a program this size will have produced new orphans. |

**Scheduling:** C-3 and C-5 both write from the dispatch path. Either make **one** of them the
dispatch owner and defer the other, or repeat wave 6's function-level carve-out — it worked, but
only because every card reported its exact footprint. G-3's footprint (`core/security.py`,
process-launch sites) is disjoint from both.

**Deferred, not forgotten:** the **dependency floors** (`pyproject.toml` advertises `typer>=0.12`,
`rich>=13`, `pydantic>=2` while CI only ever resolves the locked current versions). Needs a
`--resolution lowest-direct` CI job; blocked on network access, not on effort. Do not raise the
floors blind.

---

## Dead-code register (CL-1, 2026-07-30) — the standing "no legacy code" work list

Produced by a full-tree sweep. **The non-dispatch half is DONE** — CL-2 merged in wave 5; the
three dispatch-local rows belong to W-5. Kept here as the durable record of what was decided and
why, because "we looked at this and chose to keep it" is worth exactly as much as "we deleted it",
and without the record the next sweep re-litigates the same rows.

**Operational note learned here:** `CLAUDE.md` is **gitignored on purpose** (`.gitignore:56`, "AI
assistant dev guidance (kept local, not published)"). It therefore **cannot travel on a card
branch** — a worktree agent that corrects it changes only its own copy, and the integrator must
apply the change by hand in the main worktree. Any card whose work makes CLAUDE.md untrue must say
so in its report; the diff will never show it.

### High confidence — ☑ all fixed (CL-2, except the dispatch row W-5 owns)

| Finding | Location | Blocked by | Note |
| --- | --- | --- | --- |
| ☑ **`core/sync.py` was an entirely dead module** | whole file | **fixed (CL-2)** — kept as the single implementation, `cli/_doctor.py` now calls `check_agent` instead of reimplementing it; `SYNCED_FIELDS` is now iterated rather than shadowed by hardcoded field names | `check_agent`/`check_all`/`Drift`/`SYNCED_FIELDS` have **zero** production callers. `cli/_doctor.py:280-334`'s `_check_drift` reimplements the identical model+sessionKey comparison inline without importing it. **Independently verified: zero `import sync` in `src/`.** Note CLAUDE.md describes this module as the thing that "keeps the two config sources in sync" — the docs and the code disagree. Prefer keeping `sync.py` as the single source and pointing doctor at it. `SYNCED_FIELDS` is dead even *within* `check_agent`, which hardcodes the field names instead of iterating it. |
| ☑ **`HEARTBEAT_FILE` unused; literal hardcoded in 9 files** | `core/memory.py:57` | **fixed (CL-2)** — constant used everywhere, following L-2's `GATEWAY_UNIT` pattern | The string `"HEARTBEAT.md"` is repeated across `cli/_agents.py`, `_pod.py`, `_install.py`, `_context.py`, `_doctor.py`, `cli/__init__.py`. Same shape as the `openclaw-gateway.service` duplicate fixed in L-2. |
| **`print()` inside `core/` — a layering violation** | `core/dispatch.py:1313` | **W-5 owns this** | `print(f"[dispatch] verification skipped...")` breaks the standing rule that `core/`/`edges/` never print; it should return a typed result for `cli/` to render. |
| ☑ **Zero-caller ACL functions** | `edges/adapters/openclaw.py` | **deleted (CL-2)** — `meta_write`, `set_agent_project_key`; verified gone from `src/` and `tests/` | `meta_write` and `set_agent_project_key` have no callers anywhere, tests included. |

### Medium confidence — ☑ all resolved (CL-2): two fixed, three kept with a dated in-code reason

| Finding | Location | Note |
| --- | --- | --- |
| `with_lock()` has no production caller | `edges/store.py:49` | `read_modify_write` has its own independent `_acquire` body rather than calling it; only `test_m2_data_layer.py` exercises it. **Re-check after W-2 lands** — W-2 is reworking the claim/locking path and may add a genuine call site. |
| `docker_ps()`, `git_current_branch()` | `edges/adapters/system.py:~166, ~223` | Zero production callers; each has a dedicated unit test. May be forward-looking scaffolding for a future doctor check rather than abandoned code. Genuinely ambiguous. |
| `validate_policy()` never called by the CLI | `core/policy.py:44` | Implemented and tested, but `cli/_policies.py`'s `_list()` does its own generic JSON parse. Either wire a `docket policies validate` command or remove it. |
| `VerifyResult.total_lines` written, never read | `core/audit.py:206` | Populated at 7 construction sites; no renderer or test reads it. **G-4b owns this** (it is the card already inside `core/audit.py`). |
| `dispatch_all_pods` flagged uncalled | `core/dispatch.py:1684` | **W-5 owns this** — wire it or delete it, and say which in the commit body. |

### Deliberately NOT dead — do not "clean these up"

- `core/security.py`'s `high_risk_bins`/`resolve_command_action`/`match_high_risk`/`is_high_risk` —
  documented in-code **and** in CLAUDE.md as deferred infrastructure for a daemon capability that
  does not exist yet. Intentional, not orphaned.
- `core/pipeline.py`'s `validate_pipeline()` — its own docstring says it awaits W-2's wiring.
- `edges/adapters/openclaw.py` importing `core/models.py`/`oc_models.py`/`runtime_driver.py` — a
  documented schema-only exception (pure typing modules), **not** a layering violation.

### Confirmed false positives (dynamic access — checked, not dead)

`cli/__init__.py`'s ~35 `cmd_*` functions (Typer-registered) · `serve.py`'s
`do_POST`/`do_HEAD`/`log_message` (`BaseHTTPRequestHandler` overrides) ·
`ConversationStatus.waiting`/`.done` (constructed dynamically from `--status`) · every
Pydantic `model_config` · `RuntimeDriver` Protocol members (used via runtime `isinstance`).

**Swept and clean:** `scripts/` (all referenced), `templates/policies/*.json` (all seeded via the
glob copy), no unconditional skips, no vacuous tests.

### Still owed — all of it now W-5's

The ~76 `_oc.AgentRunResult(...)` test call sites → `TurnResult`, the ad-hoc-double → `FakeDriver`
sweep, the legacy `CostTotals`/`DayRecord` decision, plus the two dispatch-local rows above
(`core/dispatch.py`'s `print()` and `dispatch_all_pods`). W-2 unblocked them; W-5 owns
`core/dispatch.py` and the dispatch-adjacent test families this wave.

---

## Known-open gaps carried forward (do not let these get quietly re-claimed)

From Phase 14's honest record — these are **still true** until the cards above close them:

- ~~Cancellation of an in-flight hop and parallel hop execution are not implemented~~ — **closed by W-2**
  (`docket runs cancel`; `agent_run` now spawns a process group there was previously nothing to kill).
  Three narrower gaps replace it: `runs.cancel` writes **no audit entry** (W-4 owns it), resuming a task
  that crashed mid-parallel-group **re-runs the whole group**, and approval gates are **rejected inside a
  parallel group** as a configuration error.
- `docket models set/preset/reset` still write **no audit entry** (G-4 follow-up — **G-4b owns it this wave**).
- Enforcement exists **only** in the pod-dispatch lane — spend or actions from a Telegram session or
  direct daemon use are entirely ungated, per D-9's "docket orchestrates hops" boundary.
- Per-argument daemon enforcement for allowlisted bins (`git`, `npm`) still does not exist (G-3 narrows
  this where docket itself launches the process; the daemon-side half remains backlog).
- `maxReworkCycles` has no dedicated CLI setter (set via the internal `meta-set` path).
- **`CLAUDE.md` had drifted badly and was re-trued by hand on 2026-07-30** (it is gitignored, so no
  card could have fixed it): it still advertised "Lobster Workflows" as a core capability nine
  merges after W-3 deleted that surface, and quoted 847 tests / 17 goldens against a tree with
  1,684 and 18. **Nothing guards this file** — `metrics.py --check` covers README only. Re-read it
  for truth at the end of each wave, or give it its own guard.
- ~~Hops still exchange concatenated raw text~~ — **closed by W-5**, and W-5b gave
  `files_changed`/`diff_ref` real producers. **`notes` still has no producer** and is documented as
  reserved. Do not read a populated-looking schema as populated data.
- ~~The policy engine is not on any live path~~ — **closed by G-2** (wave 6): `install` seeds the
  baseline policies, `pre_input` evaluates at enqueue, `pre_output` on every hop output, and the
  existing `cli/_metrics.py` reader needed no changes. **Still daemon-gated:** `pre_tool_call`
  (in-turn interception) — docket orchestrates *between* hops and is never inside a turn to
  intercept a tool call. And `resolve_command_action` still has **zero callers** (G-3, wave 7).
- Hops still exchange **concatenated raw text**, not structured artifacts (W-5, in flight this wave).
- **The runtime dependency floors in `pyproject.toml` are unverified.** They claim `typer>=0.12`,
  `rich>=13`, `pydantic>=2`, `pydantic-settings>=2`, `filelock>=3.13`, while CI runs
  `uv sync --all-extras --dev` off `uv.lock` and therefore only ever exercises the current versions
  (typer 0.26, rich 15, pydantic 2.13, filelock 3.29). Nothing has ever tested docket against the
  floors it advertises, so a `pip install docket` into an older environment may resolve a
  combination that has never run. The fix is a `--resolution lowest-direct` job in CI — either the
  floors pass and the claim becomes real, or they fail and get raised to what is actually supported.
  **Not attempted here: it needs network access to resolve the floor set, which this environment
  blocks.** Do not raise the floors blind — an untested floor and a wrong floor look identical until
  someone installs.
- ~~`scripts/validate-specs.sh` reports two spec references on one line as a broken reference~~ —
  **fixed by the integrator in `771f622`**, along with a second defect found next to it: `check_todos`
  ran its loop in a pipe subshell, so every warning increment was discarded and a spec full of TODO
  markers still reported zero warnings. Both were reproduced before being fixed.
