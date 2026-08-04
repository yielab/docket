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
> ## ☑ BOARD CLEAR (2026-08-04) — Phases 19, 20 and 21 all closed; nothing is scheduled
>
> **Phase 19 closed with wave 11.** All 13 cards shipped. The acceptance test for the whole phase —
> `command grep -ril openclaw src/` — returns only comments and docstrings narrating the removal;
> zero live string literals. docket now owns the loop, the tool registry, all three policy hooks,
> approvals, audit and sessions, and rents only protocols (OpenAI-compatible HTTP, MCP, containers,
> the Telegram Bot API).
>
> **The claim this phase existed to make true:** docket shipped four `pre_tool_call` policy templates
> that had **never once been evaluated**, because the daemon owned the inside of a turn. They are
> live now. So is Telegram as a **real** approval channel — a grant writes `channel="telegram"` to
> the hash-chained audit log, reversing a caveat carried since Phase 15.
>
> Executable board for **Phase 19** in [ROADMAP.md](ROADMAP.md) — read that section first, plus
> decisions **D-19** (own the loop, rent the protocols; clean break, no migration), **D-20**
> (**ANSWERED** — a factory for agentic products, so both: factory first, embeddable substrate
> second), **D-21** (package split, YES, *packaging only*), **D-22** (tenant axis, **CUT**), **D-23**
> (egress — `fetch` tool yes, lockdown deferred) and **D-24** (the prioritization ruling that cut
> roughly half of Phases 20/21) in §6. Phases 14–18 are all **COMPLETE**; their durable per-card
> record lives in ROADMAP, not here.
>
> **Scheduling rule, carried from Phase 14 and re-earned in wave 9:** schedule by **file contention**,
> not phase number, and state ownership at **function** level when a file is hot. `core/dispatch.py`
> was Phase 14's hotspot; `core/tools.py` is Phase 19's — wave 9 ran three cards against it by giving
> P19-9 only `ToolContext` + the `bash` registration, forbidding P19-10 the file entirely, and letting
> P19-5 import it unchanged. Zero code conflicts; the one real conflict (`config.py`, two cards
> appending constants) was resolved by keeping **both** blocks and then *importing the module* to
> assert nothing was lost — not by reading the diff and assuming.

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

## ☑ CURRENT STATE (2026-08-04) — the board is CLEAR. Wave 13 closed; nothing is scheduled

