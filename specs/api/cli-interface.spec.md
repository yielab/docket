# CLI Interface Contract Specification

**Version**: 1.61.0
**Status**: Complete
**Last Updated**: 2026-10-05

## Purpose

This specification defines the complete CLI interface contract for docket, including all commands, arguments, options, and outputs.

## Scope

This specification covers:
- Command syntax and structure
- Argument parsing and validation
- Option flags and modifiers
- Output formats and structures
- Return codes and error handling
- Environment variables

## Syntax

All docket commands follow a single top-level grammar:

```
docket [global-options] <command> [command-options] [arguments]
```

### Installed Distribution

The root `docket` distribution MUST build both a wheel and an sdist that install
without a source checkout.  Each artifact MUST expose `docket` as the canonical
console command; `docket --version`, `docket --help`, and `docket init --help`
MUST run from an artifact-only installation.  Installed project metadata MUST
report a PEP 440-equivalent form of declared version `0.2.0-beta.3`, Python
requirement `>=3.11`, Apache-2.0 licensing, and the canonical project source,
issues, and homepage URLs.  Uninstalling the
distribution MUST remove its executable, package, and distribution metadata
without deleting dependencies shared by other installed packages.

The release sdist MUST exclude the repository-only `Formula/` directory. The
Homebrew formula hashes that exact archive, so including the formula would make
the published input depend on its own output digest.

The `[project.scripts]` console-command object MUST be the same entry point that
`python -m docket` runs (`docket.__main__:main`), which only invokes the Typer
app, so an installed `docket` and `python -m docket` parse every argv identically.
There is no command alias table and no retired-command notice: a name that is not
a registered command (including one docket used to have) is Click's ordinary
unknown-command usage error (`No such command`, exit 2).

