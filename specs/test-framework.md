# Test Framework

**Version**: 4.0.0
**Status**: Active
**Last Updated**: 2026-10-25

## Overview

Docket's test system has four blocking layers: pytest behavior, byte-for-byte CLI goldens, static
analysis, and specification validation. Docket owns its runtime; tests exercise that runtime
directly and replace only real external protocol/process boundaries.

It also ships whole-flow proofs. They are not a fifth exhaustive layer; they prove the separately
tested components compose across real CLI subprocess and HTTP protocol boundaries into completed,
inspectable tasks. The deterministic ones are the end-to-end lane (`tests/e2e/`, rule 13); the one
that needs a real model is the opt-in live smoke canary.

Each rule below names the check that enforces it. A rule marked **convention** is followed by
review only; no guard fails when it is broken.

## Philosophy

### Coding-harness portability

`AGENTS.md` and `.agents/skills/` are the canonical shared contract for every coding harness.
Claude Code receives a short tracked `.claude/CLAUDE.md` bridge that imports `AGENTS.md` and tells it
to load canonical skills from `.agents/skills`; the repository **MUST NOT** duplicate those skills
under `.claude/skills`, because clients that scan both locations require unique skill names.

Tracked hook configuration (`.claude/settings.json`, `.codex/hooks.json`) **MUST** use a
PATH-resolved `python3` and the harness's documented project-root variable or root discovery, never
a machine-specific interpreter path. Hooks are context convenience only: correctness and
permissions continue to come from the current spec, tests, process sandbox, and operator trust. A
harness that does not run the snapshot **MUST** be able to invoke it manually (the snapshot script
runs standalone). No test pins these requirements.

Model transport and coding harness are independent axes. Gateway tests exercise Docket's public
endpoint/key semantics with deterministic HTTP fakes; they do not use Codex, Claude Code, or
OpenCode as the model backend. Live-model canaries remain opt-in and budgeted.

### Spec-first, then test-first

Behavior changes begin in the owning current-state spec. A RED test must fail for the intended
contract before implementation, and the smallest coherent change makes it green.

### Properties every test must have

- **Hermetic state:** an autouse fixture runs every test inside one `use_home` block on a per-test
  temporary root, so every path the current `Home` derives (traces, approvals, sessions,
  registries, the audit log, the fleet file, the secrets files) lies under it and no test can
  write the operator's real `~/.docket`. A test that needs another root enters its own `use_home`
  block. The fixture does not set the `DOCKET_HOME` environment variable: a test that spawns a
  child process sets it explicitly to a temporary directory.
- **No real credentials or network:** model, Telegram, MCP, and HTTP boundaries use deterministic
  fakes unless a separately-labelled environment test explicitly requires a live service.
- **Real internal path:** tests call the same functions production calls; they do not mock the
  behavior under test.
- **Atomic assertions:** persisted JSON/session/audit state is inspected after the public operation,
  including failure paths.
- **Stable output:** user-visible CLI text is pinned by pytest or a reviewed golden case.

## Test layout

Layout on disk today (the target is rules 11-15 of "Lanes and placement"):

```text
tests/
├── conftest.py             autouse isolation (home, DOCKET_SERVICE_MANAGER=none, plain Typer errors), duration guard
├── support/                the one owner of each shared helper and fixture: home, pods, trace, llm, git, http, cli, fakes, model_server, e2e, e2e_oracles
├── fixtures/               recorded data and adapter-scenario fixtures shared by several lanes
├── unit/                   mirrors src/docket/: unit/tasks/application/test_queue.py ↔ src/docket/tasks/application/queue.py
├── integration/<context>/  one folder per context (plus bootstrap and product): several modules, or a real process or socket
├── guards/                 AST and layout invariants, with shrink-only committed baselines
├── e2e/                    NOT in testpaths; CI job `e2e`; one file per named journey, run as subprocesses
├── golden/
│   ├── cases/readonly/     expected CLI output (*.golden)
│   ├── fixtures/seed.sh    deterministic ~/.docket state
│   ├── fakes/              external executable stubs (docker)
│   ├── scrub.py            normalises unstable values
│   └── run.sh              capture / verify / verify-all / list harness
├── agent/                  NOT in testpaths; CI job `agent-lane`
│   ├── truth/              assertions on prose (README, spec index, positioning, project policy)
│   └── release/            builds or installs artifacts; adapter parity; journeys; adoption evidence
└── run-all-tests.sh        local aggregate gate (default lanes + golden; not the agent lane)
```

The deterministic whole-workflow proofs live in `tests/e2e/`. The live smoke canary's helper tests
and its opt-in wrapper live in `tests/integration/product/smoke/`.

## Lanes and placement