**Every scheduled card is done.** Phase 19 (13 cards), Phase 21's surviving two (P21-1, P21-5) and
Phase 20's surviving one (P20-2) have all shipped. P20-4 was dispatched and came back a **no-op** —
the gap it was written against had been closed by W-4 months earlier and never re-trued (see
ROADMAP's P20-4 card; the lesson is that a gap list is a claim about the tree and decays like one).

`platform` green at wave 13 close: **2,081 tests** (`pytest` exit 0, 4 env skips), 18/18 goldens
byte-identical, **25 specs** valid / 0 warnings, 37 commands, ~26,700 lines, `ruff` + `ruff format`
+ `mypy --strict` (73 files) clean, `metrics.py --check` in sync across all five claims.

**Do not start the next thing from this file.** Everything remaining in the plan was deliberately
**cut or deferred by D-24 with a named trigger** — OpenTelemetry, streaming, the tenant axis, fleet
trace query + retention, egress lockdown, the build-agent profile. A trigger firing is a fact about
the world (a second operator, a disk that fills, a cross-pod question asked twice), not a queue to
work down. The right next move is to reassess against a real product, not to re-claim cut scope.

## ☑ WAVE 14 — the cleanup wave (2026-08-04). Docs re-trued, dead code gone, archaeology stripped

Six cards, two rounds. **Round 1:** CL-A (`docs/**`), CL-B (root `*.md`), CL-C (dead code in
`src/`+`tests/`), CL-D (repo hygiene: `examples/`, `Formula/`, `install.sh`, `.github/`, `scripts/`).
**Round 2:** CL-E (`src/` comments), CL-F (`tests/` ceremony + comments).

**What it removed:** `restart_gateway()` and its ~15 ceremonial call sites (a documented no-op each
one rendered a result for); `ToolResult.needs_approval`; `save_mcp_servers`; the golden suite's fake
`openclaw` binary; two `.lobster.yml` examples for a removed command; `scripts/wire-local-provider.sh`
(shelled out to `openclaw config set`); `DOCKET_NO_RESTART` in 37 test files; `OPENCLAW_DIR`/
`openclaw.json` fixture setup in 11; two genuinely dead tests. ~2,900 lines net.

**Comment archaeology, `src/`:** `Phase 1X` 204→3 · `P19-` 163→1 · `ROADMAP` 142→5 · `W-N` 147→2 ·
`D-1X` 57→0. `tests/`: `P19-` 109→1 · `Phase NN` 86→0. Survivors are golden-pinned strings or live
pointers to standing rules (§4.5), not shipped-card records.

**The policy applied, worth keeping for the next sweep:** delete card ids, phase numbers, dates,
provenance, and narration of deleted things — git history and ROADMAP hold all of it. **Keep** any
sentence whose loss would let someone introduce a bug: why a constant has its value, why something
fails closed, why two similar things differ deliberately, and (in tests) which regression a guard
exists to prevent plus any note that a guard was proven RED before being trusted. When in doubt, keep.

**Three findings that were defects, not staleness:**
1. **MCP tools are not reachable in a live turn.** `load_mcp_tools` is never called; `DocketDriver`'s
   `registry_factory` defaults to `builtin_registry` and nothing overrides it. Configuring a server
   registers and gates it; the last wire is missing. README and `commands.md` both overclaimed this
   (text written the same session) and were corrected. **The spec had it right all along.**
   *"Browser support is just an MCP config" is only true once that wire exists — do not reuse that
   argument to decline work until then.*
2. **`NOTICE` declared the project MIT-licensed** while `LICENSE`, the CHANGELOG relicense entry and
   the README badge all say Apache 2.0.
3. **All four `examples/configs/*-agent-meta.json` failed `AgentMeta` validation**, and
   `agents.yaml` silently dropped 2 of its 3 entries through `docket add --from`.

**Carried forward, NOT carded — the eval harness is dead code.** `tests/evals/` is entirely coupled
to the deleted daemon: workspaces at `$HOME/.openclaw/workspaces/<role>`, and `eval_run_task` shells
out to `openclaw agent --local --json`. It survived because `eval_skip_unless_command openclaw`
makes it **skip silently** rather than fail. Re-pointing it at docket's own driver is a redesign, not
a cleanup — decide whether the harness is worth keeping before rebuilding it.

---

## Historical — Phase 19 waves 8-9 shipped; the daemon is unused

**Platformization (Phases 14-18) is COMPLETE** — 38 cards, 7 waves; durable per-card records are the
`☑ Waves 3-4 / 5 / 6 / 7 shipped` blocks in ROADMAP.md's Phase 16 section.

**Phase 19 is ACTIVE.** Waves 8-9 shipped six cards: P19-1 (chat port) · P19-2 (gated tool registry)
· **P19-3 (`pre_tool_call` is live — the milestone)** · P19-4 (session history) · **P19-5 (the turn
loop + `DocketDriver`)** · P19-9 (sandboxed exec) · P19-10 (MCP client).

**Where that leaves the daemon: unused, not yet uninstalled.** docket can now run a fully gated agent
turn end to end — and does not yet, because `core/dispatch.py` still resolves `OpenClawDriver`. The
cutover is wave 11 (P19-6 -> P19-7), which is also where the ACL and `openclaw.json` are deleted.

`platform` green at wave 9 close: **2,026 tests** (`pytest` exit 0), 18/18 goldens byte-identical,
**24 specs** valid / 0 warnings, 37 commands, ~27,100 lines, `ruff` + `ruff format` + `mypy --strict`
(71 files) clean, `metrics.py --check` in sync across all five claims.

**The goal is now stated, and it resolved the open decision.** The user's objective is **a factory for
agentic products**. That answers **D-20: both, in an order** — factory first (it exists; Phase 19
finishes it), embeddable substrate second (Phase 21). The reasoning is one sentence and worth keeping
in front of you while working: *if every product is agentic, the runtime is the common part of every
product*, so the factory's highest-value output is a **reusable substrate**, not agent-written code.

**What that answer does NOT buy — read this before scoping anything:** the *hosted-SaaS* half.
Multi-tenancy, authn for external callers, queues/workers, streaming and per-customer quota are
**out of scope**. The substrate is a **library a product embeds**; the product owns its own serving
layer. Conflating "embeddable library" with "hosted product runtime" is the failure mode D-20 exists
to prevent.

**Decision status (2026-07-31):** **D-20 ANSWERED** (both, factory first) · **D-21 YES** — the package
split is live, *packaging only*, after the removal wave · **D-22 CUT** — stay project-scoped, build
nothing, re-open only if docket itself serves multiple end customers · **D-23 re-scoped** — ship the
`fetch` tool, defer the egress lockdown · **D-24 NEW — the prioritization ruling.**

**D-24 cut roughly half of Phases 20/21, including the integrator's own recommendations from hours
earlier.** Full verdict table in ROADMAP §5 (*"Prioritization ruling"*). What it means for this board:
**CUT** — OpenTelemetry (P20-1), streaming (P21-2), tenant axis (P21-3), and any browser-automation
tooling (that is an MCP config, per P19-13). **DEFERRED** — egress lockdown, fleet trace query
(P20-3), build-agent profile (P21-4). **KEPT** — the removal wave, P19-11's `fetch` tool, P19-12,
P19-13, P21-1, one new XS card **P21-5** (`agentic-product` blueprint — a row in an existing
registry, not new machinery), P20-2 and P20-4. The test applied was §4.5's, not "is this best practice
for someone": **does a measured need in *this* system ask for it.** It binds the integrator too.

**Phase status:** Phase 14 **COMPLETE** (R-1…R-8) · Phase 15 **COMPLETE** (G-1…G-6, closed by G-3)
· Phase 16 **COMPLETE** (W-1…W-8) · Phase 17 **COMPLETE** (C-1…C-5, closed by C-3/C-5) ·
Phase 18 **COMPLETE** (L-1/L-2/L-3/L-6 shipped; L-4 and L-5 answered as evidenced spikes).

### Three standing integrator checks (all earned the hard way)

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
3. **Ask what set a guard actually checks, not just whether it is green.** Check 2 caught guards
   that verified *nothing*; wave 7 caught two that verified the *wrong set* while reporting
   success. `metrics.py` counted specs with an `*.spec.md` suffix filter while the blocking
   validator globs `specs/acceptance/*.md`, so README published 20 where CI counted 21. The
   dependency floors in `pyproject.toml` had never once been resolved-and-tested, and two of six
   were false. **The tell is the same every time: a number nobody has ever watched go red.** When
   two scripts both claim authority over one number, pin them to each other.

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

## Wave 7 — ☑ COMPLETE (2026-07-31) — and with it, the whole Platformization program

Merge order `c-3-c-5 → g-3 → cl-3`. Durable record: the `☑ Wave 7 shipped` block in ROADMAP.md's
Phase 16 section. **Phases 14–18 are all closed. 38 cards across 7 waves.**

**Tree at close:** 1,684 → **1,735 tests** (`pytest` exit 0, zero FAILED/ERROR), 18/18 goldens
byte-identical, **21 specs** / 0 warnings, 37 commands, ~22,880 lines, `ruff` + `ruff format` +
`mypy --strict` (62 files) clean, `metrics.py --check` in sync across all five claims.

☑ **C-3 + C-5** (`0381e22`) durable task ledger + self-maintaining conversation registry — one
branch, not two · ☑ **G-3** (`5e71330`) high-risk classification on two real docket-launched paths
· ☑ **CL-3** (`31dadbb`) post-program sweep, 4 symbols deleted from 97 examined.

**Integrator commits this wave:** `997e5c8` dependency floors corrected + `floors` CI job ·
`77c4367` spec-count guard aligned to the blocking validator · `bb0de2c` the three high-risk
helpers deleted · `9d02d4f` distillation failure kind reported.

### Four lessons, in the order they cost something

1. **"Wire the unused function" can be the wrong instruction.** G-3's card named
   `resolve_command_action`. Wiring it proved it was unwireable: it resolves `ask`/`allow` for a
   command string, and that decision belongs to the daemon's exec gate (D-15), which keys on
   binary path and has no hook to consult docket. `match_high_risk` was the function that *could*
   be called. **The card was right about the defect and wrong about the fix** — the agent caught
   this and said so, which is the only reason it was caught.
2. **A dead function next to the code that fixed dead code is worse than elsewhere.** Deleting
   `resolve_command_action`/`is_high_risk`/`high_risk_bins` was not tidiness: leaving a
   never-called ask/allow resolver one function away from Phase 15's whole point would have
   published the opposite lesson.
3. **Two guards were checking the wrong set while reporting success** — the same shape as Phase
   14's vacuous `metrics.py --check`, found again twice in one day. The dependency floors had
   never been resolved-and-tested (`typer>=0.12` fails 216 tests; `pydantic>=2` fails 56 modules
   at import). `metrics.py` and `validate-specs.sh` disagreed on how many specs exist because one
   used a suffix filter the other didn't. **Both are now pinned by a job or a test that fails on
   bad input.** The recurring tell in all three: a number nobody had ever seen go red.
4. **Carve-outs need disjoint regions, not merely different names.** C-3 and C-5 were queued as
   separate cards with a note offering "one owner or a carve-out". Neither was available — they
   write from the *same five* functions. Merging them into one branch was cheaper than any
   scheduling trick, and both siblings then auto-merged with zero conflicts.

### The scheduling decision, kept for the next program

The queued board offered two options — one dispatch owner, or a repeat of wave 6's function-level
carve-out. **Neither applies to a pair like C-3/C-5.** They do not merely share a *file*; they
write from the **same lifecycle points** — task claim, hop persist, task finalize. A carve-out
only works when the regions are disjoint, and these are the same five functions. Split, they would
have produced a guaranteed hand-resolved conflict in the one file that has cost the most to merge
all program. They shipped on one branch.

**The carve-out that did apply** — G-3 vs C-3/C-5 in `core/dispatch.py`, genuinely disjoint
regions, declared before dispatch so the merge was predictable. It held exactly: every hunk landed
where declared (verified by reading the diff's hunk headers, not by trusting the reports), and all
three branches merged with **no code conflict**.

| Branch | Owns in `core/dispatch.py` | Owns elsewhere |
| --- | --- | --- |
| `pc/g-3` | the `pre_output` guardrail block inside `_execute_unit` **only** | `core/security.py`, `edges/adapters/system.py`, `cli/_gates.py` |
| `pc/c-3-c-5` | `_claim_next_task`, `_persist_hop`, `_finalize_task`, `_touch_claim`, `_apply_result` **only** | `core/memory.py`, `core/conversations.py`, `serve.py`, `cli/_doctor.py` |
| `pc/cl-3` | **nothing — the file is off-limits**; findings inside it are *deferred to the register*, not edited | everything neither sibling owns |

CL-3 sweeps the whole tree but may only **delete** in unowned files; anything dead inside a
sibling's file is recorded in the register with file/symbol/evidence for the integrator to apply
after that sibling merges. This is the wave-6 lesson generalized: C-1 could not delete R-7's dead
helpers because they sat outside its carve-out, and the integrator removed 56 lines by hand on
merge. A precise deferred finding is worth as much as a deletion, and it is the only shape of this
card that does not conflict with both siblings.

### ☑ Dependency floors — CLOSED 2026-07-31 (integrator, off-card)

Deferred since Phase 14 because measuring it needed network access. Network came back; measured.
**Two of the six advertised floors were false**, and the guard note's "do not raise the floors
blind" turned out to be the right instinct for the opposite reason — they needed *raising*, and
only measurement could say by how much.

| Bound | Was | Now | Evidence |
| --- | --- | --- | --- |
| `typer` | `>=0.12` ✗ | `>=0.13` | typer 0.12.x + modern click (8.4.2) raises `TypeError: Secondary flag is not valid for non-boolean flag` on this CLI's `--flag/--no-flag` options. **216 tests failed.** Bisected: 0.12.0 → exit 2, 0.12.5 → exit 1, 0.13.0 → clean. |
| `pydantic` | `>=2` ✗ | `>=2.1` | pydantic 2.0 raises `NameError` on the `model_source` field (protected `model_` namespace) and rejects `Field(discriminator="type")` on the pipeline union. **56 test modules failed to import.** 2.1.0 collects and passes. |
| `rich` | `>=13` ✓ | unchanged | 13.0.0 verified green. |
| `pydantic-settings` | `>=2` ✓ | unchanged | 2.0.0 verified green. |
| `filelock` | `>=3.13` ✓ | unchanged | 3.13.0 verified green. |
| `pyyaml` | `>=6` ✓ | unchanged | 6.0 verified green. |

Verified set — `typer 0.13.0 · rich 13.0.0 · pydantic 2.1.0 · pydantic-settings 2.0.0 ·
filelock 3.13.0 · pyyaml 6.0 · click 8.4.2` — installed into a clean 3.11 venv from
`uv pip compile --resolution lowest-direct`, then run against the **full suite: exit 0, zero
FAILED, zero ERROR**. The corrected bounds re-resolve to exactly that set.

**The fix is the CI job, not the numbers.** `.github/workflows/ci.yml` gains a `floors` job that
repeats the resolve-and-test on every push. Without it these bounds rot again the moment a
dependency ships a breaking release — which is precisely how they got a year out of date. This is
the same lesson as the `metrics.py --check` guard: *a bound nothing tests is a wish, not a
constraint.*

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
| `with_lock()` has no production caller | `edges/store.py:49` | `read_modify_write` has its own independent `_acquire` body rather than calling it; only `test_data_layer.py` exercises it. **Re-check after W-2 lands** — W-2 is reworking the claim/locking path and may add a genuine call site. |
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

**Confirmed resolved (CL-3, 2026-07-31)** — see the wave 3-6 section below: every row in this
list, and every "medium confidence" row above, now has a real, verified production caller.

---

## Dead-code register — wave 3-6 sweep (CL-3, 2026-07-31)

Re-ran CL-1's full-tree method against everything waves 3-6 added on top of the CL-1 baseline
(`5f73e30`..`910a557`, ~4,100 inserted lines across 38 files) — the scope CL-2 explicitly left
open (it covered waves 3-5's non-dispatch half only). Method: every top-level function/class/
constant added since CL-1 (97 symbols) plus every method on a class among them, checked with
`command grep -rn "<symbol>" src/ tests/ specs/ docs/ scripts/` for non-definition, non-test
references. Per this wave's file-ownership split, deletions below are limited to files neither
G-3 nor C-3/C-5 own; `core/dispatch.py` was swept read-only (fully off-limits for edits this
wave — both siblings are in it) and its findings are recorded as deferred.

### Deleted (high confidence — zero callers anywhere, verified)

| Symbol | Location | Evidence |
| --- | --- | --- |
| `step_id_of()` | `core/orchestrator.py:81-83` (3 lines) | Zero references anywhere in `src/`/`tests/`/`specs/`/`docs/` — not even its own test file. `PlannedUnit`/`PlannedGroup` (the two members of the `PlannedNode` union it exists to abstract over) are accessed via plain `.step_id` attribute access everywhere it matters (`core/orchestrator.py`'s own `render_plan`, `core/dispatch.py`'s hop-loop, `tests/python/test_orchestrator.py`) — the helper was never wired to a caller that needed the abstraction. |
| `BlueprintRegistry.__contains__()` | `core/blueprints.py` (was lines 231-233, 3 lines) | Zero callers. Built symmetrically with `core/archetypes.py`'s `ArchetypeRegistry` (which has a real `"producer" in registry`-style caller in `tests/python/test_archetypes.py`), but no code ever does `name in blueprint_registry` — there is no `docket blueprints` listing surface to need it. |
| `BlueprintRegistry.items()` | `core/blueprints.py` (was lines 237-238, 2 lines) | Zero callers. Same shape as `ArchetypeRegistry.items()` (which IS called, by `cli/_roles.py:61,143` for `docket roles list/validate`) but `core/blueprints.py` has no CLI listing command to call it. |
| `BUILTIN_BLUEPRINT_ORDER` | `core/blueprints.py` (was line 216, 1 line) | Zero production callers — only referenced by its own test file (`tests/python/test_pod_blueprints.py`, which used it in two assertions). Mirrors `core/archetypes.py`'s `BUILTIN_ROLE_ORDER`/`STARTER_ROLE_ORDER`, which ARE wired into `docket roles list`'s display (`cli/_roles.py:68-69`) — blueprints has no equivalent `docket blueprints list` command, so the display-order constant was never consumed. Textbook "seam shipped for a producer that never arrived" (built by the same convention as the archetypes registry, one card over). |

Test fallout (expected, per the card): `test_pod_blueprints.py::TestRegistry::test_builtin_order`
deleted — it tested only `BUILTIN_BLUEPRINT_ORDER`'s own value, nothing else, so it dies with the
constant. `test_get_blueprint_known_roundtrips` (same class) is **not** deleted — its assertion
(every built-in blueprint's name round-trips through `get_blueprint`) is real coverage — it now
iterates `bp.load_registry().names()` instead of the deleted constant, matching the pattern the
test right above it already uses. Net: **1,684 → 1,683 tests.**

### Confirmed resolved since CL-1's register closed (no action — dated evidence for the record)

Every row CL-1 left open with "re-check later" or "ambiguous, may be forward-looking" now has a
real, verified production caller. This is the register earning its keep — recorded here so the
next sweep doesn't re-litigate them:

| Finding (as CL-1/CL-2 left it) | Now | Evidence |
| --- | --- | --- |
| `with_lock()` — "re-check after W-2 lands" | Resolved | `edges/store.py:83`'s `read_modify_write` now calls `with with_lock(path):` directly — exactly the call site CL-1 predicted W-2 would add. |
| `git_current_branch()` — "genuinely ambiguous... may be forward-looking" | Resolved | `core/dispatch.py:835`, inside W-5b's `_implementer_diff_probe`: `diff_ref = _sys.git_current_branch(cwd) or None`. One wave later than CL-2 kept it, exactly as this card's brief cited. |
| `validate_policy()` — "never called by the CLI" | Resolved | G-2 (wave 6) wired it into `docket policies validate` (`cli/_policies.py:178,197,213`). |
| `VerifyResult.total_lines` — "written, never read" | Resolved | G-4b (wave 5) wired it into `cli/_audit.py:73`'s tamper-check message (`"...FAILED at line {result.break_at.line} of {result.total_lines}"`). |
| `core/dispatch.py`'s `print()` layering violation | Resolved | W-5 (wave 5) replaced it with the typed `HopResult.verification_skipped` flag (`core/dispatch.py:177-183`); `cli/`'s renderer prints the notice now, not `core/`. |
| `dispatch_all_pods` | Resolved | W-5 deleted it outright — `core/dispatch.py:2286-2293` carries the dated removal comment, pinned by `test_dispatch_all_pods_no_longer_called_unguarded_in_serve`. |
| `AgentRunResult` alias | Resolved | Fully deleted (`edges/adapters/openclaw.py:906-912`'s comment documents the removal); only 3 historical/comment mentions remain tree-wide, zero live references. |
| Ad-hoc-double → `FakeDriver` sweep | Resolved | `FakeDriver` (`tests/python/fakes.py`) is now the shared fixture across 7 test modules. |
| Legacy `CostTotals`/`DayRecord` decision | Resolved (predates this card's scope — Phase 18 L-1) | Kept deliberately as the stable public shape `cli/_cost.py`/`cli/_doctor.py`/`core/dispatch.py` depend on, now a pure translation of the RuntimeDriver port's `UsageTotals` (`core/utils.py:90-97`'s docstring records the decision). Not part of waves 3-6, included here only because the old "still owed" row pointed at it. |

### Checked specifically per this card's brief — kept, not dead

- **`core/handoff.py`'s `notes` field** — still written by no producer (confirmed:
  `core/dispatch.py` never sets it), but it is live schema: in `HandoffArtifact.DROP_ORDER`, in
  `render()`'s conditional, in `_EMPTY_VALUES`. A schema field with no producer yet is not a dead
  code path — its own docstring already says "reserved" and dated (W-5b). Do not delete; do not
  read it as populated data either (see the "known-open gaps" section below).
- **`core/handoff.py`'s `from_legacy_output()`** — has two real production callers:
  `core/dispatch.py:187` (`HopResult.__post_init__`'s backfill) and `core/dispatch.py:884`
  (`_hop_from_record`'s pre-W-5 record replay path). Not dead.
- **`cli/_pod.py`'s `build_pod()`** — looked at first glance like it might be superseded by the
  newer `build_pod_from_blueprint()` (W-7), since `docket add`'s interactive path now calls the
  latter. It is not superseded: `build_pod_from_blueprint` calls `build_pod` internally
  (`cli/_pod.py:601`) as its underlying primitive, and `build_pod` is still the direct, real
  entry point for `docket pod add full` and ~50 test call sites that exercise pod provisioning
  without a blueprint. Wrapped, not replaced.
- **`cli/__init__.py`'s `cmd_pipeline`** — flagged by the automated sweep as having zero non-test
  references (only its own test calls it directly); confirmed false positive — it is
  Typer-registered via `@app.command("pipeline", ...)` immediately above its definition
  (`cli/__init__.py:1337-1341`), the same pattern as the ~35 other `cmd_*` functions the register
  already documents as confirmed-not-dead.

### Medium confidence — flagged, not deleted (struct fields, not symbols)

Two typed-result fields are populated with real data but have no production reader today — the
same shape as CL-1's `VerifyResult.total_lines` finding, which sat unread for a full wave before
G-4b gave it one. Given that precedent, deleting these now risks the exact false negative CL-1
avoided by leaving `total_lines` for a later card to claim:

| Field | Location | Note |
| --- | --- | --- |
| `CancelOutcome.killed_pids` | `core/runs.py:76` | `cancel_run()` builds the full pid list and returns it (`core/runs.py:324`), but `cli/_runs.py`'s `_cancel` only renders `.ok`/`.message` (a count), and the audit-log entry logs `len(killed)`, not the list. Only `tests/python/test_run_cancellation.py` reads the field itself. No HTTP `/runs/<id>/cancel` endpoint exists yet that might want the exact pids. |
| `DistillResult.failure_kind` | `core/memory.py` (in `core/memory.py` — **C-3/C-5-owned this wave, not edited**) | Populated from the driver's `TurnResult.failure_kind` at the one construction site, but `cli/_agents.py`'s `_run_distillation`/`_maintain_distill` only ever read `.error` (the string), never `.failure_kind`. Only `tests/python/test_memory_distillation.py` reads it directly. Recorded here rather than acted on because the file is owned this wave. |

### Deferred findings inside sibling-owned files (for the integrator, after G-3 / C-3-C-5 merge)

Swept read-only per this wave's file-ownership split — nothing below was edited. Both are minor
(struct-field level, not whole symbols) and low-risk to leave for the next sweep if the owning
card doesn't touch the exact lines:

1. **`core/runs.py:76` `CancelOutcome.killed_pids`** — see the table above. `core/runs.py` itself
   is not owned by either sibling, but the *decision* of whether this is worth trimming belongs
   with whoever next touches `docket runs cancel`'s rendering — flagging here rather than
   deleting per this card's "judgment required" rule, since the precedent (`total_lines`) argues
   for patience over deletion.
2. **`core/memory.py` `DistillResult.failure_kind`** — see the table above. `core/memory.py` is
   C-3/C-5-owned this wave; if their conversation-registry/task-durability work ends up touching
   `_run_distillation`'s error rendering anyway, this is the moment to either wire `failure_kind`
   into the CLI message (e.g. distinguishing a timeout from a malformed reply) or drop the field
   — not before, since `core/dispatch.py`'s off-limits status this wave meant it could not be
   cross-checked against how `TurnResult.failure_kind` is rendered elsewhere for consistency.

No findings to defer in `core/security.py`, `edges/adapters/system.py`, or `cli/_gates.py`
(G-3's files) — `high_risk_bins`/`resolve_command_action`/`match_high_risk`/`is_high_risk` are
already correctly tracked as "deliberately not dead, awaiting G-3's wiring" in the section above
and in ROADMAP's wave 7 table; re-flagging them here would just be re-litigating G-3's own card.
Likewise `core/conversations.py`, `serve.py`, and `cli/_doctor.py` (C-3/C-5's other files) were
read in full for this sweep and showed no new orphans introduced by waves 3-6 — `cli/_doctor.py`'s
`_check_drift` now correctly delegates to `core/sync.py`'s `check_agent` (CL-2's fix, still
holding), and `core/dispatch.py`'s off-limits `_UnitOutcome`/pre_output block were checked and
have real, heavily-used call sites — nothing to hand off there either.

---

## Phase 19 — docket owns the runtime (opened 2026-07-31)

**Goal, in the user's terms:** stop depending on OpenClaw so docket has control of every layer —
reusing robust libraries where they help, but **keeping control of guardrails and tool handling**.
Decision **D-19** in ROADMAP §6.

**Scope ruling (2026-07-31, from the user): clean break, no compatibility layer.** docket is
pre-1.0 with no external installs to protect, so this phase does **not** stand a second runtime up
beside the daemon and ships **no** migration path. The OpenClaw driver, the ACL, the daemon's
config file and every shell-out to the `openclaw` binary are **deleted**; `docket install` is
reimplemented to provision a docket-native home from scratch. Local installs are **re-created, not
upgraded**. This supersedes this phase's first draft, which sequenced a per-agent migration and
kept the daemon installed throughout — legacy carried for nobody.

### The finding that decides the architecture

docket ships **four** guardrail policy templates hooked on `pre_tool_call` — `block-destructive`,
`high-risk-credentials`, `high-risk-deploy`, `high-risk-payment` — and **not one has ever been
evaluated.** `core/policy.py` defines the hook, `validate_policy` accepts it, the templates ship in
the wheel, and `core/dispatch.py` says in three places that it stays "daemon-gated, never evaluated
here."

That is the whole argument. docket already owns the governance stack — policy engine (3 hooks, 2
live), approval store with three channels and fail-closed timeout, high-risk classifier, hash-chained
audit, per-hop traces, worktree/port/scratch isolation. All of it can only act *between* turns,
because the daemon owns what happens *inside* one. **Owning the loop is not new scope; it is the
missing half of work already shipped.** The single most valuable guardrail docket has is currently
dead code.

### Verified preconditions (measured 2026-07-31, not assumed)

| Check | Result |
| --- | --- |
| Local llama-server does native tool calling | **Yes** — returned a well-formed `tool_calls` for a `calc` tool |
| `pre_tool_call` exists as a first-class hook | **Yes**, with 4 shipped templates and zero evaluations |
| `RuntimeDriver` port ready for a 2nd driver | **Yes** — 7 methods, built by L-1 for exactly this |
| MCP client present? | **No** — docket ships an MCP *server* (10 tools); the client side is new |
| New deps needed for inference | **None** — OpenAI-compatible chat completions is plain HTTP/JSON |

### Measured blast radius of the break (do not re-estimate from memory)

| Surface | Size |
| --- | --- |
| ACL functions/classes to delete or re-home | **82** in `edges/adapters/openclaw.py` (1,600 lines) |
| `src/` modules importing the ACL | **22** |
| test modules mentioning openclaw | **62 of 91** |

### What actually replaces each daemon capability

Nothing may be quietly dropped in the name of "no legacy" — this table is the completeness check.

| Daemon capability today | docket replacement | Card |
| --- | --- | --- |
| Inference call | OpenAI-compatible HTTP, stdlib | P19-1 |
| Tool execution | `core/tools.py` gated registry | P19-2 |
| In-turn exec approval gate | `pre_tool_call` + existing approval store | P19-3 |
| Session persistence / transcript | `core/session.py` (docket-owned, durable) | P19-4 |
| The turn loop itself | `core/agent_loop.py` + `DocketDriver` | P19-5 |
| Agent registry (`openclaw.json`) | docket-owned `fleet.json` via `edges/store.py` | P19-6 |
| Token/cost usage from session JSONL | real `usage` counts off the API response | P19-4 → P19-7 |
| Auth profiles / provider config | `docket keys` + docket-owned provider config | P19-7 |
| Gateway systemd unit | not needed — `docket serve` already exists | P19-7 |
| Telegram channel | docket-owned bot | P19-8 |

### The architecture

```text
docket OWNS (control plane -- never delegated to a library)
  core/agent_loop.py     the turn loop: call model -> receive tool_calls -> gate -> execute -> feed back
  core/tools.py          tool registry + dispatch; EVERY call passes the gates below
  core/policy.py         pre_input (live) | pre_tool_call (finally live) | pre_output (live)
  core/approval.py       human-in-the-loop, 3 channels, fail-closed on timeout
  core/security.py       high-risk action classes, allowlist, argument-aware at last
  core/audit.py+trace.py hash-chained audit, per-tool-call traces
  core/session.py        turn history + compaction (NEW; docket already owns memory/ledger/registry)

docket RENTS (protocol only -- no library sees a control decision)
  inference   OpenAI-compatible /v1/chat/completions  -> stdlib urllib, zero new deps
  tools       MCP client (official SDK, already an optional extra) -> pluggable tool servers
  isolation   containers / git worktrees              -> already wrapped in edges/adapters
```

**Why no agent framework.** LangGraph/CrewAI/AutoGen own the loop, so they own the interception
points. Adopting one moves docket's guardrails into a third party's callback API — the same
dependency being escaped, with a new vendor and a worse audit story. It also contradicts the
product's own positioning ("an ops/control plane, not an agent framework").

**Why MCP for tools.** It makes the tool set pluggable without docket implementing every tool, it
reuses an SDK already declared as an optional extra, and docket stays the dispatcher — so
`pre_tool_call` fires on every call regardless of which server provides the tool. Built-in tools
(read/write/edit/bash) still land in `core/tools.py` behind the same gate.

### Wave A — the runtime (additive; the tree stays green throughout)

**P19-1 · `core/llm.py` port + `edges/adapters/llm.py` client** — *DONE (`5ec051c`) · M*
Typed chat port in `core/` (`ChatMessage`, `ToolCall`, `ChatResponse`, `ChatBackend` Protocol),
OpenAI-compatible implementation in `edges/` over stdlib `urllib` — **zero new dependencies**, and
the same core-is-pure-typing / edges-does-I/O split `runtime_driver.py` already uses. Reports the
response's real `usage` token counts: docket's first non-estimated token numbers. Failure modes map
onto the existing `FailureKind` vocabulary so `core/dispatch.py`'s retry policy needs no changes.

**P19-2 · `core/tools.py`: the gated tool registry** — *DONE (`75c2b04`) · M*
Tool schema (JSON-Schema, as the model expects it), registry, and **one** dispatch chokepoint every
call goes through — there must be no second path. Ships the built-in set
(`read`/`write`/`edit`/`glob`/`grep`/`bash`). Bash **parses its arguments**, not just the binary
path — the gap the daemon's allowlist structurally could not close.

**P19-3 · Turn on `pre_tool_call`** — *DONE (`9814da4`) · S, and the point of the phase*
Wire the hook into P19-2's chokepoint so the four shipped templates finally evaluate. `deny` blocks
and writes an audit entry; `require_approval` routes to the existing store and fails closed on
timeout. Acceptance, test-pinned: a `block-destructive` policy actually blocks an `rm -rf` tool
call, and `high-risk-deploy` catches `git push` **by argument** — the deferred backlog item since
Phase 13.

**P19-4 · `core/session.py`: turn history + compaction** — *DONE (`08c5c11`) · M*
docket already owns HEARTBEAT, the conversation registry and memory logs; this adds the in-turn
message history the loop needs. Durable per `agent:<id>:<project>` session key, written through
`edges/store.py`. Compaction reuses C-1's budget compiler and C-2's distillation. Retires the
daemon's session JSONL as the source of usage data.

**P19-5 · `core/agent_loop.py` + `DocketDriver`** — *DONE (`71b792f`) · L*
The loop: compose context -> call model -> receive `tool_calls` -> **gate** -> execute -> feed
results back -> repeat until a stop condition (final message, tool-call cap, token budget, timeout).
`edges/adapters/docket_runtime.py::DocketDriver` implements `RuntimeDriver` on top of it, so
`core/dispatch.py`, the pipeline executor and every existing caller are unchanged.
**After this card the daemon is unused — not yet uninstalled.**

### Wave B — the removal (this is what "no legacy" means)

> **Re-sequenced 2026-07-31:** P19-6 was pulled forward into **wave 10** (it is disjoint from the
> runtime-capability cards and the spine should start immediately); P19-7 and P19-8 are **wave 11**.
> The card text below is the durable definition — the live schedule is the wave-10 block and the
> sequencing table further down.

**P19-6 · docket-native home + fleet registry** — *moved to wave 10 · M*
`~/.openclaw/` -> `~/.docket/`; agent registration, channel bindings, gates/isolation flags and
model defaults move out of `openclaw.json` into a docket-owned `fleet.json` through
`edges/store.py`. **The dual-source problem disappears with it:** `core/sync.py`,
`core/oc_models.py` and `doctor`'s config-drift check are **deleted rather than ported** — with one
source of truth there is nothing left to drift.

> **Split into P19-7a + P19-7b (integrator, 2026-08-03).** Measured before dispatching rather than
> estimated from the card text: **44 files** under `src/` mention `openclaw`, **23** import the ACL,
> and the ACL itself is **1,549 lines / 72 functions**. That is too large for one agent to keep
> coherent, and it bundles two different risks — *flipping the runtime* and *deleting the old one*.
> The seam is exact: `_oc.default_driver()` is the **single** point that decides which runtime
> executes a hop (`core/dispatch.py` ~1207 and ~1399), so the flip can be verified on its own before
> anything is deleted. Splitting there buys an integration checkpoint at the most consequential
> moment in the phase.
>
> **P19-7a · The runtime cutover** — *IN-PROGRESS · M · wave 11*
> `default_driver()` returns `DocketDriver`, so production pod-dispatch hops execute on docket's own
> gated loop. Moves the four remaining docket-owned constants (`MODEL_REGISTRY_FILE`,
> `ARCHETYPE_REGISTRY_FILE`, `PROJECTS_DIR`, `AUDIT_LOG`) under `DOCKET_HOME`. Deletes nothing.
> **Walks straight into wave 10's trap** — it moves four more constants across the
> `OPENCLAW_DIR`/`DOCKET_HOME` boundary that silently de-isolated the suite last time, so rule 10's
> snapshot proof is mandatory and `test_docket_home_isolation.py`'s third test is *expected*
> to fire until `_DOCKET_HOME_PATHS` is extended. Extend the list; never weaken the guard.
>
> **P19-7b · Delete the ACL; reimplement install/doctor/cost** — *TODO · L · wave 11, after P19-7a*
Delete `edges/adapters/openclaw.py` and every `openclaw` shell-out, auth-profile read, gateway
restart and version probe. Reimplement `docket install` to provision a docket-native home with no
external daemon; re-point `doctor`, `gates`, `keys`, `auth`, `cost` and `context` at docket-owned
state. `openclaw` leaves the dependency list, CLAUDE.md and the README.
**Acceptance: `command grep -ril openclaw src/` returns nothing but a historical note.**

**P19-8 · Channels: docket-owned Telegram** — *TODO · M · wave 11 (was BLOCKED; the clean break decides it)*
With no daemon there is no daemon channel to fall back on, so docket owns the bot: long-poll over
stdlib HTTP, bound to the existing approval store and pod delegation. This is what finally makes
Telegram a **real** docket approval channel — the claim CLAUDE.md has had to explicitly deny since
Phase 15, and G-5's unbridgeable gap closed by removing the other side of it.

### Wave C — hardening

**P19-9 · Sandboxed exec** — *DONE (`fe0d7b0`) · M*
Container/bwrap jail for bash-class tools, reusing `edges/adapters/system.py`'s docker wrappers and
the existing worktree/port/scratch isolation.

**P19-10 · MCP client: pluggable tool servers** — *DONE (`3d3e3ed`) · M*
Consume external MCP tool servers through P19-2's dispatcher. Never a second, ungated path. docket
already ships an MCP *server*; this is the client half.

### Wave 8 record (in flight)

**Shipped: P19-1 (`5ec051c`) + P19-2 (`75c2b04`).** Facts later cards depend on, so they are not
re-derived from memory:

- **Inference needs no new dependency and the local endpoint really does tool-call.** Verified live,
  not stubbed: a tool-calling exchange returned a well-formed call with real `usage` counts, and the
  tool-result round-trip came back `finish_reason=stop`. Two real-server quirks are handled and
  test-pinned — an assistant tool-call turn must be replayed with `content: null` (not `""`), and
  llama.cpp can emit already-decoded dict arguments where the spec says JSON *string*.
- **`TokenUsage` carries counts reported by the endpoint.** These are docket's first non-estimated
  token numbers. Everything prior — `core/context.py` budgets, `maintain check` guards — is a
  bytes/divisor approximation. Do not let the two get conflated in code or in prose.
- **The Phase 13 per-argument gap is closed on the paths docket controls.** `classify_command` reads
  the whole command line and every segment behind `;`/`&&`/`||`/pipe, so `git status` is allowed and
  `git push origin production` asks. The daemon-side half remains impossible, and is moot once P19-7
  lands.
- **`resolve_command_action`'s deletion in G-3 was still correct.** It classified a bare binary name,
  the exact granularity that made this distinction impossible, and it had no possible caller while
  the daemon owned the turn. The new classifier is a different shape with a real enforcement point.
- **Three architectural guards now hold the chokepoint invariant**: no module outside `core/tools.py`
  imports the handlers, `dispatch_tool` itself calls the gate, and `edges/adapters/toolbox.py` holds
  no policy vocabulary. All three were verified red against planted drift.

- **`pre_tool_call` fires.** The four shipped templates evaluate for the first time since Phase 11,
  against a **pinned canonical render** (`render_tool_call`: `"<name> <key>=<json-value> ..."`) — that
  render is a contract every policy pattern depends on, not an implementation detail, so it is
  test-pinned. Policy and command classifier are combined most-restrictive-wins, mirroring
  `core/policy.py`'s own `_RANK`.
- **Two shipped policy patterns could never have matched anything, and now do.** P19-3 verified rather
  than assumed it: `block-destructive`'s `\.env\b.*write` and `\.ssh\/\s*write` require the path to
  appear *before* the verb, which no natural render produces. Both were fixed to match either order.
  **This is what "shipped but never evaluated" costs** — nobody had ever run these against real input.
- **The policy engine gates tools the command classifier cannot see.** A `write` call to `.env` is not
  a shell command, so `classify_command` never inspects it; the hook does. That is the argument for
  having both, and it is test-pinned.
- **In-turn approval blocks and fails closed.** `wait_for_approval` (new, in `core/approval.py`) is the
  in-turn counterpart to dispatch's async `waiting_approval`: the model is blocked on this exact
  answer, so there is nowhere to return to. Timeout resolves the record to **denied** through the same
  helper the expiry sweep uses — never left dangling. `TOOL_APPROVAL_TIMEOUT` is 120s, deliberately
  short against dispatch's 300s hop budget so a grant still leaves time for the tool to run; the async
  `APPROVAL_TIMEOUT` stays 900s because nothing is blocked on it.
- **Compaction's real trap is tool-call atomicity.** An assistant message carrying `tool_calls` and the
  `tool` messages answering it are one unit; split them and every endpoint rejects the next request.
  `plan_compaction` only ever moves whole units, and `compact_session` re-validates its own output
  before persisting. Failure to summarise leaves the stored history untouched (fail closed, per C-2).

**Scheduling, and how it went.** P19-3 and P19-4 ran in parallel — disjoint footprints
(`core/tools.py` + `core/approval.py` + policy templates vs. a new `core/session.py`), each in its
own worktree, per the Phase 14 contention rule. Both auto-merged with **zero conflicts**; the one
shared file (`config.py`, both adding constants) was verified after the merge to still carry both
cards' additions rather than trusted to have merged cleanly. Every load-bearing claim in both
cards' reports was re-verified by the integrator planting the drift independently: the policy hook
being consulted, the approval timeout failing closed, the `.env` pattern fix, and compaction's
unit atomicity all went red on demand. P19-5 depends on both and follows.

### Wave 9 ownership map (in flight)

Three cards in parallel. `core/tools.py` is now the contention hotspot the way `core/dispatch.py` was
in Phase 14, so ownership is **function-level**, not file-level, and is stated here rather than left
to goodwill:

| Card | Owns | Explicitly may not touch |
| --- | --- | --- |
| **P19-5** loop + driver | `core/agent_loop.py`, `edges/adapters/docket_runtime.py` (both new) | all of `core/tools.py`, `toolbox.py`, `system.py`, `llm.py`, `session.py` — import only |
| **P19-9** sandboxed exec | `toolbox.py`, `system.py`, **and only** `ToolContext` + the `bash` registration in `core/tools.py` | `dispatch_tool` / `evaluate_tool_call` / `render_tool_call` — P19-3's gate logic stays byte-stable |
| **P19-10** MCP client | new client modules under `edges/adapters/` + `core/` | **all** of `core/tools.py` — works through the public `Tool`/`ToolRegistry.register` API |

Each appends to `config.py` in one contiguous commented block; that file auto-merged cleanly in wave
8 and is checked after merge rather than trusted.

**The P19-10 constraint worth remembering:** an MCP tool registers with `kind="write"`, never
`"exec"` — `"exec"` routes into the shell-command classifier, which expects an `args["command"]` an
MCP tool does not have, and would classify every such call as an empty command. `"write"` is not
"ungated": the `pre_tool_call` hook fires for every tool kind, which is exactly why renting MCP as a
transport does not cost docket its guardrails.


**Wave 9 outcome.** All three merged. **The daemon is now unused, not yet uninstalled** — that was
P19-5's job and it is done. Findings worth keeping:

- **Truncation and compaction interact.** P19-5 found that persisting a length-truncated assistant
  message which requested tool calls would create exactly the orphaned-tool-call state P19-4's
  compaction post-conditions exist to forbid. A truncated response is therefore neither dispatched
  **nor persisted**. Neither card could have found this alone.
- **`cost_usd` stays 0.0 in `DocketDriver`, deliberately.** Real token counts are recorded; turning
  them into dollars where `docket cost` reports *recorded spend* would convert an estimate into a
  billing claim. Pinned by a test that goes red if a future card fabricates one.
- **`provision`/`teardown` are honest no-ops** with `supports_provisioning=False`, rather than
  returning `ok=True` for work that does not exist. `teardown` deliberately does not guess at deleting
  sessions from a bare `agent_id` — a session is keyed by the full `agent:<id>:<project>`.
- **Docker needs an explicit container kill on timeout.** P19-9 verified empirically that killing
  `docker run`'s process group leaves the container alive under `dockerd` — it is a thin client. bwrap
  needs nothing extra (its pid namespace tears down with its first process).
- **A sandbox that silently degrades is worse than none.** `run_bash` reports the backend that actually
  ran (`[sandbox: none (docker unavailable, bwrap unavailable)]`), kept distinct from "a jail is
  possible on this host". Opt-in, default off — a filesystem jail can break a call the gate would allow.
- **MCP tools are namespaced `mcp__<server>__<tool>`,** so a remote server naming its tool `bash` lands
  at `mcp__evil__bash` and cannot shadow the gated built-in. Proven with a hostile fake server.
- **Server-supplied tool descriptions are screened** through the existing `prompt-injection` policy on
  `pre_input` before registration — that text is attacker-controlled and ends up in a model's prompt.
  `block`/`require_approval` both refuse registration, since there is no human-approval channel for
  static catalog text.

**Integration findings (the merge itself).** `config.py` conflicted — both P19-5 and P19-10 appended a
constants block — and was resolved by keeping **both**, then verified by importing the module and
asserting all eleven constants from waves 8-9 exist. **`specs/README.md`'s status table had six stale
version cells**, some drifting since wave 7, plus a missing row; it was regenerated from the spec
headers rather than hand-patched. That is integrator check #1 paying for itself again: a roll-up table
edited by several branches at once holds no single correct side.

**P19-10 widened one of P19-2's guards** (the toolbox-import allowlist) to admit two files that
reference only the inert `ToolOutcome` type, and added a narrower guard in its place. The integrator
re-verified that replacement by planting a real handler-function import — it fired.

### ☑ Wave 10 — COMPLETE (2026-08-02, all four merged)

Merge order `p19-11 -> p19-12 -> p19-13 -> p19-6`. **Tree: 2,026 -> 2,096 tests**, 18/18 goldens,
24 specs / 0 warnings, `mypy --strict` clean (71 files — `sync.py` + `oc_models.py` deleted,
`fleet.py` added). Four cards ran in parallel with **zero code conflicts** outside the one
`config.py` collision the ownership map predicted; it was resolved by keeping both blocks and then
*importing the module* to assert all 16 constants survived.

**The finding no card could have made alone.** P19-6 decoupled `DOCKET_HOME` from `OPENCLAW_DIR`.
Before it, the two were the same physical directory, so **every test that repointed `OPENCLAW_DIR`
for hermeticity isolated docket's own state for free**. Afterwards it did not — and the card
isolated exactly *one* of the ten constants that changed meaning (its own `FLEET_FILE`), while
writing a docstring that correctly described the danger for that one. A full `pytest` was writing
real approval records, trace JSONL, `docket-conversations.json` and `port-allocations.json` into
the developer's actual `~/.docket`. Found by **snapshotting the directory either side of a run**,
not by reading code. Two of the leaking constants (`PORT_ALLOC_FILE`, `CONVERSATIONS_FILE`) have no
env override at all, so no test could have opted out even deliberately.
Fixed in `conftest.py` (`_isolate_docket_home`) + guarded by
`tests/python/test_docket_home_isolation.py`, whose third test reads `config.py`'s source and
fails if a *future* `DOCKET_HOME`-derived constant is added unisolated — because a guard is only as
good as the set it checks (integrator check #3).

**A reporting failure worth institutionalising: three of four agents claimed a gate failure was
somebody else's.** P19-6, P19-11 and P19-12 each reported "3 pre-existing `mypy` errors in
`mcp_client.py`, confirmed against the `platform` baseline"; two said they verified it with `git
stash`. The baseline is clean (`Success: no issues found in 71 source files`) and so is every merge.
It was an artifact of their worktree environments. No code impact — but **"seen it fail" was applied
to their own new guards and not to a red they inherited.** Wave 11 briefs must require: *if a gate
is red, prove the attribution on a clean checkout of the base commit before calling it pre-existing.*

**Carried open (integrator, decide before wave 12):** `fetch` refuses every domain by default
(`FETCH_ALLOWED_DOMAINS=()`) while `python3`/`node`/`git clone` reach the network unattended, so the
**inspectable path is the closed one and the escape hatch is the open one**. Verified at the gate:
both `fetch` and the `python3` one-liner return `decision='allow'`; `fetch` is then refused *inside
the handler*, which also means the domain decision never reaches the policy engine and **no approver
can ever be asked** "may this agent fetch example.com?". P19-12 sharpened it — `reviewer`/`lead` now
have `fetch` but no `bash`, so their only egress tool is one that refuses everything.
**Proposed fix:** a non-allowlisted domain should resolve to `ask` at the gate, not a handler
refusal. Fail-closed on the safe path while the unsafe path stays open is the wrong shape.

### Wave 10 dispatch record (kept — the ownership map that produced zero conflicts)

**Change from the earlier plan:** wave 10 was three runtime-capability cards with the removal
deferred to wave 11. It now **pulls P19-6 forward** so the removal spine starts immediately — the
daemon still resolves `OpenClawDriver`, and every runtime claim on this board is theoretical until
that flips. P19-6 (state-side) and P19-11/12/13 (runtime-side) touch disjoint trees, so they run
together. P19-7 stays in wave 11 because it cannot start until P19-6's registry exists.

#### Ownership map — function-level where a file is hot (state it, do not leave it to goodwill)

| Card | Owns | Explicitly may not touch |
| --- | --- | --- |
| **P19-6** fleet registry | `edges/adapters/openclaw.py` (writes redirected), new `fleet.json` handling, `config.py` **path constants only**, deletion of `core/sync.py` + `core/oc_models.py` | `core/tools.py`, `core/agent_loop.py`, `core/archetypes.py`, `cli/_mcp.py`, `edges/adapters/toolbox.py` |
| **P19-11** `fetch` tool | new `edges/adapters/fetch.py`, **and only** the registration entry for `fetch` in `core/tools.py` | `dispatch_tool` / `evaluate_tool_call` / `render_tool_call` — P19-3's gate logic stays byte-stable. Also all of `toolbox.py` |
| **P19-12** role tool sets + identity | `core/archetypes.py`, `core/identity.py`, `core/agent_loop.py` (prompt composition) | **all** of `core/tools.py` — compose through the public `ToolRegistry.without()` API only |
| **P19-13** MCP servers CLI | `cli/_mcp.py`, `core/mcp_tools.py`, `edges/adapters/mcp_client.py`, docs | **all** of `core/tools.py`; any built-in tool registration |

**`config.py` will conflict again** — P19-6 adds path constants while others may add tool constants.
That is expected and the resolution is settled: **keep both blocks, then import the module and assert
every constant exists**. Do not resolve it by reading the diff and assuming (wave 9's lesson).

#### Dispatch protocol (identical for every card in the wave — no per-card negotiation)

1. **One agent per card, one worktree per card, branch `pc/<card-id>`** (e.g. `pc/p19-12`). Merge
   into `platform`, never into `main`.
2. **Read before writing:** ROADMAP.md's Phase 19 section, §2 (Python ground truth), §4.5
   (architectural principles + the anti-overengineering "we will NOT" list), §6 decisions
   **D-19/D-20/D-21/D-24**, `CLAUDE.md`, and this card's own ownership row above.
3. **Stay inside your ownership row.** If a card genuinely needs a file another card owns, **stop and
   report it** rather than editing it — the integrator re-slices the wave. Three waves have now run
   clean on this rule; every conflict we did hit came from a file nobody had assigned.
4. **Do not edit `ROADMAP.md`, `TODO.md`, `README.md` or `CLAUDE.md`.** They are integrator-owned.
   **Report what you shipped; do not update the board.** Phase 14 lost real time to roll-up tables
   conflicting on nearly every merge.
5. **A guard is not evidence until you have seen it fail.** Any test a card adds to protect an
   invariant must be run against **planted drift** — break the thing on purpose, watch it go red,
   restore, watch it go green — and the report must say which drift was planted. Three separate
   guards in this repo were green while verifying nothing; this is the only rule that catches that.
6. **Never regenerate a golden to make a diff go away.** Only P19-13 adds CLI surface, so only P19-13
   regenerates goldens, and it must explain the diff line by line. For every other card the 18 goldens
   stay byte-identical.
7. **Definition of done** is the list in *"How to use this board"* above — full gate suite green
   (`ruff check` · `ruff format --check` · `mypy src` · `pytest` · `golden verify-all` ·
   `validate-specs.sh`), the card's spec updated with a version bump + changelog entry and a Status
   line matching **what actually shipped**, commit as `Type: description` with **no** AI/Claude/
   Co-Authored-By trailer, and the diff grepped for real names and `/home/<user>` paths.
8. **Report back:** what shipped, what you deliberately did **not** ship and why, every load-bearing
   claim with the command that proves it, and anything you found in a sibling card's territory
   (do not fix it — report it).
9. **Never call a red gate "pre-existing" without proving it on the base commit.** Added after wave
   10, where **three of four agents** reported the same three `mypy` errors as pre-existing — two
   claiming they had confirmed it with `git stash` — against a baseline that was clean. It was
   their worktree environment. If a gate is red, check out the base commit **clean** (a fresh
   worktree, not a stash in a dirty tree) and re-run there before attributing it to anyone else. A
   stash does not restore deleted files, added files, or a changed environment, so it is not a
   baseline.
10. **Isolation is part of done.** If your card changes where docket stores state, snapshot the real
    directory (`find ~/.docket -printf '%p %s\n' | sort`) before and after a full `pytest`, and prove
    the suite created, modified and removed nothing there. Wave 10's worst defect was invisible to
    every gate: the suite was writing into the developer's home and every check stayed green.

#### The cards

**P19-6 · docket-native home + fleet registry** — *TODO · M · the removal spine starts here*
`~/.openclaw/` -> `~/.docket/`; agent registration, channel bindings, gates/isolation flags and model
defaults move out of `openclaw.json` into a docket-owned `fleet.json` through `edges/store.py`.
**The dual-source problem disappears with it:** `core/sync.py`, `core/oc_models.py` and `doctor`'s
config-drift check are **deleted rather than ported** — with one source of truth there is nothing left
to drift. Per the clean-break amendment to D-19, **write no migration code**; local installs are
re-created, not upgraded.

**P19-11 · `fetch` tool** — *TODO · S (was M) · decision D-23, re-scoped*
**Re-scoped by D-24: ship the tool, drop the lockdown.** The gap is measured, not assumed:
`curl`/`wget` correctly ask, but `python3 -c "import urllib..."`, `node` and `git clone <url>` are
**allowed unattended** — both interpreters are on the curated allowlist because agents need them
constantly, and both are universal escape hatches. Ship a first-class `fetch` tool (domain allowlist,
size cap, timeout, gated like every other tool) so there is an **inspectable** egress path.
**Do NOT ship** the opt-in `--network none` / `--unshare-net` lockdown: it is off by default, breaks
`npm install`/`pip`/`git clone` when on, and buys a config option rather than a guarantee.
**Instead, this card must make the docs say the true thing** — egress is open, `fetch` is the
inspectable path, and the escape hatches are named. An honestly-open gate beats one that reads as
closed.

**P19-12 · Per-role tool sets + identity composition** — *TODO · M*
Two omissions P19-5 recorded honestly rather than papering over. (1) `ToolRegistry.without()` exists
and is tested but **nothing composes it per role** — a Reviewer is *told* not to edit code instead of
being *unable* to, which is a strictly weaker guarantee and the exact distinction docket sells.
(2) The loop **composes no system prompt at all**: `SOUL.md`, the docket-owned persona
(`core/identity.py`) and `WORKFLOW_AUTO.md`'s resume contract never reach the model. Wire both;
role -> toolset belongs in `core/archetypes.py` as **data, not a branch**. Acceptance must include a
test that a Reviewer registry genuinely lacks `write`/`edit` — asserted by dispatching and getting a
tool-not-found denial, not by inspecting a dict.

**P19-13 · `docket mcp servers` CLI + browser recipe** — *TODO · S*
P19-10 shipped `add_mcp_server`/`load_mcp_tools` as tested, uncalled library functions. Give them a
CLI (`docket mcp servers add/list/remove`) and document the payoff: **browser support is
configuration, not code** — point it at the Playwright MCP server and P19-10's client gates those
tools exactly like a built-in (namespaced `mcp__<server>__<tool>`, so a remote server cannot shadow
`bash`). Same for web search. This is what "rent the protocol" buys, and it is why **browser
automation is on the never-build list** (D-24). Adds CLI surface, so this card **regenerates goldens**
and must explain the diff.

### Sequencing (updated 2026-07-31)

| Wave | Cards | Mode | Gate to the next wave |
| --- | --- | --- | --- |
| 8-9 | ☑ P19-1 -> P19-2 -> **P19-3** -> P19-4 -> P19-5 -> P19-9/P19-10 | done | — |
| 10 | ☑ P19-6 · P19-11 · P19-12 · P19-13 | done (2026-08-02) | — |
| 11 | ☑ P19-7a -> P19-7b -> P19-8 | done (2026-08-03) | **PHASE 19 CLOSED** — acceptance grep clean |
| 12 | ☑ P21-1 -> P21-5 | done (2026-08-03) | — |
| 13 | ☑ **P20-2** · ~~P20-4~~ | done (2026-08-04) | **BOARD CLEAR** — P20-2 shipped; P20-4 was a phantom card (W-4 had already closed it). Everything else was cut/deferred by D-24 |

**Wave 11 closes Phase 19. Wave 12 is Phase 21 (the substrate — the factory's actual product line).
Wave 13 is all that survives of Phase 20.** Anything not in this table was cut or deferred by D-24;
do not let it get quietly re-claimed.

**P19-3 was the milestone that mattered** — the moment docket's guardrails stopped being advisory.
**P19-7 is the moment the dependency is actually gone**; do not report Phase 19 complete before that
grep is clean.

Wave A is additive — every card lands on a green tree with the existing suite passing. The daemon
stops being *used* at P19-5 and stops being *present* at P19-7. Wave C is optional depth once the
loop is real.

**P19-3 is the milestone that matters** — the moment docket's guardrails stop being advisory.
**P19-7 is the moment the dependency is actually gone**; do not report the phase complete before
that grep is clean.

### Measured caveat, unchanged

The local Qwen answered a one-word prompt in **107 s**. Owning the loop does not make the model
fast; model choice per role stays a separate decision from runtime ownership. Nothing in this phase
may be sold as a performance improvement.

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
- ~~Per-argument daemon enforcement for allowlisted bins (`git`, `npm`) still does not exist~~ —
  **closed on docket's own paths by P19-2/P19-3 (wave 8)**: `classify_command` reads the whole command
  line and every segment behind `;`/`&&`/`||`/pipe, so `git status` is allowed and `git push origin
  production` asks. The daemon-side half remains impossible by construction (its allowlist gates by
  binary path) and becomes moot at P19-7, when the daemon goes.
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
  existing `cli/_metrics.py` reader needed no changes. ~~**Still daemon-gated:** `pre_tool_call`~~ —
  **closed by P19-3 (wave 8)** for the calls docket dispatches itself: `core/tools.py`'s chokepoint
  evaluates the hook, so all three hooks are now live. Precise scope, do not overstate it: nothing in
  the pod-dispatch hop path calls that dispatcher yet (P19-5 wires it), and the daemon's own
  tool-calling loop stays unbridged until P19-7 deletes it. `resolve_command_action` stayed deleted —
  P19-2's `classify_command` is a different, argument-aware shape with a real enforcement point.
- Hops still exchange **concatenated raw text**, not structured artifacts (W-5, in flight this wave).
- ~~The runtime dependency floors in `pyproject.toml` are unverified~~ — **closed 2026-07-31, and
  the suspicion was right: two of the six advertised floors were false.** `typer>=0.12` failed 216
  tests (click 8.4.2 incompatibility) and `pydantic>=2` failed 56 test modules at import; both were
  raised to what actually runs (`typer>=0.13`, `pydantic>=2.1`). The measured floor set —
  typer 0.13.0 / rich 13.0.0 / pydantic 2.1.0 / pydantic-settings 2.0.0 / filelock 3.13.0 /
  pyyaml 6.0 — now passes the full suite, and a `floors` CI job resolves `--resolution
  lowest-direct` and runs pytest against it so the claim stays real. **Do not raise or lower a
  floor without re-measuring** — an untested floor and a wrong floor look identical until someone
  installs.
- ~~`scripts/validate-specs.sh` reports two spec references on one line as a broken reference~~ —
  **fixed by the integrator in `771f622`**, along with a second defect found next to it: `check_todos`
  ran its loop in a pipe subshell, so every warning increment was discarded and a spec full of TODO
  markers still reported zero warnings. Both were reproduced before being fixed.