- `global-options` MUST precede the command (see [Options](#options)).
- `command` MUST be one of the entries in the Command Registry below.
- `arguments` are positional and command-specific (see [Arguments](#arguments)).

When a required `agent-id` argument is omitted, commands that operate on a single agent
MUST fall back to interactive selection (a numbered menu).
The per-command entries in the Command Registry are the authoritative source for each
command's exact syntax.

## Arguments

Positional arguments are command-specific; the following conventions apply across commands:

| Argument | Applies to | Rules |
|----------|------------|-------|
| `agent-id` | most commands | MUST match `^[a-z0-9][a-z0-9-]*[a-z0-9]$`; MAY be omitted where an interactive picker can supply it |
| `location` | `init` | MUST be absolute or tilde-expanded. For a `codebase`-kind blueprint (`software`) MUST exist and be readable; for a `workdir`-kind blueprint (`research`/`content`/`ops`) docket creates it if absent |
| `provider/model` | `profile` | MUST be well-formed `<provider>/<model-id>`; or the literal `default` to re-attach to the role policy |
| `action` | `scope`, `keys`, `pod`, `gates` | MUST be a verb from that command's documented action set |

Unrecognized or excess positional arguments MUST produce a clear error and exit 1.

## Options

Options are `--long` flags, some with a `-short` alias. The global options listed above are
accepted by every command; command-specific options are listed per command in the Command
Registry. Conventions:

- Boolean flags default to `false` and take no value (e.g. `--force`, `--json`).
- Value options take exactly one argument (e.g. `--model <provider/model>`, `--days <N>`).
- `--help` MUST be honored before any other parsing and exit 0 (there is no `-h` short form).
- Unknown options MUST produce a clear error and exit non-zero (Typer's usage error, exit 2 —
  see Return Code Convention).

## Global Command Structure

### Syntax Pattern

```
docket [global-options] <command> [command-options] [arguments]
```

### Global Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| --help | - | Show help message | - |
| --version | -V | Show version info | - |

These two are the whole global surface (`docket --help`). There is no `-h`, `-v`, `-d`,
`--debug`, `--quiet`, `--config` or `--no-color` (any of them is an unknown option, exit 2);
state location is chosen with `DOCKET_HOME`, not a config file flag.

## Command Registry

### Core Commands

Invoking `docket` with no command **MUST** print only a compact command guide. It **MUST NOT**
read or render the fleet, project agents, specialist agents, costs, bindings, or health checks.

#### docket init
**Purpose**: Provision a project pod from a blueprint (Lead + Implementer against a codebase by
default — see pod-blueprints.spec.md, ROADMAP Phase 16 W-7). On the first project only, it **MUST**
also bootstrap the workstation-wide Docket home, shared org specialists, baseline policies, and
default security posture before provisioning the project. This global foundation is necessary;
an extra user-facing setup command is not.
**Syntax**: `docket init [project] [location] [--blueprint <name>] [--recipe <name|dir>] [--no-apply] [options]`

Before the first project is created, workstation bootstrap **MUST** validate that the selected
model resolves to a callable OpenAI-compatible endpoint. An API key without a compatible endpoint
is not ready. Failure returns 1, omits every ready/continuation claim, and prints the exact
`docket models provider ...` plus `docket models preset ...` recovery sequence. A registered local
endpoint may pass without a key.
**Arguments**:
- `project` (optional): Project name / pod identifier (slugified to `^[a-z0-9][a-z0-9-]*[a-z0-9]$`);
  omitted defaults to the current directory name
- `location` (optional): Meaning depends on the selected blueprint's `workspaceKind` — a codebase
  path for `software` (the default), or a working directory for `research`/`content`/`ops`
  (auto-provisioned if omitted)
**Options**:
- `--blueprint <name>`: Select a pod blueprint (`software` | `research` | `content` | `ops`);
  omitted defaults to `software` — unchanged from pre-W-7 `docket add`. An unknown name fails
  cleanly (exit 1) before any prompt is shown
- `--codebase <path>`: Explicit location, skipping its interactive prompt
- `--name <text>`: Explicit display name, skipping its interactive prompt
- `--pod full`: Provision a full pod — Lead, Implementer, Reviewer, and Tester. Applies only to
  the `software` blueprint
- `--with <roles>`: Start from the lean pod and add named roles (comma-separated: `reviewer`,
  `tester`, `implementer`). Applies only to the `software` blueprint; passing it with another
  blueprint warns and is ignored (that blueprint's own fixed roster is used instead)
- `--from <file>`: Declarative provisioning from a JSON/YAML spec file (idempotent); an entry
  carrying a `blueprint` field provisions a pod the same way `--blueprint` does interactively
- `--recipe <name|dir>`: Apply a shipped or local recipe directory after provisioning (ADR 0012,
  D-46) — resolved as a directory path if one exists at that location, else a shipped recipe
  under the recipes directory; an unresolvable name fails cleanly (exit 1) naming the shipped
  recipe names, before any prompt or provisioning. Mutually exclusive with a present
  `<location>/.docket/`: giving both fails cleanly (exit 1) naming both sources, before
  provisioning
- `--no-apply`: Provision the pod only, skipping the apply step for a present `.docket/` or a
  resolved `--recipe`; prints the `docket pod <p> apply <dir>` command that would apply it

A repository's own `<location>/.docket/` (the same directory shape `docket pod <p> apply` reads,
see pod-blueprints.spec.md, "Pod manifests: apply") is discovered automatically: `init` validates
every document under it before provisioning anything, and — unless `--no-apply` is given — applies
it after provisioning through the same `plan_apply`/`apply` path `docket pod <p> apply` uses. A
validation error exits 1 naming the file and field, with nothing provisioned.
**Output**: Creation progress and confirmation with member IDs. The closing `created with N
members` line and the id list that follows it count every member of the pod as it stands after
the apply step, so a member a present `.docket/` or `--recipe` added is counted and listed
**Return**: 0 on success, 1 on error (pod already exists, invalid arguments, unknown blueprint,
or provisioning registered no member — docket's flat convention, see Return Code Convention below)

With no explicit project or location, `init` **MUST** derive both from the current working
directory without an interactive questionnaire. The intended first-run flow is package-manager
installation followed directly by `docket init` once per project. Declarative `--from`
provisioning belongs to `init`, including multi-project automation.

#### docket add
**Purpose**: Add one or more role agents to an existing pod. It **MUST NOT** create a project.
**Syntax**: `docket add <role> [--project <pod>] [--count N] [--verify "<cmd>"]`
**Arguments**:
- `role` (required): A built-in or installed archetype role; duplicate non-singleton roles are
  indexed using the existing pod-member rules.
**Options**:
- `--project <pod>`: Target pod explicitly. When omitted, Docket resolves the pod whose configured
  `codebase`/`workDir` contains the current working directory; zero or ambiguous matches fail with
  an actionable error.
- `--count N`: Add N members of that role.
- `--verify "<cmd>"`: Set the mechanical verification command for a new Implementer.
**Output**: Confirmation with the created member ID(s).
**Return**: 0 on success, 1 when the pod/role is missing or invalid.

#### docket status
**Purpose**: Show project-level status without mixing it with workstation diagnostics or the
agent inventory.
**Syntax**: `docket status [--all] [--json]`
**Behavior**:
- With no flag, resolve the most-specific initialized pod whose `codebase`/`workDir` contains the
  current directory and report its path, members, task counts, and readiness.
- `--all` reports the same summary for every registered pod, once per project rather than once per
  agent.
- No current-directory match **MUST** fail with an actionable `docket init`/`--all` message.
- `doctor` remains workstation-wide technical health; `list` remains the detailed global agent
  inventory. Neither behavior is an implicit side effect of `status` or bare `docket`.
**Return**: 0 on success, 1 when current-project resolution fails.

#### docket list
**Purpose**: Display all agents
**Syntax**: `docket list [--json]`
**Arguments**: None
**Options**:
- `--json`: Emit the listing as one JSON document instead of the Rich table (see
  `cli-json-shapes.spec.md`)
**Output**: Formatted agent list
**Return**: 0 always

#### docket info
**Purpose**: Display detailed agent information
**Syntax**: `docket info [agent-id] [--json]`
**Arguments**:
- `agent-id` (optional): Agent identifier; interactive picker if omitted
**Options**:
- `--json`: Emit the agent record as JSON
**Output**: Agent details in requested format
**Return**: 0 on success, 1 if not found

#### docket delete
**Purpose**: Remove agent completely
**Syntax**: `docket delete [agent-id]`
**Arguments**:
- `agent-id` (optional): A pod id (removes every member) or a legacy flat agent id; interactive
  picker if omitted. Org specialists cannot be deleted this way
**Options**: None. A pod deletion requires typing the exact pod id to confirm in an interactive
terminal; there is no `--force` or `--keep-logs`
**Output**: Deletion confirmation
**Return**: 0 on success, 1 if not found

#### docket maintain
**Purpose**: Clear memory, repair, or rebuild an agent (replaces the retired `reset`/`repair`/`cleanup`)
**Syntax**: `docket maintain [agent-id] [mode] [--no-distill-first]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
- `mode` (optional): Maintenance level (default: `check`)
**Modes**:
- `check`: Health check and auto-fix (was `docket repair`)
- `clean`: Distill pending `memory/*.md` day-logs into MEMORY.md and archive the originals, then
  delete anything left in `memory/*.md` (was `docket reset 1`)
- `reset`: Clean + clear MEMORY.md (unless a distillation just refreshed it) and HEARTBEAT.md
  (was `docket reset 2`)
- `rebuild`: Deep rebuild — regenerate all files from metadata (was `docket reset 3`)
- `sessions`: Report per-session storage size (ROADMAP Phase 19 P19-4: session compaction is
  automatic now, so there is nothing left to trim or archive manually; was `docket cleanup safe`)
- `distill` (ROADMAP Phase 17 C-2): summarize pending `memory/*.md` day-logs into a dated
  `MEMORY.md` section via one driver-backed agent turn (decision D-18 — no provider SDK, routed
  through the same `RuntimeDriver` port every pod dispatch hop uses), then archive the originals
  to `memory/.distilled/<day>/`. Runs without a confirmation prompt (non-destructive to the logs
  it processes); a driver failure or an empty reply leaves every file untouched and exits 1
**Options** (`clean`/`reset` only):
- By default `clean`/`reset` run `distill`'s summarize-then-archive step before the command's
  own destructive step; a failed distillation aborts the whole command before anything is deleted
- `--no-distill-first`: skip distillation and delete/clear immediately
Any other flag (including `--distill-first`, which there is no need to pass) is an unrecognized
flag: an error naming it, exit 2.
**Output**: Maintenance progress and confirmation
**Return**: 0 on success (including a cancelled confirmation); 1 if the agent is not found, the
mode is unknown, or (`clean`/`reset`/`distill`) the distillation turn fails; 2 on an unrecognized
flag

### Configuration Commands

#### docket profile
**Purpose**: Pin an agent's model, set a budget cap, or resume from an auto-pause
**Syntax**: `docket profile <agent-id> [<provider/model> | default] [--budget <USD>] [--resume]`
**Arguments**:
- `agent-id` (required): Target agent
- `provider/model` (optional): Pin to a specific model (e.g. `anthropic/claude-sonnet-4-6`); shows current if omitted
- `default` (optional): Re-attach to the role policy model (unpin)
**Options**:
- `--budget <USD>`: Set per-agent spend cap; `0` or `--budget 0` removes it and clears any
  auto-pause; when *agent-id* is a pod's Lead, also unblocks that pod's budget-blocked tasks
- `--resume` (ROADMAP Phase 14 R-5): Clear an auto-pause (`paused`/`pausedReason`) reached via a
  budget cap; writes a `profile.resume` audit entry; when *agent-id* is a pod's Lead, also
  unblocks that pod's budget-blocked tasks so dispatch can claim them again
**Output**: Profile change confirmation or current profile
**Return**: 0 on success, 1 on error (agent not found, or invalid input)

#### docket models
**Purpose**: View and update the role→model policy; switch provider presets; manage the provider
catalog
**Syntax**: `docket models [set <role> <provider/model> | preset <name> | provider <action> | reset]`
**Actions**:
- (no args): Show the current role→model table (role, model, price, source, why)
- `set <role> <provider/model>`: Override the model for a specific role
- `preset <name>`: Switch all roles to a provider preset from the catalog (`anthropic`, `openai`,
  `google`, `openrouter`, `openrouter-free`, `ai-gateway`, `local` among others); a built-in
  hosted preset needs only its credential -- no separate registration -- and applying one prints
  a readiness line naming that credential as present or missing
- `provider add <file.yaml>`: Register a `kind: provider` document
- `provider add <name> <base-url> [--model ID] [--ctx N] [--max-tokens N] [--credential NAME]`:
  Today's shortcut over the same document; registration probes `<base-url>/models` with the
  resolved credential and classifies the result (model-profiles.spec.md "Provider readiness" 3)
  -- only a transport failure refuses; every HTTP status registers, with a warning when it is not
  a clean 200
- `provider list`: List every provider (name, scope, dialect, base URL, credential)
- `provider show <name> [--json]`: Show one provider's resolved entry and scope
- `provider remove <name>`: Remove a global override; a built-in with none refuses
- `provider export <name> [<file>]`: Print (or write) the provider as a `kind: provider` document
- `reset`: Restore built-in defaults
**Output**: Role→model table or update confirmation
**Return**: 0 on success, 1 on invalid role, preset, or provider action

#### docket scope
**Purpose**: Manage session keys for project isolation
**Syntax**: `docket scope [agent-id] [action] [value]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
- `action` (optional): show (default)/set/reset
- `value` (conditional): Required for 'set' action
**Output**: Current or updated session key
**Return**: 0 on success, 1 on error (agent not found, or invalid input)

#### docket keys
**Purpose**: Manage API keys centrally; the model resolver reads selected-provider keys directly
and matching credentials sync to agent workspaces
**Syntax**: `docket keys [action] [key-name]`
**Actions**:
- `list`: Show all stored keys (values masked) — default
- `setup`: Interactive setup wizard for all keys
- `add <KEY_NAME>`: Add a key (errors, exit 1, if the name already exists — use `rotate`)
- `rotate <KEY_NAME>`: Replace the value of an existing key (exit 1 if it does not exist)
- `validate [KEY_NAME]`: Check known local format rules (no network validation)
- `remove <KEY_NAME>`: Remove a key
- `export`: Print keys as shell environment variables
**Key names**: at least `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`,
`OPENROUTER_API_KEY`, `AI_GATEWAY_API_KEY`; other syntactically valid uppercase names are allowed
**Output**: Key status or update confirmation
**Return**: 0 on success, 1 on missing/invalid arguments or invalid key-name syntax
**Note**: `keys` is the real, and now the only, model-auth credential path. `setup` prompts for
every built-in provider credential the provider catalog declares, in catalog order (see
api-keys.spec.md).

`docket auth` (provider API-key status plus honest-gone `login`/`key`/`setup` stubs) was
**retired** in Phase 29 (D-45) — the provider catalog (`docket models provider add`, above
`docket keys`) replaced the daemon-era shape that command was reporting the absence of. `auth`
is not a registered command: `docket auth <anything>` is an ordinary unknown-command error
(exit 2). Store a credential with `docket keys add`; register an endpoint with `docket models
provider add`. (ROADMAP decision D-45 is the durable retirement record.)

#### docket validate
**Purpose**: Validate role, pipeline, policy, and pod configuration documents (see
`config-format.spec.md`) — one command for every kind, rather than a separate `validate`
subcommand per kind
**Syntax**: `docket validate [dir|file]`
**Arguments**:
- `dir|file` (optional): A directory to validate every document under (default `<cwd>/.docket`
  when it exists, else the current directory), or a single file to validate alone
**Output**: One line per file — `ok <file> (<kind> <name>)` or its error — invalid files
printed first, plus one `note:` line per file loaded without a `kind:` key. A directory target
also prints, after the per-file lines, `summary: <line>` — `core.pod_apply.summarize_recipe`'s
derived roles/policies/members/pipeline/plugins/skills/settings counts
(`pod-blueprints.spec.md` 1.14.0) — and the directory's own `description` on its own line when
its `pod.yaml` sets one; a file target prints neither
**Return**: 0 if every file is valid, 1 if any file is invalid or the target does not exist

### Pipeline Commands

`docket workflow` (the Lobster YAML surface: author/validate/plan a `.lobster.yml` template)
was **retired** in Phase 16 (D-16) — its validator silently ignored four constructs its own
template emitted, so docket was linting a dialect it could not fully execute. `workflow` (and
`wf`) are not registered commands — invoking one is an ordinary unknown-command error (exit 2).
The single pipeline dialect docket executes is `docket pipeline validate` / `plan` / `run`
(`pipeline-format.spec.md`, Phase 16 W-1/W-2). Any
existing `<workspace>/workflows/*.lobster.yml` files are left on disk untouched, but no longer
read by docket. (The former workflow-integration.spec.md was removed 2026-07-30; ROADMAP
decision D-16 is the durable retirement record.)

#### docket pipeline
**Purpose**: Validate, plan, and run a docket-native pipeline (ROADMAP Phase 16 W-1 format / W-2
executor). See pipeline-format.spec.md for the file format.
See pod-dispatch.spec.md for how it actually runs.
Not the Lobster dialect — `docket workflow` was retired by ROADMAP Phase 16 W-3 (see above).
**Syntax**: `docket pipeline <action> ...`
**Actions**:
- `validate <file>`: Structural validation of a pipeline YAML file; does not execute; no project
  involved
- `plan <project> [--file <path>]`: Render the resolved step plan for *project*'s pod, from the
  real executor (`core.orchestrator.resolve_plan`/`render_plan`) — never a second, drift-prone
  pretty-printer; does not execute or consume tokens. `--file` omitted resolves the pod's
  zero-migration default pipeline (identical to what `run`/`docket pod <project> dispatch` would
  actually execute)
- `run <project> [--file <path>] [--resume] [--timeout <seconds>] [--follow]`: Dispatch
  *project*'s pending (and, with `--resume`, crash-recoverable) tasks through the given (or
  default) pipeline — the same real, costed pipeline `docket pod <project> dispatch` drives
  (identical run-registry recording, budget/approval gating, retries, crash resume); `--file`
  selects a custom `PipelineSpec` instead of the pod's zero-migration default. `--follow`
  (ROADMAP Phase 16 W-4) runs that same dispatch on a background thread while the foreground
  thread tails new trace events for *project* to stdout as they're written — an operator sees
  hop-by-hop progress rather than only the final summary; Ctrl-C stops *watching* only; the
  dispatch keeps running and recording in the background. See pod-dispatch.spec.md for the
  full state machine and pipeline-format.spec.md for the file format
**Output**: Validation result, rendered plan, or per-task dispatch results (including cost);
with `--follow`, also every new trace event observed while the dispatch is in flight
**Return**: `0` on success; `1` on an invalid/missing file, an unknown project/pod, a dispatch
error, or a dispatch whose run record ends `failed` because a task failed — the same rule as
`docket pod <project> dispatch` (see `docket runs show <id>` for the recorded error)

### Pod Commands

`docket team` (the old org-wide manual task queue) was **retired** in 0.2.0 (D-11) — it had no
dispatcher and never executed anything. Delegation now belongs to each project's pod
(pod-dispatch.spec.md). `team` is not a registered command — `docket team <anything>` is an
ordinary unknown-command error (exit 2); use `docket pod <project> delegate|queue|dispatch`
below. (The former team-coordination.spec.md
was removed 2026-07-30; ROADMAP decision D-11 is the durable retirement record.)

#### docket pod
**Purpose**: Manage a project's pod (list/add/remove members; delegate, queue, and dispatch real work)
**Syntax**: `docket pod <project> <action> [args]`
**Actions**:
- `list`: Show the pod's members (Lead, Implementer, optional Reviewer/Tester)
- `add <role> [--count N] [--verify "<cmd>"]`: Add a member (role may be duplicated, e.g. a
  second implementer). `--verify` is Implementer-only — it writes the new member's `verifyCmd`
  (FD-1); passing it for a non-implementer role warns and is ignored
- `set-verify <member-id> "<cmd>"`: Set or replace an existing Implementer's `verifyCmd`
  (FD-1); rejected with an error for a non-implementer member id; validated (no NUL/newline,
  length-capped) and audit-logged (`pod.set-verify`, ROADMAP Phase 14 R-6)
- `evidence <task-id> [--json]`: Show what a task's hops kept (evidence-v1, built by
  `core.evidence.task_evidence`): a table of hop, role, ok, verdict, verify exit code, short
  commit and measured tokens in/out. `--json` prints that document byte-for-byte as `GET
  /tasks/<project>/<id>/evidence` returns it. An unknown task prints an error and exits `1`
- `worktrees prune [--dry-run] [--force]`: Remove the worktrees of this pod's finished
  (`done`/`failed`/`cancelled`) tasks, deleting each branch merged into the codebase's current
  branch and recording `worktree.prunedAt`. Dirty or unmerged ones are kept and reported with
  the reason; `--force` removes them anyway (the unmerged branch itself stays) and audits it
  (`pod.worktrees.prune`); `--dry-run` changes nothing. Other usage exits `1`
- `apply [<name|dir>] [--dry-run] [--json]`: Apply a recipe/manifest directory (`roles/*.yaml`,
  `pipeline.yaml`, a small `pod.yaml` naming
  `members`/`settings`/`pipeline`/`description`/`exporters`) to this pod in one command,
  composing the same `roles add`/`add <role>`/`config set` writers rather than a new write path;
  the argument resolves as a directory path if one exists there, else as a shipped recipe name,
  exactly as `docket init --recipe` resolves it (an unresolvable name exits 1 naming the shipped
  recipes); with no argument it defaults to `<codebase>/.docket`. Validates every role, the
  roster the pipeline would resolve against once `members` join, every setting, and every
  `exporters` name against `core.exporter.load_catalog()`, before writing anything; idempotent
  (a second run plans every item `skip`); `--dry-run` prints the plan without writing. The
  non-`--json` plan is preceded by a header — `Apply plan — <project> <- <dir>`, the directory's
  own `description` when set, then `core.pod_apply.summarize_recipe`'s derived summary line —
  the same header `docket init --recipe`/a discovered `.docket/` prints
  (`cli/_pod.py::render_apply_header`), and followed, after the plan, by one line per named
  exporter — its state from `core.exporter.activation_state` and, unless already `enabled`, the
  exact `docket exporters enable <name>` command (`cli/_pod.py::render_apply_plan`/
  `render_exporter_states`); nothing is ever written to `docket-exporters.json` from this path.
  See `pod-blueprints.spec.md`, "Pod manifests: apply"
- `export [<dir>] [--force]`: Write this pod's own scope, every YAML file in the short form with
  a `# yaml-language-server:` header — pod-overlay `roles/<name>.yaml` (+ paired
  `roles/<name>.md` instructions), this pod's own `policies/<stem>.yaml`, a bound
  `pipeline.yaml` copy (if any), a `pod.yaml` naming `kind: pod`, `name`, non-Lead `members`,
  every non-default `setting`, this pod's recorded `exporters` (when set), and the four
  config-v1 JSON Schemas copied into
  `.schemas/` — into `<dir>`, the same shape `apply` reads back. `<dir>` defaults to
  `<codebase>/.docket`, like `apply`. Global scope (the operator's
  own role overlay, fleet-wide policies, other pods) is never exported. Refuses a non-empty
  `<dir>` (including the default) unless `--force`. See `pod-blueprints.spec.md`,
  "Pod manifests: export"
- `remove <member-id>`: Remove a pod member
- `delegate <task> [--priority high|normal|low] [--brief FILE.json]`: Queue the complete
  free-form task on this pod's own list whether it arrives as one quoted argv item or several
  ordinary positional words (one queue per pod, at
  `~/.docket/workspaces/<project>-lead/TASK_LIST.json`). `--brief` (Phase 34, P34-13) loads and
  validates the file as a `TaskBrief` (operator-v1); an invalid one exits non-zero and enqueues
  nothing. A *valid* one is passed through to `core.dispatch.enqueue_task`'s own `brief=`
  parameter and actually enqueues
- `answer <task-id> [text] [--field name=value]... [--decline]`: Answer a parked question
  (Phase 34, P34-13; see operator-loop.spec.md "Answer surfaces"). A bare `text` fills the single
  property of a one-property question schema; `--field` sets named properties explicitly
  (required for a multi-property schema); `--decline` ignores any `text`/`--field`. Calls
  `core.answers.answer_task(channel="cli", actor=<OS user>)`
- `explain interruptions [--json]` (Phase 34, P34-15, ADR 0016 §10): Forecast, from this pod's
  own effective configuration, everything that could pause a task before it is even dispatched —
  matching `require_approval` policies, pipeline `ApprovalGate`/`input` steps,
  `requireApprovalRoles`, plus context on the pod's resolved `approvalMode`, the always-on
  `core/security.py` high-risk classes, and enabled notifying channels. Prints
  `core.interruptions.NOTHING_WILL_ASK` when nothing would ask. `--json` emits `{"pod",
  "interruptions": [{"kind", "description", "detail"}, ...]}`. A bare `explain` with no
  `interruptions` argument, or any other topic, prints usage and exits 1
- `pregrant <task-id> "<command>" [--tool bash]` (Phase 34, P34-15, ADR 0016 §10): Record a
  single-use pre-grant for one exact command on one task, ahead of dispatch — the CLI counterpart
  of `POST /tasks/<id>/pregrants` and the MCP `task_pregrant` tool. Calls
  `core.interruptions.record_pregrant(channel="cli", actor=<OS user>)`, which calls
  `core.approval.create_pregrant` exactly as an in-turn park does; when the pipeline later
  reaches that exact call (matched by `core.operator_contract.canonical_args_digest`), it passes
  once without asking again
- `queue [--retry <task-id>]`: List the pod's task queue (all statuses, not just pending);
  `--retry <task-id>` (Phase 14 R-1) moves one `blocked` task back to `pending` — the only
  other way is a pod-wide budget change (`docket profile <lead-id> --budget`/`--resume`). A
  `blocked` task is never retried automatically
- `dispatch [--resume] [--timeout <seconds>]`: Run the pod's pending (and, with `--resume`,
  crash-recoverable) tasks through its real pipeline — one real, costed agent turn per hop
  (Lead → Implementer → optional Reviewer/Tester), via `core/dispatch.py`. Gated by the budget
  cap (which now auto-pauses the pod's Lead when reached), the Implementer's `verifyCmd` (if
  set, run in its worktree when one exists), a Reviewer verdict gate with a bounded rework loop
  (if a Reviewer is present), and — when a Tester is present — a structural PASS/FAIL parse of
  the Tester's reply (FD-2). `--resume` (Phase 14 R-1) also reclaims any task a prior dispatcher
  left `failed` with a stale claim (it crashed mid-task) and continues each one from its last
  persisted hop instead of hop 0. `--timeout <seconds>` (Phase 14 R-2) overrides both the
  agent-turn and `verifyCmd` timeout for this run only. Every invocation (this CLI path, the
  serve webhook, a due schedule, or the sweep loop) is recorded in the run registry (`docket
  runs`, Phase 14 R-3) with a queryable outcome. See `pod-dispatch.spec.md` for the full state
  machine
**Output**: Pod roster, queue listing, or per-task dispatch results (including cost). Every
bracketed identifier (`[<task-id>]`, `[<role>]`, `[<member-id>]`) and every task description or
failure reason is printed literally, never interpreted as terminal markup
**Return**: `0` on success, `1` on error (project/member not found, malformed args, no pod for
the project, dispatch raised an exception, or any task in this dispatch ended `failed` — the exit
status matches the run record's `failed` state; see `docket runs show <id>` for the recorded
error). A task left `blocked` or `waiting_approval` is an expected pause, not a failure, and
exits `0`

#### docket roles
**Purpose**: Inspect and manage declarative role archetypes — built-in, starter-library, and
user-defined (see role-archetypes.spec.md)
**Syntax**: `docket roles <list|show|add|validate> [args] [--pod <p>]`
**Actions**:
- `list [--pod <p>]`: Show every registered archetype (name, scope, model class, gate contract,
  edit rights, description); with `--pod <p>`, also resolves pod `<p>`'s own role overlay on top
- `show <name> [--pod <p>]`: Print one archetype's full definition (YAML, or JSON if PyYAML is
  unavailable), resolved the same way as `list`
- `add <file.yaml> [--pod <p>]`: Validate a standalone archetype YAML file and merge it into the
  user overlay (`~/.docket/docket-roles.json`), or — with `--pod <p>` — into pod `<p>`'s own
  overlay instead; either overrides a built-in/starter/global-overlay archetype by reusing its
  name
- `validate [file.yaml]`: With no argument, validate every archetype in the live registry; with
  a file argument, validate that candidate definition without persisting it. Takes no `--pod`
**Output**: Archetype listing, one archetype's definition, or a per-archetype pass/fail report.
`list`/`show` report a pod-overlay-defined role's source as `pod:<p>`, distinct from `user`
**Return**: `0` on success, `1` on an unknown subcommand, an unknown `show` target, or an invalid
archetype definition

#### docket runs
**Purpose**: Inspect the persisted dispatch-run registry — one record per invocation of a pod's
pipeline, whatever triggered it (ROADMAP Phase 14 R-3); cancel one in flight (ROADMAP Phase 16 W-2)
**Syntax**: `docket runs <list|show|cancel> [args]`
**Actions**:
- `list [--project <project>] [--json]`: Show run records, newest first; `--project` filters to
  one pod
- `show <run-id> [--json]`: Show one run record (source, project, state, task ids, error,
  timestamps, and — for a `webhook` source, ROADMAP Phase 16 W-4 — the resolved pipeline
  `variables` its payload was dispatched with). Human output also shows cancellation request,
  observation, and full-stop timestamps when present.
- `cancel <run-id>`: Kill every hop subprocess currently recorded as in-flight for that run — its
  whole process group, not just the immediate child (see pod-dispatch.spec.md's "Cancellation")
  — and durably request cancellation. Queued work becomes terminal immediately; running work stays
  visibly `running` with a cancel-requested marker until its executor observes the signal and fully
  stops. A no-op (reported, not an error-free success) against a run that's already terminal. A
  genuine cancellation writes exactly one `runs.cancel` audit entry
  (ROADMAP Phase 16 W-4; see audit.spec.md) naming the run, its project, its pre-cancel state,
  and how many process groups were killed — the no-op paths write nothing
**Output**: A table (or, with `--json`, the bare record(s) — see `cli-json-shapes.spec.md`); a
confirmation message for `cancel`
**Return**: `0` on success; `1` if `show`'s run id is unknown or no id was given, or if `cancel`'s
run id is unknown or already terminal

#### docket mcp

**Purpose**: Expose docket's control plane as an MCP (Model Context Protocol) stdio server
(ROADMAP Phase 18 L-3) — full contract in `mcp-server.spec.md`
**Syntax**: `docket mcp <serve | servers <list|add|remove> ...>`
**Actions**:
- `serve`: Start the stdio MCP server (blocks until the client disconnects). Requires the
  optional `mcp` extra (`pip install 'docket[mcp]'`); prints an actionable hint and exits 1 if
  it isn't installed, rather than a bare traceback
- `servers list|add|remove`: Configure external stdio MCP tool servers whose tools reach a live
  turn through the same `dispatch_tool` chokepoint — `add <name> [--env K=V ...] [--timeout S]
  [--kind read|write] [--tools NAME,...] [--no-isolate] -- <command> [args]`; `--kind` declares the server's
  trust level (default `write`) and `list` shows it alongside each server's `tools` allow-list
  (empty = all); `--no-isolate` starts the server on the host instead of in the turn's jail (audited, shown by `list`); a bad `--kind` value exits 1 naming the field; full contract in
  `mcp-client.spec.md`
**Output**: Nothing on stdout (stdout is the JSON-RPC transport once serving); one stderr line at
startup naming the registered tools
**Return**: `0` on clean shutdown or bare `docket mcp` (prints usage), `1` if the SDK is missing or
an unrecognized subcommand was given

#### docket harness
**Purpose**: Run one agent, for one turn, to completion, in a workspace and `DOCKET_HOME` the
caller supplies — for an external plan-of-record that spawns docket as a subprocess. Full
contract (wire shapes, refusal table, result mapping) in `harness-mode.spec.md`
**Syntax**: `docket harness run --workspace DIR (--task TEXT | --task-file PATH) --model
PROVIDER/ID [--role implementer] [--timeout SECONDS] [--agent-id ID]` · `docket harness status
TOKEN`
**Output**: `run` streams NDJSON `HarnessEvent` lines and exactly one `HarnessResult` on stdout;
every log goes to stderr. `status` prints one JSON line
**Return**: `run` — 0 `ok`, 1 `failed`/`blocked`/`cancelled`, 2 refused before any run began (the
one named exception to the flat convention, see Return Code Convention); `status` — 0 on a
lookup, 1 on a missing token

### Memory and Context Commands

#### docket context
**Purpose**: Inspect and manage an agent's memory/context
**Syntax**: `docket context [agent-id] [action]`
**Actions**:
- `show`: Recent activity overview (default)
- `project`: Show project-level context

Any other action prints `docket context: unknown action '<action>' (expected: show, project)`
and exits 2; it never falls through to `show`.

`search`/`snapshot`/`index`/`compress` and the `SNAPSHOT.md` artifact were **removed** — see the
CHANGELOG's Unreleased "Removed" entry. Semantic search over an agent's memory (`memory_search`/
`memory_get`) is not part of Docket's runtime — there is no keyword-index successor, so this is a
real, named gap
rather than a capability delegated elsewhere. Folding logs into `MEMORY.md` is
`docket maintain <id> distill`.
**Output**: Context view or action confirmation
**Return**: 0 on success, 1 if not found, 2 on an unknown action

#### docket edit
**Purpose**: Open an agent's workspace files in `$EDITOR`
**Syntax**: `docket edit [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Opens SOUL.md, AGENTS.md, TOOLS.md, HEARTBEAT.md in the editor
**Return**: 0 on success, 1 if not found

#### docket logs
**Purpose**: Show an agent's latest memory log. **ROADMAP Phase 19 P19-7b removed the
"today's gateway entries" section** — there is no daemon gateway log left to scan for a bound
peer's activity, and no successor; the command reports memory logs only.
**Syntax**: `docket logs [agent-id]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Latest memory day-log (first ~40 lines, with a "more lines" note if truncated)
**Return**: 0 on success, 1 if not found

### Maintenance Commands

#### docket doctor
**Purpose**: Workstation-wide diagnostics across the complete registered fleet. Human-readable
output **MUST** label the project-agent section as global so running it from one repository cannot
be mistaken for a repository-local listing; seeing another registered project is inventory
visibility, not shared workspace or session state.
**Syntax**: `docket doctor [--json] [--fix]`
**Options**:
- `--json`: Emit the machine-readable health probe (see `cli-json-shapes.spec.md`)
- `--fix`: Apply auto-fixes for detected drift
**Output**: System health report
**Checks** (ROADMAP Phase 19 P19-7b — no daemon left to check status of):
- Required command availability (`python3`; no optional binaries are probed)
- Fleet registry (`fleet.json`) and agent-registration validity
- Malformed `docket-models.json` entries (unknown rank anchor or role, bad model id) that the
  registry loader would silently ignore
- Workspace permissions and template drift
- Dispatch ledger sync, budget/runaway spend, key hygiene, security-gate posture (when docker is
  the jail backend in use, the `DOCKET_SANDBOX_IMAGE` image is probed once for `git` and a missing
  one warns with the fix)
- Global guardrail policy files, plus every provisioned pod's own `config/` overlay
  (role archetypes and policy files) — a malformed pod-scoped entry is named with the
  pod, not silently skipped
- Global provider catalog documents (`docket-providers.json`) — a malformed entry is named
  with the file and the failing field, e.g. an unknown `auth.type`
- Enabled exporters' recorded health (`exporters-health.json`) — a non-zero `failed` count
  since the exporter's last success is named with `docket exporters test <name>` as the fix
- MCP server isolation state: unjailed servers (isolate: false) from both global and per-pod
  registries when isolation is not off (human output warns; `--json` lists with pod context)

When issues are found the footer points at `docket maintain [id] check`.
**Return**: 0 if healthy, 1 when any issue is flagged

#### docket cost
**Purpose**: Display usage and costs
**Syntax**: `docket cost [agent-id] [--json] [--history [--days N]]`
**Arguments**:
- `agent-id` (optional): Specific agent or all
**Options**:
- `--json`: Emit JSON (see `cli-json-shapes.spec.md`)
- `--history`: Per-day history view (see cost-tracking.spec.md for why it is currently empty)
- `--days N`: History window in days (default `0`, meaning no limit)
**Output**: Cost breakdown table
**Return**: 0 always

### Monitoring Commands

#### docket snapshot
**Purpose**: Emit JSON system state for dashboards or CI artifacts
**Syntax**: `docket snapshot [--output <file>]`
**Options**:
- `--output <file>`: Write JSON to a file instead of stdout
**Output**: JSON object (`timestamp`, `channels`, `agents`, `totalCostUsd`)
**Return**: 0 on success

#### docket serve
**Purpose**: Background loop — refresh fleet status and optionally drive pod dispatch pipelines
**Syntax**: `docket serve [--port <n>] [--interval <s>] [--dispatch] [--telegram] [--token-file <path>]`
**Options**:
- `--port`/`-p <n>`: Listen port for the HTTP API (default: 7331)
- `--interval`/`-i <s>`: Sweep refresh interval in seconds (default: 30)
- `--dispatch`: On each refresh, also run every pod's pending tasks through its pipeline (real, costed LLM turns; budget-gated and traced). Off by default — plain `docket serve` never dispatches on its own.
- `--telegram`: Long-poll docket's own Telegram bot for `/approve` `/deny` `/status` `/delegate`
  (needs `TELEGRAM_BOT_TOKEN`; see telegram-integration.spec.md)
- `--token-file <path>`: Write the Bearer token for the authenticated routes to this file (0600)
  instead of printing it
**Output**: Serves the HTTP API on `http://localhost:<port>/` — unauthenticated read routes
(`/status.json`, `/metrics`, `/health`) plus Bearer-authenticated routes (`/approvals`, `/runs`,
`/tasks`, `/traces`, `POST /approvals/<token>`, `POST /dispatch/<project>`, `POST /pods`); full
contract in serve-read-api.spec.md.
With `--dispatch`, also logs each dispatch hop
**Return**: 0 on clean shutdown (Ctrl-C)

### Security and Gates

#### docket gates
**Purpose**: Report docket's own tool-call gate and manage workspace isolation. The gate itself
(the policy engine + argument-aware command classifier) is unconditionally active on every tool
call docket dispatches — there is nothing to enable or disable — so what this command manages is
isolation-mode posture.
**Syntax**: `docket gates [status | isolate <on|off> | network <none|open> | classes]`
**Actions**:
- `status` (default): Report the gate as always-active, plus the isolation state
  (`on (default)` with no recorded choice, `on`, or `off`)
- `isolate <on|off>`: Record exec isolation on or off explicitly. Isolation is on by default.
  `DocketDriver` reads it on every turn (`edges/adapters/docket_runtime.py`,
  `get_isolation_enabled`): unless off, `bash` runs in the bwrap/docker jail and a turn fails
  closed when no backend is available (see security-gates.spec.md)
- `network <none|open>`: Record the global sandbox network mode (default open), audited as
  `gates.network`; any other value prints usage, exit 2. `none` cuts the jail's network and
  refuses turns that would run with isolation off (`network.refused`); `status` reports the mode
- `classes`: List the documented high-risk action classes (money-movement, prod-deploy,
  secret-access); read-only, makes no config changes. All three are now fully enforced by
  `core/tools.py`'s `dispatch_tool` (the only execution path since P19-7b) — see
  security-gates.spec.md v0.11.0 for why prod-deploy's `git`/`npm` overlap is no longer merely
  documented policy

Any other subcommand (including `enable`/`disable`, which do not exist) prints
`docket gates: unknown subcommand '<sub>'` plus the usage and exits 2; any flag after the
subcommand is an unrecognized flag (exit 2). There is no approval-routing flag to report or set.
**Output**: Gates status or update confirmation
**Return**: 0 on success; 1 when `isolate on` finds no usable sandbox backend; 2 on an unknown
subcommand or flag

#### docket audit
**Purpose**: Show recent recorded operator events, or verify the log's tamper-evidence chain
(see audit.spec.md for the exact recorded families and the coverage gap)
**Syntax**: `docket audit [N | verify] [--json]`
**Arguments**:
- `N` (optional): Number of recent entries to show (default: 20)
**Options/Actions**:
- `--json`: Emit the raw JSONL passthrough instead of a formatted table
- `verify` (ROADMAP Phase 15 G-4): Walk the current log's `seq`/`prev_hash` hash chain and report
  the first broken link, instead of listing entries
**Output**: Timestamped log of mutating operations, or a chain-verification result
**Return**: 0 always for the listing forms; for `verify`, 0 when the chain is clean (or no log
exists yet), 1 when a broken link is detected

`docket eval` (the specialist-role eval harness: structural checks + optional live golden
tasks) was **removed** (CL-J) — `tests/evals/` was dead code wired to the retired runtime and
skipped silently rather than failing, which is why the drift went unnoticed. Unlike
`docket workflow`/`docket team`, there is **no replacement command**: no CLI entry point runs a
single agent turn to repoint the harness at (`DocketDriver.run_turn` is only reached from pod
dispatch and `maintain distill`), so repairing it would mean inventing new surface against a
private port, not fixing a bug. (That was true when CL-J landed; since Phase 24, `docket harness
run` is such an entry point — see harness-mode.spec.md — but no eval harness was rebuilt on it.)
`eval` (and `evals`) are not registered commands — invoking one is an ordinary unknown-command
error (exit 2). `tests/evals/` and `cli/_eval.py` are deleted; `docket
doctor` no longer prints an eval-results advisory section. (The former eval.spec.md was removed
2026-08-04; ROADMAP decision CL-J is the durable retirement record.)

### Observability

#### docket trace
**Purpose**: View, tail, export, ingest, or expire agent-action JSONL traces
**Syntax**: `docket trace <session-id | subcommand> [args]`
**Subcommands**:
- `<session-id>`: Render one session's events human-readable
- `tail <project>`: Follow the most-recent open session live
- `export <project> [--since YYYY-MM-DD]`: Print raw JSONL to stdout
- `ingest <project>`: Project the active driver's session history (`core/session.py`, via
  `DocketDriver`) into the trace store — no daemon session-JSONL format left to parse
  (ROADMAP Phase 19 P19-7b)
- `expire [project] [--dry-run] [--days N]`: Delete TERMINATED trace files (one with a
  `session_end` event, real or the synthetic one `sweep_all` appends to a timed-out session)
  whose last event is older than the retention window. An OPEN trace (no `session_end` yet) is
  never deleted regardless of age — a live turn may still be appending to it. `--dry-run`
  previews what would be deleted without deleting anything or touching the ingest index.
  `--days N` overrides `TRACE_RETENTION_DAYS` (default 30) for one run. Omitting `[project]`
  sweeps every project. `audit.log` is out of scope — this command only ever touches
  `$TRACES_DIR` (`core/audit.py` is an intentionally separate, non-lossy record; see
  ROADMAP P22-6)
**Output**: Human-readable event log, raw JSONL, or an expiry summary (scanned/kept/deleted
counts and per-file detail)
**Return**: 0 on success, 1 if session not found

#### docket metrics
**Purpose**: Compute success rate, latency, cost, and guardrail trip counts
**Syntax**: `docket metrics [--role <role>] [--project <project>] [--window <N>]`
**Options**:
- `--role <role>`: Filter to a specific agent role
- `--project <project>`: Filter to a specific project
- `--window <N>`: Rolling window size in sessions (default: `METRICS_WINDOW`)
**Output**: Table of success rate, mean/p95 duration, total/mean cost, guardrail trips
**Return**: 0 always

#### docket policies
**Purpose**: Manage declarative guardrail policies
**Syntax**: `docket policies <subcommand> [args]`
**Subcommands**:
- `list [--pod <p>]`: List installed policies in `$POLICIES_DIR`, plus that pod's own policy
  directory when `--pod` is given (a pod's policies only ever add to the global set; ROADMAP
  P27-2); omitted, output is unchanged
- `show <name>`: Print one policy's JSON
- `init`: Copy the six baseline policies (block-destructive, prompt-injection,
  secret-pii-redact, high-risk-payment, high-risk-deploy, high-risk-credentials)
- `validate [name] [--pod <p>]`: Schema-check one installed policy, or every one; `--pod` also
  checks that pod's own directory
- `test <hook> <role> <text> [--tool <name>] [--pod <p>]`: Dry-run the evaluator (no traces
  emitted); `--pod` scopes the evaluation to that pod's own policies too
**Output**: Policy listing, JSON, or evaluation result
**Return**: 0 on success, 1 on invalid subcommand

#### docket plugins
**Purpose**: List operator-applied predicate plugins a policy's `when.plugin` can reach
**Syntax**: `docket plugins <subcommand> [args]`
**Subcommands**:
- `list [--pod <p>]`: Table (name, scope, file, sha256) of every predicate `core.plugins.discover`
  finds -- global (`$PLUGINS_DIR`) first, then that pod's own `config/plugins/` when `--pod` is
  given; `"No plugins applied."` when empty. Never lists a codebase's own `.docket/plugins/` --
  only the two applied scopes are ever searched
**Output**: Plugin listing, or an error naming an unknown/duplicate predicate
**Return**: 0 on success, 1 on invalid subcommand or a `PluginError`

#### docket recipes
**Purpose**: List and inspect the recipe library (ADR 0013 §1 rule 5) -- read-only discovery
over both scopes `core.pod_apply.resolve_recipe` reads. Installs, removes, or fetches nothing;
`docket pod <p> apply`/`docket init --recipe` remain the only writers
**Syntax**: `docket recipes <subcommand> [args]`
**Subcommands**:
- `list [--json]`: Table (NAME, SCOPE, BRINGS, DESCRIPTION) of every recipe `core.pod_apply.
  list_recipes()` returns -- the operator's own `$DOCKET_HOME/recipes/<name>/` before the
  shipped `templates/recipes/<name>/`, nearest scope wins by name, sorted by name. BRINGS is
  derived, never a stored field: the non-zero parts of the recipe's summary joined with `+` in
  summary order (`roles+members+pipeline+policies`, `policies`, `members+pipeline+skills`, ...;
  `nothing` for an empty directory). `--json` prints a list of objects carrying `name`, `scope`,
  `brings`, `directory`, `description`, and every `core.pod_apply.RecipeSummary` count
- `show <name|dir> [--json]`: Resolve *name|dir* through the same `resolve_recipe` order
  `docket pod <p> apply` uses and print its scope, directory, derived summary line
  (`pod-blueprints.spec.md` 1.14.0), one line per exporter the directory's `pod.yaml` names —
  the same state lines `docket pod <p> apply` prints, from `core.exporter.activation_state`
  (`pod-blueprints.spec.md` 1.20.0) — and `README.md` body when present; `--json` adds a
  `readme` field to the same object shape `list --json` prints
**Output**: Recipe listing, one recipe's detail, or the `resolve_recipe` error naming both
scopes' recipe names
**Return**: 0 on success, 1 on invalid subcommand or an unresolvable name, 2 on an unrecognized
flag

#### docket exporters
**Purpose**: List, inspect, and enable an observability export destination (`kind: exporter`
document, `core.exporter`) by authenticating -- the requested experience is "the YAML exists,
I only put the key" (observability-export.spec.md "Activation"); and show or change what an
exporter shares beyond bare structure, as a confirmed command
(observability-export.spec.md "Privacy commands and disclosure")
**Syntax**: `docket exporters <subcommand> [args]`
**Subcommands**:
- `list [--json]`: Table (NAME, DIALECT, STATE, CREDENTIALS, SCOPE, SHARES) of every catalog
  exporter, state from `core.exporter.activation_state`, SHARES its `privacy_label`; `--json`
  prints the same fields as objects (not including SHARES)
- `show <name> [--json]`: One exporter's effective document (dialect, endpoint, auth, enabled,
  state, aliases, privacy label), its scope, today's health counters, and a "Leaves this host"
  disclosure of every content class (`core.privacy.describe`: granted or not, its example
  attributes, and the fixed line naming that credentials and secret-shaped values are never
  sent); `--json` adds `missingCredentials` and the raw `health` record
- `enable <name> [--endpoint URL] [--privacy <level>|--share a,b] [--events ...] [--no-verify]
  [--yes]`: For each of *name*'s credentials that resolves to no value, prompts on a TTY and
  stores it (`docket keys add`'s own storage path), or on a non-TTY names `docket keys add
  <NAME>` per missing credential and exits 1 writing nothing. A `--privacy`/`--share` that
  widens what the exporter shares (`core.exporter.is_widening`) follows the same
  confirm-or-refuse rule as `docket exporters privacy`. Then probes the (possibly overridden)
  endpoint and classifies it exactly like `docket models provider add`; a transport failure
  exits 1 and writes nothing unless `--no-verify` is given. On success, writes only
  `{kind, name, enabled: true, <overrides given>}` to the global catalog through
  `core.exporter.enable_exporter` -- every other field is inherited from the built-in of the
  same name at read time -- and prints `shares: <label> (<classes, or "structure only">)`. The
  retired `--payload metadata|full` flag is no longer accepted
- `disable <name>`: Flip `enabled` to `false` in the global catalog; stored credentials are
  never touched
- `test <name>`: Re-probe the endpoint and print the classified result; exit 0 on a clean
  2xx, 1 otherwise
- `add <file.yaml> [--no-verify] [--yes]`: Register a full `kind: exporter` document, verified
  like `enable`; a document sharing beyond `minimal` follows the same widening rule, compared
  against any existing catalog entry of the same name
- `remove <name>`: Remove a global override; a built-in with none refuses naming it as built-in
- `export <name> [<file>]`: Print (or write) the exporter as a `kind: exporter` document --
  never a credential value, only credential names
- `privacy <name> [<level>|--share a,b] [--max-chars N] [--yes]`: With no level, `--share` or
  `--max-chars`, prints the same "Leaves this host" disclosure as `show`, writing nothing.
  Otherwise resolves the requested classes and compares them, via `is_widening`, against the
  exporter's presently effective classes: a widening prints each newly granted class with one
  example attribute and the destination host, then asks `y/N` on a TTY or exits 1 off one
  naming `--yes` and writing nothing (`--yes` skips the confirmation); a narrowing or equal
  change never asks. Writes only the changed field(s) through `core.exporter.set_privacy` and
  audits `exporter.privacy` (`name`, `from`, `to`, `host` -- never content)
- `preview <name> [--session <id>] [--level minimal|actions|conversation|full] [--share a,b]
  [--json]`: Project a real local session (default: the newest trace under `TRACES_DIR`,
  across every project) through *name*'s resolved `ExportPolicy` -- or the given `--level`/
  `--share` override, which is never written -- and print each span's attributes with their
  content class, content truncated to 200 characters for display, plus a footer counting spans,
  attributes per class, and total bytes; `--json` prints the exact `otlp_http.encode` document
  byte-for-byte. No network call, no write, no audit entry (observability-export.spec.md
  "Preview")
**Output**: Exporter listing, one exporter's detail, an enable/disable/test/add/remove/
privacy confirmation or refusal, or a preview of what a destination would receive
**Return**: 0 on success, 1 on an unknown exporter, a missing credential, an unreachable
endpoint, a refused widening, or (`preview`) an unknown session

#### docket approve
**Purpose**: Grant a pending HITL approval token
**Syntax**: `docket approve <token>`
**Arguments**:
- `token` (required): An `apr-*` token from docket's approval store (list pending with
  `docket approve` and no arguments). The store has **three** production producers since Phase 15
  G-1/G-2 and Phase 19 P19-3: pod-level/pipeline-step `require_approval` gates, a `pre_input`
  policy match at enqueue, and an in-turn `core/tools.py` tool-call gate. Since ROADMAP Phase 19
  P19-7b deleted the daemon outright, this is now the **only** approval system — the "daemon's
  own gate prompt, unbridged" caveat this line used to carry no longer applies to anything real
  (security-gates.spec.md v0.11.0)
**Output**: Approval confirmation
**Return**: 0 on success, 1 if token not found or already resolved

#### docket deny
**Purpose**: Deny a pending HITL approval token
**Syntax**: `docket deny <token>`
**Arguments**:
- `token` (required): An `apr-*` token from docket's approval store (same provenance note
  as `docket approve`)
**Output**: Denial confirmation
**Return**: 0 on success, 1 if token not found or already resolved

#### docket chat
**Purpose**: See and answer one task's parked question in the foreground (Phase 34, P34-13; see
operator-loop.spec.md "Answer surfaces")
**Syntax**: `docket chat <task-id> [--pod <project>]`
**Behavior**: Searches every pod for *task-id* (or just *pod* when given), then shows its brief,
its pending question (if any) and its earlier answers. On a TTY, a pending question is followed
by one prompt per `requestedSchema` property (a blank optional property is omitted; a blank
required one is passed through so the schema check itself reports it) and then answered through
`core.answers.answer_task(action="accept", channel="cli", actor=<OS user>)`. Off a TTY, or with no
pending question, this command only ever displays — use `docket pod <p> answer` to answer
non-interactively
**Output**: The task's status/brief/question/answers; an answer confirmation when one is sent
**Return**: 0 on success or a read-only display, 1 if *task-id* is not found, the answer is
blocked by a `pre_input` policy, or fails the question's own schema validation

#### docket inbox
**Purpose**: List everything across every pod that needs the operator, in one call (Phase 34,
D-50, ADR 0016; see operator-loop.spec.md "One inbox, derived")
**Syntax**: `docket inbox [--json] [--since <iso>] [--peek]`
**Behavior**: Derives, fresh on every call, a pure `InboxView` (`core/operator_contract.py`) over
every pod's tasks and pending approvals — `needsYou` (waiting/blocked tasks and pending
approvals), `failed`, `doneSince`, `running`. A plain call advances a durable cursor
(`~/.docket/inbox-cursor.json`) so a repeat call's `doneSince` only shows newly-terminal tasks
since the last call; `--peek` reads without advancing the cursor; `--since <iso>` overrides the
stored cursor for this one call without touching it either. `--json` emits the identical shape
`docket serve`'s `GET /inbox` and the MCP `inbox` tool return
**Output**: A human-readable summary by section, or (with `--json`) the bare `InboxView`
**Return**: 0 always — an empty inbox is not an error

#### docket channels
**Purpose**: Manage `kind: channel` documents — notification/conversation/decision destinations
(Phase 34, D-50, ADR 0016 §7; see operator-loop.spec.md "Notifications")
**Syntax**: `docket channels <list|show|enable|disable|add|remove|export|content|test> [args]`
**Actions**:
- `list [--json]`: Every catalog channel's dialect, enabled state, capabilities and content level
- `show <name> [--json]`: One channel's effective document and scope
- `enable <name> [--set k=v ...]`: Writes only the `enabled` flag plus the overrides given
  (`--set actors=a,b` sets the actors list, `--set secret=NAME` sets the credential name,
  anything else lands in `config`); refuses without writing while a required field the built-in
  names is still empty (`ntfy` needs a non-empty `topic`, `telegram` needs a non-empty `actors`)
- `disable <name>`: Turns it back off
- `add <file.yaml>` / `remove <name>`: Manage a full document
- `export <name> [<file>]`: Print or write one back out
- `content <name> [<level>] [--yes]`: Show or change how much a delivery carries (`minimal <
  actions < conversation`); widening prints the change and asks for confirmation on a TTY, or
  refuses off one without `--yes` — narrowing never asks
- `test <name>`: Sends one synthetic `dev.docket.channel.test` event through that one channel and
  reports success or failure — useful to verify a webhook URL or a command binary before relying
  on it. Every other subcommand here only edits the catalog; `test` and `docket notify` are the
  only things in this command group that ever send anything
**Output**: A table/document, or a confirmation
**Return**: 0 on success, 1 on an unknown channel, a missing required field on `enable`, or a
refused content widening

#### docket notify
**Purpose**: Flush operator events to every enabled channel (Phase 34, D-50, ADR 0016 §6; see
operator-loop.spec.md "Notifications")
**Syntax**: `docket notify flush [--dry-run]`
**Behavior**: `docket serve`'s sweep and `docket pod <p> dispatch` already flush after every real
state change; this command forces one in between, or previews it. With no `--dry-run`, diffs the
inbox against the last flush's saved snapshot, delivers each new event
(`dev.docket.task.*`/`approval.*`) to every enabled channel whose `on` matches, and prints the
delivered/failed/skipped counts. The snapshot is saved *before* delivering, so a crash mid-flush
never re-emits; a failed delivery is recorded in `~/.docket/docket-channels-health.json` and not
retried on the next flush (at-most-once, never at-least-once). `--dry-run` prints what would be
sent without delivering or advancing the snapshot
**Output**: Delivered/failed/skipped counts, or (with `--dry-run`) the same counts as a preview
**Return**: 0 always — nothing to deliver is not an error

### Identity & Conversations

#### docket persona
**Purpose**: Manage an agent's docket-owned cosmetic persona (display name/emoji rendered into SOUL.md)
**Syntax**: `docket persona <agent-id> <show|set "<label>"|clear>`
**Actions**:
- `show`: Print the current persona (if any)
- `set "<Name emoji>"`: Set/replace the persona (survives `maintain rebuild`)
- `clear`: Remove the persona (agent displays by role/id again)
**Output**: Persona confirmation or display
**Return**: 0 on success, 1 on error

#### docket conversations
**Purpose**: Inspect docket's durable conversation registry (pointers to channel threads; even
before ROADMAP Phase 19 P19-7b deleted the daemon outright, it kept no durable transcript of its
own — its per-agent sqlite was a rebuildable RAG index, not a transcript — so docket has always
owned this, and now there is no daemon at all to contrast it with)
**Syntax**: `docket conversations [list | show <id|agent-id> | resume <id|agent-id> | set <agent-id> <peer-id> [--topic] [--status] [--last] [--task]]`
**Actions**:
- `list` (default): Table of registered conversations (agent, channel, peer, status, topic)
- `show <id|agent-id>`: Print one conversation's fields
- `resume <id|agent-id>`: Mark in-progress and point at the agent's durable HEARTBEAT.md/memory
- `set <agent-id> <peer-id> [--topic] [--status] [--last] [--task]`: Upsert registry fields
**Output**: Registry table or confirmation
**Return**: 0 on success, 1 on error

### Telegram Commands

The Telegram binding commands are `docket wire` and `docket unwire`. There is no `docket
telegram` command or alias (it is an ordinary unknown-command error, exit 2).

#### docket wire
**Purpose**: Bind a channel group/peer to an agent (see telegram-integration.spec.md). With
`TELEGRAM_BOT_TOKEN` stored, docket shows a one-time `/wire <code>` command to send in the group
and discovers the group from it; manual numeric-ID entry is the fallback. (The daemon-era
log-scanning discovery, `scan_telegram_groups`, was removed by ROADMAP Phase 19 P19-7b.)
**Syntax**: `docket wire [agent-id] [--channel <name>]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Discovers (or prompts for) the group ID, records the binding in `fleet.json`, and
registers the thread in the conversation registry. The binding is inbound-only: it authorizes the
chat to use the four verbs `docket serve --telegram` answers; docket never messages it first.
There is no gateway-restart step: it was deleted outright, not kept as a no-op (CL-C, ROADMAP
Phase 19 wave 14).
**Return**: 0 on success, 1 if not found

#### docket unwire
**Purpose**: Remove an agent's channel binding
**Syntax**: `docket unwire [agent-id] [--channel <name>]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Unbind confirmation. No gateway-restart step (see `docket wire` above).
**Return**: 0 on success, 1 if not found

#### docket completions
**Purpose**: Emit a shell completion script for bash or zsh
**Syntax**: `docket completions <bash|zsh>`
**Arguments**:
- `bash` or `zsh` (required): Target shell
**Output**: Shell script — source with `eval "$(docket completions bash)"`
**Return**: 0 on success, 1 on invalid shell

### Help

#### docket help
**Purpose**: Show usage information
**Syntax**: `docket help [command]`
**Arguments**:
- `command` (optional): Show help for a specific command
**Output**: With no `command`, docket's full hand-written command reference. With a known
`command`, that command's own usage text (its `--help` output). With an unknown `command`,
a one-line error naming it.
**Return**: 0 for no `command` or a known `command`; 1 for an unknown `command`

## Output Formats

### Standard Output Structure

Messages go through the Rich helpers in `src/docket/ui.py`, which prefix a glyph rather than a
bracketed level:

- `→ text`: informational (`ui.info`, cyan)
- `✓ text`: operation completed (`ui.success`, green)
- `⚠ text`: warning (`ui.warn`, yellow)
- `✗ Error: text`: error (`ui.error`, red, on **stderr**); `ui.fail` prints `✗ text` on stderr

There is no debug output level.

### JSON Output Schema

When `--json` is specified, commands emit bare JSON objects or arrays — **no envelope wrapper**.
There is no `{success, data, error, version}` outer object. Each command's actual output shape
is documented in [specs/data/cli-json-shapes.spec.md](../data/cli-json-shapes.spec.md).

Key naming: camelCase throughout (`costUsd`, `totalUsd`, `budgetUsd`, `sessionKey`).

### Table Output Format

Default table uses column alignment:
- Left-aligned: text fields
- Right-aligned: numeric fields
- Center-aligned: status fields

## Environment Variables

The complete, code-derived table lives in the generated `docs/commands.md` ("Environment
Variables", checked by `scripts/gen_cli_docs.py --check`). The variables a CLI user most often
sets:

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCKET_HOME` | Base directory for all Docket-owned state | `~/.docket` |
| `DOCKET_LLM_BASE_URL` / `DOCKET_LLM_API_KEY` | Process-wide override of the OpenAI-compatible chat endpoint `DocketDriver` talks to (`edges/adapters/llm.py`'s `resolve_endpoint`) | (per-provider resolution) |
| `DOCKET_TOOL_MAX_OUTPUT_CHARS` | Ceiling on one tool result's text before visible truncation | `30000` |
| `DOCKET_NO_TRACE` | `1` disables trace-store writes | unset |
| `DOCKET_SERVE_TOKEN` | Fix `docket serve`'s Bearer token instead of generating one | unset |
| `EDITOR` / `VISUAL` | Editor for `docket edit` | `nano` |

There is no `DOCKET_DEBUG`, `DOCKET_NO_COLOR`, `DOCKET_MODEL_DEFAULT` or `DOCKET_EDITOR`.
`DOCKET_APPROVAL_MODE` is not an environment variable despite its name: it is a key of the `env`
dict `run_turn` receives (see harness-mode.spec.md), never read from `os.environ`.

## Return Code Convention

docket uses a deliberately flat convention — the printed message, not the exit code,
distinguishes error kinds:

| Code | Meaning | Used By |
|------|---------|---------|
| 0 | Success | All commands |
| 1 | Any failure (not found, invalid arguments, permission, driver/model error, …) | All commands |

Code `2` (SKIP, role not installed / live mode off) was the one surviving exception to this flat
convention, used only by the now-removed `docket eval` (CL-J). No command produces it anymore.

`docket harness run` is the one live exception, and it is deliberate. Its stdout is a wire protocol
that a caller outside this repository parses, so the exit code has to separate "the run happened and
ended badly" from "the run never started", which a printed message cannot do for a program:

| Code | `docket harness run` meaning |
|------|------------------------------|
| 0 | The turn completed; the final `result` line carries `status: "ok"` |
| 1 | The turn ran and ended `failed`, `blocked` or `cancelled` |
| 2 | Refused before any turn began: preflight rejected the environment, or the arguments were unusable. Exactly one `result` line with `status: "refused"`, no run record, no meta written |

`docket harness status` keeps the flat convention: 0 for any successful lookup, including `unknown`,
and 1 only for a missing token.

No other exit codes are produced by docket's own commands. Typer/Click's own usage errors (an
unknown option or command, before any command body runs — including every retired command name
and former alias) exit `2`. Commands that parse their own trailing arguments report the same
class of usage error with `2` too: an unrecognized flag (`find_unknown_flag`), an unknown
`docket gates` subcommand, or an unknown `docket context` action. (Earlier revisions of this
spec described codes 2–9 and 127 per failure kind; those were never implemented — removed in
v1.5.0.)

## Validation

Input validation rules that every command MUST enforce before performing side effects.
The authoritative rule set lives in [input-validation.spec.md](../validation/input-validation.spec.md);
the contract-level summary follows.

### Agent ID Validation
- Pattern: `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- Length: 3-50 characters
- Reserved IDs: manager, system, docket
- **Not enforced today** beyond `core/provisioning.py::slugify` — the length and reserved-id
  checks, and the path checks below beyond existence, have no implementing function (see
  input-validation.spec.md's Status; open maintainer decision)

### Path Validation
- Must be absolute or tilde-expanded
- Must exist (for codebase paths)
- Must be readable

### Model Validation
- Must be well-formed `provider/model-id` (e.g. `anthropic/claude-sonnet-4-6`)
- docket does not itself validate that the named model exists at the provider; it accepts any
  well-formed string and warns if pricing is unknown (an unresolvable model surfaces as a
  driver-level error the first time a turn actually runs, not at validation time)
- Tier names (`economy`, `standard`, `premium`) are **not accepted** — removed in 0.2.0 (D-2 exit); they hard-error like any other malformed input (see input-validation.spec.md)

### Numeric Validation
- Budget values: non-negative USD (`profile --budget`)
- History window: positive days (`cost --history --days N`)
- Timeout values: 1-3600

## Interactive Features

### Project Picker
When agent-id is omitted for commands that need it:
1. Show a numbered menu (there is no fzf integration)
2. Allow typing ID directly

### Confirmation Prompts
Required for destructive operations:
- `docket delete` — type the exact pod (or agent) id to confirm; there is no `--force`
- `docket maintain` reset/rebuild, `docket models reset`

Format: `Continue? [y/N]: ` for the y/N prompts; `Type the ... id to confirm [<id>]: ` for deletes

## Foreground dispatch progress and in-place approval

### Rendering

`docket pod <project> dispatch` (and `docket pipeline run`, which drives the same function) MUST
render one line per event on stderr while the dispatch runs, whenever stderr is a real TTY or
`--progress` is given:

- `session_start` → `▶ <role> …`
- `approval_requested` → `⏸ <role> wants: <action> · token <token> · denies in <n>s · docket
  approve <token>`, where `<n>` is `TOOL_APPROVAL_TIMEOUT` minus the elapsed time since the event
- `approval_required` (the hop-level gate) → `⏸ <role> hop needs approval · token <token> ·
  docket approve <token>`
- `session_end` → `■ <role> finished — status=<status>`

No other trace event type renders a line. Without a TTY and without `--progress`, no worker
thread runs, no trace subscription opens, and stdout/stderr MUST stay byte-identical to a build
with no progress view (the no-change oracle the golden suite pins).

### In-place approval

When the rendering above is active, stdin is also a real TTY, and `--no-prompt` is absent, every
`approval_requested` event additionally prints `[a]pprove  [d]eny  [Enter] keep waiting` and reads
one line from stdin. `a` MUST call `core.approval.approval_grant(token, channel="cli")` then
`core.dispatch.resolve_waiting_approval(token, "granted")`; `d` MUST call the same pair with
`approval_deny`/`"denied"` — the identical pair `docket approve`/`docket deny` use, so an in-place
answer is indistinguishable from a second terminal's. Any other input (including a bare Enter)
keeps waiting. A token already resolved through another channel (`ApprovalNoop`) prints one dim
notice and the prompt keeps waiting on the next event; it MUST NOT raise out of the dispatch call.

### Flags

- `--progress` forces the rendering above even when stderr is not a TTY.
- `--no-prompt` disables the in-place prompt even when stdin is a TTY; rendering is unaffected.

Neither flag applies to `docket harness run` or a non-interactive dispatch caller (`serve
--dispatch`, a due schedule, the MCP `dispatch` tool) — this section governs only the foreground
CLI path (`cli/_pod.py::_pod_dispatch`, `cli/_progress.py`).

## Error Message Standards

### Format
One `ui.error` line on stderr (`✗ Error: <what failed>`), optionally followed by a usage or
recovery hint line, then `typer.Exit(1)`. There is no multi-line Details/Suggestion block.

### Example
```
✗ Error: Project key required. Usage: docket scope <agent-id> set <project-key>
```

## Performance Requirements

### Response Times
- Simple queries (list, info): < 500ms
- Creation operations: < 2s
- Deletion operations: < 1s
- Repair operations: < 5s
- Cost calculations: < 3s for 30 days

### Resource Limits
- Max JSON parsing: 10MB
- Max memory log: 100MB
- Max agents: 1000

## Backwards Compatibility

### Version Detection
- Docket's supported state root is `~/.docket` (or `DOCKET_HOME`). It does not import state from a
  retired runtime; the first `docket init` writes a Docket-owned home.

### Retired Names
- docket carries no backward-compatibility layer for its own CLI: no alias table, no
  retired-command notices, no deprecated no-op flags. A command name docket used to have
  (`install`, `setup`, `reset`, `repair`, `cleanup`, `model`, `team`, `workflow`, `eval`,
  `auth`, …) or a former alias (`show`, `rm`, `telegram`, …) is an ordinary unknown command
  (exit 2). Package installation belongs to the package manager; first-project initialization
  bootstraps global state lazily.
- Direct JSON editing → Use docket commands

## Changelog

### Unreleased

- `docket doctor` (human and `--json`) probes the docker jail image for `git` when docker is the backend in use and warns with `DOCKET_SANDBOX_IMAGE=<an image with git>`.
- `docket doctor` (human and `--json`) shows unjailed MCP servers (isolate: false) from global and per-pod registries with pod context.
- `docket config explain` adds `isolate` field to each MCP server, with human marker for unjailed servers.
- `docket recipes show --json` and `recipes list --json` include `unjailed_mcp_servers` field.
- `docket pod <project> worktrees prune [--dry-run] [--force]`: new action (`core.pod_provisioning.prune_task_worktrees`).

### Version 1.61.0 (2026-10-05)

Phase 38 close (P38-9, ADR 0020): the entries below were Unreleased and are now this version.

- `docket mcp servers add` gains `--no-isolate` (ADR 0020 §5; `mcp-client.spec.md` Requirement 40).
- **P38-4.** `docket gates network none|open`; `status`, `doctor` and `config explain` report the
  network mode and its scope.

- **P38-3.** `docket gates` isolation is on by default; `isolate on` probes `sandbox_availability`
  (bwrap or docker) instead of `docker` on PATH; `docket doctor` reports the backend.

### Version 1.60.0 (2026-10-04)

Phase 36 close (P36-10): the entries below were Unreleased and are now this version.

- **P36-4.** `docket pod <project> evidence <task-id> [--json]`: new action over `core.evidence`. No version
  bump.

### Version 1.59.0 (2026-10-03)

- **Legacy compatibility removed (no users; maintainer decision 2026-10-03).** `__main__.py`
  no longer carries `_REMOVED` (retired-command notices) or `_ALIASES`; `main()` only invokes
  the Typer app. Every retired command name (`team`, `workflow`/`wf`, `eval`/`evals`, `auth`,
  `reset`, `repair`, …) and former alias (`show`, `rm`, `remove`, `telegram`, `key`, `secret`,
  `log`, `usage`, `check`, `security`, `export`, `completion`, `policy`) is an ordinary unknown
  command (Click, `No such command`, exit 2). Installed Distribution, the `auth`/`workflow`/
  `team`/`eval` paragraphs, Telegram Commands and Backwards Compatibility rewritten accordingly.
- Removed: the hidden global `--debug` (now an unknown option, exit 2) and the hidden `_json`
  command; `init --path` (use `--codebase`); `maintain --distill-first` (distillation stays the
  default; the flag is now an unrecognized flag, exit 2); `audit`'s positional `--json` (the
  `--json` option stays; syntax now `docket audit [N | verify] [--json]`).
- `docket gates`: `enable`/`disable` and `--force` are gone with the approval-routing flag they
  wrote; `status` reports the gate and isolation only; an unknown subcommand prints an error plus
  usage and exits 2.
- `docket context`: an unknown action now exits 2 instead of falling through to `show`.
- The interactive picker is a numbered menu only (fzf was never invoked); doctor's checks list
  drops the stale-model check and names the `docket-models.json` entry check instead, and its
  footer points at `docket maintain [id] check`; `docket snapshot` output has no `gateway` field.
- Return Code Convention states that pass-through usage errors (unrecognized flag, unknown
  `gates` subcommand or `context` action) exit 2 like Click's own.

### Version 1.58.0 (2026-09-29)

- **Closes the known gap 1.57.0 left open.** `docket inbox`, `docket channels`, `docket notify`
  and `docket pod <p> explain interruptions`/`pregrant` (Phase 34, D-50, ADR 0016) now have full
  entries in this spec — all five were real, shipped commands with no coverage here since the
  cards that built them.

### Version 1.57.0 (2026-09-29)

- **Phase 34, D-50, ADR 0016.** `pod <p> delegate` gains `--brief FILE.json` and `pod <p>
  answer` (P34-13); the corrected version below states a valid brief now actually enqueues
  (a post-close integration fix wired `enqueue_task`'s `brief=` parameter through, see
  operator-loop.spec.md's changelog). New `docket chat <task-id>` command (P34-13). New
  "Foreground dispatch progress and in-place approval" section (P34-4): `docket pod <p>
  dispatch` renders trace events on a TTY or `--progress`, with an in-place `[a]pprove/[d]eny`
  prompt, `--no-prompt` to disable it, and a byte-identical no-TTY/no-flag oracle.
  **Known gap, not closed by this pass:** `docket inbox`, `docket channels`, `docket notify`,
  `docket pod <p> pregrant` and `docket pod <p> explain interruptions` are real, shipped
  commands (`docs/commands.md`, operator-loop.spec.md areas 5/6/9) with no coverage in this
  spec yet — flagged for a follow-up card rather than backfilled here.

- **`docket exporters privacy` and `docket exporters preview`.** The exporters entry gains
  both actions; `enable` takes `--privacy <level>|--share a,b` and no longer `--payload`;
  `add` and `enable` follow the widening confirmation rule.

### Version 1.55.0 (2026-09-27)

- **`pod apply`/`recipes show` report exporter state, never activate one.** `pod.yaml`'s
  `apply` action now also accepts `exporters`; the non-`--json` plan prints one line per named
  exporter after the plan (`exporter <name>: enabled` / `needs credential <names> -> docket
  exporters enable <name>` / `disabled -> docket exporters enable <name>`), from
  `core.exporter.activation_state` (`cli/_pod.py::render_exporter_states`, shared by
  `render_apply_plan` and `docket recipes show`); nothing is written to
  `docket-exporters.json`. `export` writes this pod's recorded `exporters` list back into
  `pod.yaml` when set. See `pod-blueprints.spec.md` 1.20.0 and `config-format.spec.md` 1.5.0.

### Version 1.54.0 (2026-09-27)

- **Added `docket exporters`**: `list`/`show`/`enable`/`disable`/`test`/`add`/`remove`/`export`
  over the exporter catalog (observability-export.spec.md "Activation"). `enable` prompts for a
  missing credential on a TTY, else names `docket keys add <NAME>` and refuses writing nothing;
  a reachable endpoint activates the exporter with a minimal patch document, everything else
  inherited from the built-in at read time. `docket config explain <agent>` gains an
  `exporters` array (name, dialect, state, scope, credential source, payload, health counters)
  and a rendered `Exporters:` block; `docket doctor`'s Checks list gains a per-enabled-exporter
  health check naming `docket exporters test <name>` on a recorded failure.

### Version 1.53.0 (2026-09-27)

- **`docket recipes list` shows what a recipe brings, not a one-word kind.** The derived
  column is `BRINGS`: the non-zero summary parts joined with `+` (`roles+members+pipeline+
  policies`, `policies`, ...), and the JSON field is `brings`. A one-word `kind` could not tell
  a methodology recipe (members plus a pipeline) from a team, so it was the declared-scope
  drift ADR 0013 §1 rule 1 refuses, by another name. `summarize_recipe`'s line renders
  `pipeline none` when no pipeline resolves (`pod-blueprints.spec.md` 1.19.0).

### Version 1.52.0 (2026-09-27)

- `docket config explain <agent>` gains `skills`: every skill a live turn's `# Skills` prompt
  section would list, `name` and its scope (`codebase | pod | global`), one human line
  (`Skills:          security-review (pod)` / `none`). See `agent-loop.spec.md` 1.24.0 for the
  composition itself (P31-6, ADR 0013 §3 rule 8) and `cli-json-shapes.spec.md` 1.14.0 for the
  exact `--json` shape.

### Version 1.51.0 (2026-09-27)

- **P31-2: `docket recipes list|show`, and the operator's own recipes directory (ADR 0013 §1
  rules 4-5).** New `docket recipes` command, registered exactly as `docket plugins` is: `list
  [--json]` (a table of every recipe `core.pod_apply.list_recipes()` returns, its scope, a
  derived `brings` composition, and its description) and `show <name|dir> [--json]` (one recipe's scope,
  directory, derived summary, and README body); an unresolvable name exits 1 naming both
  `operator:`/`shipped:` recipe lists. `core.pod_apply.resolve_recipe` gains a third scope, the
  operator's own `config.user_recipes_dir()` (`$DOCKET_HOME/recipes/<name>/`), checked before
  the shipped library — nearest wins by name. See `pod-blueprints.spec.md` 1.17.0 and
  `workspace-structure.spec.md` 1.13.0.

### Version 1.50.0 (2026-09-27)

- `docket config explain <agent>` gains `projectInstructions`: the effective project-instructions
  files and their source (`AGENTS.md` composed by default when unset and present at the codebase
  root, an operator's explicit list, or none), one human line beside `Config source:`
  (`Project instr.:   AGENTS.md (default)` / `... (set)` / `none`). See `agent-loop.spec.md`
  1.23.0 for the default itself (P31-5, ADR 0013 §3 rule 7) and `cli-json-shapes.spec.md` 1.13.0
  for the exact `--json` shape.

### Version 1.49.0 (2026-09-27)

- **P31-1: a recipe says what it brings.** `docket validate <dir>` prints a derived `summary:`
  line (and the directory's own `description`, when set) after its per-file lines; a file target
  is unchanged. `docket pod <project> apply` and `docket init --recipe`/a discovered `.docket/`
  print the same header — the description (when set) then the summary line — before the plan,
  through the shared `cli/_pod.py::render_apply_header`. `pod.yaml` gains an optional
  `description` string. See `pod-blueprints.spec.md` 1.14.0 and `config-format.spec.md` 1.3.0.

### Version 1.48.0 (2026-09-27)

- `docket pod <project> apply [<name|dir>]`: the argument resolves a shipped recipe by name
  when no directory exists at that path, through the same `core.pod_apply.resolve_recipe`
  `docket init --recipe` uses, so a recipe's own README can print a command with no path into
  the installed package. See `pod-blueprints.spec.md` 1.13.0.
- `docket init`'s closing `created with N members` line and member list count the pod as it
  stands after the apply step: a member added by a present `.docket/` or `--recipe` is counted
  and listed (it was previously the blueprint roster only).

### Version 1.47.0 (2026-09-27)

- `docket roles list` drops the `EDIT` column: `editRights` is retired (Phase 30, D-46, ADR
  0012 §2 rule 7). `docket roles show`'s wire-format dump no longer prints `editRights` either.
  See `role-archetypes.spec.md` 1.19.0 for the schema-level change (P30-4).

### Version 1.46.0 (2026-09-27)

- `docket pod <project> export [<dir>] [--force]`: `<dir>` is now optional, defaulting to
  `<codebase>/.docket` like `apply`; the non-empty-directory refusal now also covers that
  default. `docket config explain <agent>` gains `configSource`, `configDigest`, and a
  recomputed `drift` (`"yes"`/`"no"`/`""` with no recorded source) reporting this pod's
  configuration of record (P30-2, ADR 0012). See `pod-blueprints.spec.md` 1.12.0, "Pod
  manifests: apply" requirement 6 and "Pod manifests: export" requirements 1 and 3, and
  `cli-json-shapes.spec.md` for the exact `docket config explain --json` shape these three
  fields join.

### Version 1.45.0 (2026-09-27)

- `docket init` gains `--recipe <name|dir>` and `--no-apply` (ADR 0012, D-46, P30-1): a present
  `<location>/.docket/` is now discovered, validated, and applied automatically after
  provisioning, the same directory shape and path `docket pod <p> apply` already reads (see
  pod-blueprints.spec.md 1.11.0, "Pod manifests: apply" requirement 8); the readiness rule (a
  callable endpoint before the first pod) is unchanged.

### Version 1.44.0 (2026-09-27)

- `docket doctor`'s Checks list gains the global provider catalog (`docket-providers.json`): a
  malformed entry is named with the file and the failing field, carried the same way under
  `--json`. See `model-profiles.spec.md` 2.15.0 ("Provider catalog" requirement 7) for this and
  the matching `config explain --json` `provider` block (P29-6).

### Version 1.43.0 (2026-09-27)

- `docket models`: added the five `provider` actions (`add <file.yaml>`, the `add <name>
  <base-url> [--opts]` shortcut, `list`, `show [--json]`, `remove`, `export`), replacing the
  `add`-only surface. Registration now probes with the resolved credential and classifies the
  result instead of a boolean; `preset <name>` no longer requires a separately registered block
  for `anthropic`/`openai`/`google` and prints a readiness line after applying (P29-3).

### Version 1.42.0 (2026-09-27)

- `docket auth` is **retired** (Phase 29, D-45): the `#### docket auth` section is gone, replaced
  by a removed-command paragraph next to `docket keys` -- every `docket auth <anything>` prints
  the `_REMOVED` notice and exits 1, with no `status`/`login`/`key`/`setup`/`--provider` survivor.
  `docket keys`'s note now says `keys` is the only model-auth credential path, and that `setup`
  walks the provider catalog in catalog order (api-keys.spec.md 1.6.0).

### Version 1.39.0 (2026-09-26)

- `docket pod <project> export <dir> [--force]`: now writes the short form throughout, each
  file starting with a `# yaml-language-server:` header, a role's instructions moved to a
  paired `roles/<name>.md`, `pod.yaml` gaining `kind: pod`/`name`, and the four config-v1 JSON
  Schemas copied into `.schemas/` (`core/pod_apply.py`, P28-8). See `config-format.spec.md`,
  "Published schemas"/"Short-form export", and `pod-blueprints.spec.md`, "Pod manifests:
  export".
### Version 1.38.0 (2026-09-26)

- New `docket plugins list [--pod <p>]` (`cli/_plugins.py`, `core/plugins.py`): lists every
  predicate a policy's `when: {plugin: ...}` can reach -- global (`$PLUGINS_DIR`) then a pod's
  own `config/plugins/`, by name, scope, file, and sha256. See `security-gates.spec.md`'s
  "Predicate plugins" section for the discovery scope, the fail-closed evaluation, and the
  `docket pod <p> apply` copy step.

### Version 1.36.0 (2026-09-26)

- New `docket validate [dir|file]` (`cli/_validate.py`, `core/config_docs.py`): validates a
  role, pipeline, policy, or pod document by resolving its `kind:` and dispatching to the
  parser that already owns that kind, printing `ok <file> (<kind> <name>)` or the error for
  every file under a directory, invalid ones first. See `config-format.spec.md` for the
  envelope, the deprecation path for a document with no `kind:`, and the `ConfigDocError`
  format.

### Version 1.35.0 (2026-09-26)

- `docket pod <project> export <dir> [--force]`: new action writing this pod's own scope
  (`core/pod_apply.py::export_pod`, P27-7) into the same directory shape `apply` reads back —
  the write direction "Pod manifests: apply" deferred. See `pod-blueprints.spec.md`, "Pod
  manifests: export", for the exported shape and the round-trip proof.

### Version 1.34.0 (2026-09-26)

- `docket doctor`'s Checks list documents the per-pod `config/` overlay check
  (role archetypes and policy files, alongside the existing global-only checks) —
  see `cli-json-shapes.spec.md` 1.11.0 for the matching `config explain --json`
  `scope` labeling this wave also ships (P27-8).

### Version 1.33.0 (2026-09-26)

- `docket pod <project> apply [<dir>] [--dry-run] [--json]`: new action composing a recipe's
  existing writers into one command (`core/pod_apply.py`, P27-6). See `pod-blueprints.spec.md`,
  "Pod manifests: apply", for the manifest shape and validation contract.

### Version 1.32.0 (2026-09-26)

- `docket mcp` entry: `servers add` gains `--kind read|write` (default `write`) and `--tools
  NAME,...` (default: all); `servers list` shows both. A bad `--kind` value exits 1 naming the
  field. Full contract in `mcp-client.spec.md` 1.5.0 (Requirements 32-33).

### Version 1.31.0 (2026-09-26)

- `docket policies list|validate|test` accept `--pod <p>`, folding that pod's own policy
  directory into the files considered — a pod's policies only ever add to the global set
  (security-gates.spec.md 0.25.0, P27-2). Omitted, `docket policies list`'s output is
  byte-identical to before.

### Version 1.30.0 (2026-09-26)

- **P27-1: a pod has its own role overlay.** `docket roles list/show/add` gain `--pod <p>`,
  resolving (and, for `add`, writing) against that pod's own role overlay, which resolves
  nearest-wins above the global user overlay — see role-archetypes.spec.md's "User registry
  overlay". `docket roles validate` is unchanged; it has no pod-specific overlay concept.

### Version 1.29.0 (2026-09-25)

- The installed console script resolves `docket.__main__:main`, so aliases and removed-command notices behave as under `python -m docket`; `docket help <command>` prints that command's usage and exits 1 for an unknown command (W37-C3).

### Version 1.28.0 (2026-09-21)

- Global Options: `--debug` is a deprecated, hidden no-op (still accepted, sets nothing); it used to set `DEBUG=1` that nothing read (W36-C9). `docket models` no longer claims prices can be overridden in `docket-models.json`.

### Version 1.27.1 (2026-09-18)

- Truth pass against the live Typer registry (`docket <cmd> --help`) and `src/docket/ui.py`.
  Global options are `--help`, `--version`/`-V`, `--debug` only (no `-h`/`-v`/`-d`/`--quiet`/
  `--config`/`--no-color`). Corrected shipped flags for `list`/`info` (`--json` only), `delete`
  (no `--force`/`--keep-logs`; typed-id confirmation), `doctor` (`--json`/`--fix`; exit 0/1, not an
  issue count), `cost` (`--json`/`--history`/`--days`), and `serve` (added `--telegram`,
  `--token-file`, and the authenticated routes). Added the missing `keys rotate`, `policies
  validate` (six baseline templates, not three), `mcp servers`, and a Command Registry entry for
  `docket harness`. `gates isolate` is consumed by `DocketDriver` on every turn (W18-3), not
  "recorded only". `docket wire` discovers the group from a one-time `/wire` command with manual
  fallback, and the bot exists (P19-8). Replaced four environment variables that do not exist
  with real ones and pointed at the generated table in `docs/commands.md`. Output/error formats
  now describe the real glyph prefixes; Return Code Convention notes Typer usage errors exit 2.

### Version 1.27.0 (2026-09-18)

- Releases `0.2.0-beta.3`; artifact metadata and `docket --version` report its PEP 440 form
  `0.2.0b3`.

### Version 1.26.0 (2026-09-18)

- `docket pod <project> dispatch` and `docket pipeline run` exit `1` when any task in the dispatch
  ends `failed`, matching the run record's `failed` state and the flat convention's "any failure"
  row. Before, only an exception exited `1`, so `docket pod x dispatch && git push` proceeded past
  a failed task. `blocked` and `waiting_approval` still exit `0`.
- Pod output prints bracketed identifiers, descriptions and failure reasons literally. They were
  passed through terminal markup, which silently erased every `[<task-id>]` and `[<role>]` and
  would raise on model text containing a closing tag.

### Version 1.25.0 (2026-09-12)

- W30-C5 records `docket harness run`'s three-code exception to the flat return convention. The
  command's stdout is a wire protocol, so a consumer needs the exit status to distinguish a turn
  that ran and ended badly from one that never started; a printed message cannot carry that.
  `docket harness status` stays flat.

### Version 1.24.0 (2026-09-07)

- W29-C7 excludes the repository-only Homebrew formula from the release sdist, preserving one
  reproducible source-archive digest for the formula to verify.

### Version 1.23.0 (2026-09-07)

- W29-C7 releases `0.2.0-beta.2`; artifact metadata and `docket --version` now report its PEP
  440-equivalent version from both the wheel and sdist.

### Version 1.22.0 (2026-08-31)

- W26-C10c makes the cancellation lifecycle explicit in human `runs list`/`runs show` output and
  defines `runs cancel` as a durable request rather than premature terminal completion.

### Version 1.21.0 (2026-08-30)

- Defined the root distribution contract: standards-compliant wheel and sdist,
  artifact-only `docket` command checks, aligned version/license/project metadata,
  and clean uninstall boundaries.

### Version 1.20.0 (2026-08-30)

- Made first initialization fail closed when the selected model has no callable endpoint, and
  required provider registration to reject unreachable endpoints without persisting them.
- Clarified that coding-tool subscriptions do not supply Docket runtime credentials; the supported
  no-key acceptance path is a registered local OpenAI-compatible endpoint.

### Version 1.19.0 (2026-08-25)

- Added the `ai-gateway`/`local` preset and the previously omitted `models provider add` action.
- Corrected `keys` to the real central model-auth path, documented format-only validation and
  least-privilege workspace sync, and added `AI_GATEWAY_API_KEY`.

### Version 1.18.0 (2026-08-19)

- Bare `docket` is now a compact, state-free command guide. Added `docket status` for the current
  directory's project and `docket status --all` for a global one-row-per-project summary, keeping
  `list` as the agent inventory and `doctor` as workstation health.

### Version 1.17.0 (2026-08-19)

- Simplified the lifecycle to two user-facing verbs: `init` lazily creates the workstation
  foundation and the current project's minimum isolated pod, while `add` adds role agents to an
  existing pod. `doctor` deliberately reports the global fleet and labels it accordingly.

### Version 1.16.0 (2026-08-19)

- W21-C1 daemon-free truth pass: removed retired-runtime commands, paths, and variables from the
  current CLI contract while preserving the clean-break decision in ROADMAP/Git history.

### Version 1.15.0 (2026-08-04)

- **ROADMAP P22-6 — trace retention.** Docket's trace JSONL becomes a cache rather than the
  only copy once an external consumer durably ingests trace events (P22-3), which makes
  deleting old trace data safe rather than lossy — the reasoning P20-3's deferred retention
  half was waiting on. Added `docket trace expire [project] [--dry-run] [--days N]`
  (`core.trace.expire_old_traces`), age-bounded by the new `TRACE_RETENTION_DAYS` config
  constant (default 30 days). Reuses `sweep_all`'s liveness reasoning: only a trace with a
  `session_end` event is eligible, so an open/still-writing session is never deleted
  regardless of age. Deletion keeps the per-project `.ingest-index.json` consistent by
  dropping any removed session_id's offset entry. `audit.log` is explicitly out of scope —
  see `core/audit.py`. `docket serve`'s periodic sweep does not call this yet — wiring
  `trace.expire_old_traces()` alongside the existing `trace.sweep_all()` call in
  `serve.py::_run_sweeps` is tracked as follow-up, not shipped by this card.

### Version 1.14.0 (2026-08-04)

- **CL-J — `docket eval` removed.** The specialist-role eval harness (`tests/evals/`) was dead
  code wired to the deleted OpenClaw daemon, and — unlike `docket workflow`/`docket team` —
  has no successor command. Removed the "docket eval" section under Security and Gates in
  favor of a removed-command paragraph; dropped exit code `2` (SKIP) from the Return Code
  Convention table, the one surviving exception to the flat `0`/`1` convention. `docket eval`/
  `docket evals` now print a removed-command notice and exit 1.

### Version 1.13.1 (2026-08-04)

- **CL-C (ROADMAP Phase 19, wave 14 dead-code sweep).** `restart_gateway()`/`RestartResult` and
  every ceremonial call site across `cli/` (`docket wire`/`unwire`, `docket keys add/remove/
  rotate/sync`, `docket profile`, `docket scope set/reset`, `docket models set/preset/reset`,
  `docket pod ... add/remove`, `docket add`/`delete`) are deleted outright, not kept as a no-op
  stub — the prior version's "still runs... but is now a no-op" phrasing on `docket wire`/
  `docket unwire` is corrected accordingly. `gateway_active()` (and the `gateway` field it backs
  in `docket snapshot`'s output, line ~463) is unchanged — it has real external consumers (the
  `serve` read API) that `restart_gateway()` never had.

### Version 1.13.0 (2026-08-03)

- **ROADMAP Phase 19 P19-7b — the OpenClaw daemon is deleted; truth-passed every command
  section that still described it.** `edges/adapters/openclaw.py` (the ACL), every `openclaw`
  binary shell-out, `openclaw.json`, and the daemon's own auth-profiles concept are gone
  outright — no compatibility layer, no migration (D-19). Fixed: `docket install`/`docket auth`
  (already corrected mid-cycle, kept as-is), `docket gates` (no more "writes to openclaw.json";
  it now manages only `fleet.json`'s approval-routing/isolation posture, per `cli/_gates.py`),
  `docket doctor`'s Checks list (no more "OpenClaw daemon status"; the real `_doctor_json()` key
  set), `docket logs` (no more "today's gateway entries" — no gateway log left to scan),
  `docket eval --live` ("against the configured model endpoint", not "the daemon"), `docket
  trace ingest` (projects the active driver's session history via `DocketDriver`/
  `core/session.py`, not daemon session-JSONL), `docket wire`/`docket unwire` (manual peer/group
  ID entry only — log-based Telegram group auto-discovery, `scan_telegram_groups`, is deleted
  along with the gateway log it read; `restart_gateway()` is now an honest `status="no_daemon"`
  no-op kept only for call-site compatibility), `docket context`'s semantic-search note (named as
  a real gap, not attributed to a runtime that no longer exists), `docket conversations`'s
  purpose line, the Environment Variables table (`DOCKET_HOME` default is `~/.docket`, not
  `~/.openclaw`; replaced the fictional `OPENCLAW_API` row with the real
  `DOCKET_LLM_BASE_URL`/`DOCKET_LLM_API_KEY` override `edges/adapters/llm.py`'s
  `resolve_endpoint` reads), and Backwards Compatibility's "Version Detection" (rewritten to
  state D-19's actual no-migration policy instead of a fictional config-migration step). Several
  of these sections (`--config` default, `docket pod delegate`'s queue path, `docket roles add`'s
  overlay path, the error-example path) were already corrected earlier in this cycle and are
  unchanged here.

### Version 1.12.0 (2026-07-31)

- **Removed `docket context` actions that no longer exist.** `search`, `snapshot`, `index` and
  `compress` were documented here as live surface; `cli/_context.py` implements only `show` and
  `project` (any unrecognized action falls through to `show`), and the CHANGELOG's Unreleased
  "Removed" entry records their deletion along with the `SNAPSHOT.md` artifact. Noted that
  semantic memory search is the openclaw runtime's job and that folding logs into `MEMORY.md` is
  `docket maintain <id> distill`.
- **Corrected nine fictional exit codes.** Eight commands (`info`, `delete`, `scope`, `context`,
  `edit`, `logs`, `wire`, `unwire`) documented `2 if not found`, and four documented a `4 on
  invalid ...` case. Neither code is reachable: every not-found path in `cli/__init__.py` raises
  `typer.Exit(1)` (verified live for `info`/`context`/`scope`/`logs`/`edit`), and the only two
  `typer.Exit(2)` sites in the tree are inside the hidden internal `_json` bridge. There is no
  `typer.Exit(4)` anywhere. Version 1.11.0 corrected exactly this defect for `maintain` and
  described the result as "the real 0/1 convention every other command in this spec already
  uses" -- that was not true when written, which is precisely how the remaining nine survived.
- **Corrected the `docket approve` note.** It still said docket's approval store "has no
  production producer yet". It has had two since Phase 15: G-1's pod-level and pipeline-step
  `require_approval` gates, and G-2's `pre_input` policy match at enqueue. The separate point --
  that the daemon's own gate prompts do not mint these tokens, and that G-5 found no practical
  bridge -- is still true and is kept.

### Version 1.11.0 (2026-07-30)

- ROADMAP Phase 17 C-2 (memory distillation, decision D-18): documented the new `docket maintain
  distill` mode and the `--distill-first` (default)/`--no-distill-first` option pair on
  `clean`/`reset`. Corrected `maintain`'s stale `Return` line (`2 if not found, 4 on invalid mode`)
  to the real 0/1 convention every other command in this spec already uses, and noted the new
  fail-closed exit-1 case: a distillation turn that fails (no daemon, model error, timeout) aborts
  the whole `clean`/`reset`/`distill` invocation before any file is touched.

### Version 1.10.0 (2026-07-30)

- ROADMAP Phase 16 W-4 (durable scheduling + event triggers): documented `docket pipeline run`'s
  new `--follow` flag — streams new trace events for the dispatched project to stdout while it
  runs on a background thread, rather than only the final summary (see pipeline-format.spec.md /
  serve-read-api.spec.md for the webhook/schedule side of this card). Documented that `docket
  runs show` also surfaces a webhook-triggered run's resolved pipeline `variables`, and that a
  genuine `docket runs cancel` now writes a `runs.cancel` audit entry (audit.spec.md) — the one
  gap left when W-2 shipped cancellation.

### Version 1.9.0 (2026-07-30)

- ROADMAP Phase 16 W-2 (executor) / W-8 (generalized gates): documented the new `docket pipeline
  validate|plan|run` command (the docket-native pipeline format's first CLI surface — see
  pipeline-format.spec.md/pod-dispatch.spec.md) and the new `docket runs cancel <id>` action
  (kills an in-flight hop's process group; see pod-dispatch.spec.md's "Cancellation"). `docket
  workflow` is unchanged and continues to serve the Lobster dialect until ROADMAP Phase 16 W-3
  retires it in favor of `docket pipeline`.

- ROADMAP Phase 16 W-7 (pod blueprints): rewrote the `docket add` section — replaced the stale
  `--type <repo|task>` option (the field was removed from the schema in an earlier truth pass but
  this section was missed) and the never-implemented `--description <text>` option with the real
  `--blueprint <name>`/`--codebase`/`--path`/`--name` flags, documented `--pod full`/`--with`'s
  software-blueprint-only scope, and documented the extended `--from <file>` (a `blueprint` field
  per entry). Fixed this section's Return line to the real flat 0/1 convention (it still described
  the fictional 3/4 codes v1.5.0 removed everywhere else in this file). Renamed the generic
  `codebase-path` argument-table row to `location` (meaning depends on the blueprint's
  `workspaceKind`) and updated its existence rule accordingly. See the new `pod-blueprints.spec.md`
  for the full blueprint contract.

- ROADMAP Phase 16 W-3 (D-16): retired `docket workflow` (the Lobster YAML surface) — replaced
  the "Workflow Commands" / `docket workflow` section with a "Pipeline Commands" section
  documenting the removed-command notice, the same treatment `docket team` got under D-11.
  Removed `workflow` from the `action` argument table row and the now-meaningless "Max workflows
  per agent: 100" resource limit.

### Version 1.8.0 (2026-07-30)

- ROADMAP Phase 16 W-6 (declarative role archetypes): documented the new `docket roles
  list/show/add/validate` command — see role-archetypes.spec.md for the registry it manages.
- ROADMAP Phase 18 L-3: added the `docket mcp serve` section — the new MCP (Model Context
  Protocol) stdio server exposing docket's control plane as tools. Full contract in the new
  `mcp-server.spec.md`.

### Version 1.7.0 (2026-07-30)

- ROADMAP Phase 14 R-8 spec truth pass for the R-1…R-6 CLI surface changes: added the new
  `docket runs list/show` command; documented `docket pod <project> dispatch`'s `--resume`
  (crash recovery) and `--timeout` (independent turn/verify override) flags and its now-real
  budget auto-pause / Reviewer-rework / worktree-`verifyCmd` gates; documented `docket pod
  <project> queue --retry <task-id>` (the explicit way to un-block a single `blocked` task) and
  `set-verify`'s validation + audit logging; documented `docket profile --resume`; documented
  `docket audit verify`.

### Version 1.6.0 (2026-07-30)

- Phase 18 L-2: documented the new `--provider <name>` option on `docket auth
  login/key/setup` (defaults to `anthropic`) — previously the provider was hardcoded and
  unconfigurable; generalized the section's "Claude model provider" wording to "model
  provider" to match.

### Version 1.5.0 (2026-07-30)

- Truth pass (Platformization baseline): replaced the fictional per-kind return codes (2–9,
  127) with the real flat 0/1 convention (+ `eval`'s documented SKIP=2) and fixed every
  per-command return line that cited them; corrected `docket gates` to on-by-default and
  aligned `gates classes` wording with security-gates.spec.md's honest enforcement scope;
  scoped `docket audit`'s purpose to the actually-recorded families; corrected
  `docket approve`/`deny` token provenance (docket's approval store — which has no production
  producer until Phase 15 — not "from approval_create or Telegram"); removed the phantom
  `docket telegram` command section (it is a silent argv alias of `wire`); added the missing
  `docket persona` and `docket conversations` sections (shipped commands with zero spec
  coverage); removed `team` from the live argument table and retargeted the retirement note
  at ROADMAP D-11 / pod-dispatch.spec.md; fixed stale numeric-validation rows (reset level,
  cost period) and the `--model <tier>` option example.

### Version 1.4.0 (2026-07-02)
- FD-6 spec truth pass for Phase 13's FD-1/FD-2/FD-3 cards: added the public `--verify "<cmd>"`
  option on `docket pod <project> add` and the `set-verify <member-id> "<cmd>"` action (FD-1,
  previously only settable via the internal `meta-set` debug command); noted `dispatch`'s budget/
  verify/Tester-PASS-FAIL gates and cross-referenced the new `pod-dispatch.spec.md` for the full
  state machine (FD-2); added `docket gates classes` (FD-3's read-only high-risk-class listing).

### Version 1.3.0 (2026-07-02)
- CH-10 spec truth pass: fixed the version header (was stuck at 1.0.0 while this changelog
  had already reached 1.2.0). Replaced the "Team Commands" / `docket team` section — retired
  in 0.2.0 (D-11), no dispatcher, never executed — with a "Pod Commands" / `docket pod`
  section documenting the real, executing delegation surface (list/add/remove/delegate/
  queue/dispatch). Added `validate`/`plan` to the `docket workflow` actions and fixed its
  return-code claim to the real plain `0`/`1` contract. Fixed the model-validation tier claim:
  tier names are rejected outright (0.2.0, D-2 exit), not accepted with a warning.

### Version 1.2.0 (2026-06-26)
- Replaced tier argument (`economy|standard|premium`) with `provider/model` — tier names are now deprecated aliases only
- Updated `docket install` flags: removed removed `--clean`/`--skip-agents`/`--profile`; added `--portfolio` and `--gates`
- Updated `docket add`: replaced `--model <tier>` with `--pod full`, `--with <roles>`, and `--from <file>`
- Added `--dispatch` to `docket serve`
- Fixed `docket team` action set: removed `status`, added `start` and `cancel`
- Fixed `docket models preset` list: removed deprecated `economy` alias
- Corrected `DOCKET_MODEL_DEFAULT` description: value is a `provider/model` string, not a tier name
- Removed "Phase 8" label from Observability section heading
- Updated model validation rules to describe `provider/model` format and tier deprecation

### Version 1.1.0 (2026-06-09)
- Synced the command registry with the shipped CLI
- Replaced retired `reset`/`repair`/`model` with `maintain` and `mode`
- Added `context`, `edit`, `logs`, `snapshot`, `serve`, `wire`, `unwire`, `help`
- Corrected the `team` action set and return-code usage

### Version 1.0.0 (2024-01-20)
- Complete CLI interface specification
- All commands documented
- Return codes standardized
- Validation rules defined
