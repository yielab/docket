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

## ◇ Phase 46 closed 2026-10-23

> Phase 46 (organize by context, refactor by tool, D-66,
> [ADR 0030](docs/adr/0030-organize-by-context-and-refactor-by-tool.md)) closed 2026-10-23 on branch
> `plan/phase-46-structure`, archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
> `src/docket/` is `kernel`, twelve context packages, `interfaces/` and `bootstrap.py`; no module is
> over 700 lines; `tests/architecture/` holds the import contracts and the size and local-import
> ratchets at their recorded baselines. A real run on `fab-dev` matches the baseline hop for hop and
> event for event, and found one defect (a refused task re-claimed in a loop), fixed in `8afff095`.
> Acceptance met except the clauses Phase 47 owns: the import baseline is 748 (not empty), `status`
> has 16 writers, 40 patches cross modules. The branch is unmerged and unpushed. Phase 47 below is
> planned and waits for the maintainer.

## ◇ PHASE 47 — PLANNED, NOT SCHEDULED — the seams: the import rule, ports, the state owner, the runtime package, the tests

> Opened 2026-10-23 from the Phase 46 cards the maintainer moved here (P46-10..14). The working
> plan is `internal-docs/plans/phase-46-47-fast-path-2026-10-23.md` (gitignored); this section is
> the tracked record. **That plan's measurements are stale**: they say the largest module is 1,959
> lines, 20 modules exceed 700 and there are 207 local imports. Measured 2026-10-23 at `484bc805`:
> largest module 695 lines (0 over 700), local `docket` imports 20 (the baseline), largest cycle
> 35 modules counting local imports and 2 at top level, `status` writers 16, cross-module
> monkeypatch targets 40. The splits and the HTTP and turn-loop collaborators already landed, so the
> plan's stages A and B are done. Re-measure before any card claims a number.

### P47-1 — the import rule for the 748 baseline exceptions

