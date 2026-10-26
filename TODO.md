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
> **Active: none.** Phase 51 closed 2026-10-25 (D-72, [ADR 0032](docs/adr/0032-one-escalation-record-and-one-resolve.md),
> ROADMAP §6); its loose ends are under "Escalations" in the follow-ups below. A new phase starts
> from a measured trigger or a maintainer request. The integration branch is
> `plan/phase-46-structure` until the maintainer merges it.
> **Planned: Phase 52** (D-73, [ADR 0033](docs/adr/0033-the-harness-adapts-to-the-model-by-data.md);
> D-74, [ADR 0034](docs/adr/0034-the-turn-owns-its-processes-and-its-time.md)), twelve cards cut by
> file ownership over four waves.

## ○ PHASE 52 PLANNED — the harness adapts to the model by data, and pays for context once (D-73, ADR 0033); the turn owns its processes and its time (D-74, ADR 0034)

> Planned 2026-10-25 by the maintainer from a code audit against a harness-engineering survey
> ([ADR 0033](docs/adr/0033-the-harness-adapts-to-the-model-by-data.md) holds the findings and the
> refusals). Cards are cut by **file ownership**, not by technique: everything one worker would
> change in the same files is one card, so no file is edited twice in the same wave. Wave A may
> start beside Phase 51's remaining cards: no Wave A or B card edits `hops/application/dispatch*`,
> `tasks/`, `operator/` or `interfaces/http/` (P52-1 writes only `observability/`; `/metrics`
> reads the fold). P52-9 to P52-12 were added the same day from a second reading
> ([ADR 0034](docs/adr/0034-the-turn-owns-its-processes-and-its-time.md): a tool's clock, background
> processes, `fetch`, search, machine waits). They continue files Waves A and B own, so they run as
> Waves C and D; the exception is P52-11, whose files nobody in Wave A touches. P52-12 (the fourth
> proposal, search) is folded into P52-6: same owner, same files.

### How a Phase 52 card runs (read before claiming one)

- Spec → failing test → smallest change. Bump the owning spec (MINOR) with `Last Updated` and the
  `specs/README.md` row in the same commit.
- **Read bounded, to spend little:** `card_packet.py P52-<n>`, ADR 0033 §"Decision" (one screen),
  the spec section the card names, the files it names. Nothing else: not the ADR's findings, not
  another card, not a spec directory. A worktree has no `internal-docs/`.
- **Measure with what exists, free first.** The replay bench
  (`scripts/maint/context_replay.py tests/fixtures/context-replay --policy <name>`) costs nothing
  and is the oracle for bytes and counted tokens; a card that changes what the model sees adds its
  `--policy` and reports the table before/after. The live eval (`scripts/maint/live_eval.py -n 3`,
  local endpoint, `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`) runs **once per wave by the integrator**, not
  per card; the remote provider once at the phase close, after a go.
- **Every card:** focused tests by path under `timeout 120`; before handoff `ruff`, `mypy src`,
  `pytest --co -q`, `tests/architecture`, `comment_lint.py --check` on touched files. The e2e lane
  only on cards that change a tool's output or the wire (P52-2, P52-3, P52-7, P52-8, P52-10,
  P52-11).
- **Spend by model.** Haiku runs the data card (P52-6) and, on any card, the spec and doc edits the
  card spells out; Sonnet runs behaviour in `src/`; no Opus on this phase. A worker opens only the
  files its card names (no card names more than eight) and the one spec section it names; a card
  that turns out to need more parks with the missing locator instead of exploring. Every card's
  trigger carries its line numbers so the worker greps, never reads a module whole.
- **Integrator seams:** P52-2 and P52-3 both bump `agent-loop.spec.md`; the integrator renumbers at
  merge (as in Phase 44). The full default suite runs once per merge, `--lf` after.
- Workers in `.claude/worktrees/p52-<n>`, one card per worktree. **Model per card** is on the
  card: Sonnet for behaviour in `src/`, Haiku for data-only cards. Delta-only handoff with the
  end-of-work control summary.

**Waves (by file contention)**

| Wave | Cards | Why this order |
| --- | --- | --- |
| A | P52-1 ∥ P52-2 ∥ P52-3 ∥ P52-6 ∥ P52-11 (∥ P52-4 once unblocked) | disjoint owners: `observability/`+bench · `kernel/text.py`+toolbox+`session.py` · request/wire/catalog · recipes · `platform/fetch.py`+`_fetch_tool` · `governance/`; P52-4 and P52-11 share only `security-gates.spec.md` (integrator renumbers) |
| B | P52-5 ∥ P52-7 ∥ P52-8 | P52-5 needs P52-1's re-read figure; P52-7 continues P52-3's files and P52-11's `builtin_tools.py`; P52-8 continues P52-2's files and covers `fetch` results |
| C | P52-9 | continues P52-7's `builtin_tools.py` and `driver.py`; `lifecycle.py` after P51-9 |
| D | P52-10 | continues P52-9's files, P52-8's `toolbox.py` and P52-4's `security.py` |
| — | P52-12 | blocked on a recorded run and on P51-9; no wave until the trigger fires |

