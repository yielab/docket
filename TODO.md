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
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

## ◆ ACTIVE — Phase 44: context in layers and a budget that counts new tokens (D-64, ADR 0028)

> Measured first: four real steps on 2026-10-18 counted 369,263 tokens; three stopped on the
> 100k budget and a finished critic verdict was discarded. Evidence and the decision:
> [ADR 0028](docs/adr/0028-context-in-layers-and-a-budget-that-counts-new-tokens.md). Packets:
> [.agents/handoffs/phase-44-worker-packets.md](.agents/handoffs/phase-44-worker-packets.md).
> **Phase acceptance:** on the replay bench every step *sends* under half today's input tokens,
> none reaches the budget under the new count, the critic's verdict is kept; then one real run of
> the same four steps (maintainer-approved, paid).
>
> **Wave 112 closed 2026-10-18.** Bench on the private copies (estimates labelled, per step
> implementer-a / implementer-b / critic / researcher): counted under the new rule 31,229 / 18,664 /
> 101,292 / 18,641 (old rule 101,248 / 84,340 / 101,292 / 82,383); with the `tool-output` policy
> sent 0.33 / 0.83 / 0.89 / 0.75 of today. The critic (0 % cache) is still over budget: it needs
> P44-4, P44-6 and P44-9. `read`'s window was cut to 6,000 characters with unpadded numbers at
> integration because the card's 400-line window sent more on two steps.
>
> **Wave 113 closed 2026-10-18.** Bench on the private copies with the composed `phase44`
> policy (tool output + K=2 condensation; estimates): sent 0.25 / 0.49 / 0.63 / 0.37 of today,
> counted under the new rule 11,584 / 12,502 / 64,979 / 12,147, so no step reaches the budget.
> The critic cannot send under half on a replay (its system and tool floor repeats on all 11
> calls, and the replay keeps its nine recorded re-reads that P44-5's delivered diff removes); the
> real run at the phase close is the measure. Integration moved the request measurement into the
> adapter (P44-10 had mirrored the wire encoders in core) and dropped a stale checkout note.
>
> | Wave | Cards | Depends on |
> | --- | --- | --- |
> | 112 | P44-1 bench · P44-2 budget · P44-3 tool output · P44-5 handoff — **closed 2026-10-18** | — |
> | 113 | P44-4 condensation · P44-6 prompt layers · P44-10 measurement fields — **closed 2026-10-18** | 112 merged |
> | 114 | P44-7 pod memory store · P44-9 `cache_control` — **closed 2026-10-18** | 113 merged |
> | 115 | P44-8 memory operator controls — **closed 2026-10-18** · phase close (paid real run of the four steps) **pending** | 114 merged |

### P44-1 — a replay bench over the four measured steps

- **Status:** DONE 2026-10-18 (`c49864a5`) · **Size:** M · **Model:** Sonnet
- **Trigger:** ADR 0028 "Acceptance for the phase": no change in this phase can claim a saving
  without before/after numbers, and no paid call may be used to get them.
- **Goal:** `scripts/maint/context_replay.py` reads session files (a directory argument) and
  prints, per step and in total: calls, sent input tokens, cached tokens, largest request,
  counted tokens under the current rule (`input + output`) and under the new rule (`input -
  cached + output`), whether the 100k budget is reached, and whether the final reply carries a
  verdict line. A `--policy` hook list re-projects each recorded request (bytes, scaled per call
  by the recorded measured/estimated ratio, labelled as an estimate). `--anonymize OUT` writes a
  shape-preserving copy: message structure, roles, tool names, argument keys, byte lengths,
  usage and the verdict line kept; every path segment and text replaced by a deterministic
  same-length placeholder (so a repeated absolute prefix stays repeated).
- **Non-goals:** the new policies themselves (P44-2..6 own them; their cards wire their hook);
  committing a real session.
- **Files:** new `scripts/maint/context_replay.py`, new `tests/fixtures/context-replay/v1/`
  (four anonymized steps: session plus its `llm_call` records), new test per
  `specs/test-framework.md` §"Lanes and placement".
  The real `session.json` files and the matching trace `llm_call` records are copied, read-only,
  into gitignored `internal-docs/context-replay/` (never a credential file).
- **Acceptance:** run on the real copies, the baseline reproduces the measured table (369,263
  counted; 25,806 largest request; per step 101,248 / 84,340 / 101,292 / 82,383; two steps over
  the budget and one refused by the prospective check at 84,340 + 12,730 + 4,096 reserve); run on
  the anonymized fixtures it
  gives the same counted totals; a grep of the fixtures for the private project's names, `/home/`
  and any key-shaped string prints nothing. Oracle: the recorded usage in the sessions.
- **RED test:** the bench test asserting the four-step baseline totals fails (no script).
- **Spec:** `specs/test-framework.md` only if the lane table needs the new fixture directory.

### P44-2 — the budget counts new tokens and accepts a paid final reply

- **Status:** DONE 2026-10-18 (`e5fe4962`) · **Size:** M · **Model:** Sonnet
- **Trigger:** ADR 0028 evidence: cache reads count at full weight (`TokenUsage.total_tokens`);
  the critic's `finish_reason=stop` reply was discarded 1,292 tokens over; no prospective check
  without a registered output bound; estimate 1.8x short; pod dollar estimate charges cache twice.
- **Goal:** `TokenUsage` gains `cache_write_tokens` and `counted_tokens` (`input - cached +
  output`); every budget comparison in the loop uses `counted_tokens`; a reply with no tool calls
  is accepted even when it crosses the budget (the turn ends `ok`); a backend with no output bound
  gets `config.DEFAULT_MAX_OUTPUT_TOKENS` as reserve; after the first call the input estimate is
  scaled by `max(1, measured/estimated)`; the adapter parses cache writes where the endpoint
  reports them; a hop's `usage` carries `input`, `cached`, `cacheWrite`, `output`;
  `_task_token_budget` uses the same count; `estimate_cost_usd` prices `input - cache_read` at the
  input rate.
- **Non-goals:** retried attempts in the budget (deferred, ADR 0028); trace/API fields (P44-10);
  any limit change.
- **Files/functions:** `core/llm.py::TokenUsage`; `core/agent_loop.py::_accumulate`,
  `_usage_delta`, `_resolve_context_bounds`, `_estimate_input_tokens` (calibration state on
  `_TurnState`), `_TurnState.effective_measured_tokens`, `prospective_budget_error`,
  `check_iteration_bounds`, `call_backend_and_handle_response`; `edges/adapters/llm.py` usage
  parser; `core/session.py` usage model; `core/dispatch.py::_hop_usage`, `_task_token_budget`
  only; `core/utils.py::estimate_cost_usd`; `config.py` (one constant).
- **Acceptance:** a stub backend reporting 30k input of which 25k cached, four calls, budget 20k:
  the turn is not stopped (counted 4 x 5k + output); a final no-tool reply that crosses the
  budget is persisted and returned `ok`; a tool-calling reply that crosses it is still refused;
  a backend with no `max_output_tokens` traces `request_fit` with a positive reserve; the dollar
  estimate for 1M input of which 900k cached equals `0.1M x in + 0.9M x cache_read`.
- **RED test:** `tests/unit/core/test_agent_loop.py` — final reply over budget is accepted
  (fails today with `stop_reason=token_budget`).
- **Spec:** `agent-loop.spec.md` (budget requirements), `cost-tracking.spec.md`,
  `operator-api.spec.md` (hop `usage` keys, additive).

### P44-3 — tool output has a budget

- **Status:** DONE 2026-10-18 (`64ae55b2`) · **Size:** S · **Model:** Haiku
- **Trigger:** ADR 0028 evidence: `glob **/*` 41,964 characters (78 % repeated prefix) re-sent
  four times; `read` whole-file 12,475 characters; `fetch` up to 200k bytes and offered with an
  empty allowlist (seven refused calls).
- **Goal:** `glob`/`grep` print paths relative to the first root, sort by path, skip
  `SKIPPED_DIRS` (`.git`, `node_modules`, `.venv`, `dist`, `build`, `target`, `vendor`,
  `__pycache__`), and pass through `_truncate`; `read` with no offset/limit returns the first
  `READ_DEFAULT_LINES` lines numbered, plus `[lines 1-N of M; call read with offset=N+1 for
  more]`; `fetch` output passes through `_truncate`; `builtin_registry` does not register `fetch`
  while `FETCH_ALLOWED_DOMAINS` is empty; the `read`/`glob`/`grep` descriptions state the rules
  (relative paths, ranges, search before listing).
- **Non-goals:** `.gitignore` parsing; changing `TOOL_MAX_OUTPUT_CHARS`.
- **Files/functions:** `edges/adapters/toolbox.py::glob_files`, `grep_files`, `read_file`;
  `edges/adapters/fetch.py::fetch_url` (tail only); `core/tools.py::builtin_registry` and the
  `read`/`glob`/`grep`/`fetch` tool descriptions only.
- **Acceptance:** a temp tree with 2,000 files under `src/` and a `node_modules/`: `glob **/*`
  output starts with `src/`, contains no root prefix and no `node_modules`, is sorted, and is at
  most `TOOL_MAX_OUTPUT_CHARS` plus the marker; `read` of a 1,000-line file returns
  `READ_DEFAULT_LINES` numbered lines and the remaining-lines footer; an `edit` whose
  `old_string` was copied from that window (without numbers) applies; `builtin_registry().specs()`
  has no `fetch` with an empty allowlist and has it with one domain.
- **RED test:** `tests/unit/edges/adapters/test_toolbox.py` — glob prints relative paths.
- **Spec:** `agent-loop.spec.md` (built-in tools), `security-gates.spec.md` (fetch offering).

### P44-5 — every writing hop delivers what it produced

- **Status:** DONE 2026-10-18 (`e80a1e03`) · **Size:** S · **Model:** Sonnet
- **Trigger:** ADR 0028 evidence: the critic re-read and re-sent the researcher's note nine
  times (~30k tokens) because `_implementer_diff_probe` serves the `implementer` role only and
  `diff_ref` is a branch name.
- **Goal:** the probe runs for every role whose hop changed the tree; the artifact carries a
  capped `diff` (tracked changes plus the content of new files, `HANDOFF_DIFF_MAX_CHARS`, with a
  marker when cut); `diff` is first in `DROP_ORDER`; the next hop's message renders it once,
  after the summary.
- **Non-goals:** the list of files a hop read; changing verdict parsing or gates.
- **Files/functions:** `core/dispatch.py::_implementer_diff_probe` (renamed `_hop_diff_probe`),
  `_build_hop_result`; `core/handoff.py::HandoffArtifact` (field, `DROP_ORDER`, `render`);
  `edges/adapters/system.py` (one helper for new-file content if needed).
- **Acceptance:** a two-step pipeline (researcher writes `notes/x.md`, critic reviews) on the
  stub endpoint in a temp home: the critic's first request contains the note's content once;
  a 50k-character note is cut at the cap with the marker; a read-only hop that changed nothing
  adds no `diff`. Oracle: the critic's recorded first request.
- **RED test:** `tests/integration/` — critic's first request contains the researcher's note
  (fails today: only the summary is passed).
- **Spec:** `pod-dispatch.spec.md` ("Hop evidence", handoff).

### P44-4 — history inside a step does not grow quadratically

- **Status:** DONE 2026-10-18 (`6d42237d`) · **Size:** M · **Model:** Sonnet
- **Trigger:** ADR 0028 evidence: 64 % of counted tokens were old tool results re-sent; the
  bench (P44-1) gives K=1 -53 %, K=2 -39 %.
- **Goal:** when a request is built, tool results older than the last `K` results become a
  one-line notice naming the tool, the path or command and the size; large `write`/`edit`
  arguments in old assistant messages become `[wrote <path>: N characters]`; errors stay short,
  the newest result stays whole; the projection is deterministic and never touches
  `session.json`; K is chosen with the bench and recorded with its numbers; the bench gains the
  `condense` policy hook calling the real function.
- **Non-goals:** changing compaction; summarising with a model.
- **Files/functions:** a new pure function in `core/session.py` or `core/context.py`, called
  from `core/agent_loop.py::_TurnState.messages_for_durable` (or the single request-building
  point the worker locates); `scripts/maint/context_replay.py` hook table.
- **Acceptance:** a session of six read results: the request holds K whole results and six-K
  notices; two consecutive requests share a byte-identical prefix up to the newest notice;
  `session.json` is unchanged; on the bench the step that re-sent `glob` four times sends it once.
- **RED test:** request built after six tool results contains six full results (today).
- **Spec:** `session-history.spec.md`, `agent-loop.spec.md`.

### P44-6 — the prompt in layers, stable first

- **Status:** DONE 2026-10-18 (`323e467a`) · **Size:** M · **Model:** Sonnet
- **Trigger:** ADR 0028 evidence: roots in the middle of the system prompt, HEARTBEAT's per-task
  block after them, member files contradicting the live contract, `<promise>DONE</promise>` with
  no reader, a `glob **/*` to discover the tree.
- **Goal:** `_runtime_startup_contract` carries no roots; the roots and a derived repository map
  (directories with file counts from `git ls-files`, relative, capped) go in the task message;
  HEARTBEAT.md and TOOLS.md are not composed in a pod task; MEMORY.md is composed only when it
  holds more than its template; the archetype templates lose every instruction the contract
  forbids, the absolute codebase paths and `<promise>DONE</promise>`, and gain one shared
  strategy block (start from what was delivered and the map, `grep` for concrete symbols, read
  by ranges, never list the whole tree, never re-read what the message carries); step prompts
  add only their own output contract; `POD_TEMPLATE_VERSION` 4 so `docket pod update`
  regenerates members without touching MEMORY.md.
- **Non-goals:** pod memory (P44-7); `cache_control` (P44-9).
- **Files/functions:** `core/identity.py::compose_system_prompt`, `_runtime_startup_contract`,
  `_runtime_workspace_context`, `_RUNTIME_CONTEXT_FILES`; `core/archetypes.py` templates;
  `core/pod_provisioning.py::POD_TEMPLATE_VERSION`; `core/dispatch.py::_hop_message`;
  `edges/adapters/system.py` (`git ls-files` helper); a new `core/repo_map.py`.
- **Acceptance:** two tasks of the same member in different worktrees compose byte-identical
  system prompts and tool schemas; the task message names the worktree root and holds the map;
  a pod-task prompt contains no HEARTBEAT text; no template contains `HEARTBEAT`, `memory/`,
  `promise` or an absolute path; `pod update` on a v3 member rewrites SOUL/AGENTS and leaves
  MEMORY.md byte-identical.
- **RED test:** two tasks' system prompts differ today (roots).
- **Spec:** `workspace-structure.spec.md`, `role-archetypes.spec.md`, `agent-loop.spec.md`.

### P44-10 — measurable without reconstruction

- **Status:** DONE 2026-10-18 (`b2677337`) · **Size:** S · **Model:** Haiku
- **Trigger:** ADR 0028 point 8: the measured table had to be rebuilt by hand from sessions.
- **Goal:** each `llm_call` trace event carries `request` = bytes and estimated tokens for
  system, tools, tool results, assistant text and user; the task's `byModel` carries `input`,
  `cached`, `cacheWrite`, `output` (and `reasoning` when reported); `GET /tasks/<pod>/<id>` and
  the pod read routes report `tokenBudget` (the per-step budget docket enforces).
- **Non-goals:** a new route; changing `hop_finished`'s existing fields.
- **Files/functions:** `core/agent_loop.py::_trace_llm_call`; `core/dispatch.py::_finalize_task`
  (`byModel` only); `serve.py` (the field); `trace-store` event schema.
- **Acceptance:** a stub run's `llm_call` payload has the five parts summing to the request's
  bytes; `byModel` sums equal the hops' usage; the API field equals the configured budget.
- **RED test:** `llm_call` payload has no `request` today.
- **Spec:** `trace-store.spec.md`, `operator-api.spec.md` (additive, API 5).

### P44-7 — pod memory: store, parse, verify, render

- **Status:** DONE 2026-10-18 (`1171ca16`) · **Size:** M · **Model:** Sonnet
- **Trigger:** ADR 0028 point 7 and evidence: MEMORY.md is never filled in a pod task and the
  daily-log pipeline has no writer there.
- **Goal:** `core/pod_memory.py` over `edges/store.py` (`memory.json` per pod): typed entries
  (`generated`, `command`, `pitfall`, `convention`), provenance, dedupe, count cap; a parser for a
  hop's trailing memory section; `pre_input` screening; automatic acceptance of verifiable
  `generated`/`command` entries (path at the task commit, exit status in the task trace), pending
  state for the rest; no automatic entry from a hop that called `fetch`; render into the system
  tail under the repository frame, entries whose path is gone omitted; `memory_update` trace and
  audit entry; the pod-task daily-log seeding and distillation deleted (D-57).
- **Non-goals:** operator commands and inbox approval (P44-8).
- **Files/functions:** new `core/pod_memory.py`; `core/dispatch.py::_finalize_task` (one call);
  `core/identity.py` (render tail); `core/memory.py` (deletions).
- **Acceptance:** a hop ending with two `generated` entries (one existing path, one missing) and
  one `pitfall`: one accepted, one refused, one pending; the next task's system prompt carries the
  accepted entry under the untrusted frame; an entry with imperative free text is refused; a hop
  that called `fetch` stores everything pending.
- **RED test:** accepted entry absent from the next task's prompt (today).
- **Spec:** `workspace-structure.spec.md`, `agent-loop.spec.md`, `trace-store.spec.md`.

### P44-9 — `cache_control` for Anthropic models

- **Status:** DONE 2026-10-18 (`5df30da4`) · gateway verified 2026-10-18: two identical calls to `anthropic/claude-sonnet-5.5` through `ai-gateway`, input 7,529 each, cache write 7,525 then cache read 7,525 · **Size:** S · **Model:** Sonnet
- **Trigger:** ADR 0028 evidence: 0 % cache over 11 calls for the Anthropic critic.
- **Goal:** for a provider/model the catalog marks as Anthropic, the request marks
  `cache_control` at the end of the stable prefix (system) and on the last message; other
  dialects are byte-unchanged.
- **Non-goals:** changing the dialect set.
- **Files/functions:** `edges/adapters/llm.py` request builder; the catalog flag in
  `core/provider.py` if one is needed.
- **Acceptance:** a captured request for an Anthropic model carries two markers; an OpenAI model's
  request is byte-identical to today. **Integrator, after merge and with maintainer approval:**
  one real call through the gateway shows `cached > 0` on the second request.
- **RED test:** captured Anthropic request has no `cache_control` (today).
- **Spec:** `agent-loop.spec.md` or the provider spec the worker locates.

### P44-8 — pod memory: operator controls

- **Status:** DONE 2026-10-18 (`357ca9bd`) · **Size:** S · **Model:** Sonnet
- **Trigger:** ADR 0028 point 7: pending entries need approval; every change must be visible
  and revertible.
- **Goal:** pending `pitfall`/`convention` entries appear in `docket inbox` and are approved or
  refused there (audited); `docket pod memory list|revert <id>|reset` (confirmed, audited).
- **Files/functions:** `core/inbox.py`, `cli/_pod.py`, `core/pod_memory.py` (API only).
- **Acceptance:** approve moves an entry to accepted and into the next prompt; revert removes it
  with an audit entry; reset empties `memory.json` after confirmation; goldens for `pod --help`
  regenerated and explained.
- **RED test:** `docket pod memory list` is an unknown command (today).
- **Spec:** `operator-loop.spec.md`, `cli-interface.spec.md`.

## ◇ FOLLOW-UPS WITH TRIGGERS — found in Phase 43 (not cards; triage when a trigger fires)

- **Found in Wave 115 (Phase 44).** Pending memory entries show in `docket inbox` (text and
  `--json`) but not in `GET /inbox`, MCP `inbox`, notifications or Telegram `/status`: that needs
  an operator-v1 inbox contract bump and `notify.py`/`telegram.py` edits (operator-loop item 7's
  "`GET /inbox` equals `inbox --json`" was already broken by approved-ready tasks).
- **Found in Wave 114 (Phase 44).** `core/telemetry.py` has no structural key for
  `memory_update` (the generic handler serves it); members stamped `POD_TEMPLATE_VERSION` 4 before
  P44-7's method line show stale to `pod update` by text comparison (v4 never shipped);
  `scripts/smoke_workflow.py`'s memory scenario now seeds MEMORY.md directly and needs a live run.
- **Found in Wave 113 (Phase 44).** `_resolve_hop_instructions` still opens "You are the
  Implementer..." (SOUL says it); recipe roles using `${codebaseOrConfigured}` (secure-build
  security-vetter) still render a path; `cli/_agents._create_workspace` (standalone agents)
  still writes HEARTBEAT/promise text; `repo_map.SKIPPED_DIRS` mirrors `toolbox.SKIPPED_DIRS`
  (pinned by an equality test); a condensation notice carries the call's full path; the task's
  top-level `usage` lacks `cached`/`cacheWrite` (only `byModel` has them); pod read routes do
  not carry `tokenBudget`.
