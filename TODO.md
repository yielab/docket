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
> ## ▶ ACTIVE BOARD — WAVE 60-61 (2026-11-03): Phases 60 and 61
>
> **Active: Phases 60 (D-82) and 61 (D-83)**, accepted 2026-11-03, below, in four waves; no card is claimed yet. Phase 59 (D-81, [ADR 0038](docs/adr/0038-a-step-budget-is-a-checkpoint-not-a-cliff.md)) closed 2026-11-03
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

## ▶ PHASE 60 ACTIVE — WAVE 60-61 · a transient failure costs a request, not a step (D-82) · accepted 2026-11-03

> From an app-dev Implementer step (`task-61932818`, 2026-11-03) that failed `hop_failed` after three
> requests to haiku-5-5 each received no byte in 120 s, while the other 152 requests of the live home
> took p99 11.6 s. Measured in the traces and the stored sessions of `~/.docket` (2026-10-24..11-03);
> the maintainer's analysis is in the gitignored `internal-docs/audits/`. API stays 6.
>
> **Waves (by file):** 1: P60-1 ‖ P60-3 ‖ P61-1 · 2: P60-2 (after P60-1) ‖ P61-2 · 3: P61-3 ‖ P61-5 ‖
> P61-6 · 4: P61-4 · 5: P61-7 · 6: P61-8. P60-1 owns `agent/loop*.py`, `agent/ports.py`, `driver_support.py`, `runner.py`; P60-3 owns
> `tasks/application/record.py` until P61-3.

### P60-1 — A transient failure is retried per request, inside the turn

**Status:** DONE 2026-11-03 (a request retried in the turn; live: two `request_retry` events then `timeout` at 2 s and 4 s) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** none

- **Trigger:**
  - The three failed requests had 10-17k input tokens; each ended the turn (`agent/loop.py`
    ~470-481), and `hops/application/runner.py::_run_hop_turn` (~141-260) re-ran it: the session
    was compacted (three summary requests, ~25 s) and the model re-read for 6-8 rounds. The step's
    two retries (`DISPATCH_RETRIES_*`) were spent on three stalls in nine minutes; the step ran
    532 s on a 300 s clock, because every attempt gets a fresh clock and a fresh token budget.
  - By code, not yet seen: `agent/loop_budget.py::request_timeout` (~202-209) cuts a request to
    the clock left; when it fires the adapter returns `timeout`, which the runner retries with a
    fresh clock. ADR 0038: `timeout` means only a request or transport timeout.
- **Goal:**
  - One function sends a request and retries `timeout` and `daemon_error` up to the step's retry
    count (step `retries`, then `DISPATCH_RETRIES_<ROLE>`, then `DISPATCH_RETRIES_DEFAULT`, as
    today), sleeping `min(max(DISPATCH_RETRY_BACKOFF_S × n, Retry-After), DISPATCH_RETRY_MAX_WAIT_S)`.
    The task request and the compaction summary request (`loop_compaction.py` ~112, ~208) both use
    it. A retry whose wait does not fit in the clock left is not made. Each retry is traced as
    `request_retry` `{attempt, retries, failureKind, error, retryAfterS}`.
  - A request whose timeout was the clock left, not `request_timeout_s`, ends the turn
    `budget_exhausted` `{bound: time}` under P59-3's landing rules, never `timeout`.
  - The hop's in-place retry is deleted: the loop in `_run_hop_turn`, `_RETRYABLE_FAILURE_KINDS`,
    the backoff sleep and the `hop_retry` event. One turn per hop. The hop's `attempts` is
    `1 + TurnResult.request_retries`.
- **Non-goals:** streaming (follow-up below); changing `AGENT_LOOP_REQUEST_TIMEOUT_S` (120 s is what
  a full 8,192-token reply needs at the slowest measured 90 tokens/s); retrying anything after a
  response body arrived (`invalid_output`, a truncated reply); a new setting.
