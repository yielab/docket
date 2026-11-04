# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> **History lives elsewhere.** Every closed wave and phase section that used to sit in this file is
> archived verbatim in [docs/cycles-ended/](docs/cycles-ended/README.md) (`todo-waves.md`, with a
> SHA-256 manifest). This file holds only the usage rules, the active section and planned sections.
> Do not mine the archive for work.
>
> ---
>
> **Scheduling rule:** schedule by **file contention**, not phase number. Cards that edit the same
> files run one after the other, and work that would touch the same files twice belongs to one card.
> Parallel lanes are allowed only when they share no file, spec, persisted state or live environment;
> finishing a card well matters more than running two at once.
>
> ## ▶ BOARD — no active phase (Phases 63 and 64 closed 2026-11-04); Phase 66 planned (D-87 proposed)
>
> **No active phase.** Phase 66 (the context a turn sends) is planned below as `○ PLANNED` and waits for the
> maintainer's decision on D-87; its cards are not claimable until the section reads `ACTIVE`. Phases 63 (D-85) and 64 (D-86) closed 2026-11-04 on three shared waves: a plan of
> record reads a pod's contract (`delivers`, `methods`, `needs`, `budget`), applies to any shape, resumes a
> pod over HTTP and queries its memory by status; the pod's memory is verified for every pod, `stale` when a
> path goes, and the live smoke runs jailed by default. Their sections are archived and what they leave open
> is under "Phases 63-64" in the follow-ups below.
> Before them, Phases 60 (D-82), 61 (D-83) and 62 (D-84) closed 2026-11-03: a transient failure costs a request, a pod says what it can reach, and `fetch` keeps the perimeter. Their sections are archived and what they leave open is in the follow-ups below. Phase 59 (D-81, [ADR 0038](docs/adr/0038-a-step-budget-is-a-checkpoint-not-a-cliff.md)) closed 2026-11-03
> (decision 5 amended before the push): a step's budget is a checkpoint, not a cliff, and docket keeps no dollars. Its
> section is archived and what it leaves open is under "Phase 59" in the follow-ups below. Phase 58 (D-80) closed 2026-11-02: what a plan of record needs to follow a team it does
> not run. Its section is archived and what it leaves open is under "Phase 58" in the follow-ups below.
> **Phase 57** (D-79, [ADR 0037](docs/adr/0037-what-docket-gives-a-manager-in-the-plan-of-record.md)) closed 2026-11-01. Before it, Phase 56 (D-77, [ADR 0036](docs/adr/0036-a-pod-works-outward.md) decisions 13-16) closed
> 2026-10-30: an external service is declared, not programmed; a pod keeps records; one judge; one home layout; the
> four team shapes. Its section is archived and what it leaves open is under "Phase 56" in the follow-ups below.
> Decisions 15-16 of the ADR were accepted by the maintainer the same day. Phase 55
> closed 2026-10-30; Phases 52 to 54 closed 2026-10-29. The integration branch is `develop`. A new phase starts from
> a measured trigger or a maintainer request.

## How to use this board (read before claiming a card)

1. **One card is one worker run.** Its steps are ordered; each step ends green and committed. A run
   that does not finish parks at its last green commit and the card's Status names what is left; the
   next run continues the same card. A card is never split into sub-cards to make it fit.
2. **Claim.** Set Status to `IN-PROGRESS (@who)`; one owner per card. The worker gets a worktree made
   by hand from the integration branch's current head (`git worktree add -b <branch>
   .claude/worktrees/<card> <sha>`), and its own `DOCKET_HOME` and temp directory in the scratchpad.
3. **Read bounded.** `python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`, then
   the card's own read list. Never all of `ROADMAP.md`, `TODO.md`, `CLAUDE.md` or a spec directory.
   A task worktree has no `internal-docs/` (gitignored); a card needs only itself and tracked files.
4. **The layer rule** is ADR 0030's table, enforced by `tests/architecture/`: the contexts are layered
   `platform < governance < agent < models < observability < pipeline < teams < sandbox < operator <
   tasks < hops` and a context imports only those below it; `kernel` imports nothing outside itself;
   a `domain/` is pure; only `interfaces/` talks to the user; `bootstrap.py` is the only module that
   names a concrete adapter. Two invariants never move: every tool call passes `dispatch_tool`
   (`agent/tools/registry.py`), and docket-owned JSON is written only by `platform/store.py`.
5. **The testing budget, the same for every card.**
   1. Per commit: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run
      pytest --co -q` (about 10 s). No test runs.
   2. While iterating: only the tests of what the step changed, by path, each under `timeout 120`.
   3. The card's gate, as the card names it, in a few minutes.
   4. A pure move or rename adds no test: `pytest --co` and `tests/architecture` are its check. A
      behaviour change adds a failing test first, placed by lane (`specs/test-framework.md`).
   5. After each merge the integrator runs the default suite once, in parallel (`uv run pytest -n auto
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 85 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge. What
      each check costs, measured, is in `.agents/skills/docket-spec-work/references/validation.md`.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, the generated-docs checks and the real run: once, at
      the phase close. The agent lane takes about 5 min.
   7. **Stop rule:** a check that fails again after one fix stops the step. Park with the failing line
      and the hypothesis. No third attempt, no "until green", no background process or polling, no
      `git stash` (a WIP commit sets work aside).
   8. **A script is a means, not a deliverable.** A one-shot script (planner, path rewriter,
      converter) exists to save effort on the card's goal. Write it once, run it, review its output,
      and finish by hand whatever it did not cover. If it is wrong after one fix, stop improving it
      and do the remainder by bounded edits. Polishing, generalizing or testing a throwaway script is
      out of scope; it is never committed unless the card says so.
6. **Baselines only shrink.** A baseline file is rewritten (`--write`) only after the violations are
   gone, and its diff is deletions only. A new guard is trusted only after it was seen failing on a
   planted case.
7. **No behaviour change** unless the card says so: the HTTP API 6 tests, the CLI goldens and the
   `docket_runtime` facade stay byte for byte. **No re-export or shim:** a replaced name is
   deleted in the same change, with no alias or compatibility reader.
8. **Central files are integrator-owned:** `TODO.md`, `ROADMAP.md`, `README.md` metric counts and
   `CHANGELOG.md`. A worker reports what shipped; it does not edit them.
9. **Commits:** `Type: description`, ASCII only, a detailed body, no AI or assistant attribution.
   Scrub `/home/<user>` paths and real names from every diff.

**Status:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `PARKED (left: X)` · `DONE`.
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once · XL ≈ two cards'
scope in one pass over the same files, parks at least once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`).
`main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ○ PHASE 66 PLANNED — the context a turn sends is protected, reduced by what it carries, explained and recoverable (D-87, proposed 2026-11-04, awaiting the maintainer)

> From the context-engineering audit of 2026-11-04 (`internal-docs/audits/context-engineering-2026-11-04.es.md`,
> the maintainer's request; code read at `2462c872`, every locator re-checked there). Four measured facts drive
> the phase; the rest of the audit's list keeps its trigger. **Measured, live home since 2026-10-24:**
> (a) 77 compaction checks, 4 summaries, 0 failures; the three summaries persisted sit at index 0 of their
> sessions, which is what compacting a one-turn history over the 6000-token `hosted` budget looks like, not a
> defect: the turn's own task is appended after the pre-turn compaction and is never in its range (the audit
> first read it as one; corrected the same day). The `hosted` history share stays deferred with its trigger;
> (b) the first request of a hop measures 1.55x its estimate (median, n=75; p90 1.64, max 1.69), every later
> request 1.00x (median, n=173): the bytes/4 estimator is right once calibrated and wrong on the one request
> that carries the whole history (`request_fit.estimatedInputTokens` against the next `llm_call.inputTokens`);
> (c) a synthetic history of 12 reads of about 9.6k characters estimates 29,886 tokens raw and 6,210 once
> projected by `condense_history` (4.8x), while `reduce_for_fit` subtracts a projected overflow from the raw
> figure; (d) 256 calls sent 34 % of their bytes as tool results and 25 % as tool schemas, with 53 % of input
> tokens read from cache. Not planned, each with its trigger on this board or in the audit: a lazy MCP
> catalog, lifecycle condensation, the `hosted` history share, recitation of the objective, a JSONL session
> store, a cheaper summarizer model, server-side compaction or `count_tokens` on the Anthropic dialect.
>
> **Decisions the plan takes (for the maintainer; D-87 is `Proposed` until accepted):**
> 1. Every line docket writes to steer the model and nothing else is request-only: the budget notice joins
>    the landing ask and the closing ask as a trailing `user` message, never written to `session.json`.
>    Requirement 108's "appended to the last tool result" becomes "appended to the next request". The
>    pre-turn compaction keeps its order: the task is appended after it and is never summarized by it.
> 2. A request that does not fit is reduced by what the request carries. The range to summarize is chosen
>    by the projected size of its atomic units (the same `condense_history` the request uses), oldest first,
>    until the overflow is covered, and that range is summarized whole (`budget_tokens=0` on a range means
>    the whole range; `plan_compaction` already does that for a range with an anchor). The budget-driven
>    pre-turn compaction keeps its budget semantics.
> 3. A compaction leaves a record. The replaced messages and the summary are written to
>    `<session dir>/compactions/<seq>.json` by `platform/store.py`, same permissions as `session.json`, in
>    the same locked mutation; the `session_compaction` event names the record and the summarized range.
>    State, not trace: the trace keeps counts, as today.
> 4. The compaction summary is stored with role `user`, prefixed `[compacted summary of ...]` as today, so
>    both dialects carry it in chronology (the Anthropic wire lifts every `system` into the `system`
>    parameter, out of order, and puts the cache breakpoint on it). A session written before this phase is
>    read as it is: an old `system` summary is one more body unit, never re-labelled (no compatibility
>    reader, D-34). Requirements 11, 13 and 25 say "the summary message", not "a system message".
> 5. The summarizer prompt is a shipped prompt document, `layer: compaction`, resolved through the four
>    scopes like every prompt (ADR 0035), reached by the engine through the `RoleComposer` port; its sha256
>    is on the `session_compaction` event. The body has sections (objective and state; decisions; files
>    touched; commands and results; errors; open items), the shape Cline, Codex and Gemini converged on.
>    ADR 0035 decision 1's layer list gains `compaction`; no new ADR.
> 6. The estimate ratio is an observed limit of the model. The first request of a turn is scaled by the ratio
>    the last turn on that model measured, recorded beside `contextWindow`/`maxTokens` in
>    `provider-models.json` (declared > observed > unknown, model-profiles 9; `estimateRatio` has no
>    declared form). Measured after the first call, the ratio then follows requirement 46a as today. Still an
>    estimate, never folded into `TokenUsage`.
>
> **Waves (by file; Sonnet workers in parallel, one integrator):**
>
> | Wave | Cards | File contention resolved |
> | --- | --- | --- |
> | 1 | P66-1 ∥ P66-4 ∥ P66-5 | `agent-loop.spec.md`, `loop.py`, `loop_steps.py`, `loop_request.py` are P66-1's; `session-history.spec.md`, `session_compaction.py` and `agent/ports.py` are P66-4's; P66-5 edits no spec and no `src/` behaviour |
> | 2 | P66-2 ∥ P66-6 | `loop_compaction.py`, `loop_request.py` are P66-2's; `loop_budget.py`, `loop.py`, `loop_types.py`, `driver*.py`, `models/` are P66-6's; both amend `agent-loop.spec.md`: the integrator applies the two spec hunks at merge (as `FEATURES` was in Phases 63-64) |
> | 3 | P66-3, then P66-7 | P66-3 owns `session_compaction.py`, `session_units.py`, `session.py`, `loop_compaction.py`, `loop_trace.py` and both specs; P66-7 is the integrator's real run and bench |
>
> The integrator runs the default suite once per wave. `agent/loop.py` stays under 1,000 lines (657 today,
> D-78); a card that would cross it moves the helper to `loop_request.py`.

### P66-1 — The one steering line docket stores is sent with the request instead

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** —

- **Trigger:** the audit §6.6: the budget notice of requirement 108 is written into the last tool result that
  `dispatch_tool_batch` persists (`agent/loop_steps.py` ~142-160), so it lands in `session.json` and in every
  later request and summary of that session ("when it ends you will be asked for a report" read back by a
  resumed or conversation turn). The landing ask and the closing ask are already request-only
  (`_finalization_messages`, `_closing_messages`, `agent/loop_request.py` ~221-235). 0 cases live: no run
  reached a quarter left.
- **Goal (decision 1):** `budget_notice` (`agent/loop_budget.py` ~27) is unchanged; its one caller moves from
  `dispatch_tool_batch` to `_TurnState.prepare_request_or_finalize` (`agent/loop.py` ~290): when the line is
  due, the request is `[*messages, user(notice)]`, built by a `_notice_messages` helper beside
  `_finalization_messages`. The `budget_warning` event is unchanged. `load_messages` never contains the line.
  The exclusions of requirement 108 (a batch that ends the turn) become "a request that is the landing or
  the closing call carries no notice".
- **Non-goals:** the notice's text or its 25 % rule; adding the objective to it; the fit loop (P66-2).
- **Change:** `agent/loop.py`, `agent/loop_steps.py`, `agent/loop_request.py`; tests
  `tests/unit/agent/test_loop_steps.py` (`TestDispatchToolBatch` ~63), `tests/unit/agent/test_loop_budget.py`,
  `tests/integration/agent/loop/test_terminal_reservation.py` (the requirement 108 test is rewritten, not kept
  beside the new one). Spec: `agent-loop.spec.md` requirement 108 (:940), version bump.
- **Acceptance (RED first):**
  - Integration: with `max_iterations=8`, the round-7 request carries the notice as its last `user` message
    (the quarter is reached after round 6's batch), the round-8 request does not, and no stored message
    contains `[docket] This step's budget`. Oracle: today the line is in round 6's last stored tool result.
  - Unit: `dispatch_tool_batch` persists the tool results byte-identical to what `dispatch_tool` returned.
  - Unit: a landing request built while the notice is due carries the landing ask only.
