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

## ◇ Phase 45 closed 2026-10-20

> Phase 45 (a prepared checkout, models from the provider, and a check the change cannot define,
> D-65, [ADR 0029](docs/adr/0029-a-prepared-checkout-models-from-the-provider-and-a-check-the-change-cannot-define.md))
> closed 2026-10-20: five cards over Waves 117-119 and two small real runs on the operator's home
> without Tack, archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
> Acceptance met except one clause: the worktree is prepared from the lockfile (22.4 s, then a
> cache hit in 0 s), the project's eslint, tsc and vitest run as the gate, `setup provider show`
> names every limit's source or says `unknown`, approvals are kept per (codebase, pod); no run
> parked on `check_changed` because neither touched a protected path (the unit and seam tests are
> the evidence for that clause). The runs found three defects, all fixed the same day
> (`3e9c3d9f`, `0a0bff6c`, `f9a5cec4`). Operator items left: `~/.docket/provider-models.json.bak`
> still holds a worker test's junk rows (`m`, window 9) and the maintainer deletes it; the two
> task branches `docket/fab-dev/task-b1e95477…` and `…task-b5e39e26…` in the Fabulada repository
> carry the new tests and are the maintainer's to merge or drop. No phase is planned on
> `develop`; Phase 46 (D-66, ADR 0030) is planned on branch `plan/phase-46-structure` and waits for
> the maintainer's approval.

## ◇ PHASE 46 — PLANNED — organize by context, refactor by tool (D-66, [ADR 0030](docs/adr/0030-organize-by-context-and-refactor-by-tool.md); planned 2026-10-20, starts when Phase 45 closes)

> **Evidence.** Measured 2026-10-20 at `c74a224e` (ADR 0030 "Evidence"): 31 of 63 `core` modules
> import `edges`; 206 function-local imports hide a 38-module cycle; `core/dispatch.py` is 4,727
> lines, 168 definitions, 20 % of all `src/` commits in 90 days; `status` is written in 16 places;
> 1,191 `monkeypatch` uses, 72 on `dispatch`; the runtime wheel is a 40-file build-hook copy.
>
> **Shape.** The ADR is the step-by-step guide; each card below is one of its steps. **Zero
> behaviour change** is the contract: the HTTP API 6, the CLI goldens and the `docket_runtime`
> facade are the oracle; every internal shape (module paths, persisted JSON, test locations) is
> free to change (D-57: no users, no data to migrate). Every card ends with
> `scripts/maint/refactor_gate.sh` exit 0 (nine checks, ADR 0030 "The step-by-step guide"); a
> card that fails the gate is reverted and its mapping corrected, never patched until green.
>
> **Who does what.** Tool-only cards (T) run a script; a model writes code only in P46-2, P46-3,
> P46-4 (tools with their own tests) and P46-12, P46-13 (bounded judgment with generated input).
> Review cards (R) are one human read of a generated artifact. The integrator owns `refactor/`
> (mapping, analysis, retired list), the board, ROADMAP, CHANGELOG and every rollup.
>
> **Ordering.** A: P46-1 → P46-2 ∥ P46-3 → P46-4 → P46-5. B: P46-6 → P46-7 → P46-8 → P46-9 →
> P46-10 → P46-11. C: P46-12 (after P46-7), P46-13 (after P46-8). D: P46-14 → P46-15. Baseline
> live run recorded before P46-6. **Freeze:** no other card touches `src/` from P46-6 to P46-15.
>
> **Dev dependencies added:** `libcst`, `import-linter`. Runtime dependencies unchanged.
>
> **Phase acceptance** (ADR 0030 "Phase acceptance"): architecture tests at target (ignore list
> empty, local imports 0, largest module ≤ 700, `status` writers 1, every patch on its defining
> module, every test at its mirror path); runtime installs without a hook; API/goldens/facade
> tests unchanged; before/after live traces identical modulo ids and timestamps; no `cli/`,
> `core/`, `edges/`, `serve.py`, `config.py` left.

### P46-1 — the rules the documents state