- **Found in Wave 112 (Phase 44).** The prospective budget check compares the whole calibrated
  input estimate plus reserve against the counted budget, so a heavily cached step is refused
  early; discount by the previous call's cache reads if a real run is refused with room left.
  `glob`/`grep` still walk vendored trees before filtering (pathlib cannot prune); measure before
  changing. In an in-place task on an already dirty tree, the first writing hop's `diff` carries
  the operator's own changes once (task worktrees start clean). The bench scales cached tokens by
  the sent ratio; P44-4 may need a cache-aware projection.
- **The Lead plans with the codebase path, the Implementer is rooted in the task worktree**
  (measurement 3: `tool.refused` on `read` of the codebase path, audit seq 6-7 of the throwaway
  home). The Lead's hop should name the task worktree, or the handoff should rewrite the path.
  Reproduce with any local-model dispatch in a worktree pod before scheduling.
- **Parallel tasks in a pod** -- trigger in ADR 0027 point 10. The task record and the claim
  are already per task; a card would add a `maxParallelTasks` pod setting and a bounded pool in
  `dispatch_pod`.
- **Warm workspace** -- trigger in ADR 0027 point 10 (measured 6.5 s + 15.5 s, 829 MB).
- **A task's `network: none` cuts the agent turn only** (P43-4): `verifyCmd` and `run:` steps keep
  the pod's posture; the spec says so. A parallel group's merge in `_run_group_node` drops
  `_UnitOutcome.failure_kind`, so a budget stop inside a group loses `budget`.
