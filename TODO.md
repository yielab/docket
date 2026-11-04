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
> ## ▶ BOARD — Phase 67 ACTIVE (its real run, P67-5, re-runs as P68-6); Phases 68 (D-89 proposed) and 66 (D-87 proposed) planned
>
> **Phase 67 is active** (D-88, accepted 2026-11-04): P67-1 to P67-4 are done and committed (`2ce62d69`, `3b32a2b4`,
> not pushed): a folder pod under the jail reads any public host, the pod says how (`webRead`) and which need
> blocks, and Tack reads both. Its real run (P67-5) read the web and failed in the writer hop on a compaction
> defect, with no report. **Phase 68** (D-89, proposed) is that run's three defects plus search and runs first;
> **Phase 66** (D-87, proposed) follows, since both edit `session_compaction.py`. Neither phase's cards are
> claimable until the maintainer accepts its decision. Phases 63 (D-85) and 64 (D-86) closed 2026-11-04; their
> sections are archived and what they leave open is under "Phases 63-64" in the follow-ups below.
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

## ○ PHASE 68 PLANNED — what the first real research run broke: compaction, a payment false positive, a writer that researches (D-89, proposed 2026-11-04, awaiting the maintainer)

> **Trigger: the P67-5 real run** (Tack task `4C9BAB`, docket task `task-52c89dbb-2eb6`, pod `web-research`, Haiku
> 5.5, 2026-11-04): the web worked (no `fetch` refused), and the task ended `failed` with no report, after 445,209
> input and 29,432 output tokens. Three independent defects, each reproduced; the investigation, the
> reproductions and the options are in `internal-docs/audits/corrida-real-investigacion-2026-11-04.es.md`.
>
> 1. **A compaction that gains nothing kills the hop.** The writer's pre-turn compaction (history budget 6,000,
>    its `token_budget`) ran five summary calls and failed `compaction summary did not reduce estimated history size
>    (45271 -> 45272)`. Replayed offline on the session's copy: four of its 13 units (an `assistant` with 3-4
>    parallel `fetch` results) weigh 7,003-8,371 estimated tokens, more than the 6,000-token summary prompt; once a
>    summary sits in front, the batch is that summary alone, which cannot shrink. A `fetch` result alone reaches
>    `DOCKET_TOOL_MAX_OUTPUT_CHARS` (30,000 chars, about 7,500 tokens). The request fitted the window (`request_fit
>    fits`, 28,041 measured tokens of 200k). Conforms to `session-history` requirements 24 and 26, so the spec moves.
> 2. **`high-risk-payment` parks a report that mentions payments.** `render_tool_call` JSON-encodes the file into one
>    line, so `payment.*charge` and `refund.*amount` span the whole file, and the free-text clause reads `write`
>    content, which moves no money. Measured with the real engine: six ordinary report sentences park, a bare price
>    passes. `block-destructive`'s `drop table` clause has the same shape.
> 3. **The writer researches again.** 23 `fetch` calls (the researcher 13) and 246,954 of the 445,209 input tokens:
>    `fetch` is offered to every member that does not deny it, and the writer denies only `bash`.
>
> **Decisions the plan takes (D-89, `Proposed` until accepted):**
> 1. **Accepted 2026-11-04 by the maintainer.** A unit too large for a summary prompt is summarized from a projection of its tool results (cut, with a visible
>    marker, in the summarizer's prompt only); a batch always holds one raw unit; a pre-turn compaction that the
>    guard refuses (no progress, round cap, irreducible unit) leaves the history unchanged and the turn runs. A
>    summarizer that fails still aborts the turn (agent-loop 36), and request-fit stays the one stop for a request
>    over the window.
> 2. **Accepted 2026-11-04 by the maintainer; shipped as P68-2.** The free-text clause of the `ask` templates is not evaluated on the built-in file tools (`write`, `edit`):
>    a new `when` key `notTool`; and `payment.*charge`-style spans are bounded to one phrase. Relaxing a gate is the
>    maintainer's call; no corpus row is weakened (the payment rows are all commands).
> 3. **Accepted 2026-11-04 by the maintainer.** The `writer` archetype denies `fetch`: it drafts from the analyst's handoff and cites the researcher's URLs,
>    and asks with `consult` when a citation is missing.
> 4. Search ships as a declared service in `web-research` (ADR 0036 decision 13) once the maintainer picks the
>    provider (Brave Search API or Tavily); P67-3 measured that no search site answers `fetch`.
>
> **Not doing:** a summarizer output cap (follow-up with its measurement), the `hosted` history share (Phase 66
> keeps it deferred), per-host approval, re-running the researcher when a question is answered in a later hop (the
> hop that asks is the hop that resumes, by design).
>
> **Waves (by file; Sonnet workers, one integrator):**
>
> | Wave | Cards | File contention resolved |
> | --- | --- | --- |
> | 1 | P68-1 ∥ P68-2 ∥ P68-3 | P68-1 owns `agent/session_compaction.py`, `agent/loop_compaction.py`, `session-history.spec.md`, `agent-loop.spec.md` 37; P68-2 owns `governance/policy.py`, the policy templates, the corpus, `security-gates.spec.md`; P68-3 owns `teams/builtin_roles.py`, `role-archetypes.spec.md` |
> | 2 | P68-4 (when the provider is chosen) ∥ P68-5 | P68-4 owns the `web-research` recipe and `services/`; P68-5 owns `agent/tools/capability_gap.py`, `hops/application/driver_support.py` `pod_offer`, `serve-read-api.spec.md` |
> | 2b | P68-7 | `agent/session.py`, `session-history.spec.md` requirement 30; before P68-6 |
| 3 | P68-6 | the integrator's real run, which also closes P67-5 |
>
> **Against Phase 66:** P68-1 edits `session_compaction.py`, `loop_compaction.py` and `session-history.spec.md`, which
> P66-2, P66-3 and P66-4 also edit. Phase 68 wave 1 goes first (a live defect that fails every long research hop);
> Phase 66 re-checks its locators when it starts.

### P68-1 — A compaction converges on a unit larger than its prompt, and never kills a turn that fits

**Status:** DONE 2026-11-04 (`262f0cc8`; D-89 choice 1; gate green: `test_session_compaction.py`, `test_loop_compaction.py`, tests/integration/agent -k compact, architecture, validate-specs; the real writer session replayed offline converges in 10 rounds, every prompt under 6,000 estimated tokens; session-history 1.13.0, agent-loop 4.6.0) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** —

- **Trigger:** decision 1's reproduction (`scratchpad` replay of the writer session: rounds 1-3 reduce, round 4
  summarizes a lone summary, `45650 -> 45650`, `ok=False`).