**Status:** TODO after Phase 45 closes · **Size:** S · **Model:** integrator · **Kind:** R

- **Trigger:** ADR 0030 points 1-2 and 5 replace the layer rule `cli -> core -> edges`.
- **Goal:** `CONTRIBUTING.md` "Package layout" describes the context packages, the two-level rule,
  the dependency table and the 700-line ceiling; `AGENTS.md` change contract item 4 names the
  import contracts instead of the three layers; `specs/test-framework.md` "Lanes and placement"
  (2.21.0) describes mirror placement, markers as lanes, `tests/fixtures/`, `contracts/`, `e2e/`,
  `architecture/`, `release/`, and the end of `SUBJECT`; CLAUDE.md "Architecture" points to the ADR.
  ADR 0030, the ROADMAP rows and the §4.5 amendment landed with the plan (2026-10-20).
- **Non-goals:** moving any code.
- **Acceptance:** the three documents agree with the ADR's dependency table word for word where
  they cite it; `validate-specs.sh` and the agent-lane prose tests pass.
- **Gates:** `validate-specs.sh`, `tests/release` prose tests, `gen_cli_docs --check`.

### P46-2 — `analyze.py`: the measurements and the first mapping

**Status:** TODO after P46-1 · **Size:** M · **Model:** Sonnet · **Kind:** T (tool with tests)

- **Goal:** `scripts/maint/refactor/analyze.py` writes `refactor/analysis.json` + markdown: import
  graph and SCCs (top-level and with local imports, via `grimp`); every function-local `docket`
  import (file, line); call-graph groups for `core/dispatch.py`, `serve.py`,
  `edges/adapters/system.py` (definitions, line ranges, external callers); every `["status"] =`
  site with the fields set in the same block and its caller; every `_cfg.NAME` read; every
  monkeypatch target with the module that defines the patched object; fan-in per task-record key;
  whether `runs.json` duplicates `task["hops"]`. `--metrics` prints the nine gate numbers.
  `--draft-map` emits `refactor/target-map.toml` from the groups and ADR 0030 "Target layout".
- **Non-goals:** changing any file under `src/` or `tests/`.
- **Acceptance:** on `develop` the metrics print local imports 206, largest cycle 38, `status`
  writers 16, largest module 4727 (±0); on `tests/architecture/fixtures/toy/` the groups and
  SCCs match the fixture's expected JSON. Oracle: the tool's own tests.
- **RED test:** the toy fixture's expected JSON before the tool exists.
- **Gates:** ruff, mypy on the script, its tests; `comment_lint`.

### P46-3 — `move.py` and `refactor_gate.sh`

**Status:** TODO after P46-1 · **Size:** L · **Model:** Sonnet · **Kind:** T (tool with tests)

- **Goal:** `scripts/maint/refactor/move.py` (libcst) executes `target-map.toml`: `git mv` whole
  modules; move named definitions with leading comments and decorators in mapping order; rewrite
  `import`/`from … import` in `src/` and `tests/`; rewrite `"docket.a.b"` string targets and
  `SUBJECT`; move each test file to its `SUBJECT` module's mirror path, splitting a file by
  symbol when its tests import two destinations; rewrite code paths in `specs/`, `docs/` (not
  `cycles-ended/`, not `adr/`), `CONTRIBUTING.md`, `AGENTS.md`, `.agents/skills/`; `ruff --fix`;
  maintain `refactor/retired.txt`. Flags `--dry-run`, `--check`; idempotent.
  `scripts/maint/refactor_gate.sh` runs the nine checks of ADR 0030 and exits non-zero on the
  first failure, printing which.
- **Non-goals:** running the mapping on the real tree (that is P46-7 onwards).
- **Acceptance:** on the toy fixture, three mappings (whole module, split by definition, test
  split by symbol) produce the expected trees byte for byte and `--check` passes afterwards;
  `--dry-run` on the real tree with the P46-2 draft lists only mapped files and changes nothing.
- **RED test:** the expected trees before the tool exists.
- **Gates:** ruff, mypy on the scripts, their tests.