- **Gate:** the three test files (under 10 s); `tests/architecture` (3 s); `bash scripts/validate-specs.sh`;
  `scripts/maint/comment_lint.py --check` on touched files.

### P66-2 — A request that does not fit is reduced by what the request carries, not by what the record holds

**Status:** TODO (after P66-1) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P66-1 (both edit `agent/loop_request.py`)

- **Trigger:** measured (c): `reduce_for_fit` (`agent/loop_compaction.py` ~347) computes
  `overflow` on the projected request and `target = selected_tokens - overflow - 32` on
  `_selected_estimate(selected)` (`agent/loop_request.py` ~146), the raw durable range; a range of old tool
  results is 4.8x larger raw than projected, so one accepted summary removes little from the request and
  the loop pays another summarizer round per attempt, up to `attempt_cap = len(durable) + 1`. Not yet seen
  live (260 fits, 0 `context_fit`), because the only live provider has 200k; the local endpoint has 32k.
- **Goal (decision 2):**
  - `reduce_for_fit` projects the durable history once (`condense_history`, the same `budget` as
    `messages_for_durable`), groups both lists by `group_atomic_units` (same indices), and for each
    candidate range (suffix after the task, then prefix; `_build_reduction_candidates` unchanged) selects
    the oldest units whose projected estimate sums to at least `overflow + 32`; it calls
    `run_compaction(budget_tokens=0, compact_range=<that sub-range>, keep_latest_unit=False)`.
  - `compact_session` documents `budget_tokens=0` on a range as "summarize the range whole"
    (`plan_compaction` with `keep_latest_unit=False` already yields that; `_validate_compaction_range`
    keeps the anchor rule). `_selected_estimate` is deleted with its last caller.
  - The protected-segment bookkeeping (`protected_segments`) and the attempt cap stay as they are.
- **Non-goals:** a free reduction before the summarizer (the projection already is one); changing the
  pre-turn compaction; the summarizer prompt (P66-4).
