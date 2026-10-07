# Wave 91–95 worker packets — Phase 39, one CLI surface (D-57)

Coordinator: the session that planned Phase 39 on 2026-10-07. **Base commit for Wave 91: the
commit that opened the phase on `develop`** (`git log -1 --format=%h -- .agents/handoffs/wave-91-worker-packets.md`).
Every later wave bases on the previous wave's rollup commit, which the coordinator names when it
spawns the wave. One card, one worker, one isolated worktree each. The decision, the eleven
commands, the removal table, the voice, the setup flow and the test discipline:
[docs/adr/0022-one-cli-surface.md](../../docs/adr/0022-one-cli-surface.md).
The card (`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P39-<N>`) is the
contract; this file is the map. **Read §0 and your own packet only.** Symbols below were located
at `2a245cac` and drift; re-locate every one with `rg -n` before editing.

| Wave | Cards (parallel inside the wave) | Merge order | Model |
| --- | --- | --- | --- |
| 91 | P39-1, P39-2, P39-3, P39-4, P39-5, P39-6 | 4, 6, 3, 5, 1, 2 | Sonnet x6 |
| 92 | P39-7 | — | Sonnet; the integrator reviews the script before it runs |
| 93a | P39-12, P39-13, P39-14, P39-15, P39-16 | 12, 13, 14, 15, 16 | Sonnet x5 |
| 93b | P39-8, P39-9, P39-10, P39-11 | 8, 9, 10, 11 | Sonnet x4, based on the 93a rollup |
| 94 | P39-17 (integrator) and P39-18 (Sonnet) first; then P39-19 (Sonnet), P39-20, P39-21, P39-22 (Haiku); then P39-23 (integrator) | 17, 18, 19, 20, 21, 22, 23 | — |
| 95 | P39-24 | — | Integrator, live endpoint |

The tree every card builds toward (ADR 0022 decision 1):

```text
init · status · inbox · task · run · pod · log · setup · start · stop · exec
task  add list show approve deny answer retry cancel diff trace prune
pod   show add remove reset set unset apply export validate plan check recipes roles policies delete
setup (bare = the guided first run) provider model notify export sandbox mcp shell
log   [N] | verify          start [--http --telegram --dispatch --mcp] · stop          exec (was harness run)
```

## 0. Rules for every worker