### P46-4 — `tests/architecture/`, the ratchets and the markers

**Status:** TODO after P46-2 and P46-3 · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Goal:** move the 25 guards to `tests/architecture/` and the 18 agent-lane files to
  `tests/release/` (by `move.py`). Add `test_import_contracts.py` (import-linter, ADR 0030
  dependency table, current violations in a baseline ignore list), `test_no_local_imports.py`
  (baseline 206), `test_module_size.py` (ceiling = current largest, target 700),
  `test_status_writers.py` (baseline 16, target 1), `test_ids.py` (`test_ids.txt` manifest; a
  missing id needs a `retired:` line in the commit), and the autouse fixture in `tests/conftest.py`
  wrapping `monkeypatch.setattr`: an original whose `__module__` is not the patched module fails
  with `patch the defining module: <module>`. Register markers `unit integration sandbox e2e slow
  release evals`; a codemod adds `pytestmark` by current directory; CI selects by `-m`;
  `testpaths = ["tests"]`; `tests/evals/README.md` states the lane is empty and never in CI.
- **Acceptance:** the gate passes with every baseline at its measured value; in a scratch branch
  one added local import, one `status` write and one patch on a re-exporting module each fail the
  gate (seen to fail, reverted); `-m "not sandbox"` collects what `pytest-without-sandbox.sh` did.
- **Gates:** `refactor_gate.sh`.

### P46-5 — `kernel/` and `Home`

**Status:** TODO after P46-4 · **Size:** L · **Model:** integrator + codemod · **Kind:** T + R

- **Goal:** `analyze.py --emit-home` generates `kernel/home.py::Home` from the 102 `config.py`
  names (same defaults, types, environment variables); the maintainer reviews the class once.
  `current_home()` (`ContextVar`, process default from the environment) and `use_home(home)`
  context manager. Codemods: the 307 `_cfg.NAME` reads → `current_home().name`; the test fixture
  `use_home(Home(tmp_path))` replaces `repoint_docket_home`; `datetime.now(UTC)`/`time.monotonic`
  outside tests → `kernel/clock.py`. `config.py` keeps only template lookups and moves to
  `kernel/`. `kernel/ids.py`, `kernel/errors.py`, `kernel/text.py` take `_now`, `_parse_iso`,
  `_cut_at_word` and friends. The architecture guard forbids `os.environ`, `datetime.now` and
  `time.*` outside `kernel/`.
- **Acceptance:** a new test runs two `use_home` blocks and asserts disjoint files; the
  partial-repointer guard and its baseline are deleted; the gate passes.
- **Gates:** `refactor_gate.sh`.

### P46-6 — `bootstrap.py`, the composition root

**Status:** TODO after P46-5 · **Size:** M · **Model:** Sonnet · **Kind:** T + R

- **Goal:** plain functions `build_store`, `build_sandbox`, `build_driver`, `build_channels`,
  `build_app` (CLI), `build_server` (HTTP), each taking a `Home`; the CLI entry and `serve` call
  them once. No registry, no framework. Import-linter contract: only `bootstrap` and `interfaces`
  import `*/adapters` (added to the ignore-list ratchet).
- **Before this card the integrator records the baseline live run** (ADR 0030 P46-15):
  `capture-doc-journey.sh` on the local model plus one HTTP dispatch, trace files kept under
  `refactor/baseline/`.
- **Acceptance:** the gate; `docket --help` golden unchanged; `serve` starts from `build_server`.
- **Gates:** `refactor_gate.sh`.

### P46-7 — split `core/dispatch.py`

**Status:** TODO after P46-6 · **Size:** L · **Model:** codemod · **Kind:** T + R

- **Goal:** the reviewed mapping assigns the 168 definitions to `tasks/application/` (`queue`,
  `lifecycle`, `actions`, `approvals`, `sweep`), `tasks/domain/task.py` (shared types),
  `pipeline/application/executor.py`, `hops/application/` (`compose`, `runner`, `record`),
  `hops/gates/` (`pre_hop`, `post_hop`), `hops/workspace/*`, `teams/settings.py` (the `pod_*`
  readers). One commit per destination, leaf-first. The six externally used private names become
  public in their module; the 24 importers are rewritten in the same commit (no re-export, D-57).
  `HopResult`/`TaskResult` become frozen with `with_*` methods; the four mutators return values.