- **Change:**
  - `agent/loop_request.py` (the retrying send); `agent/loop.py` ~433-481 (the request site);
    `agent/loop_compaction.py` ~112, ~208; `agent/loop_budget.py::request_timeout` (say whether the
    clock set the timeout); `agent/loop_types.py` (`LoopConfig.request_retries`,
    `AgentLoopResult.request_retries`); `agent/ports.py` `TurnResult` (~187-201);
    `hops/application/driver_support.py::_loop_config` (~329; the count travels like the hop
    timeout's source); `hops/application/runner.py` (~49, ~141-260).
  - Specs: `agent-loop.spec.md` a "Transport retries" section after "Per-request endpoint fit"
    (~382) and the clock-cut request under "Stop conditions" (~85); `pod-dispatch.spec.md`
    "Retries and the failure-kind taxonomy" 2-6 (~563-605): retries move to the request,
    `attempts` counts requests tried, requirement 6 keeps only the retried-task half.
- **Acceptance (RED first):**
  - `tests/unit/agent/test_loop.py`, fake backend and fake sleep:
    - `[timeout, ok]` ends ok with `request_retries == 1`, one `request_retry` event, and no message
      from the failed request in the session. Oracle: before the change the turn ends `ok: false`.
    - `[timeout] × 3` with retries 2 ends `failure_kind == "timeout"` after three requests and sleeps
      `[2, 4]`; `daemon_error` with `retry_after_s=5` sleeps 5.
  - `tests/unit/agent/test_loop_budget.py`: a clock of 10 s, a request sent with 3 s left, the
    transport timeout fires → `budget_exhausted` `{bound: time}`; the same with `request_timeout_s`
    the smaller limit → `timeout`. Oracle: before, both are `timeout`.
  - `tests/unit/agent/test_loop_compaction.py`: a summary request `[timeout, ok]` compacts.
  - `tests/integration/tasks/test_retries_and_timeouts.py`: a fake driver returning `daemon_error`
    runs once, `attempts == 1 + its request_retries`, and no `hop_retry` event exists. Oracle:
    before, three runs.
  - Real run (integrator, phase close): a throwaway home and pod on haiku-5-5 with
    `AGENT_LOOP_REQUEST_TIMEOUT_S=8` (the measured p90 is 7.5 s, so about one request in ten times out and three in a row is rare): the
    trace holds `request_retry` events and the task ends `done`.
- **Gate:** the four files under `timeout 120`; `tests/architecture` (3 s); `tests/e2e -n auto`
  (42 s: `attempts` on the HTTP task).

### P60-2 — The hosted profile sizes the kept history from the model's window

**Status:** DONE 2026-11-03 (hosted history 25k tokens; live: in a 5-hop research task every request after the first of a hop read the previous request's prefix from cache (4 of 4 pairs), no rewrite; too short a task to measure the 20 % bound) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P60-1
(`loop_types.py`, `loop_compaction.py`, `driver_support.py`)

- **Trigger (live home, 152 Anthropic requests):**
  - 57 requests (37 %) report `cacheMiss: messages_changed` and fall back to the 5,116-token
    system-and-tools prefix. Cache writes are 696k tokens against ~238k for a prefix that only
    grows (2.9×), and a write counts as a new token toward every budget.
  - Replaying the 113 requests of the stored sessions through `condense_history`: 43 (38 %) rewrite
    an earlier message, every one a batch boundary of `session-history.spec.md` requirement 30,
    none from requirement 32. The batch is 6,000 characters with a 3,000 low water
    (`agent/session.py` ~67-73, ~330), sized for a 32k window and applied to a 1M one.
  - Turn-start compaction uses the role's context budget (8,000 for the Implementer;
    `session_compaction.py` ~438 calls `budget_for_role` without the window), because
    `LoopConfig.history_budget_tokens` (`loop_types.py` ~90) has no writer. The step above was
    compacted from 21k to 8k tokens on each retry.
  - The same replay with the history budget below (25,000 tokens: 18,750 / 9,375 characters):
    21 of 113 (19 %).
- **Goal:**
  - `BudgetShares` gains `history` (a share of the window in (0, 1]). `hosted` declares
    `history: 0.025`; `local` declares none. The resolved history budget is
    `max(role context budget, floor(window × share))`, and the role's context budget without a
    share or a window (today).
  - The driver writes `LoopConfig.history_budget_tokens` from it; turn-start compaction already
    takes that parameter.
  - `condense_history`'s whole-results budget is `max(6000, history_tokens × bytes_per_token × 3 //
    16)` (3/16 is today's ratio: 6,000 of the 32,000 characters an 8,000-token history holds) and
    its low water half of it; `HISTORY_LOW_WATER_CHARS` is deleted. A role budget of 8,000
    gives 6,000 and 3,000, so `local` stays byte for byte.
- **Non-goals:** a second cache breakpoint (follow-up below); `local`'s numbers; the role's
  `tokenBudget` for the compiled context (`compose.py` ~369); any number keyed by model id.
- **Change:** `models/catalog.py` (`BudgetShares` ~117, `ProfileBudgets` ~134, `BUILTIN_PROFILES`
  ~157, `_budgets_of` ~169); `hops/application/driver_support.py` (`_turn_budgets` ~191,
  `_loop_config` ~329); `agent/loop_compaction.py::messages_for_durable` (~244); `agent/session.py`
  (~67-73, `_batch_cut` ~327, `condense_history` ~356). Specs: `model-profiles.spec.md` "Model
  profiles" 1-2 (~430-445); `session-history.spec.md` 29-31 (~156-188), the boundary promise
  unchanged.
- **Acceptance (RED first):**
  - `tests/unit/models/test_catalog__profile.py`: `hosted` with a 1,000,000 window and a role budget
    of 8,000 resolves 25,000; with 200,000 it resolves 8,000; `local` with 32,768 resolves 8,000. A
    provider document with `budgets: {history: 0}` is refused naming the field.
  - `tests/unit/agent/test_session__condense.py`: a history of 25,000 gives 18,750 and 9,375, and a
    fixture of growing results moves the cut once where 6,000 moved it three times; at 8,000 the
    existing cases pass unchanged.
  - `tests/unit/agent/test_loop_compaction.py`: a 21,000-token session with
    `history_budget_tokens=25000` is not compacted at turn start; with 8,000 it is. Oracle: before
    the change the first is compacted.
  - `scripts/maint/context_replay.py tests/fixtures/context-replay` under the local policy: no step
    worse than recorded (P52-2's oracle).
  - Real run (integrator): one app-dev task on haiku-5-5 reports `messages_changed` on at most 20 %
    of its requests (37 % before).
- **Gate:** the three unit files under `timeout 120`; `tests/architecture`; the replay bench.

### P60-3 — A failed Implementer hop keeps its work after a transport stop

**Status:** DONE 2026-11-03 (a failed Implementer hop keeps its work) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** none

- **Trigger:** `task-61932818`'s hop record has `files_changed: []` and Tack shows "This run changed
  no files", while the task worktree holds `guard.ts` and `guard.test.ts` modified and
  `src/lib/botcheck/` new. `tasks/application/record.py::_keeps_its_work` (~413-415) pins only
  `budget_exhausted`, narrower than ADR 0038 decision 2.
- **Goal:** an Implementer hop that ended `budget_exhausted`, `timeout` or `daemon_error` is pinned
  as P59-2 pins it (commit, `filesChanged`, evidence); it stays `ok: false`, and `budget` stays
  `null` for a transport stop.
- **Non-goals:** other roles; approvals, `invalid_output`, `no_progress` and cancellation keep
  today's behaviour (P61-3 adds `capability_missing`).
- **Change:** `record.py` ~413-415; `pod-dispatch.spec.md` "Implementer diff producer" (~1717).
- **Acceptance (RED first):** a new `tests/integration/tasks/test_failed_hop_keeps_work.py`: a fake
  Implementer driver writes `app.txt` and returns `timeout` → the hop is `ok: false` with
  `artifact.filesChanged == ["app.txt"]` and the task branch has a commit holding it; a Reviewer
  hop that ends `timeout` pins nothing. Oracle: before, `filesChanged == []`.
- **Gate:** that file; `tests/architecture`; `tests/e2e -n auto` (the HTTP task shape).

## ▶ PHASE 61 ACTIVE — WAVE 60-61 · a pod says what it can reach (D-83) · accepted 2026-11-03

> Tack's request, carried by the maintainer, from `task-6d3fc1e9` on `web-research`: four steps met
> the same three gaps, each handed off `ok`, and the writer opened one consult that mixed them
> (`esc-7b6ebde7f664`; option A asked for three things). Verified live on `GET /pods/web-research`
> and in the code. Every change is additive on API 6, announced in `features`, and its new JSON is
> captured under `tests/fixtures/operator-v2/` for Tack. No contract version moves. ADR 0036
> decision 17 and ADR 0032 decisions 6-7 are written; the cards build them.

### P61-1 — The pod report says whether its network is enforced, and where its folder is

**Status:** DONE 2026-11-03 (live: `GET /pods/web-research` `network.enforced` agrees with `docket status`) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** none

- **Trigger:**
  - `network` is `{mode, scope}` (`hops/application/report.py` ~416-418; members ~361-363), and
    `GET /pods` rows carry none (`pod_summary` ~518-531). `teams/network_posture.py::network_posture`
    (~28) computes `enforced` from isolation alone, not the backend, and only the CLI uses it.
  - Tack read `workdir: null` because no field carries it: all six `web-research` members hold
    `workDir` (`pods/web-research/workdir`, present on disk).
- **Goal:** `network.enforced: bool` on the pod, each member and each `GET /pods` row (which gains
  `network`): true only when the mode is `none`, isolation is on
  (`teams/fleet.py::get_isolation_enabled` ~249) and a backend exists
  (`sandbox_availability().backend != "none"`). `network_posture` takes that one fact, so the CLI
  and HTTP agree. A `workdir` pod's report and row carry `workDir`. Features `networkEnforced` and
  `podWorkDir` (`interfaces/http/routes/health.py` `FEATURES` ~21-33).
- **Non-goals:** per-pod isolation; what `none` means.
- **Change:** `teams/network_posture.py`; `report.py` (~361, ~416, ~518, ~543); `health.py`; specs
  `specs/api/operator-api.spec.md` (the pod shape), `specs/data/serve-read-api.spec.md` (~114).
- **Acceptance (RED first):**
  - `tests/unit/teams/test_network_posture.py`: `none` with isolation on and a backend → enforced;
    isolation off → not; isolation on and backend `none` → not; `open` → not. Oracle: before, the
    third is enforced.
  - `tests/integration/interfaces/test_serve_pods_config.py`: a workdir pod's `GET /pods/<pod>` has
    `network.enforced` and `workDir`; its `GET /pods` row has `network.enforced`; `/status.json`
    lists both features. The response, home path normalized to `<home>`, is
    `tests/fixtures/operator-v2/pod-reach.json`, and the test compares against it.
  - Live (integrator): after `./install.sh` and a service restart, `GET /pods/web-research` on :7399
    shows `enforced` agreeing with `docket status`.
- **Gate:** the two files; `tests/architecture`; `tests/e2e -n auto` (HTTP API).

### P61-2 — A pod declares the hosts its `fetch` reads

**Status:** DONE 2026-11-03 (live: web-research with `*.wikipedia.org` fetched es.wikipedia.org (allowed) and example.com was refused naming the pod's list) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P61-1
(`report.py`, `health.py`)

- **Trigger:** the maintainer's request (Tack's report): `web-research` could read the web only
  through the machine's exact-host list (`kernel/home.py` ~275-279, `platform/fetch.py` ~218,
  ~259-262), empty by default. ADR 0036 decision 17.
- **Goal:** decision 17 as written. The pod setting `fetchDomains` (`*.host` for subdomains, never the
  apex; `*` only through `pod set fetchDomains '*' --widen`, recorded and audited like the network
  grant). `FETCH_ALLOWED_DOMAINS` accepts `*.`. One matcher serves the call and the redirect guard.
  `platform` imports nothing above it, so `fetch_url` (`platform/fetch.py` ~243) takes the allowed
  set as an argument and `allowed_domains()` (~218) goes; `builtin_tools.py` passes the member's
  set. `_offered_fetch` (`hops/application/builtin_tools.py` ~487-490, ~623) offers `fetch` when the
  member's set (machine plus pod) is not empty; `member_capabilities`
  (`hops/application/capabilities.py` ~23-39) lists it only then and adds `fetchDomains`; the pod
  report adds the pod's declared `fetchDomains`. Feature `podFetch`.
- **Non-goals:** a search tool; methods, headers or bodies; network rules inside the jail;
  `pod update` or the HTTP apply writing `*`.
- **Change:** `teams/pod_settings.py` (the setting and the grant beside the network one, ~50,
  ~591-607); `platform/fetch.py`; `builtin_tools.py`; `capabilities.py`; `report.py`; `health.py`;
  specs `security-gates.spec.md` (fetch), `agent-loop.spec.md` requirement 83 (~697), the pod and
  member shapes in `operator-api.spec.md`.
- **Acceptance (RED first):**
  - `tests/unit/platform/test_fetch.py`: `*.example.org` allows `a.example.org` and
    `b.a.example.org`, refuses `example.org` and `badexample.org`; a redirect to an unlisted host is
    refused.
  - `tests/unit/teams/test_pod_settings.py`: `fetchDomains` set and cleared; `*` refused without
    `--widen` and recorded with its date and audited with it; a document carrying `*` through
    `pod update` is refused.
  - `tests/unit/hops/application/test_builtin_tools.py`: an empty machine list and a pod list
    `[docs.python.org]` offer `fetch` reaching that host only; a role denying `fetch` gets none.
    Oracle: before, no `fetch` is offered.
  - `test_serve_pods_config.py`: the member's `capabilities.tools` has `fetch` and `fetchDomains ==
    ["docs.python.org"]`; fixture `tests/fixtures/operator-v2/pod-fetch.json`.
  - Live (integrator): `docket pod set fetchDomains '*.wikipedia.org' --pod web-research`, then a
    research task: the trace shows an allowed `fetch` of an `es.wikipedia.org` page and a refused
    one elsewhere.
- **Gate:** the four files; `tests/architecture`; `tests/e2e -n auto`.

### P61-3 — A configuration gap ends the step with `capability_missing`

**Status:** DONE 2026-11-03 (feature `capabilityMissing` live on the reinstalled service; the Tack task rerun was not made, the stop is proven by the integration test) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P60-1
(`agent/`), P60-3 (`record.py`), P61-2 (the `fetch` fix, `health.py`)

- **Trigger:** in `task-6d3fc1e9` the Lead was refused twice `unknown tool
  'rec__tack_proposals__add'` with "offered when the pod declares that record set", and handed off
  `ok`; the researcher and the analyst reported no network and handed off `ok`; the writer asked a
  person. ADR 0032 decision 7.
- **Goal:**
  - The driver gives the turn the tool names the pod offers any member and its declared record
    sets (`capabilities.py`). `dispatch_tool` returns a typed gap `{kind, name, fix}` for:
    - `tool`: a tool another member holds, or a declared service or MCP server offers, missing
      from this role; the fix names the role's `tools`.
    - `records`: `rec__<set>__*` for a set the pod does not declare (declare `records/<set>.yaml`,
      then `docket pod update`), or one the role may not write (add `rec__<set>` to its `tools`).
    - `fetch`: `fetch` not held while the task's pod could hold it (`docket pod set fetchDomains
      <host> --pod <pod>`). A host outside the set stays an ordinary refusal whose text names the
      same command: a researcher may try several hosts, and one miss is not a gap.
    The pod's names reach `dispatch_tool` as one typed value on the registry, computed in
    `driver_support.py` (hops); `agent/` reads no pod, fleet or records module.
  - The loop stops at the first gap, like the `approval_parked` stop (`agent-loop.spec.md` ~617),
    with `failure_kind capability_missing`. The hop records `capabilityMissing {kind, name, fix}`;
    the task fails `failureKind: capability_missing` with `reason` "<role> needs <kind> '<name>':
    <fix>"; no escalation is opened; an Implementer's work is kept (P60-3's set gains it). Feature
    `capabilityMissing`.
  - `pod-dispatch.spec.md`'s failure-kind list (~2268) gains `capability_missing`, and also
    `hop_failed` and `pod_budget`, which the enum has (`tasks/domain/state.py` ~29-44) and the list
    lacks.
- **Non-goals:** spotting a network failure inside `bash` (no deterministic signal; P61-5 tells the
  model); a name no member has (stays `invalid_call`); a missing workdir (follow-up below).
- **Change:** `agent/tools/registry.py` (the unknown-tool refusal); `agent/loop_steps.py` (the
  stop); `agent/ports.py` `FailureKind` (~59-66); `tasks/domain/state.py`; `tasks/domain/task.py`
  (`HopResult`); `record.py` (`_turn_failure_kind`, `_keeps_its_work`);
  `hops/application/driver_support.py` (the pod's names); `health.py`. Specs: `agent-loop.spec.md`
  (a "capability_missing stop" beside ~617), `pod-dispatch.spec.md` (~563 requirement 1, ~2268),
  the task and hop shapes in `operator-api.spec.md`.
- **Acceptance (RED first):**
  - `tests/unit/agent/tools/test_registry__dispatch.py`: each kind returns its gap and fix; a name
    no member has is `invalid_call` as today.
  - `tests/unit/agent/test_loop_steps.py`: a turn whose second call meets a gap stops after it with
    `capability_missing` and sends no further request. Oracle: before, the turn goes on.
  - A new `tests/integration/tasks/test_capability_missing.py`: a lead → writer pod whose Lead calls
    `rec__tack_proposals__add` with no set declared: the task is `failed` with `failureKind ==
    "capability_missing"`, the hop has `capabilityMissing == {kind: "records", name:
    "tack_proposals", fix: ...}`, no escalation exists and the writer never runs. Fixture
    `tests/fixtures/operator-v2/task-capability-missing.json`.
  - The fix sentences pass the CLI invocation linter (`tests/guards/`).
  - Live (integrator): the same `web-research` task re-run from Tack fails at the Lead with that fix
    instead of reaching the writer.
- **Gate:** the three files and the linter guard; `tests/architecture`; `tests/e2e -n auto`.

### P61-4 — One escalation per question

**Status:** DONE 2026-11-03 (live: a web-research task asked two questions, `GET /escalations` showed parts 1/2 and 2/2, the task stayed `waiting_input` after one answer and finished with both) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P61-2
(`builtin_tools.py`), P61-3 (`health.py`)

- **Trigger:** `esc-7b6ebde7f664` asked three things in one message, and its option A bundled three
  requests. ADR 0032 decision 6.
- **Goal:** `consult` takes `questions` (one to five), each `{kind, message, options,
  recommendation}`, in place of today's top-level fields. `consult.run` opens one escalation per
  question, each with `part: {index, count}` (1-based; `{1, 1}` for one question, absent on other
  kinds). The step stays parked until every part is settled, and the answers reach the turn
  together in question order. A pod in `consultMode: decide` decides each part by its
  recommendation. The tool's description says an option is one action. Feature `consultParts`.
- **Non-goals:** `questions[]` on one escalation; checking options mechanically; Telegram beyond
  showing `1/3`.
- **Change:** `builtin_tools.py` (`_consult_tool` ~186-222, `_consult_handler` ~114);
  `tasks/application/consult.py` (~163, ~206); `tasks/application/escalations.py`
  (`open_for_question` ~214-249, `decided_consult` ~352, `resolve` ~603);
  `hops/application/resolutions.py` (`_unapplied` ~110, `apply_resolutions` ~197: a question's
  parts are applied together, and none while one is pending); `kernel/operator_contract.py`
  (`_EscalationFields` ~289-316, `as_question` ~325); `docs/contracts/operator-v2/question.schema.json`
  (additive `part`, no version change). Specs: `operator-loop.spec.md` "11. Escalations" (~690) and
  "Consult" (~1036), `specs/api/operator-api.spec.md` (~478), `specs/data/docket-store.spec.md`
  "Escalation records" (~73).
- **Acceptance (RED first):**
  - `tests/integration/tasks/test_consult_budget.py` or a new sibling: three questions open three
    escalations on one task and step with parts 1/3 to 3/3; answering one leaves the task parked;
    answering all sends the three answers, in order, in the turn's next request. Under
    `consultMode: decide` the three are decided. Oracle: before, one escalation.
  - `tests/contracts/test_escalation_http.py` (35 s): `GET /escalations` shows `part`; new fixture
    `tests/fixtures/operator-v2/escalation-consult-parts.json`; `escalation-consult.json` gains
    `part: {index: 1, count: 1}`.
  - Live (integrator): a `web-research` task told to ask two independent questions shows two
    escalations in `docket inbox` and in Tack.
- **Gate:** the two files; `tests/architecture`; `tests/e2e -n auto`.

### P61-5 — The hop message states the member's reach and folder

**Status:** DONE 2026-11-03 (live: the first request of a web-research hop holds Working folder, Network, Web and Records lines) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P61-1,
P61-2 (the facts it states)

- **Trigger:** in `task-6d3fc1e9` the researcher and the analyst learned "no internet" by failing on
  DNS, and the writer "could not find the team folder's path": a workdir hop reads only "the pod's
  working directory" (`hops/application/compose.py` `_WORKDIR_LINE` ~136, `_root_line` ~142), and
  neither `compose.py` nor `teams/identity.py` states the network, the web or the record sets.
- **Goal:** `_hop_message` (~307) carries a short block from the facts the pod report serves: the
  working folder's path (workdir pods); the network (`none, enforced by the jail` · `none, not
  enforced: isolation is off` · `open`); the web (`fetch reads <hosts>, outside the jail` · `no web
  access`); the record sets the role may write, or none. It goes in the hop message, beside the
  working-directory line it already carries, because these facts are the pod's and the task's,
  not the member's identity. Its wording lives where ADR 0035 keeps hop text, under
  that ADR's version rule.
- **Non-goals:** listing tools (the tool list does); repeating the block in a continuation message.
- **Change:** `compose.py` (~136-142, ~307) and the hop text file ADR 0035 names; the hop message
  section of `pod-dispatch.spec.md`; goldens whose hop text gains the block, regenerated with a diff
  that shows only the block, named in the commit body.
- **Acceptance (RED first):** `tests/unit/hops/application/test_compose__hop_message.py`: a workdir
  pod with network `none` enforced, `fetchDomains [docs.python.org]` and `tack_proposals` writable
  by the role reads exactly those four facts; a codebase pod with nothing reads `none`, `no web
  access`, no records. Oracle: before, none of the lines exist. Live (integrator): the first request
  of a `web-research` task holds the block (`prompt_composed`).
- **Gate:** that file; `tests/golden/run.sh verify-all` (4 s); `tests/architecture`.

### P61-6 — `fetch` keeps the service perimeter at any host

**Status:** DONE 2026-11-03 (live: exact `localhost` read the service, a PDF was refused as not text, hosts off the list were refused, es.wikipedia.org read) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P61-2
(`platform/fetch.py`, the `fetch` section of `security-gates.spec.md`)

- **Trigger:** the maintainer's request (2026-11-03): a research pod must read sites nobody here
  controls, "a solid and secure implementation, not a patch". P61-2 opens `*.host` and `*`, but
  `fetch_url` (`platform/fetch.py` ~243-315) checks only the host *name*. It opens through
  `urllib.request.build_opener` (~276) with the environment's proxies and a second, unchecked DNS
  lookup. So under `*`, `http://127.0.0.1:8081/` (this machine's model endpoint),
  `http://localhost:7399/` (docket's own API), `http://169.254.169.254/` (cloud metadata), a LAN
  address, or a public name that resolves to any of these is reached from docket's process, outside
  the jail. A redirect from https to http is followed (`_DomainLockedRedirectHandler` ~182-213). A
  binary body (a PDF) is decoded as UTF-8 and handed to the model (~303-305). The service caller
  already closes the first three (`platform/service_http.py`: `address_refused` ~115; `_connector`
  ~157-182 connects only to the address it has just checked; `ProxyHandler({})` ~314;
  `_PerimeterRedirects` ~226-250; ADR 0036 decision 13). `fetch` was left on the older guard.
- **Goal:** one perimeter for every outbound HTTP call docket makes itself.
  - Move the address check, the checked connector, the two handlers and the redirect guard from
    `service_http.py` to `platform/perimeter.py`. This is a pure move: `pytest --co` and
    `tests/architecture` are its check. Then `fetch_url` and `call_operation` both open through it.
    `fetch.py` keeps no opener of its own.
  - **Addresses.** Every address a host resolves to is checked, and the socket connects to that
    checked address (no second lookup, so rebinding cannot swap it).
    - A private, loopback, link-local, multicast or unparseable address is refused before a byte is
      sent.
    - Exception: the host is an *exact* entry of the member's set, not one matched by `*.` or `*`.
      This keeps the recipe's self-hosted SearXNG working (`searxng.lan`, `localhost`).
    - An IP-literal URL is checked the same way.
  - **No environment proxy.** `HTTP_PROXY` and `HTTPS_PROXY` are ignored, as the service caller
    already does.
  - **Redirects.** Each hop is checked by P61-2's matcher and then by the address check. https to
    http is refused.
  - **Text only.**
    - A body is text when its content type is `text/*`, `application/json`, `application/xml`,
      `application/javascript`, `*+json` or `*+xml`.
    - With no content type, a body is text when it has no NUL byte in its first 8 KB.
    - Anything else is refused as `content type 'application/pdf' is not text; fetch reads text
      pages`, and none of the body reaches the model.
  - **Refusals.** Each is `ToolOutcome(ok=False, refusal="fetch_not_allowed")`, so the existing
    audit path (`governance/gate.py` `audit_refusal` ~408-418) records the host. The error text
    names the resolved address and the fix ("list the exact host in the pod's fetchDomains").
- **Non-goals:**
  - extracting text from a PDF or another document (follow-up below);
  - a port rule;
  - methods, headers or bodies (ADR 0036 "Not doing");
  - a search tool (decision 17);
  - rendering JavaScript;
  - an operator-configured egress proxy.
- **Change:** `platform/perimeter.py` (new, moved from `service_http.py` ~115-250);
  `platform/service_http.py` (imports it; `call_operation` ~277-347); `platform/fetch.py` (~182-213
  goes, ~276, ~300-315); `tests/unit/platform/test_perimeter.py` (the moved cases from
  `test_service_http.py` ~43); `tests/unit/platform/test_fetch.py`;
  `tests/integration/platform/test_fetch__wire.py`. Spec: `security-gates.spec.md` "`fetch`: an
  inspectable path" (~1120-1185): the address, proxy, downgrade and text rules. Also its known
  limits: `fetch` is still an outbound channel through its URL (P61-7), and a public host that
  serves hostile text is `pre_input`'s job (~1186).
- **Acceptance (RED first):**
  - `test_fetch__wire.py`, with a local server on `127.0.0.1` that counts requests:
    - set `*`: `http://127.0.0.1:<port>/` and `http://localhost:<port>/` are refused, and the server
      counts 0;
    - set `localhost` (exact): the fetch is allowed and the server counts 1;
    - set `localhost`, with `HTTP_PROXY` pointing at a closed port: the fetch still reaches the
      server directly;
    - set `localhost, *`: a redirect from `localhost` to `127.0.0.1` is refused.
    - Oracle: on P61-2 alone, the `*` case counts 1.
  - `test_perimeter.py`:
    - the addresses already at `test_service_http.py` ~43, plus an IPv4-mapped IPv6 one, are refused
      and a public one is not;
    - an https to http redirect is refused;
    - a resolver seam that answers a public address and then a private one is called once, and the
      connection goes to the first answer.
  - `test_fetch.py` (the `_fetch_with` seam ~82): `application/pdf` returns `ok=False` with an empty
    content and the type in the error; `application/ld+json` and an untyped UTF-8 body pass.
  - `test_service_http.py` passes unchanged: the move keeps the services' behaviour.
- **Gate:** the four test files; `tests/architecture`; `tests/e2e -n auto` (42 s; `fetch`'s output
  changes).

### P61-7 — A `fetch` URL that carries a credential is refused

**Status:** DONE 2026-11-03 (live: a web-research fetch of a URL with a fake key shape was refused naming the rule, and the audit row holds the host only) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P61-4
(`builtin_tools.py`), P61-6 (the `fetch` section of `security-gates.spec.md`)

- **Trigger:** the same request. With `*`, `fetch` is an outbound channel: a GET's URL carries
  whatever the model writes into it, to a host nobody vetted.
  - ADR 0036 decision 2 keeps `send` and `fetch` out of one hop, but not this.
  - The shipped credential shapes run only `on: output`, for logging
    (`templates/policies/secret-pii-redact.yaml`), and never on a call's arguments.
  - A home holds only the policies its operator installed, so a policy is not the place for this.
- **Goal:** `_fetch_handler` (`hops/application/builtin_tools.py` ~228) refuses, before `fetch_url`
  is called:
  - a URL with userinfo (`user:pw@host`);
  - a URL whose percent-decoded text changes under `governance/secrets.redact(personal=False)`
    (~213). That function covers the credential shapes and the exact stored secret values; with
    `personal=False`, an e-mail address in a search query is not a credential.

  The rule holds at every host. A key belongs in a declared service (ADR 0036 decision 13), never in
  the model's hand. The refusal is `refusal="fetch_secret_in_url"`, and `audit_refusal` (~408) gains
  it with the host only. The error says which rule matched and never quotes the value.
- **Non-goals:** a secret that is encoded, split or shaped like none of the patterns (known limit
  `unlisted-secret-shape`, `security-gates.spec.md` ~326, which gains `fetch`); a length cap on
  queries.
- **Change:** `builtin_tools.py` (`_fetch_handler` ~228); `governance/gate.py` (`audit_refusal`
  ~408-418); `tests/unit/hops/application/test_builtin_tools.py`; `tests/unit/governance/test_gate.py`
  (or the file whose `SUBJECT` is `gate`). Spec: `security-gates.spec.md`'s `fetch` section and
  limit 5.
- **Acceptance (RED first):**
  - `test_builtin_tools.py` (`_fetch_tool` takes `fetch_url` as an argument, so a stub records its
    calls):
    - `https://example.org/?q=<a provider-key shape>` and `https://u:pw@example.org/` are refused,
      the stub is never called, and the error and the audit detail hold no key;
    - `https://example.org/?q=ana%40example.org` reaches the stub.
    - Oracle: before, the stub receives the key.
  - `test_gate.py`: `audit_refusal(..., "fetch_secret_in_url")` writes `host=` only.
- **Gate:** the two files; `tests/architecture`; `tests/e2e -n auto` (42 s).

### P61-8 — `fetch` reads a PDF's text through the jail

**Status:** DONE 2026-11-03 (PARTIAL on the live step: the jail path is proven by the integration test with real Landlock and the real pdftotext, and live the PDF fetch fails closed naming `docket setup sandbox read add <prefix>`; the read of an arXiv PDF through the grant was not run, because the maintainer must grant the Homebrew prefix (a permission rule denied the grant to the agent)) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P61-6
(`platform/fetch.py`'s text rule), P61-7 (`_fetch_handler`)

- **Trigger:** the maintainer's decision (2026-11-03). Research reads papers and reports, so
  `fetch` reads a PDF's text. A hostile PDF is parsed inside the jail, never in docket's own
  process. After P61-6, `fetch` refuses `application/pdf`. A PDF is usually over the 200,000-byte
  cap (`kernel/home.py` ~176), and a truncated PDF does not parse.
- **Goal:**
  - **`fetch_url`** (`platform/fetch.py`) hands its caller a PDF body as typed bytes, beside its
    content type, in place of P61-6's refusal. A PDF is a body of type `application/pdf`, or an
    untyped body that starts with `%PDF-`. Every other non-text body stays refused.
    - A PDF is read up to `FETCH_MAX_DOCUMENT_BYTES` (default 10,000,000; `Home`, `docs/CONFIGURATION.md`).
    - A larger one is refused whole, never truncated. The refusal names the setting.
  - **`hops/application/pdf_text.py`** (new) turns the bytes into text through the `kernel.ports.jail`
    port, the way `agent/tools/mcp_client.py` `_jailed_command` (~88) builds its argv. It does not
    use `sandbox` modules directly.
    - The bytes go to a fresh 0700 directory under the jail's temp dir. That directory is the
      jail's only root. The network is off. The read-only paths are the operator's grants
      (`ctx.read_only`, `docket setup sandbox read add`). The environment is the jail's temp
      variables only, so no credential passes.
    - It runs `pdftotext -enc UTF-8 -nopgbrk -q -- in.pdf -`. The extractor's name is one module
      constant.
    - The run is bounded by what is left of the fetch deadline, and its process group is killed
      at the deadline. Its output is capped like any tool output. The directory is removed in a
      `finally`.
  - **Fail closed**, each refusal naming its fix:
    - the recorded backend is `none` (isolation off, or no backend): "reading a PDF needs the jail".
      There is never an unjailed run.
    - `pdftotext` is not on `PATH`: name poppler.
    - the jail cannot execute it (outside `/usr`, `/opt` and the other default read roots, for
      example a Homebrew prefix): name `docket setup sandbox read add <its prefix>`.
    - with the docker backend, an image without it: name the image.
    - a non-zero exit: give the first line of stderr, bounded.
  - **Result.** `HTTP 200 application/pdf; <n> chars of text`, then the text. It passes `pre_input`
    like every `fetch` result (`security-gates.spec.md` fetch requirement 6). A refusal is `ok=False`
    with `refusal="fetch_not_allowed"` and no page bytes.
- **Non-goals:**
  - other document types (`.docx`, images, OCR);
  - layout or tables;
  - a pure-Python parser in docket's process (the maintainer's decision);
  - a `setup check` line (follow-up below);
  - caching extracted text.
- **Change:** `platform/fetch.py`; `kernel/home.py` (~176, the setting); `docs/CONFIGURATION.md`;
  `hops/application/pdf_text.py` (new); `hops/application/builtin_tools.py` (`_fetch_handler`
  ~228); `tests/unit/hops/application/test_pdf_text.py`;
  `tests/integration/hops/test_pdf_text__jail.py` with the fixture `tests/fixtures/documents/hola.pdf`
  (a minimal hand-written PDF holding "Hola docket"). Spec: `security-gates.spec.md`'s `fetch` section
  (the PDF rule, the jail, fail closed), its known limits (the extracted text is untrusted text), and
  agent-loop requirement 83's tool text. That is nine files, with the fixture counted; the seam
  between fetch's bytes and the extractor stays in one card, so no two green cards break it.
- **Acceptance (RED first):**
  - `test_pdf_text.py`, with an injected runner (no I/O in `unit/`):
    - backend `none`: refused, and the runner is never called;
    - extractor missing: refused with the fix;
    - non-zero exit: stderr's first line, bounded;
    - output over the cap: truncation is announced;
    - the runner receives one root, network off and an environment with no credential name
      (`jail.credential_names()`).
  - `test_pdf_text__jail.py` (integration, Landlock or Seatbelt detected):
    - the fixture gives text holding "Hola docket", and the temp directory is gone afterwards.
    - With a fake `pdftotext` first on `PATH` (a script that reads `$DOCKET_HOME/token`, opens a
      socket to `127.0.0.1` and sleeps): the read and the socket fail inside the jail, the call is
      refused at the deadline, and no process is left in its group.
    - With isolation recorded off, the fake leaves no marker file.
    - Skip only when `pdftotext` is absent, and say so in the skip reason.
  - `test_fetch.py` (`_fetch_with` ~82):
    - a `%PDF-` body with no type comes back as bytes, not text;
    - a PDF over `FETCH_MAX_DOCUMENT_BYTES` is refused, never truncated;
    - an `image/png` body stays refused.
    - Oracle: on P61-6, every PDF is refused.
  - Live (integrator): a `web-research` task with `*.arxiv.org` in `fetchDomains`, on this
    machine's Homebrew `pdftotext` after `docket setup sandbox read add <the Homebrew prefix>`. The
    trace shows a `fetch` of an arXiv PDF answered with text.
- **Gate:** the three test files; `tests/architecture`; `tests/e2e -n auto` (42 s);
  `tests/integration/sandbox/test_escape_matrix.py` (it is the jail's own check, and this card adds
  a jailed launch).

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Phases 60-61 (planned 2026-11-03).** Left out of the cards on purpose:
- *PDF reading in `setup check`.* After P61-8, `docket setup check` could report whether a PDF is
  readable: whether `pdftotext` is found, whether the jail can execute it, and whether isolation is
  on. Trigger: an operator's first PDF refusal for a missing grant.
- *The `web-research` recipe after P61-2.* Its README (`templates/recipes/web-research/README.md`)
  still tells the operator to list exact hosts in `FETCH_ALLOWED_DOMAINS` and to declare search as an
  MCP server. Once P61-2 and P61-6 are merged, the README teaches `pod set fetchDomains` and a search
  site as a host (ADR 0036 decision 17). Trigger: P61-6 merged.
- *Dead retry plumbing after P60-1.* `UnitContext.do_sleep`/`on_retry` (`tasks/application/record.py`
  ~261-263), `executor.dispatch_task`'s `on_retry`/`sleep` (~475-580) and `sweep._touch` (~161) have no
  reader. Delete with P61-3, which owns `record.py` next.
- *`NOT_ENFORCED` wording.* "isolation off" is also what a machine with isolation on and no backend prints
  (`teams/network_posture.py`); changing it moves a golden and security-gates requirement 14. `pod_summary`
  probes the backend per row. Trigger: an operator misreads the line, or a pod list slower than 50 ms.
- *Is `capability_missing` pinned?* Whether P61-3's kind joins `_PINNED_FAILURE_KINDS` (`record.py`).
- *`fetch` text extraction and its byte cap.* The live Chile page was cut at the infobox by the 200,000-byte cap
  (`platform/fetch.py`), before the first sentence: the cap counts HTML, not text. Trigger: a research task that
  reports a page it could not read. P61-6 changes the body rules; decide there or after it.
- *A pod.yaml `fetchDomains` is not a run item.* `teams/apply/review.py` `_NOT_ADDED_SETTINGS`: should adding
  hosts need `accept`? Also `_export_manifest` exports a pod's `*` as `fetchDomains: '*'`, which `pod update`
  refuses. Trigger: the first repo that ships `fetchDomains`. Tack: `pod-reach.json` gained `fetchDomains`.
- *The fetch refusal for a host off the pod's list does not name the pod command.* `platform/fetch.py` ~279 says
  "add it to FETCH_ALLOWED_DOMAINS, or to the pod's fetchDomains"; P61-3's card wanted the exact `docket pod set`
  command. `platform` does not know the pod. Trigger: a hop that stops on this refusal and a person asks how.
- *`capability_missing` for a tool is "a name the role could hold".* P61-3 chose that over "a tool another member
  holds" so a deliberate `deniedTools` is not a gap. A Reviewer calling a record write it may not use now fails
  the task `capability_missing` (`tests/e2e/test_workdir_pod.py` follows).
- *Sibling consult parts and expiry.* P61-4: if one part expires (`onExpiry: block`) the others become unanswerable
  (`tasks/application/escalation_sweep.py`); `operator/inbox.py` `_pending_id` shows only the newest pending part
  while `/escalations` lists all (live: `docket inbox` printed one question for a two-part consult); if the parked
  token's question is lost, parts 1..n-1 stay orphaned on a failed task. Trigger: a two-part consult that expires,
  or a person who cannot find the first question in the inbox.
- *A refused `fetch` URL still sits in the trace.* P61-7 refuses the call and keeps the key out of the result and the
  audit row, but the trace's `tool_call` event records the model's arguments as written (seen in a live trace), and
  `governance/gate.py` `render_tool_call` renders `fetch url=...` for `pre_tool_call` policies. Trigger: the first
  export at a privacy level that sends tool arguments (`full`) of a run that had a refusal; then redact call
  arguments with the same `secrets.redact` before the trace writes them. Also unmatched: a double-encoded key, a
  stored secret of 8 characters or fewer, and the keyring backend (the spec lists them under `unlisted-secret-shape`).
- *`run_jailed` lives in `platform/fetch.py`.* P61-8 put the jailed Popen, process-group kill and bounded read there
  because `tests/guards/test_no_subprocess_in_core.py` forbids `subprocess` in `hops/`. Move it to its own
  `platform` module. Also stale: the `ToolContext.read_only` comment ("only a jailed bash reads them",
  `agent/tools/registry.py` ~94), and a `setup check` line for `pdftotext`. The `header n chars` of a PDF result counts
  the returned text, not the full extraction.
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
- **Pod memory with non-path subjects** (`workspace-structure.spec.md:158-169`: a subject is a
  repository path; a workdir pod's "the client prefers a formal tone" has no home). Trigger: a recorded
  workdir run whose Lead repeats a correction a person already made.

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
  Telegram `/status`.** Needs an operator-v1 inbox contract bump.
- **`GET /pods` (the list) was not checked** for the invalid-settings failure fixed on `/pods/<p>`.
- **`POST /pods/<p>/apply` with every item skipped writes no `pod.apply` audit entry.**
- **The corrections cursor needs `+` percent-encoded in `since`**; a pod whose Lead was removed but
  whose ledger remains answers `404`.
- **The `openhands` and `pydantic_ai` adapters never pass `cache_write_tokens`**
  (`packages/docket-runtime/src/docket_runtime/adapters/`). Trigger: someone reads that usage.

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
