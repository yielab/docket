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

## ▶ PHASE 45 — ACTIVE — a prepared checkout, models from the provider, and a check the change cannot define (D-65, ADR 0029; opened 2026-10-19)

> **Evidence.** Fabulada's first code run through a team, through Tack, on 2026-10-19:
> [ADR 0029](docs/adr/0029-a-prepared-checkout-models-from-the-provider-and-a-check-the-change-cannot-define.md)
> "Evidence". It is also the trigger D-63 named for the deferred **warm workspace** (ADR 0027
> point 10), so P45-1 consumes that follow-up. The per-step token limit needs no card: every run
> Tack sends carries `maxTokens` (Tack ADR 0086 decision 5) and `core/dispatch.py::_gate_task_tokens`
> already hands each hop what is left of it.
>
> **Shape.** Four cards, one per ADR point, plus the real run. Items from the follow-ups list ride
> along only where the card already edits that file or function; the rest stay in the follow-ups
> section, untouched.
>
> **Planning measurements (2026-10-19, `f2e9b956`).**
> - Nothing on the dispatch path reads `core/reviewed_repos.py` (callers: `cli/_status.py`,
>   `cli/_run.py::_pick_up_repository`, `cli/_agents.py`, `core/pod_apply.py::review_decision` /
>   `apply_directory`). P45-3 therefore makes the files a reviewed command names protected paths,
>   so the agent's own edit to them parks for a person, instead of adding a claim-time check.
> - The "4,096 output cap" is a reserve, not a request field:
>   `core/agent_loop.py::_resolve_request_limits` uses `config.DEFAULT_MAX_OUTPUT_TOKENS` for the
>   window and budget checks only and sends no `max_tokens` when the endpoint registers none. A
>   reply cut at 4,096 came from the provider's default; P45-2 reproduces it first.
> - The local llama.cpp `/v1/models` publishes `meta.n_ctx` 32768 (served) and `meta.n_ctx_train`
>   262144 (training); the field map is per shape and pinned by recorded bodies.
> - `jail_launch(..., network=)` takes the network per launch, and `dispatch_pod`'s
>   `claimRefusal` -> `_refuse_claimed_task` fails a task before any hop with a `failureKind`;
>   `prepare` reuses both.
>
> **Interface for Tack (provisional until P45-1 lands; Tack builds against it, ADR 0086).**
> `POST /tasks/<pod>` accepts `prepare` (string; `""` off; absent = the team's `prepare:`, else the
> lockfile's command). New `failureKind` values `prepare` (before any hop, the command's output as
> reason) and `check_changed` (on deny, `checkChanged: [paths]` on the task). Tack sends `prepare`
> only when `apiVersion` is `"6"` or later.
>
> **Before Wave 117 (operator steps, refused to agents by the permission classifier):** reinstall
> the service venv, replace the installed `block-destructive.yaml` from the template, restart
> `docket start`. Retired, not carried: the Phase 39 "Tack `harness run` -> `exec` string" item;
> `exec` was deleted in Phase 43 and Tack sends work over HTTP.
>
> **Worker packets** §0: `uv run --extra mcp` for `mypy src` and `scripts/gen_cli_docs.py --check`
> (worker worktrees lack `click`/`anyio` otherwise; every Wave 116 worker hit it).
>
> **Phase acceptance:** Fabulada's code task through Tack prepares its worktree from the lockfile
> (the second task with the same lockfile prepares in seconds), runs eslint, vitest and the
> project's own `tsc`, and finishes or parks on `check_changed`; `setup provider show` names every
> limit it uses or says `unknown`; two teams on one codebase keep both approvals.
>
> | Wave | Cards | Ownership (no two lanes share a function) | Depends on |
> | --- | --- | --- | --- |
> | 117 | P45-1 prepare · P45-2 limits from `/models` · P45-4 approvals as a set | P45-1: new `core/prepare.py`, `core/dispatch.py::dispatch_pod` claim loop, `core/task_options.py`, `serve.py` field map + `SERVE_API_VERSION`, a `prepare` RunItem in `core/pod_apply.py` (new function), `pod.schema.json`. P45-2: `edges/adapters/llm.py`, `core/provider.py`, `core/agent_loop.py::_resolve_request_limits`/`_trace_llm_call`, `templates/providers/`, `cli/_provider.py`. P45-4: `core/reviewed_repos.py` keying, `core/pod_apply.py::review_decision`/`apply_directory`/the two `lookup` readers, `cli/_status.py`, `cli/_run.py`, `cli/_agents.py` | — |
> | 118 | P45-3 protected paths | `core/protected_paths.py` (new), `core/reviewed_repos.py::_digest`, `core/dispatch.py::_run_pipeline` done path/`_finalize_task`/`_pin_hop_tree`/`_run_group_node`/`_ensure_task_worktree`, `core/pod_apply.py::plan_apply`, `pod.schema.json` | 117 merged |
> | 119 | P45-5 the real run and the close | board, ROADMAP, CHANGELOG | 118 merged |