- **Non-goals:** changing any transition (P46-12), any persisted shape (P46-11).
- **Acceptance:** `core/dispatch.py` does not exist; largest resulting module ≤ 700; the 72
  `dispatch` patches are on their defining modules (the P46-4 fixture proves it); manifest ids
  unchanged under new paths; the gate passes after every commit.
- **Gates:** `refactor_gate.sh` per commit.

### P46-8 — every remaining module to its context

**Status:** TODO after P46-7 · **Size:** L · **Model:** codemod · **Kind:** T

- **Goal:** one commit per context, leaf-first: `platform`, `models`, `observability`,
  `operator`, `sandbox`, `governance`, `teams`, `agent`, `tasks`, `pipeline`, `hops`,
  `interfaces` (cli commands, mcp, telegram entry). `edges/adapters/system.py` splits into
  `platform/process.py`, `platform/git.py`, `sandbox/launch.py` by the P46-2 groups; `jail.py` and
  `plugins.py` leave the package root. Mirror tests, specs and live docs rewritten per commit.
- **Acceptance:** `src/docket/cli`, `core` and `edges` do not exist; the import-linter ignore
  list is exactly the remaining domain→adapter edges (printed by `analyze.py`); the gate passes
  per commit.
- **Gates:** `refactor_gate.sh` per commit.

### P46-9 — split `serve.py`

**Status:** TODO after P46-8 · **Size:** M · **Model:** codemod · **Kind:** T + R

- **Goal:** a codemod lifts each path branch of `do_GET`/`do_POST` into
  `interfaces/http/routes/<resource>.py` (tasks, pods, approvals, inbox, traces, health, metrics,
  dispatch) and generates the `(method, pattern) -> handler` table; `interfaces/http/auth.py`
  holds the bearer check once; `interfaces/http/server.py` holds the handler class, threads and
  stop controller.
- **Acceptance:** `SERVE_API_VERSION` and every response byte-identical (the serve tests move
  beside their route and pass unchanged); `serve.py` does not exist.
- **Gates:** `refactor_gate.sh`.

### P46-10 — the runtime is a package, not a build hook

**Status:** TODO after P46-8 · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Goal:** with the contract "`agent` imports `kernel` only" green, delete
  `packages/docket-runtime/hatch_build.py` and its 40-file closure; the distribution includes
  `docket/agent` and `docket/kernel`; `docket_runtime/__init__.py` re-exports the same facade names.
- **Acceptance:** `uv build` in a clean venv, `import docket_runtime` exposes the same names;
  `tests/release/test_runtime_package_boundary.py` passes with the hook gone.
- **Gates:** `refactor_gate.sh`, `tests/release`.

### P46-11 — persisted shapes the structure wants (D-57)

**Status:** TODO after P46-9 · **Size:** M · **Model:** Sonnet · **Kind:** T + R

- **Goal:** the task record is written nested (`spec`, `lifecycle`, `execution`, `pending`) with
  the same camelCase field names inside (the API serializer flattens, so responses are
  unchanged); pod settings move from the Lead's `.docket-meta.json` to `pods/<pod>/settings.json`;
  `TASK_LIST.json` stays one document per pod. Old-shape readers are deleted, not kept.
- **Non-goals:** one file per task (measured trigger); any API change.
- **Acceptance:** operator-api and serve-read-api tests unchanged; the gate; the operator wipes
  and re-initializes the live `~/.docket` after it lands (no users, no migration) and one
  dispatch on the local model runs to `done`.
- **Gates:** `refactor_gate.sh`.

### P46-12 — one owner of the task's state

**Status:** TODO after P46-7 · **Size:** M · **Model:** Sonnet (one attempt) · **Kind:** M + T

