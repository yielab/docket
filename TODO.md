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

**`platform` @ `7fc6233`** ("Merge W-2 + W-8"), working tree clean, everything green —
**1,512 tests** (1,509 passed / 3 skipped), 18/18 goldens, 20 specs valid, 37 commands,
`ruff` + `ruff format` + `mypy --strict` clean, `metrics.py --check` in sync (and the guard
itself is now repaired — see below).

**Waves 3 and 4 are fully merged (11 cards).** Their durable record — what shipped, what was
narrowed, and the two integration defects that the gates did *not* catch — is the
`☑ Waves 3–4 shipped` block in ROADMAP.md's Phase 16 section. Per the board convention their
per-card entries were cleared from here; ROADMAP holds the history.

**Phase status:** Phase 16 exit criteria **met** (W-4/W-5 open) · Phase 18 done but for two
daemon-gated spikes · Phase 15 at 4 of 6 (G-2/G-3 open) · Phase 17 opens once W-5 lands.

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

## Wave 5 — IN FLIGHT

Five cards, chosen for disjoint file footprints. **W-5 is the wave's single `core/dispatch.py`
owner** and therefore also absorbs the three dispatch-local dead-code items — the file's owner
cleans the file, rather than a second branch racing it.

| Card | Phase | Owns (do not edit outside your card's footprint) |
| --- | --- | --- |
| **W-5** | 16 | `core/dispatch.py`, `core/handoff.py` (new), dispatch-adjacent test families |
| **CL-2** | standing | `core/sync.py`, `cli/_doctor.py`, `core/memory.py`, `core/policy.py`, `edges/store.py`, `edges/adapters/system.py`, the two zero-caller ACL functions, `CLAUDE.md` |
| **W-4** | 16 | `serve.py`, `core/runs.py`, `core/schedule.py` (new), `cli/_pipeline.py` |
| **G-4b** | 15 | `core/models_policy.py`, `core/policy.py`'s audit hooks, `core/audit.py`, `cli/` models commands |
| **L-4** | 18 | spike — research + `specs/api/mcp-server.spec.md` only |

### W-5 — Structured handoff artifacts  *(Phase 16 · the wave's dispatch owner)*

**Status:** TODO · **Size:** M · **Branch:** `pc/w-5` · **Owns:** `core/dispatch.py`

Hops currently exchange **concatenated raw text**. Replace it with a typed record persisted per hop:
`{summary, files_changed, diff_ref, verdict, notes}`. **This card gates Phase 17's C-1** (the context
compiler needs structured inputs to budget), so the artifact shape is the deliverable, not a detail.

- **Read:** `core/dispatch.py` (R-1's v2 state machine + W-2's executor integration), `core/orchestrator.py`,
  `core/trace.py`, `specs/functional/pod-dispatch.spec.md` (v3.0.0), `specs/data/docket-meta.spec.md`.
- **Do:** a Pydantic `HandoffArtifact` in `core/handoff.py`; each hop writes one; the next hop's prompt is
  built *from the artifact*, not from the previous hop's stdout. Persist alongside the hop record so
  `--resume` recovers it. Keep R-7's token cap applying to the rendered prompt.
- **Also fix, because you own the file** (from the dead-code register): the `print()` at
  `core/dispatch.py:1313` (`"[dispatch] verification skipped — verifyCmd not set…"`) is a **layering
  violation** — `core/` never prints; return a typed result and let `cli/` render it. Then settle
  `dispatch_all_pods` (`core/dispatch.py:~1684`, flagged uncalled — wire it or delete it, and say which
  in the commit body).
- **Also finish CL-1's blocked sweep, because you own these test families:** the ~76
  `_oc.AgentRunResult(...)` call sites → `TurnResult` (in `test_r2/r4/r5/r6/r7`, `test_cd2`,
  `test_dispatch`, `test_g1_*`, `test_l1_*`). `AgentRunResult` is an alias of `TurnResult`; once every
  call site is converted, decide whether the alias can go (`core/dispatch.py:85`'s
  `Runner = Callable[..., _oc.AgentRunResult]` binds it at import time — check before deleting).
- **Acceptance:** a two-hop dispatch passes a typed artifact, not a string · resume after a crash
  recovers the artifact · no `print()` remains anywhere in `core/` or `edges/` (grep-pinned test) ·
  `pod-dispatch.spec.md` bumped with the artifact contract · goldens byte-identical.

### CL-2 — Dead-code register sweep, non-dispatch half  *(standing · "no legacy code")*

**Status:** TODO · **Size:** M · **Branch:** `pc/cl-2`

