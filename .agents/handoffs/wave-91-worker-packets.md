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

### P39-25 — the invocation guard (Sonnet)

Branch `p39-25-invocation-guard`. No spec.

- **Where.** `scripts/maint/lint_cli_invocations.py` (a starting copy is in the worktree,
  untracked: the integrator's scratch linter from the Wave 94 merges; keep its shape, finish it)
  and `tests/guards/test_cli_invocations_true.py`, a sibling of
  `tests/guards/test_no_removed_cli_names.py` (load the script with `importlib`, reuse
  `rewrite_cli_names.py::split_record` for specs and its `EXCLUDED` idea for the roots).
- **The tree.** `typer.main.get_command(app)` from `docket.cli`; a group has `.commands`, a leaf
  has `.params` (`param_type_name == "argument"`, `opts`, `is_flag`, `nargs`). `log` is a group
  invoked without a verb and takes a count (`docket log 50`); `setup` and `status` likewise take
  no verb. `init` is hand-parsed and exempt.
- **False positives seen in Wave 94, all to handle:** markdown tables escape the pipe (`\|`);
  syntax lines in specs (`docket pod set KEY VALUE [--member ID]`); a code span holding just
  `docket`; `docket --version`; the `-h` option; a quoted task text with spaces; a shell line
  that continues with `|`, `&&`, `#` or `\`.
- **What it finds today** is the card's RED list: run it over the roots first, record every line,
  fix the false ones (one line each, in the doc that holds it), keep the true ones as evidence of
  a linter gap and fix the linter, never the doc, for those.
- **Help examples.** Walk every leaf; its help holds one `Example:` line; lint it. A failing
  example is a one-line fix in the leaf's help string.
- Return: the RED list with each line's disposition (doc fixed | linter fixed), the guard's run
  time, and the CHANGELOG line.

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

## Wave 92 returns (integrator, 2026-10-07)

- P39-7 merged as `a99e0344` (worker commit `5e08396c`, branch `p39-7-split-registry`, based on
  `69549e01`). `cli/__init__.py` is 177 lines: the app, `_default`, sixteen module imports and
  46 `app.command(...)(_module.cmd_x)` registrations. `scripts/maint/split_cli_registry.py`
  (`--dry-run`, `--write`, `--check`) did the move; a second `--write` is a no-op; `--write`
  refuses on an import conflict, a name clash, a stray line between definitions or a `cmd_*`
  calling another `cmd_*`. `_run.py` was not created (nothing lands there until P39-15).
- Integrator decisions: shared helpers moved by a `SHARED` table in the script, not by hand:
  `_pick_agent` and `_test_cmd_for_stack` -> `cli/_agents.py` (its three lazy imports of them
  deleted); `_delete_pod` -> `cli/_pod.py` (reached as `_pod._delete_pod`);
  `_resolve_version` and `_version_callback` -> `cli/_setup.py`. `_default` is exempt from the
  ten-line rule by name (`test-framework.md` rule 9, 2.19.0; `tests/guards/test_layout.py::
  test_cli_registry_functions_are_short`, RED on the base with 57 functions listed). Every
  target module imports at module level now; `docket --version` median 0.23 s -> 0.25 s.
- Accepted deviations: `scripts/maint/comment_lint.py::_renders_user_help` treats a `cmd_*`
  function as a Typer command (the decorator was its only proxy and the move detaches it;
  `comment-baseline.json` untouched). `tests/guards/console_voice_baseline.txt` counts
  relocated with the lines: the tree totals 209 literals before and after (the old
  `cli/__init__.py 51` entry was stale-high; the real base count was 40).
- Retargets outside the script: `tests/integration/test_audit_log.py` (`_remove.cmd_scope`/
  `cmd_persona`, `_pod.cmd_profile`), `tests/integration/test_pod_provisioning.py`
  (`_pod._delete_pod`).
- Empty `SUBJECT` unit files (allowed for this card only): `tests/unit/cli/test__pod_config.py`,
  `test__remove.py`, `test__setup_model.py`, `test__setup_notify.py`. The Wave 93 card that owns
  each module fills its file.
- Follow-ups by owner: P39-16 deletes `cli/_remove.py` whole and the `_default` greeting lines
  that name `list`/`help`; P39-17 rewrites `_default`. `scripts/validate-specs.sh` printed one
  warning on the branch (integrator checks it in the rollup gates).

## Wave 93a returns (integrator, 2026-10-07)

Base `dd483ba8` (the board claim on top of the seed `f768584c`, which added `cli/_setup.py::setup_app`
and `readiness()` so the three cards that meet there never carried a red suite). Merged in the
packet order with `--no-ff`: P39-12 `3633ed8d`, P39-13 `7c4acba1`, P39-14 `c81aac07`, P39-15
`77ca8ed6`, P39-16 `e29436be`; integrator wiring `f61f1bac`; then the rollup. Every conflict was in
a shared file the packets predicted (`cli/__init__.py` registration lines, `cli-interface.spec.md`
header and changelog, `scripts/gen_cli_docs.py::GROUPS`, the completions goldens and
`docs/commands.md`, both regenerated from the merged tree after each merge) plus five test files
three cards edited by class. Live-home check after the merge: `setup`, `status [--all]`,
`inbox --peek`, `log 3`, `setup notify list`, `setup model list`, `setup sandbox` and
`run --dry-run --pod rack-cli` all behave; `doctor` and `pod <p> dispatch` are unknown.

**Decisions taken at merge.**
- Two version collisions renumbered by keeping both bullets under one block instead of a second
  bump: `audit.spec.md` 2.12.0 (P39-14 and P39-16) and `agent-lifecycle.spec.md` 1.17.0 (P39-12
  and P39-16); `operator-loop.spec.md` 1.4.0 likewise (P39-13 and P39-15). Next time, pre-assign
  every number.
- `cli/_mcp.py` keeps the MCP server half as the module behind `start --mcp`; P39-13's deletion
  of the servers half had also dropped the `docket.config` import P39-14's `tool_cost` needs; the
  import is back. `tool_cost` reads `core.utils`/`edges.store` directly (no `_cost` module).
- `tests/integration/test_completions_eval_metrics_help.py` is deleted: each of its three classes
  belonged to a removed command and each card removed its own.
- Integrator wiring (`f61f1bac`): the wizard's Telegram step calls
  `cli/_setup_notify.py::enable_telegram` (seam test `test__setup.py::TestTelegramStep`);
  `status` asks `cli/_service.py::is_running()`; `docket run` is pinned to refuse through the real
  `readiness()` on a fresh home (`test__run.py::...test_refuses_through_the_real_readiness_report`).
- P39-14: no `--http/--no-http` on `start` (`run_serve` cannot run without HTTP and `serve.py` is
  frozen), no `--no-dispatch`; `--mcp` with `--dispatch`/`--telegram`/`--token-file` exits 2. The
  pinned stderr line is now `docket exec: run <token> ...` (Tack does not match it; see below).
- P39-15: no `run --dry-run` golden (the golden home cannot hold a pod); `writers/status_--all`
  added instead. `serve /inbox` items are unchanged; `state`/`command` are CLI-side.
- P39-16: `info_*` goldens kept (output unchanged); `core/utils.py::aggregate_cost`/`last_activity`
  stay (callers in `core/dispatch.py`, `serve.py`, `cli/_agents.py`).

**Tack (one-line changes, not applied here):** `crates/tack-runner/src/harness/docket/probe.rs`
(~l.106) `"harness", "run",` becomes `"exec",`; same in `harness/docket.rs` (~l.336) and
`docket/tests.rs` (three places). Tack's stderr match on `docket harness:` needs `docket exec:`.

**Follow-ups by owning card (locators only).**
- P39-8/P39-10 (93b, `cli/_pod.py`): `cmd_pod` help and `_pod_*` messages (~l.542) still say
  `dispatch`; `cli/_pod.py:1162,1165` name removed commands; `cli/_pod_config.py::cmd_pipeline`
  help mentions `run`; `docket info` is still a top-level command (P39-10 folds it into `pod show`).
- P39-9 (93b): `harness status`'s replacement is `task show <run-id>` through `core/task_ref`.
- P39-17: `tests/golden/run.sh` `cases_dir()` read-only list still names `list|scope|context|help`
  (every new read-only case sits under `cases/writers/`); the bare `docket` greeting; the
  hand-written completion word lists in `cli/_setup_shell.py` (no `setup` sub-word list beyond
  the first level); `serve.py`'s banner prints "docket serve" (frozen file, one string).
- P39-18/P39-19/P39-20..22: old names in `docs/*.md`, `README.md` (the quick-start route pinned by
  `tests/agent/release/test_public_release_truth.py:211` still says `docket pod myapp dispatch`),
  `scripts/render-doc-assets.py` transcripts (SVGs not re-rendered), `templates/channels/07-telegram.yaml`,
  `templates/exporters/03-langfuse.yaml`, `04-honeycomb.yaml`, `core/telegram.py:55`,
  `edges/adapters/channels/telegram.py:33`, `serve.py:746`, `core/agent_loop.py:136,141` (comments
  mention persona; frozen file), `scripts/maint/split_cli_registry.py` (spent; mentions `_remove`).
- Specs not in any 93a scope that still mention removed names: `security-gates`, `pod-dispatch`,
  `pod-blueprints`, `cli-json-shapes` (text), `cli-interface.spec.md` ~l.463 and ~l.685; audit.spec.md
  has no entry for the new `run.resume` action (P39-23's spec 2.0.0 pass).
- `setup mcp test` was not requested and does not exist; `bind` without `--chat` runs the guided
  discovery on a TTY only; `readiness().service` only checks for the systemd user unit file.

## Wave 93b returns (integrator, 2026-10-08)

Base `a7588463` (the board claim on top of the seed `f54020ee`, which defined `cli/_pod.py::pod_app`
unregistered, `cli/_task.py::task_app` registered, and `tests/unit/cli/test__task.py` with the pod
helpers both task cards use). Merged in the packet order with `--no-ff`: P39-8 `f2dcfb4b` (clean),
P39-9 `372c46d4`, P39-10 `9fba00fb`, P39-11 `2f1105e1`; integrator release-lane pass `515a606b` and `70b41380`; then
the rollup. Every conflict was in a file the packets predicted: `cli/_pod.py` (four cards deleting
neighbouring functions), `cli/_task.py` (two cards replacing neighbouring legacy commands),
`cli/__init__.py`, `scripts/gen_cli_docs.py::GROUPS`, the completions goldens and `docs/commands.md`
(regenerated after each merge), `cli-interface`, `pod-dispatch`, `pod-blueprints` and
`cli-json-shapes` (pre-assigned numbers, blocks kept in version order), `tests/unit/cli/test__pod.py`
and `test_runs_cli.py` (by class), `_setup_shell.py`'s hand-written word lists, the two guard
baselines. Live check on a throwaway home: `pod --help`, `pod policies|roles|recipes|validate|check`
answer outside a pod, `pod plan|apply|show`, `task list` refuse outside one naming `docket init`,
`task show x` names the ref, and every removed name exits 2.

**Decisions taken at merge.**
- The registration swap (`app.command("pod")(_pod.cmd_pod)` -> `app.add_typer(_pod.pod_app)`) and
  the deletion of `cmd_pod` happened at P39-10's merge; the emptied `dispatch()` switch was deleted
  at P39-11's merge, and `cli/_runs.py` at P39-9's, as the prompts said.
- A deletion conflict resolves to neither side: when both cards removed the neighbouring function,
  the hunk's two sides are what each card had *kept*, so "take both" would have resurrected every
  removed function. Three fragments survived the first pass (an argument loop in `_pod.py`, a
  method tail in `test__pod.py`, two dangling `app.command(` lines in the registry) and were caught
  by importing the package before each merge commit.
- `cli/_task.py` ended with two `_resolve`/`_task_record` helpers (one per card); one survives.
  `_implementer_member` (P39-10) was restored from the branch after a resolution dropped it.
- `tests/guards/test_completions_drift.py::TestSubcommandListsMatchTheImplementation` was deleted:
  it derived truth from `sub == "..."` literals and no module has one left.
- `cli-interface.spec.md` lost the emptied `#### docket runs` and the legacy pod-action section;
  `cli-json-shapes.spec.md`'s surface sentence names `task list|show|trace` and `pod show`.
- The release lane (integrator pass): `examples/starter/starter.py`, `scripts/release_journey.py`
  and `tests/agent/release/test_starter_journey.py` inspect through `task show <id> --pod --json`
  (its `runs` list replaces `runs list|show`) and `task trace <id> --export`; the benchmark's
  corrupt-primary scenario triggers the store recovery through `task show task-one`;
  `scripts/render-doc-assets.py` and `scripts/maint/capture-doc-journey.sh` speak the new verbs
  and the three assets were re-rendered; `scripts/smoke_workflow.py`'s memory scenario runs
  `pod reset --yes` where it ran `maintain distill` (reset distils, then clears and rebuilds: a
  live-only script, flagged here, not verified live).
  The first gate run on the pass found three more: the smoke test still asserted
  `runs cancel`, the benchmark's approve/deny action and the starter's approval listing
  (`docket approve` with no token) still used the top-level verbs; they are `task cancel`,
  `task approve|deny <token>` and `docket inbox` now. The evidence schema and the recipe
  docs were regenerated (a docstring the schema embeds named `docket trace`).
  Two facts the starter journey taught: a task parked for approval shows in `inbox` under its
  task id (the `apr-` token is printed only for an approval no task holds), so the starter
  denies and approves by task id; and `task trace <id> --export` is the task's own session,
  so the `approval_denied`/`approval_granted` events, written on the pod's approval session,
  are not in it: the journey test pins `approval_task_denied`/`approval_resumed` instead.
- P39-10 reported one accidental request to a vendor host during a manual `pod reset` in a
  throwaway home (no credential, HTTP 401). The rule stands; the tests use `FakeDriver`.

**Follow-ups by owning card (locators only).**
- P39-17: `cli/_setup_shell.py` `pod)` and `task)` word lists are hand-trimmed, the `$_ids` arm on
  `pod` is wrong now that there is no positional id; the greeting; `tests/golden/run.sh` read-only
  list.
- P39-18/19/20..22: `README.md` (quick start still says `docket pod myapp delegate|dispatch`,
  `runs list`, `trace`, `pod myapp export`, `docket add --from`; pinned by
  `tests/agent/release/test_public_release_truth.py:157,162,210-214`, which still passes because
  the README is unchanged), `docs/*.md` (P39-11 swept `pod apply|export|validate|plan|check|
  recipes|roles|policies`; `task`, `pod show|set|unset|reset|delete`, `maintain`, `profile`,
  `info`, `config explain` mentions remain), `examples/configs/*`, `examples/pipelines/
  code-review.yaml:8`, `src/docket/templates/recipes/*/README.md` (partly swept by P39-11).
- P39-23 (spec 2.0.0 pass): `audit.spec.md` has no entries for `pod.reset`, `pod.delete`
  (replaces `agent.delete`), `pod.unset-verify`, `run.resume`; stale names remain in
  `workspace-structure`, `cost-tracking`, `mcp-client`, `operator-loop`, `model-profiles`,
  `harness-mode`, `security-gates`, `acceptance/user-stories.md`. Comments in frozen files:
  `serve.py:151`, `core/agent_loop.py:119`.
- No replacement exists for `maintain check|sessions` (the context-footprint warning),
  `policies init` and the whole-registry `roles validate`; `cli/_setup_check.py::
  _check_template_version` keeps an unused `drift` counter.
- `tests/integration/test_doctor_ledger_drift.py:106` expects `Fix with: docket setup --fix`.

## Wave 94 returns (integrator, 2026-10-08)

Base `d6c7f493` (the board claim on the Wave 93b rollup `4ce57b6c`). Stage one ran P39-17 and
P39-18 as two Sonnet workers in parallel (the board listed P39-17 as integrator-owned; it was
delegated whole and reviewed at merge). Merged `--no-ff`: P39-17 `cc81c003` (clean), followed by
the integrator fix `55b77647`; P39-18 `254fba94` (clean), followed by the integrator fix `a5f04351`. Stage two (P39-19 Sonnet, P39-20 and P39-21
Haiku, P39-22 Sonnet, upgraded because telling a requirement from prose in 26 specs is a
judgement) based on the claim `6ac5e765`; merged in return order rather than card order, since the four file sets are disjoint: P39-21 `22861f7b`, P39-20 `305e05ed`, P39-22 `7a1a85ce`, P39-19 `d362eb5f`, with the integrator fixes `c6b4cc53` (two rename-table entries) and `dbc3b49d` (the assets table and the CONTRIBUTING example).

**Decisions taken at merge.**
- **Did-you-mean comes from the live tree only.** The card's acceptance example (`docket dispatch`
  -> "did you mean `run`") needed a table of removed names, which ADR 0022 decision 4 forbids;
  it was dropped. `cli/_help.py::DocketGroup` offers Click's similarity matches over the live
  top-level names plus every group that has a verb of that name (`docket add x` names `docket
  task add` and `docket pod add`); `docket dispatch` and `docket delegate x` exit 2 with a bare
  `No such command`. P39-24 scores the live run against this, not the card's example.
- `cli/_help.py` takes click from the module `TyperGroup`'s base class lives in: Typer 0.26
  vendors click as `typer._click`, the floor `typer==0.16` does not. Verified by importing the
  module and running the help tests in a `--resolution lowest-direct` environment.
- `setup mcp list` gained `--json` (the JSON-surface guard had carried it as a strict xfail;
  ADR 0022 decision 6 says every list has it) and `log --json` on a home with no log prints the
  empty JSONL rather than the human text. Both in `55b77647`.
- The golden runner keys the read-only directory on the verb words (`cases_dir "$@"`); the nine
  existing cases moved to `cases/readonly/` byte-identical. A bare `docket` invocation cannot be
  a golden case (the case id is the argv), so the three-part guide is pinned in
  `tests/unit/cli/test__help.py`.
- `pyproject.toml`'s description is the tagline. `docket init --help` gained its `Example:` line
  (the help-examples guard was red on the base for it).

**Follow-ups by owning card (locators only).**
- P39-23: `cli/_agents.py::cmd_init` still hand-parses its flags through `allow_extra_args`
  (the one leaf left that violates the real-sub-app rule; its `--help` lists the flags in prose);
  the bare `setup` report exits 1 while the endpoint is unconfigured, so the JSON-surface guard
  allows 0 or 1 for it alone; no golden covers the root `--help` (it would land under `writers/`).
- `scripts/maint/comment_lint.py --check` lists five pre-existing `long-def-doc` findings in
  `cli/_agents.py` and `cli/_setup_check.py`.

**P39-18 at merge.**
- The script never touches `CHANGELOG.md` (the record) and never checks it; the card's
  "`[Unreleased]` only" clause was dropped. `docs/cycles-ended/`, `docs/adr/`, the golden
  cases, the frozen harness contract and its fixtures are excluded; an `ALLOW` tuple holds the
  two substrings that look like invocations and are not (the contract's schema title, one test
  asserting a removed word is absent).
- `runs` counts as an invocation only before `show|list|cancel` or at a line or backtick end,
  because "docket runs teams of coding agents" (the tagline) is prose.
- The worker's `--write` pass covered `src/docket/` (minus templates), `scripts/`, the three
  default test lanes, `examples/` and `benchmarks/`: 62 files of comments, docstrings and
  example headers. The guard's `PENDING` tuple (files inside the roots not yet swept) was
  closed at merge down to `src/docket/templates` (P39-22): `cli/_setup_check.py` and its test
  were P39-17's, and the comments and the service banner in `serve.py` and
  `core/agent_loop.py` were rewritten by the script (no route, event or behaviour changed).
- The table turned `docket add --from` into `docket pod add --from`, a flag that verb does not
  have; the entry now maps to `docket init --from`.
- On the base the check listed 1,457 lines over the default roots; after stage one, 0 over the
  swept roots and these for the doc cards: `docs/` 612 (51 unmappable), `specs/` 661 (80),
  `README.md` 30 (1), `CONTRIBUTING.md` 1 (1), `tests/agent/` 9, `src/docket/templates/` 31.


**Integrator pass between the stages (on `develop`, no worker file touched).**
- `CHANGELOG.md` `[Unreleased]`: the "Removed" section is one line per old name with its
  replacement (ADR 0022 decision 5, every row) and "Added" carries the grouped help and the
  rename script (`70fbec81`).
- `specs/api/cli-interface.spec.md` 2.0.0 (`4aeedf8c`): one `#### docket <cmd>` section per
  top-level command in `--help` order, each with its verbs; the eight grouped headings, the
  `workflow`/`team`/`eval` retirement notes, the project picker, the positional pod id and the
  `profile`/`keys` examples are gone; a `pod roles` section was missing and was written; the
  index row mirrors the header.
- The rename script treats a spec's `## Changelog` as the record (`7ea2d5c3`): never checked,
  never rewritten (the version history names commands as they were). P39-22 was told mid-card
  to revert any changelog hunk its `--write` produced.
- Denied by the session's permission classifier, left for the maintainer: the one-line
  `"harness","run"` -> `"exec"` change in Tack (`objetivosMios/crates/tack-runner/src/harness/
  docket.rs:336`, `docket/probe.rs:106` and three argv arrays in `docket/tests.rs`) and its
  harness tests; and the live re-capture of the doc assets (`scripts/maint/capture-doc-journey.sh`
  against the local endpoint). The assets were re-rendered from the transcript in Wave 93b
  (`scripts/render-doc-assets.py`) and show the new verbs; the live capture is what P39-23 asked
  for and is still owed.

**Stage two at merge.**
- An invocation linter (`lint_invocations.py`, integrator scratch, not committed) checks every
  `docket ...` line in code spans and code blocks against the live Click tree: verbs, options,
  positional counts. It found about twenty wrong lines in P39-21's first return (`setup sandbox
  isolate on`, `setup notify content`, `status <agent>`, `pod plan <p>`, `task list --retry`, a
  `pod check` argument order, a `programmer` role) that the rename check could not see, because
  they are new-form lines naming things the tree does not have. The worker fixed them on a second
  pass; four lines in `docs/README.md` it left were fixed at merge. Every later card ran the
  linter before returning. **Lesson: a rename check proves old names are gone; only a check
  against the live tree proves the new lines are true. Ship the linter as a guard in Wave 95.**
- P39-19's Sonnet worker was stopped mid-card by the account's session rate limit with its work
  uncommitted. The integrator finished the card in its worktree: the diff was sound except a
  fabricated `docket setup` report block (replaced with the real output of a throwaway home) and
  a wrong Telegram token line (`enable telegram --chat <id>` stores the token). Its agent-lane
  run failed only the spec-index test, already fixed on `develop` at `4951c751`.
- P39-22 ran one `docket setup --fix --json` against the real `~/.docket` (a missing `DOCKET_HOME`
  export); it reported healthy and the live audit log shows no new entry. The worker reverted
  every rewrite inside a spec's `## Changelog` and emptied the guard's `PENDING`; `specs` joined
  the roots at merge, and the index notes in `specs/README.md` were swept by the script and by
  hand (three lines).
- The guard's final roots are the whole tree (`src/docket`, `scripts`, `tests`, `examples`,
  `benchmarks`, `docs`, `specs`, `README.md`, `CONTRIBUTING.md`), `PENDING` is empty, and the
  two `docket add --from` rejection tuples in `test_public_release_truth.py` went (the guard
  covers `examples/`). `git grep 'docket pod '` outside `docs/cycles-ended/` and `CHANGELOG.md`
  finds the old form only in `ROADMAP.md`'s decision history and `.agents/handoffs/` records.