The placement rules below bind every new or edited test file. Rules 1-10 describe the layout the
tree has today and the guards that enforce it. Rules 11-15 are the placement rule new tests follow
under ADR 0030 (D-66): each is a **convention** until the guard it names exists. Where a later
rule changes an earlier one, the later rule names it.

Requirements:

1. **Default suite = product lanes.** `testpaths` lists `tests/unit`, `tests/integration`,
   `tests/guards`, `tests/architecture` and `tests/contracts`, and never collects `tests/agent` or
   `tests/e2e`. Each runs by path in its own CI job: `agent-lane` runs `uv run pytest tests/agent`
   and `e2e` runs `uv run pytest tests/e2e -n auto`. The `no-sandbox` CI job runs the default
   suite through `scripts/maint/pytest-without-sandbox.sh -q`, a host where sandbox detection
   reports `none`.
2. **One unit file per module, named for it.** `unit/<pkg>/test_<module>.py` declares
   `SUBJECT = "docket.<pkg>.<module>"` (a top-level module's file sits directly in `unit/`; the
   part of the stem before `__` names the module). The guard checks that `SUBJECT` equals the
   path-derived name and that the module exists; four named structural files assert their own
   `SUBJECT` verbatim. Every `src/` module over 150 lines has such a file unless it is listed in a
   committed baseline that may only shrink. Every `integration/<context>/**/test_*.py` also
   declares `SUBJECT`, naming the entry module it drives, never a package: the context folder is
   the context of that module, with `kernel`, `interfaces`, `bootstrap` and `product` (a
   cross-context end-to-end flow) as folders too. Unlike the unit rule, a mismatch with the
   file's own name is not an error there: the guard requires only that the module exists, and
   reports every offender in one assertion. A test file is at most 800 lines, checked by
   `test_suite_shape.py`; a longer one splits by flow, as `test_<module>__<aspect>.py` in the
   same folder or, when the halves share an autouse fixture, in a folder of its own with that
   fixture in a `conftest.py`. **Convention** (no guard): file names never encode history (`_v2`,
   `_migration`, `_removed`, `_legacy`, card ids).
3. **A test that reads prose or builds an artifact is agent-lane by definition.** Every file under
   `agent/` declares the module constants `LANE`, `REASON` (the recorded defect it prevents) and
   `RETIRE_WHEN` (the condition, not a date, under which it is deleted); the guard checks that the
   three names exist, not their content. The lane's total line count is ratcheted against a
   committed baseline that may only fall; the lane shrinks when a file's `RETIRE_WHEN` condition
   fires, and lowering the baseline is a commit that also deletes what it accounts for.
   **Convention:** one test per public claim.
4. **`subprocess` is forbidden in `unit/`, and so are sockets and sleeps.** The guard fails any
   `unit/` file that imports `subprocess` or another socket or process module, starts a server
   or a process, or calls `time.sleep`; the files that still do are listed in a shrink-only
   baseline (`suite_shape_baseline.txt`). CLI behaviour is tested in-process with `typer.testing.CliRunner`; exact
   user-visible text belongs to the golden suite. `integration/` spawns a process only when the
   process boundary (signals, sandbox, cancellation, `PATH` stubs) is what the test proves
   (convention).
5. **A retired command name is an ordinary unknown command** (exit 2), pinned by the console-script
   entry-point test. Two guards keep docs, specs, templates, help examples and the source tree free
   of removed command names and of any `docket ...` invocation that is not live in the Click tree.
6. **Duration ceilings** are stop conditions: 2 s per test in `unit/` and `guards/`, 10 s in
   `integration/`, 60 s in `e2e/`. A test that passes but runs past its lane's ceiling is reported
   as failed by `tests/conftest.py`. `agent/` and the golden suite have no ceiling. No pytest marker is registered.
7. **Docstrings and comments follow the repository comment policy**: a module docstring is at
   most 12 lines and a function, class or test docstring at most 3 lines, in `src/` and `tests/`
   alike; no card ids, phases, dates or provenance narration anywhere. The comment-lint script is
   the reader. The comment-hygiene guard ratchets its per-kind counts against a committed baseline
   that only falls: archaeology is held at zero; over-length docstrings are held at their recorded
   (non-zero) counts. The lint's `--check` exits non-zero on archaeology only, so a green lint says
   nothing about the length budget.
8. **Structure is guarded, and each guard is seen to fail before it ships** (convention for the
   second half): unit↔module mapping, lane headers, agent-lane budget, no-subprocess-in-unit,
   duration ceilings, comment hygiene, and the guards listed in rule 10.
9. **The CLI registry module holds the Typer app, the default callback and one registration per
   command**, with every command body in its own `_*` module of the CLI package. No function in the
   registry is longer than ten lines, except the default callback, which is exempt by name.
   Enforced by the layout guard.