Execute the **High confidence** and **Medium confidence** rows of the register below, minus the three
W-5 owns. The operator's standing instruction is that refactors and new features leave **no legacy or
dead code** behind — this card is that instruction's board entry.

- **`core/sync.py` is an entirely dead module** — zero production importers (only `test_m2_data_layer.py`
  reaches it). `cli/_doctor.py:280-334`'s `_check_drift` reimplements the identical model+sessionKey
  comparison inline. **Resolve toward one implementation, and make CLAUDE.md true either way** — it
  currently documents `core/sync.py` as the module that "keeps the two config sources in sync", which is
  false today. Prefer keeping `sync.py` and pointing doctor at it (doctor's inline copy is the duplicate,
  and `core/` is where that logic belongs); if you delete `sync.py` instead, say why in the commit body.
  `SYNCED_FIELDS` is dead even *inside* `check_agent`, which hardcodes the field names.
- **`HEARTBEAT_FILE` unused while `"HEARTBEAT.md"` is hardcoded in 9 files** (`core/memory.py:57` defines
  it; the literal appears in `core/archetypes.py`, `cli/_conversations.py`, `_pod.py`, `_context.py`,
  `_agents.py`, `_install.py`, `__init__.py`, `_doctor.py`). Same shape as the `openclaw-gateway.service`
  duplicate L-2 already fixed — use that fix as the pattern.
- **Zero-caller ACL functions** — `meta_write` (`edges/adapters/openclaw.py:127`) and
  `set_agent_project_key` (`:173`) have no callers anywhere, tests included. Delete, or give them the
  caller they were written for; do not leave them.
- **Medium-confidence rows — verify first, then act or explicitly keep with a reason:** `with_lock()`
  (`edges/store.py:49`) — W-2 has now landed, so re-check whether the claim path gained a real call site;
  `docker_ps()`/`git_current_branch()` (`edges/adapters/system.py`); `validate_policy()`
  (`core/policy.py:44`, never called by the CLI — wire `docket policies validate` or remove).
- **Do NOT touch** the "Deliberately NOT dead" list below, and do not re-litigate the confirmed false
  positives (Typer `cmd_*`, `BaseHTTPRequestHandler` overrides, dynamically constructed enum members,
  Pydantic `model_config`, `RuntimeDriver` Protocol members).
- **Acceptance:** every row below is either fixed or annotated with a dated reason to keep · CLAUDE.md
  no longer describes a dead module as load-bearing · full suite + goldens green · **no behaviour change**
  (this is a cleanup card; a golden diff means you broke something).

### W-4 — Durable scheduling + event triggers  *(Phase 16)*

**Status:** TODO · **Size:** M · **Branch:** `pc/w-4`

- Persisted last-run so a `serve` restart does **not** re-fire a schedule; cron specs; webhook params
  bound into pipeline variables; `dispatch --follow` streaming from the trace.
