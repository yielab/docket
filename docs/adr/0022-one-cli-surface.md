# ADR 0022 (D-57): one CLI surface, and nothing kept for the past

**Question:** docket's CLI is 46 flat top-level commands over 161 named entry points, none of them
a real Typer sub-command. The maintainer asked for the commands to be "way more intuitive and
simple", checked against best practice and against how the tool actually behaves, and then asked
for the strict reading: every command that is not needed or is redundant goes, with no alias, no
retirement notice and no memory of the old name anywhere; what remains must say what it does
without reading the help, and nest under the thing it belongs to. What is the one surface, what
goes, and what rule keeps it clean?

**Where decided:** 2026-10-07, by the maintainer, opening Phase 39, over three rounds: the audit's
target tree of 32, a cut to 22 on the test "does this noun answer a question of its own", and the
final cut to eleven on the test "does the name explain itself, and what does it belong to". The
noun `pod` was discussed and kept. The audit and its three evidence files (command inventory, six
journeys run live in a throwaway home, sourced best practices with a 20-rule checklist) are in the
gitignored `internal-docs/cli-ux-audit-2026-10-07/`; what this ADR needs from them is restated
here so a contributor without that directory can follow the reasoning.

**Evidence (re-verified in the tree on 2026-10-07, `develop` at `2a245cac`):**

| Fact | Locator |
| --- | --- |
| 46 visible top-level commands, registration order, no grouping; zero `add_typer`; 23 commands parse their own action word from `ctx.args` | `cli/__init__.py` (`context_settings={"allow_extra_args": True, ...}` 24 times) |
| `--help` below the top level prints the parent's help, 0 of 21 probed actions show their own | `docket pod x dispatch --help`, `docket config explain --help` |
| An unknown flag is dropped without a word: `pod <p> dispatch --dry-run` starts a real dispatch | `cli/_pod.py::_parse_dispatch_args` tests membership of four flags |
| Bare `docket gates isolate` turns isolation on and audits it | `cli/_gates.py::run_gates(want="on")` default |
| Bare `docket notify` delivers notifications | `cli/_notify.py::run_notify` accepts `""` as `flush` |
| `delete <pod>` confirms only on a TTY; piped stdin deletes silently, exit 0 | `cli/__init__.py::_delete_pod` (`if sys.stdin.isatty()`) |
| `pod <p> remove <lead>` has no confirmation and removes the Lead; the pod still reports `ready` | `cli/_pod.py::_pod_remove` |
| A `done` task's change sits uncommitted in a task worktree and no command prints its path, branch or diff | `rg worktree src/docket/cli` finds only `worktrees prune` |
| The pod is named seven ways; only `status` and `add` infer it from the cwd | `cli/_agents.py::_pod_for_directory` (two callers) |
| Two role vocabularies: `models` lists `manager`/`programmer`/`repo`; pods use `lead`/`implementer`; `policy_role` bridges them | `core/models_policy.py::ALL_ROLES`, `core/archetypes.py::RoleArchetype.policy_role` |
| The three org specialists (`manager`, `knowledge`, `security`) and the opt-in portfolio manager are provisioned on first `init`, listed, model-resolved and health-checked, and **nothing ever runs one**: no reader in `core/dispatch.py`, `core/orchestrator.py`, `core/pipeline.py`, `serve.py` or the driver | `config.py::ORG_SPECIALIST_ORDER` callers: `cli/_install.py`, `cli/_doctor.py`, `cli/__init__.py` (list, snapshot), `serve.py::_SPECIALISTS`, `core/models_policy.py` |
| Tack, the plan of record, calls exactly one docket command, `harness run`, and reads its final result line | `objetivosMios/crates/tack-runner/src/harness/docket/probe.rs` |
| The README and the landing page speak "team" in prose (25 and 20 lines) and `pod` in every command (15 and 18); `pod.yaml` is `kind: pod` in 32 recipes; HTTP has `/pods`, MCP a `pods` tool; Tack never says either | `README.md`, `newPortaflio/content/docket-landing.ts`, `src/docket/templates/recipes/*/pod.yaml`, `serve.py`, `cli/_mcp.py` |
| `docket help`'s four examples all pass a pod id to a command that takes only an agent id; every one fails | `cli/_help.py` examples vs `info`/`profile`/`context`/`maintain` |
| Exit code for an unknown action is 0 for three commands, 1 for eighteen, 2 for two | measured per command in the inventory |
| `ROADMAP.md` §3 still said removed commands get a notice from `__main__.py`'s `_REMOVED` map, deleted 2026-10-03; §2 said `__main__.py` maps aliases | `ROADMAP.md` before this decision |