### P45-1 — docket prepares the worktree it makes

**Status:** READY · **Size:** M · **Model:** Sonnet

- **Trigger:** ADR 0029 point 1: in a fresh Fabulada worktree `Cannot find package 'eslint'`,
  `Cannot find module 'vitest/config'`, and the machine's `tsc` 7.0.2 against the project's 5.9.3.
- **Goal:** after the claim checks, `dispatch_pod` prepares the task worktree. The command is the
  task's `prepare`, else the team's `prepare:` in `pod.yaml`, else derived from the lockfile at the
  worktree root (`package-lock.json` -> `npm ci`, `pnpm-lock.yaml` ->
  `pnpm install --frozen-lockfile`, `yarn.lock` -> `yarn install --immutable`, `uv.lock` ->
  `uv sync --frozen`, `poetry.lock` -> `poetry install`, `Cargo.lock` -> `cargo fetch`); `""` or
  `prepare: none` turns it off; no lockfile and no command runs nothing. It runs through
  `jail_launch(..., network=True)` when isolation is on (the hops keep the pod's network) and on
  the host like `verifyCmd` when it is off. The install output is kept once per codebase and
  lockfile hash under `DOCKET_HOME/cache/prepare/`, built under a file lock, linked into each
  worktree, readable (not writable) by the hops' jail, three entries kept per codebase. A team's
  or derived command is a reviewed item (kind `prepare`); a task's own `prepare` is on the task
  record before it runs. A failure fails the task with `failureKind: "prepare"` and the output
  tail, before any hop. A `prepare` trace event records command, source, cache hit, seconds,
  exit. `SERVE_API_VERSION` becomes `"6"`.
- **Non-goals:** guessing without a lockfile; container images per project.
- **Acceptance:** a fixture repo with `package-lock.json` and one dev dependency: the implementer
  hop finds `node_modules/.bin/<tool>`; the second task with the same lockfile is a cache hit; a
  broken lockfile fails `prepare` with no hop and no tokens; `prepare: ""` skips it; with isolation
  on, a hop cannot write the cache entry and its network is the pod's (escape-matrix rows).
  Oracle: task record, trace, the hop's tool result.
- **RED test:** the fixture repo has no `node_modules` after claim.
- **Gates:** full default lanes, `pytest-without-sandbox.sh`, escape matrix, goldens,
  `gen_cli_docs --check`.
- **Spec:** `pod-dispatch.spec.md`, `operator-api.spec.md` (field, version 6, `failureKind`),
  `pod-blueprints.spec.md` (`prepare:` reviewed), `trace-store.spec.md` (event), sandbox spec.

### P45-2 — a model's limits come from the provider's `/models`

**Status:** BLOCKED on the maintainer's prices decision (below) · **Size:** M · **Model:** Sonnet

- **Trigger:** ADR 0029 point 2: an id outside the shipped rows gets no window and no output bound
  (`edges/adapters/llm.py::endpoint_from_spec`); 49 of 49 `request_fit` events in the joint run
  said `unknown_window` (gateway).
- **First step:** reproduce the 4,096 cut on a model with no registered bound and cite where it
  comes from.
- **Goal:** `probe_models` returns each advertised id's window and output cap through one
  per-shape field map (Anthropic `max_input_tokens`/`max_tokens`; llama.cpp `meta.n_ctx`, never
  `n_ctx_train`; OpenRouter `context_length`/`top_provider.max_completion_tokens`; the gateway as
  its recorded body shows; anything else unknown). Observed limits go to a docket-owned
  `provider-models.json` (via `edges/store.py`, with the date) at `setup provider add` and once a
  day in the `docket start --dispatch` sweep. `endpoint_from_spec` resolves operator-declared >
  observed > unknown; a known output cap is sent as `max_tokens`. The shipped templates lose their
  `contextWindow`/`maxTokens` rows. `setup provider show` and `pod report` print each limit's
  source (`declared`, `observed <date>`, `unknown`).
- **Rides along (same files):** `request_part_bytes` measures UTF-8 (18,037 B against 11,367 B
  measured for a non-ASCII part); `llm_call` carries `cacheWrite` when reported.
- **Decision needed before claim (maintainer):** ADR 0029 says templates keep "only connection
  data", but prices feed the labelled estimate and budget auto-pause and `presets` feed the rank
  anchors. Recommended: remove limits only; keep `price`/`pricesAsOf`/`presets`.
- **Non-goals:** refusing an unadvertised step `model:`; prices from the provider.
- **Acceptance:** recorded `/models` bodies (llama.cpp from `127.0.0.1:8081`, Anthropic,
  OpenRouter, the gateway; scrubbed) yield the published limits, the llama.cpp window is 32768;
  `rg 'contextWindow|maxTokens' src/docket/templates/providers` prints nothing; a never-observed
  model shows `unknown`, never a filled-in number. Oracle: the recorded bodies.
- **RED test:** the llama.cpp body parsed to `n_ctx`.
- **Gates:** full default lanes, goldens, `scripts/metrics.py --check`.
- **Spec:** `model-profiles.spec.md`, `agent-loop.spec.md` (reserve), `trace-store.spec.md`
  (`llm_call`).

### P45-3 — a change that edits its own check goes to a person

**Status:** TODO after Wave 117 · **Size:** M · **Model:** Sonnet

- **Trigger:** ADR 0029 point 3: a gate such as `npx eslint` reads configuration the agent edits;
  `reviewed_repos.py` hashes only the command text.
- **Goal:** protected paths are the defaults (lockfiles, `package.json`, `pyproject.toml`,
  `Cargo.toml`, lint/type/test configuration, `.docket/`, `prill.yaml`, CI workflows), the team's
  `protects:` in `pod.yaml` (adds only), and every tracked file a reviewed command names. When a
  pipeline ends `done` and `git diff --name-only <baseCommit>..<branch>` touches one, the task
  parks `waiting_approval` (approval kind `check_changed`, `checkChanged: [paths]`) whatever the
  profile, lights-out included; grant -> `done`, deny -> `failed`/`check_changed`. The review digest
  includes the blob id of each file a command names, so `pod update` and `docket run` ask again
  after such a file changes.
- **Rides along (same functions):** `_pin_hop_tree` cuts a subject at a word boundary;
  `_run_group_node` keeps `failure_kind` (a budget stop in a group says `budget`); the dead
  `inPlace` key in `_ensure_task_worktree`; the stale `.env\b.*write` paragraph in
  `security-gates.spec.md`.
- **Non-goals:** restoring files before a gate; a claim-time review check.
- **Acceptance:** a stub task editing `package.json` under `lights-out` parks naming it;
  `task approve` -> `done`, `task deny` -> `failed`/`check_changed`; a task editing `scripts/check.sh`
  behind gate `bash scripts/check.sh` parks; a task editing only `src/` ends `done`. Oracle: task
  record, audit entries with their channel.
- **RED test:** the lights-out `package.json` case.
- **Gates:** full default lanes, goldens, `validate-specs.sh`.
- **Spec:** `pod-dispatch.spec.md`, `operator-api.spec.md`, `operator-loop.spec.md`,
  `pod-blueprints.spec.md` (`protects:`, digest), `security-gates.spec.md`.

### P45-4 — approvals are kept per codebase and team, as a set

**Status:** READY · **Size:** S · **Model:** Haiku

- **Trigger:** ADR 0029 point 4: one entry per codebase, overwritten; two pods' approvals 0.3 s
  apart in `audit.log`, the second replacing the first.
- **Goal:** `reviewed-repos.json` keys by (resolved codebase, pod) and keeps every approved digest;
  `is_reviewed` is true for any of them; `code_mismatch` diffs against the pair's latest approval;
  `repo.allow` audits `pod=`. An old one-entry file is ignored and asked again once (D-57;
  CHANGELOG says so).
- **Rides along (same functions):** `POST /pods/<p>/apply` on a pod with no recorded codebase
  refuses instead of reviewing against `directory.parent`; the `_changed_since_review` hint names
  `teams/<pod>/` when the repository keeps teams.
- **Acceptance:** two pods on one codebase approved in turn both answer `go`; returning to an
  earlier approved set asks nothing; a third set asks with only its changed items. Oracle:
  `review_decision` and the file.
- **RED test:** the second pod's approval removing the first's.
- **Gates:** full default lanes, goldens, `gen_cli_docs --check`.
- **Spec:** `pod-blueprints.spec.md`, `operator-api.spec.md`, `cli-interface.spec.md`.

### P45-5 — the real run, and the phase close

**Status:** TODO after Wave 118 · **Size:** M · **Model:** integrator, maintainer-approved, paid

- **Goal:** Fabulada's code task through Tack on the merged tree, against the operator's
  `~/.docket`: per step sent/counted/largest request, prepare seconds and cache MB, every
  `failureKind`. Write down, without acting on them, the observed values for the follow-up
  triggers this run can see: a parked turn paid twice, the implementers' sent ratio, hop report
  language, the W116-10 re-read count, `unknown_window` events. A trigger that fires becomes a
  card afterwards, not inside this one.
- **Acceptance:** the phase acceptance, met or stated as partly met with numbers; ROADMAP row 45
  dated, CHANGELOG `[Unreleased]`, board archived with `split_board.py archive`.
- **Gates:** every gate in CLAUDE.md "Running tests", in a clean worktree.

## ◇ FOLLOW-UPS WITH TRIGGERS — found in Phases 43-44 (not cards; triage when a trigger fires)

> Items a Phase 45 card absorbed moved into that card on 2026-10-19 (the gateway window, the
> measurement gaps, the cut commit subject, the group `failure_kind`, the stale `security-gates`
> paragraph, the `inPlace` key, the apply-without-codebase edge, the team-aware hint, the worker
> packet note, the warm workspace, and "no `node_modules` is pod configuration", which ADR 0029
> reversed).

- **Found integrating Wave 116 batch A (2026-10-18).**
  - **Shell keywords are classified as binaries when unjailed.** `for t in a; do ...; done` asks
    with `'for' is not on the curated allowlist` (also `do`, `done`, `if`, `then`, `while`).
    Jailed, the allowlist stands down and the loop runs. Pre-existing; the run's parked command
    ends in such a loop, so it still asks without the sandbox. Trigger: an operator running
    without isolation reports it.
- **Found in the 2026-10-18 joint run (Wave 116 evidence).**
  - **A parked turn is paid twice.**
    - The development `red` step spent 100,573 input tokens before parking.
    - Its `approve_task` grant went unused: the re-run hop never re-issued the call.
    - The resume added a compaction call (9,065 in) and a cold first call.
    - Trigger: after W116-1..4, a real run that still parks on a write.
    - Then: weigh resuming the session over re-running the hop (operator-loop §2 item 6 keeps
      this a non-goal today).
  - **Hop language drift.** The resumed Sonnet `red` step wrote its final report in Chinese, and
    that report became the `green` step's handoff. This happened once.
    - Trigger: a second occurrence.
    - Then: a pod `language` setting rendered into the handoff instruction.
- **Found at the Phase 44 close.** The two implementer steps of the real rerun did not send under
  half (0.77, 0.80): every request shrank to a fifth to a third, but the trajectories grew (12 and
  20 calls against 8 and 5), partly from retrying a toolchain the jail could not load (now a grant
  and a 126 message). Trigger: a real implementer run with the needed grants declared that still
  sends over half of its 03:38 counterpart; then measure which calls repeat before cutting
  anything. No grant is declared on this machine's live home (the operator's call). The rerun's
  pod names are in already-pushed history (ADR 0027, the operator API spec, a test); the tree
  no longer carries them, and rewriting public history is the maintainer's call.

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
  (pinned by an equality test); a condensation notice carries the call's full path; pod read
  routes do not carry `tokenBudget`.
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
- **A task's `network: none` cuts the agent turn only** (P43-4): `verifyCmd` and `run:` steps keep
  the pod's posture; the spec says so.