- **Input:** the P46-2 table of 16 sites (from, to, fields, caller).
- **Goal:** `tasks/domain/state.py`: `Status`, `FailureKind` enums, the allowed-transition table,
  `transition(record, to, *, reason="", failure_kind=None, ...)` setting exactly each
  transition's fields (`completedAt`, `claimId=None`, `pending=None` on a terminal state). A
  codemod replaces the 16 sites by AST location. A test **generated from the table**: each allowed
  transition sets its fields; each other pair raises `IllegalTransition`.
  `test_status_writers.py` ratchets to 1.
- **Non-goals:** adding or removing a transition that exists today.
- **Acceptance:** no behavioural test changes; the generated test passes; the gate passes.
- **Gates:** `refactor_gate.sh`.

### P46-13 — ports for what the ignore list still holds

**Status:** TODO after P46-8 · **Size:** L · **Model:** Sonnet where a signature is unclean · **Kind:** T + M

- **Goal:** for each remaining domain→adapter import, `analyze.py --emit-port` generates a
  `Protocol` from the signatures the domain uses; `bootstrap.py` binds the real adapter; the
  domain receives the port as a parameter or from `current_home()`. A model handles only
  signatures that mix effects, one card per unclean port if more than one.
  `tests/fixtures/fakes/<port>.py` and `tests/contracts/test_<port>_contract.py` (parametrized
  `[real, fake]`) per port.
- **Acceptance:** import-linter ignore list empty; local imports 0; largest SCC 1; every fake
  passes its contract suite; the gate.
- **Gates:** `refactor_gate.sh`.

### P46-14 — the tests only the new structure allows

**Status:** TODO after P46-13 · **Size:** L · **Model:** Sonnet · **Kind:** T + M

- **Goal:** `tests/fixtures/`: `home.py`, `repo.py` (temp git repo with lockfile and commits),
  `builders.py` (`make_task`, `make_pod`, `make_hop`), `fakes/chat.py` (`ScriptedChat`: turns
  with text and tool calls, fails when the script runs out) replacing the 7 LLM stubs.
  `tests/e2e/`: 8-12 named flows extracted from `integration/` (software pod to done, rework
  cycle, check_changed park + grant/deny, prepare from lockfile + cache hit, HTTP lifecycle as
  Tack drives it, resume after restart, lights-out profile, Telegram approval). The flat
  `tests/integration/` directory disappears (mirror path, `e2e/` or `contracts/`); each retired
  test named in `retired:`. `SUBJECT` deleted everywhere; the layout guard checks the mirror path.
- **Acceptance:** no file outside `tests/architecture/` mentions a module path; `analyze.py`
  reports monkeypatch targets only on `kernel.clock` and `os.environ`; the gate.
- **Gates:** `refactor_gate.sh`.

### P46-15 — the live run, before and after, and the close

**Status:** TODO after P46-14 · **Size:** M · **Model:** integrator · **Kind:** R

- **Goal:** repeat the P46-6 baseline runs; compare traces event by event (names, gate outcomes,
  transitions; ids and timestamps masked) and the HTTP responses. Rewrite CLAUDE.md, AGENTS.md,
  the `docket-*` skills and CONTRIBUTING for the new layout (paths by the tool, prose by hand).
  CHANGELOG "Changed (internal)". Delete `refactor/`; the architecture tests are the record.
  ROADMAP row 46 dated; board archived with `split_board.py archive`.
- **Acceptance:** the trace diff is empty; the Phase 46 acceptance above, with numbers.
- **Gates:** every gate in CLAUDE.md "Running tests", in a clean worktree.

## ◇ FOLLOW-UPS WITH TRIGGERS — found in Phases 43-45 (not cards; triage when a trigger fires)

> Items a Phase 45 card absorbed moved into that card on 2026-10-19 (the gateway window, the
> measurement gaps, the cut commit subject, the group `failure_kind`, the stale `security-gates`
> paragraph, the `inPlace` key, the apply-without-codebase edge, the team-aware hint, the worker
> packet note, the warm workspace, and "no `node_modules` is pod configuration", which ADR 0029
> reversed).

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