- **Change:** `agent/loop_compaction.py` (`reduce_for_fit`, `messages_for_durable`), `agent/loop_request.py`
  (`_selected_estimate` deleted; a `projected_units` helper may live here); tests
  `tests/integration/agent/loop/test_compaction.py` (`TestLiveSessionCompaction` ~39: the growth test ~40
  and the irreducible test ~109), `tests/unit/agent/test_loop_compaction.py`. Spec: `agent-loop.spec.md`
  requirement 47 (:419: "with a smaller target" becomes "the oldest units whose projected size covers the
  overflow, summarized whole"); `session-history.spec.md` requirement 28 (`budget_tokens=0`).
- **Acceptance (RED first):**
  - Integration, the audit's shape: a 8,000-token window, a durable history of 12 tool units of about
    9.6k characters each after the task, a fake backend that counts summarizer calls and returns a
    120-character summary. Today: more than one summarizer call before the task request is sent (assert
    the count the RED run records, then the new bound). After: exactly one summarizer call, then the task
    request, whose `request_fit` is `fits`. Oracle: the count of `llm_call` events with
    `purpose: "compaction"` before the first task `llm_call`.
  - Integration: the irreducible case still fails before transport with `context_fit` and no backend call
    (the existing test, unchanged in outcome).
  - Unit: `plan_compaction(range, 0, keep_latest_unit=False)` summarizes every unit of the range.
- **Gate:** the two test files (under 10 s); `tests/architecture`; `validate-specs.sh`; the replay bench
  on the fixtures unchanged in its figures (`scripts/maint/context_replay.py tests/fixtures/context-replay
  --json`, "no step worse than the recorded request", P52-2's oracle).

### P66-3 — A compaction leaves a record, its summary reads the same on every wire, and the request says what it condensed

**Status:** TODO (after P66-2, P66-4) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P66-2 (both edit `loop_compaction.py`), P66-4 (the prompt it records the hash of)

- **Trigger:** the audit §6.13 and §6.5: `_plan_and_apply_compaction` (`agent/session_compaction.py` ~298)
  replaces the summarized messages in `session.json`, `platform/store.py` keeps one `.bak`, and
  `_trace_compaction` (`agent/loop_trace.py` ~262) records counts; after two compactions the original is
  nowhere. The summary is a `system` message (`~252`); `anthropic_wire.build_payload` (:118-124) lifts every
  `system` into the `system` parameter and marks the last one for cache, so a mid-history summary leaves
  chronology and takes the breakpoint. The request projection (`condense_history`) is invisible in the
  trace (§6.8).
- **Goal (decisions 3, 4 and the projection):**
  - Inside the locked mutation, before the history payload is returned, a record
    `{sessionKey, at, range: [start, end], replaced: [messages], summary, promptSha256}` is written with
    `platform/store.py::write_json` to `<session dir>/compactions/<seq>.json` (`seq` = count of existing
    records + 1; `_session_dir` in `agent/session.py` ~145 gives the directory; 0o700/0o600 like
    `session.json`). `CompactionResult` carries `record` (the relative path) and `summarized_range`;
    `session_compaction` carries `record`, `summarizedRange` and `promptSha256`, never the text.
  - The summary message is `role="user"`, prefixed as today. `_is_compacted_summary_unit` (~89) and the
    head rule of `plan_compaction` (`agent/session_units.py` ~129-135) read the prefix on a `user`
    message; the three spec requirements say "the summary message".
  - `messages_for_durable` (`agent/loop_compaction.py` ~255) returns the projection and its figures
    (`condensedResults`, `keptWholeResults`, `budgetChars`); `_trace_llm_call` (~96) puts them under
    `projection` on every task `llm_call`.
- **Non-goals:** reading records back (an operator reads the JSON); pruning records (they go with the
  session directory); re-labelling old `system` summaries.
- **Change:** `agent/session_compaction.py`, `agent/session_units.py`, `agent/session.py`,
  `agent/loop_compaction.py`, `agent/loop_trace.py`; tests `tests/unit/agent/test_session_compaction.py`,
  `tests/unit/agent/test_session_units.py`, `tests/integration/agent/loop/test_compaction_budget.py`
  (`test_no_op_uses_one_backend_call_and_emits_bounded_trace` ~351,
  `test_old_results_become_notices_and_the_record_keeps_every_byte` ~577), captured-payload tests of both
  wires for a mid-history summary (`tests/unit/models/adapters/`). Specs: `session-history.spec.md`
  (storage layout: the `compactions/` directory, a new requirement under "Fail-closed summarisation";
  11, 13, 25 reworded; the duplicate requirement 9 at :75 renumbered `9a`; "Implementation" (:395) names
  `session_units.py` and `session_compaction.py`), `agent-loop.spec.md` 37 (:352: the record and range
  keys) and 71 (:630: `projection`); `trace-store.spec.md` needs no change (no new event type).
- **Acceptance (RED first):**
  - Unit: after a successful `compact_session`, `compactions/1.json` exists, its `replaced` equals the
    messages `load_messages` no longer returns, byte for byte, and `[*replaced, *kept]` reproduces the
    pre-compaction history; a failed summary writes no record. Oracle: today the directory does not exist.
  - Unit: the stored summary has `role == "user"`; the Anthropic payload of a history
    `[system prompt, summary, user task]` has one `system` block (the prompt) and the summary as the first
    `user` block, in order; the OpenAI payload has it as a `user` message. Oracle: today it is in
    `system[]` / a mid-history `system` message.
  - Integration: `session_compaction` carries `record`, `summarizedRange`, `promptSha256`; the first
    task `llm_call` of a turn whose history condensed two results carries `projection.condensedResults == 2`.
- **Gate:** the five test files (under 15 s); `tests/architecture`; `validate-specs.sh`; `tests/e2e -n
  auto` (42 s: the wire shape of a summary changed).

### P66-4 — The compaction prompt is a shipped prompt document with sections, reached through the port

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + data · **After:** —

- **Trigger:** the audit §6.3: `_summarization_message` (`agent/session_compaction.py` ~38) is a fixed
  string asking for "a concise summary"; no plantilla, no scope override, no hash on the trace, no recall
  test. ADR 0035 made every other prompt a versioned document; this one was left in code.
- **Goal (decision 5):**
  - `src/docket/templates/prompts/compaction/history.md`: `kind: prompt`, `name: history`, `version:
    1.0.0`, `layer: compaction`, `for: any`, `modelClass: any`, `inputs: {label, turns}`; the body states
    the role of the summary (the only memory the next request has of these turns), then the sections it
    must fill in order, each one line when empty: objective and current state; decisions taken and why;
    files touched (path: what changed); commands run and their result; errors seen and whether resolved;
    open items and the next step. It ends "Reply with the sections only." `${turns}` is the rendered units
    (today's `_render_unit`), `${label}` the session label.
  - `Layer` (`teams/prompts.py` :32) and `prompt.schema.json` (:35) gain `compaction`; `config-format.spec.md`
    (:89, :202, :221, :279) and `role-archetypes.spec.md` (:75) name it where they enumerate layers;
    `floor` keeps refusing it (a role has no compaction floor). ADR 0035 decision 1's line :94 is amended.
  - `RoleComposer` (`agent/ports.py` ~399) gains `compaction_prompt(role, project) -> (text, sha256)`;
    `TeamsRoleComposer` (`teams/role_composer.py`) answers with `resolve_prompt("compaction", "history",
    project=project)` so a repository, pod or operator overrides it by scope. `compact_session` takes the
    prompt text and hash from its caller (`TurnCompaction.run_compaction`), substitutes the two inputs
    and reports the hash on `CompactionResult` (P66-3 puts it on the trace).
- **Non-goals:** a per-role prompt (scopes already allow one; none ships); a verification pass over the
  summary (Gemini's probe turn) until a recall figure says it is needed.
- **Change:** the template file, `teams/prompts.py`, `templates/schemas/prompt.schema.json`,
  `agent/ports.py`, `teams/role_composer.py`, `agent/session_compaction.py`, `agent/loop_compaction.py`
  (`run_compaction` passes the prompt); tests `tests/unit/teams/test_prompts.py`,
  `tests/unit/agent/test_session_compaction.py`, `tests/unit/agent/test_loop_compaction.py`
  (`TestSummarizeWithoutReentry` ~62), the package test that lists shipped templates
  (`tests/agent/release/test_distribution_package.py`, run by the integrator). Specs: `session-history.spec.md`
  17 and 23 (the prompt is the resolved document; the input budget bounds the substituted text),
  `config-format.spec.md`, `role-archetypes.spec.md`; ADR 0035 :94.
- **Acceptance (RED first):**
  - Unit: `shipped_prompt("compaction", "history")` loads, declares the two inputs, and a body with the six
    section headings; `resolve_prompt` with a pod overlay `prompts/compaction/history.md` returns the
    overlay's text and hash. Oracle: today `layer: compaction` is a load error.
  - Unit: the summarizer prompt `compact_session` sends starts with the document's body and carries the
    rendered units where `${turns}` was; a repository prompt is read from the base commit view, never the
    worktree (the existing `RepoView` rule).
  - Agent lane (`tests/agent/context/test_compaction_recall.py`, `LANE = "context"`, `REASON`: the summary's
    recall is a model behaviour no unit test can read; `RETIRE_WHEN`: a recall figure is published per
    model and tracked by the bench): on the local endpoint, a seeded history with four facts (a decision, a
    failing command and its fix, a file edited, an open item) is compacted; the summary names all four.
    Runs at phase close only.
- **Gate:** the four unit files (under 10 s); `tests/architecture`; `validate-specs.sh`;
  `scripts/maint/comment_lint.py --check`.

### P66-5 — Prose that says what the code no longer does

**Status:** TODO · **Size:** S · **Model:** Haiku · **Kind:** docs · **After:** —

- **Trigger:** the audit §6.12, verified with `rg`: `agent/context.py`'s docstrings say the drop order is
  `diff_ref -> files_changed -> verdict` (`kernel/handoff.py` :231 starts at `diff` and includes
  `assumptions`, `questions`) and that "today's only registered window" is 16384 tokens (the live home
  registers 32768 and Anthropic rows); `.agents/skills/docket-context-runtime/references/live-path.md`
  says MCP output "reads `current_home().tool_max_output_chars` per call" (the live reader is
  `artifact_scope(ctx.project, output_chars=ctx.output_cap, ...)` in `dispatch_tool`,
  `agent/tools/registry.py` :329, for every tool).
- **Goal:** the three statements say what the code does, with the symbol they describe. Nothing else in
  those files changes. The gitignored `CLAUDE.md` note that `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` is required
  against the local endpoint is the maintainer's to re-check after P66-7 (the `local` profile derives 2,621
  from the 32k window today).
- **Non-goals:** the spec's "Implementation" section and duplicate requirement 9 (P66-3 owns that file).
- **Change:** `src/docket/agent/context.py` (docstrings and the `WINDOW_SHARE` comment only),
  `.agents/skills/docket-context-runtime/references/live-path.md`.
- **Acceptance:** `rg -n "diff_ref -> files_changed|16384" src/docket/agent/context.py` is empty;
  `rg -n "tool_max_output_chars.*per call" .agents/skills` is empty; `pytest --co -q` unchanged.
- **Gate:** `uv run ruff check src/docket/agent/context.py`; `scripts/maint/comment_lint.py --check
  src/docket/agent/context.py`.

### P66-6 — The first request of a turn is estimated with the ratio the model showed last time

**Status:** TODO (after P66-1) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P66-1 (both edit `agent/loop.py`)

- **Trigger:** measured (b): first request of a hop 1.55x (median, n=75, p90 1.64, max 1.69, none under
  1.0), later requests 1.00x (median, n=173), live traces 2026-10-24 to 2026-11-04, Anthropic dialect.
  `TurnBudget.calibration` starts at 1.0 (`agent/loop_budget.py` ~60) and `calibrate` (~98) runs after the
  first measured call; the request that carries the whole history is the one checked with the wrong
  figure, against the window (46a) and the token budget (prospective check). On a 32k endpoint with a
  dense history that is an HTTP 400 the pre-flight exists to prevent.
- **Goal (decision 6):**
  - `provider-models.json` (`Home.provider_models_file`, `kernel/home.py` :480) gains, per model,
    `estimateRatio: <float>` and `estimateRatioAt: "YYYY-MM-DD"`, written by one new function beside
    `record_observed_models` (`models/provider_lifecycle.py` :29), `record_observed_estimate_ratio(provider,
    model_id, ratio)`, through `platform/store.py`. `ModelLimits`/`observed_limits` (`models/catalog.py`
    ~516, :542) read it; `resolve_limits` (:564) resolves it observed > unknown (no declared form);
    `Endpoint` (`agent/ports.py` ~651) carries `estimate_ratio: float | None`; the OpenAI and Anthropic
    clients expose it like `context_window_tokens`.
  - `_resolve_context_bounds` (`agent/loop.py` ~150) reads the backend's `estimate_ratio`;
    `TurnBudget.__init__` seeds `calibration = max(1.0, ratio)`; `calibrate` is unchanged after the first
    measured call. `AgentLoopResult` (`agent/loop_types.py`) carries `first_call_ratio: float | None`
    (measured input / raw estimate of the first task call); `DocketDriver.run_turn`
    (`hops/application/driver.py` ~255) records it for the turn's provider/model when it is positive.
  - `docket status` / the provider render that shows `observedAt` shows the ratio with its date
    (`model-profiles.spec.md` :353-354 names that render).
- **Non-goals:** a tokenizer; `count_tokens`; changing `CONTEXT_BYTES_PER_TOKEN`; a ratio per role.
- **Change:** `models/catalog.py`, `models/provider_lifecycle.py`, `models/adapters/openai_http.py`
  (property), `agent/ports.py`, `agent/loop.py`, `agent/loop_budget.py`, `agent/loop_types.py`,
  `hops/application/driver.py`; tests `tests/unit/agent/test_loop_budget.py`,
  `tests/unit/models/test_catalog.py`, `tests/unit/models/test_provider_lifecycle.py`,
  `tests/integration/agent/test_runtime_driver.py`. Specs: `agent-loop.spec.md` 46a (:412) and 44 (:388,
  the seed is an observed limit), `model-profiles.spec.md` 9 (:371) and the render line (:353);
  `docs/CONFIGURATION.md` where `provider-models.json` is described.
- **Acceptance (RED first):**
  - Unit: with `estimate_ratio=1.5` on the backend, the first `request_fit` of a turn reports
    `estimatedInputTokens == ceil(raw * 1.5)`; with `None`, `raw`. Oracle: today the first figure is `raw`
    whatever the model.
  - Integration: a turn whose first call measures 1.6x its raw estimate ends with `first_call_ratio ==
    1.6` and `provider-models.json` holds `estimateRatio: 1.6` for that model; a second turn on the same
    model starts calibrated at 1.6. A turn that made no call records nothing.
  - Unit: `resolve_limits` reports the ratio `observed` with its date, `unknown` when absent.
- **Gate:** the four test files (under 15 s); `tests/architecture`; `validate-specs.sh`; `tests/e2e -n
  auto` (42 s: the home layout gained two keys in a state file).

### P66-7 — The real run: the local endpoint, the fit path and the bench, before and after

**Status:** TODO (after P66-1..P66-6) · **Size:** M · **Model:** Opus (integrator) · **Kind:** verification · **After:** P66-1..P66-6 merged

- **Trigger:** the phase-close rule ("a real run") and measured (c), whose consequence is inferred.
- **Goal:** on this machine's llama.cpp endpoint (32k, `local` profile, `DOCKET_TOOL_MAX_OUTPUT_CHARS`
  unset to prove the profile's cap), one `app-dev` task whose Implementer history is made to overflow (a
  `read` of a large file, three times): the trace shows at most one `purpose: "compaction"` call before
  each task call, every `request_fit` `fits`, `session_compaction` with `record` and `summarizedRange`, the
  record reproduces the history, the first `request_fit` of the second turn on that model scaled by the
  recorded ratio, and no stored `[docket]` line. Then `scripts/maint/context_replay.py
  tests/fixtures/context-replay --json` and `--repeats` before (at `2462c872`) and after: no step sends
  more, prefix stability not worse. The figures go to `internal-docs/baselines/phase-66/` and one line each
  to the phase's ROADMAP row; the gitignored `CLAUDE.md` note on `DOCKET_TOOL_MAX_OUTPUT_CHARS` is rewritten
  to what the run showed.
- **Non-goals:** a hosted-model run (spends tokens; the maintainer's call, §7.1).
- **Acceptance:** the trace assertions above, read with `docket task trace`; the bench's two JSON files;
  the phase-close gates of `CLAUDE.md` "Testing budget" (goldens, agent lane incl. P66-4's recall test,
  `pytest-without-sandbox.sh`, escape matrix, `validate-specs.sh`, `gen_cli_docs.py --check`,
  `split_board.py check`).
- **Gate:** the phase-close list; the full suite once at the last merge.


## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Phases 63-64 (2026-11-04).** Left out of the cards on purpose, or found while merging:
- *`POST /pods/<p>/apply` over HTTP writes a `pod.apply` audit entry even when it skips everything*; the CLI
  writes none (P63-4's exception to requirement 6). Trigger: an audit reader that counts applies.
- *The policy-pack recipes (`outward`, `ops-approval`, `records`, `hacker-news`) declare no `shape`.* Trigger:
  a plan of record that needs their shape before it applies one.
- *The imperative-verb defence is gone* (P64-3 deleted `_IMPERATIVE_FIRST_WORDS`): a `generated` note such as
  "Run make proto..." is accepted when the path exists and renders under the untrusted frame. Trigger: a live
  note that tries to steer the next task.
- *A `generated` check proves a path exists, not that the note is true* (a live note said "top5.md is not
  present" and was accepted). Trigger: an operator reads a wrong accepted note.
- *`_still_there` in `teams/memory.py` repeats the P64-3 verifier's path logic*, and `render_entries` also hides
  a `generated` entry whose path is missing under the first project root. The stale re-check runs on every
  finished task that has an accepted `generated` entry. Trigger: a third place needs the same check.
- *`docket run`'s header and `docket setup` show the lifetime token count*, which differs from
  `budget.used` for a windowed pod; seven tests stub `pod_counted_tokens` as `lambda _p: 5` instead of taking
  `since`. A pipeline with a missing role and an out-of-pod agent reports only the roles.
- *Stale `memory/` mentions* in `specs/api/cli-interface.spec.md`, `specs/acceptance/user-stories.md`,
  `specs/functional/agent-lifecycle.spec.md` and `specs/test-framework.md`; `docs/recipes.md` does not mention
  `shape`; the word "adapters" in the `_execution.py` docstring and ADR 0006.
- *The `web-research` pod's settings fix (2026-11-04).* A pod with a `researcher` records `fetch-hosts` and says it
  cannot read the web, but no role holds `fetch` until a person names hosts; that is the decision, not a gap.
- *The live home's old memory is invisible to the new build* (entries of kind `command` are dropped at the
  first write, as D-86 said); the installed `hn-live` entries are the two tasks of 2026-11-04.

**Phases 60-62 (2026-11-03).** Left out of the cards on purpose, or found while merging:
- *`NOT_ENFORCED` wording.* "isolation off" is also what a machine with isolation on and no backend prints
  (`teams/network_posture.py`); changing it moves a golden and security-gates requirement 14. `pod_summary`
  probes the backend per row. Trigger: an operator misreads the line, or a pod list slower than 50 ms.
- *The fetch refusal for a host off the pod's list does not name the pod command.* `platform/fetch.py` ~279 says
  "add it to FETCH_ALLOWED_DOMAINS, or to the pod's fetchDomains"; P61-3's card wanted the exact `docket pod set`
  command. `platform` does not know the pod. Trigger: a hop that stops on this refusal and a person asks how.
- *`capability_missing` for a tool is "a name the role could hold".* P61-3 chose that over "a tool another member
  holds" so a deliberate `deniedTools` is not a gap. A Reviewer calling a record write it may not use now fails
  the task `capability_missing` (`tests/e2e/test_workdir_pod.py` follows).
- *PDF reading, after P62-1.* `setup check` has no line for the PDF reader (whether isolation is on is the
  only fact it needs; the recipe readiness block already says it); an encrypted PDF is refused (only the empty
  password is tried and AES needs `cryptography`); `pypdf` decodes about 30 MB/s, so a real stream bomb ends by the
  1 GiB memory limit or the deadline after ~30 s of CPU. The jail runs a copy of `pdf_extract.py` beside `in.pdf`
  because `-m docket...` fails when docket is editable. Trigger: a PDF a user needs that these refuse.
- *`pod export` drops a recipe's `needs`* (`teams/apply/write.py` ~191, the manifest built there), by design: `needs` is
  a recipe declaration, not pod state. The "search service" check is a heuristic (a declared service whose name or an
  operation name contains "search"), and the known search hosts are a constant in `teams/apply/needs.py`. Trigger: a
  recipe that needs a fact these do not cover, or a search host that is not on the list.
- *Streaming with an idle timeout.* A stall is only seen after `AGENT_LOOP_REQUEST_TIMEOUT_S`
  because a non-streamed reply sends nothing until it ends. Trigger: after P60-1, more than one
  `request_retry` per 50 requests over a week of the live home, or a turn that ends `timeout` after
  its retries.
- *A cache breakpoint at the condensed boundary.* Replayed: with P60-2's sizes, a miss would re-send
  69 % of what it re-sends without one. Trigger: after P60-2, `messages_changed` on more than 20 % of
  a real task's requests.
- *A missing workdir folder.* Not seen: `web-research`'s exists, and Tack's `workdir: null` was the
  absent field (P61-1). Trigger: a dispatch whose recorded `workDir` is gone; then the docket-owned
  default is recreated, and a declared location becomes a profile violation and a `POST /tasks` 422.
- *A network failure inside `bash`.* No deterministic signal; P61-5 states the posture. Trigger: a
  recorded hop that tried the network after its message said `none`.
- *Approvals for shell idioms.* 7 of the live home's 9 failed hops (2026-10-24..11-03, mostly before
  Phase 59) parked on `$(`, `${` or a redirect to `/tmp`. Trigger: a week after Phase 59 in which
  approvals park more than one Implementer hop in five.

**Phase 63 (planned 2026-11-03).**
- *The A2A agent card says only "Runs tasks in the X pod"* (`interfaces/http/routes/a2a.py` ~263). Trigger:
  P63-2 lands; then the card's skill reads the pod's `description`, `blueprint` and `delivers` from `pod_report`.
  One line, not a card.

**Toolchain read grants (dropped from Phase 48).** A sibling project's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Phase 55 Wave 1 (merged 2026-10-30).** Loose ends, none a card yet; the first two belong to the later cards
that already own the files.
- *Specs that lag.* `trace-store.spec.md` items 30-32 say every `process_*` payload carries `pgid`; MCP events carry
  none. `audit.spec.md` (~line 77) omits `pod.network_widen` / `pod.network_narrow`. P55-12 or the next card that
  edits either spec.
- *Required variables supplied by tasks.* `dispatch_pod`'s up-front check refuses a `required` pipeline variable that
  only tasks supply. P55-9 (routines) meets it first.
- *Smaller.* `docket task cancel` does not kill a `hop` MCP session directly (it closes at hop end); a top-level
  `networkGrant` in `pod.yaml` is an unknown-key error, not a skip (only under `settings`).
- *Flakes under load, seen once each and passing alone:* `test_run.py::TestForegroundApprovalPrompt` (two tests),
  `test_consult_wait.py::TestAnsweredInPlace::test_an_option_answer_goes_back_to_the_model_in_the_same_turn`,
  `test_end_to_end.py` approval-mode tests. A second failure of the same test is its trigger.
- *Phase 55 Wave 2, P55-3.* The `outward` recipe's policy `ask` names one tool, `mcp__outbox__send`
  (`when.tool` matches an exact name), so a send tool of another name is not asked about: a kind predicate or a default
  `ask` for every `send` tool belongs with P55-4. `--kind` stays an operator assertion, not verified against the server.
  A pipeline step that runs a role from the pod's existing registry (not in the applied directory) is not checked by
  the read/act rule.
- *Phase 55 Wave 2, P55-6.* `docket task show` "Waiting on you", the foreground `run` progress view and Telegram
  `/status` do not special-case a `wait`. `serve-read-api.spec.md` (the `kind` label list) and `a2a-binding.spec.md`
  (`escalationKind`) still list five kinds. `docket_escalations_total` counts a probe-resolved wait as `by=person`. A
  `stale_claim` between wake and claim drops the wait, so the next claim parks the step again. A monitor-only `docket
  start` never runs a probe (only a dispatching sweep does). Tack's maintainer is told: `wait` is an additive
  `EscalationKind`, `machine` an additive `EscalationPolicy`, the task is `waiting_input` with a2a state `WORKING`, a
  timed-out wait with no route is `blocked` / `wait_expired`, and `POST /escalations/<id>` `{optionId: "resume"}` ends
  it early. The e2e lane took 344 s once on this host against about 42 s measured before; its slowest tests are 13 s,
  so it was host load, not a test; re-measure if it repeats.
- *Phase 55 Wave 3.*
  - P55-2: the refusal golden is not added. `tests/golden/run.sh` derives the command from the case id and
    `setup model set` validates the model id (it contains `/`) before the role; a CLI unit test in
    `tests/unit/interfaces/cli/commands/test_setup_model.py` plus checking the role first would fix both. The refusal
    hint and `setup model list` name only the ten built-in roles; `known_role_names()` reads every overlay per call.
  - P55-4: `task show --json` carries no `call` (deliberate). The `Authorization` redaction pattern needs a token of
    about 20 characters after "Bearer". `outward` and `call` are additive to `operator-v2`; tell Tack's maintainer.
  - P55-9: `docs/CONFIGURATION.md` and `kernel/layout.py` do not list `docket-routines.json`;
    `pod-blueprints.spec.md` omits `routines/` from the `pod update` list; the recipe summary line does not name
    routines; cron day-of-month and day-of-week are ANDed, as in the existing parser; `tzdata` is not a declared
    dependency; no `--tz`-aware `HH:MM` form. A routine fires only under `docket start --dispatch`.
    A routine skip is traced as `step_skipped` because `EVENT_TYPES` is closed.
- *Phase 55 Wave 4.*
  - P55-10, a gap in the flow: nothing user-facing stores a secret under an arbitrary name such as `crm` (provider add
    and notify write only their own names; `setup_notify.store_secret` is the one writer), so a `secret:crm` reference
    needs `secrets.json` or the keyring edited by hand. Recommended: a `docket setup secret set <name>` command that
    reads the value from stdin or a prompt and never echoes it; needs the maintainer's go as a card. Sessions and the
    model's own reply carry raw tool output (the model sees it); not checked. `setup --fix` (not bare `setup`) carries
    the literal-credential warning; there is no CLI golden for `--secret` (run.sh replays readonly cases only).
  - P55-8: the check and the increment of a quota are not atomic (two concurrent sends in one pod could both pass at
    count-1); an unreadable counter counts as empty; `pod policies` and `check` do not show quotas.
  - A flake, once: `test_consult_wait.py::TestAnsweredInPlace::test_an_answer_by_the_task_goes_through_the_same_record`
    failed in the full run and passed alone (the file's other test is already on the list above).
  - Phase 56 Wave 2 merge run (2026-10-30), both passed alone: `test_consult_wait.py::TestAnsweredInPlace::
    test_a_decline_tells_the_model_to_decide_itself` (a third test of that class, so the class now has three flakes
    under load: that is its trigger), and `tests/integration/product/test_runtime_execution_envelope.py`, 8 setup
    errors from `uv build` exiting 2 in a parallel worker.
- *Declarative external services (became Phase 56, closed 2026-10-30).* The maintainer wants a pod to reach
  an external service from a `kind: service` document or commands (base URL, auth from the secret store, operations as
  read/send tools through `dispatch_tool`), with no program written per service and no more MCP implementation work. It
  reverses ADR 0036's "no native HTTP tool": written as decision 13 in the amendment of
  [ADR 0036](docs/adr/0036-a-pod-works-outward.md) (proposed 2026-10-30, not accepted; no new ADR). Sketch and open
  questions in `internal-docs/design/site-credentials-for-a-pod.md` (Addendum). Scope accepted 2026-10-30: Phase 56.
- *To investigate, important: a pod logging in to a site nobody configured.* Per-service MCP bridges and `secret:<name>`
  are fixed when a server is registered; a task that ends in a `send` at a new site that needs a login has no per-site
  credential the model never sees. Raised by the maintainer 2026-10-30. Analysis, seven open questions and a suggested
  path (ADR first, then `docket setup secret set`, then a per-site grant like the network grant, then a real run with a
  throwaway account) are in `internal-docs/design/site-credentials-for-a-pod.md`. No card yet.
- *Phase 59 merges and real runs (2026-11-03).* Seen while merging or in the six real runs.
  - The `bash` clamp is `max(1, int(deadline - now))`, so a hop clock of 2 s ends a clamped command at 1 s and
    the clock is not yet spent (`agent/loop_steps.py`). Round it up when a `time` stop is seen to need a
    second request.
  - Only an Implementer hop that ended `budget_exhausted` is pinned (ADR 0038 decision 2 reads wider). Trigger:
    a plan of record that needs the tree of another failed Implementer hop in the patch.
  - `--resume`'s lease still uses the pod's `turnTimeoutS` + `verifyTimeoutS` and ignores a step's `timeout`;
    the per-round claim refresh covers a live claim.
  - A `budget_exhausted` stop for a finalization reply that carried tool calls is a model misbehaviour with
    `stop_reason: token_budget`; it lands as a budget outcome. Trigger: one seen in a real trace.
  - A budget stop that entered its landing keeps the pre-landing reason: "cannot start tool-enabled task
    completion within token_budget=N ... no backend call made" (`agent/loop_budget.py`
    `prospective_budget_error`), though the landing call was made. It reads as a refusal with no call and
    quotes the 128000-token output reserve of a model with no registered cap. Trigger: an operator misreads
    one, or Tack shows the `reason` text.
  - The CLI cannot see why a task stopped: `docket task show` and `task list --json` print neither
    `failureKind` nor the hop's `budget`; they are in the HTTP task and `TASK_LIST.json`. Trigger: an
    operator asks for the limit that stopped a task from the terminal.
  - Tack's live run (2026-11-03) never reached a clean `time` stop: its request clock ran out first, as a
    transport timeout, while the loop was in its own landing. Unverified on docket's side (the landing's share of
    the clock, and whether a client's request timeout should exceed the step `timeout`). Trigger: a plan of record
    reports a `time` stop that arrived as a transport timeout, or a real run where the landing outlives its step
    clock.
  - A second implementation of a port can sit outside `src/` (the `docket-runtime` package's `Tracer`).
    Trigger: the next port-signature change sweeps `packages/` too (`rg` the method name there).
  - A policy `ask` on `.env.local.example` (a template, no secret) stopped the retried app-dev task. Trigger:
    the operator wants templates exempt from `block-destructive`.
- *Phase 59 planning (2026-11-02).* Left out of the phase by ADR 0038; each waits on its trigger.
  - docket continuing a budget-stopped hop on its own (ADR 0038 decision 6). Trigger: the same task
    retried after a `budget` stop with `treeChanged: true` three times in a week (audit `task.retry`
    plus the hop's `budget`).
  - A stall detector beyond identical calls (rounds that only re-read what the session already
    holds). Trigger: three Implementer `budget` stops with `treeChanged: false` in real runs.
  - The 300 s default hop clock (`AGENT_LOOP_WALL_CLOCK_TIMEOUT_S` after P59-4). Trigger: a `time` budget stop
    whose last `bash` the clamp killed (requirement 98's marker).
  - Parallel-group resume re-runs a group's ok children with their original prompt over their
    sessions (`pod-dispatch.spec.md` "Parallel step groups" item 6). Trigger: a group child re-run
    observed in a real retry.
- *Phase 58 planning (2026-11-01).* Asks from the manager audit that Tack would not read today.
  - `actor` on `POST /tasks/<pod>` and on retry. Enqueue audits no actor (`tasks/application/queue.py`
    ~237), and retry audits neither channel nor actor (`lifecycle.py` ~188). Tack sends `actor: "tack"`
    on resolve and nothing on enqueue. Trigger: Tack links an attempt to the principal that caused it
    and sends that principal.
  - `updatedAt` on a task, stamped beside `rev` in `tasks/application/json_store.py` ~40-49. Tack follows
    changes through `rev` and would show this only for work the board did not start. Trigger: a client
    that has to show when a task last moved.
  - A hop's `output` is not in the task shape of `operator-api.spec.md`. Tack uses `artifact.summary`
    as the reply of a conversation turn. Trigger: a recorded turn whose summary is too terse to serve
    as the reply.
  - Tack's audit found that `conversation.turns` (`len(hops)`, `tasks/domain/task.py` ~315) and
    `_park_turn`'s limit (`executor.py` ~338) would count a hop parked for approval as a turn. This is
    not verified by a run. It is the same trigger as "Turns taken" below.
- *Phase 58 wave 1 (2026-11-02).* Found by the workers of P58-1 to P58-3, none in a card.
  - An escalation's `seq` is issued before its record is written (`platform/store.py::write_escalation`).
    A poller reading between the two can return a later record and move `next` past the missing one.
    Trigger: a poller that reports a missed escalation, or a second writer that opens escalations
    concurrently with a poll.
  - Blocked outcomes other than the pod budget (`_block_on_missing_resources`, the `resources` block)
    carry no `failureKind`. Trigger: a client that has to tell those blocks apart.
  - `docket pod show --json` does not carry `paused`/`pausedReason` (`pod_report` feeds it;
    `cli-json-shapes.spec.md`). Trigger: an operator who reads the pause from the CLI JSON.
- *Phase 58 close (2026-11-02).* Seen once in the real run, not reproduced.
  - `POST /tasks/<pod>/<id>/cancel` sent a few milliseconds after `POST /tasks/<pod>` answered `409
    not_cancellable` ("is running; nothing to cancel"). The spec says a `running` task is cancelled by
    killing its hop's process group, so the claim had likely set `running` before any run or hop was there
    to stop. A client that cancels right after enqueueing gets a refusal for a task that then runs.
    Trigger: a second sighting, or Tack cancelling a task it just queued.
- *Phase 57 close (2026-11-01).* Loose ends of the phase, none a card yet; each waits on its trigger.
  - Park order. `_park_turn` marks the hop parked after it was persisted unparked and opens the `turn` escalation
    while the task is still `running` (`hops/application/executor.py`). A crash between leaves an unparked hop and a
    pending `turn`; replay moves past the step and the record expires unread. The reverse order would leave a
    waiting task nobody can answer, so this is the safer failure; a consult has the same window. Trigger: a
    conversation task found ended after a restart with a `turn` still pending.
  - One `current` slot. A parallel group names the child that started last and the key goes when that child ends
    (`operator-api.spec.md`). Trigger: Tack must show every running child; `current` then becomes a list under a
    new feature name.
  - "Turns taken" is read three ways: `len(hops)` in `_park_turn` and in the task dump, answered hops in the
    budget end. They agree until a final hop fails. Trigger: a `turns` count that disagrees with the hops shown.
  - Names written twice. The `reply` option id is in `answers.py` and in `escalations.py` (`_REPLY`); `tool_queue`
    and `tool_retry` in `mcp.py` repeat one queue dump; an error `code` reaches the wire as `DocketError.code` and
    as `_send_json_error(code=)`; `task_control.py` builds a `Conflict` only to render it. Trigger: the next edit of
    any of them.
  - `decide_task_tokens` is untouched: the budget end of a conversation is decided in the executor
    (`conversation_ends_on_budget`). Trigger: a second consumer of "ended after an answered turn".
  - `rev` shows in the CLI and MCP task dumps because they print the record; Tack reads it over HTTP only.
  - The live service on `:7399` runs the code from before the phase until it is restarted, and the `docket` on
    PATH until `./install.sh` runs again.
  - Flakes under load, each passing alone, seen once: `tests/guards/test_no_removed_cli_names.py` (a 2 s timing
    bound), `test_record_store_conformance.py` (two sqlite tests: the row cut, the CSV header) and
    `test_bash_background.py::TestTheTurnLeavesNoOrphan`. A second failure of the same test is its trigger.
- *Phase 56 close (the real run and the gates, 2026-10-30).*
  - Real evidence: `tests/live/test_hacker_news_live.py` (`DOCKET_RUN_LIVE_HN=1`) ran the `hacker-news` recipe against
    `hn.algolia.com` and the local model; the fourth run passed (see P56-22 in the archive). The write path of a declared
    service (park, approve, one `POST`) against a real model was **not** repeated at this close; the deterministic e2e
    (`tests/e2e/test_declared_service.py`, a scripted model) covers it. A run with the real model is the trigger for
    the first service that sends.
  - The role prompt's "end your reply with `## Memory`" line made a local model run `echo` through `bash`, and the
    gate parked the task for an approval nobody was there to give. The `hacker-news` steps say to run no command; the
    prompt in `builtin_roles.py` is unchanged (trigger: a second pod where a model does the same).
  - P56-10 left: a producer of git evidence for a non-implementer role. The `operate` and `routine` pods are workdir
    pods with no commits, so nothing would read it (trigger: a git-backed pod whose non-implementer step commits what
    a later step needs).
  - Tack's runner sends `"blueprint": "software"` in `POST /pods` and must send `build`.
  - `summarize_recipe` does not count a recipe's `services/`; `gen_recipe_docs._brings` and
    `pod_config_library._brings` are two near-duplicates. The `captured` column of `stories` holds the day a story
    was posted (the model has no clock); the row's `_at` is the capture time.
  - Prose still behind the code: the MCP client text ("workdir blueprint such as research"),
    `README.md` line 11 ("research, content or outward work"), `builtin_roles.py:68` ("forward-compat"), and
    `config-format.spec.md` (~line 115, `load_pipeline(text)`); `_blueprint_pipeline` loads a registry only to call
    `load_pipeline(None, ...)`; `conversations.load` returns an empty registry for an invalid file.
  - Records port (P56-23, merged): a second backend is one adapter module, one line in
    `bootstrap._open_records` and one `BACKENDS` entry in the conformance suite; a remote one needs the ADR
    amendment on `send` first, and S3 is an export destination, not a backend. `teams/records.py` quotes a set name
    in ANSI double quotes (each backend would quote its own); `ReadLimits` serves `read` and `export` though
    `export` honours only `timeout_s` (a possible `ExportLimits`).
  - Live Hacker News on Anthropic: the recipe ran on `claude-haiku-5-5` with Langfuse export (digest 218.9k tokens,
    weekly report 111.1k) and `tests/live` now takes `DOCKET_LIVE_HN_PROVIDER=anthropic`, but that lane was not run
    with a real key (setup only checked with a fake one). A fake key makes the run wait out its timeout instead of
    failing on the 401 at once.
  - Records and services: `pod update` does not check that a `rec__<set>` allow-list entry names a declared set;
    real PostgREST documents carry no `operationId`; `setup service list` shows secret names; the `ask-before-send` custom message is not shown
    for service sends; service results are not screened as untrusted; `pod records --csv` overwrites silently; the
    idempotency key also hashes path and query arguments; `pod-blueprints.spec.md` should list `services/`.
  - Code: `setup_model_credentials._write_credential` duplicates store logic; `config_docs.py` imports itself;
    `_read_until_deadline` is duplicated; `decided_approval` sits in `escalations.py`.
  - Flakes under load, each passes alone: the `test_consult_wait` decline test and the `uv build` in
    `test_runtime_execution_envelope`.
- *Phase 55 close (the repeated real run, 2026-10-30).* `docket run` does not wake a `wait` whose time has passed
  ("No pending tasks"); only the dispatch service's sweep does, as the spec says; a person expecting `run` to finish
  it is surprised (trigger: a second report). In one fresh home `setup provider add local ...` left the roles on
  `anthropic/*` until `setup model preset local` ran; an earlier fresh home applied the preset by itself: reproduce
  before a card. A stdio MCP server under isolation needs its script, interpreter and venv readable, and fails with
  `mcp_client.unavailable: ExceptionGroup` while python's "Permission denied" goes only to stderr (trigger: the next
  operator who meets it). P55-14 keys its note by task and role, not step, and splits the approval's `action` on
  `; call=` rather than reading a typed field; `task show --json` carries no `approval_unused`. P55-13 adds no trace
  line when the surface drops a role-named built-in (the closed event set has none that fits).
- *Live evidence, P55-5 (2026-10-30).* A real Playwright MCP server (0.0.83, headless system Chrome) driven through
  docket's MCP layer against a local page: under `lifetime: hop` navigate, snapshot and click by ref keep one session
  (the click ran, the page title changed); under `call` the snapshot after a navigate is `about:blank` and no ref
  exists. Not a model-driven pod run. That server's click argument is `target`, not `ref`.

**Phase 54 (closed 2026-10-29).** Two items wait for their triggers.
- *Dated model ids.* The native `/models` lists `claude-haiku-4-5-20251001`, and the probe matches ids
  exactly, so `claude-haiku-4-5` never gets an observed output cap and a call without a declared
  `--max-tokens` fails by design. Trigger: a second operator who meets that refusal. Next: the probe
  matches a catalog id to the dated id that starts with it.
- *Names.* `openai_http.py` and `OpenAIChatClient` hold both wires and still carry the first one's name;
  ADR 0011, ADR 0014 and two specs quote them. Trigger: a third dialect or the next edit of either module.

**Outward work (ADR 0036, deferred with triggers; the cards are Phase 55).**

- **HTTP/SSE MCP transport** (`mcp-client.spec.md:50`). Trigger: the first real pod whose connector
  exists only hosted.
- **A per-pod `fetch` allowlist** (`kernel/home.py:278`, one list for the machine). Trigger: two pods
  on one machine that need different hosts.
- **`lifetime: task` for an MCP server.** Trigger: a recorded run in which a following hop needed the
  previous hop's session.
- **A structured-output gate** (a result that must match a schema). Trigger: a recorded run whose
  critic approved a malformed list.

**Standard teams and records (deferred from Phase 56, 2026-10-30; analysis in
`internal-docs/strategy/equipos-estandar-empresa-digital-2026-10-30.es.md` §8 and
`capa-de-datos-para-docket-2026-10-30.es.md`).**

- **A pod without a Lead member.** Not a blocker, so not a card: the Lead is the pod's *anchor record*
  (its workspace holds the queue, `teams/settings.py:21-26`, the settings and budget, `:29`,
  `teams/member_workspace.py:214`; `pre_input` is evaluated and session events traced as `"lead"`,
  `tasks/application/queue.py:72`, `governance/approval.py:73`), but no pipeline step has to use it: the
  `outward` recipe's pipeline already runs researcher, writer, critic, actor. Making the pod the subject is
  a persisted-state change (the queue's and settings' location). Trigger: a measured cost of the idle Lead
  member (its workspace, its row in `status`), or a pod whose operator refuses a Lead at all.
- **Measuring the three-role full pod against the four-role one** (P56-15 ships the change on the
  maintainer's request; this is the evidence it did not wait for). Trigger: a maintainer go, since the
  comparison spends hosted-model tokens on `app-dev`: the same tasks under both rosters, measured tokens
  and escaped defects.
- **A port for docket's task store** (`TaskRepository` takes the concrete `JsonTaskStore`,
  `tasks/application/repository.py:48`). Not business data, and a port with one implementation is the
  "unwired machinery" this project refuses. Trigger: a queue the one file cannot carry (measured).

**Fired, waiting for a maintainer go (the measurement spends hosted-model tokens).**

- **The implementer sends 0.65 of what the backend counts** (Phase 45 real runs on `app-dev`,
  2026-10-20: 14 and 13 calls, largest request about 7,000 estimated tokens; reviewer 0.62, tester 0.80
  and 0.90). The Phase 44 trigger ("a real implementer run with its grants declared that still sends
  over half") fired. Next: P52-1 measures which calls repeat on the recorded traces (no live run
  needed); P53-4 (which absorbed P52-5) acts on the figure.

**Model adaptation and context (ADR 0033, deferred with triggers; the cards are Phase 52).**

- **Reasoning kept inside the turn** (`ChatMessage.reasoning`, resent only in the active tool
  loop; `reasoning_content` is dropped today in `models/adapters/openai_wire.py::decode_response`).
  Trigger: a profile that declares `reasoning: interleaved`.
- **Lifecycle condensation** (a `read` superseded by a later `read` or an `edit` of the same file
  is evicted first, in batches aligned to steps). Trigger: after P52-2 (which absorbed P52-8), the bench `--repeats`
  still shows re-reads on the recorded implementer steps.
- **A bounded model escalation** on a step (`escalate: {on: [verify_failed, no_progress], model:
  strong, max: 1}`), audited. Trigger: the `strong-plan-cheap-edit` recipe (P52-6) fails
  `verifyCmd` on a measured share of real runs.
- **A lazy MCP catalog** (`mcp_describe(server, tool)`, the tool list kept stable within a turn).
  Trigger: a pod whose MCP schemas exceed its built-in ones (`request_part_bytes["tools"]`).
- **A native Anthropic dialect** (1 h TTL, `cache_control` on tools, signed thinking blocks; the
  provider note already defers it). Trigger: direct use without the gateway, which caches today.

**Escalations (left at the Phase 51 close, 2026-10-25; ADR 0032).**

- **Approval, gate and `check_changed` follow-ups still run inside `resolve`** (`approval_grant`
  and the task-grant audit in `tasks/application/escalations.py`), not on the claim path; P51-6
  stopped at PARTIAL because deferring them breaks `approved_ready`, which reads pregrants and
  `gateOverridePipelineIndex`, and P51-9's "Also" list named the move. Trigger: a change to
  `approved_ready` or to the claim path.
- **Settled escalations written before P51-11 stay in the flat `escalations/` directory**; no
  migration is written. A scan of the live directory still opens them (`platform/store.py::list_escalations`
  reads the flat folder for `pending` and unfiltered scans). Trigger: an operator whose pre-P51-11
  records slow the inbox; then move them under `settled/` once.
- **`GET /escalations?since=` reads every settled file** (`operator/inbox.py::escalation_views`
  calls `list_escalations(since_seq=...)` with no state, so `settled/` is scanned on each poll).
  Trigger: a poller whose `settled/` directory is large; then index by `seq` or bound the scan.
- **docket follows an enclosing git repository when a pod path is not itself one**
  (`platform/git.py::git_is_repo` answers `rev-parse --git-dir`, true anywhere inside a work tree),
  so it would prepare and branch the enclosing repository. Only the live-eval and smoke worlds
  refuse that today (`specs/test-framework.md`). Trigger: a pod registered on a subdirectory or
  a nested path that is not a repo.
- **`scripts/render-doc-assets.py:275` prints a made-up approval token** (`token=apr-...`) and the
  `waiting_approval` line, shapes Phase 51 removed. Trigger: the maintainer re-captures the README
  assets (a classifier-refused step); then render the escalation id and `waiting_input`.

**Test suite under load (found at the Phase 47 close, 2026-10-24; each passes alone).**

- **Timing flakes seen once each:**
  `test_retries_and_timeouts.py::TestRetryDoesNotTripStaleClaimSweep`, and the foreground approval
  deny test (its fake approval timeout was raised from 5 s to 60 s, `1a704359`). Trigger: a second
  failure of the same test. Then replace its wall-clock wait with an event.
- **Docstring budget:** `comment_lint.py` counts 209 long definition docstrings at the close against 205
  on `develop` (most moved or renamed code). Trigger: the next card that edits one of those modules
  trims its own.
- **Two contract files set the merge run's floor** (measured 2026-10-28, `--durations=0`):
  `tests/contracts/test_a2a_http.py` 60 s and `test_escalation_http.py` 35 s of the 84 s run. Each
  test's function-scoped `parked` fixture runs a real `docket run` and starts a service (about 3 s
  of setup per test), and `--dist loadfile` keeps a file on one worker. Trigger: the merge run
  passes 120 s, or a card adds a test to either file. Then share one parked world per module for
  the read-only tests.

**Runtime and dispatch (from real runs).**

- **A refused task is resumed on every 30 s sweep tick** (`dispatch_refused` is in
  `RESUMABLE_FAILURE_KINDS`, `tasks/domain/state.py`; operator-api §6 by design). Trigger: the audit log
  fills with one task's refusals, or a second operator asks. Then resume only when the cause changed.
- **A parked turn is paid twice**: the resumed hop re-sends the whole prompt (4,157 input tokens before
  the park, 8,181 after; 100,573 in the 2026-10-18 joint run). Trigger: a third run that parks on the
  same shape. Then weigh resuming the session over re-running the hop (operator-loop §2 item 6).
- **A hop refused before any call records an empty model** (`hop_finished.model == ""`, a `""` key in
  `usage.byModel`). Trigger: a reader of `byModel` that trips on it.
- **Provider rows lag the models in use:** Anthropic advertises dated ids while the template rows use
  aliases (limits stay `unknown`), and no row prices `claude-sonnet-5-5` or `claude-opus-5-5`
  (`task show` prints `cost: -`). Trigger: a run on an alias id whose window matters, or an operator
  asking for the estimate.
- **Hop language drift:** a resumed step once wrote its report in another language, which became the
  next handoff. Trigger: a second occurrence; then a pod `language` setting.
- **The Lead plans with the codebase path while the Implementer is rooted in the task worktree**
  (`tool.refused` on `read`). Trigger: reproduce with a local-model dispatch in a worktree pod.
- **The prospective budget check ignores cache reads**, so a heavily cached step is refused early.
  Trigger: a real run refused with room left. `glob`/`grep` walk vendored trees before filtering;
  measure before changing.
- **A task's `network: none` cuts the agent turn only**; `verifyCmd` and `run:` steps keep the pod's
  posture (stated in the spec).
- **Cancel over HTTP reports `cancelled` once the stop is requested**; the task stays `running` until
  the executor notices. The slow-stub cancel path has no test.
- **Not examined:** each Phase 45 run's trace carries two `approval_denied` events beside its park.
- **Real-Docker tests exceed their duration ceiling under load** (`test_network_lockdown`,
  `test_sandboxed_exec`, the escape matrix's docker cases): they pass alone. A flake, measured
  2026-10-14.

**Workspace and checks.**

- **`docket setup` without `--fix` writes:** its report re-seeds `WORKFLOW_AUTO.md`
  (`interfaces/cli/commands/setup_check.py`). A check that writes is a defect. Trigger: the next edit
  of that file.
- **A file a check reaches only through `make` or `npm run` is protected only through the default
  files it reads**, and **a gitignored file is invisible to the check**. Trigger: a real gate whose
  script lives behind a target, or a repository that ignores a file its gate reads.
- **Prepare:** only `node_modules` is cached (`.venv` is not relocatable); `node_modules/.cache` is
  read-only in the jail; eviction can break a running task's link (resume prepares again); prepare is
  not cancellable (bounded by `PREPARE_TIMEOUT_S`); `hops/workspace/prepare.py::linked_entries` accepts
  any cache entry, not only the task's codebase. Trigger: a real run that hits one of them.
- **Shell keywords are classified as binaries when unjailed** (`for`, `do`, `done`, `if`, `then`,
  `while` ask in `governance/security`). Trigger: an operator without isolation reports it.

**Configuration.**

- **A tool deny per team member** (a read-only researcher): `tool_profile` is prose, the only denial is
  the pod-wide `deniedTools`. Trigger: a recipe or pod that needs one member without write tools.
- **Delete the old-layout reader** (`kernel/layout.py::is_legacy` and the legacy branches of `Home`).
  Trigger: the next minor release. First move what still seeds or reads an old-layout home:
  `tests/support/home.py` and `pods.py`, and the old paths named in `scripts/gen_cli_docs.py`,
  `scripts/render-doc-assets.py` and `docs/commands.md`.
- **Parallel tasks in a pod:** ADR 0027 point 10 holds the trigger; a card would add a
  `maxParallelTasks` pod setting and a bounded pool in dispatch.
- **A team's skills:** `hops/workspace/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope.

**Channels, inbox and the HTTP API.**

- **`docket start`'s periodic notify flush ignores `FlushReport.error`** (`interfaces/http/server.py:200`).
- **Enabling the `email` channel checks nothing**; with no `to`, `from` or `smtpHost`, every delivery
  fails into the health record. Trigger: an operator enables it.
- **Pending memory entries show in `docket inbox` but not in `GET /inbox`, MCP `inbox`, notifications or
  Telegram `/status`.** Needs an operator-v1 inbox contract bump. Interim: `GET /pods/<p>/memory?status=pending`
  (P63-6). Trigger for an HTTP approve route: Tack asks for one.
- **The corrections cursor needs `+` percent-encoded in `since`**; a pod whose Lead was removed but
  whose ledger remains answers `404`.

**Prompts and pod state.**

- `hops/application/compose.py::_resolve_hop_instructions` still opens "You are the Implementer..."
  (SOUL says it); recipe roles using `${codebaseOrConfigured}` render a path; `repo_map.SKIPPED_DIRS`
  mirrors `toolbox.SKIPPED_DIRS` (pinned by an equality test); pod read routes do not carry
  `tokenBudget`; the condensation notice carries the call's full path.
- **Every member of a pod shares the base session key `agent:<pod>:<key>`** (`teams/pod.py`); no turn
  reads it today. Trigger: a turn that does.
- **Three readers of the implementer's codebase** (`rg -n "def _pod_codebase|def _codebase|def
  task_diff" src`); one helper when next touched.
- **`memory_update` has no structural telemetry key**; members stamped `POD_TEMPLATE_VERSION` 4 show stale
  to `pod update` by text comparison; `scripts/smoke_workflow.py`'s memory scenario needs a live run.

**Phases 52 and 53 (closed 2026-10-29).** Triaged the same day: the brief redaction, the prompt `tests` file, a role's
unknown tool name, `pod test`'s handoff spec, the live-run key lookup and the stale docs were fixed; what stays waits
for its trigger.

- **P52-12, a wait on a machine is an escalation.** Absorbed by P55-6 (ADR 0036 decision 5): a `wait` step is
  an escalation of kind `wait` the sweep settles on time or on a probe; the wait on a machine is one case of it.
- **P53-4 goal 3, the Lead's locators read into the Implementer's message.** Measured on three recorded smoke tasks
  (two local Qwen, one Haiku, `context_replay.py --repeats`): the Implementer read 1/1, 1/1 and 2/4 files the Lead had
  read, but all except one were files it then edited, whose exact text `edit` needs; "not edited after" was 0, 0 and
  1 file (682 bytes). Trigger: "not edited after" reaching 30 % of the Implementer's reads on recorded tasks of a real
  pod (the smoke repository has three files).
- **The model class comes only from the rank anchors** (`economy` is `cheap`, `standard` and `premium` are `strong`),
  so a non-anchor model such as the local Qwen resolves `any` and no `<name>.<class>.md` variant acts for it. No
  shipped prompt has a variant. Trigger: a variant written for a non-anchor model.
- **Structured `task` intake** exists on `POST /tasks/<pod>` only; the CLI, MCP and Tack's runner do not send it.
  Trigger: Tack adopting it.
- **Decided, not open:** P52-2's bench oracle is "no step worse than the recorded request, and prefix stability not
  worse", met on the fixture (sent 0.25 to 0.66 of the baseline per step; stable 8/10, 3/4, 5/7, 6/7). The "+0.3 %
  to +3 %" was against the pre-P52-2 `condense_history`, which the bench's `phase44` policy now calls live, so it is no
  longer reproducible; the small-result rule stays. The re-ask, finalization and closing texts
  (`hops/application/runner.py`, `agent/loop_request.py`) are the harness's protocol, versioned with the code and the
  agent-loop spec, not role prompts. `smoke_workflow.py` calls an interpreter running a script (`PYTHONPATH=src python3
  x.py`) opaque on purpose: it can read any file, so the private-path check fails closed; `VAR=x` alone is parsed.

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.
- **`FailureKind` enumerates only the four kinds the task state writes**; hop and gate kinds stay plain
  strings (pod-dispatch spec item 9). Trigger: the next change to those kinds.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