- **Two enqueue entry points** (P43-1): `enqueue_task` returns the task, `enqueue_task_once`
  returns `(task, created)`; fold into one when the remaining callers (`telegram.py`, `_mcp.py`)
  are next touched. A raced duplicate `idempotencyKey` under `require_approval` can leave an
  orphan approval token.
- **`trace-store.spec.md` requirement 6 says "exactly"** but the code's `EVENT_TYPES` has members
  the list never named (found by P43-2); re-derive the list from the frozenset.
- **A team's skills** (P43-7): `core/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope. `init --help` and `--name` do not mention
  teams.
- **Queue counts twice** (P43-6): `core/pod_report.py::task_counts` and the inline Counter in
  `cli/_status.py` (~lines 138-164) compute the same mapping; point `status` at `task_counts`.
  `pod_report._caller_default` reads `sys.stdin.isatty()`, so under `docket start` the report's
  approval default depends on the daemon's stdin.
- **`POST /pods/<p>/apply` edge** (P43-8): an all-skip apply writes no `pod.apply` audit entry
  (pre-existing rule).
- **Corrections cursor** (P43-9): a client must percent-encode `+` in `since` (a raw `+` decodes
  to a space and is `400`); a pod whose Lead was removed but whose ledger remains answers `404`
  (existence is `dispatchable_pods()`, the same rule as `GET /pods`).
- **Dead after the harness deletion** (P43-12, proven by `rg`; the `inPlace` key rides P45-3):
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