- **Isolation.** One branch `p39-<N>-<slug>` in your own worktree, based on the commit the
  coordinator names (verify with `git merge-base HEAD develop`; if it is older than that commit,
  stop and report: worktrees here have been created at stale bases before). Never touch
  `~/.docket`: every CLI run sets `export W=$(mktemp -d); export DOCKET_HOME=$W/.docket` (two
  statements; **never override `HOME`**, it breaks uv's cache). pytest isolates `DOCKET_HOME`
  through the autouse fixture in `tests/conftest.py`. **Never call a real model endpoint and never
  probe a real vendor host**; `tests/fakes.py::FakeDriver` and the loopback fakes in
  `tests/integration/test_llm_port.py` are the pattern.
- **Never `git stash`.** Set work aside with a WIP commit on your branch.
- Run everything with `env -u VIRTUAL_ENV uv run ...`; run `env -u VIRTUAL_ENV uv sync --all-extras`
  once in your worktree first (`scripts/gen_cli_docs.py` imports `click`).
- **Order of work.** 1. Read the owning spec *section* and the neighbouring tests. 2. Amend the
  spec requirement text and add the pre-assigned version + changelog line. 3. Write the RED test
  and see it fail on the base for the stated reason. 4. Smallest implementation. 5. Gates.
- **Nothing is kept for the past (ADR 0022 §4).** When your card removes a name, delete it from
  code, tests, the spec, `docs/`, `src/docket/templates/`, `scripts/` and the completion script
  in the same commit. No alias, no notice, no "did you mean the old name", no hidden command, no
  `was`/`formerly` sentence anywhere. If a removed name is referenced from a file another card
  owns, return the locator; do not edit that file.
- **Real sub-apps.** A group is `typer.Typer(name=..., help=..., no_args_is_help=True)` registered
  once in `cli/__init__.py` with `app.add_typer`; verbs are `@group.command("verb")` with
  Typer-declared arguments and options only. No `ctx.args`, no `allow_extra_args`, no hand-parsed
  action word in any module you own. Every leaf's help docstring ends with one line
  `Example: docket ...`.
- **Shared helpers.** Pod targeting is `cli/_target.py::resolve_pod` and `pod_option()` (P39-1).
  Confirmations, JSON emission, the non-TTY rule and the `→ Next:` line are `cli/_contract.py`;
  symbols, colour roles, headers, sections, tables and errors are `ui.py` (both P39-2). **No Rich
  markup literal (`[green]`, `[bold]`, …) in a module you rewrite**: the voice guard's baseline
  only falls. A Wave 93 card that needs something these lack returns the gap; it does not extend
  the helper.
- **The copy rule (ADR 0022 decision 9).** A command that changes state ends with exactly one
  `→ Next: docket ...` line on stderr through `_contract.next_step`; a read command ends with
  none; an error is one line, `ui.error(what, do)`, exit 1 (2 for usage). Section names are the
  shared four: `Needs you`, `Running`, `Done`, `Failed`.
- **Tests.** One unit file per module (`tests/unit/cli/test_<module>.py` with
  `SUBJECT = "docket.cli.<module>"`), `typer.testing.CliRunner`, in-process. One RED behavioural
  test per card plus one for the card's fail-closed negative case; exact user-visible text belongs
  to the golden suite, not to assertions. No agent-lane tests, no guards unless your card names
  one. Docstrings at most three lines; no card ids, phases or dates in any `.py` file
  (`scripts/maint/comment_lint.py --check` refuses them).
- **Layer rules.** `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py`, never
  prints, never opens a socket. Docket-owned JSON only through `edges/store.py`. Every tool call
  through `core/tools.py::dispatch_tool`. Every shell-out through `edges/adapters/system.py`.
- **Frozen.** The `exec` contract (events, result line, exit codes, `--contract 1.0|1.1`,
  `docs/contracts/harness-v1/`, `tests/fixtures/harness-contract/v1/`), `serve.py`'s routes,
  the MCP tool names, `core/telegram.py`'s five verbs, `core/tools.py`, `core/agent_loop.py`,
  `core/policy.py`, `core/security.py`. A card that finds it needs one of these stops and reports.
- **Forbidden files:** `TODO.md`, `ROADMAP.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `AGENTS.md`, `specs/README.md`, `.agents/`, `internal-docs/`, `docs/adr/`, `docs/` except what
  your packet names and the regenerated `docs/commands.md`. Return the CHANGELOG line you would
  add. Never edit `scripts/metrics.py` or `scripts/validate-specs.sh`.
- **Goldens.** `bash tests/golden/run.sh verify-all` stays byte-identical unless your packet names
  a case; then regenerate only that case and list every changed line with its reason. The golden
  runner's `cases_dir()` read-only list is rewritten by P39-17, not by you: a new read-only case
  you add goes under `cases/writers/` for now and you say so.
- **Worker gates** before returning:

  ```bash
  env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src
  env -u VIRTUAL_ENV uv run pytest -q
  env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all
  bash scripts/validate-specs.sh
  env -u VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check   # regenerate docs/commands.md when help text changed
  env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <every .py you touched>
  bash scripts/maint/pytest-without-sandbox.sh -q                     # only if you touched isolation/sandbox code
  ```

  `scripts/metrics.py --check` is expected to fail on a branch that adds tests or removes
  commands; say so.
- **Commit.** One commit per card. Subject `Type: description` (`Add:`/`Fix:`/`Remove:`/`Refactor:`),
  ASCII, body says what was false and what is now true. **No AI mention, no `Co-Authored-By`
  trailer of any kind.** Before committing: `git diff --cached | command grep -nE '/home/|/tmp/claude|@gmail|sk-'`
  prints nothing. Do not push, do not merge into `develop` or `main`.
- **Return** a delta of 1,500–3,000 characters, no logs: card / branch / commit; outcome;
  user-visible behaviour; changed paths and owned functions; spec sections + one changelog line
  per spec; CHANGELOG line for the integrator; RED evidence (test id, base failure reason);
  focused tests -> result; worker gates -> pass or first failing gate; goldens changed with
  reasons; missing/failed; pending in this card; later follow-ups (locators only); contention note.

## Wave 91 — the foundation (no rename; six parallel lanes)

### P39-1 — one pod resolver

Branch `p39-1-pod-resolver`. Spec: `specs/api/cli-interface.spec.md` -> 1.67.0 (new "Pod
targeting" subsection under "Global Command Structure": the three sources in order, the error
text verbatim, the deeper-match rule; `status` and `add` cite it).

- **Where.** New `src/docket/cli/_target.py`: `class TargetError(Exception)`,
  `resolve_pod(explicit, *, env, cwd) -> str`, `pod_option() -> typer.Option` (`"--pod", "-p"`,
  help `"Pod name; default: DOCKET_POD, then the pod whose codebase contains the current directory"`),
  and `_pod_for_directory` moved verbatim from `cli/_agents.py` (delete it there; `cli/_status.py`
  imports from `_target`). `cli/_agents.py::run_add` and `cli/_status.py::run_status` call
  `resolve_pod` and print `TargetError` through `ui.error`, exit 1.
- **Allowed:** `cli/_target.py`, `cli/_agents.py` (`_pod_for_directory`, `run_add` only),
  `cli/_status.py`, `tests/unit/cli/test__target.py` (new), `tests/unit/cli/test__status.py`
  (new if missing). **Forbidden:** every other `cli/` module; `core/`.
- **RED:** `tests/unit/cli/test__target.py` with the five cases of the card; `ModuleNotFoundError`
  on the base.
- **Goldens:** none expected.

### P39-2 — one interaction contract and one console voice

Branch `p39-2-contract-and-voice`. Specs: `cli-interface.spec.md` -> 1.68.0 ("Interactive
Features": confirmation and non-TTY rule verbatim from the card; "Output Formats" rewritten as
"The console voice": the five symbols, five roles, header/section/table/error shapes, the plain
mode, the copy rule, the tagline; "Return Code Convention": 2 usage, 1 failure);
`security-gates.spec.md` -> patch (bare `gates isolate` is a read); `operator-loop.spec.md` ->
patch (bare `notify` is usage, exit 2).

- **Where.** New `src/docket/cli/_contract.py` with exactly `confirm`, `emit_json`,
  `require_value`, `next_step` (signatures in the card); `_is_tty()` is the one probe.
  `src/docket/ui.py`: keep `info/success/warn/error/dim/header` as names, change them to render
  through the roles; add `section`, `table`, `TAGLINE`, `SYMBOLS`, the plain mode (`NO_COLOR` or
  `not sys.stdout.isatty()`: ASCII `ok`/`x`/`!`/`->`, no colour; `DOCKET_NO_COLOR` already exists,
  keep it as a second spelling of the same switch or remove it, your call, say which). `error`
  gains a second parameter `do: str = ""`. Existing callers keep working (the signatures grow,
  they do not change). `tests/guards/test_console_voice.py` with
  `tests/guards/console_voice_baseline.txt` (count of `\[(bold|dim|green|red|yellow|cyan|magenta|blue|white)[^\]]*\]`
  literals per module outside `ui.py`; the guard fails when any module's count rises). Seen red
  by planting one literal. `cli/_gates.py::run_gates`: `want: str | None = None`; `_isolate(None)`
  prints the status plus `Usage: docket gates isolate on|off`, returns 2.
  `cli/_notify.py::run_notify`: `action == ""` is unknown (usage, return 2). Update the two call
  sites in `cli/__init__.py` only where they pass the default.
- **Allowed:** `cli/_contract.py`, `ui.py`, `cli/_gates.py`, `cli/_notify.py`, the two call sites
  in `cli/__init__.py`, the guard and its baseline, `tests/unit/cli/test__contract.py`,
  `tests/unit/test_ui.py`, `test__gates.py`, `test__notify.py`.
- **RED:** `test__gates.py`: fresh home, `run_gates("isolate")`, `fleet.json` bytes unchanged and
  no `gates.isolate` audit line; fails on the base with `isolation.enabled` written.
- **Goldens:** `gates_status` unchanged; any golden whose symbols change because `ui.py` now
  renders them (`✓` was already in use; `→` may replace `->` in some lines): list every line.

### P39-3 — one task id everywhere (core)

Branch `p39-3-task-ref`. Spec: `specs/functional/pod-dispatch.spec.md` -> minor bump (new
requirement "Task references": full id, short id, unambiguous prefix, a run id, ambiguity error
listing candidates with pods, the `TaskRef` fields).

- **Where.** New `src/docket/core/task_ref.py`: `@dataclass(frozen=True) class TaskRef`
  (`task_id`, `project`, `session_key`, `run_ids: tuple[str, ...]`, `worktree: Path | None`),
  `class TaskRefError(Exception)`, `resolve_task(project, ref)`, `short_id(task_id)`. Read tasks
  through `core.dispatch.read_tasks` and the pod registry helper (`rg -n "def .*pod_ids|def
  list_pods" src/docket/core`); the session key through `core.dispatch.step_session_key` for the
  Lead's first step; the worktree through the task record's recorded path (`rg -n "worktree"
  src/docket/core/dispatch.py` for the key); run ids through `core.runs`. A ref that matches a run
  record id (`core.runs.get_run`) resolves to that run's task, or to a `TaskRef` with the run
  alone when the run has no pod task (a harness run). The short form is whatever
  `cli/_pod.py::_pod_queue` prints today (`rg -n "task-" src/docket/cli/_pod.py`).