- **Two enqueue entry points** (P43-1): `enqueue_task` returns the task, `enqueue_task_once`
  returns `(task, created)`; fold into one when the remaining callers (`telegram.py`, `_mcp.py`)
  are next touched. A raced duplicate `idempotencyKey` under `require_approval` can leave an
  orphan approval token.
- **`trace-store.spec.md` requirement 6 says "exactly"** but the code's `EVENT_TYPES` has members
  the list never named (found by P43-2); re-derive the list from the frozenset.
- **A team's skills** (P43-7): `core/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope. `init --help` and `--name` do not mention
  teams, and the `docket pod update .docket` hint in `cli/_agents.py::_changed_since_review` is
  not team-aware.
- **Queue counts twice** (P43-6): `core/pod_report.py::task_counts` and the inline Counter in
  `cli/_status.py` (~lines 138-164) compute the same mapping; point `status` at `task_counts`.
  `pod_report._caller_default` reads `sys.stdin.isatty()`, so under `docket start` the report's
  approval default depends on the daemon's stdin.
- **`POST /pods/<p>/apply` edges** (P43-8): a pod with no recorded codebase reviews against
  `directory.parent`; an all-skip apply writes no `pod.apply` audit entry (pre-existing rule).
- **Corrections cursor** (P43-9): a client must percent-encode `+` in `since` (a raw `+` decodes
  to a space and is `400`); a pod whose Lead was removed but whose ledger remains answers `404`
  (existence is `dispatchable_pods()`, the same rule as `GET /pods`).
