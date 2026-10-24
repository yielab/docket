# ADR 0030 (D-66): organize by context, refactor by tool

> **Amended 2026-10-23, at the Phase 46 close** (§"After Phase 46"): a context's public surface is
> an explicit `__all__`; ports only where a test fakes a boundary or a contract forbids the import;
> a context's `domain/` is a functional core for decisions; the test layout follows the 2026-10-23
> test audit; one testing budget replaces the gate after every commit. Phase 47 on `TODO.md` is the
> card list for what Phase 46 left.
>
> **Amended 2026-10-23, during Phase 47 (P47-9)** (§"The contexts are layered"): "a context talks to
> another only through its `__init__`" is replaced by a layers contract. The contexts have one fixed
> bottom-to-top order; a context imports any module of a context below it, and an import of a
> context above it is the violation the baseline records.

**Question:** docket's source is three technical layers (`cli/`, `core/`, `edges/`) with 63 domain
modules in `core/`. The layer rule exists in prose, not in a check: 31 of 63 `core` modules import
`edges`, 206 function-local imports hide a 38-module import cycle, `core/dispatch.py` is 4,727
lines and 168 definitions, it is touched by 20 % of all commits, and the task's `status` is written
in 16 places with no table of allowed transitions. What does docket change, and how does it change
it without changing what docket does?

**Where decided:** 2026-10-20, by the maintainer, from the measurements below (`develop` at
`c74a224e`). This ADR is also the **step-by-step guide** for the refactor: Phase 46 on `TODO.md`
is its card list.

**What is fixed and what is free.** docket has no users and no data to migrate (D-57). Every
**internal** shape may change: module paths, persisted JSON layouts, file names under
`DOCKET_HOME`, test locations. Three **external** contracts stay byte-for-byte and are the oracle
that nothing else changed: the HTTP operator API (version 6), the CLI surface (the golden suite),
and the `docket_runtime` facade. Every `specs/` requirement keeps its meaning; only the paths it
cites move.

## The decision, on one screen

1. **Organize by context, with layers inside each context.** `src/docket/` becomes twelve
   packages, each a business context (`tasks/`, `pipeline/`, `hops/`, `agent/`, `governance/`,
   `sandbox/`, `teams/`, `models/`, `observability/`, `operator/`, `platform/`, `kernel/`) plus
   `interfaces/` (cli, http, mcp, telegram) and one `bootstrap.py`. Inside a context, at most two
   levels: `domain/`, `application/`, `adapters/` where the context needs them, flat otherwise.
2. **The dependency rule is checked, not declared.** `tests/architecture/` runs import-linter
   contracts: a domain package never imports an adapter, a context imports only contexts below it
   in the fixed layer order (amended 2026-10-23), no module imports `interfaces/`, `agent/` depends
   on `kernel/` and `platform`'s `__init__`. Function-
   local imports of `docket.*` are forbidden; the current 206 are a baseline that only shrinks.
   *Amended 2026-10-23:* a context's `__init__` declares `__all__` with exactly the names other
   contexts import, and an export nothing uses fails the contracts test.
3. **One owner of the task's state.** `tasks/domain/state.py` holds the transition table and the
   one function that writes `status`; an AST guard refuses `["status"] =` anywhere else. This is
   the same chokepoint pattern as `dispatch_tool` and `store.py`, applied to state. *Amended
   2026-10-23:* the table and a pure `decide()` live in `domain/`; the one writer that applies the
   decision lives in `application/`.
4. **Configuration is an object.** `kernel/home.py::Home` replaces the 102 module-level constants
   of `config.py`; a `ContextVar` makes `current_home()` available without threading a parameter
   through every call, and a test owns its `Home(tmp_path)`.
5. **Tests mirror the code.** `tests/<same path>/test_<module>.py` for every module; lanes are
   pytest markers, not directories; `tests/fixtures/` is the one source of fakes, each fake proven
   by a contract suite that also runs against the real adapter; `tests/contracts/`, `tests/e2e/`,
   `tests/architecture/` and `tests/release/` are the only directories that do not mirror a module.
   *Amended 2026-10-23* (§"After Phase 46", Tests): lanes stay directories; shared helpers and
   fakes live in `tests/support/`; integration files sit under `integration/<context>/` and name
   their entry module as `SUBJECT`.
6. **The refactor is done by tools, not by models.** One mapping file (`refactor/target-map.toml`)
   is the plan; a libcst codemod executes it; one gate script decides pass or fail. A failing step
   is reverted and the mapping corrected; nothing is iterated "until green". A model writes code
   in exactly five tasks: the three tools (each with its own tests) and two bounded judgments (the
   state table, the ports a signature does not reveal).