10. **Guards** each assert one invariant, with a shrink-only committed baseline where the invariant
    is not yet fully true:
    - *Home isolation.* No path the current `Home` holds or derives resolves into the real
      `~/.docket` under the autouse fixture; `test_docket_home_isolation.py` walks every field and
      property that is a path, so a path added to `Home` is covered without editing the guard.
    - *Single owners.* A setting read from the environment is read in one place,
      `Home.from_environ`; `fleet.json` has one writer and the fleet registry does not duplicate
      what `.docket-meta.json` owns; docket-owned JSON is written only through the store
      chokepoint (two JSONL-append exemptions); only the tool chokepoint imports the tool-handler
      module.
    - *Suite shape.* No top-level helper or fixture is defined, with an identical body, in two
      test files; the one definition lives in `tests/support/`. A unit file opens no socket or
      process and does not sleep; `SUBJECT` names a module; a test file is at most 800 lines;
      the count of `setenv` calls and of `in result.output` asserts on a `--json` command, per
      file, may only fall (`test_suite_shape.py`, `suite_shape_baseline.txt`).
    - *Layering.* The domain and edge layers never print, never import the console helper, and the
      domain layer never imports `subprocess`.
    - *CLI surface.* Every leaf's `--help` exits 0 and carries an `Example:` line, and every
      group's help renders; every `list`/`show`/`status`/`inbox` leaf and the bare
      `log`/`setup`/`setup model`/`setup sandbox` reads print one parseable JSON document under
      `--json` (a reader missing from the guard's argument table fails by name); only the contract
      helper and the listed TTY-checked flows call `input(`/`getpass(`, and every confirming verb
      refuses off a TTY, exits 1 and names its flag; the shell completions advertise exactly the
      live command tree; the count of Rich markup literals outside the console helper may only
      fall.
    - *Dispatch.* `docket start` and dispatch never re-read a repository's `.docket/` or the
      operator's review store; no `contextlib.suppress(Exception)` wraps a dispatch call; the paths
      a member is told to work in lie inside the roots it is gated against.
    - *Repository hygiene.* No Telegram-ID-shaped literal in `src/` and only sanctioned synthetic
      ones elsewhere; no retired-daemon coupling in product code; no function under `src/docket`
      exceeds 150 lines except the listed ones, which may not grow (a baseline records them); the
      numbers of definitions no file names, of definitions only a test names and of groups of
      identical function bodies under `src/docket` may only fall.

11. **Tests mirror the code.** A test file for `src/docket/<path>/<module>.py` lives at
    `tests/<path>/test_<module>.py`, one file per module, and that path is the file's subject. A
    file over 800 lines splits as `test_<module>__<aspect>.py` (rule 2). A module's test moves
    with the module when the module moves into its context package. **Convention** until the
    layout guard checks the mirror path (see rule 14).
12. **Lanes are pytest markers, not directories.** The registered markers are `unit`,
    `integration`, `sandbox`, `e2e`, `release` and `evals`; every test carries the marker
    of its lane, CI jobs select with `-m`, and `testpaths` is `tests`. The duration ceilings of
    rule 6 bind by marker (`unit` 2 s, `integration` 10 s). Rule 1's list of `testpaths`
    directories holds until the markers are registered. **Convention** until then.
13. **Four directories exist for a reason other than mirroring a module, and one holds the shared
    fakes.** `tests/support/` is the one source of shared helpers, fixtures and fakes (`home.py`, `pods.py`,
    `trace.py`, `llm.py`, `git.py`, `http.py`, `cli.py`, `fakes.py`, `model_server.py`, `e2e.py`,
    `e2e_oracles.py`); `tests/fixtures/` holds recorded data only. `tests/contracts/` holds `test_<port>_contract.py`, one suite per
    port, parametrized over the real adapter and the fake in `tests/support/fakes.py`, so a fake
    is proven to behave as the real one. `tests/e2e/` is real and holds named whole flows, one
    file `test_<journey>.py` per journey, named in the operator's words (a software pod to done, the
    rework cycle, a park and its grant or deny, a resume after restart). An end-to-end test runs
    the product the way a person or the plan of record runs it: it enters through a `docket`
    subprocess (`World.docket`) or over HTTP to a `docket start` subprocess (`World.service`),
    works on a real `DOCKET_HOME` and a real git repository, replaces nothing inside docket (the
    only fake is the model, reached through the real OpenAI-compatible wire), judges by what an
    operator sees (task state, `task diff`, files, `log verify`, the trace), and runs a named
    journey to its end (`done`, `failed` with the expected reason, or parked with a token). A test
    that needs to patch docket is an integration test. An end-to-end test **MUST NOT**
    `monkeypatch` a `docket.*` name or call docket in-process; its settings reach docket only as
    environment variables of the subprocess; it imports `docket.*` only in
    `tests/support/e2e_oracles.py` (read-only domain tables) and in skip conditions; it waits on a
    condition with `World.wait_for`, never `sleep`; its expected trace skeleton is a list written
    inline in the test and is never regenerated to hide a change. The oracles are shared in
    `tests/support/e2e_oracles.py`: the trace skeleton, audit coverage of every gate denial and
    handler refusal, legal task transitions, an untouched checkout, an untouched sentinel file
    under the fake home, and a verifying audit chain.
    `tests/architecture/` holds the import-linter contracts and the shrink-only ratchets (import
    contracts, function-local `docket` imports, module size toward the 700-line ceiling, writers
    of a task's `status`, the test-id manifest). `tests/release/` is the agent lane of rule 3 under
    its new name and keeps its `LANE` / `REASON` / `RETIRE_WHEN` headers and its line budget.
    `tests/evals/` is reserved for agent-quality evals and holds a README only. `tests/guards/`,
    `tests/agent/` and the context folders of `tests/integration/` hold until their files are moved
    into these directories and mirror paths.
14. **`SUBJECT` ends.** Once rule 11 is checked by path, no test file declares `SUBJECT`, the
    layout guard derives the subject from the path, and no file outside `tests/architecture/`
    names a module path in a string. Until then rule 2 stands.
15. **A patch targets the module that defines the patched name.** An autouse fixture fails any
    `monkeypatch.setattr` whose original object's `__module__` is not the module patched, with
    "patch the defining module: <module>"; the targets a test patches at the process boundary are
    `docket.kernel.clock` and `os.environ`. **Convention** until the fixture exists; the
    existing patches on other modules are a baseline that only shrinks.

Run every guard with `uv run pytest tests/guards`.

### Live smoke canary

The deterministic full-workflow proofs are journeys of the end-to-end lane (`tests/e2e/`, rule
13), run against the fake model through real CLI subprocesses and a real `docket start`: a pod to
done through a park and its grant, two pods in one service where one waits for a person while the
other finishes, and a pipeline step that declares its own approval. `scripts/smoke_workflow.py`
holds no scripted model and no deterministic mode; it is only the live canary:

```bash
uv run python scripts/smoke_workflow.py --live-model
```

Run without `--live-model`, the command **MUST** print a `SMOKE FAIL` line that names
`tests/e2e/` and exit 2, and **MUST NOT** start any endpoint. A live run **MUST** exercise,
display, and verify this sequence:

1. Declarative provisioning of an `agentic-product` pod (`docket init --from`).
2. Task delegation and rendering of the resolved pipeline plan.
3. Lead planning, an Implementer tool call through `dispatch_tool`, and a real mechanical file
   check.
4. Reviewer verdict, a pipeline-defined human approval pause, CLI approval, exact-position resume,
   and final Tester verdict.
5. Terminal task state plus typed handoffs, isolated durable step histories, an atomic tool-call/
   tool-result pair, traces, audit chain, measured usage, and two run records (the parked dispatch,
   then the one that succeeded).

Its final output **MUST** name each verified stage and end in one unambiguous `SMOKE PASS` line; a
failure prints `SMOKE FAIL` to stderr and exits 1, and a refused invocation exits 2. `--workdir
<path>` preserves the otherwise-temporary world for inspection and must name a new or empty
directory.

The `basic` scenario's artifact contract is byte-exact: `smoke-artifact.txt` **MUST** contain
exactly the 16 UTF-8 bytes `docket smoke ok` followed by one LF. Its delegated task text **MUST**
state the terminal-LF requirement, its Implementer mechanical gate **MUST** reject the 15-byte
no-newline variant as well as any extra byte/line, and the harness **MUST** retain an independent
final exact read assertion after the pipeline completes.

Options: `--live-model` (required), `--endpoint` (loopback base URL, default
`http://127.0.0.1:8081/v1`), `--model`, `--scenario basic|memory-maintenance` (default
`memory-maintenance`), and `--workdir`.

An explicitly selected live-local canary **MUST** run the same workflow against a real
OpenAI-compatible model without replacing its replies. An endpoint override **MUST** remain
loopback-only and the harness **MUST** discover the loaded model from `/models` unless the operator
supplies its id. The canary **MUST** configure only its temporary `DOCKET_HOME`, through
`docket setup provider add` and `docket setup model set` (the lead, implementer, reviewer, tester
and default roles) and `docket setup sandbox off`, send no API key, and make no exact
response-text or request-count assumption beyond the task's real artifact and pipeline gate
contracts. It **MUST NOT** tighten the product's normal turn, tool, token, or output limits merely
to make the canary predictable.

The default live scenario **MUST** be `memory-maintenance`, a realistic code-repair task whose
critical current decision exists only in the Lead's private `MEMORY.md`, which the canary seeds in
its isolated home (superseding decisions: integer-cent half-up tax arithmetic and a receipt tenant
value). The scenario **MUST** delegate a task that refers to durable project decisions without
restating their values. Its acceptance **MUST** prove the Lead carried the current decision
through its typed artifact and that the Implementer repaired a real module against a pre-existing
failing regression suite and a behavioral check that sits outside project-tool roots. The public
regressions **MUST** define the arithmetic edge and required metadata shape without revealing the
current private tenant value, so the model does not have to invent expected behavior and memory
transfer remains necessary. Before delegation, the canary **MUST** run that suite and prove it is
red for precisely those seeded defects, then commit the seed as a real Git repository before pod
provisioning. Mechanical and hidden acceptance **MUST** inspect the Implementer's effective
worktree rather than the untouched origin checkout.

The delegated task **MUST** direct every downstream role to consume those durable decisions only
through the Lead's typed handoff, explicitly forbid searching for or accessing Docket private
control paths (`MEMORY.md`, `HEARTBEAT.md`, `memory/`, and `.docket`) with project tools, and
**MUST NOT** restate the private fact values. That complete instruction **MUST** fit the public
`docket task add` 500-character description ceiling and be delivered through that real CLI
boundary. Because opaque shell execution fails closed, the same instruction **MUST** tell
downstream roles to mutate source through structured `edit`/`write` tools, spell the fixture
README's regression command byte-for-byte as the only allowed shell command, and prohibit
alternative runners, wrappers, inline code, and redirections.

The final oracle **MUST** reject every project-tool attempt on a private path even when the target
is absent, the read is denied, or later session compaction removes the call from retained
messages; a failed probe is not evidence of respecting the private-context boundary. Durable
`tool_call` trace arguments are the historical authority and retained session calls are a defense
in depth. The oracle **MUST** classify structured tool targets and selectors rather than searching
raw argument or editable-content text: it checks the path field for `read`, `write`, and `edit`;
path plus pattern for `glob`; path plus file-glob for `grep` without treating the search expression
as a target; and path-like shell tokens for `bash`, including nested `sh -c`/equivalent command
text. It semantically normalizes each path against the role's actual runtime root before comparing
exact case-insensitive path components; the Lead uses the origin checkout while Implementer,
Reviewer, and Tester use the Implementer's effective worktree once it exists. A non-universal
selector component capable of matching a private component is also private, while a
root-contained universal selector such as `**/*` remains valid. The origin checkout and physical
worktree are the only trusted roots, and must match the canary's expected layout plus Implementer
metadata before either prefix is exempted. Opaque shell text, common command-wrapper indirection,
and execution of project-controlled interpreter or shell scripts fail closed unless the effective
command is the canary's known regression-suite entrypoint; a known project tool's undecodable
arguments also fail closed.

The live approval monitor and the final trace/session oracle **MUST** consume the same typed
verdict: `allowed`, `confirmed_private`, or `opaque`. Confirmed-private and opaque calls are
distinct diagnostic outcomes, but both disqualify the canary and fail closed. When granting a live
`bash` approval, the monitor **MUST** classify the most recent durable trace call matching that
approval's role, tool, and call id rather than wrapper prose or an older colliding id. A diagnostic
contains only source, role, tool, call id, verdict, and a privacy-safe marker; it never includes
raw arguments or private values. On the first disqualifying pending approval, the operator **MUST**
cancel the active run (`docket task cancel`) and deny the approval (`docket task deny`) through the
public CLI, then terminate the blocking canary subprocess so no later model transport or tool grant
can occur. This fail-fast cleanup preserves the already-durable approval/session/trace/audit
evidence, never executes the denied handler, and cannot turn the cancelled run into success.

Exact model prose is not contractual; retained fact values and the resulting behavior are. If the
un-scripted agent requests a policy-gated `bash` validation, the canary **MUST** exercise a genuine
operator grant through `docket task approve` in its isolated home; it **MUST NOT** disable the
policy or shorten its timeout. Pipeline approval remains a distinct, explicit pause/resume
assertion. `--scenario basic` **MUST** retain the smaller live workflow for focused infrastructure
diagnosis.

Because the canary requires mutable local infrastructure and un-scripted inference, it **MUST** be
opt-in rather than a blocking default-suite dependency. The pytest wrapper runs the live
`memory-maintenance` scenario only when `DOCKET_RUN_LIVE_SMOKE=1` (`DOCKET_LIVE_SMOKE_ENDPOINT` and
`DOCKET_LIVE_SMOKE_MODEL` select the endpoint and model); the standalone live command is the
acceptance evidence.

Test files use `test_<owned_behavior>.py`; card IDs belong in commit history, not permanent
filenames.

## Pytest suite

### Pointing Docket at a temporary world

Every test already runs inside the autouse `use_home` block in `tests/conftest.py`: a `Home` under
`tmp_path` that holds every home-derived path, the audit log, the fleet file and the secrets files.
A test that needs a home of its own choosing wraps its body in `use_home(Home(path))`; a field on
top of the current home is set with `use_home(dataclasses.replace(current_home(), field=value))`.
The block ends with the test, so nothing is restored by hand. A helper that seeds a home is a
context manager the test enters, or a yield fixture; a server serves the home it was built in, so a
fixture builds its server after the home it serves is current, and a thread a test starts goes
through `docket.kernel.threads` so it runs in the home of the code that started it.

```python
from docket.kernel.home import Home, use_home


def test_example(tmp_path):
    with use_home(Home(tmp_path / ".docket")):
        ...
```

`tests/conftest.py` also provides `register_local_provider` (a keyless loopback provider document in
a given home) and `record_isolation_off` / `record_isolation_on` (record the sandbox mode in a
home's `fleet.json`).

For turn behavior, inject a deterministic `ChatBackend`, or use the `fake_model` fixture
(`tests/support/model_server.py`), a loopback OpenAI-compatible fake that serves scripted
replies by role or by request order, and fails on demand. For driver-bound behavior, use `FakeDriver` from
`tests/support/fakes.py` or a purpose-built fake implementing `RuntimeDriver`. Patch an edge adapter only
when the contract being tested ends at that external boundary.

### State safety

- Never infer test paths from the operator's real home.
- Never mutate module constants without pytest restoration.
- Never call a live model endpoint, Telegram API, MCP server, Docker daemon, or Git remote from the
  default suite.
- When testing subprocess behavior itself, create the minimum executable stub under `tmp_path` and
  prepend only that directory to `PATH`.
- The default suite **MUST** pass on a host with no sandbox backend. `scripts/maint/pytest-without-sandbox.sh [pytest args]`
  runs it with `DOCKET_SANDBOX_PROBE=none`, which hides Landlock and `sandbox-exec` (Docker is never
  probed unless the operator chose it), after asserting that detection reports `none`. Forcing
  `DOCKET_SANDBOX_BACKEND=none` is not that check: a fixture that deletes the variable falls back to
  detection. A test that wants no jail calls `record_isolation_off`. The `no-sandbox` CI job runs the
  script.

## Golden parity suite

`tests/golden/run.sh` seeds a deterministic fake `~/.docket`, runs the real launcher, scrubs only
unstable values (home and temp paths, timestamps, dates, durations, relative times, tmp/lock file
names, long hex ids, ANSI), and compares the snapshot (an `EXIT:<code>` line, stdout, and a
`---STDERR---` section when stderr is non-empty) byte-for-byte with `tests/golden/cases/`. A case
id is the command words joined with underscores.

```bash
bash tests/golden/run.sh verify-all
```

`capture <cmd...>` writes a case, `verify <cmd...>` checks one, `list` lists them. Use `capture` only
for an intentional CLI contract change. Review the diff; never regenerate a golden merely to hide an
unexpected output change.

## Static and specification gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
bash scripts/validate-specs.sh
uv run python scripts/metrics.py --check
```

ShellCheck covers the launcher, installers, scripts, and golden harness in CI. The dependency-floor
job resolves the minimum declared direct versions and runs pytest against them.

CI jobs: `python` (ruff, format, mypy, `uv run pytest`, `metrics.py --check`), `agent-lane`
(`uv run pytest tests/agent`), `docs` (the generated-reference drift checks
`gen_cli_docs.py`, `gen_evidence_schema.py`, `gen_recipe_docs.py` and `gen_operator_schemas.py`, each
with `--check`, then a strict mkdocs build), `floors`, `golden`, `shell` (ShellCheck and
`validate-specs.sh`), `macos` (pytest and goldens, advisory: `continue-on-error`), and
`release-journey` (the release journey plus the escape matrix, `tests/integration/sandbox/test_escape_matrix.py`,
on `ubuntu-latest` and `macos-latest`).

### Immutable release-artifact oracle

The release gate MUST exercise the tagged release boundary, not a checkout or mutable branch
archive. The release workflow MUST build the canonical root wheel and sdist, publish SHA-256
verification data for every downloadable install asset, produce an SBOM, and request build
provenance/attestation. Publication MUST be a separate protected job (`environment: release`) that
`needs` the build job and consumes only its verified artifacts; ordinary branch pushes cannot
publish merely because they are newer.

The remote `install.sh` path MUST resolve an explicit versioned GitHub release asset, fetch its
matching checksum, and verify bytes before invoking `tar`, Python, or any package installation.
A one-byte mismatch MUST exit nonzero before extraction and leave the requested prefix untouched.
The closest valid asset/checksum pair MUST pass verification and reach extraction. Installer tests
MUST fake only the network/archive edge and run the real installer control flow; they MUST NOT
contact GitHub or read the developer's Docket home.

The Homebrew formula MUST use the same tagged release asset as the workflow/installer, declare
Apache-2.0, and carry a non-placeholder 64-hex SHA-256. A separate test compares that pin with the
published `.sha256` sidecar over HTTPS and skips when the release is not published yet or the host
is offline. The existing artifact-only wheel/sdist tests remain the independent oracle that both
package formats install outside the checkout, expose the canonical `docket` executable, and report
the tagged package version.

### Artifact-installed release journey

The release exit gate MUST run as one command:

```bash
uv run python scripts/release_journey.py
```

The command MUST create a unique temporary world and loopback port, build the canonical root wheel,
install that exact artifact into a fresh virtual environment, clear source-import overrides
(`PYTHONPATH`, `PYTHONHOME`, inherited model endpoint variables), and invoke only the installed
`docket` executable from outside the checkout. Its deterministic OpenAI-compatible recorder is the
only replaced edge; provider registration, initialization (`docket init --from`),
delegation/dispatch, the agent loop, `dispatch_tool`, stores, trace, and audit MUST use production
public paths. No real credential, paid provider, developer Docket home, or non-loopback network may
be read.

The successful journey MUST prove a model request advertised tools, a governed tool call produced
the exact `docket release journey ok\n` side effect, the subsequent request carried its tool result,
and a final assistant turn reported measured usage. The installed module and executable MUST resolve
inside the fresh environment rather than the checkout. Terminal task/run state, a complete
assistant-call/tool-result session unit, trace events, and a clean non-empty audit chain MUST remain
inspectable after the command. A bounded `journey-evidence.json` recorder file MAY carry only
artifact/interpreter paths and boolean/count wire metadata; it is not a substitute for inspecting
the durable product state. Success MUST end with `RELEASE JOURNEY PASS`.

An unreachable loopback endpoint MUST fail provider validation without registering that provider,
initializing the release-journey project, dispatching a model request, writing the tool artifact, or
creating trace/audit evidence. Failure output MUST be bounded and actionable without a traceback or
credential value. `--workdir <new-or-empty-path>` MUST preserve either outcome for inspection.

The same command MUST be a blocking CI matrix job on `ubuntu-latest` and `macos-latest`; the macOS
release journey MUST NOT inherit the advisory `macos` job's `continue-on-error` waiver.

### Public release-truth oracle

The public-truth gate treats the root README, the compatibility and security guides, the docs
index, the quickstart, the model-gateway guide, the simple security guide, the command reference,
and the checked-in example configs' README as one release surface. Every repository-relative
Markdown link in that surface MUST resolve. The command reference MUST NOT advertise the inert
`DEBUG=1` environment variable as runnable guidance. The README MUST NOT describe cancellation as
killing the in-flight hop's process group (the docs index states the cooperative limit: cancel
requested, honoured at a safe checkpoint) and MUST NOT present a mutable-branch URL for
`install.sh` as a release install; installer guidance pins immutable tagged installer/archive
bytes. The README and quickstart never type a pod name in the newcomer path.

The quickstart MUST contain one ordered route from the current tagged artifact through
`docket setup provider add`, `docket init --recipe`, `docket task add`, `docket run`,
`docket task list`, `docket task show <id>`, `docket task trace <id>` and `docket pod export`. The
artifact-installed release journey is the behavioral oracle for the documented route; documentation
checks MUST bind its public commands to that already-live path instead of replacing it with a
prose-only or source-mode assertion.

The README runtime section MUST describe only the versioned `docket_runtime` gated-tool facade and
MUST state that `docket-runtime` is not published to any package index. A minimal checked-in
embedding example MUST build and install the runtime wheel in a fresh environment outside the
checkout, import only the public facade, dispatch one governed tool call, and leave inspectable
trace/audit evidence without importing the root `docket` package.

Every spec on disk MUST have a row in the `specs/README.md` index whose version and canonical
status category match the owning spec header. A spec MUST NOT carry a `## Changelog` section: its
history is `git log` and `CHANGELOG.md` (enforced by `validate-specs.sh`). Package and formula names
in public installation guidance MUST match their built artifact metadata. The gate MUST use
temporary Docket/build state and only the runner's already-synced dependency environment; the
runtime artifact install MUST run offline, and the gate MUST NOT contact a model provider, package
index, or the developer's real home.

## Full validation

```bash
uv run pytest
bash tests/golden/run.sh verify-all
uv run ruff check .
uv run ruff format --check .
uv run mypy src
bash scripts/validate-specs.sh
uv run python scripts/metrics.py --check
uv run python scripts/gen_cli_docs.py --check
uv run python scripts/gen_evidence_schema.py --check
uv run python scripts/gen_recipe_docs.py --check
uv run python scripts/gen_operator_schemas.py --check
uv run pytest tests/agent
uv run pytest tests/integration/sandbox/test_escape_matrix.py
uv run python scripts/release_journey.py
bash scripts/maint/pytest-without-sandbox.sh -q
uv run python scripts/maint/comment_lint.py --check
```

`uv run python scripts/maint/comment_lint.py --check` is run on touched files before handoff. The
no-sandbox run and the comment lint are local gates; the other commands are CI jobs.
Environment-dependent skips are acceptable only when the owning contract labels them optional and
the skip reason names the missing capability.

## Implementation

Where the names used above live today.

- `src/docket/interfaces/cli/app/__init__.py`: the CLI registry (rule 9); `src/docket/interfaces/cli/commands/task.py`: the
  500-character task description ceiling.
- `src/docket/kernel/home.py`: `Home`, `current_home`, `use_home`, which the autouse fixture and
  every test home go through.
- `src/docket/agent/ports.py`: `ChatBackend`; `src/docket/agent/ports.py`: `RuntimeDriver`;
  `src/docket/agent/tools/registry.py`: `dispatch_tool`.
- `src/docket/sandbox/launch.py`, `src/docket/sandbox/landlock.py`,
  `src/docket/sandbox/seatbelt.py`: sandbox detection and `DOCKET_SANDBOX_PROBE`.
- `tests/conftest.py`: the autouse home fixture,
  `register_local_provider`, `record_isolation_off`, `record_isolation_on`, the lane duration guard.
- `tests/support/fakes.py`: `FakeDriver`; `tests/support/model_server.py`: `FakeModel`, `fake_model`.
- `tests/support/e2e.py`: `World`, `Result`, `Service`; `tests/support/e2e_oracles.py`: the oracles
  of rule 13; `tests/e2e/conftest.py`: the `world` fixture.
- `tests/guards/`: `test_layout.py` (unit and integration `SUBJECT`, large-module baseline
  `layout_baseline.txt`, CLI registry), `test_lane_headers.py` (agent headers, no `subprocess` in
  unit), `test_agent_lane_budget.py` (`agent_lane_baseline.txt`), `test_comment_hygiene.py` (with
  `scripts/maint/comment_lint.py` and `scripts/maint/comment-baseline.json`),
  `test_function_span.py` (`function_span_baseline.txt`, `scripts/maint/measure_function_spans.py`),
  `test_dead_code.py` (`dead_code_baseline.txt`, `scripts/maint/measure_dead_code.py`),
  `test_docket_home_isolation.py`, `test_home_single_owner.py`, `test_fleet_registry.py`,
  `test_no_print_in_core_edges.py`, `test_no_ui_in_core_edges.py`, `test_no_subprocess_in_core.py`,
  `test_cli_help_examples.py`, `test_cli_json_surface.py`, `test_cli_prompt_sites.py`,
  `test_completions_drift.py`,
  `test_console_voice.py` (`console_voice_baseline.txt`), `test_cli_invocations_true.py`
  (`scripts/maint/lint_cli_invocations.py`), `test_no_removed_cli_names.py`
  (`scripts/maint/rewrite_cli_names.py`), `test_dispatch_never_rereads_the_repository.py`,
  `test_no_suppressed_dispatch.py`, `test_workspace_root_agreement.py`,
  `test_no_hardcoded_telegram_ids.py`, `test_no_external_daemon_coupling.py`.
- `tests/unit/test_store_writer.py`: the store single-writer guard;
  `tests/unit/agent/tools/test_registry.py`: the tool-chokepoint import guard.
- `tests/integration/bootstrap/test_console_script_entry_point.py`: retired names are unknown commands;
  `tests/integration/product/smoke/`: the live smoke canary's helper tests and opt-in wrapper;
  `tests/integration/sandbox/test_escape_matrix.py`: the escape matrix.
- `tests/agent/release/`: `test_public_release_truth.py`, `test_release_artifacts.py`,
  `test_release_journey.py`, `test_distribution_package.py`, `test_runtime_package_boundary.py`.
- `tests/golden/`: `run.sh`, `scrub.py`, `fixtures/seed.sh`, `fakes/docker`, `cases/readonly/`.
- `scripts/smoke_workflow.py`, `scripts/release_journey.py`, `scripts/validate-specs.sh`,
  `scripts/metrics.py`, `scripts/maint/check_spec_index.py`,
  `scripts/maint/pytest-without-sandbox.sh`.
- `.github/workflows/ci.yml`, `.github/workflows/release.yml`; `pyproject.toml`: `testpaths` and the
  registered `slow` marker.