- **Dead after the harness deletion** (P43-12, proven by `rg`): the `inPlace` meta key has no
  writer (reader `core/dispatch.py::_ensure_task_worktree`, `docs/CONFIGURATION.md`,
  `specs/data/docket-meta.spec.md`; `tests/unit/core/test_task_worktrees.py` sets it by hand);
  the `verify["touched"]` key (`dispatch.py` around `_evaluate_mechanical_gate`,
  `system.git_worktree_fingerprint`, `core/evidence.py`) only fed the harness `files`; evidence
  1.0.0 (`task_evidence(..., "1.0.0")`, `EVIDENCE_V1`, `docs/contracts/evidence-v1`,
  `scripts/gen_evidence_schema.py`) has no `src` caller. Delete under D-57 when the next card
  touches `core/dispatch.py` or `core/evidence.py`.
- **Cancel over HTTP reports `cancelled` once the stop is requested** (P43-10): the task stays
  `running` in the store until the executor notices; a consumer polls `GET /tasks/<pod>/<id>`.
  The slow-stub cancel path is not covered by a test (the test seeds a run record).
- **`cli/_task.py::_pod_codebase`** is a second reader of the implementer's codebase beside
  `core/pod_report._codebase` and `core/dispatch.task_diff`; one core helper when next touched.