7. **The anti-overengineering list stands, amended in one row.** No DI framework (`bootstrap.py`
   is plain functions), no event bus (subscribers are callbacks, as `trace.add_subscriber` already
   is), no database, no FastAPI. The row "keep it flat; split a module only when it actually hurts"
   is amended: the hurt is measured (below), so the split happens, and the new rule is "one
   context per package, two levels at most, a module over 700 lines is a defect".

## Evidence (measured 2026-10-20 at `c74a224e`)

| Measure | Value |
|---|---|
| `core` modules importing `edges` | 31 of 63 |
| Function-local `docket` imports (cycle-hiding) | 206 (core 73, cli 69, serve 50, edges 14) |
| Import cycles at top level / counting local imports | 0 / **6, the largest 38 modules** |
| `core/dispatch.py` | 4,727 lines, 168 definitions, fan-in 24, fan-out 36, 134 of 675 `src/` commits in 90 days |
| Writers of a task's `status` | 16 (12 in `dispatch.py`, 4 in `answers.py`) |
| `dict[str, Any]` annotations / `isinstance(x, dict)` guards | 639 / 218 |
| Module-level `os.environ` reads in `config.py` | 61 (102 names, read in 307 places) |
| `monkeypatch` uses in tests / patches on `dispatch` | 1,191 / 72 |
| Fake classes and helpers / LLM stubs | 11 + 24 / 7 variants |
| Shipped `docket-runtime` closure | 40 files copied and rewritten by a build hook |
| Recorded "unwired machinery" instances (a setting with a writer and no live reader) | 7 |

The cost of not deciding: every wave contends on `dispatch.py` (Waves 117 and 118 had to forbid
seven of its functions per worker packet), every new feature adds another `status` writer (P45-1
and P45-3 both did), and the embeddable runtime ships the whole ball.

## What stays, because it is right

Owning the loop (D-19); `dispatch_tool` as the one tool chokepoint; `store.py` as the one atomic
JSON writer; capability-based denial; closed dialects for providers, exporters and channels;
measured tokens kept apart from estimates; zero runtime dependencies for HTTP; JSON files as the
store; append-only trace and audit; the golden suite; the no-backend test lane; the escape matrix.
The refactor builds on these; it does not replace any.

## Target layout

```
src/docket/
├── kernel/            home.py (Home + current_home()), clock.py, ids.py, errors.py, text.py,
│                      operator_contract.py (the shared operator-loop wire model), protected_paths.py,
│                      tool_outcome.py
├── tasks/             domain/{task,state,options,refs}.py  application/{queue,lifecycle,actions,
│                      approvals,answers,interruptions,corrections,escalation,evidence,runs,sweep}.py
│                      ports.py  adapters/json_store.py
├── pipeline/          domain/{spec,plan,verdict,routing}.py  application/{executor,steps,schedule}.py
├── hops/              application/{compose,runner,record}.py  gates/{pre_hop,post_hop}.py
│                      workspace/{worktree,prepare,repo_view,repo_map}.py
├── agent/             loop*, session*, context, tools/{registry,screening,builtin_tools,mcp_tools,
│                      mcp_client}.py, tools/builtins/*.py, ports.py   (the turn engine; the pod-turn
│                      driver is hops/application/driver.py, identity and the role composer are teams)
├── governance/        policy/, security/, approval/, audit/, secrets, privacy, profile,
│                      network_posture, review (reviewed_repos), plugins
├── sandbox/           ports.py, launch.py, landlock.py, seatbelt.py, docker.py
├── teams/             settings, roles, blueprints, fleet, resources, memory, report,
│                      apply/{plan,review,directory}.py, provisioning.py, config_docs.py
├── models/            catalog.py (provider), selection.py (models_policy), adapters/openai_http.py
├── observability/     trace.py, telemetry.py, exporter.py, adapters/otlp_http.py
├── operator/          inbox, notify, channel, adapters/{console,desktop,email,ntfy,
│                      telegram,webhook,command}.py
├── platform/          store.py, process.py, git.py, fetch.py, redirects.py, parked_questions.py
├── interfaces/        cli/{app.py,commands/*,render/}, http/{server,auth,routes/*}, mcp/, telegram/
├── bootstrap.py       Home -> adapters -> services; the only module that names concrete adapters
└── templates/         unchanged
```

Allowed dependencies (import-linter contracts, enforced from A3 on):

| From | May import |
|---|---|
| `kernel` | nothing in `docket` |
| `<context>/domain` | `kernel`, its own `domain` |
| `<context>/application` | `kernel`, its own `domain` and `ports`, any module of a context below it in the layer order (amended 2026-10-23) |
| `<context>/adapters`, `platform`, `sandbox` | `kernel`, `platform`'s `__init__` (amended 2026-10-23), the ports and domain types they implement |
| `agent` | `kernel`, `platform`'s `__init__` (amended 2026-10-23), its own modules |
| `interfaces` | `kernel`, `bootstrap`, any context (amended 2026-10-23) |
| `bootstrap` | everything |