- **Goal:**
  - `_bounded_summary_batch` (`agent/session_compaction.py` ~68) and `_summarization_message` (~38): a unit whose
    prompt does not fit is rendered with each tool result cut to its share of the input budget and the marker
    `[... <n> characters of this tool result not shown to the summarizer ...]`; the batch never consists of
    compaction summaries only (a summary rides with the next raw unit, projected when needed).
  - `_run_compaction_rounds` (~162) keeps failing closed (no write) when even the projection cannot fit or a round
    still gains nothing; the `CompactionResult` names that case (a typed field, not a string match).
  - `apply_initial_history_compaction` (`agent/loop_compaction.py` ~245): a result refused by that guard does not
    end the turn; the turn runs on the stored history and the `session_compaction` event says `failed` with the
    reason. Requirement 36's summarizer failures, cancellation and `token_budget` stop the turn as today.
- **Non-goals:** a cap on the summary's length; the `hosted` share; request-fit (`reduce_for_fit`, P66-2).
- **Change:** the two modules; `session-history.spec.md` requirements 24 and 26 (version bump); `agent-loop.spec.md`
  requirement 37; tests `tests/unit/agent/test_session_compaction.py`, `tests/unit/agent/test_loop_compaction.py`,
  and a synthetic fixture under `tests/fixtures/` with the measured shape (13 units, four of 7,000-8,400 estimated
  tokens made of 3-4 tool results, filler text only, never the live session's content).
- **Acceptance (RED first):**
  - Unit: the fixture through `compact_session` with budget and input budget 6,000 and a fake summarizer returning
    1,000 tokens: `ok`, `compacted`, every raw unit folded, `after_estimated_tokens < before_estimated_tokens`, and
    no summarizer prompt made of compaction summaries alone. Oracle: today `ok=False`, "did not reduce".
  - Unit: a single `user` message larger than the input budget still fails closed and the stored record is
    byte-identical.
  - Unit (loop): a pre-turn compaction refused by the guard leaves `session.json` unchanged, the turn reaches the
    model, and the trace carries `session_compaction status=failed`; a summarizer timeout still ends the turn
    `compaction_failed`.
- **Gate:** the two unit files (seconds); `tests/architecture`; `validate-specs.sh`; `comment_lint.py --check`.

### P68-2 — A file that mentions payments is not a payment

**Status:** DONE 2026-11-04 (D-89 choice 2 accepted by the maintainer the same day; gate green: `test_policy.py` (`TestAFileIsNotAnAction`, `TestNotToolValidation`), `test_policy__corpus.py`, the governance unit and integration files, `tests/architecture`, goldens, `validate-specs.sh`; security-gates 3.16.0. The write/edit cases are unit tests, not corpus rows: the corpus is a measured table of `bash` calls) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + data · **After:** —

- **Trigger:** decision 2's probe: with the shipped template, `write` of "La app cobra con Stripe.", of
  "Payment …(400 words)… No extra charge", of "Refund policy … The amount of stories", of "pays a payout", of
  "Payment is optional; … free of charge" and of "Payment model … recharge" all `require_approval`; "Calm cuesta
  69.99 USD al año" passes. Live: the P67-5 writer's report parked.
- **Goal:**
  - `when` gains `notTool` (a list of tool names; the predicate is false when the call's tool is one of them),
    validated with the other keys (`governance/policy.py` `_WHEN_PREDICATE_KEYS` ~51, `validate` ~82,
    `_predicate_matches` ~466).
  - `templates/policies/high-risk-payment.yaml` and `block-destructive.yaml`: the `matches` item carries
    `notTool: [write, edit]`; the payment spans become one-phrase proximity (`payment\W+(?:\w+\W+){0,4}charge` and
    the same for `refund…amount`, `crypto…send`, `btc/eth…send`).
- **Non-goals:** the `when.command` rules and `HIGH_RISK_PATTERNS` (unchanged); MCP and `svc__` tools keep the
  free-text clause.
- **Change:** `governance/policy.py`, the two templates, `tests/fixtures/policy-corpus/corpus.yaml`,
  `tests/unit/governance/test_policy.py`, `tests/unit/governance/test_policy__corpus.py`; `security-gates.spec.md`
  (the `when` grammar, requirement 8, its known limits).
- **Acceptance (RED first):** corpus rows: the six sentences above as `write` → `allowed`; `curl
  https://api.stripe.com/v1/charges …` → still `ask`; a `mcp__pay__charge` call whose arguments say "charge
  customer" → still `ask`; `edit` of a migration containing `DROP TABLE` → `allowed`; `bash -c "psql -c 'drop
  table x'"` → still `ask`. Unit: `notTool` with a non-list value is refused by validation naming `notTool`.
- **Gate:** the corpus test and `test_policy.py`; `tests/architecture`; `validate-specs.sh`; `comment_lint.py
  --check`.

### P68-3 — The writer drafts from the handoff; it does not research again

**Status:** DONE 2026-11-04 (`b4d62ffb`; D-89 choice 3; role-archetypes 5.10.0; `pod-reach.json` and `pod-fetch.json` re-recorded from a real server; an existing pod keeps its stored role copy, so `web-research` takes the denial only when reapplied) · **Size:** S · **Model:** Sonnet · **Kind:** data + spec · **After:** —

- **Trigger:** decision 3's measurement (writer 23 `fetch`, 246,954 input tokens of 445,209).
- **Goal:** the `writer` archetype's `denied_tools` becomes `("bash", "fetch")` (`teams/builtin_roles.py` ~180);
  its `SOUL.md` sentence about its tools follows.
- **Non-goals:** the researcher, analyst, lead and reviewer keep `fetch`; the `respond` pipeline is unchanged.
- **Change:** `teams/builtin_roles.py`; `role-archetypes.spec.md` requirement 8 (the writer's tool list);
  `tests/unit/teams/test_builtin_roles.py`; the operator-v2 fixtures whose writer capabilities list `fetch`
  (`pod-reach.json`, `pod-fetch.json`; `pod-web-read.json` shows only the researcher), re-recorded with
  `OPERATOR_RECORD_DIR` from a real server.
- **Acceptance (RED first):** `member_capabilities(<respond pod under the jail>, "writer")["tools"]` lacks `fetch`
  while `"researcher"` keeps it; `capability_missing` for a writer's `fetch` names the role's denial, not a host.
- **Gate:** `test_builtin_roles.py`, `tests/integration/teams/test_fetch_reach.py`, the fixture tests;
  `validate-specs.sh`; the e2e lane (42 s: a tool set changes).

### P68-4 — A research team searches through a declared service

**Status:** TODO (measured 2026-11-04, `internal-docs/baselines/phase-68/search.md`; the provider is the maintainer's yes: a local SearXNG is recommended, Brave Search API the fallback) · **Size:** M · **Model:** Sonnet · **Kind:** data + docs + measurement · **After:** —

- **Trigger:** P67-3 (`internal-docs/baselines/phase-67/search.md`): DuckDuckGo html and lite answer a challenge to
  20 of 20 queries, Bing returns links unrelated to the query; the P67-5 run's two Bing searches returned
  WhatsApp and Ualá for a question on bedtime-story apps.
- **Measured (the same 20 queries, 5 s apart, no tokens):** a local SearXNG (Docker, `127.0.0.1:8888`, JSON on):
  20 of 20 with 38-55 results, 0 errors, and a competitor, comparison or pricing page among the first three results
  of every query, English and Spanish (engines: `google cse`, `duckduckgo`, `brave`). Marginalia's public API: 1 of 20
  (17 timeouts). Not measured: a burst or a week of use (upstream engines throttle heavy use).
- **Provider constraint (service-client requirements 10-11):** an operation's access is `read` for `GET` and
  `send` for every other method, and a role that names a `send` tool cannot hold `fetch` (ADR 0036 decision 2).
  SearXNG's and Brave's search are a `GET`, so the operation is `read` and the researcher keeps `fetch`; Tavily's
  search is a `POST`, so it would be `send`.
- **Goal:** `services/search.yaml` in the `web-research` recipe (`kind: service`, ADR 0036 decision 13): `baseUrl`
  `http://127.0.0.1:8888`, `hosts: [127.0.0.1]` (a loopback host must be listed, service-client requirement 29; the
  call is docket's own, so a jail with network `none` reaches it), one `GET /search` operation with `q` and
  `format=json`, access `read`. The recipe README says how to run it: the `docker run` line and the two lines of
  `settings.yml` (`search.formats: [html, json]`, `server.limiter: false`), once per machine; with Brave instead, the
  `baseUrl`, the `X-Subscription-Token` header from the home's secret store and the same operation. `needs.SEARCH_HOSTS`
  stops promising a search site, so `search-host` is satisfied by the service only. Then the 20 queries again through
  the declared service (not through urllib), spaced 5 s, judged by reading.
- **Non-goals:** docket starting or supervising the container; a native search tool (ADR 0034, ADR 0036 decision 17).
- **Change:** the recipe directory, `teams/apply/needs.py` (`SEARCH_HOSTS`, `_search_line`), `pod-blueprints.spec.md`
  requirement 16, `tests/integration/teams/test_recipe_needs.py`, `docs/recipes.md` (generated).
- **Acceptance:** with a stub service, `init --recipe web-research` reports `search-host` ready only once the service
  resolves; under open read without the service, `search-host` is not satisfied (today it is, by the `*` reach). The
  measurement: at least 18 of 20 queries with five relevant links through the service, judged by reading.
- **Gate:** the recipe tests; `validate-specs.sh`; `gen_recipe_docs.py --check`; the measurement spends no model
  tokens.

### P68-5 — The fix docket names for a missing `fetch` is the one that opens it

**Status:** DONE 2026-11-04 (`1617bd38`; agent-loop 4.7.0, serve-read-api 6.5.0; the `features` list in serve-read-api now points at `FEATURES` and its exact-list test) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P68-1

- **Trigger:** `agent/tools/capability_gap.py` ~56 always says `docket pod set fetchDomains <host>`; for a folder pod
  whose jail is off the fix is `docket setup sandbox on` (`network_posture.fetch_reach`'s `fix`). Found in P67-2.
- **Goal:** `PodOffer` gains `fetch_fix` (`hops/application/driver_support.py` `pod_offer` ~170 fills it from
  `fetch_reach(project).fix`); `gap_for` uses it. `serve-read-api.spec.md`'s `features` list (stale since
  `consultParts`) is replaced by a pointer to `FEATURES` and its exact-list test.
- **Change:** `capability_gap.py`, `driver_support.py`, `serve-read-api.spec.md`, `agent-loop.spec.md` requirement
  113; `tests/unit/agent/tools/test_registry__dispatch.py`.
- **Acceptance (RED first):** a folder pod without the jail: the gap's fix is `run \`docket setup sandbox on\``; a
  repository pod: unchanged. Oracle: today both name `pod set fetchDomains`.
- **Gate:** the unit file; `tests/architecture`; `validate-specs.sh`.

### P68-6 — The research task again, through to a report with sources

**Status:** TODO (P68-1, P68-2, P68-3 and P68-5 done and installed; P68-7 first; needs `web-research` reapplied from the app's `onboard/tack`, so its writer loses `fetch`, and the maintainer's go in Tack's session) · **Size:** M · **Model:** Opus (integrator) · **Kind:** real run

- **Goal:** P67-5's acceptance, on the installed build (`./install.sh`, service restarted), the user's go given in
  Tack's session: Tack task `4C9BAB` from **Run again**, nobody writing `fetchDomains`.
- **Acceptance:** the task ends `done` with a report in the workdir citing at least three distinct public hosts;
  no `session_compaction status=failed` ends a hop; no `write` of the report parks on a payment policy; the writer
  makes no `fetch`; input tokens reported against this run's 445,209 (never dollars). Evidence to
  `internal-docs/baselines/phase-68/`. Closes P67-5.
- **Gate:** the phase-close list; the full suite once at the last merge.

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

**Status:** TODO (after P68-1: both amend `agent-loop.spec.md`) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P68-1

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

**Status:** TODO (after P68-1: both edit `session_compaction.py` and `session-history.spec.md`) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + data · **After:** P68-1

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


## ▶ PHASE 67 ACTIVE — a research team reads the web without anyone writing it a host list (D-88, accepted 2026-11-04)

> **Trigger (the maintainer's request, with a reproduction).** Tack task `4C9BAB` ("Anliza app similares",
> team `web-research`) has ended **Not started** eight times: Tack's `NoWeb` gate reads `network: none` and no
> member holding `fetch` (`GET /pods/web-research`: `fetchDomains: []`, `network.enforced: true`,
> `workspaceKind: workdir`, `needs: []`). The 2026-11-03 answer (per-pod `fetchDomains`, ADR 0036 decision 17)
> asks someone to know in advance which hosts a research task will read: dozens per task, different each
> time; the onboarding skill cannot write `*` and never wrote a list, so every research team is born unable
> to research. Design and reasoning: `internal-docs/design/research-web-access-2026-11-04.es.md`.
>
> **Decisions (D-88; ADR 0036 decision 17 amended, no new ADR):**
> 1. **Open read by shape, not by list.** A member's `fetch` reaches any public host, with no grant, when
>    its pod works in a folder (`workspaceKind: workdir`), the jail is enforced (`jail_enforces()`), and
>    the pod declares no `fetchDomains`. The reason is the rule of two (Willison's lethal trifecta, Meta's
>    Agents Rule of Two): web content is untrusted and a GET can leak in its URL, so the safe posture removes
>    private data from reach. A folder pod has no repository, and the jail keeps `bash` off the rest of the
>    host. A role that holds a `send` tool already cannot hold `fetch` (`check.send_conflicts` at apply,
>    `registry_for_role`'s allow-list at run time); open read changes neither.
> 2. **Every other pod keeps today's rules.** A repository pod, a pod without an enforced jail, or a pod
>    that declares `fetchDomains` reads only its list; `*` stays `--widen` only. A declared list narrows a
>    folder pod (the operator's choice wins); `deniedTools: fetch` turns the web off.
> 3. **One precondition for the web and for PDFs.** P61-8/P62-1 read a PDF only inside the jail; open read
>    needs the same jail. On a folder pod, `docket setup sandbox on` is the single command that gives a
>    research team both, and the `fetch-hosts` need says so instead of asking for hosts.
> 4. **docket owns the sentence Tack shows.** The pod report says how the pod reads the web (`webRead`:
>    mode, reason, fix) and whether each unmet need blocks the work or only degrades it (`blocking`).
>    Tack quotes docket's fix instead of spelling docket commands in Rust, and refuses a run only on a
>    blocking need. Additive on API 6, announced as the feature `webRead`.
> 5. **Search is measured before anything ships.** Open read reaches `html.duckduckgo.com`, but search
>    sites block bots; a search API as a declared service (ADR 0036 decision 13) ships only if the
>    measurement says the HTML site fails.
>
> **Residual risk, said in the specs:** an injected page can make the agent put the task text, the pod's
> memory or its folder's files into a GET URL. For a folder pod that is the research itself, not code or
> secrets; it is the risk every deep-research tool accepts. Not tamper-proof wording; "enforcement covers the
> tool calls docket dispatches".
>
> **Not doing:** per-host approval during a task (a human bottleneck that does not lower the risk); opening the
> jail's network to research (it also opens `bash`, `run:` and MCP); open read without an enforced jail
> (`bash` would read the whole host); a browser, POST or headers on `fetch` (ADR 0036 "Not doing").
>
> **Waves (by file; Sonnet workers, one integrator):**
>
> | Wave | Cards | File contention resolved |
> | --- | --- | --- |
> | 1 | P67-1 ∥ P67-3 | P67-1 owns `network_posture.py`, `builtin_tools.py`, `capabilities.py`, `security-gates.spec.md`, `agent-loop.spec.md` requirement 83 and ADR 0036; P67-3 edits no `src/` and no spec |
> | 2 | P67-2 | `needs.py`, `report.py`, `pod_provisioning.py`, `health.py`, `operator-api.spec.md`, `pod-blueprints.spec.md`, the operator-v2 fixtures; needs P67-1's reader |
> | 3 | P67-4, then P67-5 | P67-4 is prose only; P67-5 is the integrator's real run with Tack |
>
> **Against Phase 66:** P67-1 amends `agent-loop.spec.md` (requirement 83), which P66-1, P66-2 and P66-6 also
> amend; if both phases run at once the integrator applies the spec hunks at merge. No `src/` file is shared.
> **Tack's side** (another repository, its own session): the prompt in
> `internal-docs/plans/tack-research-web-2026-11-04.md`; it waits for P67-2's fixtures.

### P67-1 — A folder pod under an enforced jail reads any public host

**Status:** DONE 2026-11-04 (uncommitted; gate green: `test_fetch_reach.py` 6 tests, `test_network_posture.py`, architecture, e2e lane, `validate-specs.sh`, `comment_lint.py`; security-gates 3.15.0, agent-loop 4.5.0, ADR 0036 decision 17 amended; the machine's own list counts as declared, so open read needs both empty) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** —

- **Trigger:** the reproduction above: `web-research` meets every condition of decision 1 and its members
  hold no `fetch`, because `_offered_fetch` (`hops/application/builtin_tools.py` ~550) offers `fetch` only when
  `effective_fetch_domains` (`teams/pod_settings.py` ~735) is non-empty, and that list is the machine's plus
  the pod's declared hosts.
- **Goal (decisions 1-2):**
  - `teams/network_posture.py` (58 lines; already imports `pod_settings` and has `jail_enforces`) gains
    `fetch_reach(project) -> FetchReach(hosts, mode, reason, fix)`. `mode` is `open` (decision 1's three
    conditions; `hosts == ("*",)`), `listed` (declared or machine hosts; `any` when the `--widen` grant is
    recorded) or `none`. `reason` is one sentence ("a folder team under the jail reads any public host");
    `fix` is the one command that opens it when `mode` is `none`: `docket setup sandbox on` (or the backend
    choice, as `needs._isolation_line` words it) on a folder pod, `docket pod set fetchDomains <host> --pod
    <pod>` on a repository pod.
  - The three readers switch to it: `_offered_fetch`, `member_capabilities` (`hops/application/capabilities.py`
    ~33, `fetchDomains` stays the served key and serves `["*"]` under open read) and the fetch handler's
    allowed set (the same `_offered_fetch` call). `effective_fetch_domains` stays as the declared part that
    `fetch_reach` reads; `needs.readiness` keeps calling it until P67-2.
  - `fetch`'s perimeter is unchanged: `*` is not an exact host, so private addresses stay refused
    (`platform/fetch.py` `_exact_hosts` ~216, `platform/perimeter.py` ~69), and credentials in a URL too.
- **Non-goals:** the pod report's `webRead`, the needs, `blocking` (P67-2); search (P67-3); the hop message's
  `Web:` line, which already words `*` as any public host (`hops/application/compose.py` ~175).
- **Change:** `teams/network_posture.py`, `hops/application/builtin_tools.py`, `hops/application/capabilities.py`;
  tests `tests/integration/teams/test_fetch_reach.py` (new), `tests/unit/teams/test_network_posture.py`.
  Spec: `security-gates.spec.md` "Network egress and the fetch allowlist" (~1125-1150) and the default-install
  requirement (~1905: "a default install MUST leave `fetch`..." gains the open-read case); `agent-loop.spec.md`
  requirement 83 (~771); ADR 0036 decision 17 amended in place (its "`*` alone ... only through `--widen`"
  becomes "only through `--widen`, or open read on a folder pod under the jail").
- **Acceptance (RED first):** each with the jail bound the way `00825233` binds it (record isolation on and stub
  the backend probe), never the host's real backend.
  - Integration: a `respond` folder pod, jail enforced, no `fetchDomains`: `member_capabilities(pod,
    "researcher")["tools"]` contains `fetch` and `fetchDomains == ["*"]`; the fetch tool built for that
    member accepts `https://example.org/` at the host check and still refuses `http://127.0.0.1/`. Oracle:
    today `tools` lacks `fetch`.
  - Integration: the same pod's `actor` (the `send` role of `respond`) has no `fetch`.
  - Integration: the same pod with isolation recorded off, a `codebase` pod with the jail on, and a folder pod
    declaring `fetchDomains: docs.python.org` give, in order, no `fetch`, no `fetch`, and `["docs.python.org"]`.
  - Unit: `fetch_reach` returns each `mode` with the `fix` named above; `deniedTools: fetch` leaves `mode`
    computed but `tools` without `fetch`.
- **Gate:** the two test files (under 10 s); `tests/architecture` (3 s); the e2e lane (42 s: the tool set
  changes); `bash scripts/validate-specs.sh`; `scripts/maint/comment_lint.py --check` on touched files.

### P67-2 — The pod says how it reads the web, and which unmet need blocks the work

**Status:** DONE 2026-11-04 (uncommitted; gate green: test_researcher_needs_web, test_recipe_needs, test_report, test_health, serve_pods_config/endpoint with fixtures re-recorded from a real server (pod-fetch, pod-reach, pod-contract) and pod-web-read added, architecture, e2e lane, goldens, `validate-specs.sh`, `gen_cli_docs --check`, comment_lint; operator-api 7.29.0, pod-blueprints 4.9.0, cli-json-shapes 5.7.0; `webRead.mode` is `open|listed|none`, a `--widen` grant is `listed`; `search-host` reads satisfied under open read although P67-3 measured search as unusable) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + wire · **After:** P67-1 (`fetch_reach`)

- **Trigger:** Tack's `team_misfits` (Tack's repository, `crates/tack-protocol/src/execution/capabilities.rs`
  ~490-535) refuses a run on **every** unsatisfied need but `model`, and spells docket's fix itself for
  `NoWeb` (`crates/tack-runner/src/harness/docket.rs` ~214). A pod that records `isolation` or `search-host`
  would then be refused for something that only degrades it, and Tack's sentence names `fetchDomains` where
  the fix for a folder pod is the jail.
- **Goal (decisions 3-4):**
  - `GET /pods/<p>` and `docket pod show --json` carry `webRead: {mode, reason, fix}` from `fetch_reach`
    (`hops/application/report.py`, beside `network` ~613/653); `pod show` prints `Web: <reason>` and, when
    `mode` is `none`, `-> <fix>`.
  - `NeedLine` (`teams/apply/needs.py` ~26) gains `blocking: bool` on the wire: `fetch-hosts` blocks;
    `search-host` and `isolation` degrade (the agent can still read pages it knows, and every format but
    PDF). `_fetch_line` reads `fetch_reach`: satisfied under `open` or `listed`, and its `fix` is
    `fetch_reach`'s. `_isolation_line`'s text says what it opens: "PDFs, and the web on a folder team".
  - `record_reading_needs` (`teams/pod_provisioning.py` ~391) records `fetch-hosts`, `search-host` and
    `isolation` for a pod with a `researcher`, the same three `web-research` declares.
  - `FEATURES` (`interfaces/http/routes/health.py` ~21) gains `webRead`; the operator-v2 fixtures
    `pod-fetch.json` and `pod-reach.json` are re-recorded and `pod-web-read.json` added (a folder pod under
    the jail, open read, three satisfied needs), captured from a real throwaway docket as P61 did.
- **Non-goals:** Tack's code (its prompt is the plan file above); search (P67-3); a `blocking` per pod.
- **Change:** `hops/application/report.py`, `teams/apply/needs.py`, `teams/pod_provisioning.py`,
  `interfaces/http/routes/health.py`, `interfaces/cli/render/apply.py` (the `pod show` line); fixtures under
  `tests/fixtures/operator-v2/`; tests `tests/integration/teams/test_researcher_needs_web.py` (extend),
  `tests/unit/hops/application/test_report.py`. Spec: `operator-api.spec.md` "Pod answers" (~434-502) and the
  features list; `pod-blueprints.spec.md` requirement 16 (~512-550); `cli-json-shapes` for `needs`.
- **Acceptance (RED first):**
  - Integration: the P67-1 folder pod reports `webRead.mode == "open"` and `needs` with three entries, all
    `satisfied`, `fetch-hosts` `blocking: true`. Oracle: today `needs` holds one unsatisfied `fetch-hosts`.
  - Integration: the same pod with isolation off reports `webRead.mode == "none"`, `fix == "docket setup
    sandbox on"`, `fetch-hosts` unsatisfied and blocking with that fix, `isolation` unsatisfied and not blocking.
  - Integration: a repository pod with a researcher and no list: `fetch-hosts` fix names `pod set fetchDomains`.
  - The exact-list `FEATURES` test lists `webRead`; the three fixtures parse with the operator-v2 schema test.
- **Gate:** the two test files; `tests/architecture`; the e2e lane (42 s: the HTTP API changes);
  `validate-specs.sh`; `comment_lint.py --check`.

### P67-3 — Measure whether a research team can search, before anything ships for it

**Status:** DONE 2026-11-04, `internal-docs/baselines/phase-67/search.md`. DuckDuckGo html and lite: 20/20 challenge pages (HTTP 202); Bing: 10 links for 20/20 queries but unrelated to the query (mattress shops, Epic Games, "File Explorer" for "Speakaboos pricing"), one URL-parameter fix tried and failed. The 18-of-20 rule counts links, not relevance, so it is not read as a pass: the second branch applies, a follow-up card for `services/search.yaml`, **provider chosen by the maintainer** · **Size:** S · **Model:** Sonnet · **Kind:** measurement, then a decision · **After:** —

- **Trigger:** `needs.SEARCH_HOSTS` (`teams/apply/needs.py` ~23) assumes `html.duckduckgo.com` answers a
  GET from docket's `fetch`; nobody has measured it. Search sites rate-limit and challenge bots.
- **Goal:** a throwaway script (not kept in `scripts/maint/`; one fix at most) sends 20 fixed research queries
  (Spanish and English, from the real task: apps similar to the product, bedtime-story apps, pricing pages) through
  `platform.fetch.fetch_url` with `*` to `html.duckduckgo.com`, `lite.duckduckgo.com` and `www.bing.com`, one
  run, spaced 5 s. Per host: answers with at least five result links, challenge or captcha pages, errors.
  Results to `internal-docs/baselines/phase-67/search.md`.
- **Decision it fires:** if a host returns results for at least 18 of 20, that host is the documented search
  and nothing ships. If none does, a follow-up card ships `services/search.yaml` in the `web-research` recipe
  (declared service, ADR 0036 decision 13; Brave Search API or Tavily, the key in the home's secret store,
  set once per machine), and the measurement is repeated through it. Choosing the provider is the maintainer's.
- **Non-goals:** a native search tool (refused by ADR 0034 and ADR 0036 decision 17); any `src/` change.
- **Gate:** none beyond the script running; no tokens are spent (no model call).

### P67-4 — The prose says what a research team can read

**Status:** DONE 2026-11-04 (uncommitted; README names the changed sentence per D-37) · **Size:** S · **Model:** Haiku · **Kind:** docs · **After:** P67-1, P67-2

- **Goal:** every user-facing sentence about `fetch` being off by default gains the open-read case, quoting
  the spec, not paraphrasing it: `README.md` (rg `deny-by-default`), `docs/CONFIGURATION.md`,
  `src/docket/templates/recipes/web-research/README.md` (a folder team needs only isolation, a repository team
  needs hosts), the `fetch-hosts` follow-up in this board's "Phases 63-64" list (rewritten: it was the
  decision of 2026-11-04 morning and D-88 replaced it), `CHANGELOG.md`. The README sentence is named in the
  commit body (D-37).
- **Gate:** `uv run python scripts/gen_cli_docs.py --check`; `comment_lint.py --check`; the README prose tests
  (`tests/agent/`, the false-claim checks only).

### P67-5 — The real run: Tack's research task reaches docket and comes back with sources

**Status:** RAN 2026-11-04, acceptance NOT met: the web worked (no `fetch` refused, `webRead` open in Tack) and the task ended `failed` in the writer hop on a compaction defect, with no report; evidence `internal-docs/baselines/phase-67/real-run.md`. Re-run as P68-6 after Phase 68 wave 1 · **Size:** M · **Model:** Opus (integrator) · **Kind:** real run

- **Goal:** with the build installed (`./install.sh`, then `~/.local/bin/docket start ...` restarted), the
  live `web-research` pod reapplied from the app's repository, branch `onboard/tack` (its `configSource` today is
  a scratchpad copy under `/tmp`), isolation on, **no `fetchDomains` set by anyone**, Tack task `4C9BAB` runs
  from **Run again**.
- **Acceptance:** the task is sent (no "Not sent to docket"); the trace shows `fetch` calls to at least three
  distinct public hosts and none refused for its host; a PDF among them, if the research reaches one, is read
  as text; the Reviewer's gate passes on cited sources; Tack's Teams screen shows docket's `webRead.reason`.
  Tokens spent are reported, never dollars. Evidence to `internal-docs/baselines/phase-67/`.
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

**Phase 68 (2026-11-04).** Left out of the cards on purpose, or found while merging:
- *A turn that continues after a refused pre-turn compaction is tested at the unit, not through the model.*
  `test_loop_compaction.py` asserts `apply_initial_history_compaction() is None` and the `failed` event; an
  integration test that runs `run_agent_turn` to the model after a refusal is cheap. Trigger: any later
  edit of `loop_compaction.py` (Phase 66).
- *Converging on the real writer session takes 10 summarizer rounds* (4 more than the run that failed). A cap on
  the summary's length would cut it; measure it with the next real run (P68-6) before adding one.
- *`loop_trace.py` `_trace_compaction` gained a `reason` key* (guard refusals only); Phase 66 cards P66-3 and P66-4
  that touch that file re-check their locators.
- *`comment_lint` flags `_resolve_roots` and `_loop_config`* (`hops/application/driver_support.py`) as
  `long-def-doc`, and six docstrings in `governance/policy.py`; none new.

- *A turn that reads many pages can run out of its token budget before its landing fits.* A throwaway run's
  researcher used 86,021 of `token_budget=100000` in 8 model calls (39 `fetch`) and ended `cannot start terminal
  finalization ... estimated input 22406 + output reserve 8192, remaining 13979`, losing everything it read
  (`agent/loop_budget.py` `prospective_budget_error` ~139, `agent/loop.py` `enter_landing` ~373). Probably the
  re-fetching P68-7 removes; trigger: a researcher turn still ends this way after P68-7, then reserve the
  landing's input before a tool round starts.
- *`docket init <pod> --blueprint respond` prints `needs fetch-hosts ... -> docket setup sandbox on` and then
  records isolation on* (a throwaway home, 2026-11-04): `pod show` says the web is open right after. The line is
  printed before the jail is recorded; pod-blueprints requirement 16 says it is printed after. Check the order in
  `interfaces/cli/commands/` init.
- *A pod made with `docket init <name> --blueprint respond` from inside a repository takes that directory as its
  folder* (the throwaway run's writer wrote `informe.md` into the working tree). Probably as designed (`location`
  defaults to the current directory); say so in `init --help`, or refuse a folder inside a git repository.

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
  a real task's requests. **FIRED 2026-11-04:** the P67-5 task (`task-52c89dbb`, raw trace under
  `state/traces/web-research/`) has `cacheMiss: messages_changed` on 16 of its 30 `llm_call`s (53 %); the writer's
  requests of 19-28k tokens cached only the 2,854-token prefix. Belongs with Phase 66 (D-87), which owns the
  request projection.
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
  - P55-8: the check and the increment of a quota are not atomic (two concurrent sends in one pod could both pass at
    count-1); an unreadable counter counts as empty; `pod policies` and `check` do not show quotas.
  - Phase 56 Wave 2 merge run (2026-10-30), both passed alone: `test_consult_wait.py::TestAnsweredInPlace::
    test_a_decline_tells_the_model_to_decide_itself` (a third test of that class, so the class now has three flakes
    under load: that is its trigger), and `tests/integration/product/test_runtime_execution_envelope.py`, 8 setup
    errors from `uv build` exiting 2 in a parallel worker.
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
  **FIRED 2026-11-04:** the P67-5 writer parked on a question and resumed with 21,642 input tokens, 0 cached
  (21:41:43 UTC); its second resume, after the approval, died in compaction (P68-1).
- **A hop refused before any call records an empty model** (`hop_finished.model == ""`, a `""` key in
  `usage.byModel`). Trigger: a reader of `byModel` that trips on it.
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

- **Parallel tasks in a pod:** ADR 0027 point 10 holds the trigger; a card would add a
  `maxParallelTasks` pod setting and a bounded pool in dispatch.

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

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