The org-specialist finding is the **seventh** recorded instance of the unwired-machinery shape
(machinery implemented, tested, documented, never wired to the default path). The audit did not
flag it; re-verifying the inventory against the live turn path did.

## Decision

1. **Eleven commands. Each says what it does; each thing lives under what owns it.** A command is
   top level only when it is a verb of the daily loop typed without a noun (`init`, `status`,
   `inbox`, `run`), a noun that owns persisted state with several operations (`task`, `pod`,
   `setup`, `log`), or a process or program entry point (`start`, `stop`, `exec`). Everything
   else is a verb under its noun, as a real Typer sub-app: `--help` works at every level with an
   example, an unknown verb or flag is a usage error (exit 2) with "did you mean", and no first
   argument is ever taken as a name.

   ```text
   docket init                         create the team for this repository
   docket status                       this pod: members, queue, last run, cost, what needs you
   docket inbox                        everything waiting for your answer, across pods
   docket task add "..."               queue a task
   docket task list | show <id>        the queue; one task's whole story, worktree and diff included
   docket task approve|deny|answer <id>   respond to what that task is holding
   docket task retry|cancel|diff|trace|prune <id>
   docket run [--resume] [--dry-run] [--pipeline FILE]   run the queued tasks through the pipeline
   docket pod show                     the pod and its effective configuration, with sources and drift
   docket pod add|remove|reset <..>    the roster
   docket pod set|unset <key> [value]  settings: budget, pipeline, network, approval mode, a member's verify command
   docket pod apply|export|validate|plan   the configuration of record in .docket/
   docket pod check "<cmd>" --role R   would the pod's rules allow this?
   docket pod recipes|roles|policies [name]   what can be installed, and what is
   docket pod delete                   destroy the pod, name typed
   docket log [N] | log verify         the hash-chained record of what was authorized and done
   docket setup check [--fix]          what is configured, what is missing, repair
   docket setup model|provider|notify|export|sandbox|mcp|shell ...   each piece of the machine
   docket start | docket stop          the background service: tasks, notifications, Telegram, HTTP, MCP
   docket exec ...                     one agent, one task, one workspace, non-interactive, for programs
   ```

   The verbs are one set: `add`, `remove`, `show`, `list`, `set`, `unset`, plus the domain verbs
   that earn their place (`approve`, `deny`, `answer`, `retry`, `cancel`, `diff`, `trace`,
   `prune`, `reset`, `apply`, `export`, `validate`, `plan`, `check`, `verify`, `enable`,
   `disable`, `bind`, `unbind`, `flush`, `test`, `preset`, `rotate`, `privacy`, `preview`).
   Nouns under `setup` are singular and named for what they do: `model` (role to model),
   `provider` (endpoints and credentials), `notify` (channels and the Telegram binding),
   `export` (trace destinations), `sandbox` (isolation and network), `mcp` (tool servers),
   `shell` (the completion script).

2. **The pod comes from where you stand.** Every pod-scoped command resolves its pod as
   `--pod/-p <name>` > `DOCKET_POD` > the registered pod whose codebase contains the cwd (the
   deeper of two nested pods wins). There is no positional pod id anywhere. When nothing matches,
   the error names what was looked for, the flag and the fix, and exits 1. `--pod` is the same
   flag on every command; `--project` is gone.