The layer order, bottom to top (amended 2026-10-23; the constant `LAYERS` in
`tests/architecture/test_import_contracts.py`): `platform` < `governance` < `agent` < `models` <
`observability` < `pipeline` < `teams` < `sandbox` < `operator` < `tasks` < `hops`. `kernel` is below
all of them and `interfaces` and `bootstrap` above. "Below" is the only thing the rule asks of a
context-to-context import; see §"The contexts are layered".

## The step-by-step guide

Every step below is one card on `TODO.md` (P46-N). Each has: what is done, who does it (a tool, a
tool plus one human review, or a bounded model task), what is expected afterwards, and how it is
verified. **The gate** named in every step is `scripts/maint/refactor_gate.sh`, built in P46-3;
it exits 0 only when all of these hold:

1. `ruff check` and `ruff format --check` are clean.
2. `mypy src` is clean (no broken reference survives a move).
3. import-linter reports no new violation and its ignore list is no longer than before.
4. `pytest --collect-only` yields the same test node ids as the committed manifest
   (`tests/architecture/test_ids.txt`), translated through the mapping; a removed id needs a
   `retired:` line in the commit message naming the test that replaces it.
5. The full default lanes, `scripts/maint/pytest-without-sandbox.sh` and
   `tests/integration/sandbox/test_escape_matrix.py` pass (exit code is the evidence; this repo's pytest
   prints no summary line).
6. `bash tests/golden/run.sh verify-all` passes.
7. `bash scripts/validate-specs.sh` and the three generated-docs checks pass.
8. The diff of `specs/` with path-only line changes removed is empty.
9. `scripts/maint/refactor/analyze.py --metrics` reports values ≤ the previous commit's for: the
   largest cycle, function-local imports, the largest module, `status` writers, monkeypatch
   targets whose defining module differs from the patched one.

A step that fails the gate is reverted with `git reset --hard` in its worktree. The mapping, the
tool or the plan is corrected; the step is rerun from the clean base. No partial fix is committed.

### Phase A — tools and oracles (P46-1 … P46-5; sequential, except P46-2 ∥ P46-3)

**P46-1 — this ADR, the decision rows, the amended rules.** `ROADMAP.md` gains D-66 and the
Phase 46 row; §4.5 amends the "keep it flat" row; `CONTRIBUTING.md` "Package layout" and
`AGENTS.md` change contract item 4 describe the new rule; `specs/test-framework.md` "Lanes and
placement" describes mirror placement and markers. *Expected:* the rule a reviewer applies is the
one the tools enforce. *Verified:* `validate-specs.sh`; the agent-lane prose tests; a read of
the three documents side by side.

**P46-2 — `scripts/maint/refactor/analyze.py`.** Reads `src/` and `tests/` with `ast` and
`grimp` and writes `refactor/analysis.json` plus a markdown summary: the import graph and its
strongly connected components (top-level and with local imports); every function-local
`docket` import with file and line; call-graph groups for `core/dispatch.py`, `serve.py` and
`edges/adapters/system.py` (connected components over intra-module calls, each with its
definitions, line ranges and external callers); every `["status"] =` site with the surrounding
fields assigned in the same block; every `_cfg.<NAME>` read; every monkeypatch target with the
module that actually defines the patched object; fan-in per task-record key (which keys nothing
reads); whether `runs.json` records duplicate `task["hops"]`. `--metrics` prints the nine gate
numbers. Has its own tests on a toy package under `tests/architecture/fixtures/`. *Expected:* the
first `refactor/target-map.toml` draft, generated from the groups, ready for review. *Verified:*
its tests; the metrics it prints match the hand counts in this ADR within the documented
tolerance (local imports 206, cycle 38, status writers 16).