- **Read:** `serve.py`, `core/runs.py`, `core/pipeline.py` (W-1's format), `core/orchestrator.py`,
  `specs/functional/pipeline-format.spec.md`, `specs/data/serve-read-api.spec.md`.
- **Also close, because you own `core/runs.py`:** the **`runs.cancel` audit gap** — W-2 shipped
  cancellation but it writes **no audit entry**. Every other privileged action does. Add it and cover it
  in `audit.spec.md`'s action families.
- **Acceptance:** restarting `serve` mid-window does not double-fire a schedule (test-pinned) · a webhook
  param reaches a pipeline variable · `runs cancel` writes an audit entry · specs bumped.

### G-4b — Audit coverage for `models.*`  *(Phase 15 · G-4 follow-up)*

**Status:** TODO · **Size:** S · **Branch:** `pc/g-4b`

`docket models set/preset/reset` change the role→model policy for the entire fleet and write **no audit
entry** — a gap G-4 named and left open, and it is still open after two waves.

- **Read:** `core/audit.py` (hash-chained log, action families), `core/models_policy.py`, the `models`
  commands in `cli/`, `specs/functional/audit.spec.md`, `specs/functional/model-profiles.spec.md`.
- Add the `models.*` action family with the same hash-chain guarantees as the existing families; cover
  `set`, `preset` and `reset`, recording enough to reconstruct what changed (role, before, after).
- **Also settle** `VerifyResult.total_lines` (`core/audit.py:206`) — populated at 7 construction sites and
  read by nothing. Render it in `docket audit verify` or remove the field.
- **Acceptance:** each of the three commands writes a verifiable entry · `docket audit verify` still
  passes over a log containing them · `audit.spec.md` bumped, and its "still uncovered" note updated to
  name only what genuinely remains.

### L-4 — MCP config plumbing  *(Phase 18 · spike, daemon-gated)*

**Status:** TODO · **Size:** S · **Branch:** `pc/l-4`

Can docket manage the daemon's own MCP server configuration through the ACL, or does that capability not
exist upstream? **Answer the question with evidence — do not build a speculative feature.** L-3's MCP
server ships regardless; this is about the *other* direction.

- **Follow G-5's pattern exactly** (the `[GATE]` seam spike, wave 3): probe the real upstream, record
  version/date/what was tried, and if the answer is **no**, land the dated evidence trail as the
  deliverable and change no production code.
- **Read:** `edges/adapters/openclaw.py` (the ACL is the only path to daemon config), `cli/_mcp.py`,
  `specs/api/mcp-server.spec.md`, ROADMAP §7 backlog.
- **Acceptance:** a yes/no with reproducible evidence, recorded in `mcp-server.spec.md`'s scope section
  and the commit body. A well-evidenced **no** is a complete card.

### Deferred out of wave 5 (with the reason, so it is not mistaken for an oversight)

- **G-2 / G-3** (policy engine on the live path, high-risk classes enforced) — G-2 needs `pre_input` at
  enqueue and `pre_output` on every hop output, i.e. `core/dispatch.py`, which W-5 owns this wave. G-3 is
  blocked on G-2. Both are wave 6's governance pair.
- **C-2 / C-3 / C-5** (Phase 17) — C-3 and C-5 need the dispatch file; C-2 (`core/memory.py`) would race
  CL-2's `HEARTBEAT_FILE` work in the same file.
- **C-1** (context compiler) — genuinely blocked on W-5's artifact shape, by design.
- **L-5** (wrapped gateway spike, D-18) — daemon-gated like L-4; running both spikes at once wastes a slot
  if the answer to L-4 already tells us the daemon's config surface is closed.

---

## Dead-code register (CL-1, 2026-07-30) — the standing "no legacy code" work list

Produced by a full-tree sweep. **Two entries were fixed and merged** (`ad8e14e`): `cli/_eval.py`'s
duplicate of `config.cli_root()`, and a stale `core/security.py` docstring. Everything below is
**found, verified, and not yet fixed** — mostly because the file belongs to an in-flight card.
Work these once the owning card merges.

### High confidence — fix these

| Finding | Location | Blocked by | Note |
| --- | --- | --- | --- |
| **`core/sync.py` is an entirely dead module** | whole file | **CL-2 owns this** | `check_agent`/`check_all`/`Drift`/`SYNCED_FIELDS` have **zero** production callers. `cli/_doctor.py:280-334`'s `_check_drift` reimplements the identical model+sessionKey comparison inline without importing it. **Independently verified: zero `import sync` in `src/`.** Note CLAUDE.md describes this module as the thing that "keeps the two config sources in sync" — the docs and the code disagree. Prefer keeping `sync.py` as the single source and pointing doctor at it. `SYNCED_FIELDS` is dead even *within* `check_agent`, which hardcodes the field names instead of iterating it. |
| **`HEARTBEAT_FILE` constant unused; literal hardcoded 8+ times** | `core/memory.py:57` | **CL-2 owns this** | The string `"HEARTBEAT.md"` is repeated across `cli/_agents.py`, `_pod.py`, `_install.py`, `_context.py`, `_doctor.py`, `cli/__init__.py`. Same shape as the `openclaw-gateway.service` duplicate fixed in L-2. |
| **`print()` inside `core/` — a layering violation** | `core/dispatch.py:1313` | **W-5 owns this** | `print(f"[dispatch] verification skipped...")` breaks the standing rule that `core/`/`edges/` never print; it should return a typed result for `cli/` to render. |
| **Zero-caller ACL functions** | `edges/adapters/openclaw.py:127, 173` | **CL-2 owns this** | `meta_write` and `set_agent_project_key` have no callers anywhere, tests included. |

### Medium confidence — verify before acting

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

### Still owed on CL-1's original card

The ~76 `_oc.AgentRunResult(...)` test call sites → `TurnResult`, the ad-hoc-double → `FakeDriver`
sweep, and the legacy `CostTotals`/`DayRecord` decision. W-2 has landed, so these are **unblocked**;
**W-5 owns them** together with the dispatch-adjacent test families it is already editing.

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
- Hops still exchange **concatenated raw text**, not structured artifacts (W-5, in flight this wave).
- `scripts/validate-specs.sh` has a **pre-existing bug**: two spec references on one line produce a false
  broken-reference warning. Unowned — claim it with whatever card next touches the script.