**Status:** DECIDED 2026-10-23 (option A below, chosen at the maintainer's request; reversible by amending this card) · **Size:** S (the decision) and M (the facades it creates) · **Model:** Sonnet for the facades · **Kind:** T

- **Measured 2026-10-23 at `484bc805`** (`import_contracts_baseline.txt`, classified by consumer and target):
  - Into other contexts' internal modules, 585 edges: `interfaces` 302, `tasks` 78, `hops` 69, `teams` 65, `pipeline` 26, `governance` 17, `models` 14, `operator` 9, `observability` 5.
  - `agent` into other contexts, 44 edges.
  - Into `platform`, `sandbox` or a context's `adapters/`, 114 edges: `interfaces` 31, `agent` 18, `teams` 12, `tasks` 11, `governance` 8, `hops` 8, `models` 7, `observability` 6, `operator` 5, `pipeline` 4, `sandbox` 4.
  - Reversed, 5 edges: `platform` → a context 1, `sandbox` → a context 4.
  - **Every context's `__init__.py` is empty** (0 lines, no `__all__`). The contract says contexts talk through `__init__`, but no context has a public surface yet.
- **Decision (option A): keep the ADR 0030 rule and build the public surface it names.** Options rejected:
  - *Ports for everything:* 585 facade edges would each become a protocol and a binding, with no less coupling.
  - *Amend ADR 0030 to let `interfaces` reach `application`:* it legalizes the CLI importing `tasks.domain.task` and leaves the domain edges open.
  - *A blind re-export of every name:* it hides the boundary instead of defining it.
  1. Each context's `__init__.py` gets an explicit `__all__`. A name is exported only when another context imports it today, and `test_import_contracts.py` fails on an export nothing outside the context uses (the dead-code rule applies to facades too). The AST scan finds 159 distinct names across 50 cross-context modules, which bounds the work.
  2. `agent` cannot use a facade, because its contract is `kernel` only. Its 44 edges become ports owned by `agent/ports.py` and bound in `bootstrap.py` (P47-2).
  3. `platform`, `sandbox` and context `adapters/` are side effects, reached through ports (P47-2, 114 edges).
  4. The 5 reversed edges move the shared type to `kernel` or behind a port (P47-2).
- **Risk:** a facade `__init__` imports its submodules, so importing a context loads all of it and can create cycles that do not exist today. Every facade commit checks `analyze.py --metrics`: `cycle_largest` must not rise.
- **Acceptance:** ADR 0030's dependency table is unchanged; every context `__init__.py` has `__all__`; the dead-export check passes; the baseline drops by exactly the 585 facade edges, leaving the 44 + 114 + 5 that P47-2 owns; `cycle_largest` ≤ 35.

### P47-2 — ports for what is not a context (narrows the old P46-13)

**Status:** TODO after P47-1 · **Size:** L · **Model:** Sonnet where a signature is unclean · **Kind:** T + M

- **Scope, from P47-1's decision:** the ports cover 163 edges: 114 into `platform`, `sandbox` and context `adapters/`; 44 from `agent`, whose ports live in `agent/ports.py` and are bound in `bootstrap.py`; and the 5 reversed edges, which move the shared type to `kernel` or behind a port. The other 585 are closed by P47-1's facades, not by ports.
- **Correction to the earlier plan:** ports do not bring the ignore list to 0 on their own. After P47-1 and P47-2 the list should be empty, and that is the acceptance of both cards together.
- **Acceptance:** each edge in that 163 leaves the baseline, the baseline count drops by exactly that number, and each new port has a fake and a `tests/contracts/` suite run as
  `[real, fake]`.

### P47-3 — one owner of the task's `status` (old P46-12)

**Status:** TODO, independent of P47-2 · **Size:** M · **Model:** Sonnet (transition table) · **Kind:** M + T

- **Measured:** `status` writers 16 (`analyze.py --metrics`), target 1 (ADR 0030 item 3).
- **Acceptance:** `tasks/domain/state.py` holds the transition table and the one writer; an AST
  guard, `tests/architecture/test_status_writers.py`, refuses `["status"] =` anywhere else and is
  written at baseline 1, not 16.

### P47-4 — the runtime package without a build hook (old P46-10)

**Status:** TODO after P47-1 and P47-2 · **Size:** S · **Model:** Sonnet · **Kind:** T

- **Gate:** the `agent` → other-context edges are zero (62 today).
- **Acceptance:** `docket-runtime` builds from `src/docket/agent` and `kernel` with no hook, and the
  runtime boundary tests pass unchanged.

### P47-5 — the test restructure (old P46-14 and the test-suite plan, T1–T6)

**Status:** TODO after P47-2 · **Size:** L · **Model:** Sonnet · **Kind:** T

- **Goal:** ports replace the patches; the order is `internal-docs/plans/test-suite-refactor-2026-10-23.md`.
- **Also owed:** `tests/architecture/test_ids.py` and the autouse fixture in `tests/conftest.py` that
  fails a patch whose target is not defined in the patched module (neither exists yet).
- **Acceptance:** cross-module monkeypatch targets 40 → 0 (`analyze.py --metrics`), and the
  manifest and the fixture are in `tests/architecture/`.

### Left out of Phase 47's path, and owed from Phase 46

- **P46-11, the persisted shapes (nested task record, `pods/<pod>/settings.json`), is not scheduled.** It is a redesign; a measured need must ask for it. Its two real defects are small fixes inside Phase 47: **10** (`answer_task` clears `question`; the answer record keeps neither `kind` nor `createdAt`, so every answer counts as `clarification` and `docket_decision_latency_seconds_count` stays 0) and **67** (`budgetUsd` is a string after provisioning and the flat `--from`, a float after `pod set`, and `AgentMeta.budget_usd` has no `ge=0`).
- **Defect 69 remains in P47-5:** `pytest-without-sandbox.sh` runs in no CI job (a `-m "not sandbox"` job on a runner with `DOCKET_SANDBOX_PROBE=none`), and the `slow` marker is registered and used by nothing.

## ◇ FOLLOW-UPS WITH TRIGGERS — found in Phases 43-46 (not cards; triage when a trigger fires)

- **Found in the Phase 46 real run (2026-10-23).**
  - **A refused task is resumed on every 30 s sweep tick** (`dispatch_refused` is in `RESUMABLE_FAILURE_KINDS`, operator-api §6 says so by design), so a task refused for a cause the operator has not fixed writes one refusal to the audit log and trace every tick. The unbounded in-run loop is fixed (`8afff095`); this is the per-tick residue. Trigger: the audit log fills with refusals of one task, or a second operator asks. Then resume only when the cause changed, or back off, and amend operator-api §6.
  - **The gitignored `CLAUDE.md` still describes the `cli/ -> core/ -> edges/` tree.** It is not in git, so no card fixes it: the maintainer rewrites its architecture section from ADR 0030.
  - **`analyze.py`'s default Profile and `refactor/` data are spent:** the target map is deleted; `analyze.py --draft-map` and `move.py` need a map to run, so retire them when the last Phase 47 move is done.

> Items a Phase 45 card absorbed moved into that card on 2026-10-19 (the gateway window, the
> measurement gaps, the cut commit subject, the group `failure_kind`, the stale `security-gates`
> paragraph, the `inPlace` key, the apply-without-codebase edge, the team-aware hint, the worker
> packet note, the warm workspace, and "no `node_modules` is pod configuration", which ADR 0029
> reversed).

- **Found in the specs truth pass (2026-10-22).**
  - **Notification dedup is in memory only** (`core/notify.py` ~91-118): restarting `docket
    start` resends each pending notification once (unverified). Trigger: an operator reports a
    repeat after a restart.
  - **Every member of a pod shares the base session key `agent:<pod>:<key>`** (`core/pod.py`
    ~86-90); latent, no turn uses the base key as history. Trigger: a turn that reads it.
- **Found while merging Wave 120 (2026-10-23).** Each comes from a worker report and was checked against its branch.
  - **`setup` without `--fix` writes:** its text report re-seeds `WORKFLOW_AUTO.md`. A check that writes is a defect. Trigger: the next edit of `cli/_setup_check.py`.
  - **The seeds point at `memory/YYYY-MM-DD.md`** (`core/memory.py` and the AGENTS.md seed in `cli/_agents.py`), a path docket never creates. Changing it bumps `CONTRACT_VERSION`, so the maintainer decides.
  - **A canonical document without `kind:` still loads with a deprecation advisory** (W120-9 deleted only the short-form path, as Q3 named). Under D-57 the advisory is a notice; either every canonical fixture gains `kind:` or the advisory goes. Trigger: the next edit of `core/config_docs.py`.
  - **`enqueue_task` is kept beside `enqueue_task_once`**, because about 300 test call sites in 40 files use it. Delete it with a script in stage 3 if the two have the same semantics for a fresh task; otherwise each site is a decision.
  - **`docket start`'s periodic notify flush ignores `FlushReport.error`** (`serve.py::_flush_notify_channels`; serve has no logger). → P46-9.
  - **An answer to a task run with `run --pipeline <file>` is placed against the pod's pipeline**, because the file's spec is not persisted on the task (W120-8 fixed the named-pipeline half of defect 48). → P46-11, which reshapes the task record.
  - **Enabling the `email` channel checks nothing**: with no `to`, `from` or `smtpHost`, every delivery fails into the health record. Trigger: an operator enables it.
  - **The `openhands` and `pydantic_ai` adapters never pass `cache_write_tokens`**, so the facade's cache-write sum is 0 for them. Trigger: either adapter reports usage someone reads.
  - **`GET /pods` (the list) was not checked** for the invalid-settings failure that W120-6 fixed on `/pods/<p>`. → P46-9's byte-identity check.
- **Found in the Phase 45 real runs (2026-10-20, two runs of one small task on `fab-dev`).**
  - **The implementer sends 0.65 of what the backend counts** (14 and 13 calls, largest request
    ~7,000 estimated tokens), with no toolchain grant needed (`npm` came from the prepared
    `node_modules`). The Phase 44 trigger below ("still sends over half") therefore **fired**:
    triage, then measure which calls repeat before cutting anything. The reviewer sent 0.62, the
    tester 0.80 and 0.90.
  - **A parked turn is still paid twice**, now on a read: the model's first `bash` carries `$(...)`
    ("not statically analysable"), parks every run, and the resumed hop re-sends the whole
    prompt (4,157 input tokens before the park, 8,181 on the first call after). Two runs, same
    call. Trigger: a third run that parks on the same shape; then weigh resuming the session
    over re-running the hop (operator-loop §2 item 6 keeps this a non-goal today).
  - **A hop refused before any call records an empty model**: `hop_finished.model` is `""` and
    `usage.byModel` gains a `""` key with zeros (seen on the budget-refused reviewer). Trigger: a
    reader of `byModel` that trips on the empty key.
  - **Anthropic advertises dated ids** (`claude-haiku-4-5-20251001`) while the template rows use
    aliases (`claude-haiku-4-5`), so an alias row's limits stay `unknown` though the chat route
    accepts the alias. Trigger: a run on an alias id whose window matters.
  - **The shipped price rows lag the models in use**: the pod's steps run `claude-sonnet-5-5` and
    `claude-opus-5-5`, which no template row prices, so `task show` prints `cost: -`. Trigger: an
    operator asking for the estimate; then add rows or let `provider add` take a price file.
  - **Not examined:** each run's trace carries two `approval_denied` events beside the one park.
  - A worker's test with `monkeypatch.undo()` undid the autouse home isolation and wrote into the
    real `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
- **Found integrating Wave 118 (P45-3, 2026-10-19).**
  - **A file a check reaches only through `make` or `npm run` is protected only through the
    default files it reads** (`Makefile` is not a default; `package.json` is). Stated in
    `security-gates.spec.md`. Trigger: a real gate whose script lives behind a target.
  - **A gitignored file is invisible to the check** (`git status` and `git diff` skip it), so a
    tool configuration the repository ignores can be edited without a park. Trigger: a real
    repository that ignores a file its gate reads.
- **Found integrating Wave 117 (P45-1, 2026-10-19).**
  - **Only `node_modules` is cached.** A `.venv` is not relocatable, so `uv sync`, `poetry
    install` and `cargo fetch` run in each task worktree. Trigger: a measured Python or Rust
    prepare that dominates a task's wall clock.
  - **A tool that writes into `node_modules/.cache` fails with isolation on** (the entry is
    read-only in the jail). Trigger: a real gate failing on it.
  - **Eviction can break a running task's link** when a fourth lockfile of one codebase is
    prepared while an older task still runs; resume detects the broken link and prepares again.
    Trigger: a real run that hits it.
  - **Prepare is not cancellable**, like `verifyCmd`; it is bounded by `PREPARE_TIMEOUT_S` (900 s).
  - **A hop that makes its own `node_modules` symlink to another codebase's cache entry gets that
    entry read-only in its jail** (`core/prepare.py::linked_entries` accepts any entry under the
    cache). Installed packages, not secrets; restrict to the task's codebase when next touched.
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
- **A team's skills** (P43-7): `core/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope. `init --help` and `--name` do not mention
  teams.
- **`POST /pods/<p>/apply` edge** (P43-8): an all-skip apply writes no `pod.apply` audit entry
  (pre-existing rule).
- **Corrections cursor** (P43-9): a client must percent-encode `+` in `since` (a raw `+` decodes
  to a space and is `400`); a pod whose Lead was removed but whose ledger remains answers `404`
  (existence is `dispatchable_pods()`, the same rule as `GET /pods`).
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
   card's own spec updated with a version bump (specs carry no changelog) (integrator-applied in a
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