**P46-3 — `scripts/maint/refactor/move.py` and `refactor_gate.sh`.** The codemod (libcst)
executes a mapping: `git mv` for whole modules; for definitions, cut the node with its leading
comments and decorators and paste it into the destination module in mapping order; rewrite every
`import`/`from … import` in `src/` and `tests/`; rewrite string targets `"docket.a.b"` in tests;
rewrite `SUBJECT`; move each test file to the mirror path of its `SUBJECT` module (a test file
whose tests import symbols from two destination modules is split by symbol, each half keeping
its fixtures); rewrite code paths in `specs/`, `docs/` (not `docs/cycles-ended/`, not
`docs/adr/`), `CONTRIBUTING.md`, `AGENTS.md`, `.agents/skills/`; run `ruff --fix`; append
`retired:` lines to a `refactor/retired.txt` it maintains. Flags: `--dry-run`, `--check` (the
tree equals the mapping's result), idempotent. Its tests run it on the toy package and compare to
expected trees byte for byte. `refactor_gate.sh` is the nine checks above in one script.
*Expected:* a move is a command, not a session. *Verified:* the tool's tests; `--dry-run` on the
real tree lists exactly the files the mapping names.

**P46-4 — `tests/architecture/` and the markers.** Move the 25 guards to `tests/architecture/`
and the 18 agent-lane files to `tests/release/`. Add: `test_import_contracts.py` (import-linter
with the baseline ignore list), `test_no_local_imports.py` (baseline 206), `test_module_size.py`
(ceiling = current largest, ratchets down to 700), `test_status_writers.py` (baseline 16,
target 1), `test_ids.py` (the manifest), and in `tests/conftest.py` the autouse fixture that
wraps `monkeypatch.setattr`: patching a name whose original object's `__module__` is not the
patched module fails with "patch the defining module: <module>". Register markers `unit`,
`integration`, `sandbox`, `e2e`, `slow`, `release`, `evals`; a codemod adds `pytestmark` per
current directory; CI jobs select with `-m`; `testpaths` becomes `tests`. *Expected:* lanes no
longer depend on folders, and every later step has its ratchet. *Verified:* the gate passes with
every baseline equal to the measured value; a deliberate new local import in a scratch branch
fails the gate (seen to fail, then reverted).

**P46-5 — `kernel/` and `Home`.** `analyze.py` emits the `Home` dataclass from the 102 names of
`config.py` (paths derived from `DOCKET_HOME`, tunables from their environment variables, same
defaults, same types). The maintainer reviews the generated class once. `kernel/home.py` adds
`current_home()` (a `ContextVar` with the process default) and `use_home(home)` (a context
manager). A codemod rewrites the 307 `_cfg.NAME` reads to `current_home().name`; `config.py`
keeps only what is not a setting (the templates directory lookups) and is renamed into `kernel/`.
The test fixture `use_home(Home(tmp_path))` replaces `repoint_docket_home`, by codemod.
`kernel/clock.py` (`now()`, `monotonic()`) replaces the direct `datetime.now(UTC)`/`time.*`
calls outside tests, by codemod, and the architecture guard forbids them elsewhere. *Expected:*
two homes in one process are possible; no test can reach the real `~/.docket` without asking.
*Verified:* the gate; a new test that runs two `use_home` blocks and asserts disjoint files; the
partial-repointer guard is deleted with its baseline (nothing is left to repoint).

### Phase B — deterministic transformations (P46-6 … P46-11)

**P46-6 — `bootstrap.py`.** One module with plain functions: `build_store(home)`,
`build_sandbox(home)`, `build_driver(home)`, `build_channels(home)`, `build_app(home)` for the
CLI and `build_server(home)` for HTTP. The CLI entry and `serve` call it once. No framework, no
registry: functions returning typed objects. *Expected:* the only module that names a concrete
adapter. *Verified:* the gate; an import-linter contract "nothing but `bootstrap` and
`interfaces` imports `*/adapters`" added to the ignore-list ratchet.

**P46-7 — split `core/dispatch.py`.** The mapping assigns each of the 168 definitions to its
destination (groups from P46-2: queue, settings, prompt composition, record and resume, pre-hop
gates, hop runner, post-hop gates, pipeline executor, lifecycle, operator actions, sweep; shared
types to `tasks/domain/task.py` and `hops/application/record.py`). One commit per destination
module, in leaf-first order so each commit is importable. `_now`/`_parse_iso` go to `kernel`; the
six private names used from outside become public in their new module; the 24 importers are
rewritten in the same commit (no re-export, D-57). `HopResult` and `TaskResult` become frozen
dataclasses with `with_*` methods, and the four functions that mutated a `TaskResult` return the
new value instead. *Expected:* `core/dispatch.py` is gone; the largest resulting module is
≤ 700 lines; the 72 patches on `dispatch` are rewritten to their defining modules (the fixture
from P46-4 proves none was left behind). *Verified:* the gate after every commit; the manifest
shows the same ids under new paths.

**P46-8 — move every remaining module to its context.** One commit per context, leaf-first by the
graph: `platform`, `models`, `observability`, `operator`, `sandbox`, `governance`, `teams`,
`agent`, `tasks`, `pipeline`, `hops`, `interfaces`. Each commit moves the modules, their mirror
tests, and rewrites specs and live docs. `edges/adapters/system.py` is split here into
`platform/process.py`, `platform/git.py` and `sandbox/launch.py` by the P46-2 groups. `jail.py`
and `plugins.py` leave the package root. *Expected:* `cli/`, `core/`, `edges/` no longer exist;
the import-linter ignore list is the exact list of remaining domain→adapter edges. *Verified:*
the gate after each commit.

**P46-9 — split `serve.py`.** A codemod lifts each `if path == …`/`startswith` branch of
`do_GET`/`do_POST` into a function in `interfaces/http/routes/<resource>.py` (tasks, pods,
approvals, inbox, traces, health, metrics, dispatch) and generates `routes/__init__.py` as a
table `(method, pattern) -> handler`; `interfaces/http/auth.py` holds the bearer check once;
`interfaces/http/server.py` holds the handler class, the threads and the stop controller.
*Expected:* `SERVE_API_VERSION` and every response are unchanged. *Verified:* the gate; the
serve test files (`test_serve__*.py`) move beside their route and pass unchanged.

**P46-10 — the embeddable runtime is a package, not a build hook.** With `agent/` depending on
`kernel/` alone (an import-linter contract since P46-8), `packages/docket-runtime/hatch_build.py`
and its 40-file closure are deleted; the distribution includes `docket/agent` and `docket/kernel`
directly, and `docket_runtime/__init__.py` re-exports the same facade names. *Expected:* the
wheel installs and `tests/agent/release/test_runtime_package_boundary.py` passes with the hook gone.
*Verified:* the release lane; `uv build` of the package in a clean venv importing the facade.

**P46-11 — persisted shapes that the structure wants (allowed by D-57).** The task record is
written as the nested shape `{spec, lifecycle, execution, pending}` with the same field names
(camelCase) inside; pod settings move from the Lead's `.docket-meta.json` to `pods/<pod>/
settings.json`; `TASK_LIST.json` stays one document per pod (one file per task waits for a
measured trigger). Readers of the old shapes are deleted, not kept. *Expected:* the live `~/.docket`
is wiped and re-initialized by the operator after this lands (no users, no migration); the HTTP
responses are unchanged because the API serializer flattens. *Verified:* the gate; the operator-api
and serve-read-api tests unchanged; `docket init` + one dispatch on the local model.

### Phase C — bounded judgment (P46-12, P46-13)

**P46-12 — one owner of the task's state.** Input: the table `analyze.py` produced (16 sites:
from-status, to-status, fields set, caller). Output, by a model in one attempt: `tasks/domain/
state.py` with `Status` and `FailureKind` enums, the allowed-transition table, and
`transition(record, to, *, reason="", failure_kind=None, …)` that sets exactly the fields each
transition needs (`completedAt`, `claimId=None`, `pending=None` on a terminal state). A codemod
replaces the 16 sites by AST location. A test is **generated from the table**: every allowed
transition succeeds and sets its fields; every other pair raises `IllegalTransition`. The guard
`test_status_writers.py` ratchets to 1. *Expected:* a new feature cannot add a transition without
adding a row. *Verified:* the gate; the generated test; no behavioural test changes.

**P46-13 — ports for what the ignore list still holds.** After P46-8 the import-linter ignore list
is the exact set of domain→adapter imports left. For each: `analyze.py` emits a `Protocol` from
the signatures the domain uses; `bootstrap.py` binds the real adapter; the domain receives the
port as a parameter or from `current_home()`'s registry. A model handles only the signatures that
are not clean (a function mixing effects), one card per port if more than one is unclean.
*Expected:* ignore list empty, local imports 0, cycle size 1. *Verified:* the gate; a fake per
port in `tests/fixtures/fakes/` passing the same contract suite as the real one
(`tests/contracts/test_<port>_contract.py`, parametrized `[real, fake]`).

### Phase D — final verification and the tests the structure allows (P46-14, P46-15)

**P46-14 — tests that only the new structure allows.** `tests/fixtures/`: `home.py`, `repo.py`
(temporary git repository with lockfile and commits), `builders.py` (`make_task`, `make_pod`,
`make_hop`), `fakes/chat.py` (`ScriptedChat`: a list of turns, each with text and tool calls,
failing when the script runs out) replacing the 7 LLM stubs, and one fake per port. `tests/e2e/`:
eight to twelve named flows extracted from `integration/` (software pod to done, rework cycle,
check_changed park and grant/deny, prepare from lockfile and cache hit, HTTP task lifecycle as
Tack drives it, resume after restart, lights-out profile, approval over Telegram). The flat
`tests/integration/` directory disappears: each file is in its mirror path, in `e2e/` or in
`contracts/`. Every retired test is named in a `retired:` line. *Expected:* no file outside
`tests/architecture/` mentions a module path; `SUBJECT` is deleted everywhere (the mirror path
is the subject) and the layout guard checks the path instead. *Verified:* the gate; monkeypatch
count reported by `analyze.py` (target: patches only on `kernel.clock` and `os.environ`).

**P46-15 — the live run, before and after, and the close.** Before P46-6 the integrator records a
baseline: `scripts/maint/capture-doc-journey.sh` on the local model plus one real dispatch
through the HTTP API, keeping the trace files. After P46-14 the same two runs are made; the
traces are compared event by event (same event names, same gate outcomes, same transitions; ids
and timestamps masked). `CLAUDE.md`, `AGENTS.md`, the `docket-*` skills and `CONTRIBUTING.md` are
rewritten for the new layout by hand (paths by the tool, prose by the integrator); `CHANGELOG.md`
records the change under "Changed (internal)". The `refactor/` directory (mapping, analysis,
retired list) is deleted in the close commit: the architecture tests are the durable record.
*Expected:* identical behaviour with the metrics at their targets. *Verified:* the trace diff is
empty; the gate; the Phase 46 acceptance below.

## After Phase 46 (amended 2026-10-23)

Phase 46 moved the tree, split every module over 700 lines, wrote `bootstrap.py` and the route
table, and put the contracts in `tests/architecture/`. It closed against **recorded baselines that
only shrink** (748 import exceptions, 20 function-local imports), not against the empty lists the
acceptance below names; a real run matched the pre-move baseline hop for hop. Steps P46-10, 12, 13
and 14 continue as Phase 47 cards; P46-11 waits for a measured need. Measuring the 748 exceptions
showed four things this ADR had left open.

### A context's public surface is an explicit `__all__`

*Amended 2026-10-23:* a facade is the preferred surface of a context, not a condition of reaching it
(§"The contexts are layered"). `platform` and `operator` have one and keep the dead-export check;
a context that declares no `__all__` is reached through its modules.

624 of the 748 exceptions import another context's internal module, because every context
`__init__.py` was empty: the rule "talk through `__init__`" had nothing to talk through. Each
context's `__init__` re-exports exactly the names other contexts import, under `__all__`, and the
contracts test fails on an export nothing outside the context uses (dead code applies to a facade
too). `platform` and `sandbox` are contexts like the rest and are reached the same way.

*Rejected:* a port for every edge (624 protocols and bindings, with no less coupling); letting
`interfaces` import `application` modules (it legalizes the CLI reaching into a domain type and
leaves the domain edges open); re-exporting every name (it hides the boundary instead of drawing it).

### Ports only where a test fakes a boundary or a contract forbids the import

Hexagonal ports between internal packages are what produced the 748: a port was asked for where a
facade was needed. A port exists in two cases. **A boundary that tests fake** (git, processes, the
sandbox launcher, the LLM, outbound channels): today the tests reach them by patching a private
alias (113 patches on `_git`, `_launch`, `_process`), which breaks on any refactor. **An import a
contract forbids** (`agent` depends on `kernel` alone, so what it needs from a context is a port in
`agent/ports.py`). The store is not a port: it is the one JSON chokepoint, and no test fakes it.

A port is a `Protocol` plus a `Binding` (`kernel/ports.py`): `bootstrap.bind_adapters()` binds the
real adapter at each entry, the test conftest binds the real one by default, and a test swaps one in
for a block with `<port>_port.use(fake)` (or a `real_<port>_except(...)` fixture for one replaced
call). The kernel holds git, process, jail and tracer; `agent/ports.py` holds the ones that are the
engine's own (`RoleComposer`, `ToolGate`).
Each port has one fake and a contract suite run against both, `[real, fake]`. No DI framework.

### A context's `domain/` is a functional core for decisions

The design principle is "functional core, imperative shell" (Gary Bernhardt, *Boundaries*, 2012).
The core is functions that receive data and return a decision, with no file, process, clock or
environment access. The shell, in `application/` or `hops/gates/`, gathers the facts, calls the
core and performs the effects. In docket it applies to **decisions**: task state transitions,
gate outcomes, budget and token limits, profile requirements. It does not apply to LLM calls,
git, the store or processes; those stay in the shell and are not made pure.

The evidence: `status` has 16 writers with no transition table; `tasks/domain` and
`pipeline/domain` import `application` modules, `teams`, `governance` and `sandbox` (10
exceptions), so the domain reads state instead of receiving it; the post-hop gates (605 lines)
mix running a command, writing a reasons file and tracing with the decision, and no test names
them as subject. The payoff is that a rule is tested as a table of cases, without disk or patches,
and read in one place. The check is the existing domain contract plus a table test per decision;
`decide()` in `tasks/domain/state.py` is the first instance (item 3 above).

### `agent` is the turn engine (P47-3, 2026-10-23)

`agent/` held three things; it keeps one. **The engine** is the loop, the session and its
compaction, the context fit, the chat vocabulary, the tools registry with its one chokepoint
`dispatch_tool`, the built-in tool handlers and the adapter that turns an MCP server's tools into
registry tools. It imports `kernel`, `platform`'s `__init__` and its own modules.

**The composition of a pod turn** moved to the contexts that know what it composes:
`hops/application/driver.py` (`DocketDriver`), `hops/application/isolation_posture.py`,
`hops/workspace/skills.py`, `teams/identity.py` (the system prompt from the workspace; it reads
fleet, pod and pod memory, which is why it is in `teams` and not in `hops`), `teams/agent_memory.py`,
`teams/conversations.py` and `teams/mcp_servers.py` (the server declarations; the config model they
share with the adapter is `kernel/mcp.py`).

**The governance** that sat inside the chokepoint moved to `governance/gate.py`: `govern` combines
the command classifier and the `pre_tool_call` policy, audits, and settles an `ask` by pre-grant,
refusal, parking or an approval wait. The decisions are pure functions in `governance/gate_rules.py`
with table tests. `dispatch_tool` reaches it through the `ToolGate` port (`agent/ports.py`:
`govern`, `audit_refusal`, `audit_event`, `screen_untrusted`) and stays the only way a call runs;
`registry.py` imports nothing from `governance` and is 284 lines. The vocabulary both sides share
(`GateCall`, `GateDecision`, `Screened`, the context and tool protocols) is `kernel/gate.py`, so
neither imports the other.

**What the engine asks of its neighbours** is three more ports: `RoleComposer` (narrow the registry
for a role, the role's declared budget, compose the system prompt; adapter `teams/role_composer.py`),
`Tracer` (`kernel/ports.py`; adapter `observability/adapters/local_tracer.py`) and the chat
vocabulary, which moved into `agent/ports.py` because the model adapters import it. All are bound in
`bootstrap.bind_adapters`; the runtime package binds `ToolGate` in `_bind.py`.

**The runtime closure is computed.** `packages/docket-runtime/hatch_build.py::runtime_closure`
follows the import-time imports of the facade package through `src/docket` and ships those files
(51, from a hand list of 55), still renamed into `docket_runtime._internal.docket` because the
package may own no `docket/` path. Imports inside a function are not followed: they belong to
features the runtime does not ship (the task ledger an approval denial joins). The build hook stays
for that rename; `tests/guards/test_runtime_closure.py` pins what the closure holds and what it never
may (no task, pipeline, hop, interface or loop module).

**Two named exceptions remain in the `agent` row of the baseline**, both in `builtin_tools.py`: the
`skill` tool reads `hops.workspace.skills` and the `consult` tool runs
`tasks.application.consult`. `builtin_registry()` registers them with the other built-ins, and it
is the default tool set that `teams/report.py`, the role narrowing and a dozen suites count; moving
their registration to the driver changes that set and is a decision for its own card. The baseline
went from 625 to 600 lines over the card (the `agent` row 51 to 2); the edges of the moved modules
sit under the `application` row with their new names (until 2026-10-23 the rule asked for a
facade; §"The contexts are layered" replaced it).

*Rejected:* a facade for `agent` (it would import the loop, the session and the built-in tools at
`import docket.agent`, and the runtime wheel would ship them); one `Governance` object with a
method per `ToolContext` field (the Protocols in `kernel/gate.py` list the thirteen fields the gate
reads, and `ToolContext` satisfies them without knowing).

### The contexts are layered (amended 2026-10-23, P47-9)

The rule "a context talks to another only through its `__init__`" measured the wrong thing. Only
`platform` and `operator` got a facade (P47-8); the other eight could not, for two reasons measured
on `60d3d90d`:

- **The contexts are not acyclic, so a facade turns each upward import into an import cycle.** Over
  the module-level `import` and `from ... import` statements between the 11 contexts (53 pairs,
  311 imports; 318 counting function-local ones) the best of all 2^11 orders still has 56
  upward imports (62 with function-local). A package `__init__` that binds names runs on any
  submodule import, so an upward import through a facade is a cycle at import time.
- **A facade drags itself into the runtime wheel.** Any context the runtime imports brings the whole
  facade with it, and `tests/guards/test_runtime_closure.py` forbids task, pipeline, hop, interface
  and loop modules in the closure.

Of the 549 lines of the baseline before this amendment, 273 were `interfaces` -> a context (always
downward), 213 were context -> context downward in the order below, and only 61 were upward: the
real design debt. The rule counted all 549 as the same defect.

**The new rule is a layers contract** (the standard import-linter idea). The contexts have one
fixed order, bottom to top:

`platform` < `governance` < `agent` < `models` < `observability` < `pipeline` < `teams` < `sandbox`
< `operator` < `tasks` < `hops`

A context imports any module of a context below it and its own package; `interfaces` imports any
context; importing a context above is the violation, recorded in the baseline and shrink-only. The
rest of the table is unchanged: `kernel` imports nothing outside `kernel`; `<context>/domain`
imports `kernel` and its own `domain`; adapters, `platform` and `sandbox` keep their row; `agent`
imports `kernel`, `platform`'s `__init__` and its own modules; nothing imports `interfaces`; no
function-local `docket.*` import. A facade stays the preferred surface where one exists, and
`platform` and `operator` keep theirs with the dead-export check.

**Where the order came from.** An exact search over all subsets (a dynamic program over the 2^11
orders, ties broken alphabetically, run as a throwaway script over `src/` at `60d3d90d`) gives the
same minimum, 56 module-level upward imports, as the order above, which a local search had found;
it does not give fewer, so the order above stands. Counted as the contract counts, with
function-local imports, the baseline holds **62 upward imports** (60 under the `application` row,
2 under the `agent` row) in 65 lines. The ten largest upward pairs:

| Importer -> imported | Imports |
|---|---|
| `pipeline` -> `hops` | 10 |
| `tasks` -> `hops` | 9 |
| `pipeline` -> `teams` | 6 |
| `governance` -> `teams` | 6 |
| `teams` -> `hops` | 5 |
| `models` -> `teams` | 5 |
| `teams` -> `tasks` | 4 |
| `governance` -> `pipeline` | 4 |
| `pipeline` -> `tasks` | 3 |
| `governance` -> `tasks` | 3 |

The remaining three lines are exceptions of rows the amendment kept: `models/provider_lifecycle.py`
imports its own adapter (`application` row), `models/adapters/openai_http.py` imports
`governance.secrets` and `operator/adapters/telegram.py` imports `interfaces.telegram.client`
(`adapters` row).

The baseline went from 549 lines to 65. Every line left is an upward import or one of those
exceptions, and one line is new only because the old rule let it through a facade:
`teams/config_docs.py` -> `operator`, an upward import now that the order puts `operator` above
`teams`.

*Rejected:* a facade for every context (the cycles and the runtime wheel above); the order by
fewest-imports-first alone (it does not look at direction); keeping the old rule and leaving the
baseline at 549 lines (the number then says nothing about which of them are debt).

### Tests: what the 2026-10-23 audit changed

The test layout in item 5 and in P46-4/P46-14 is replaced by the audit's: lanes stay directories
(`unit`, `integration`, `guards`, `architecture`, `agent`, `golden`), not markers; shared helpers
and the fakes live in `tests/support/`, one owner each; integration files sit under
`integration/<context>/`, at most 800 lines, and `SUBJECT` names the entry module they drive;
a unit file opens no socket or process. A test stays only if it pins a `specs/` requirement, pins
live-path behaviour nobody would notice breaking, or is the regression of a defect found by
running the product. The `test_ids.txt` manifest and the autouse patch wrapper are dropped: the
moves they guarded are done, and AST guards with shrink-only baselines do the same job statically.

### How a change is verified (replaces "the gate after every commit")

Per commit, only the static checks (`ruff`, `mypy src`, `pytest --co`; about 10 s). While
iterating, only the tests of the files touched. At the end of a card, one parallel run of the
default suite (about 50 s), with failures fixed by cause and re-run with `--lf` only. Goldens, the
agent lane and a real run happen once, at the phase close. A check that fails again after one fix
stops the work and reports; nothing is iterated until green. `refactor_gate.sh`, `analyze.py` and
`move.py` are deleted at the Phase 47 close; the architecture tests are the durable record.

## Phase acceptance

Phase 46 closed against recorded baselines (§"After Phase 46"); these clauses are Phase 47's
acceptance.

- `tests/architecture/` passes with: no upward import between contexts (amended 2026-10-23; it was
  "import-linter ignore list empty", and the list now holds only upward imports and the two named
  `agent` exceptions); function-local `docket`
  imports 0; largest module ≤ 700 lines; `status` writers 1; no patch on another module's private
  alias; every unit test file at its module's mirror path and every integration file under
  `integration/<context>/`.
- `docket_runtime` installs from `agent/` + `kernel/` with no build hook.
- The HTTP API 6 tests, the golden suite and the `docket_runtime` boundary tests pass unchanged.
- The before/after live traces are identical modulo ids and timestamps.
- `src/docket` has no `cli/`, `core/`, `edges/`, `serve.py`, `config.py`, `jail.py`, `plugins.py`.

## What this unlocks after Phase 47 (not scheduled; each waits for a measured trigger)

Declarative HTTP routes landed in Phase 46 (P46-9), and dead code by fan-in was deleted before the
move (Wave 120). The rest are behaviour-preserving reductions that the new structure makes safe, each a card with a before/after
measure as its acceptance: the task as a typed aggregate with a repository (−1,500 to −2,000
lines; removes the 639 `Any` annotations, 15 find-by-id loops, 32 store closures); pod settings
as one injected object (−500 incl. tests); a `@degrades_to(default)` decorator for the 30
identical fallback blocks in the system adapter (−250); typed trace and audit events (−300, and
redaction on fields rather than on serialized JSON); hop prompt composition as prioritized sections
(−200); one reader per question (−150). And one small behaviour addition with its own card: reconciliation of a granted
approval whose task is still waiting, at sweep start, preceded by the crash test that shows the
window.

## Non-goals

A framework for agents, a database, FastAPI, a plugin system, event sourcing, a typed verdict tool
(behaviour change; its own card later), agent-quality evals (its own decision; `tests/evals/` is
created empty with a README), one file per task (waits for a measured trigger).