3. **The noun stays `pod`, defined once.** A pod is the team of agents attached to one
   repository: its members, its rules, its queue, its ports and worktrees. A recipe is a team
   that can be installed; a pod is that team living in a repo, and the two words are needed to
   say both. With cwd inference the operator types the noun only in the `pod` group and in
   `--pod`; the inconsistency the audit found was seven ways of naming it, not the word. The
   README and the landing page keep "team" in prose and define `pod` with that sentence where
   the first command appears. `pod.yaml`, `kind: pod`, `/pods` and the MCP `pods` tool stand.

4. **Nothing is kept for the past.** docket has no users. A removed or renamed command, flag,
   alias, route, persisted shape or behaviour is deleted in the same change that replaces it,
   together with its tests, its spec text and its documentation. No alias table, no retirement
   notice, no "did you mean the old name", no migration, no `_REMOVED` map, no hidden command, no
   deprecated no-op flag. A retired name is an ordinary unknown command (exit 2) and
   `CHANGELOG.md` is the only record. This rule is written into `CONTRIBUTING.md` ("Rules that
   have cost this project time"), `AGENTS.md` and `ROADMAP.md` §3, and it stands until docket has
   an installed base, which is a fact about the world and not a release number.

5. **Where every old name went, and what goes with nothing in its place.** A command survived
   only with a live consumer: the daily loop uses it, or it is the only operator path to a
   docket-owned state something on the live turn path reads. A read view over files the operator
   can open directly is replaced by printing the path.

   | Old | New | Why it lives there |
   | --- | --- | --- |
   | `delegate`, `pod <p> delegate` | `task add` | a task is the noun; the verb is add |
   | `dispatch`, `pod <p> dispatch`, `pipeline run` | `run` | the verb that spends tokens, typed daily; `--pipeline FILE` is the one-off pipeline |
   | `approve`, `deny`, `chat`, `pod <p> answer`, `pod <p> pregrant` | `task approve\|deny\|answer <id>` | a held action or a question always belongs to one task, and a task holds at most one at a time; `task approve <id> --for "<cmd>"` is the pre-grant. The `apr-…` token leaves the surface |
   | `pod <p> queue\|evidence\|corrections\|explain\|worktrees`, `runs`, `trace` | `task list\|show\|diff\|retry\|cancel\|trace\|prune` | one task's whole story in one place; a run is seen from its task; `task show <run-id>` also resolves a harness run record (was `harness status`) |
   | `cost`, `metrics`, `snapshot` | `status` (per pod, with the labelled estimate and the success/failure counts) and a column of `task list` | all three answered "what happened and what did it cost" |
   | `audit` | `log`, `log verify` | "log" names what you see; "audit" named the mechanism |
   | `add`, `info`, `delete <agent>`, `maintain`, `profile`, `pod <p> list\|add\|remove\|set-verify` | `pod show\|add\|remove\|reset\|set\|unset` | the roster is the pod's; `reset` rebuilds a member's workspace, distilling memory first and failing closed |
   | `pod <p> config`, `config explain`, `profile --budget` | `pod show`, `pod set\|unset` | one reader and one writer for the pod's settings; `pod set verify "<cmd>" --member <id>` |
   | `pod <p> apply\|export\|sync`, `validate`, `roles validate`, `policies validate`, `pipeline validate\|plan` | `pod apply\|export\|validate\|plan` | one validator and one installer for every `kind:` document; `apply` with no argument re-syncs instructions |
   | `policies test` | `pod check` | the question is "would my pod allow this" |
   | `recipes`, `roles`, `policies` (list, show, add), `plugins` | `pod recipes\|roles\|policies [name]` | documents of the pod's configuration; `add <file>` is `pod apply <file>`; plugins are a section of `pod policies` |
   | `delete <pod>`, `profile --resume` | `pod delete` (name typed or `--confirm`), `run --resume` | the inverse of `init`; a budget pause is one more thing `--resume` reclaims |
   | `models`, `models provider`, `keys` | `setup model`, `setup provider` (credentials belong to a provider: `add --credential`, `rotate`) | set once per machine |
   | `channels`, `wire`, `unwire`, `notify`, `conversations` | `setup notify` (`bind\|unbind` for Telegram, `flush`, `show telegram` lists bindings and open conversations) | one place for where notifications go |
   | `exporters` | `setup export` | |
   | `gates` | `setup sandbox status\|on\|off\|network` (bare is a read) | the always-on policy gate is not a setting; the sandbox is |
   | `mcp servers`, `mcp serve` | `setup mcp list\|add\|remove`, `start --mcp` | the catalog is setup; serving MCP is the background service |
   | `completions` | `setup shell bash\|zsh` | printed once, installed once |
   | `doctor` | `setup check [--fix]` | the question is "is my setup complete" |
   | `serve` | `start [--http] [--telegram] [--mcp]`, `stop` | what it is: docket running in the background, picking up tasks, delivering notifications, answering Telegram, exposing the API; the two-stage stop already exists |
   | `harness run` | `exec` (same flags, same contract 1.0/1.1, same events, same exit codes 0/1/2) | one word for "execute one agent on one task in a workspace you give me, for a program"; Tack changes one string |
   | `list`, `info` (views), `context`, `logs`, `edit` | nothing; `pod show <member>` prints the workspace path | read views over files the operator can open |
   | `scope` | nothing; the session key is derived (`core/dispatch.py::step_session_key`) | an operator-set key had no reader on the live path |
   | `persona` | nothing; the persona layer in `core/identity.py` goes with it | cosmetic, one writer, no journey |
   | `profile <id> <model>` (the per-agent pin, `modelSource`) | nothing; a model comes from the role policy, a pod role overlay, or a step's `model:` | a fourth layer with no measured need |
   | `help` | `--help` at every level | |
   | the org specialists and the portfolio manager | nothing; `scope: org`, `ORG_ROLES`, their workspaces, `init --portfolio`, their rows in `/status.json` | never run by anything |

6. **One output and interaction contract.** `--json` on every list, show and status, with
   Rich-free stdout; no prompt and no picker without a TTY (a missing value fails naming its
   flag); destructive verbs confirm on a TTY and need `--yes` off it; `pod delete` and removing a
   Lead need the name typed or `--confirm <name>`; usage errors exit 2, failures 1; every
   state-changing daily-loop command prints one next-step hint on stderr, silenced by
   `DOCKET_NO_HINTS=1`. `inbox` prints the exact `docket task approve <id>` line for each item.

7. **One role vocabulary.** The model policy is keyed by archetype names (`lead`, `implementer`,
   `reviewer`, `tester` and the starter archetypes); `policy_role` and the `manager`/`programmer`/
   `repo` names go. `setup model` shows the names a pod uses.

8. **What does not change.** The `exec` contract (events, result, exit codes, `--contract
   1.0|1.1`): only its name moves. The HTTP routes, the MCP tool names (`delegate`, `dispatch`,
   `pods`, …) and the five Telegram verbs (`/delegate`, `/approve`, `/deny`, `/status`,
   `/answer`): chat and machine surfaces keep their own vocabulary. `core/` and `edges/` beyond
   the deletions named above; the one-chokepoint and one-writer invariants. The `~/.docket/`
   layout and the `.docket/` documents.

9. **One voice.** `ui.py` is the only module that knows symbols, colours and layout. Five
   symbols (`✓` done, `✗` failed or refused, `⚠` attention, `→` next step, `·` detail), five
   colour roles (`success`, `error`, `warn`, `accent` for names, ids and commands, `dim`), one
   tagline, headers of the form `docket · pod myapp`, the same section names everywhere
   (`Needs you`, `Running`, `Done`, `Failed`), tables that wrap and never cut a word, errors of
   one line that say what happened and what to do, and plain ASCII output when stdout is not a
   TTY or `NO_COLOR` is set. A command that changes state ends with exactly one `→ Next: docket
   ...` line on stderr (`DOCKET_NO_HINTS=1` silences it); a read command ends with none. The bare
   `docket` greeting is the tagline, the five daily commands and `Not set up yet? docket setup`.
   A shrink-only guard counts Rich markup outside `ui.py`.

10. **`setup` with no verb is the first run, and it is a flow, not a catalog.** Today the first
    run is four fragments of a wizard (`init` bootstrapping silently and offering desktop
    notifications, `keys setup` walking the catalog, `models preset` reporting readiness,
    `doctor` checking health) and "use Anthropic" is three commands while "use the local
    endpoint" is one. `docket setup` always starts with a report (one line per piece with its
    state and the exact command: the model endpoint, which is the only required piece;
    notifications; sandbox; shell completion; the background service). On a TTY it continues
    by asking only for what is missing, required first, optional pieces default `N`, printing
    every command it runs so the explicit form is learned; it is idempotent and ends with
    `Ready. → Next: cd into a repo and run docket init`. Off a TTY it prints the report with the
    commands and exits 1 when the endpoint is missing. `--fix` repairs what `doctor --fix`
    repaired; there is no separate `check`. The wizard calls the same functions the verbs call,
    so every store keeps one writer. Two intents become one command each: `setup provider add
    <name>` stores the credential, probes `/models` and applies the provider's preset; `setup
    notify enable telegram --chat <id>` writes the token, the actors and every Lead's binding.
    `init` and `run` point at `docket setup` when no endpoint is configured.

## What this reverses

| Earlier decision | Now |
| --- | --- |
| D-2: deprecated commands keep a warning shim one release | Superseded: no shim, no notice, ever, while docket has no users. |
| D-11: `docket team` replaced by a removed-command notice | The notice went 2026-10-03; the name is an unknown command. |
| ROADMAP §3 "Removed commands get a notice, not an unknown-command error" | Replaced by decision 4. |
| ADR 0012 §2 and the audit's own recommendation to keep an `agent` group | Decision 5: no group; the commands go. |
| The audit's recommendation to keep `delegate`/`dispatch`/`approve`/`deny`/`answer` flat and `harness run` by name | Decision 1 and 5: `task add`, `run`, `task approve|deny|answer`, `exec`; chat and MCP keep their verbs. |
| ADR 0001: `docket harness run` is the harness command | The contract stands; the command is `exec`. |
| `docs/AGENT-TEAMS.md` "Org specialists, shared by every pod" | Decision 5: deleted as the seventh unwired-machinery instance. |

## How done is measured

The six journeys of the audit's live run are re-run against the new build under the same
throwaway setup, and the 20-rule checklist is re-scored. Done means: none of the sixteen defects
reproduces; the newcomer path (`init`, `task add`, `run`, `status`, `inbox`, `task approve`) runs
from inside the repo without typing the pod name; every `--help` at every level shows its own help
with an example; a fresh machine reaches `Ready` through `docket setup` alone, with `local` or a
hosted provider; every state-changing command ends with one `→ Next:` line and no module outside
`ui.py` carries Rich markup; every guessed command from the live run (`docket dispatch`, `docket delegate x`,
`docket run`, `docket ls`) either works or gets a correct "did you mean"; the checklist scores
18/20 or better with the two exceptions named; `rg` over `src/`, `docs/`, `specs/`, `tests/`,
`scripts/` and `templates/` finds no invocation of a removed name; Tack's harness probe passes
against `exec`.

## Test discipline

- Three guards, each seen red before it counts: every leaf reachable from the registry has its own
  `--help` with an example; every list/show/status parses as JSON with `--json`; every prompt site
  reached with stdin closed fails fast naming its flag. A fourth guard refuses an invocation of a
  removed command name anywhere in the tree.
- Goldens are regenerated because the cards deliberately change CLI surface; every changed line is
  explained. The README prose tests are rebuilt from the new README, never carried forward.
- The mechanical parts (moving command bodies out of `cli/__init__.py`, rewriting command names in
  docs, templates, scripts and tests) are scripts under `scripts/maint/`, each with a `--check`.

## Live run

Measured 2026-10-08 on `develop` at the Wave 94 rollup (P39-24), the six journeys of the
audit's live run re-run under a throwaway `DOCKET_HOME` against the local endpoint; the
transcript is the gitignored `internal-docs/cli-ux-audit-2026-10-07/live-run-after.md`.

- **None of the sixteen defects reproduces.** `run --dry-run` starts nothing and an unknown
  flag exits 2; `pod unset verify --member` clears a verify command; a done task's worktree,
  branch, base, diff and merge command are printed by `task show` and its path by `task list`;
  `setup sandbox` bare is read-only; an unknown role is one line; the Lead cannot be removed and
  `pod delete` off a terminal needs `--confirm <name>`; after `task approve` the inbox says
  `approved ready` with the `run` command; the short id, a prefix and the approval token all
  resolve; the verify command shows in `pod show`; one role vocabulary; `pod --help` lists
  every verb; one tagline. A dispatch killed mid-hop is settled by `task cancel`, requeued by
  `task retry` and finished by `run --resume`.
- **The newcomer path types no pod name**: `setup`, `init`, `task add`, `run`, `status`, `inbox`,
  `task show`, `task diff` and `task answer` all resolved the pod from the directory.
- **A fresh machine reaches `Ready` through `docket setup` alone** with the local provider, and a
  hosted-shaped provider registers against a fake endpoint (`--credential`, rotate, remove with
  `--yes`).
- **Every `--help` at every level shows its own help with an example** (`-h` included); the
  guessed commands: `docket run` works, `docket pods|add|approve` get the right suggestion,
  `docket dispatch|delegate|ls` exit 2 with no suggestion because no live name is near them
  (decision 4 leaves no old name to point at).
- **Checklist: 18 of 20.** The two exceptions: rule 5, `pod recipes|roles|policies` take a bare
  name where the rest of the tree says `show`; rule 16, there is no switch to turn hints off and
  `task approve <token>` prints no `Next` line.
- **New, for triage** (locators in the transcript's last section): the `--progress` stream names
  the first step for every hop; a denied dispatch's run record stays `waiting_approval` and the
  deny reason reaches the log only; `status` has no "waiting input" bucket; `pod check` requires
  `--role`; a custom provider without `--model` records `local-model`; three `Example:` lines pass
  a timestamp as a task ref.

## Closed with, and carried

Phase 39 closed 2026-10-08: twenty-five cards over Waves 91–95, every gate green on `develop`,
the live run above as the measurement. Integrator corrections made while merging are in each
card's status line on the board (archived in `docs/cycles-ended/todo-waves.md`).

Carried, by name:
- Tack's one string: `"harness", "run"` becomes `"exec"` in its docket adapter, probe and tests,
  then that crate's harness tests. The contract itself did not change. Refused by the permission
  classifier of the session that integrated the phase; the maintainer applies it.
- The live asset re-capture (`scripts/maint/capture-doc-journey.sh`, then
  `scripts/render-doc-assets.py` re-transcribed): the committed visuals show the eleven-command
  names, but their output lines were rewritten by name, not re-captured. Refused likewise.
- The landing page, after the release that ships the names.
- The eighteen locators of the live run, as a triage list; the six worth a card are named above.
  Triaged 2026-10-08 into five cards A–E; A (the approve-by-token hint and the deny reason that
  never reached its task) closed the same day in Wave 96 (`50da5d59`); B–E are proposed, not
  scheduled.
- Two gaps in `scripts/maint/lint_cli_invocations.py`: any upper-case word passes as a
  placeholder, and positional counts go unchecked after an `<a|b>` verb. Closed 2026-10-08
  (`ebbc7b64`), the same day `docket init` became a real Typer command (`a49abba0`, the P39-23
  follow-up) and the prose of six docs was swept (`d8be1e24`).
