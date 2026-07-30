# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> *Phase 13 (Close the differentiation gaps, FD-0…FD-7) is **COMPLETE** (2026-07-02) — its durable
> record lives in ROADMAP.md's Phase 13 section. Its board was cleared per the convention above.*
>
> ---
>
> ## Active: PHASE 14 — Platformization I: runtime truth & dispatch hardening
>
> Executable board for **PHASE 14** in [ROADMAP.md](ROADMAP.md) (read that section first — the
> defect rationale, explicit **keeps**, and exit criteria; also decisions **D-15/D-17** in §6 and
> the 2026-07-30 Platformization amendment in §4.5). Source of record:
> `internal-docs/agent-platform-audit-and-build-plan.md` (2026-07-29 four-pass platform audit,
> gitignored local rationale — every defect below was code-verified with file:line evidence and is
> restated self-containedly here). This phase is the **foundation** of the Platformization program
> (Phases 14–18): Phases 15–18 (wired governance, declarative orchestration + role archetypes,
> context/memory, driver port + MCP) all execute through this dispatch lane, so it hardens first
> and **nothing from a later phase ships before this board is green**.
>
> **What we're doing (one paragraph):** make the dispatch lane crash-safe, race-free, observable,
> and honest. Today the pod queue has an unlocked read-modify-write (concurrent serve threads can
> double-run a task), no persisted `running` state (a crash re-pays every hop), no retries, no
> cancellation, one hardcoded 300s timeout, budget-`blocked` tasks that silently retry forever, a
> Reviewer role whose verdict is never parsed, an auto-pause that was never ported from Bash, a
> verifyCmd that runs in the wrong tree, unbounded hop prompts, and a serve lane that swallows every
> exception behind fire-and-forget threads. R-1…R-7 fix the mechanics; R-8 makes the specs/docs stop
> overclaiming what the code does.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (always):** ROADMAP.md's Phase 14 section, §2 (Python ground truth), §4.5
   (architectural principles, incl. the 2026-07-30 Platformization amendment), [CLAUDE.md](CLAUDE.md),
   and the task's own "Read" list.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. OpenClaw formats live **only**
   in `edges/adapters/openclaw.py` (the ACL). docket-owned JSON goes **only** through `edges/store.py`
   (JSONL append logs are the one D-12 exemption). Every shell-out goes through `edges/adapters/`.
   `core/`/`edges/` never import `ui.py` or print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds
   new CLI surface (R-2's `--timeout` flags, R-3's `docket runs`, R-5's `--resume`) — those cards
   say so and require regenerated goldens with the diff explained in the PR.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `uv run python scripts/metrics.py --check` green · committed `Type: description` (no
   Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs R-x)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** this phase lives on the long-running **`platform`** branch (a deliberate
fork-candidate line — see ROADMAP §8). One short-lived `pc/r-<id>` branch per task → PR into
`platform`, never directly into `main`.

---

## Dependency map (what unblocks what)

```text
R-1 (state machine v2) ──┬── R-2 (retries/timeouts — extends R-1's task record)
                         ├── R-3 (run registry — persists R-1's states)
                         ├── R-4 (reviewer gate + rework loop — new hop edges need R-1's attempts)
                         └── R-5 (auto-pause — dispatch refusal reads R-1's claim path)
R-6 (verifyCmd fixes) ── independent, parallel-safe with everything
R-7 (bounded hop prompts) ── independent, parallel-safe with everything
R-8 (spec/docs truth pass) ── LAST — documents whatever R-1..R-7 actually shipped
```

---

### R-1 — Task state machine v2: persisted `running`, locked claims, crash recovery

- **Depends on:** — · **Blocks:** R-2, R-3, R-4, R-5.
- **Read:** `core/dispatch.py` in full (`enqueue_task` ~L110-129, `dispatch_pod` ~L406-436 — the
  unlocked read at ~L420 vs write at ~L434, `_apply_result` ~L384-403 and its `blocked→pending`
  rewrite at ~L399-401, `startedAt` set in memory only at ~L430); `edges/store.py` (`read_json`
  takes no lock ~L35-40; `write_json`'s per-directory filelock ~L43-83); `serve.py` ~L214-268 +
  ~L364-382 (the three thread sources that can dispatch one pod concurrently);
  `tests/python/test_dispatch.py`.
- **Why:** the queue is the substrate for every later phase. Today two concurrent dispatchers can
  both select the same `pending` task (read is unlocked, there is no claim state) and clobber each
  other's results; a crash mid-task leaves `pending` and re-runs — re-paying — every hop; a
  budget-`blocked` task is rewritten to `pending` and retries on every sweep forever.
- **Do:**
  1. Add task states `running` and `waiting` (persisted immediately, not post-hoc): claim =
     locked read-modify-write that flips `pending→running` and writes `startedAt`+`claimId` to disk
     **before** the first hop. Extend `store.py` with a `with_lock(path)` context (or a
     `read_modify_write` helper) so the claim is atomic under the existing per-directory filelock.
  2. Persist per-hop progress as it happens (the `hops[]` array already exists — write it after
     each hop, not only at task end) so recovery can resume from the last completed hop.
  3. Crash sweep: a `running` task whose `claimId` is stale past its timeout is swept to `failed`
     with a `stale_claim` trace event and is resumable (`--resume` re-claims and continues from the
     last persisted hop instead of hop 0).
  4. `blocked` stays `blocked` (kill the `→pending` rewrite); it re-enters `pending` only when the
     pod budget changes (`docket profile --budget`) or via an explicit `docket pod <p> queue
     --retry <task-id>`.
  5. Task ids: `task-<uuid4>` (keep a `created` timestamp field; epoch-ms ids collide under
     concurrent enqueue and leak ordering assumptions).
  6. Tests: thread-race test proving two concurrent `dispatch_pod` calls cannot double-run one
     task; kill-mid-task resume test (fake runner, assert earlier hops not re-invoked); blocked
     stays blocked across sweeps.
- **Out of scope:** parallel hop execution (Phase 16 W-2); changing the pipeline order or gates.
- **Deliverables:** state machine v2 in `core/dispatch.py`; locked-claim helper in `edges/store.py`;
  migration shim (old TASK_LIST.json records without the new fields load fine); tests.
- **Acceptance gate:** [x] concurrent-dispatch race test green · [x] resume-from-hop test green ·
  [x] `blocked` never auto-retries · [x] old queue files still load · [x] suite + goldens green.
- **Size:** L (split: claims/states vs recovery/resume) · **Status:** DONE (pc/r-1) — claims via
  `store.read_modify_write`; `running`/stale-claim/`--resume` land in `core/dispatch.py`; `blocked`
  no longer auto-retries (`retry_task`/`unblock_pod`, wired to `queue --retry` and `profile
  --budget`); task ids are `task-<uuid4>`. R-2/R-3/R-4/R-5 can now proceed.

---

### R-2 — Retries + configurable timeouts (turn vs verify decoupled)

- **Depends on:** R-1 (task record gains `attempts`) · **Parallel-safe with:** R-3, R-4, R-5, R-6, R-7.
- **Read:** `core/dispatch.py` `DEFAULT_TIMEOUT = 300` (~L32) and its two consumers (agent turn
  ~L286, verify ~L350); `edges/adapters/openclaw.py` `agent_run` failure modes (~L979-999 —
  `TimeoutExpired`, `OSError`, non-zero exit, non-JSON-stdout-treated-as-success); `cli/_pod.py`
  `_pod_dispatch` (~L735-758, passes no timeout today); `serve.py` dispatch call sites.
- **Why:** one attempt per hop and one hardcoded constant for two unrelated operations. A transient
  daemon hiccup kills a whole task; a 20-minute test suite can't be verified; a hung turn and a hung
  verify are indistinguishable.
- **Do:**
  1. Failure taxonomy on `AgentRunResult` (`timeout | daemon_error | nonzero_exit | invalid_output`)
     — retries apply only to retryable kinds (timeout, daemon_error), with per-role `retries` +
     linear backoff, `attempts` persisted per hop (R-1's record).
  2. Config: `turnTimeoutS` / `verifyTimeoutS` per pod (Lead meta), `--timeout` on
     `docket pod <p> dispatch`, serve config knob; `DEFAULT_TIMEOUT` becomes the fallback only.
  3. Tests: retryable vs non-retryable paths; attempts persisted; verify timeout independent.
- **Out of scope:** model-fallback-on-failure (stays out per Phase 6b — retry same model only).
- **Deliverables:** taxonomy, retry loop, timeout knobs, tests; golden update for new `--help` text.
- **Acceptance gate:** [x] a timed-out hop retries up to its budget then fails with `attempts`
  recorded · [x] verify and turn timeouts settable independently · [x] suite + goldens green.
- **Size:** M · **Status:** DONE (pc/r-2) — `AgentRunResult` gains a `failure_kind`
  (`timeout | daemon_error | nonzero_exit | invalid_output`), additive/backward-compatible; only
  `timeout`/`daemon_error` are retryable (`core/dispatch.py`'s `_RETRYABLE_FAILURE_KINDS`). Per-role
  retry budget + linear backoff (`config.DISPATCH_RETRIES_PER_ROLE`/`DISPATCH_RETRY_BACKOFF_S`);
  `attempts` persisted per hop (`HopResult.attempts`, round-trips through `_hop_record`/
  `_hop_from_record`); a `hop_retry` trace event per attempt. `turnTimeoutS`/`verifyTimeoutS` on the
  Lead's meta (alongside `budgetUsd`), a `--timeout` override on `docket pod <p> dispatch`
  (overrides both for that run), and a `DISPATCH_TURN_TIMEOUT_S`/`DISPATCH_VERIFY_TIMEOUT_S` serve
  config knob — `DEFAULT_TIMEOUT` is now the last-resort fallback only. **Stale-claim interaction**
  (the subtle point this card called out): a retry adds backoff + another turn-timeout to a hop's
  wall-clock time on top of whatever earlier hops already took, so a legitimately-still-running
  retry loop could now exceed `CLAIM_STALE_TIMEOUT` and get swept as `stale_claim` by a *concurrent*
  dispatcher's sweep (the same concurrency R-1's locked claims exist for). Fixed by refreshing
  `claimedAt` on every retry (`dispatch_task`'s `on_retry` → `_touch_claim`) and on every completed
  hop (`_persist_hop`, extended) — both are real forward progress, not staleness. No golden diff:
  `docket pod` isn't part of the golden suite (its `--help` text lives in raw `ctx.args`, not a
  Typer-documented option) and the static `docket help` blob in `cli/_help.py` was left untouched
  (matching R-1's own `--resume`, which also isn't listed there). New tests in
  `tests/python/test_r2_retries.py` (23 cases) rather than growing `test_dispatch.py`.

---

### R-3 — Run registry + job API; ban suppressed exceptions in the dispatch lane (D-17)

- **Depends on:** R-1 · **Parallel-safe with:** R-2, R-4, R-5, R-6, R-7.
- **Read:** `serve.py` in full — the four `contextlib.suppress(Exception)` sites around dispatch
  (~L235, ~L258-268, ~L375), the fire-and-forget webhook (~L364-382, returns 200 with no id), the
  in-memory `_schedule_state` (~L214); `cli/__init__.py` serve wiring (~L1575-1595);
  `specs/data/serve-read-api.spec.md` (the versioned read-API contract to extend, pinned by test).
- **Why:** D-17. Background dispatch is unobservable: no run id, no status query, and every
  exception is silently discarded — an operator cannot distinguish "done", "failed", and "never
  ran".
- **Do:**
  1. `core/runs.py`: a persisted run registry (docket-owned JSON via `store.py`) — one record per
     dispatch invocation (`run-<uuid>`, source: cli|webhook|schedule|sweep, project, task ids,
     state, error, timestamps). CLI: `docket runs [list|show <id>]`.
  2. `POST /dispatch/<project>` returns `{"run": "<id>"}` **after** enqueueing the run record;
     work still executes async, but its outcome lands in the registry. New `GET /runs/<id>` +
     `GET /runs?project=` (Bearer-authed, added to the read-API spec with a version bump).
  3. Remove every `contextlib.suppress(Exception)` around dispatch: exceptions are caught, written
     to the run record + an `error` trace event, and (for the sweep loop) logged without killing
     the sweeper. Persist scheduler last-run into the schedules file (kills the restart-refire bug).
  4. Tests: webhook returns a queryable id; an induced dispatch exception is visible in
     `docket runs show`; scheduler survives restart without re-firing.
- **Out of scope:** cancellation (Phase 16 W-2 — needs process-group plumbing); a web UI.
- **Deliverables:** `core/runs.py`, `docket runs`, extended serve endpoints + spec bump, durable
  scheduler state, zero suppressed dispatch exceptions; tests; goldens for new CLI surface.
- **Acceptance gate:** [ ] every dispatch path yields a queryable run record · [ ] induced failure
  visible with its error · [ ] no `suppress(Exception)` remains around dispatch (grep-pinned test) ·
  [ ] scheduler state survives restart · [ ] suite + goldens green.
- **Size:** L (split: registry/CLI vs serve wiring) · **Status:** TODO

---

### R-4 — Reviewer verdict gate + bounded rework loop

- **Depends on:** R-1 (persisted per-hop progress; rework consumes `attempts`) · **Parallel-safe
  with:** R-2, R-3, R-5, R-6, R-7.
- **Read:** `core/dispatch.py` tester gate (~L326-342, `_parse_tester_verdict` ~L39-52 — the
  structural pattern to mirror) and the straight-line hop loop (~L254); `cli/_pod.py` reviewer SOUL
  body (~L79-85: "APPROVE or REQUEST-CHANGES", veto prose the pipeline never reads);
  `tests/python/test_fd2_tester_gate.py` (fixture pattern).
- **Why:** the Reviewer's documented contract is a veto, but dispatch never parses its output — a
  REQUEST-CHANGES review advances to the tester and the task completes `done`. The role is
  mechanically decorative; separation-of-duties is prose.
- **Do:**
  1. Parse the reviewer hop's first non-blank line for `APPROVE|REQUEST-CHANGES` (case-insensitive,
     same regex style as the tester gate). Unparseable ⇒ fail with a distinct reason
     (`reviewer_verdict_unparseable`), mirroring FD-2's convention.
  2. REQUEST-CHANGES ⇒ loop back to the implementer **once** (config `maxReworkCycles`, default 1):
     re-run the implementer hop with the review text appended, then reviewer again; a second
     REQUEST-CHANGES fails the task (`review_rejected` trace event). Rework cycles are recorded in
     the persisted `hops[]`.
  3. Update the reviewer SOUL text to state the parsed marker convention (as FD-2 did for tester).
  4. Tests: APPROVE advances; REQUEST-CHANGES triggers exactly one rework then re-review; second
     rejection fails; unparseable fails distinctly; pods without a reviewer unaffected.
- **Out of scope:** parsing anything beyond the first-line marker (no diff-level review semantics);
  reviewer gating for non-code pods (Phase 16 W-8 generalizes gates).
- **Deliverables:** reviewer parser + rework edge in dispatch; SOUL wording; trace events; tests.
- **Acceptance gate:** [x] REQUEST-CHANGES blocks and triggers a bounded rework cycle · [x]
  unparseable output blocks distinctly · [x] APPROVE/no-reviewer behavior unchanged · [x] suite green.
- **Size:** M · **Status:** DONE (pc/r-4) — `_parse_reviewer_verdict` mirrors `_parse_tester_verdict`
  exactly; the hop loop is now pointer-based (`pipeline_index`) instead of a role-presence set so a
  role can legitimately run twice (rework). `pod_max_rework_cycles` reads the Lead's
  `maxReworkCycles` meta (default 1, same convention as `budgetUsd`). A REQUEST-CHANGES with budget
  left jumps `pipeline_index` back to the Implementer and re-runs it with the review text as a
  dedicated, un-derated "REWORK REQUIRED" section in `_hop_message` (excluded from the generic
  recency-ranked carryover loop so it's never truncated away and never rendered twice) — see R-7
  interaction note below. Every rework hop persists through the existing `on_hop`/`_persist_hop`
  path into `hops[]`. New `_replay_pipeline_position` helper replays a resumed task's persisted
  hops to recompute `(pipeline_index, rework_count, pending_rework)` — resuming mid-rework
  re-enters the rework Implementer hop, not a stale position past the Reviewer (a naive
  role-was-seen resume would have silently skipped the rework); test-pinned in
  `TestReviewerReworkResume`. New trace events `rework_started`/`review_rejected`/
  `reviewer_verdict_unparseable`. Reviewer SOUL text (`cli/_pod.py`) states the marker convention,
  following FD-2's tester precedent. Fixed several pre-existing test fixtures
  (`test_cd2_verify.py`'s `_runner_with_tester_output`/`test_verify_pass_continues_to_reviewer`,
  `test_dispatch.py`'s `_VerdictAwareRunner`) whose generic non-APPROVE reviewer stubs would
  otherwise now fail under the new gate, plus one exact-string test in
  `test_r7_hop_carryover.py` for the updated Reviewer instruction line. Tests:
  `tests/python/test_r4_reviewer_gate.py` (25 cases). `maxReworkCycles` has no dedicated CLI
  setter yet (out of scope per the card — set via the internal `meta-set` path if a non-default
  value is needed).

---

### R-5 — Budget honesty: implement auto-pause, fix the paused-flag bug, labeled estimates

- **Depends on:** R-1 (dispatch refusal integrates with the claim path) · **Parallel-safe with:**
  R-2, R-3, R-4, R-6, R-7.
- **Read:** `core/models.py` ~L88-90 (`budget_usd`, `paused`, `paused_reason` — declared, never set
  true anywhere); `cli/__init__.py` ~L757-766 (`--budget` — the only writer, and it *clears* the
  flags); `cli/_agents.py` ~L541,562-584 (reads `paused` with a **string** compare `== "true"`
  while the writer stores a bool); `core/dispatch.py` budget gate (~L263-275, pre-hop, pod-wide via
  the Lead's cap) and `pod_recorded_cost` (~L155-161); `core/utils.py` `aggregate_cost`
  (~L91-176 — dollars come only from the daemon's `usage.cost.total`, which daemon v2026.2.23 may
  never write); `edges/adapters/openclaw.py` ~L881-891 (`cost_usd` always 0.0 note);
  `core/models_policy.py` `MODEL_PRICING` (~L63-77); ROADMAP D-9 (budget fields are docket-local).
- **Why:** "per-agent USD budget caps with auto-pause" is a headline claim (CLAUDE.md, README) and
  the pause half **does not exist** — it was Phase 1 Bash-era behavior the Python port dropped. And
  when the daemon writes no `usage.cost.total`, recorded spend is 0 and the cap never trips at all.
- **Do:**
  1. Implement the pause writer: after each hop and in the serve sweep, if an agent/pod is at ≥100%
     of cap ⇒ `meta.paused=true, pausedReason="budget"` (through `store.py`); dispatch refuses
     paused members at claim time with a `paused_refused` trace event; `docket profile <id>
     --resume` clears with an audit entry. Warn path at ≥80% (display only) stays.
  2. Fix the read bug: one typed accessor on `AgentMeta` (bool), used by `_agents.py` display and
     dispatch alike; migration-tolerant of legacy `"true"` strings.
  3. Estimation fallback for gating: when session JSONL carries tokens but no `cost.total`, compute
     `estimatedUsd` from token counts × `MODEL_PRICING` **for gating and warning only**, always
     rendered as `~$X.XX (estimated — daemon recorded no cost)`; never mixed into "recorded" totals
     (`docket cost` provenance line stays truthful; no-dollar-savings discipline intact).
  4. Tests: cap breach pauses + dispatch refuses + resume clears; string/bool legacy meta reads
     correctly; estimate path gates when recorded cost is absent and labels itself.
- **Out of scope:** daemon-side pause (D-9: budget state is docket-local); per-turn in-flight
  metering (Phase 18 L-5's problem); any savings claims.
- **Deliverables:** pause writer + dispatch refusal + `--resume`; typed accessor; labeled estimate
  path; audit entries; tests; docs line-up (CLAUDE.md/README claim matches shipped behavior).
- **Acceptance gate:** [ ] an over-cap agent is actually paused and refused, test-pinned · [ ]
  legacy string flag reads correctly · [ ] estimates gate and are always labeled · [ ] suite +
  goldens green.
- **Size:** M · **Status:** TODO

---

### R-6 — verifyCmd correctness: worktree cwd, bounded shell surface, audited setter

- **Depends on:** — · **Parallel-safe with:** everything.
- **Read:** `core/dispatch.py` verify gate (~L345-372 — cwd = `meta["codebase"]` at ~L348-349);
  `cli/_pod.py` worktree provisioning (~L251-253 writes `worktreeDir`) and
  `_regenerate_member_tools` (~L641 — already prefers `worktreeDir`, the precedent);
  `edges/adapters/system.py` `run_verify_cmd` (~L191-215, `shell=True`, 4096-char cap);
  `cli/_pod.py` `set-verify` (~L655-677).
- **Why:** a worktree-pod implementer's work is verified against the **shared repo root**, not the
  worktree it actually changed — the gate can pass on stale code or fail on someone else's; and the
  command is `shell=True` on a meta value with no independent audit trail of who set it.
- **Do:**
  1. cwd resolution: `worktreeDir` if present → else `codebase` → else workspace (one helper,
     shared with `_regenerate_member_tools` so the two can't diverge again).
  2. Bound the shell surface: keep `shell=True` (verify commands legitimately use `&&`/pipes) but
     length-cap the stored command, reject NUL/newline injection at `set-verify` time, and write an
     `audit_log("pod.set-verify", …)` entry naming member + command (governance for the one
     process docket itself launches — Phase 15 G-3 extends this).
  3. Tests: worktree cwd used when present; fallback order; set-verify validation + audit entry.
- **Out of scope:** sandboxing the verify command (daemon/Docker lane); argument-level high-risk
  matching (Phase 15 G-3).
- **Deliverables:** cwd helper + dispatch fix; setter validation + audit; tests.
- **Acceptance gate:** [ ] verify runs in the member's worktree when one exists · [ ] set-verify is
  validated + audited · [ ] suite green.
- **Size:** S · **Status:** TODO

---

### R-7 — Bounded hop prompts (stopgap until Phase 17's context compiler)

- **Depends on:** — · **Parallel-safe with:** everything.
- **Read:** `core/dispatch.py` `_hop_message` (~L174-198 — concatenates the **full raw output of
  every prior hop**, no cap); `config.py` context knobs (~L32-39, the honest bytes/4 comment — the
  estimator to reuse).
- **Why:** a 4-hop task's tester prompt carries three complete prior outputs verbatim; long tasks
  grow context (and cost) unboundedly, and there is no record of what was sent.
- **Do:**
  1. Per-hop carryover cap (config `hopCarryoverBytes`, default ~32KB): keep the task description
     whole; truncate each prior hop's output head+tail with an explicit
     `[... truncated N bytes ...]` marker, newest hop least-truncated.
  2. Log composition per hop (a `context_composed` trace event: per-section byte counts,
     truncated-or-not) so Phase 17's compiler has a measured baseline.
  3. Tests: cap enforced; marker present; task description never truncated; small tasks unchanged.
- **Out of scope:** token-accurate budgeting, priority ordering, artifact rendering (all Phase 17
  C-1 — this card is the safety cap, not the compiler).
- **Deliverables:** capped `_hop_message` + config knob + trace event; tests.
- **Acceptance gate:** [x] no hop message exceeds the configured cap (test-pinned) · [x]
  truncation is explicit in the prompt and the trace · [x] suite green.
- **Size:** S · **Status:** DONE

---

### R-8 — Spec & docs truth pass (LAST — documents what R-1..R-7 actually shipped)

- **Depends on:** R-1…R-7 landed.
- **Read:** the Phase-14 spec refactor commit on this branch (specs were re-statused 2026-07-30 —
  keep them true); `specs/functional/pod-dispatch.spec.md` (must gain the v2 state machine, retry,
  rework-loop, run-registry, pause semantics); `specs/data/serve-read-api.spec.md` (R-3's version
  bump); `specs/functional/cost-tracking.spec.md` (auto-pause becomes real — flip its gap note);
  `specs/functional/audit.spec.md` (new entries from R-5/R-6); `cli/_provider.py` ~L84 (nonexistent
  `docket models set task` guidance) and ~L100 (raw-openclaw instruction — contradicts the product
  proposition); `tests/evals/lib/eval-helpers.sh` ~L56-80 (parses a different daemon JSON shape
  than the ACL — reconcile to the ACL's `result.payloads[0].text`); the duplicated
  `openclaw-gateway.service` constant (`edges/adapters/system.py` ~L21 vs `core/utils.py` ~L35 —
  single-source it).
- **Why:** honesty is the product's stated trust edge and Phase 14 changes real behavior; specs and
  guidance strings must land in the same phase, not drift behind (the exact failure mode Phases 12
  and 13 each had to clean up once already).
- **Do:** update every spec touched by R-1..R-7 with version bumps; fix the two `_provider.py`
  guidance bugs; reconcile the eval harness parser; de-duplicate the unit-name constant; run the
  full doc drift guard (`scripts/metrics.py --check`) and `docs/commands.md` additions for `docket
  runs`, `--resume`, `--retry`, timeout flags.
- **Out of scope:** the broad spec restructure (done 2026-07-30 on this branch, before R-1).
- **Deliverables:** true specs; fixed guidance; reconciled eval parser; single-sourced constant;
  green drift guard.
- **Acceptance gate:** [ ] every Phase-14 behavior is specified with a bumped version · [ ] no spec
  Status line contradicts the code (spot-audit) · [ ] metrics/drift guard green · [ ] suite green.
- **Size:** M · **Status:** TODO

---

## Roll-up checklist (Phase 14 definition of done — mirrors ROADMAP exit criteria)

- [x] R-1 — two concurrent dispatchers cannot double-run a task; crash resumes from last hop;
  `blocked` never auto-retries.
- [x] R-2 — retryable failures retry with persisted `attempts`; turn/verify timeouts independent.
  *(DONE, pc/r-2)*
- [ ] R-3 — every dispatch has a queryable run id; zero suppressed exceptions in the lane;
  scheduler state survives restart.
- [x] R-4 — REQUEST-CHANGES blocks and drives one bounded rework cycle.
- [ ] R-5 — an over-cap agent is genuinely paused and refused; estimates always labeled.
- [ ] R-6 — verify runs in the worktree; setter validated + audited.
- [x] R-7 — hop prompts capped with explicit truncation.
- [ ] R-8 — specs/docs/guidance match everything above; drift guard green.
- [ ] Full suite green throughout: ruff + format + mypy strict + pytest + goldens +
  `scripts/metrics.py --check`.