### P52-1 — the numbers: cache hits, tokens per accepted task, re-reads

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** observability + script

- **Trigger:** maintainer request (ADR 0033 §Decision 5). No cache-hit ratio exists; `task show`
  prints usage per model but not per accepted task; the Phase 44 follow-up "measure which calls
  repeat before cutting anything" never ran because its measurement was framed as a paid live run.
  The recorded traces already hold the answer.
- **Goal:** three figures, read-only on data docket already records. (1) `cache_hit =
  cachedTokens / inputTokens` on every `llm_call` event and folded per task and per role in the
  metrics fold `observability/` keeps (the `/metrics` route reads it unchanged). (2) `tokens per
  accepted task`: counted tokens of tasks that ended `done`, as a line of `docket log --summary`
  and a metrics key. (3) `context_replay.py --repeats`: per step, the `read`/`grep`/`glob` calls
  whose canonical arguments repeat; per task, the files the Implementer read that the Lead had
  read.
- **Non-goals:** dollars; alerting; any change to what the model sees.
- **Spec:** `trace-store.spec.md` (3.2.0 → 3.3.0: `cache_hit` is derived, not stored);
  `serve-read-api.spec.md` (4.2.0 → 4.3.0: the two metrics keys); `cost-tracking.spec.md` only if
  a sentence there names the per-task figure.
- **Change:** `observability/` metrics fold (one function per figure); `interfaces/cli/commands/log*`
  renders the summary line; `scripts/maint/context_replay.py` gains `--repeats` (a table: step,
  repeated calls, re-read files, bytes they cost at the measured ratio).
- **Acceptance:** fixture `tests/fixtures/traces` (an `llm_call` with `cachedTokens` > 0) →
  `GET /metrics` shows `cacheHit` for that task's role; a task record `done` with usage →
  `docket log --summary` prints `tokens per accepted task`; `context_replay.py
  tests/fixtures/context-replay --repeats` prints a non-empty table and the JSON form lists at least
  one repeated `read` (the committed implementer fixture has one). Oracle: the numbers equal a
  hand-computed value from the fixture, asserted in `tests/unit/observability/` and
  `tests/integration/observability/`. The private replay copies are run by the integrator and the
  figure recorded on P52-5's trigger line.
- **Contention:** `observability/` and the bench script only. Serial with nothing.

### P52-2 — tool results the model can use

**Status:** TODO · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0033 findings, verified 2026-10-25: `kernel/text.py::cut_output` keeps the head
  only; `toolbox.py` merges stderr into stdout (`:419`) and hints only on exit 126 (`:472-473`);
  `edit` says only "not found" (`:188-197`); no ANSI or repeated-line normalization anywhere; the
  condensation window (`agent/session.py:65-69`) lets one 20 KB grep evict a 1.2 KB README that
  is then re-read (Phase 44 close note).