- **Real-Docker tests over their duration ceiling under load** (`test_network_lockdown.py`,
  `test_sandboxed_exec.py`, `test_escape_matrix.py[docker]`): pass alone, fail when five suites
  run at once. A flake, not a regression; measured 2026-10-14.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (bounded):** use `$docket-roadmap` to load the active card, its named ROADMAP
   decision/section, the owning spec, and the card's own "Read" list. Do not ingest all of
   `ROADMAP.md`, `TODO.md`, or local `CLAUDE.md` as startup context.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. docket-owned JSON goes
   **only** through `edges/store.py` (JSONL append logs are the one D-12 exemption), external
   protocols terminate in `edges/adapters/`, and there is no compatibility layer for the retired
   daemon. Every shell-out goes through `edges/adapters/`. `core/`/`edges/` never import `ui.py` or
   print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds new
   CLI surface — those cards say so and require regenerated goldens with the diff explained.
   **Regenerating a golden to paper over an unintended behaviour change is never acceptable**; W-6 in
   particular must prove the four legacy roles still emit byte-identical workspaces.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `bash scripts/validate-specs.sh` green · `uv run python scripts/gen_cli_docs.py --check` green
   (regenerate `docs/commands.md` whenever a Typer docstring or help text changes) · `uv run pytest
   tests/agent` green when prose or an artifact moved · the integrator re-measures
   `scripts/metrics.py --check` per batch (card branches that add tests fail it by design) · the
   card's own spec updated with a version bump + changelog entry (integrator-applied in a
   multi-agent wave), **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model (D-52, amending D-31):** **`develop`** is the integration branch. Every card
branch or isolated worktree bases on `develop` and is integrated into `develop` without
rewriting history. **`main`** stays the canonical public/default and release lineage: it moves
only by a fast-forward (or a merge) from `develop`, when the maintainer cuts a release or
decides `main` has fallen too far behind. Tags and release jobs still originate from `main`.
`platform` may remain as a synchronized historical ref, but it is not a release source.

---