- **Allowed:** `core/task_ref.py`, `tests/unit/core/test_task_ref.py`. **Forbidden:**
  `core/dispatch.py` (read only), every `cli/` module.
- **RED:** the ambiguity case; `ModuleNotFoundError` on the base.

### P39-4 — one role vocabulary

Branch `p39-4-role-vocabulary`. Specs: `specs/functional/model-profiles.spec.md` -> 3.0.0 (roles
are archetype names; the class table rewritten; `programmer`/`manager`/`repo` removed, not struck);
`specs/functional/role-archetypes.spec.md` -> minor bump (`policy_role`/`policyRole` removed; an
archetype's model row is its own name; unknown key refused); `specs/data/cli-json-shapes.spec.md`
-> patch (the `models` listing names).

- **Where.** `src/docket/core/models_policy.py`: `ALL_ROLES`, `ROLE_CLASS`, `resolve_role_model`
  (drop the `pod.policy_role_for` indirection; the `is_specialist` branch and the
  `ORG_SPECIALIST_ORDER` loop are deleted here, so P39-6 can delete the constants), `rank_anchors`
  untouched, the preset writer in this module (`rg -n "programmer" src/docket/core/models_policy.py
  src/docket/templates`; the provider YAMLs do not key by role). `src/docket/core/archetypes.py`:
  remove `policy_role`, `resolved_policy_role`, the `policyRole` key in `to_doc`/`from_doc` (an
  unknown key is refused by the existing strict loader; add `policyRole` to the refusal test).
  `src/docket/core/pod.py::policy_role_for` deleted if it has no other caller. The CLI `models`
  renderer (`cli/__init__.py::cmd_models`, still there until P39-7) prints `ALL_ROLES`; the hint
  after `provider add` (`cli/_provider.py`) names `docket models` (P39-12 renames it again).
- **No migration.** A `docket-models.json` with old keys is not rewritten; `doctor` reports an
  unknown role key as a config error (find the existing config-error check in `cli/_doctor.py`,
  one new function). The operator re-runs the preset on the live home; the integrator does that.
- **Allowed:** `core/models_policy.py`, `core/archetypes.py`, `core/pod.py` (`policy_role_for`
  only), `cli/_provider.py` (the hint line), `cli/__init__.py::cmd_models` (names only),
  `cli/_doctor.py` (one new check function), `tests/unit/core/test_models_policy.py`,
  `test_archetypes.py`, `tests/integration/test_archetypes.py` (the byte-identical-workspace test
  for the four built-ins must still pass).
- **RED:** `resolve_role_model("implementer")` reads the `implementer` row; fails on the base.
- **Goldens:** `models` (read-only case) and `help` if it lists roles: regenerate, list lines.

### P39-5 — the record decides

Branch `p39-5-record-truth`. Specs: `pod-dispatch.spec.md` -> minor bump (run terminal states
include `waiting_input`/`waiting_approval`; a `failed` task is retryable; stale-claim reclaim rule
with the two conditions); `cli-interface.spec.md` -> 1.69.0 (`runs show` exit 1 on failure;
`doctor` critical = ✗ lines; the fix hint).

- **Where.** `src/docket/core/runs.py`: the state a run records when its last hop parked (`rg -n
  "succeeded" src/docket/core/runs.py src/docket/core/dispatch.py`). `src/docket/core/dispatch.py`:
  `retry_task(project, task_id)` (new, small: `failed`|`blocked` -> `pending`, attempt kept,
  `audit_log("task.retry", ...)`) and the stale-claim test inside the existing `--resume` reclaim
  path (`rg -n "reclaim" src/docket/core/dispatch.py`): a claim is stale when its recorded pid is
  gone (`edges/adapters/system.py::process_alive(pid)`, add it if absent) or its age exceeds
  `turnTimeoutS + verifyTimeoutS` from `PodSettings`; reclaim writes `audit_log("task.reclaimed",
  ...)`. `cli/_runs.py::_show` returns 1 when the run or any task failed. `cli/_doctor.py`: the
  summary function counts ✗ only; the footer hint names a command that exists (`docket doctor
  --fix` until P39-12 renames it). `cli/_metrics.py`: counts from terminal task events in the
  trace (`rg -n "task_done|task_failed|verification_failed" src/docket/core/trace.py`); the `-w`
  help says sessions.
- **Allowed:** `core/runs.py`, `core/dispatch.py` (the two functions named),
  `edges/adapters/system.py` (`process_alive` only), `cli/_runs.py`, `cli/_doctor.py` (summary +
  footer functions only; P39-6 owns the specialist check), `cli/_metrics.py`, their unit files.
  **Forbidden:** `cli/_pod.py`.
- **RED:** `tests/unit/core/test_runs.py` parked -> `waiting_input`; fails on the base with
  `succeeded`.
- **Goldens:** `metrics` (writers case): regenerate if the counts line changes, list lines.

### P39-6 — remove the org specialists and the portfolio manager

Branch `p39-6-remove-specialists`. Specs: `agent-lifecycle.spec.md` -> minor bump (no shared
agents; `init` provisions the pod only); `workspace-structure.spec.md` -> minor (no specialist
workspaces); `specs/data/docket-meta.spec.md` -> minor (`scope` is always `project`; `org`
removed); `specs/data/serve-read-api.spec.md` -> minor (`/status.json` agents are pod members;
API version bumped); `cli-interface.spec.md` -> 1.70.0 (`init --portfolio` removed).

- **Where.** `src/docket/config.py` (the constants and functions in the card; `workspace_dir`
  loses its specialist branch); `src/docket/cli/_install.py` (`_specialist_*`,
  `_provision_portfolio_manager`, the loops at the two `ORG_SPECIALIST_ORDER` sites, `--portfolio`
  parsing wherever `rg -n portfolio src/docket/cli` finds it); `src/docket/serve.py`
  (`_SPECIALISTS`, the `kind="specialist"` records; bump `SERVE_API_VERSION`);
  `src/docket/cli/_doctor.py` (the specialist check function only); `src/docket/cli/__init__.py`
  (the `ORG_DISPLAY_ORDER` loop in `cmd_list` and the `ORG_SPECIALIST_ORDER` loop in
  `cmd_snapshot`: delete the loop bodies, nothing else); `src/docket/cli/_agents.py` (the
  `is_specialist` branch near `profile` resolution); `src/docket/core/telegram.py` (the "org
  specialist" sentence in the delegate docstring); `tests/integration/test_portfolio_manager.py`
  (delete); `tests/golden/fixtures/seed.sh` (the six specialist workspaces and their `fleet.json`
  entries); `docs/AGENT-TEAMS.md` ("Org specialists" section and the bullet near line 27);
  `docs/DOCKET.md` (the `scope: org` sentence). **Do not touch `core/models_policy.py`** (P39-4;
  merge order 4 then 6).
- **Allowed:** the files above and their unit files; `tests/unit/cli/test__install.py` (new).
- **RED:** after `run_init` in a fresh home, `workspaces/manager` does not exist; fails on the base.
- **Goldens:** `list`, `list --json`, `info_*`, `cost`, `help` and any case whose output lists
  specialists: regenerate, list every removed line as "specialist row gone".

## Wave 92 — the registry split (one card, alone)

### P39-7 — split `cli/__init__.py` mechanically

Branch `p39-7-split-registry`. Spec: `specs/test-framework.md` -> minor (the new layout rule:
no function in `cli/__init__.py` longer than ten lines).

- **Where.** `scripts/maint/split_cli_registry.py` (new; `--dry-run`, `--write`, `--check`). It
  parses `src/docket/cli/__init__.py` with `ast`, takes the table in the card (command -> target
  module) as a dict literal at the top of the script, and for each `cmd_*` function moves the
  decorator-stripped function plus every private helper only it references (call graph over
  module-level names) into the target module **as text, byte for byte**, appending at the end of
  the module. The registration stays in `__init__.py` as
  `app.command("name", context_settings=...)(_module.cmd_name)` with the original decorator
  arguments. Imports: hoist what the moved code needs (ruff `F401`/`F821` tell you). If the AST
  approach cannot move a function cleanly (a helper shared by two target modules), leave it in
  `__init__.py` and list it in the return; the integrator decides. Target modules are the ones in
  the card; new files start with a two-line module docstring naming what they will hold.
- **Allowed:** the script, `cli/__init__.py`, every `cli/_*.py` the table names (new ones:
  `_run.py`, `_task.py`, `_pod_config.py`, `_log.py`, `_setup.py`, `_setup_model.py`,
  `_setup_notify.py`, `_setup_export.py`, `_setup_sandbox.py`, `_setup_mcp.py`, `_service.py`,
  `_exec.py`, `_remove.py`), `tests/guards/test_layout.py` (the ten-line rule), empty-but-valid
  `tests/unit/cli/test_<module>.py` files where the layout guard now requires one.
- **No-change oracle:** goldens byte-identical, `gen_cli_docs.py --check` green without
  regeneration, full suite green. If any of the three changes, the move was not mechanical: fix
  the script, not the output.

## Wave 93a — the groups, batch one (disjoint modules)

Base: the Wave 92 rollup. Spec versions below are pre-assigned; the RED test and acceptance are in
the card. A card that deletes a module also deletes its unit file and moves any still-valid test
into the new module's file.

### P39-12 — `setup`: the first-run flow; `provider`, `model`, `sandbox`, `shell`

Branch `p39-12-setup-flow`. Specs: `cli-interface.spec.md` -> 1.71.0 (the `setup` group with the
flow's two modes verbatim; `doctor`, `models`, `models provider`, `keys`, `gates`, `completions`
removed); `model-profiles.spec.md` -> minor (`setup model`; `provider add` applies the preset
unless `--no-preset`); `api-keys.spec.md` -> minor (credentials under `setup provider`; `remove`
confirmation); `security-gates.spec.md` -> minor (`setup sandbox`; bare is a read);
`agent-lifecycle.spec.md` -> minor (first run: `init` points at `setup` when no endpoint resolves).

- **Where.** `cli/_setup.py` (P39-7 moved `doctor` and `completions` here): `setup_app` with
  `invoke_without_command=True`; the callback runs the flow when no verb is given;
  `readiness() -> Readiness` (a small frozen dataclass: endpoint ok/missing with the reason,
  notify, sandbox, shell, service; pure, importable by `init` and `run`); `_report(r)` renders
  it through `ui.table`; `_ask_missing(r)` runs only on a TTY, required first, and calls the
  same functions the verbs call, printing `ran: docket setup ...` before each; `--fix` calls what
  `doctor --fix` called; `--json` emits the report through `_contract.emit_json`. `setup shell
  bash|zsh`. `cli/_setup_model.py` (P39-7 moved `models`, `keys` and `_provider.py`'s bodies
  here): `setup provider add` composes credential store + `verify_endpoint` probe + preset in one
  function the wizard reuses; `setup model` verbs. `cli/_setup_sandbox.py` (from `_gates.py`).
  `cli/_agents.py::run_init`: no silent home bootstrap beyond creating the directories
  `config.py` already ensures; with `readiness().endpoint` missing it finishes the team and prints
  `⚠ No model endpoint yet` plus `next_step("docket setup")`. Delete `cli/_doctor.py`,
  `cli/_keys.py`, `cli/_gates.py`, `cli/_completions.py` after the move; `cli/_install.py`'s
  `_step_model_readiness`/`_step_security`/`_step_policies` become the flow's steps (move them,
  do not duplicate).
- **Allowed:** the five modules above, `cli/_agents.py::run_init` (the ending only),
  `cli/_install.py`, their unit files. **Forbidden:** `cli/_setup_notify.py` (P39-13; the wizard's
  Telegram step calls `setup_notify.enable_telegram`, which P39-13 provides; until it is merged,
  the wizard's Telegram step prints the command instead and you say so), `cli/_run.py`,
  `cli/_status.py` (P39-15 reads `readiness()`).
- **RED:** `tests/unit/cli/test__setup.py`: piped `setup` on a fresh home exits 1 naming the
  provider command and writes nothing; fails on the base (no command).
- **Goldens:** `doctor`, `models`, `gates_status`, `completions_*`, `help`: cases renamed to the
  new invocations (`setup`, `setup_model_list`, `setup_sandbox_status`, `setup_shell_bash`, …);
  list every line.

### P39-13 — `setup notify` (Telegram in one step), `setup export`, `setup mcp`

Branch `p39-13-setup-notify`. Specs: `telegram-integration.spec.md` -> minor (connecting Telegram
is one operation writing the secret, the actors and every Lead's binding; nothing is sent unless
`--test`; the inbound-only pins untouched); `operator-loop.spec.md` -> minor (`setup notify
flush`); `observability-export.spec.md` -> patch; `mcp-client.spec.md` -> patch;
`cli-interface.spec.md` -> 1.72.0 (`channels`, `wire`, `unwire`, `notify`, `conversations`,
`exporters`, `mcp servers` removed).

- **Where.** `cli/_setup_notify.py` (P39-7 moved `channels`, `wire`, `unwire`, `notify`,
  `conversations` here): the sub-app; `enable_telegram(chat_ids, token, *, test) -> Written`
  (one function: secret store, actors through the channel catalog writer, one binding per pod
  Lead through `core.fleet` the way `wire` did; returns what it wrote for the printout; the wizard
  calls it); `bind`/`unbind`; `flush`; `show telegram` reads `core/conversations.py`.
  `cli/_setup_export.py` (from `_exporters.py` + `_exporters_preview.py`). `cli/_setup_mcp.py`
  (the servers half of `_mcp.py`; the serve half is P39-14's). Delete the five old modules after
  the move.
- **Allowed:** the three modules, the deleted ones, their unit files. **Forbidden:**
  `cli/_setup.py` (P39-12), `core/telegram.py`, `core/notify.py`, `core/channel.py` beyond reading.
- **RED:** `tests/unit/cli/test__setup_notify.py`: `enable telegram --chat 42 --token t` writes
  the three stores and the sink stays empty; fails on the base (no command).
- **Goldens:** `conversations` (delete), `exporters_list` -> `setup_export_list`, `help`,
  `completions_*`.

### P39-14 — `log`, `start`, `stop`, `exec`

Branch `p39-14-log-service-exec`. Specs: `audit.spec.md` -> minor (`log`, `log verify`; unknown
verb exit 2); `serve-read-api.spec.md` -> minor (`start|stop`; routes unchanged);
`specs/api/harness-mode.spec.md` -> minor (the command is `exec`; contract unchanged; `harness
status` replaced by `task show <run-id>`); `specs/api/mcp-server.spec.md` -> patch (`start
--mcp`); `cli-interface.spec.md` -> 1.73.0 (`audit`, `serve`, `harness`, `mcp serve` removed).

- **Where.** `cli/_log.py` (from `_audit.py`): `log [N] [--json]` as the group callback with
  `invoke_without_command=True` and `log verify` as its one verb. `cli/_service.py` (from
  `_serve.py`'s body, which P39-7 moved from `cmd_serve`, plus `mcp serve`): `start` with the
  flags in the card and `stop` (the two-stage stop: `rg -n "stop" src/docket/serve.py`); `status`
  reads the health file for "running" (P39-15 renders it; you expose `service.is_running()`).
  `cli/_exec.py`: `git mv cli/_harness.py cli/_exec.py`, the command `exec` with every option
  `harness run` had; delete `harness status` (its run lookup is `core/task_ref` since P39-3).
  `tests/unit/cli/test__harness.py` -> `test__exec.py` by `git mv`; the integration harness
  tests change the command name only.
- **Allowed:** the three modules, `cli/_harness_answers.py`/`_harness_recipe.py` (rename only
  if you must; keep names otherwise), the deleted `_audit.py`, `_mcp.py`'s serve half, their
  tests. **Forbidden:** `serve.py` beyond the stop function it already has, `core/harness.py`,
  the contract fixtures and schema.
- **RED:** `tests/unit/cli/test__exec.py`: invoke `exec --help`; fails on the base (no command).
  Return the one-line change Tack needs in `tack-runner/src/harness/docket/probe.rs`; do not
  edit Tack.
- **Goldens:** `audit` -> `log`, `audit_verify` -> `log_verify`, `help`, `completions_*`.

### P39-15 — `run`, `status`, `inbox`

Branch `p39-15-run-status-inbox`. Specs: `pod-dispatch.spec.md` -> minor (`run`; `--dry-run`
starts nothing; banner from the effective pipeline after roster filtering; `--resume` reclaims
stale claims and budget pauses; refuses with the setup line when no endpoint resolves);
`pipeline-format.spec.md` -> minor (`run --pipeline FILE`); `cost-tracking.spec.md` -> minor
(cost and counts in `status`, per pod); `cli-json-shapes.spec.md` -> minor (`status --all
--json`; `inbox` items carry `state` and `command`); `operator-loop.spec.md` -> minor (`inbox`
prints `docket task approve|deny|answer <id>` lines; "approved, ready"); `cli-interface.spec.md`
-> 1.74.0 (`dispatch`, `pod dispatch`, `pipeline run`, `cost`, `metrics`, `snapshot` removed).

- **Where.** `cli/_run.py` (P39-7 moved `cmd_pod`'s dispatch path? no: it moved the `pipeline
  run` body; the dispatch functions are still in `cli/_pod.py` and **you own them there**:
  `_pod_dispatch*`, `_parse_dispatch_args`, `_flush_notify_after_dispatch`; move them into
  `_run.py`, delete them from `_pod.py`): the `run` command with declared options; `--dry-run`
  renders through `core/orchestrator.py`'s plan; the banner from the same steps; the summary line
  and `next_step`; `setup.readiness()` gate. `cli/_status.py` (P39-7 moved `cost`, `metrics`,
  `snapshot` here): `status` with the fields in the card; the counting function from `_metrics.py`
  becomes one pure function (move it to `core/trace.py` if it only reads trace files).
  `cli/_inbox.py`: the sub-app; `command` and `state` on every item; wrap, never cut.
- **Allowed:** `cli/_run.py`, `cli/_status.py`, `cli/_inbox.py`, the named functions in
  `cli/_pod.py`, `cli/_pipeline.py::_run` (delete), `core/trace.py` (one new pure function), their
  unit files. **Forbidden:** everything else in `cli/_pod.py` (93b), `cli/_setup.py` beyond
  importing `readiness`.
- **RED:** `tests/unit/cli/test__run.py`: `--dry-run` leaves `docket-runs.json` unchanged; fails
  on the base (no command).
- **Goldens:** `cost` -> `status`, `metrics` (delete), `help`, `completions_*`; new writer case
  `run_--dry-run`.

### P39-16 — remove: `list`, `context`, `logs`, `edit`, `scope`, `persona`, `help`

Branch `p39-16-remove-seven`. Specs: `session-scoping.spec.md` -> 3.0.0 (operator-set scope
and `docket scope` removed; the derived key stands); `workspace-structure.spec.md` -> minor (no
persona block); `cli-json-shapes.spec.md` -> minor (`list`, `info` shapes removed; their fields
live under `status --all --json`, pinned by P39-15); `cli-interface.spec.md` -> 1.75.0 (the
seven removed).

- **Where.** Delete `cli/_remove.py`, `cli/_help.py`, `cli/_context.py` and their
  registrations; `core/identity.py`: the persona rendering and parsing (keep the role identity
  rendering); `core/models.py::AgentMeta.persona` and its `display_name()` branch; the persona
  block writer in provisioning if present (`rg -n persona src/docket`); `core/utils.py::
  aggregate_cost`/`last_activity` if their only callers were `list`/`snapshot` (`rg -n` decides;
  P39-15 may have kept one); the `scope set|reset` writers (`rg -n "scope.set|scope.reset"
  src/docket`). `tests/integration/test_completions_eval_metrics_help.py`: the `help` cases go;
  `tests/integration/test_console_script_entry_point.py`: the retired-name test parametrized over
  the seven. The bare `docket` greeting: remove only the `docket help` line (P39-17 rewrites it).
- **Allowed:** the files above, their unit files. **Forbidden:** `cli/_status.py`, `cli/_pod.py`.
- **RED:** `test_console_script_entry_point.py` parametrized over the seven; fails on the base.
- **Goldens:** `help`, `list`, `list_--json`, `info_*`, `scope_myshop`: delete the cases for
  removed commands; `config_--help` if it names `scope`.

## Wave 93b — the groups, batch two (`cli/_pod.py` and `task`)

Base: the 93a rollup. Ownership inside `cli/_pod.py` is per function; a card deletes only the
functions it owns and leaves the rest untouched. Merge order 8, 9, 10, 11.

### P39-8 — the `task` group: add, list, show, diff, trace, prune

Branch `p39-8-task-group`. Specs: `pod-dispatch.spec.md` -> minor (task views; `task add`; the
worktree printed; `task prune`); `trace-store.spec.md` -> minor (`task trace` by ref; `--tail`
ends at `session_end`; `--export`); `cli-json-shapes.spec.md` -> minor (`task list|show --json`
with `worktree`); `cli-interface.spec.md` -> 1.76.0 (`delegate`, `pod delegate|queue|evidence|
corrections|explain|worktrees`, `runs list|show|prune`, `trace` removed).

- **Where.** `cli/_task.py` (P39-7 moved `approve`, `deny`, `chat` here; leave them for P39-9):
  `task_app`; `task add` (body of `cli/_pod.py::_pod_delegate`, yours), `task list`
  (`_pod_queue`, yours), `task show` (`_pod_explain*`, `_pod_evidence`, `_pod_corrections`, yours,
  plus `cli/_runs.py::_show`'s rendering and the worktree block: path, branch, base from the task
  record, `rg -n "worktree|baseCommit" src/docket/core/dispatch.py`), `task diff`
  (`edges/adapters/system.py::git_diff(path, base)`, add if absent, one function), `task trace`
  (`cli/_trace.py`'s bodies), `task prune` (`_pod_worktrees*`, yours, plus `trace expire` and
  `runs prune`). Delete `cli/_runs.py` and `cli/_trace.py` after the move (P39-9 takes `runs
  cancel` first: coordinate through the merge order, 8 then 9, by leaving `_runs.py::_cancel` in
  place and listing it).
- **Allowed:** `cli/_task.py`, the named functions in `cli/_pod.py`, `cli/_runs.py`,
  `cli/_trace.py`, `edges/adapters/system.py` (`git_diff` only), their unit files.
- **RED:** `tests/unit/cli/test__task.py`: `task show` prints the worktree path; fails on the base.
- **Goldens:** `trace` -> `task_trace_<ref>`, `help`, `completions_*`; new readonly `task_list`
  (seed a task in `tests/golden/fixtures/seed.sh` only if none exists; say what you added).

### P39-9 — `task approve|deny|answer|retry|cancel`

Branch `p39-9-task-answers`. Specs: `operator-loop.spec.md` -> minor (`task answer` absorbs
`chat`; the pre-grant is `task approve --for`; `approved_ready`; the run hint); `pod-dispatch.spec.md`
-> minor (`task retry` uses the core retry; `task cancel`); `cli-interface.spec.md` -> 1.77.0
(`approve`, `deny`, `chat`, `pod answer|pregrant`, `runs cancel` removed).

- **Where.** `cli/_task.py` (the bodies of `approve`, `deny`, `chat` P39-7 moved here, and
  `cli/_pod.py::_pod_answer`, `_pod_pregrant`, yours): the five verbs as functions `_task_approve`,
  `_task_deny`, `_task_answer`, `_task_retry`, `_task_cancel`; the token resolved from the task
  (`rg -n "apr-" src/docket/core/approval.py` for the pending lookup by task); the sweep lock
  (`rg -n "lock" src/docket/core/dispatch.py`) decides the hint. `task cancel` takes
  `cli/_runs.py::_cancel`'s body; then delete `_runs.py` if P39-8 left it.
- **Allowed:** `cli/_task.py` (your five functions), the named functions in `cli/_pod.py`,
  `cli/_runs.py` (delete), their unit files. **Forbidden:** `core/approval.py` beyond reading.
- **RED:** `test__task.py`: `task approve <id>` resolves the task's pending token; fails on the base.
- **Goldens:** `help`, `completions_*`; new writer `inbox_--json` if absent (P39-15 may have added
  it; check).

### P39-10 — the `pod` group, roster half

Branch `p39-10-pod-roster`. Specs: `agent-lifecycle.spec.md` -> 2.0.0 (member lifecycle; Lead
removal refused; `reset` distills first and fails closed; pod deletion by typed name, never a
picker); `model-profiles.spec.md` -> minor (the per-agent pin removed; three layers remain);
`specs/data/docket-meta.spec.md` -> minor (`modelSource` removed); `pod-blueprints.spec.md` ->
minor (`pod set|unset` over every `PodSettings` key, `--member` for `verify`);
`cli-interface.spec.md` -> 1.78.0 (`add`, `info`, `delete`, `maintain`, `profile`, `pod <p>
list|add|remove|set-verify|config`, `config explain` removed).

- **Where.** `cli/_pod.py` becomes `pod_app` (P39-7 moved `add`, `info`, `delete`, `maintain`,
  `profile` here): `pod show` (merge `_pod_list`, `config explain`'s report from `cli/_config.py::
  run_config_explain` which P39-7 moved to `_pod_config.py`, so import the report builder from
  there; and `pod config get`), `pod add` (`_pod_add`), `pod remove` (`_pod_remove` +
  `_contract.confirm`; Lead refused), `pod reset` (`cli/_agents.py::_maintain_clean` with
  `distill_first=True`, then rebuild; move it), `pod set|unset` (`_pod_config*`'s set/unset with
  `--member` for `verify`, which is `_pod_set_verify`'s validation), `pod delete` (`_delete_pod`,
  typed name through `_contract.confirm(..., typed=name)`). `core/models_policy.py`: delete the
  pin branch and `model_source`; `core/models.py::ModelSource`; `core/utils.py::model_source`;
  every `modelSource` writer (`rg -n modelSource src/docket`). `cli/_agents.py` keeps `run_init`.
- **Allowed:** `cli/_pod.py` (all roster functions), `cli/_agents.py`, `core/models_policy.py`
  (the pin only), `core/models.py`, `core/utils.py`, `core/pod_provisioning.py` (`modelSource`
  writers), their unit files. **Forbidden:** `cli/_pod_config.py` beyond importing the explain
  report builder (P39-11).
- **RED:** `test__pod.py`: Lead removal refused; piped deletion refused; both fail on the base.
- **Goldens:** `info_*` (gone with P39-16; confirm), `help`, `completions_*`; new readonly
  `pod_show`.

### P39-11 — the `pod` group, configuration half

Branch `p39-11-pod-config`. Specs: `config-format.spec.md` -> minor (one validator `pod
validate [PATH]`); `pod-blueprints.spec.md` -> minor (`pod apply|export`; `apply` with no
argument re-syncs; `apply <file>` installs one document); `pipeline-format.spec.md` -> minor
(`pod plan`); `security-gates.spec.md` -> minor (`pod check`); `role-archetypes.spec.md` ->
patch (`pod roles`); `cli-interface.spec.md` -> 1.79.0 (`validate`, `roles`, `policies`,
`recipes`, `plugins`, `pipeline validate|plan`, `pod <p> apply|export|sync` removed).

- **Where.** `cli/_pod_config.py` (P39-7 moved `config`, `validate`, `pipeline`, `roles`,
  `policies`, `plugins`, `recipes` here): register onto `pod_app` imported from `cli/_pod.py`;
  `pod apply` (`cli/_pod.py::_pod_apply*`, yours, plus `_pod_sync*` for the no-argument form,
  plus the `roles add`/`policies add` installers for a single file), `pod export`
  (`_pod_export_cmd`, yours), `pod validate` (the `validate` body plus the three per-kind
  validators folded into `core.config_docs.validate_path`, one function), `pod plan`
  (`_pipeline.py::_plan`), `pod check` (`policies test`), `pod recipes|roles|policies [NAME]`
  (list/show bodies; plugins as a section of `pod policies`). Delete `cli/_config.py`,
  `cli/_validate.py`, `cli/_pipeline.py`, `cli/_roles.py`, `cli/_policies.py`,
  `cli/_recipes.py`, `cli/_plugins.py` if P39-7 left shells.
- **Allowed:** `cli/_pod_config.py`, the named functions in `cli/_pod.py`, the deleted modules,
  `core/config_docs.py` (one function), their unit files.
- **RED:** `tests/unit/cli/test__pod_config.py`: `pod check` verdict; fails on the base.
- **Goldens:** `config_--help` -> `pod_show_--help`? no: delete it; `policies_list` ->
  `pod_policies`; `help`, `completions_*`.

## Wave 94 — help, guards, rename script, docs, assets

### P39-17 — integrator (panels, tagline, greeting, completions, guards, goldens)

Not a worker packet. On `develop` after the 93b rollup, each guard seen red before it counts
(plant: remove one `Example:` line; break one `--json` with a Rich print; remove one `--yes`
check; add one `[green]` outside `ui.py`).

### P39-18 — the rename script

Branch `p39-18-rename-script`. No spec.

- **Where.** `scripts/maint/rewrite_cli_names.py`: `TABLE: list[tuple[re.Pattern, str]]` from
  ADR 0022 decision 5 (both forms, `docket pod <p> dispatch` and `docket pod myapp dispatch` ->
  `docket run`; `pod <p> delegate "x"` -> `task add "x"`; `pod <p> queue` -> `task list`; `pod <p>
  config set K V` -> `pod set K V`; `pod <p> config unset K` -> `pod unset K`; `pod <p> apply X` ->
  `pod apply X`; `pod <p> remove <id>` -> `pod remove <id>`; `pod <p> set-verify <id> "c"` -> `pod
  set verify "c" --member <id>`; `add <role>` -> `pod add <role>`; `delete <pod>` -> `pod delete`;
  `approve <tok>` -> `task approve <id>`; `deny` likewise; `chat <id>` -> `task answer <id>`;
  `gates X` -> `setup sandbox X`; `models provider X` -> `setup provider X`; `models X` -> `setup
  model X`; `keys add N` -> `setup provider add ... --credential`; `channels X` -> `setup notify
  X`; `wire <id>` -> `setup notify bind <id>`; `notify flush` -> `setup notify flush`; `exporters
  X` -> `setup export X`; `mcp servers X` -> `setup mcp X`; `mcp serve` -> `start --mcp`;
  `completions S` -> `setup shell S`; `doctor` -> `setup`; `doctor --fix` -> `setup --fix`;
  `serve` -> `start`; `harness run` -> `exec`; `audit` -> `log`; `audit verify` -> `log verify`;
  `runs show <id>` -> `task show <id>`; `trace tail <p>` -> `task trace --tail`; `cost` ->
  `status`; `metrics` -> `status`; `snapshot` -> `status --all --json`; `validate X` -> `pod
  validate X`; `pipeline plan` -> `pod plan`; `pipeline run` -> `run --pipeline`; `policies test
  ...` -> `pod check ...`; `roles|policies|recipes list|show` -> `pod roles|policies|recipes`;
  `plugins list` -> `pod policies --plugins`; `profile <id> --resume` -> `run --resume`; `profile
  <id> --budget N` -> `pod set budgetUsd N`; `maintain <id> check` -> `setup --fix`), `--write`,
  `--dry-run`, `--check` (every surviving `docket <removed-name>` invocation, exit 1), and an
  "unmappable" report for `info`, `context`, `logs`, `edit`, `scope`, `persona`, `conversations`,
  `help`, `profile <id> <model>`, `maintain <id> clean|reset|rebuild|sessions|distill`. Roots:
  `docs/` (not `docs/cycles-ended/`, not `docs/adr/`), `src/docket/templates/`, `scripts/`,
  `specs/`, `tests/agent/`, `README.md`, `CONTRIBUTING.md`. `tests/guards/test_no_removed_cli_names.py`
  calls `--check` over `src/`, `docs/`, `specs/`, `scripts/`, `tests/`, `README.md`.
- **Do not run `--write`** in this card beyond `--dry-run`: P39-19..22 run it per file set.

### P39-19 — README and quick start (Sonnet)

Branch `p39-19-readme`. Run `scripts/maint/rewrite_cli_names.py --write README.md
docs/QUICK-START-DOCKET.md` first, then rewrite by hand: the quick start is `docket setup`
(one block showing the report and the `local` answer), `docket init`, `docket task add`, `docket
run`, `docket status`, `docket inbox`, `docket task approve`; the sentence defining `pod` (ADR
0022 decision 3) where `docket pod` first appears; every transcript line typeable. The sentences
the prose tests pin are rebuilt from the new README in `tests/agent/truth/test_docs_positioning.py`
and `tests/agent/release/test_public_release_truth.py`: delete every assertion that quotes the old
README and write the new ones from the new text. The agent lane's line baseline may only fall.

### P39-20, P39-21, P39-22 — Haiku doc sweeps

Branches `p39-20-guides`, `p39-21-reference`, `p39-22-templates-specs`. Each worker: run
`scripts/maint/rewrite_cli_names.py --write <your files>`, read the script's unmappable report for
your files, rewrite exactly those lines and the sentences that depend on them, run `--check` on
your files, run `bash scripts/validate-specs.sh` (P39-22) or `uv run pytest tests/agent -q`
(P39-20/21 when a prose test reads your file). Edit only the lines the script lists plus the
sentences that reference a removed command, pin, persona or specialist. Return the list of
sentences you rewrote by hand. P39-22 also bumps each touched spec one patch level with the
changelog line "command names follow ADR 0022" and regenerates `docs/recipes.md` with
`scripts/gen_recipe_docs.py`; if a *requirement* (not prose) names a removed command, return the
locator instead of editing it.

### P39-23 — integrator (assets, CHANGELOG, spec 2.0.0, Tack's line, archive)

Not a worker packet. `scripts/maint/capture-doc-journey.sh` against the local endpoint (scene 0
is now `docket setup`), `scripts/render-doc-assets.py`, the CHANGELOG "Removed"/"Changed"
entries, `cli-interface.spec.md` cut to the eleven commands at 2.0.0, `specs/README.md`,
`scripts/metrics.py --check` (`commands=11`), the one-line change in Tack's
`harness/docket/probe.rs` applied in that repo with its tests run, the landing-page follow-up
recorded.

## Wave 95 — the measurement

### P39-24 — integrator (six journeys re-run, checklist re-scored)

Not a worker packet. The transcript goes to `internal-docs/cli-ux-audit-2026-10-07/live-run-after.md`
and the score to ADR 0022 "Live run"; the first journey is `docket setup` on a fresh machine,
`local` and a hosted provider against a fake. A new defect is a locator for triage, not a fix in
this card.

## Wave 91 returns (integrator, 2026-10-07)

Six cards merged into `develop` in the packet's order (`5cbcac79` P39-4, `798bd56c` P39-6,
`5cae754f` P39-3, `315dc23c` P39-5, `847c637c` P39-1, `54bb3977` P39-2) plus the integrator
rollup. Conflicts were confined to two spec files (`cli-interface.spec.md` header and changelog;
`pod-dispatch.spec.md`, where P39-3 and P39-5 both chose 6.32.0: P39-5's entry is now 6.33.0).
The integrator deleted `config.py`'s `ORG_ROLES`/`ORG_SPECIALIST_ORDER`/`is_specialist`/
`ROLE_WHY` (P39-6 had to leave them while P39-4's branch still read them) and pointed
`cli/_help.py`'s strong-role lookup at `implementer`.

**Decisions taken on worker questions.** P39-2's five writer goldens changed because the golden
runner pipes stdout and plain mode is the card's acceptance (ADR 0022 decision 9); accepted,
`gates_status` included. P39-1's one assertion edit in
`tests/integration/test_auth_context_maintain_keys_add.py` follows the card's required error
text; accepted. P39-6 reached into `core/models.py` (`AgentKind.specialist`, `AgentScope.org`
removed); accepted under ADR 0022 §4. P39-4 followed the card's `ROLE_CLASS` rows where they
differ from the archetype `modelClass` (`analyst` cheap, `critic` strong).

**Follow-ups returned by workers, routed to the card that owns the file.**
- P39-14 (`exec`/`log`/`start`/`stop`): `cli/_harness.py::_status` and `_terminal_result_from_run`
  treat only `succeeded|failed|cancelled` as terminal; `waiting_input`/`waiting_approval` now
  exist (P39-5). `task show <run-id>` replaces `harness status`, so settle it there.
- P39-15 (`run`/`status`/`inbox`): `cli/__init__.py` `-w/--window` help says days, means
  sessions; `cli/_metrics.py:32` hint still says `--role programmer`; `_doctor_json`/`healthy`
  still counts warnings as issues (JSON path); `run_doctor`'s `--fix` ledger subtraction is
  string-coupled.
- P39-9 (`task` verbs): wire `core/dispatch.py::retry_task` to `task retry`; `task answer`
  moves the raw `sys.stdin.isatty()` calls in `_chat.py` onto `_contract`.
- P39-10 / P39-11 / P39-12 / P39-13: raw `sys.stdin.isatty()` in `_agents.py`, `_exporters.py`,
  `_keys.py`, `_channels.py`, `_pod.py` move onto `cli/_contract.py`; `TAGLINE` is not yet read
  by the bare greeting, `app help=` (`cli/__init__.py` near lines 37 and 85) or `pyproject.toml`;
  `_gates.py` still carries markup literals (ratchet target in `console_voice_baseline.txt`);
  `cli/_agents.py::run_init`'s hand-rolled unknown-option check (P39-6) goes when `init` becomes
  a Typer command; `_parse_existing_pod_add_args` still parses `--project` by hand.
- P39-20..22 (doc sweeps): old role names / specialists / `--portfolio` still in
  `docs/WORKFLOW-GUIDE.md` (35-64, 597, 725, 832), `docs/CONFIGURATION.md` (73, 1148),
  `docs/README.md` (36, 92, 136, 146), `docs/troubleshooting.md` (50, 453),
  `docs/AGENT-TEAMS.md` (206, 372), `docs/DOCKET.md` (703), `docs/MODEL-GATEWAYS.md` (51, 54,
  76); spec prose in `telegram-integration.spec.md:131`, `role-archetypes.spec.md:246/816`,
  `security-gates.spec.md:627`, `audit.spec.md:70/325`; comments in
  `edges/adapters/docket_runtime.py:460`, `tests/integration/test_telegram_channel.py:335/453`,
  `tests/unit/core/test_pod.py:63`. `TODO.md:372` and `docs/adr/0022-one-cli-surface.md:31`
  still cite `cli/_agents.py::_pod_for_directory` (now `cli/_target.py`).
- Integrator (done in the rollup): `serve-read-api.spec.md` and `cli-json-shapes.spec.md` run
  `state` enum gains the two parked states.
- Integrator (done in the rollup): `core/models_policy.py::reapply_role_policy` resolved a
  pod-scoped archetype to `cfg.DEFAULT_MODEL` (found by running `models preset local` on the
  live home after P39-4: the `security-vetter` member flipped to Anthropic). Now goes through
  `resolve_role_model(..., project=)`; `tests/unit/core/test_models_policy.py::TestReapplyRolePolicy`.
  The agent-lane starter (`examples/starter/starter.py`) and `scripts/` role lists were also
  moved to archetype names.
- Operator (live home, done): `docket models reset` (it still uses a raw `input()`; pipe `y`)
  then `docket models preset local`; `docket profile <vetter> default` repaired the member.
  Three specialist workspaces and their `fleet.json` entries remain in `~/.docket` from before
  P39-6 (`list` counts 6 agents, shows 3); doctor is silent about them by design. Remove by hand
  or re-init when convenient. Was: re-run `docket models preset` so `docket-models.json` carries archetype
  keys; `doctor` reports the old ones until then.