- The live spot-check of the new README and quick start (sixteen lines, throwaway home and pod,
  local endpoint registered, no turn run): every line exits 0.

**Spec locators P39-22 returned for the P39-23 spec pass (requirements, not prose).**
- `mcp-server.spec.md` Syntax/Return: the old `docket mcp` exit codes 0/1 became the exit-2
  conflict of `start --mcp` with `--dispatch|--telegram|--token-file` (P39-13, P39-14).
- `operator-loop.spec.md` requirements 2-3: the forecast is rendered by `task show <ref>` (P39-8).
- `input-validation.spec.md` section 7 still cites `cli/_keys.py::_KEY_PREFIXES` and `_keys_add`
  (P39-12: `setup provider`).
- `cli-json-shapes.spec.md`: no shape for bare `setup --json` (`ready`, `pieces`) (P39-12).
- `audit.spec.md`: no entries for `pod.reset`, `pod.delete`, `pod.unset-verify`, `run.resume`.
- `observability-export.spec.md` 963-977 is a recorded transcript showing `setup provider add
  LANGFUSE_* --credential`; left as recorded output.
- `cli/_agents.py::run_init` help says there is no `docket blueprints add <file>` (a true
  negative, awkward in `--help`); `pod-blueprints.spec.md` 49 and 171 say the same.
- `cli/_setup_check.py` prints `docket setup provider add <name> <url> --credential <NAME>` for a
  missing named credential, but `--credential` takes the key value: the hint should name the
  provider verb for that credential's owner (`setup notify enable telegram`, `setup export
  enable <name>`), P39-23.
