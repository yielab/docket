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
> from a measured trigger or a maintainer request. The integration branch is `develop`
> (`plan/phase-46-structure` merged as PR #5, `52c22f89`).
> **Planned: Phases 52 and 53, one schedule.** Phase 52 (D-73,
> [ADR 0033](docs/adr/0033-the-harness-adapts-to-the-model-by-data.md); D-74,
> [ADR 0034](docs/adr/0034-the-turn-owns-its-processes-and-its-time.md)) keeps nine cards after the
> 2026-10-28 consolidation; Phase 53 (D-75,
> [ADR 0035](docs/adr/0035-prompts-are-versioned-configuration.md)) has nine. Both run on the one
> wave table in Phase 52's run block.

## ○ PHASE 52 PLANNED — the harness adapts to the model by data, and pays for context once (D-73, ADR 0033); the turn owns its processes and its time (D-74, ADR 0034)

> Planned 2026-10-25 by the maintainer from a code audit against a harness-engineering survey
> ([ADR 0033](docs/adr/0033-the-harness-adapts-to-the-model-by-data.md) holds the findings and the
> refusals). Cards are cut by **file ownership**, not by technique: everything one worker would
> change in the same files is one card, so no file is edited twice in the same wave. P52-9 to
> P52-12 were added the same day from a second reading
> ([ADR 0034](docs/adr/0034-the-turn-owns-its-processes-and-its-time.md): a tool's clock, background
> processes, `fetch`, search, machine waits); ADR 0034's search proposal is folded into P52-6
> (same owner, same files).
>
> **Validated and consolidated 2026-10-28** with Phase 53 (ADR 0035 §"One schedule with Phase
> 52"). The line locators still land. What was stale or doubled:
>
> - **Stale dependencies:** P51-6 and P51-9 shipped with Phase 51.
> - **Stale spec versions:** Phase 51 bumped `pod-dispatch` 11.0.0, `pipeline-format` 4.2.0,
>   `serve-read-api` 5.0.0, `trace-store` 4.0.0 and `security-gates` 2.0.0; the cards now name
>   these.
> - **`hops/application/driver.py` is at 678 of 700 lines.** P52-7 opens with its pure-move split
>   (a `scripts/maint/` script, its own commit), before P52-9 adds to it.
> - **Cards that would open the same files twice are merged:**
>   - P52-8 into P52-2;
>   - P52-3's sampling into P52-7;
>   - P52-10 into P52-9, with its `&` marker going to P52-4;
>   - P52-11's tool description into P52-7;
>   - P52-5 into P53-4;
>   - P52-7's tool-surface application into P53-6.
>
>   The absorbed ids (P52-5, P52-8, P52-10) are not reused.

### How a Phase 52 card runs (read before claiming one)

- Spec → failing test → smallest change. Bump the owning spec (MINOR) with `Last Updated` and the
  `specs/README.md` row in the same commit.
- **Read bounded, to spend little:** `card_packet.py P52-<n>`, ADR 0033 §"Decision" (one screen;
  ADR 0034's for P52-4, P52-9 and P52-11), the spec section the card names, the files it names.
  Nothing else: not the ADR's findings, not another card, not a spec directory. A worktree has no
  `internal-docs/`.
- **Measure with what exists, free first.** The replay bench
  (`scripts/maint/context_replay.py tests/fixtures/context-replay --policy <name>`) costs nothing
  and is the oracle for bytes and counted tokens; a card that changes what the model sees adds its
  `--policy` and reports the table before/after. The live eval (`scripts/maint/live_eval.py -n 3`,
  local endpoint, `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`) runs **once per wave by the integrator**, not
  per card; the remote provider once at the phase close, after a go.
- **Every card:** focused tests by path under `timeout 120`; before handoff `ruff`, `mypy src`,
  `pytest --co -q`, `tests/architecture`, `comment_lint.py --check` on touched files. The e2e lane
  only on cards that change a tool's output or the wire (P52-2, P52-3, P52-7, P52-9, P52-11).
- **Spend by model.** Haiku runs the data card (P52-6) and, on any card, the spec and doc edits the
  card spells out; Sonnet runs behaviour in `src/`; no Opus on this phase. A worker opens only the
  files its card names (no card names more than eight) and the one spec section it names; a card
  that turns out to need more parks with the missing locator instead of exploring. Every card's
  trigger carries its line numbers so the worker greps, never reads a module whole.
- **Integrator seams:** cards in one wave that bump the same spec (`agent-loop`, `workspace-structure`,
  `security-gates`, `pod-dispatch`, `role-archetypes`) leave the number to the integrator, who
  renumbers at merge (as in Phase 44). The full default suite runs once per merge, `--lf` after.
- Workers in `.claude/worktrees/p52-<n>`, one card per worktree. **Model per card** is on the
  card: Sonnet for behaviour in `src/`, Haiku for data-only cards. Delta-only handoff with the
  end-of-work control summary.

**Waves for Phases 52 and 53 (one schedule, by file contention)**

No file is edited by two cards of one wave. A card that continues another's file waits for that
merge, which the "after" column names. The integrator may run Wave 1 in two batches; order inside a
wave is free.

| Wave | Cards | Owners (disjoint inside the wave) | After |
| --- | --- | --- | --- |
| 1 | P52-1 ∥ P52-2 ∥ P52-3 ∥ P52-6 ∥ P52-11 ∥ P53-1 ∥ P53-2 | metrics fold + `log` + bench · `kernel/text.py`, `tool_outcome.py`, toolbox, `verify_tool.py`, `session.py`, `loop_trace.py`, `observability/trace.py` · `loop_request.py` · recipes · `platform/fetch.py` · `teams/prompts.py`, `config_docs.py`, `role_schema.py`, `builtin_roles.py`, `compose.py::_role_instructions`, `pod_config.py` · `kernel/home.py`, `agents.py`, `governance/policy.py`, `plugins.py` | none |
| 2 | P52-7 ∥ P53-3 | catalog, `ports.py`, `loop_types.py`, wire, `driver.py` (split first), `builtin_tools.py`, `home.py`, `loop_trace.py` · `roles.py`, `apply/write.py`, `apply/plan.py`, `steps.py`, `skills.py`, `mcp_servers.py`, `pod_config.py`, `prompts.py` | P52-2, P53-2 · P53-1, P53-2 |
| 3 | P52-9 ∥ P53-5 ∥ P53-6 ∥ P53-7 | `registry.py`, `loop.py`, `builtin_tools.py`, `driver.py`, toolbox, `lifecycle.py` · `verdict_tool.py`, `handoff.py`, `record.py`, `plan.py`, `runner.py`, `task.py`, `ports.py`, `identity.py` · `role_composer.py`, `role_schema.py`, `loop_steps.py`, `loop_types.py`, `pipeline/domain/spec.py` · `prompts.py`, `model_selection.py`, `pod_prompt.py`, CLI registry | P52-2, P52-7 · P52-7 · P52-7, P53-1 · P52-7, P53-3 |
| 4 | P53-4 ∥ P52-4 | `compose.py::_hop_message`, `agent/context.py`, `kernel/brief.py`, `repo_map.py`, the Lead's hop prompt file · `governance/security.py`, `command_lexer.py`, corpus | P52-1's figure, P53-1, P53-5 · P52-9 (and the go, for the syntax half) |
| 5 | P53-8 | `task_create.py`, `task.py`, `queue.py`, `compose.py` (task layer) | P53-4, P53-5 |
| close | P53-9 | docs | every card |
| — | P52-12 | blocked on a recorded run; no wave until its trigger fires | |

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
- **Spec:** `trace-store.spec.md` (4.0.0 → 4.1.0: `cache_hit` is derived, not stored);
  `serve-read-api.spec.md` (5.0.0 → 5.1.0: the two metrics keys); `cost-tracking.spec.md` only if
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
  figure recorded on P53-4's trigger line (P53-4 absorbed P52-5).
- **Contention:** the metrics fold in `observability/`, `interfaces/cli/commands/log*` and the bench
  script. `observability/trace.py::expire_old_traces` is P52-2's in the same wave: P52-1 adds its
  fold beside it, never inside that module.

### P52-2 — tool results the model can use, kept whole past the cap (absorbs P52-8)

**Status:** TODO · **Size:** XL (two cards' scope, one pass over the files) · **Model:** Sonnet ·
**Kind:** behaviour + spec

- **Trigger:** ADR 0033 findings, verified 2026-10-25 and re-located 2026-10-28:
  `kernel/text.py::cut_output` (`:35`) keeps the head only; `toolbox.py` merges stderr into stdout
  (`:419`) and hints only on exit 126 (`:472-473`); `edit` says only "not found" (`:188-197`); no
  ANSI or repeated-line normalization anywhere; the condensation window (`agent/session.py:65-69`)
  lets one 20 KB grep evict a 1.2 KB README that is then re-read (Phase 44 close note). What
  passes `DOCKET_TOOL_MAX_OUTPUT_CHARS` is gone: the trace keeps a capped copy
  (`agent/loop_trace.py:219-220`) and no tool reads it; the condensation notice says "call X
  again", which re-runs a command whose result may differ. `fetch`'s result is cut in
  `kernel/tool_outcome.py::text_outcome`, not in the toolbox. Merged with P52-8 on 2026-10-28
  (ADR 0035): both cards change the same cut and the same notice.
- **Goal, in order (a park leaves the rest visible):**
  1. Lossless normalization before the cut: strip ANSI escapes, resolve `\r` progress lines to
     their last state, collapse consecutive identical lines to `line  [x N]`.
  2. `cut_output` for `bash` and `verify` keeps head and tail (40/60) with the marker between
     them; `read` keeps head-only.
  3. A result over the cap is written whole to `<pod cache>/artifacts/<sha256>.txt` (plain text,
     not docket-owned JSON; the path composed from `Home.pod_cache_dir`, no new `Home` accessor)
     in the one place results are cut, `fetch`'s `text_outcome` path included; the cut result ends
     with `[full output: <path> — read it with read(path, offset, limit)]`. `read` and `grep`
     accept that path: if `toolbox.read`'s root containment refuses it, the artifacts directory
     joins the readable roots in this card.
  4. On exit ≠ 0, stderr first, then stdout; a fixed table of known causes: 126 (today's text),
     127 (`not on PATH inside the jail or not in allowCommands`).
  5. `edit` "not found" lists the three closest lines (`difflib`, ratio ≥ 0.6) with "the text
     must match exactly; copy it from `read` without the line-number prefix". Never auto-apply.
  6. Condensation: a tool result under 1,500 chars is never condensed while a larger one in the
     same step is whole (monotone), and the notice for a condensed result names its artifact when
     one exists instead of inviting a re-run.
  7. Artifacts expire with the traces (`observability/trace.py::expire_old_traces`).
- **Non-goals:** timestamps or pids replaced; any change to `read`'s window; a second
  normalization pass elsewhere; lifecycle condensation (deferred, ADR 0033); indexing or search
  over artifacts; a new tool.
- **Spec:** `agent-loop.spec.md` (3.2.0 → 3.3.0, tool-output section: normalization, head+tail,
  the artifact line, error order); `session-history.spec.md` (1.9.2 → 1.10.0, the small-results
  rule beside requirement 31 and the notice); `workspace-structure.spec.md` (2.2.0, MINOR: the
  artifacts directory; P53-2 bumps the same spec in Wave 1, the integrator renumbers).
- **Change:** `kernel/text.py` (`cut_output` gains a `tail` share; a new `normalize_output`),
  `kernel/tool_outcome.py` (the artifact on `fetch`'s path), `agent/tools/builtins/toolbox.py`
  (`bash`, `edit`, `read` roots, the write + marker), `hops/application/verify_tool.py`,
  `agent/session.py::condense_history` (rule + notice), `agent/loop_trace.py` (record the artifact
  path), `observability/trace.py::expire_old_traces`.
- **Acceptance:** a `bash` whose output is 20 lines of progress + a pytest summary at the tail →
  the result shows the summary after the marker; an output with ANSI colour and 50 identical lines
  → one line with `[x 50]`; a `bash` with 50 KB output under a 2,500 cap → the result carries the
  artifact marker, the file holds the full bytes, and `read(path, offset=2400, limit=50)` returns
  the bytes past the cut (oracle: `tests/integration/agent/test_tool_artifacts.py`, jailed variant
  in `tests/integration/sandbox/`); a `text_outcome` over the cap (`fetch`'s path) carries the
  same marker (`tests/unit/kernel/test_tool_outcome.py`; `test_fetch.py` is P52-11's this wave); `edit` with a near-miss `old_string` → the
  error names the closest line; a step with one 20 KB grep then a 1 KB read → the read survives
  condensation and the grep's notice names its artifact
  (`tests/unit/agent/test_session.py`); `task prune` past the retention removes
  the artifact with its trace. Units in `tests/unit/kernel/test_text.py` and
  `tests/unit/agent/tools/builtins/`. Bench `--policy p52-2` reports bytes per step before/after on
  `tests/fixtures/context-replay` (no step worse). Lane e2e green, the jailed journey included.
- **Contention:** owns the toolbox, `kernel/text.py`, `tool_outcome.py`, `session.py`,
  `loop_trace.py` and `observability/trace.py` in Wave 1. P52-7 continues `loop_trace.py` and
  P52-9 the toolbox, both after this merges. P52-11 (same wave) changes `platform/fetch.py` only,
  before `text_outcome`.

### P52-3 — finalization is a trailing message: the turn's last request keeps the cached prefix

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** `agent/loop_request.py:139-153` appends the finalization instruction to the system
  message, so the turn's last (longest) request misses the cached prefix (ADR 0033 decision 2).
  The card's sampling half (`LoopConfig.temperature` at `agent/loop_types.py:64` has no writer;
  `top_p` does not exist) moved to P52-7 on 2026-10-28: `sampling` is a profile field and touches
  the same four files P52-7 owns (ADR 0035 §"One schedule with Phase 52").
- **Goal:** finalization is a trailing `user` message, request-only as today; the system message
  is untouched.
- **Non-goals:** sampling, the profile, `tool_choice` (all P52-7); reasoning.
- **Spec:** `agent-loop.spec.md` (the finalization shape; P52-2 bumps the same spec in Wave 1, the
  integrator renumbers).
- **Change:** `agent/loop_request.py::_finalization_messages`.
- **Acceptance:** a turn that exhausts its budget → the finalization request's first message is
  byte-identical to the previous request's, and the last message is the instruction as `user`
  (oracle: `tests/integration/agent/loop/test_terminal_reservation.py` compares the two captured payloads); `docket
  status` and `task show` unchanged. Bench `--policy p52-3` reports the prefix bytes shared by the
  last two requests of each recorded step before/after. Lane e2e green.
- **Contention:** `loop_request.py` is nobody else's in either phase.

### P52-4 — the classifier: a parse failure is refused, a trailing `&` asks (absorbs P52-10 step 4)

**Status:** TODO (after P52-9) for the `&` half · BLOCKED (needs maintainer go: a parse failure
stops being an `ask`) for the syntax half · **Size:** S · **Model:** Sonnet · **Kind:**
behaviour + spec

- **Trigger:** (a) `governance/security.py:353-440` with `command_lexer.py:162-169`: a `shlex`
  `ValueError` (an unclosed quote) yields `ask: command could not be parsed`, which parks the task
  for a person; a lights-out pod stalls on a typo. (b) probe of 2026-10-25 (ADR 0034):
  `nohup sleep 47 > bg.log 2>&1 &` through `run_bash` returned in 0.02 s and the child outlived
  the call; `classify_command` allows the shape jailed or not, although the lexer already sees the
  trailing `&`. Both halves change the same function, corpus and spec row, so they are one card
  (merged 2026-10-28, ADR 0035).
- **Goal:** (1) a trailing `&` (the control operator; not `&&`, `2>&1` or `&>`) joins the opaque
  markers: asks jailed or not, reason `background a process with bash background=true` (the
  argument P52-9 adds; hence after P52-9). (2) With the go: the parse failure is `REFUSED
  [syntax]: <lexer message>; fix the quoting and call again`. Nothing runs, as today. The opaque
  markers (`$(`, backticks, `${`, `eval`, `exec`) and the unclosed heredoc keep asking: they are
  risk, not syntax. Without the go, the card ships (1) alone and (2) stays a follow-up.
- **Non-goals:** `bash -n`; any change to SAFE_BINS or `allowCommands`; the denial counter (a
  refusal still counts toward the three-denials stop); the background mode itself (P52-9).
- **Spec:** `security-gates.spec.md` (2.0.0 → 2.1.0: the opaque-marker row and the classifier
  table row).
- **Change:** `governance/security.py::classify_command`, `governance/command_lexer.py` (the `&`
  marker), the policy corpus rows.
- **Acceptance:** `bash {command: "sleep 30 &"}` → `ask` with the reason, jailed and not
  (`tests/unit/governance/`); `a && b` and `ls 2>&1` keep today's verdict; with the go, `bash` with
  `echo "unclosed` → `REFUSED [syntax]`, no escalation record and no audit `approval` entry
  (oracle: `tests/unit/governance/test_security.py` plus the audit oracle from
  `tests/support/e2e_oracles.py`); the 310-row corpus changes only by the added and parse rows.
- **Contention:** `governance/security.py` and `command_lexer.py` are nobody else's; Wave 4, after
  P52-9 ships `background`. `security-gates.spec.md` is bumped earlier by P52-11 and P53-2: the
  integrator renumbers.

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
- **Spec:** none (recipes are data; `pipeline-format.spec.md` 4.2.0 already allows every field).
- **Change:** `templates/recipes/<name>/pipeline.yaml` + `README.md` × 4; the recipe index test's
  expected list.
- **Acceptance:** `docket pod apply <recipe>` on a fresh home loads each without a validation
  error (oracle: the recipe lane's existing parametrized test picks them up); the `parallel`
  group validates (`pipeline/domain/step.py:90-193`); `web-research`'s README contains both
  prerequisite commands (the recipe README test, `tests/integration/teams/test_recipes.py`).
- **Contention:** `templates/recipes/` only. P53-1 adds `templates/prompts/`, a sibling directory;
  these recipes name built-in roles and add no role prompt file.

### P52-7 — `ModelProfile`: the contract varies with the model (absorbs P52-3's sampling)

**Status:** TODO (after P52-2 and P53-2) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour +
spec

- **Trigger:** ADR 0033 §Decision 1. Today's single contract: an Implementer's schemas are about
  5,800 chars on every request (`consult` 1,229, `bash` 1,285); `tool_choice` is always `"auto"`
  (`models/adapters/openai_wire.py:110-112`); `LoopConfig.temperature` (`agent/loop_types.py:64`)
  has no writer (unwired machinery, the eighth) and `top_p` does not exist, while the local
  endpoint reports 1.0 inherited and the model card asks 0.7/0.8 in non-thinking mode; the local
  eval needed the verdict parser's tolerance because the verdict was free text. P52-3's sampling
  half and P52-11's `fetch` description joined this card on 2026-10-28 (same files); the surface's
  application moved to P53-6 and the window-derived budgets' application to P52-9, which own
  `role_composer.py` and `ToolContext` (ADR 0035 §"One schedule with Phase 52").
- **Goal:** a `profile` on a catalog row with built-ins `hosted` (today) and `local` (default for
  `local: true`), resolved in `models/catalog.py`: `sampling: {temperature, topP}` (passed into
  `LoopConfig`; the wire sends both only when declared; `llm_call` records what was sent);
  `toolSurface: full|minimal` (declared and resolved here; P53-6 applies it); `descriptions:
  full|compact` (≤ 2 sentences per tool for compact, `fetch`'s included: the page arrives as text
  and a long page is kept whole and read back with `read`); `toolChoice: auto|forced-on-close`
  (the closing call of a gated step sends `tool_choice` for the step's closing tool, `verdict`
  today and `handoff` after P53-5, named by the step, never hard-coded); `budgets`: the read
  window and the tool-output cap as shares of `contextWindow` (computed here; P52-9 carries them
  on `ToolContext`). The profile name is on every `llm_call` and in `docket status`.
- **Non-goals:** reasoning (deferred, ADR 0033); a per-role profile; heuristics by model name;
  any default sampling when the row declares none; changing `hosted` behaviour by one byte
  (goldens stay); applying the surface or the budgets (P53-6, P52-9).
- **Spec:** `model-profiles.spec.md` (5.0.3 → 6.0.0, the profile, its two built-ins and
  `sampling`); `agent-loop.spec.md` (`tool_choice` on the chat port; the sampling passthrough).
- **Change:** first, the pure-move split of `hops/application/driver.py` (678 lines) by a
  `scripts/maint/` script in its own commit (`pytest --co` and `tests/architecture/` are its
  check). Then `models/catalog.py` (profile fields + resolution), `agent/ports.py` (`tool_choice`
  on the chat call), `agent/loop_types.py` (`top_p`), `models/adapters/openai_wire.py::build_payload`,
  `hops/application/driver.py` (LoopConfig from the profile), `hops/application/builtin_tools.py`
  (compact descriptions), `agent/loop_trace.py` (record), `interfaces/cli/commands/status.py`
  (the profile name).
- **Acceptance:** a provider doc `local: true` without `profile` → `local`; its requests carry
  compact descriptions, and the closing call of a verdict step carries `tool_choice:
  {"type":"function","function":{"name":"verdict"}}` (oracle: captured payloads in
  `tests/integration/hops/driver/`); a provider doc with `sampling` → the payload
  carries `temperature` and `top_p`, and without it carries neither
  (`tests/unit/models/adapters/test_openai_wire.py`); a `hosted` row → payloads byte-identical to
  before (the CLI goldens and `tests/e2e` unchanged); `docket status` names the profile. Live eval
  by the integrator at the wave close.
- **Contention:** Wave 2. `loop_trace.py` after P52-2; `builtin_tools.py` and `driver.py` are
  continued by P52-9 in Wave 3; `agent/ports.py` by P53-5 in Wave 3; `loop_types.py` by P53-6 in
  Wave 3.

### P52-9 — the turn owns its tools' clock, processes and output budgets (absorbs P52-10)

**Status:** TODO (after P52-2 and P52-7) · **Size:** XL (two cards' scope, one pass over
`ToolContext`) · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** (a) the 2026-10-24 run on `fab-dev` asked `bash` for `timeout: 600` and `timeout:
  900` inside a 300 s turn and `_bash_handler` (`hops/application/builtin_tools.py:272`) honoured
  both; `agent/loop_budget.py:135` checks the wall clock only between iterations, so a tool that
  overruns ends the turn with `failure_kind: timeout`, which `hops/application/runner.py:42`
  retries whole; `claimedAt` moves only at hop end and before a retry
  (`tasks/application/record.py:585`, `tasks/application/queue.py:360`), while
  `sweep_stale_claims` (`tasks/application/lifecycle.py:102`) fails a claim at a fixed
  `CLAIM_STALE_TIMEOUT` (1800 s), below the turn + verify lease `reclaim_stale_running`
  (`lifecycle.py:159`) already computes. (b) probe of 2026-10-25: `nohup sleep 47 > bg.log 2>&1 &`
  returned in 0.02 s and the child outlived the call: no handle, no exit event, nothing killed at
  turn end (ADR 0034). (c) the tool-output cap and `READ_DEFAULT_CHARS` (`toolbox.py:50`) are one
  value per home (`kernel/home.py:228`), read in `toolbox.py:66`, `kernel/tool_outcome.py:23` and
  `agent/tools/mcp_client.py:68`, so a window-derived budget (P52-7) has no per-turn carrier.
  P52-10 and the budgets' application joined this card on 2026-10-28: all three extend the same
  `ToolContext` and its construction in `driver.py` (ADR 0035).
- **Goal, in order (a park leaves the rest visible):**
  1. `ToolContext.deadline` (monotonic seconds), set once by `run_agent_turn` from the clock it
     checks; `_bash_handler` runs for `min(requested or ctx.timeout, remaining)` with `remaining =
     max(1, deadline - now)`; a result the clamp killed ends with `[killed at the turn's remaining
     time (N s); run it as a verify gate or raise turnTimeoutS]`; the `timeout` description names
     the ceiling.
  2. `_build_on_process` (`driver.py:370`) calls `touch_claim(project, task_id)` on `started` when
     the turn has a task; `sweep_stale_claims` fails a claim only past `max(CLAIM_STALE_TIMEOUT,
     lease)`, the lease from the helper `reclaim_stale_running` uses.
  3. `bash` gains `background: true`: the process starts in its own session, its output goes to
     `<ctx.cache_dir or the scratch dir>/processes/<pgid>.log`, the pgid is registered in
     `ctx.processes` and `started pgid=<n> log=<path>` returns at once; `process_started` carries
     `background: true`. Two built-ins: `process_output(pgid, offset=0)` (kind `read`) and
     `process_stop(pgid)` (kind `write`: `_kill_group`, then `process_exited` with `signal`).
     `_run_turn_body`'s `finally` stops every live entry and traces each exit with `reason:
     turn_end`. Under the Docker backend `background` is refused with a reason (deferred, ADR 0034).
  4. `ToolContext` carries the turn's output cap and read window: the profile's shares (P52-7)
     where it declares them, never above the home's `DOCKET_TOOL_MAX_OUTPUT_CHARS`; `hosted`
     carries today's values. The three readers take them from the context.
- **Non-goals:** MCP timeouts (capped at 60 s already); a tool-caused timeout made non-retryable
  (deferred, ADR 0034); `verify`'s own timeout; interrupting a running tool from the loop; stdin or
  a PTY; a process shared across hops or tasks; a new trace event type; the `&` marker (P52-4).
- **Spec:** `agent-loop.spec.md` (requirement 9 gains the tool clamp; the `bash` `timeout` and
  `background` arguments and the two tools; output budgets per turn); `pod-dispatch.spec.md`
  (11.0.0, MINOR: "Per-hop incremental persistence and crash recovery", the refresh on process
  start and the sweep floor); `security-gates.spec.md` ("Exec sandbox" requirement 7: no orphan at
  turn end); `trace-store.spec.md` (requirement 30: the optional fields). The integrator renumbers
  against P52-1, P52-4, P53-5 and P53-6.
- **Change:** `agent/tools/registry.py` (`ToolContext.deadline`, `.processes`, the budgets),
  `agent/loop.py` (set the deadline), `hops/application/builtin_tools.py` (`_bash_handler`, the
  schema, two tools), `hops/application/driver.py` (`_build_on_process`, `_run_turn_body`'s
  `finally`, the budgets into the context), `agent/tools/builtins/toolbox.py` (`run_bash`'s
  background branch, `process_output`, `process_stop`, the context's budgets),
  `tasks/application/lifecycle.py` (the floor), `kernel/tool_outcome.py` and
  `agent/tools/mcp_client.py` (the cap from the context).
- **Acceptance:** a fake clock 250 s into a 300 s turn and `bash` asking `timeout: 900` → the
  recording `run_bash` receives 50 and the killed result carries the marker (oracle: the
  `builtin_tools` unit module under `tests/unit/hops/`; the deadline's setting in
  `tests/integration/agent/loop/test_stop_conditions.py`); a `process_started` under a dispatch run
  → `claimedAt` moves, and a pod with `turnTimeoutS: 2400` and a claim 1,900 s old stays `running`
  (`tests/integration/tasks/test_retries_and_timeouts.py`, beside
  `TestRetryDoesNotTripStaleClaimSweep`); `bash {command: "sleep 30", background: true}` → returns
  under 1 s with a pgid, `process_output` shows `alive: true`, and after the turn no process of
  that group remains and the trace holds `process_exited` with `reason: turn_end` (oracle:
  `tests/integration/agent/test_bash_background.py`, built like `test_bash_cancellation.py`; the
  landlock variant in `tests/integration/sandbox/`); a real `local` catalog row with
  `contextWindow: 32768` → a `bash` result is cut at the profile's share and a `hosted` row at
  today's cap (`tests/integration/hops/driver/`, through the real catalog: the seam
  with P52-7). Lane e2e green.
- **Contention:** Wave 3. Continues P52-7's `builtin_tools.py` and `driver.py` and P52-2's toolbox
  and `tool_outcome.py`; `loop.py`, `registry.py`, `lifecycle.py` and `mcp_client.py` are nobody
  else's. P52-4 follows in Wave 4 (its `&` reason names `background`).

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
  <content-type>; <n> chars of text`. The tool's description (the page arrives as text; a long page
  is kept whole and read back with `read`) is written by P52-7, which rewrites every description
  (moved 2026-10-28, ADR 0035).
- **Non-goals:** JavaScript; a readability heuristic; wildcard domains; a cache between calls; any
  change to the allowlist, the deadline, the size cap or the redirect guard.
- **Spec:** `security-gates.spec.md` (2.0.0 → 2.1.0, "Network egress and the `fetch` tool",
  requirement 2: a fifth bullet, the conversion; P53-2, P52-9 and P52-4 bump the same spec later,
  the integrator renumbers).
- **Change:** `platform/fetch.py` (`_html_to_text`, applied before `text_outcome`).
- **Acceptance:** a fixture page (`tests/fixtures/fetch/page.html`: title, nav, two headings, a
  paragraph with a link, a `pre` block, a script) through a fake opener → the committed expected
  text byte for byte, under 15 % of the HTML's length (oracle: `tests/unit/platform/test_fetch.py`,
  a class beside `TestDomainAllowlist`); `application/json` → the body unchanged; the allowlist and
  redirect tests untouched and green. No bench: the fixtures record no `fetch`.
- **Contention:** Wave 1. `platform/fetch.py` and `tests/unit/platform/test_fetch.py` are nobody
  else's; P52-2 (same wave) changes the cut after `text_outcome` and tests it in its own unit
  module.

### P52-12 — a wait on a machine is an escalation

**Status:** BLOCKED (needs a measured trigger, none recorded; P51-9 shipped with Phase 51) ·
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
- **Spec:** `operator-api.spec.md` (7.0.0; the kind and the condition; a contract bump after
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
- **Contention:** the escalation record and `sweep.py`; `step.py` is nobody else's. If its trigger
  fires while P53-8 is open, it waits for P53-8 (`operator-api.spec.md`).

## ○ PHASE 53 PLANNED — prompts are versioned configuration, and the harness is one a small model can use (D-75, ADR 0035)

> Planned 2026-10-28 from the maintainer's scoped request (an audit of Tack's prompts through
> docket to a local model, private document "Auditoría de prompts"). The request asks for four
> things:
>
> - a prompt that is a versioned configuration document: one authored form, one loader, one
>   resolution order, one hash recorded per hop, so that it can be tested alone, varied by model
>   class and measured by version;
> - the layers no longer mixed in one message;
> - the full repository map no longer sent in every hop;
> - a verdict that no longer depends on a last-line convention.
>
> [ADR 0035](docs/adr/0035-prompts-are-versioned-configuration.md) holds the findings, the ten
> decisions and the refusals. The request is every card's trigger; no metric or saving is invented,
> and any number a card reports before its oracle runs is an estimate. Cards are cut by **file
> ownership**. Phase 53 is consolidated with Phase 52: P52-5 is absorbed into P53-4 and P52-7's
> surface application into P53-6. Both phases run on the one wave table in Phase 52's run block.

### How a Phase 53 card runs (read before claiming one)

- Spec → failing test → smallest change. Bump the owning spec (MINOR unless the card says MAJOR)
  with `Last Updated` and the `specs/README.md` row in the same commit.
- **Read bounded, to spend little:** `card_packet.py P53-<n>`, ADR 0035 §"Decision" (the one
  numbered decision the card names), the spec section the card names, the files it names.
  Nothing else: not the ADR's findings, not another card, not a spec directory. A worktree has no
  `internal-docs/`.
- **Measure with what exists, free first.** The replay bench
  (`scripts/maint/context_replay.py tests/fixtures/context-replay --policy <name>`) costs nothing
  and is the oracle for bytes and counted tokens. A card that changes what the model sees (P53-1,
  which must show zero change; P53-4; P53-5; P53-6) adds its `--policy p53-<n>` and reports the
  table before/after. The live eval (`scripts/maint/live_eval.py -n 3`, local endpoint,
  `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`) runs **once per wave by the integrator**, not per card; the
  remote provider once at the phase close, after a go.
- **Every card:** focused tests by path under `timeout 120`; before handoff `ruff`, `mypy src`,
  `pytest --co -q`, `tests/architecture`, `comment_lint.py --check` on touched files. The e2e lane
  runs on every card except P53-7 and P53-9: all of them change the home layout, the prompt on the
  wire, the tool surface or the HTTP API. P53-1, P53-3 and P53-7 also run
  `gen_cli_docs.py --check` and the CLI goldens (`pod validate`, `pod update`, `pod test`).
- **Spend by model.** Haiku runs the docs card (P53-9) and, on any card, the spec and doc edits the
  card spells out, plus the prompt files of P53-1 once the loader is green; Sonnet runs behaviour
  in `src/`; no Opus on this phase. A worker opens only the files its card names (no card names
  more than eight) and the one spec section it names; a card that turns out to need more parks
  with the missing locator instead of exploring. Every card's trigger carries its line numbers, so
  the worker greps and never reads a module whole.
- **Near the 700-line rule:** `teams/identity.py` 659, `governance/policy.py` 658,
  `interfaces/cli/commands/agents.py` 643, `tasks/application/record.py` 601. A card whose change
  would cross puts the new code in a new module, never a function-local import.
- **Integrator seams:** see Phase 52's run block (one wave table, renumbering per wave). The full
  default suite runs once per merge, `--lf` after.
- Workers in `.claude/worktrees/p53-<n>`, one card per worktree. Delta-only handoff with the
  end-of-work control summary.

### P53-1 — the `prompt` kind, one loader, and the built-in prompts as files

**Status:** TODO · **Size:** L · **Model:** Sonnet (Haiku for the prompt files) · **Kind:**
behaviour + spec + data

- **Trigger:** the maintainer's request of 2026-10-28 (ADR 0035 decision 1). Found:
  - `hops/application/compose.py::_role_instructions` (`:69-101`) holds the implementer, reviewer
    and tester instructions as code, with no version, hash or test; only the Lead is a registry
    archetype (`teams/builtin_roles.py:82`);
  - `RoleArchetype` (`teams/role_schema.py:51-81`) carries one `hop_instruction` and one
    `soul_template` per role;
  - the `kind:` envelope is `teams/config_docs.py` (539 lines).

  The loader and its first consumer are one card: a loader nothing reads is unwired machinery.
  Free measurement: bench `--policy p53-1` must report zero changed bytes.
- **Goal:**
  1. A prompt file is YAML front matter plus a Markdown body: `kind: prompt`, `name`, `version`
     (semver), `layer: identity|task|hop`, `for: <role>`, `modelClass: cheap|strong|any`, `inputs`
     (name → type), `output` (schema name), `tests` (sibling path). A `${var}` not in `inputs` is
     a load error naming file and line. The parsing lives in a new `teams/prompts.py`, and the
     kind joins `config_docs.py`'s table. `prompt.schema.json` is published beside the other
     kinds'.
  2. The loader returns text, sha256, name, version, layer and scope. In this card it resolves
     shipped prompts and today's role overrides; P53-3 adds the scopes.
  3. These become files under `src/docket/templates/prompts/{hop,identity}/`: the implementer
     (first and rework, two files, since `${var}` has no conditionals), reviewer, tester and Lead
     hop instructions, and the built-in soul templates. `builtin_roles.py` keeps only what cannot
     be data.
  4. `docket pod validate` refuses a prompt with an undeclared input or an unknown `output`.
- **Non-goals:**
  - scopes, references and the lockfile (P53-3);
  - variants and `tests` execution (P53-7);
  - the manifest (P53-5);
  - any byte the model sees;
  - `_VERIFY_SENTENCE`, which stays code (conditional on `verifyCmd`);
  - semver on roles (a role's `version` stays its major).
- **Spec:** `config-format.spec.md` (2.1.0 → 2.2.0, the `prompt` kind); `role-archetypes.spec.md`
  (4.1.0 → 4.2.0: built-in instructions and souls are shipped prompt files).
- **Change:**
  - `teams/prompts.py` (new);
  - `teams/config_docs.py` (the kind);
  - `teams/role_schema.py::resolve_hop_instruction` and `render` (through the loader);
  - `teams/builtin_roles.py` (templates out);
  - `hops/application/compose.py::_role_instructions` and the Lead branch of `_hop_message`
    (`:212-217`);
  - `interfaces/cli/commands/pod_config.py::cmd_validate`;
  - `src/docket/templates/prompts/**` and `src/docket/templates/schemas/prompt.schema.json`
    (data).
- **Acceptance:**
  - The default pipeline's composed hop messages and every built-in member's `SOUL.md` are
    byte-identical to before. Oracles: `tests/integration/hops/test_hop_carryover.py::test_small_task_byte_identical_to_pre_cap_behaviour`,
    `tests/unit/hops/application/test_compose__hop_message.py`,
    `tests/integration/teams/test_prompt_layers.py`, and the CLI goldens `verify-all` 9/9.
  - A prompt using `${undeclared}` gives a load error naming the file and line
    (`tests/unit/teams/test_prompts.py`).
  - `docket pod validate` on a `.docket/` holding such a prompt exits non-zero and names it
    (`tests/integration/teams/`).
  - The installed wheel finds the shipped prompts (the e2e lane runs the installed package path).
  - Bench `p53-1`: zero changed bytes.
- **Contention:** Wave 1. Later cards continue these files: `compose.py` by P53-4 (Wave 4) and
  P53-8 (Wave 5); `role_schema.py` by P53-6; `pod_config.py` and `teams/prompts.py` by P53-3; and
  `teams/prompts.py` by P53-7. `config-format.spec.md` is P53-3's next.

### P53-2 — authored configuration beside state, and one scope order in `Home`

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + migration

- **Trigger:** the request (ADR 0035 decision 2). Found:
  - `kernel/home.py` mixes authored configuration with state at one level, and a pod's authored
    overlay lives inside state (`Home.pod_config_dir`, `:502-504`, under `workspaces/pods/`);
  - policies are loaded global plus pod as a union (`governance/policy.py:359-382`), and plugins
    global plus pod (`governance/plugins.py:78`);
  - `governance` sits below `teams` (ADR 0030), so the shared order must be a `Home` method.
- **Goal:**
  1. `Home` gains `config_dir` (`~/.docket/config`: model and MCP catalogs, recipes, skills,
     policies, plugins, `pods/<pod>/` overlays) and `state_dir` (`~/.docket/state`: sessions,
     traces, workspaces, caches, audit, approvals, escalations, secrets). Every accessor resolves
     under one of them.
  2. `Home.scopes(kind, project, repo_root)` returns the ordered directories: repository
     `.docket/<kind>`, then pod overlay, then operator config, then shipped templates. The
     repository entry is returned only for the text kinds (`prompts`, `skills`).
  3. `governance/policy.py` and `plugins.py` load through `Home.scopes`, union and deny-anywhere
     unchanged, with no repository entry: those kinds enter from a repository only by `docket pod
     update`.
  4. `docket init` migrates an old layout one way (moving the directories; refusing when both
     layouts exist), and a second run is a no-op. Without `init`, `Home` reads the old layout for
     one minor version: the maintainer's exception to board rule 7. A follow-up with the trigger
     "the next minor release" deletes that reader.
- **Non-goals:** the lockfile and the team-side kinds (P53-3); any repository-scope read of
  policies or plugins; a new secret store.
- **Spec:** `workspace-structure.spec.md` (2.2.0 → 3.0.0, MAJOR: the layout; P52-2 adds the
  artifacts directory in the same wave, the integrator renumbers); `security-gates.spec.md`
  (policy and plugin scopes; renumber with P52-11).
- **Change:**
  - `kernel/home.py` (the two roots, `scopes`, the one-minor reader);
  - a new `kernel/` module beside it for the move, which imports nothing in docket;
  - `interfaces/cli/commands/agents.py` (643 lines: `init` calls the migration, no logic there);
  - `governance/policy.py::_pod_policies_dir` and its loader (`:359-382`);
  - `governance/plugins.py` (`:78`).
- **Acceptance:**
  - A fresh `DOCKET_HOME` after `docket init` has only `config/` and `state/` at its top level
    (e2e init journey).
  - An old-layout home is moved by `docket init`, and a second `init` changes nothing; an
    old-layout home without `init` still serves `docket status` (`tests/integration/kernel/`).
  - `Home.scopes("skills", pod, repo)` returns the four entries in order, and
    `Home.scopes("policies", …)` has no repository entry (`tests/unit/kernel/test_home.py`).
  - An operator `deny` and a pod-overlay `allow` for the same command still deny
    (`tests/integration/governance/test_policy*`).
  - Lane e2e green; `scripts/maint/pytest-without-sandbox.sh -q` green.
  - Operator step at the wave close (the integrator, not the worker): back up `~/.docket`,
    reinstall, run `docket init` once, restart the service.
- **Contention:** Wave 1. `kernel/home.py`, `agents.py`, `policy.py` and `plugins.py` are nobody
  else's in either phase; P53-3 reads `Home.scopes` without editing `home.py`.

### P53-3 — one resolution order for the team's kinds, and `applied.lock`

**Status:** TODO (after P53-1 and P53-2) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour +
spec

- **Trigger:** the request (ADR 0035 decisions 2 and 3). Found:
  - the orders differ by kind: skills (`teams/workspace/skills.py::discover_skills`, `:109`),
    pipelines (`hops/application/steps.py::_task_pipeline_file`, `:136`), roles via the applied
    `roles.json` (`teams/roles.py::_pod_roles_file`, `:119-122`), MCP servers
    (`teams/mcp_servers.py:26-32`);
  - nothing links the authored role, the applied copy and `SOUL.md` by hash;
  - the applied directory's `configDigest` exists (`teams/pod_settings.py:187-195`).
- **Goal:**
  1. Roles, prompts, pipelines, skills and MCP servers resolve through `Home.scopes`, and the
     first scope with the name wins.
  2. Prompts and skills from the repository are read from the task's base commit through
     `teams/workspace/repo_view.py`. Roles, pipelines and MCP servers enter from the repository
     only through `docket pod update`.
  3. `roles.json` goes away: `docket pod update` writes the authored `<role>.yaml` + `.md` and
     prompt files into the pod overlay, and `load_registry` reads them.
  4. `pod update` writes `applied.lock` (path, scope, version, sha256 per item), and
     `configDigest` becomes the sha256 of that lock.
  5. A reference (`implementer@2`, `prompt:hop/implementer@2`) resolves to the newest file of that
     major.
  6. `docket pod validate` checks that every reference resolves and every declared input is
     supplied.
- **Non-goals:**
  - the governance kinds (P53-2);
  - variants (P53-7);
  - a reader of `roles.json`: a pod applied before this card is rewritten by its next `docket pod
    update`, and `docket status` names it as needing one;
  - any repository read at turn time of roles, pipelines or MCP servers.
- **Spec:** `config-format.spec.md` (MINOR after P53-1's: scopes, references, the lockfile);
  `workspace-structure.spec.md` (the overlay's contents, after P53-2's 3.0.0);
  `role-archetypes.spec.md` (no applied `roles.json`).
- **Change:**
  - `teams/roles.py` (`load_registry`; `_pod_roles_file` deleted);
  - `teams/apply/write.py` (authored files + lock);
  - `teams/apply/plan.py` (the digest is the lock's);
  - `hops/application/steps.py::_task_pipeline_file`;
  - `teams/workspace/skills.py::discover_skills`;
  - `teams/mcp_servers.py`;
  - `interfaces/cli/commands/pod_config.py` (`update`, `validate`);
  - `teams/prompts.py` (references).
- **Acceptance:**
  - A role named in the repository `.docket/roles/`, the operator config and the built-ins: after
    `docket pod update` the lock names the repository file with its sha256, and the hop's
    composed prompt is that file's (`tests/integration/teams/test_recipes.py`, which already covers
    `configDigest`; a new `test_applied_lock.py` beside it if the class outgrows it).
  - A hop that edits `.docket/prompts/…` in its task worktree: the next hop's prompt still comes
    from the base commit (`tests/integration/teams/`, built on the `repo_view` tests).
  - A pod with a `roles.json` from before: `docket pod update` leaves no `roles.json` and an
    equivalent registry.
  - `docket pod show` reports drift when an applied file changes.
  - `docket pod validate` with an unresolved `@3` exits non-zero and names it.
  - Lane e2e green (the onboarding journey).
- **Contention:** Wave 2. `pod_config.py` and `teams/prompts.py` come after P53-1; P53-7 continues
  `teams/prompts.py` in Wave 3. The other files are nobody else's.

### P53-4 — three layers in a fixed order, and a repository map bounded by relevance (absorbs P52-5)

**Status:** TODO (after P53-1 and P53-5; goal 3 needs P52-1's figure) · **Size:** L · **Model:**
Sonnet · **Kind:** behaviour + spec

- **Trigger:**
  - The request (ADR 0035 decisions 4 and 8). `hops/application/compose.py::_hop_message`
    (`:184`) mixes the description, the root block, answers, gate failure, rework, prior artifacts
    and the instruction. `teams/workspace/repo_map.py::task_root_block` (`:76`) sends the
    whole-tree map, capped in characters (`render_repo_map`, `:40-55`), to every hop.
  - `glob` exists (`hops/application/builtin_tools.py:430`).
  - P52-5's trigger, carried: source `context_replay.py --repeats` (P52-1) on the recorded
    implementer steps; metric: the share of the Implementer's `read` calls on files the Lead had
    already read; window: the recorded steps; threshold ≥ 30 %; observed: _pending_. Context:
    `TaskBrief.context` is prose (`kernel/brief.py:24-38`), so the Lead's reads are lost; the
    Implementer's share is `agent/context.py:148-157`.
- **Goal:**
  1. `_hop_message` emits two named sections after the system prompt (the identity layer), in a
     fixed order:
     - `## Task`: the description or brief, and the bounded map with paths relative to the
       repository root;
     - `## Hop`: working directory, operator answers, gate failure, rework, prior artifacts, the
       instruction.

     `_HopComposition.layers` reports each layer's tokens, which P53-5 records. The `## Task`
     section is byte-identical across the non-Lead hops of one task.
  2. The bounded map lists the paths the brief names, plus one level. The Lead, which has no brief
     yet, keeps today's capped map. The block's last line names `glob` for the rest.
  3. **Only if P52-1's figure is at least 30 %:** the Lead may put locators
     (`path:<file>#L<a>-<b>`) in `context` (validated in `kernel/brief.py`). Their ranges are read
     fresh from the worktree into `## Code the Lead located`, inside the Implementer's share.
     Ranges that do not fit stay as bare locators, and an invalid locator is named. The Lead's
     prompt file asks for locators (a MINOR version). Under the threshold this goal is cut and
     the figure recorded.
- **Non-goals:** a `repo_map` tool (ADR 0035, refused); a viewer role; sub-agents; any model call
  in the composition; locators in handoffs other than the Lead's; the manifest (P53-5); the
  structured task (P53-8).
- **Spec:** `pod-dispatch.spec.md` (11.0.0, MINOR, "Bounded hop prompts": the layers, the map, the
  locators; renumber with P52-9 and P53-5); `role-archetypes.spec.md` (the Lead's prompt asks for
  locators).
- **Change:**
  - `hops/application/compose.py::_hop_message`;
  - `agent/context.py` (the share);
  - `kernel/brief.py` (the locator form);
  - `teams/workspace/repo_map.py::task_root_block`;
  - the Lead's hop prompt file under `src/docket/templates/prompts/hop/`.
- **Acceptance:**
  - Two consecutive non-Lead hops of one task have byte-identical `## Task` sections
    (`tests/unit/hops/application/test_compose__hop_message.py`).
  - A brief naming `src/app/x.py` in a repository of 500 tracked files: the map lists `src/app/`
    and its direct entries, not the tree, and ends naming `glob`
    (`tests/integration/hops/test_repo_map.py`). The Lead's message keeps today's capped map.
  - With goal 3:
    - a brief with two locators, one valid and one past EOF: the Implementer's message holds the
      valid range's lines and names the invalid one;
    - with a 200-token share: the first range whole and the second as a bare locator
      (`tests/integration/hops/test_hop_carryover.py`);
    - the starter example and `tests/agent/release/test_starter_journey.py` keep their field set.
  - Bench `--policy p53-4`: the hop message's bytes and counted tokens before/after, plus P52-1's
    `--repeats` for re-reads. Lane e2e green.
- **Contention:** Wave 4. `compose.py` and the Lead's prompt file come after P53-1, and P53-8
  continues `## Task` in Wave 5. `agent/context.py`, `kernel/brief.py` and `repo_map.py` are nobody
  else's.

### P53-5 — the hop's record: the handoff is a tool call, and a prompt manifest per hop

**Status:** TODO (after P52-7) · **Size:** XL (two decisions that change what a hop records, one
pass over `record.py` and `task.py`) · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** the request (ADR 0035 decisions 5 and 6). Found:
  - `hops/application/verdict_tool.py` offers `verdict` to gated steps only;
  - `pipeline/domain/plan.py::parse_verdict` (`:347`) reads a marker line;
    `hops/application/runner.py::_reask_unmarked_verdict` (`:45`) asks for the line again;
  - `tasks/application/record.py` (`:342-363`) builds `HandoffArtifact` (`kernel/handoff.py:127`)
    from the raw output and the git probe;
  - `HopResult` (`tasks/domain/task.py:43`) records no prompt identity, and `PromptComposition`
    (`agent/ports.py:294-303`) has no hash or sources (`teams/identity.py:531`).

  Free measurement: bench `--policy p53-5` (the tool schema's bytes).
- **Goal:**
  1. `verdict` becomes `handoff` (`summary`, `filesChanged`, `verdict`, `assumptions`,
     `questions`), offered to every hop whose prompt declares `output: handoff/v1` (every
     built-in) and validated against the published schema. A gated step requires `verdict` in the
     call. `verdict` is deleted.
  2. `_build_hop_result` takes summary, verdict, assumptions and questions from the call; the git
     probe's `files_changed` and `diff` stay the record's. With no call, today's derivation
     applies.
  3. `parse_verdict` reads the artifact's field first and the marker second; the re-ask asks for
     the call.
  4. `HopResult.promptManifest` holds, per layer, `{name, version, sha256, scope, tokens}` from
     `_HopComposition.layers` (identity plus one message layer until P53-4 splits it), plus model,
     family, class and profile. `PromptComposition` gains `sha256` and `sources`. The field is on
     the task's `GET`.
- **Non-goals:** `questions` parking a task (a question that needs an answer is `consult`, D-72);
  a model-declared file list replacing git's; the layer split (P53-4); `hops/gates/post_hop.py`,
  which already reads `hop.artifact.verdict`.
- **Spec:**
  - `pod-dispatch.spec.md` ("Structured handoff artifacts", "Hop evidence"; MINOR);
  - `serve-read-api.spec.md` (additive; after P52-1's 5.1.0);
  - `operator-api.spec.md` (7.0.0 → 7.1.0, the additive field on the task's `GET`).
- **Change:**
  - `hops/application/verdict_tool.py` (becomes `handoff`);
  - `kernel/handoff.py` (`assumptions`, `questions`, the schema name);
  - `tasks/application/record.py::_build_hop_result`;
  - `pipeline/domain/plan.py::parse_verdict`;
  - `hops/application/runner.py::_reask_unmarked_verdict`;
  - `tasks/domain/task.py` (`HopResult.prompt_manifest`);
  - `agent/ports.py` (`PromptComposition`);
  - `teams/identity.py` (hash and sources; 659 lines, so new code goes in a new module if it
    would cross).
- **Acceptance:**
  - A reviewer hop whose fake model calls `handoff` with `verdict: "approve"` and two
    `assumptions`: the record's artifact carries both, `verdict` is `approve`, and the gate passes
    (`tests/integration/hops/test_handoff_artifacts.py`).
  - The same hop answering only with a marker line still yields the verdict (the fallback).
  - A `local` profile row and a verdict step: the closing call carries `tool_choice` naming
    `handoff`. This is the seam with P52-7, through the real catalog
    (`tests/integration/hops/driver/`).
  - `GET /tasks/<id>` shows `promptManifest` with the shipped prompts' sha256 values, which equal
    the files' (`tests/integration/interfaces/test_serve_tasks_endpoint.py`; the e2e Tack journey).
  - Persisted hops from before the card load, with an empty manifest (`extra="ignore"`, D-70).
  - Lane e2e green.
- **Contention:** Wave 3. `agent/ports.py` comes after P52-7; `record.py`, `task.py`, `handoff.py`,
  `plan.py`, `runner.py`, `identity.py` and `verdict_tool.py` are nobody else's in Wave 3. P53-8
  continues `task.py` in Wave 5.

### P53-6 — tools and calls per hop: one place decides what a hop sees (absorbs P52-7's surface)

**Status:** TODO (after P52-7 and P53-1) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour +
spec

- **Trigger:**
  - The request (ADR 0035 decision 9) and ADR 0033 decision 1: P52-7 declares `toolSurface:
    minimal` (`bash`, `read`, `verify`, and the closing tool when gated), and this card applies
    it.
  - An Implementer's schemas are about 5,800 chars on every request; `RoleArchetype` has no
    allow-list or call cap (`teams/role_schema.py:51-81`).
  - `agent/loop_steps.py::_ProgressDetector` (`:43-76`) already ends a turn on repeated rounds.
- **Goal:**
  1. The archetype and the pipeline step may declare `tools` (an allow-list) and `maxToolCalls`.
  2. `teams/role_composer.py` computes the hop's tools once: the profile's surface, then the
     allow-list, then the role's denied capabilities. An allow-list never grants a denied
     capability.
  3. `maxToolCalls` reached: the hop ends with a fixed message.
  4. A repeated identical call stays `_ProgressDetector`'s: the role or profile sets its limit,
     and no second detector is written.
- **Non-goals:** per-model heuristics; new tools; MCP tools' own capability rules (unchanged:
  denial by capability, never by name).
- **Spec:** `agent-loop.spec.md` (the surface, the cap, the detector's limit; renumber with
  P52-9); `pipeline-format.spec.md` (4.2.0 → 4.3.0, the step fields); `role-archetypes.spec.md`
  (the archetype fields).
- **Change:**
  - `teams/role_composer.py`;
  - `teams/role_schema.py` (`tools`, `maxToolCalls`);
  - `agent/loop_steps.py` (the cap; the detector's limit from config);
  - `agent/loop_types.py` (`LoopConfig.max_tool_calls`);
  - `pipeline/domain/spec.py` (step fields).
- **Acceptance:**
  - A real `local` catalog row: the Implementer's request carries only the minimal surface, and
    `request_part_bytes["tools"]` is under 2,500. A `hosted` row's payload is byte-identical to
    before (`tests/integration/hops/driver/`, through the real catalog: the seam with
    P52-7).
  - A reviewer with `tools: [read, bash]` and `deniedTools: [bash]` sees `read` only
    (`tests/unit/teams/test_role_composer.py`).
  - A step with `maxToolCalls: 3` and a fake model that calls four times: the hop ends after the
    third with the fixed message (`tests/integration/agent/loop/test_stop_conditions.py`).
  - Bench `--policy p53-6`: tool bytes per request before/after. Lane e2e green.
- **Contention:** Wave 3. `loop_types.py` comes after P52-7, and `role_schema.py` after P53-1.
  `role_composer.py`, `loop_steps.py` and `pipeline/domain/spec.py` are nobody else's.

### P53-7 — prompt variants by model class, and a floor a model must pass

**Status:** TODO (after P52-7 and P53-3) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour +
spec + CLI

- **Trigger:** the request (ADR 0035 decision 7). `model_class` is read only by
  `teams/model_selection.py:251` to pick a tier, so there is one prompt per role whatever the
  model. The CLI nests verbs under what they act on (D-57, ADR 0022), and a pod's configuration
  verbs live under `pod` (`interfaces/cli/commands/pod_config.py`).
- **Goal:**
  1. A role's prompts may exist per `modelClass`; the loader picks the variant matching the
     resolved model's class (from P52-7's profile), else `any`.
  2. `docket pod test <prompt>` runs the prompt's `tests` file against a configured model. The
     file holds cases (inputs) and assertions (`contains`, `matchesSchema`, `calledHandoff`,
     `underTokens`).
  3. A floor declared on the role makes the role refuse a model that failed it, with a fixed
     reason and no fallback. The result is recorded once per model and prompt sha256, through
     `platform/store.py`, under `state/`.
- **Non-goals:** sampling (P52-7); automatic re-testing; a test that edits files; a top-level
  `prompt` command (refused, ADR 0035).
- **Spec:** `config-format.spec.md` (the `tests` file format; after P53-3's bump);
  `model-profiles.spec.md` (the variant choice and the floor; after P52-7's 6.0.0).
- **Change:**
  - `teams/prompts.py` (variant choice, the `tests` format);
  - `teams/model_selection.py` (the floor);
  - `interfaces/cli/commands/pod_prompt.py` (new: `pod test`);
  - the CLI registry that adds `pod` verbs.
- **Acceptance:**
  - A role with `hop/implementer` for `cheap` and for `any`: a `cheap` model gets the `cheap`
    file and a `strong` one the `any` file, by sha256 (`tests/unit/teams/test_prompts.py`).
  - `docket pod test hop/reviewer` with a fake model that never calls `handoff`: it exits
    non-zero and the record holds `fail` for that model and hash, and a second run on the same
    hash reads the record (`tests/integration/teams/`).
  - A role whose floor that model failed: dispatch refuses with the reason
    (`tests/integration/hops/`).
  - `gen_cli_docs.py --check` and the goldens updated by `--write` only for the new verb's help.
- **Contention:** Wave 3. `teams/prompts.py` comes after P53-3; `model_selection.py` and
  `pod_prompt.py` are nobody else's.

### P53-8 — a structured `task` on `POST /tasks/<pod>`

**Status:** TODO (after P53-4 and P53-5) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour +
spec

- **Trigger:** the request (ADR 0035 decision 10). `POST /tasks/<pod>`
  (`interfaces/http/routes/task_create.py::post_task`, `:32`) takes a prose `description`; Tack,
  the plan of record, holds objective, acceptance and constraints as fields and flattens them. The
  consumer outside is Tack: named here, not built. The consumer inside is P53-4's `## Task`
  section, so the field is not unwired.
- **Goal:**
  1. An optional `task` object (`objective`, `doneWhen`, `acceptance`, `constraints`, `risk`,
     `answers`, `verify`, `kind`, `paths`) beside `description`, which stays for API 6 callers.
     When both are present, `description` is the title.
  2. The record keeps it (`TaskRecord.task`).
  3. `## Task` renders it in a fixed order, and its `paths` feed the bounded map.
- **Non-goals:** the CLI and MCP intake (later, on a request); Tack's adoption; a new contract
  version (additive).
- **Spec:** `operator-api.spec.md` (MINOR after P53-5's 7.1.0: the request body).
- **Change:**
  - `interfaces/http/routes/task_create.py`;
  - `tasks/domain/task.py` (`TaskRecord.task`);
  - `tasks/application/queue.py` (intake);
  - `hops/application/compose.py` (the `## Task` render).
- **Acceptance:**
  - `POST /tasks/<pod>` with `task.paths: ["src/app/"]` and `task.doneWhen`: the record holds the
    object, and the first non-Lead hop's `## Task` renders `doneWhen` and a map bounded to
    `src/app/` (the e2e HTTP journey; `tests/integration/interfaces/test_serve_tasks_endpoint.py`).
  - A body with `description` only is unchanged byte for byte (the API 6 tests).
  - An unknown key inside `task` gets a 400 naming it.
- **Contention:** Wave 5. `task.py` comes after P53-5 and `compose.py` after P53-4;
  `task_create.py` and `queue.py` are nobody else's.

### P53-9 — the docs say what shipped

**Status:** TODO (at the close of both phases) · **Size:** S · **Model:** Haiku · **Kind:** docs

- **Trigger:** the request; AGENTS.md: when work changes what is true, the README sentence changes
  in the same work. Phases 52 and 53 change the home layout, the authored forms, the CLI (`pod
  test`) and what a hop records.
- **Goal:** `docs/CONFIGURATION.md` (the four scopes, `config/` and `state/`, the `prompt` kind,
  `applied.lock`, references); `docs/recipes.md` (prompts in a recipe); `docs/AGENT-TEAMS.md`
  (layers, handoff, manifest); the README sentence that lists configuration kinds. Each claim is
  checked against the spec it names, then the code (CLAUDE.md "Correct spec, wrong prose").
- **Non-goals:** new guides; savings; counts quoted from the board.
- **Spec:** none.
- **Change:** the four documents.
- **Acceptance:** the agent-lane README tests green; `gen_cli_docs.py --check` green; every
  command the docs show runs on a fresh home (`docket init`, `pod update`, `pod validate`, `pod
  test --help`).
- **Contention:** after every card of both phases.

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
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 85 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge. What
      each check costs, measured, is in `.agents/skills/docket-spec-work/references/validation.md`.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, the generated-docs checks and the real run: once, at
      the phase close. The agent lane (about 5 min) runs on a committed tree: its release check
      refuses any uncommitted path.
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