- **Goal, in order (a park leaves the rest visible):**
  1. `cut_output` for `bash` and `verify` keeps head and tail (40/60) with the marker between
     them; `read` keeps head-only (the head is right there).
  2. Lossless normalization before the cut: strip ANSI escapes, resolve `\r` progress lines to
     their last state, collapse consecutive identical lines to `line  [x N]`.
  3. On exit ≠ 0, stderr first, then stdout; a fixed table of known causes: 126 (today's text),
     127 (`not on PATH inside the jail or not in allowCommands`).
  4. `edit` "not found" lists the three closest lines (`difflib`, ratio ≥ 0.6) with "the text
     must match exactly; copy it from `read` without the line-number prefix". Never auto-apply.
  5. Condensation: a tool result under 1,500 chars is never condensed while a larger one in the
     same step is whole (monotone: never condenses more than today).
- **Non-goals:** the artifact store (P52-8); timestamps or pids replaced; any change to `read`'s
  window; a second normalization pass elsewhere.
- **Spec:** `agent-loop.spec.md` (3.2.0 → 3.3.0, tool-output section: head+tail, normalization,
  error order); `session-history.spec.md` (1.9.2 → 1.10.0, the small-results rule beside
  requirement 31).
- **Change:** `kernel/text.py` (`cut_output` gains a `tail` share; a new `normalize_output`),
  `agent/tools/builtins/toolbox.py` (`bash`, `edit`), `hops/application/verify_tool.py`,
  `agent/session.py::condense_history`.
- **Acceptance:** a `bash` whose output is 20 lines of progress + a pytest summary at the tail →
  the result shows the summary after the marker; an output with ANSI colour and 50 identical lines
  → one line with `[x 50]`; `edit` with a near-miss `old_string` → the error names the closest
  line; a step with one 20 KB grep then a 1 KB read → the read survives condensation. Oracles:
  `tests/unit/kernel/test_text.py`, `tests/unit/agent/tools/builtins/`,
  `tests/integration/agent/test_session_condensation*`; the bench `--policy p52-2` reports bytes
  per step before/after on `tests/fixtures/context-replay` (no step worse). Lane e2e green.
- **Contention:** the toolbox, `kernel/text.py`, `session.py`. P52-8 continues these files after
  this merges.

### P52-3 — one request shape: a stable prefix and sampling from the catalog

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** `agent/loop_request.py:139-153` appends the finalization instruction to the system
  message, so the turn's last (longest) request misses the cached prefix; `LoopConfig.temperature`
  (`agent/loop_types.py:64`) has no writer (unwired machinery, the eighth); `top_p` does not exist;
  the local endpoint reports 1.0 inherited while the model card asks 0.7/0.8 in non-thinking mode.
- **Goal:** (1) finalization is a trailing `user` message, request-only as today, the system
  message untouched; (2) a catalog row may declare `sampling: {temperature, topP}`; the driver
  passes it into `LoopConfig` and the wire sends both only when declared; the trace's `llm_call`
  records what was sent.
- **Non-goals:** the profile (P52-7); `tool_choice`; reasoning; any default when the row declares
  nothing (the endpoint's own stays).
- **Spec:** `agent-loop.spec.md` (finalization shape; sampling passthrough);
  `model-profiles.spec.md` (5.0.3 → 5.1.0, the `sampling` fields on a catalog row).
- **Change:** `agent/loop_request.py::_finalization_messages`, `agent/loop_types.py` (`top_p`),
  `models/catalog.py` (row fields), `models/adapters/openai_wire.py::build_payload`,
  `hops/application/driver.py` (LoopConfig construction), `agent/loop_trace.py` (record).
- **Acceptance:** a turn that exhausts its budget → the finalization request's first message is
  byte-identical to the previous request's (oracle: `tests/integration/agent/test_loop_*` compares
  the two captured payloads); a provider doc with `sampling` → the payload carries `temperature`
  and `top_p`, and without it carries neither (`tests/unit/models/adapters/test_openai_wire.py`);
  `docket status` or `task show` unchanged. Lane e2e green.
- **Contention:** `agent-loop.spec.md` with P52-2 (integrator renumbers). Files disjoint from
  every Wave A card.

### P52-4 — a command the lexer cannot parse is refused, not asked

**Status:** BLOCKED (needs maintainer go: a parse failure stops being an `ask`) · **Size:** S ·
**Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** `governance/security.py:353-440` with `command_lexer.py:162-169`: a `shlex`
  `ValueError` (an unclosed quote) yields `ask: command could not be parsed`, which parks the
  task for a person. The model's syntax error becomes human waiting time; with `consultMode`
  irrelevant here, a lights-out pod stalls on a typo.
- **Goal:** the parse failure is `REFUSED [syntax]: <lexer message>; fix the quoting and call
  again`. Nothing runs, as today. The opaque markers (`$(`, backticks, `${`, `eval`, `exec`) and
  the unclosed heredoc keep asking: they are risk, not syntax.
- **Non-goals:** `bash -n`; any change to SAFE_BINS or `allowCommands`; the denial counter (a
  refusal still counts toward the three-denials stop).
- **Spec:** `security-gates.spec.md` (1.7.0 → 1.8.0, the classifier table row; P52-11 bumps the same
  spec in Wave A, the integrator renumbers).
- **Change:** `governance/security.py::classify_command` (one branch), the policy corpus row.
- **Acceptance:** `bash` with `echo "unclosed` → `REFUSED [syntax]` and no escalation record, no
  audit `approval` entry (oracle: `tests/integration/governance/test_security*` plus the audit
  oracle from `tests/support/e2e_oracles.py`); the 310-row corpus unchanged except the parse rows.
- **Contention:** `governance/` only; P52-10 continues `security.py` and `command_lexer.py` in Wave D.

### P52-5 — the Lead's locators: the code it found reaches the Implementer

**Status:** BLOCKED (needs P52-1's re-read figure on the private replay copies) · **Size:** L ·
**Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger (to be filled by the integrator from P52-1):** source `context_replay.py --repeats`
  on the recorded implementer steps; metric: share of the Implementer's `read` calls on files the
  Lead had already read; window: the recorded steps; threshold: ≥ 30 %; observed: _pending_.
  Context: Phase 44 closed with Implementers at 0.77/0.80 sent ratio "from longer trajectories";
  `TaskBrief.context` is prose (`kernel/brief.py:24-38`), so the Lead's reads are lost.
- **Goal:** the Lead may put locators `path:<file>#L<a>-<b>` in `context`; `_hop_message`
  (`hops/application/compose.py:181`) reads each range from the task worktree, fresh, and renders
  a `## Code the Lead located` section inside the Implementer's budget share
  (`agent/context.py:148-157`); ranges that do not fit stay as bare locators; an invalid locator
  is listed as such. The Lead's hop instruction asks for locators (`teams/builtin_roles.py:82-109`).
- **Non-goals:** a viewer role; sub-agents; any model call in the composition; locators in
  handoffs other than the Lead's.
- **Spec:** `pod-dispatch.spec.md` (10.7.0 → 10.8.0, "Bounded hop prompts");
  `role-archetypes.spec.md` (4.1.0 → 4.2.0, the Lead's instruction).
- **Change:** `kernel/brief.py` (validate the locator form), `hops/application/compose.py`
  (extraction + section), `agent/context.py` (share), `teams/builtin_roles.py` (instruction text).
- **Acceptance:** a brief with two locators, one valid and one past EOF → the Implementer's
  message holds the valid range's lines and names the invalid one; with a 200-token share → the
  first range whole, the second as a bare locator (oracle: `tests/integration/hops/test_compose*`);
  the starter example and `tests/agent/release/test_starter_journey.py` keep their field set
  (locators live inside `context`, no new field). Bench: `--policy p52-5` on the implementer
  fixtures reports re-reads before/after.
- **Contention:** `compose.py` is shared with P51-6's continuation work if that card is still open;
  claim after it merges.

### P52-6 — recipes for the pod as a viewer/editor team

**Status:** TODO · **Size:** S · **Model:** Haiku · **Kind:** data + tests

- **Trigger:** ADR 0033 §Decision 4: the pod already separates exploration from editing; no recipe
  shows the three shapes the survey's level matrix asks for. `researcher` is `strong` by default
  (`teams/builtin_roles.py:243-247`), so a cheap exploration must say so.
- **Goal:** three recipes under `templates/recipes/`, each with its `README.md` sentence and
  validated by the existing recipe tests: (a) `explore-then-edit`: `researcher`
  (`modelClass: cheap`, read-only) → `implementer` → `reviewer`; (b) `strong-plan-cheap-edit`:
  `lead` on `strong`, `implementer` on `cheap`, `verifyCmd` gate with `on: {fail: {goto:
  implementer, max: 1}}`; (c) `parallel-explore`: a `parallel` group of two cheap researchers
  with disjoint instructions → join → implementer, plus `on: {fail: {goto: lead, max: 1}}` from
  the implementer's step back to the Lead; (d) `web-research` (ADR 0034 decision 4): `lead` →
  a `parallel` group of three `researcher` children (`modelClass: cheap`, read-only) with disjoint
  instructions (two over the allowed hosts, one over the repository with `grep`/`read`) → `analyst`
  → `writer`, the roles `research-review` already uses; the pages stay in the children's sessions
  and only their replies reach the analyst as handoffs. Its `README.md` states the two
  prerequisites verbatim and nothing else about the network: `FETCH_ALLOWED_DOMAINS=<hosts>` for
  the pages the researchers may read, and `docket setup mcp add <name> --kind read -- <command>`
  for a search server, because docket has no built-in search; the README's example is a
  self-hosted SearXNG behind its MCP server (no vendor, no key, the operator's own host on the
  allowlist), and it says a hosted search API works through the same command with its key in
  the secret store.
- **Non-goals:** code; a new role; a sub-agent tool; claims about savings in the README; an
  `mcp-servers/` file naming a search server docket cannot validate at apply time.
- **Spec:** none (recipes are data; `pipeline-format.spec.md` 4.1.0 already allows every field).
- **Change:** `templates/recipes/<name>/pipeline.yaml` + `README.md` × 4; the recipe index test's
  expected list.
- **Acceptance:** `docket pod apply <recipe>` on a fresh home loads each without a validation
  error (oracle: the recipe lane's existing parametrized test picks them up); the `parallel`
  group validates (`pipeline/domain/step.py:90-193`); `web-research`'s README contains both
  prerequisite commands (the recipe README test, `tests/integration/teams/test_recipes.py`).
- **Contention:** `templates/recipes/` only.

### P52-7 — `ModelProfile`: the contract varies with the model

**Status:** TODO (after P52-3) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0033 §Decision 1. Today's single contract: an Implementer's schemas are about
  5,800 chars on every request (`consult` 1,229, `bash` 1,285); `tool_choice` is always `"auto"`
  (`openai_wire.py:110-112`); `budget_for_role` is unreachable on a 32k window without the manual
  env var in CONFIGURATION.md; the local eval needed the verdict parser's tolerance because the
  verdict was free text.
- **Goal:** a `profile` on a catalog row with built-ins `hosted` (today) and `local` (default for
  `local: true`): `toolSurface: full|minimal` (minimal = `bash`, `read`, `verify`, `verdict` when
  gated), `descriptions: full|compact` (≤ 2 sentences per tool for compact), `toolChoice: auto|
  forced-on-close` (the closing call of a verdict-gated step sends `tool_choice` for `verdict`),
  `budgets: window-derived` (`READ_DEFAULT_CHARS` and the tool-output cap as shares of
  `contextWindow`). The profile name is on every `llm_call` and in `docket status`.
- **Non-goals:** reasoning (deferred, ADR 0033); a per-role profile; heuristics by model name;
  changing `hosted` behaviour by one byte (goldens stay).
- **Spec:** `model-profiles.spec.md` (5.1.0 → 6.0.0, the profile and its two built-ins);
  `agent-loop.spec.md` (`tool_choice` on the chat port; window-derived budgets).
- **Change:** `models/catalog.py` (profile fields + resolution), `agent/ports.py` (`tool_choice` on
  the chat call), `agent/loop_types.py`, `models/adapters/openai_wire.py`,
  `hops/application/driver.py` (surface and budgets from the profile), `teams/role_composer.py`
  (surface), `hops/application/builtin_tools.py` (compact descriptions), `kernel/home.py` (derived
  defaults).
- **Acceptance:** a provider doc `local: true` without `profile` → `local`; its Implementer's
  request carries only the minimal surface and compact descriptions, and the closing call of a
  verdict step carries `tool_choice: {"type":"function","function":{"name":"verdict"}}` (oracle:
  captured payloads in `tests/integration/hops/test_docket_driver*`); a `hosted` row → payloads
  byte-identical to before (the CLI goldens and `tests/e2e` unchanged); `request_part_bytes["tools"]`
  for the local Implementer under 2,500. Live eval by the integrator at the wave close.
- **Contention:** continues P52-3's files; `builtin_tools.py` is not touched by P52-2 or P52-8.

### P52-8 — a result over the cap is kept whole and readable

**Status:** TODO (after P52-2) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0033: what passes `DOCKET_TOOL_MAX_OUTPUT_CHARS` is gone (the trace keeps a
  capped copy, `agent/loop_trace.py:219-220`, and no tool reads it); the condensation notice says
  "call X again", which re-runs a command whose result may differ and costs a round. A lower cap
  (the local endpoint needs 2,500) is only safe when the whole result stays reachable. `fetch`'s
  result is cut in `kernel/tool_outcome.py::text_outcome`, not in the toolbox: the write must cover
  that path too (P52-11 makes the text worth keeping).
- **Goal:** a tool result over the cap is written whole to `<pod cache>/artifacts/<sha256>.txt`
  (plain text, not docket-owned JSON; the jail's HOME is the pod cache, so it is readable without a
  grant); the truncated result ends with `[full output: <path> — read it with read(path, offset,
  limit)]`; the condensation notice points at the artifact when one exists instead of inviting a
  re-run; retention follows the trace's. `read` and `grep` must accept that path: check
  `toolbox.read`'s root containment first and, if it refuses, add the artifacts directory to the
  readable roots in the same card (`grep` over a kept page is how the model finds one section of
  it without reading it; the artifact is the one place a `fetch` result can be searched).
- **Non-goals:** lifecycle condensation (deferred); indexing or search over artifacts; a new tool.
- **Spec:** `session-history.spec.md` (1.10.0 → 1.11.0, the notice); `agent-loop.spec.md` (the
  artifact line in the tool-output section); `workspace-structure.spec.md` (the directory).
- **Change:** `agent/tools/builtins/toolbox.py` (write + marker, in the one place results are
  cut), `agent/session.py` (notice), `agent/loop_trace.py` (record the artifact path), retention
  in `observability/` where the trace's lives.
- **Acceptance:** a `bash` with 50 KB output under a 2,500 cap → the result carries the marker, the
  file exists with the full bytes, and a following `read(path, offset=2400, limit=50)` returns the
  bytes past the cut (oracle: `tests/integration/agent/test_tool_artifacts.py`, jailed variant in
  `tests/integration/sandbox/`); a `fetch` whose text exceeds the cap carries the same marker
  (`tests/unit/platform/test_fetch.py`, fake opener); the notice for a condensed result names the
  path; the e2e jailed journey stays green.
- **Contention:** continues P52-2's files; P52-11 (Wave A) precedes it on `fetch`.

### P52-9 — a tool's clock fits inside the turn's

**Status:** TODO (after P52-7 and P52-8 merge; `lifecycle.py` after P51-9) · **Size:** M ·
**Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** the 2026-10-24 run on `fab-dev` asked `bash` for `timeout: 600` and `timeout: 900`
  inside a 300 s turn and `_bash_handler` (`hops/application/builtin_tools.py:272`) honoured both:
  the argument has no ceiling. `agent/loop_budget.py:135` checks the wall clock only between
  iterations, so a tool that overruns ends the turn with `failure_kind: timeout`, which
  `runner.py:42` retries whole. `claimedAt` moves only at hop end and before a retry
  (`tasks/application/record.py:585`, `queue.py:360`), while `sweep_stale_claims`
  (`lifecycle.py:102`) fails a claim at a fixed `CLAIM_STALE_TIMEOUT` (1800 s), below the
  turn + verify lease `reclaim_stale_running` (`lifecycle.py:159`) already computes.
- **Goal, in order:** (1) `ToolContext.deadline` (monotonic seconds), set once by
  `run_agent_turn` from the clock it checks the wall clock with; `_bash_handler` runs the command
  for `min(requested or ctx.timeout, remaining)` with `remaining = max(1, deadline - now)`; a result
  the clamp killed ends with `[killed at the turn's remaining time (N s); run it as a verify gate or
  raise turnTimeoutS]`; the `timeout` argument's description names the ceiling. (2)
  `_build_on_process` (`driver.py:370`) calls `touch_claim(project, task_id)` on `started` when the
  turn has a task. (3) `sweep_stale_claims` fails a claim only past `max(CLAIM_STALE_TIMEOUT,
  lease)`, the lease taken from the one helper `reclaim_stale_running` uses.
- **Non-goals:** MCP timeouts (capped at 60 s already); a tool-caused timeout made non-retryable
  (deferred, ADR 0034); `verify`'s own timeout; interrupting a running tool from the loop.
- **Spec:** `agent-loop.spec.md` (requirement 9 gains the tool clamp; the `bash` tool's `timeout`
  sentence); `pod-dispatch.spec.md` ("Per-hop incremental persistence and crash recovery": the
  refresh on process start and the sweep floor).
- **Change:** `agent/tools/registry.py` (`ToolContext.deadline`), `agent/loop.py` (set it),
  `hops/application/builtin_tools.py` (`_bash_handler`, the `bash` schema text),
  `hops/application/driver.py::_build_on_process`, `tasks/application/lifecycle.py` (the floor).
- **Acceptance:** a fake clock 250 s into a 300 s turn and `bash` asking `timeout: 900` → the
  recording `run_bash` receives 50 and the killed result carries the marker (oracle: the
  `builtin_tools` unit module under `tests/unit/hops/`, new beside it if none; the deadline's
  setting in `tests/integration/agent/loop/test_stop_conditions.py`); a `process_started` under a
  dispatch run → the task's `claimedAt` moves (`tests/integration/tasks/test_retries_and_timeouts.py`,
  beside `TestRetryDoesNotTripStaleClaimSweep`); a pod with `turnTimeoutS: 2400` and a claim
  1,900 s old → the sweep leaves it `running` (same file). No bench: the model reads nothing new
  but the marker.
- **Contention:** continues P52-7's `builtin_tools.py` and `driver.py`; `lifecycle.py` after
  P51-9; `loop.py` and `registry.py` are nobody else's in this phase.

### P52-10 — a background process belongs to its turn

**Status:** TODO (after P52-9; `security.py` after P52-4) · **Size:** L · **Model:** Sonnet ·
**Kind:** behaviour + spec

- **Trigger:** probe of 2026-10-25: `nohup sleep 47 > bg.log 2>&1 &` through `run_bash` returned
  in 0.02 s and the child outlived the calling process; `classify_command` allows the shape jailed
  or not, although the lexer already sees the trailing `&` (it stops `cd` placement,
  security-gates "Redirects"). No handle, no exit event, nothing killed at turn end: the one shape
  that escapes `dispatch_tool`'s reach today. Every peer harness has a background mode with a
  handle (ADR 0034).
- **Goal, in order:** (1) `bash` gains `background: true`: `run_bash` starts the process as today
  (its own session), sends its output to `<ctx.cache_dir or the scratch dir>/processes/<pgid>.log`,
  registers the pgid in `ctx.processes` and returns `started pgid=<n> log=<path>` at once;
  `process_started` carries `background: true`. (2) two built-ins: `process_output(pgid, offset=0)`
  (kind `read`: the log from `offset` with `read`'s footer form, and whether the process is alive)
  and `process_stop(pgid)` (kind `write`: `_kill_group`, then `process_exited` with `signal`). (3)
  `_run_turn_body`'s `finally` stops every live entry of `ctx.processes` and traces each exit with
  `reason: turn_end`. (4) a trailing `&` (the control operator; not `&&`, `2>&1` or `&>`) joins the
  opaque markers in `classify_command`: asks jailed or not, reason `background a process with
  bash background=true`; the corpus gains its rows. (5) under the Docker backend `background` is
  refused with that reason (deferred, ADR 0034).
- **Non-goals:** stdin or a PTY; a process shared across hops or tasks; a new trace event type
  (the two existing ones carry the fields); the cancel path (`add_hop_pid` already tracks the pgid).
- **Spec:** `agent-loop.spec.md` (tool-output section: the argument and the two tools);
  `security-gates.spec.md` (the opaque-marker row; "Exec sandbox" requirement 7 extends the
  no-orphan rule to turn end); `trace-store.spec.md` (requirement 30: the optional fields).
- **Change:** `agent/tools/builtins/toolbox.py` (`run_bash`'s background branch, `process_output`,
  `process_stop`, the table type), `agent/tools/registry.py` (`ToolContext.processes`),
  `hops/application/builtin_tools.py` (schema, two tools), `hops/application/driver.py::_run_turn_body`
  (the `finally`), `governance/security.py` and `governance/command_lexer.py` (the marker), the
  policy corpus.
- **Acceptance:** `bash {command: "sleep 30", background: true}` → returns under 1 s with a pgid;
  `process_output` shows the log and `alive: true`; the turn ends → no process of that group
  remains and the trace holds `process_exited` with `reason: turn_end` (oracle:
  `tests/integration/agent/test_bash_background.py`, built like `test_bash_cancellation.py`; the
  landlock variant in `tests/integration/sandbox/`); `bash {command: "sleep 30 &"}` → `ask` with
  the reason, jailed and not (`tests/unit/governance/`); `a && b` and `ls 2>&1` keep today's
  verdict (the corpus changes only by the added rows). Lane e2e green.
- **Contention:** continues P52-9's files and P52-8's `toolbox.py`; `security.py` after P52-4, or
  beside it while P52-4 stays blocked (a different branch of `classify_command`; say so in the packet).

### P52-11 — `fetch` returns text the model can read

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** `fetch_url` returns the raw body (`platform/fetch.py`, the `text_outcome` call) and
  the cap keeps the head (`kernel/text.py:35`), so at `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` the model
  reads a page's `<head>` element. Claude Code and Gemini CLI convert a page before the model sees
  it (ADR 0034).
- **Goal:** when `Content-Type` is `text/html` (or the body starts with `<!doctype html` or
  `<html`), the body becomes plain text with the standard library's `html.parser`: `script`,
  `style`, `noscript` and `svg` dropped; block elements and `br` as line breaks; `h1` to `h3` as
  one to three `#` and a space; list items as a dash and a space; `pre` and `code` verbatim; a
  link as `text (href)` when the text differs from the href; whitespace collapsed to at most one
  blank line. Other content types pass as today. The header line reads `HTTP <status>
  <content-type>; <n> chars of text`. The tool's description says the page arrives as text and
  that a long page is kept whole and read back with `read` (P52-8).
- **Non-goals:** JavaScript; a readability heuristic; wildcard domains; a cache between calls; any
  change to the allowlist, the deadline, the size cap or the redirect guard.
- **Spec:** `security-gates.spec.md` ("Network egress and the `fetch` tool", requirement 2: a fifth
  bullet, the conversion; P52-4 bumps the same spec, the integrator renumbers).
- **Change:** `platform/fetch.py` (`_html_to_text`, applied before `text_outcome`),
  `hops/application/builtin_tools.py::_fetch_tool` (the description only).
- **Acceptance:** a fixture page (`tests/fixtures/fetch/page.html`: title, nav, two headings, a
  paragraph with a link, a `pre` block, a script) through a fake opener → the committed expected
  text byte for byte, under 15 % of the HTML's length (oracle: `tests/unit/platform/test_fetch.py`,
  a class beside `TestDomainAllowlist`); `application/json` → the body unchanged; the allowlist and
  redirect tests untouched and green. No bench: the fixtures record no `fetch`.
- **Contention:** `platform/fetch.py` is nobody else's; `builtin_tools.py` precedes P52-7, which
  continues it in Wave B. Spec seam with P52-4.

### P52-12 — a wait on a machine is an escalation

**Status:** BLOCKED (needs a measured trigger, none recorded; and P51-9, which owns the record) ·
**Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger (to be filled from a recorded run):** source: a task's trace and `escalations[]`;
  metric: tasks that fail, re-poll or spend a hop waiting on CI, a deploy or a URL; window: the
  first ten Tack-driven runs after Phase 51 closes; threshold: one; observed: _none_. Today's
  estimate, labelled as such: Tack's pipelines end at a push, so the wait sits in Tack, not in
  docket (ADR 0034 decision 5).
- **Goal:** `EscalationKind` gains `wait` with `condition: {kind: http|command, target, everyS,
  untilS}`; a pipeline step `wait: {...}` parks the task like a consult park; `sweep_escalations`
  probes the condition on its interval and calls `resolve` with `met` or `timed_out`; `docket
  inbox` lists it with the next probe time; `whenNobody[wait]` is `fail` at every level, since
  nobody can answer it.
- **Non-goals:** a wait inside a turn; webhooks from CI (the probe polls); a condition that makes a
  model call.
- **Spec:** `operator-api.spec.md` (the kind and the condition; a contract bump after P51-9's
  `operator-v2`), `pod-dispatch.spec.md` (the step and the park), `security-gates.spec.md`
  ("Autonomy levels": the `wait` row).
- **Change:** `kernel/operator_contract.py` (`EscalationKind` at `:295`, the condition),
  `pipeline/domain/step.py` (the step),
  `hops/application/sweep.py` and `governance/escalation_expiry.py` (the probe),
  `interfaces/cli/commands/inbox*` (the line), `teams/autonomy.py` (the row).
- **Acceptance:** a pipeline with `wait: {kind: http, target: <fake server>, everyS: 1, untilS: 5}`
  → the task parks with a `wait` escalation; the server starts answering 200 → the next sweep
  resolves `met` and the following step runs; a server that never answers → `timed_out` and the
  task fails with the reason (oracle: the harness of
  `tests/integration/tasks/dispatch/test_operator_input.py`, in a new module beside it; the e2e
  lane for the inbox line).
- **Contention:** the escalation record and `sweep.py` after P51-9; `step.py` is nobody else's.

## How work runs on this board (read before claiming a card)

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
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 40 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, the generated-docs checks and the real run: once, at
      the phase close.
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
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`;
Phases 46-47 run on `plan/phase-46-structure` until the maintainer integrates it). `main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Toolchain read grants (dropped from Phase 48).** A sibling project's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Fired, waiting for a maintainer go (the measurement spends hosted-model tokens).**

- **The implementer sends 0.65 of what the backend counts** (Phase 45 real runs on `fab-dev`,
  2026-10-20: 14 and 13 calls, largest request about 7,000 estimated tokens; reviewer 0.62, tester 0.80
  and 0.90). The Phase 44 trigger ("a real implementer run with its grants declared that still sends
  over half") fired. Next: P52-1 measures which calls repeat on the recorded traces (no live run
  needed); P52-5 acts on the figure.

**Model adaptation and context (ADR 0033, deferred with triggers; the cards are Phase 52).**

- **Reasoning kept inside the turn** (`ChatMessage.reasoning`, resent only in the active tool
  loop; `reasoning_content` is dropped today in `models/adapters/openai_wire.py::decode_response`).
  Trigger: a profile that declares `reasoning: interleaved`.
- **Lifecycle condensation** (a `read` superseded by a later `read` or an `edit` of the same file
  is evicted first, in batches aligned to steps). Trigger: after P52-8, the bench `--repeats`
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

- **Timing flakes seen once each:** `test_kernel_adoption.py` over its 2 s guard ceiling, three more
  `tests/guards/` tests (`test_dead_code`, two in `test_suite_shape`) at 2.04-2.42 s on the `no-sandbox`
  CI runner (PR 5),
  `test_retries_and_timeouts.py::TestRetryDoesNotTripStaleClaimSweep`, and the foreground approval
  deny test (its fake approval timeout was raised from 5 s to 60 s, `1a704359`). Trigger: a second
  failure of the same test. Then replace its wall-clock wait with an event.
- **Docstring budget:** `comment_lint.py` counts 209 long definition docstrings at the close against 205
  on `develop` (most moved or renamed code). Trigger: the next card that edits one of those modules
  trims its own.

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

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.
- **`FailureKind` enumerates only the four kinds the task state writes**; hop and gate kinds stay plain
  strings (pod-dispatch spec item 9). Trigger: the next change to those kinds.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
