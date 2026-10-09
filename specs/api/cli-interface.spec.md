# CLI Interface Contract Specification

**Version**: 2.1.2
**Status**: Complete
**Last Updated**: 2026-10-08

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
report a PEP 440-equivalent form of declared version `0.2.0-beta.4`, Python
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

The per-command entries in the Command Registry are the authoritative source for each
command's exact syntax.

## Arguments

Positional arguments are command-specific; the following conventions apply across commands:

| Argument | Applies to | Rules |
|----------|------------|-------|
| `<ref>` | `task show|diff|trace|approve|deny|answer|retry|cancel` | A full task id, the short id `task list` prints, a unique prefix, or a run id (`core/task_ref.py`); never omitted, never picked from a menu |
| `MEMBER` | `pod show|remove|reset`, `pod set|unset --member` | MUST match `^[a-z0-9][a-z0-9-]*[a-z0-9]$`; a member of the resolved pod |
| `KEY VALUE` | `pod set|unset` | A `PodSettings` key, or `verify` with `--member` |
| `location` | `init` | MUST be absolute or tilde-expanded. For a `codebase`-kind blueprint (`software`) MUST exist and be readable; for a `workdir`-kind blueprint (`research`/`content`/`ops`) docket creates it if absent |
| `provider/model` | `setup model set`, `exec --model` | MUST be well-formed `<provider>/<model-id>`; `setup model set` also accepts the literal `default` |
| `NAME` | `setup provider|notify|export|mcp` verbs, `pod recipes|roles|policies` | A catalog or document name; an unknown one exits 1 |

Unrecognized or excess positional arguments are a usage error (exit 2). No command takes a positional pod id; the pod comes from Pod targeting below.

## Options

Options are `--long` flags, some with a `-short` alias. The global options listed above are
accepted by every command; command-specific options are listed per command in the Command
Registry. Conventions:

- Boolean flags default to `false` and take no value (e.g. `--force`, `--json`).
- Value options take exactly one argument (e.g. `--model <provider/model>`, `--days <N>`).
- `--help` MUST be honored before any other parsing and exit 0 (`-h` is the same option at every level).
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
| --help | -h | Show help message | - |
| --version | -V | Show version info | - |

These two are the whole global surface (`docket --help`); `-h` is declared once on the root
and every child command inherits it, so `docket task show -h` equals `docket task show --help`.
There is no `-v`, `-d`, `--debug`, `--quiet`, `--config` or `--no-color` (any of them is an unknown option, exit 2);
state location is chosen with `DOCKET_HOME`, not a config file flag.

### Pod targeting

Every pod-scoped command resolves its pod through `cli/_target.py::resolve_pod`, from three
sources in this order: the `--pod`/`-p` option (declared by `pod_option()`), then the `DOCKET_POD`
environment variable, then the registered pod whose codebase contains the current directory.
When several registered codebases contain it, the deepest wins; two pods matching at the same
depth are both named in the error. `docket status` and every `docket pod` verb use it.

When no pod matches, the command prints one error line and exits 1:

```
No pod for <cwd> (looked for a registered codebase containing it). Run 'docket init' here, or pass --pod <name>.
```

## Command Registry


Eleven commands, in the order `docket --help` shows them (Daily: `init`, `status`, `inbox`,
`task`, `run`; The pod: `pod`, `log`; Machine: `setup`, `start`, `stop`, `exec`). Each top-level
command has one section below with every verb it owns. A name that is not one of the eleven, or
a verb a group does not have, is an ordinary unknown-command usage error (exit 2).


Invoking `docket` with no command **MUST** print only a compact guide of three parts, in this
order: the tagline (`ui.TAGLINE`), the five daily commands with one-line meanings (`docket init`,
`docket task add "..."`, `docket run`, `docket status`, `docket inbox`), and the line
`Not set up yet? docket setup`. It is rendered by `ui.guide` and **MUST NOT** read or render the
fleet, project agents, costs, bindings, or health checks.

#### docket init
**Purpose**: Provision a project pod from a blueprint (Lead + Implementer against a codebase by
default — see pod-blueprints.spec.md, ROADMAP Phase 16 W-7). It **MUST NOT** bootstrap the
workstation-wide home beyond creating the directories it needs; the endpoint, the baseline
policies and the security posture belong to `docket setup`.
**Syntax**: `docket init [project] [location] [--blueprint <name>] [--pod full] [--with <roles>] [--codebase <path>] [--name <text>] [--from <file>] [--recipe <name|dir>] [--no-apply]`

`init` provisions the pod's own members and no shared agent. Its arguments and options are
declared on the command (`cli/_agents.py::cmd_init`), so `docket init --help` lists each with
its meaning and `setup shell` completes them; the command builds one `InitRequest` and
`run_init` provisions from it. An option it does not define, a `--pod` value other than `full`,
`--from` combined with any other argument or option, or a third positional is a usage error:
it prints one line and exits `2` before anything is provisioned. The help is one screen: the
default team, the `.docket/` discovery and `--recipe`, one `Example:`; the blueprint rosters
and the `--from` file format live in pod-blueprints.spec.md, not in the help.

When `docket setup`'s readiness report (`cli/_setup.py::readiness()`) shows no model endpoint
(the selected role models do not resolve to a callable OpenAI-compatible endpoint; an API key
without a compatible endpoint is not ready), `init` still builds the team and ends with
`⚠ No model endpoint yet` and the single next step `docket setup`. A registered local endpoint
passes without a key.
**Arguments**:
- `project` (optional): Project name / pod identifier (slugified to `^[a-z0-9][a-z0-9-]*[a-z0-9]$`);
  omitted defaults to the current directory name
- `location` (optional): Meaning depends on the selected blueprint's `workspaceKind` — a codebase
  path for `software` (the default), or a working directory for `research`/`content`/`ops`
  (auto-provisioned if omitted)
**Options**:
- `--blueprint <name>`: Select a pod blueprint (`software` | `research` | `content` | `ops` |
  `agentic-product`); omitted defaults to `software`. An unknown name fails
  cleanly (exit 1) before any prompt is shown
- `--codebase <path>`: The location, as an option instead of the second argument
- `--name <text>`: The pod's name, as an option instead of the first argument; an option wins
  over its positional
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
  resolved `--recipe`; prints the `docket pod apply <dir>` command that would apply it

A repository's own `<location>/.docket/` (the same directory shape `docket pod apply` reads,
see pod-blueprints.spec.md, "Pod manifests: apply") is discovered automatically: `init` validates
every document under it before provisioning anything, and — unless `--no-apply` is given — applies
it after provisioning through the same `plan_apply`/`apply` path `docket pod apply` uses. A
validation error exits 1 naming the file and field, with nothing provisioned.
**Output**: Creation progress and confirmation with member IDs. The closing `created with N
members` line and the id list that follows it count every member of the pod as it stands after
the apply step, so a member a present `.docket/` or `--recipe` added is counted and listed.
When no enabled channel delivers beyond the console, the summary ends with
`core.channel.unreached_warning`'s text; on a TTY with a desktop session it then asks
`Enable desktop notifications now? [Y/n]` and, on yes, enables `desktop` and sends one test
notification (operator-loop.spec.md Notifications 17). Off a TTY it only warns
**Return**: 0 on success, 1 on error (pod already exists, invalid arguments, unknown blueprint,
or provisioning registered no member — docket's flat convention, see Return Code Convention below)

With no explicit project or location, `init` **MUST** derive both from the current working
directory without an interactive questionnaire. The intended first-run flow is package-manager
installation followed directly by `docket init` once per project. Declarative `--from`
provisioning belongs to `init`, including multi-project automation.

#### docket status
**Purpose**: Show where a pod stands — tasks, tokens, outcomes, the last run — or every pod.
**Syntax**: `docket status [--all] [--json] [--history] [--days N] [--pod <name>]`
**Behavior**:
- With no flag, resolve the pod (`--pod`, `DOCKET_POD`, then the most-specific initialized pod
  whose `codebase`/`workDir` contains the current directory) and report its path, members, task
  counts (including waiting approval, waiting input, failed and "approved, ready"; a pod with a
  `waiting_input` task is `waiting`), the `Isolation:` sandbox posture (the same string as JSON
  `isolation`: `on (bwrap, network open)` or `off (default); bwrap found, network open`), measured tokens with a labelled dollar
  estimate, the success/failure/aborted counts and latency from trace `session_end` events, the
  last run, and whether `docket start` is running (its `serve.pid` names a live process).
- `--all` reports the same summary for every registered pod, once per project rather than once
  per agent, with failed counts; `--all --json` also carries the fleet inventory
  (`timestamp`, `channels`, `agents`, `totalCostUsd`).
- `--history [--days N]` shows tokens per day (empty against the production driver; see
  cost-tracking.spec.md "Known gap").
- No current-directory match **MUST** fail with an actionable `docket init`/`--all` message.
- `docket setup --fix` remains workstation-wide technical health. It is not an implicit side effect
  of `status` or bare `docket`.
**Return**: 0 on success, 1 when current-project resolution fails, 2 on an unknown flag.

#### docket inbox
**Purpose**: List everything across every pod that needs the operator, in one call (see
operator-loop.spec.md "One inbox, derived")
**Syntax**: `docket inbox [--json] [--since <iso>] [--peek]`
**Behavior**: Derives, fresh on every call, a pure `InboxView` (`core/operator_contract.py`) over
every pod's tasks and pending approvals — `Needs you` (waiting/blocked tasks, pending approvals
and "approved, ready" tasks), `Failed`, `Done`, `Running`. A plain call advances a durable
cursor (`~/.docket/inbox-cursor.json`) so a repeat call's `Done` only shows newly finished tasks;
`--peek` reads without advancing it; `--since <iso>` overrides the stored cursor for this one
call without touching it. Each item prints the exact `docket task approve|deny|answer <id>` (or
`retry`, `run`) command and the full held command or question, never truncated. `--json` emits
the `GET /inbox` shape with `state` and `command` added to every item.
**Output**: A human-readable summary by section, or (with `--json`) the bare `InboxView`
**Return**: 0 always — an empty inbox is not an error; 2 on an unknown flag

#### docket task
**Purpose**: Queue a pod's tasks, read each one's whole story (status, hops, evidence, runs,
corrections, interruption forecast, worktree, diff and trace) and move one forward: grant or
refuse what it waits on, answer its question, retry it or stop it
**Syntax**: `docket task <add|list|show|diff|trace|prune|approve|deny|answer|retry|cancel> [args] [--pod <p>]`
A `<ref>` is a full task id, the short id `task list` prints, a unique prefix, or a run id
(`core/task_ref.py`); an unknown or ambiguous ref exits 1 and an ambiguous one lists every
candidate with its pod. Without `--pod`/`DOCKET_POD` a ref is searched in every pod.
**Verbs**:
- `add "<text>" [--priority high|normal|low] [--brief FILE.json] [--pod <p>]`: Queue the task on
  the resolved pod's own list (`~/.docket/workspaces/<project>-lead/TASK_LIST.json`). The text is
  one argument; empty text or text over 500 characters exits 1, an unknown priority exits 2.
  `--brief` loads and validates the file as a `TaskBrief` (operator-v1); an invalid one exits 1
  and enqueues nothing, a valid one is passed to `core.dispatch.enqueue_task(brief=)`. Prints the
  one-line interruption forecast (`core.interruptions.NOTHING_WILL_ASK`, or `May ask you: ...`
  naming `docket task show`) and ends with `Next: docket run`
- `list [--json] [--pod <p>]`: The pod's queue, every status: short id, priority, status, cost,
  the worktree path when one exists, description. `--json` prints `{"pod", "tasks": [...]}`
  (`cli-json-shapes.spec.md`)
- `show <ref> [--json] [--pod <p>]`: Status, hop evidence (evidence-v1, `core.evidence`), the
  runs that worked the task, its corrections, and the interruption forecast (what could pause
  it: matching `require_approval` policies, pipeline approval and `input` steps,
  `requireApprovalRoles`, the resolved `approvalMode`, the always-on high-risk classes, notifying
  channels). A task with a recorded, unpruned worktree also prints its path, branch, base commit
  and the exact `git -C <path> diff <base>` and merge commands; a task that ran in place prints no
  worktree block. A `run-` ref resolves its task and exits 1 when the run failed
- `diff <ref> [--pod <p>]`: Print `git diff <base>` of the task's worktree
  (`edges/adapters/system.py::git_diff`); a task without a worktree, or a failed diff, exits 1
- `trace <ref> [--tail] [--export] [--json] [--pod <p>]`: The task's trace
  (`$TRACES_DIR/<project>/agent:<project>:<task-id>.jsonl`), one line per event with the tool
  name on `tool_call` lines; `--tail` follows until a `session_end` event and then returns;
  `--export` prints the raw JSONL; `--json` prints `{"pod", "events": [...]}`. A task with no
  trace exits 1
- `prune [--dry-run] [--force] [--yes] [--traces] [--days N] [--pod <p>]`: Remove the worktrees of
  the pod's finished (`done`/`failed`/`cancelled`) tasks, deleting each branch merged into the
  codebase's current branch and recording `worktree.prunedAt`. Dirty or unmerged ones are kept
  and reported with the reason; `--force` (confirmed, or `--yes` off a TTY) removes them anyway
  (the unmerged branch stays) and audits it (`pod.worktrees.prune`). `--traces` also deletes
  TERMINATED trace files of the pod past `TRACE_RETENTION_DAYS` (an OPEN trace is never deleted)
  and terminal run records past the same window; `--days N` overrides it and without `--traces`
  exits 2. `--dry-run` changes nothing. Ends with `Next: docket task list`
**Output**: Every bracketed identifier and every task description or failure reason is printed
literally, never interpreted as terminal markup
**Return**: `0` on success, `1` on error (no pod, unknown or ambiguous ref, invalid input)

**`task approve | deny | answer | retry | cancel`**
The answering verbs (operator-loop.spec.md "Answer surfaces", pod-dispatch.spec.md "Cancellation"):
**Syntax**:
- `docket task approve <ref> [--reason TEXT] [--once|--task] [--for "<command>" [--tool bash]] [--pod <p>]`
- `docket task deny <ref> [--reason TEXT] [--pod <p>]`
- `docket task answer <ref> [text...] [--option <id>] [--field name=value]... [--decline] [--pod <p>]`
- `docket task retry <ref> [--pod <p>]`
- `docket task cancel <ref> [--pod <p>]`
**Arguments**:
- `ref` (required): a task id, its short id, a unique prefix, or a run id (`core.task_ref.resolve_task`);
  every pod is searched unless `--pod` or `DOCKET_POD` names one. `approve` and `deny` also
  accept an `apr-*` token as given, for an approval no task carries. The approval store has
  three production producers (pod-level/pipeline-step `require_approval` gates, a `pre_input`
  policy match at enqueue, an in-turn `core/tools.py` tool-call gate) and is the only approval
  system
**Behavior**:
- `approve` resolves the task's pending approval from its own `approvalToken` and grants it
  (`channel="cli"`); a task that is not `waiting_approval` exits 1. `--task` also allows the
  same call for the rest of the task; `--once` is the default and conflicts with `--task` (exit
  2). `--for` records a single-use pre-grant for one exact command ahead of dispatch instead
  (`core.interruptions.record_pregrant`) and conflicts with `--task`
- `deny` denies the same approval; the task fails with `approval_denied` and, when `--reason`
  was given, `reason: approval denied: <reason>` (what the inbox's Failed entry shows)
- `answer` answers the parked question through `core.answers.answer_task`; on a TTY with no
  text, field or option it prompts, off a TTY it exits 1 naming `--option`
- `retry` calls `core.dispatch.retry_task` (a `failed` or `blocked` task goes back to `pending`,
  audited `task.retry`)
- `cancel` requests cancellation of the task's live run (`core.runs.cancel_run`, which writes
  one `runs.cancel` audit entry and kills every tracked process group) and settles a stale
  `running` claim as `failed` (`core.dispatch.reclaim_stale_running`)
**Output**: One confirmation line. `approve`, `answer`, `retry` and `--for` end with the run
hint: `docket is running and will pick it up` when `docket start` is running, else
`Next: docket run --pod <p>` on stderr, for a task ref and for an `apr-` token alike; `cancel` ends with `Next: docket task retry <id>` when it
settled a stale claim
**Return**: 0 on success (an approval already in the requested state is a warning, exit 0); 1 on
an unknown or ambiguous ref, a task in the wrong state, an approval already resolved the
opposite way, a blocked or invalid answer, or a `cancel` with nothing in flight; 2 on a usage
error

#### docket run
**Purpose**: Run a pod's pending tasks through its pipeline, one real agent turn per hop.
**Syntax**: `docket run [--resume] [--timeout S] [--progress] [--no-prompt] [--pipeline FILE]
[--var k=v]... [--dry-run] [--pod <name>]`
**Behavior**: see pod-dispatch.spec.md "CLI entry: `docket run`". `--dry-run` prints the plan and
starts nothing; `--resume` reclaims stale claims and clears a budget auto-pause; `--pipeline
FILE` runs a pipeline file instead of the pod's own (pipeline-format.spec.md); repeatable
`--var k=v` supplies its variables. With no model endpoint it exits 1 naming `docket setup`.
**Output**: the banner of runnable steps, one line per task, one summary line, one `Next:` line.
**Return**: `0` on success or an expected pause, `1` when a task ended `failed`, the run record
ends `failed`, the pod is unknown or no endpoint is configured, `2` on an unknown flag.

#### docket pod

**Purpose**: The pod: its roster, its settings and its configuration of record
**Syntax**: `docket pod <show|add|remove|reset|set|unset|delete|apply|export|validate|plan|check|recipes|roles|policies> [args] [--pod <p>]`

A real Typer sub-app (`cli/_pod.py::pod_app`): every verb declares its arguments and options, a
bare `docket pod` prints help, an unknown verb or flag is a usage error (exit 2), and every leaf's
help ends with an `Example:` line. Each verb resolves its pod through `--pod`/`-p`,
`DOCKET_POD`, then the current directory (Pod targeting above); there is no positional pod id.
Each state-changing verb ends with one `Next:` line on stderr.

- `show [MEMBER] [--json]`: the pod, or one member's whole effective configuration
  (agent-lifecycle.spec.md "Pod Information"; the JSON shapes are `docket pod show --json` and
  `docket pod show <member> --json` in cli-json-shapes.spec.md). Read-only, no `Next:` line.
- `add ROLE [--count N] [--verify "<cmd>"]`: add members to the existing pod; never creates a
  project. `--verify` is implementer-only (warned and ignored otherwise). An unknown role prints
  one line and exits 1; a second Lead is refused.
- `remove MEMBER [--yes]`: remove one member. Confirms on a terminal; off one it exits 1 naming
  `--yes`. The Lead is refused ("delete the pod instead").
- `reset MEMBER [--yes]`: distill the member's memory, clear it and rebuild its workspace files
  from metadata; a failed distillation exits 1 with nothing deleted (agent-lifecycle.spec.md
  "Member Reset").
- `set KEY VALUE [--member ID]` / `unset KEY [--member ID]`: the one writer of every
  `PodSettings` key (`budgetUsd` included); `verify` with `--member` writes or clears an
  implementer's `verifyCmd` (pod-blueprints.spec.md "Pod settings: set and unset").
- `delete [--confirm NAME]`: destroy the pod. The name is typed on a terminal; off one,
  `--confirm NAME` is required. A member id is refused; there is no picker.

**Return**: `0` on success, `1` on any refusal or error (unknown pod, member or role; Lead
removal; missing confirmation; failed distillation), `2` on a usage error.

**`pod apply`**
**Purpose**: Install configuration onto the pod, or re-sync its instructions
**Syntax**: `docket pod apply [NAME|DIR|FILE] [--dry-run] [--json] [--pod <p>]`
**Arguments**:
- `NAME|DIR|FILE` (optional): a directory (`roles/*.yaml`, `policies/*`, `pipeline.yaml`, a small
  `pod.yaml` naming `members`/`settings`/`pipeline`/`description`/`exporters`) or, failing that, a
  recipe name resolved exactly as `docket init --recipe` resolves it (an unresolvable name exits
  1 naming both scopes' recipes), is planned and written whole; an existing file is one `kind:
  role` or `kind: policy` document installed into the pod's own scope (any other kind exits 1);
  with no argument, members whose stored template version is stale are re-rendered from the
  current archetype and metadata (`INSTRUCTIONS.md` is never touched)
**Options**: `--dry-run` prints the plan or the diffs and writes nothing; `--json` prints `{"items":
[{kind, name, action, note}]}` (exit 1 with no argument)
**Output**: For a directory or recipe: a header (`Apply plan`, the directory's `description` when
set, `core.pod_apply.summarize_recipe`'s derived summary line), one `[action] kind: name` line per
item, then one line per named exporter — its state from `core.exporter.activation_state` and,
unless `enabled`, the exact `docket setup export enable <name>` command; nothing is ever written
to `docket-exporters.json` from this path. Validates every role, the roster the pipeline would
resolve against once `members` join, every setting, and every `exporters` name before writing
anything; idempotent (a second run plans every item `skip`). A state-changing run ends with `->
Next: docket pod show`. See `pod-blueprints.spec.md`, "Pod manifests: apply"
**Return**: 0 on success, 1 on an invalid document, an unresolvable name, or no pod

**`pod export`**
**Purpose**: Write the pod's own configuration into a directory
**Syntax**: `docket pod export [DIR] [--force] [--pod <p>]`
**Output**: This pod's own scope, every YAML file in the short form with a `# yaml-language-server:`
header — pod-overlay `roles/<name>.yaml` (+ paired `roles/<name>.md` instructions), this pod's
own `policies/<stem>.yaml`, a bound `pipeline.yaml` copy (if any), a `pod.yaml` naming `kind: pod`,
`name`, non-Lead `members`, every non-default `setting`, this pod's recorded `exporters` (when
set), and the four config-v1 JSON Schemas copied into `.schemas/` — into `DIR`, the same shape
`apply` reads back. `DIR` defaults to `<codebase>/.docket`. Global scope (the operator's own role
overlay, fleet-wide policies, other pods) is never exported. Refuses a non-empty `DIR` (including
the default) unless `--force`. Ends with `-> Next: docket pod validate <DIR>`. See
`pod-blueprints.spec.md`, "Pod manifests: export"
**Return**: 0 on success, 1 on a refusal or no pod

**`pod validate`**
**Purpose**: Validate any configuration document — role, pipeline, policy, pod manifest, MCP
server — or every document in a directory (see `config-format.spec.md`); one validator for every
kind (`core.config_docs.validate_path`)
**Syntax**: `docket pod validate [PATH]`
**Arguments**:
- `PATH` (optional): A directory to validate every document under (default `<cwd>/.docket`
  when it exists, else the current directory), or a single file to validate alone
**Output**: One line per file — `ok <file> (<kind> <name>)` on stdout, or its error on stderr —
invalid files first, plus a warning per file loaded without a `kind:` key. A pipeline whose step
`model` names a provider absent from the catalog is invalid. A directory target also prints,
after the per-file lines, `core.pod_apply.summarize_recipe`'s derived summary line
(`pod-blueprints.spec.md` 1.14.0) and the directory's own `description` when its `pod.yaml` sets
one; a file target prints neither
**Return**: 0 if every file is valid, 1 if any file is invalid or the target does not exist

**`pod plan`**
**Purpose**: Show the steps the pod's pipeline would run, from the real executor
(`core.orchestrator.resolve_plan`/`render_plan`) — never a second, drift-prone pretty-printer. See
`pipeline-format.spec.md` for the file format and `pod-dispatch.spec.md` for how it runs
**Syntax**: `docket pod plan [--pipeline FILE] [--pod <p>]`
**Options**: `--pipeline FILE` plans that file (validated like `pod validate`, a document with no
`kind:` accepted as a pipeline) instead of the pod's bound or default pipeline
**Output**: A header, `Source: <where the pipeline came from>`, and the rendered plan; nothing
executes and no tokens are spent
**Return**: `0` on success; `1` on an invalid or missing file or an unresolvable pod

**`pod check`**
**Purpose**: Would the pod's rules allow this? A dry run of the evaluator (no traces emitted)
**Syntax**: `docket pod check TEXT --role R [--hook pre_input|pre_tool_call|pre_output] [--tool
NAME] [--arg key=value]... [--pod <p>]`
**Options**: `--hook` defaults to `pre_tool_call`; `--tool` (default `bash`) names the built-in
tool simulated — an `exec`-kind tool is judged by the command classifier plus the policy hook,
exactly like the live gate, any other kind by the policy hook alone; `--arg` (repeatable) supplies
the call arguments a rule's `when:` can test
**Output**: Hook, role, text, `Result:` (`allow`, `ask`, `deny`, `warn`, `redact`, ...), the
classifier's reason when it decided, and the deciding policy id
**Return**: `0` with a verdict; `2` on an unknown hook or tool or a missing `--role`

**`pod recipes`**
**Purpose**: List and inspect the recipe library (ADR 0013 §1 rule 5) -- read-only discovery
over both scopes `core.pod_apply.resolve_recipe` reads. Installs, removes, or fetches nothing;
`docket pod apply`/`docket init --recipe` remain the only writers
**Syntax**: `docket pod recipes [NAME|DIR] [--json]`
**Output**: With no argument, a table (NAME, SCOPE, BRINGS, DESCRIPTION) of every recipe
`core.pod_apply.list_recipes()` returns -- the operator's own `$DOCKET_HOME/recipes/<name>/` before
the shipped `templates/recipes/<name>/`, nearest scope wins by name, sorted by name. BRINGS is
derived, never a stored field: the non-zero parts of the recipe's summary joined with `+` in
summary order (`roles+members+pipeline+policies`, `policies`, `members+pipeline+skills`, ...;
`nothing` for an empty directory). With an argument, the recipe resolved through the same
`resolve_recipe` order `docket pod apply` uses: its scope, directory, derived summary line
(`pod-blueprints.spec.md` 1.14.0), one line per exporter its `pod.yaml` names — the same state
lines `docket pod apply` prints (`pod-blueprints.spec.md` 1.20.0) — and `README.md` body when
present. `--json` prints a list of objects carrying `name`, `scope`, `brings`, `directory`,
`description`, `unjailed_mcp_servers` and every `core.pod_apply.RecipeSummary` count; with an
argument one such object plus a `readme` field
**Return**: `0` on success, `1` on an unresolvable name, `2` on an unrecognized flag

**`pod roles`**
**Purpose**: List the role archetypes a pod can use, or show one in full (role-archetypes.spec.md)
**Syntax**: `docket pod roles [NAME] [--json] [--pod <p>]`
**Output**: With no argument, one row per archetype (name, scope, model source, denied tools);
with a name, that role's effective document, pod overlay included when the pod has one.
`--json` prints the same as objects. Read-only, no `Next:` line
**Return**: `0` on success, `1` on an unknown name or no pod when a pod overlay is needed, `2` on a usage error

**`pod policies`**
**Purpose**: List the guardrail policies in force, or show one; the predicate plugins a rule's
`when.plugin` can reach are a section of the listing
**Syntax**: `docket pod policies [ID] [--json] [--plugins] [--pod <p>]`
**Arguments**:
- `ID` (optional): print that policy's JSON
**Options**: `--plugins` adds the predicate plugins `core.plugins.discover` finds — global
(`$PLUGINS_DIR`) first, then the pod's own `config/plugins/`; never a codebase's own
`.docket/plugins/`; it cannot be combined with `ID`
**Output**: The installed policies in `$POLICIES_DIR` plus the pod's own policy directory (a pod's
policies only ever add; ROADMAP P27-2), or one policy's JSON; `--json` prints a list of
`{id, hook, action, description}` (with `--plugins`, `{policies, plugins}` where each plugin is
`{name, scope, file, sha256}`)
**Return**: `0` on success, `1` on an unknown `ID` or a `PluginError`, `2` on a usage error

#### docket log
**Purpose**: Show recent recorded operator events, or verify the log's tamper-evidence chain
(see audit.spec.md for the exact recorded families and the coverage gap)
**Syntax**: `docket log [N] [--json]` · `docket log verify`
**Arguments**:
- `N` (optional): Number of recent entries to show (default: 20)
**Options/Actions**:
- `--json`: Emit the raw JSONL passthrough instead of a formatted table
- `verify`: Walk the current log's `seq`/`prev_hash` hash chain and report the first broken link,
  instead of listing entries
**Output**: Timestamped log of mutating operations, or a chain-verification result
**Return**: 0 for the listing form; for `verify`, 0 when the chain is clean (or no log exists
yet), 1 when a broken link is detected; 2 for an unknown verb

#### docket setup
**Purpose**: Set up this workstation. `docket setup` with no verb is the first run: a flow, not a
catalog, idempotent, in two modes chosen by the terminal (the interaction contract's rule).
**Syntax**: `docket setup [--json] [--fix]` · `docket setup provider|model|sandbox|shell|notify|export|mcp ...`
**Bare `setup`** always starts with a report: one line per piece with its state and the exact
command that fixes it — the model endpoint (the only required piece: a provider, its credential,
and `lead`/`implementer` resolving to a model), notifications (`console only (nobody is told)` is
a warning), the sandbox (state and whether bwrap or docker was found), shell completion and the
background service. The report is computed by `cli/_setup.py::readiness()`, which prints and
writes nothing; `init` and `run` read it.
- **On a terminal** it continues by asking only for what is missing, required first: choose a
  provider (the catalog's built-ins plus `local`), the credential (stored 0600, never echoed),
  probe `/models`, apply the preset and confirm the two roles resolve; then the optional pieces,
  each defaulting to `N`: desktop notifications when a desktop session exists, Telegram, the
  sandbox when a backend exists, shell completion. It prints every command it runs
  (`ran: docket setup provider add anthropic --credential`) and ends with
  `Ready.` and `→ Next: cd into a repo and run docket init`. A second run prints `Ready.` and
  asks nothing.
- **Off a terminal** it prints the report with the commands and exits 1 when the model endpoint
  is missing, 0 otherwise; it writes nothing. `--json` emits the report
  (`{"ready": bool, "pieces": [{name, ok, reason, command}]}`) with the same exit code.
- `--fix` hardens the permissions of docket-owned files, installs the baseline guardrail
  policies and runs the health checks with repair (permissions, missing workspace files,
  session-key resync, the dispatch ledger re-sync); it is the only `setup` form that repairs.
The wizard has no logic of its own: it calls the functions the verbs call, so every store keeps
one writer.

**`setup provider`** — `add <name> [url] [--credential KEY] [--model ID] [--ctx N]
[--max-tokens N] [--no-preset]` does the whole intent: store the credential (the flag, else the
provider's environment variable, else a hidden prompt on a terminal; off a terminal with none it
exits 1 naming `--credential`), probe `<url>/models` with it and classify the result
(model-profiles.spec.md "Provider readiness" 3), register the provider, then apply the provider's
preset unless `--no-preset` and print which role resolves to what. `add <file.yaml>` registers a
`kind: provider` document. `list [--json]`, `show <name> [--json]`, `remove <name> [--yes]`
(confirms on a terminal; off one it exits 1 naming `--yes`), `export <name> [<file>]`,
`rotate <name> [--credential KEY]`.
**`setup model`** — bare or `list [--json]` shows the role→model table (role, model, price,
source, why); `set <role|default> <provider/model>`; `preset [name]` lists or applies a provider
preset to every role; `reset [--yes]` restores the built-in policy.
**`setup sandbox`** — bare or `status [--json]` is a read: the gate is always active, plus the
isolation state, the network mode and the backend found. `on` needs bwrap or a reachable docker
(exit 1 naming both otherwise), `off`, `network none|open` (any other word is a usage error,
exit 2), `classes` lists the high-risk action classes. Writes are audited as `gates.isolate` and
`gates.network`. See security-gates.spec.md.
**`setup shell <bash|zsh>`** — prints the completion script generated from the live command tree;
any other shell is a usage error (exit 2). Enable it with `eval "$(docket setup shell bash)"`.
**Return**: 0 on success; 1 when the model endpoint is missing off a terminal, a provider is
unreachable, a required value or confirmation is missing, or the sandbox has no backend; 2 on a
usage error.

**`setup notify`**
**Purpose**: Manage `kind: channel` documents -- notification/conversation/decision
destinations -- and connect Telegram in one step (Phase 34, D-50, ADR 0016 §7; see
operator-loop.spec.md "Notifications" and telegram-integration.spec.md)
**Syntax**: `docket setup notify <list|show|enable|disable|add|remove|export|privacy|test|bind|unbind|flush>`
(a real sub-app of `setup`; bare `docket setup notify` prints its help)
**Subcommands**:
- `list [--json]`: Every catalog channel's dialect, enabled state, capabilities and content level
- `show <name> [--json]`: One channel's effective document and scope; `show telegram` also lists
  the bindings in `fleet.json` and the open Telegram conversations in the registry
- `enable <name> [--set k=v ...] [--chat ID ...] [--token T] [--test]`: Writes only the `enabled`
  flag plus the overrides given (`--set actors=a,b` sets the actors list, `--set secret=NAME`
  sets the credential name, anything else lands in `config`); refuses without writing while a
  required field the built-in names is still empty (`ntfy` needs a non-empty `topic`).
  `enable telegram --chat <id>` is one operation: it stores the bot token (`--token`, then
  `TELEGRAM_BOT_TOKEN` in the environment, then a hidden prompt on a TTY; a stored token is
  kept when none is given), sets `actors`, binds every pod Lead to the first chat, and prints
  what it wrote in each store. It sends nothing unless `--test` is given; with no chat id, or
  no token off a TTY, nothing is written
- `disable <name>`: Turns it back off
- `add <file.yaml>` / `remove <name> [--yes]`: Manage a full document; a built-in with no global
  override refuses naming it as built-in
- `export <name> [<file>]`: Print or write one back out
- `privacy <name> [<level>] [--yes]`: Show or change how much a delivery carries (`minimal <
  actions < conversation`); widening prints the change and asks for confirmation on a TTY, or
  refuses off one without `--yes` -- narrowing never asks
- `test <name>`: Sends one synthetic `dev.docket.channel.test` event through that one channel and
  reports success or failure -- useful to verify a webhook URL or a command binary before relying
  on it
- `bind <member> [--channel telegram] [--chat ID]`: Bind one pod member to a chat (the per-pod
  exception to `enable telegram`) and seed its conversation registry entry; without `--chat` a
  TTY runs the one-time `/wire <code>` discovery with manual entry as the fallback, and off a TTY
  the command refuses naming `--chat`. The binding is the entire authorization boundary
- `unbind <member> [--channel telegram] [--yes]`: Remove that binding after a confirmation
- `flush [--dry-run]`: `docket start`'s sweep and `docket run` already flush after
  every real state change; this forces one in between, or previews it. With no `--dry-run`, diffs
  the inbox against the last flush's saved snapshot, delivers each new event
  (`dev.docket.task.*`/`approval.*`) to every enabled channel whose `on` matches, and prints the
  delivered/failed/skipped counts. The snapshot is saved *before* delivering, so a crash
  mid-flush never re-emits; a failed delivery is recorded in `~/.docket/channels-health.json` and
  not retried on the next flush (at-most-once). `--dry-run` delivers nothing and leaves the
  snapshot untouched
Only `test`, `enable --test` and `flush` ever send anything; every other subcommand edits the
catalog or `fleet.json`
**Output**: A table/document, or a confirmation
**Return**: 0 on success, 1 on an unknown channel or member, a missing required field on
`enable`, a refused widening, or a failed delivery; 2 on a usage error

**`setup export`**
**Purpose**: List, inspect, and enable an observability export destination (`kind: exporter`
document, `core.exporter`) by authenticating -- the requested experience is "the YAML exists,
I only put the key" (observability-export.spec.md "Activation"); and show or change what an
exporter shares beyond bare structure, as a confirmed command
(observability-export.spec.md "Privacy commands and disclosure")
**Syntax**: `docket setup export <list|show|enable|disable|test|add|remove|export|privacy|preview>`
(a real sub-app of `setup`; bare `docket setup export` prints its help)
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
  stores it in the 0600 secret store, or on a non-TTY names the missing credentials and exits 1
  writing nothing. A `--privacy`/`--share` that widens what the exporter shares
  (`core.exporter.is_widening`) follows the same confirm-or-refuse rule as `privacy`. Then probes
  the (possibly overridden) endpoint and classifies it exactly like `docket setup provider add`;
  a transport failure exits 1 and writes nothing unless `--no-verify` is given. On success,
  writes only `{kind, name, enabled: true, <overrides given>}` to the global catalog through
  `core.exporter.enable_exporter` -- every other field is inherited from the built-in of the
  same name at read time -- and prints `shares: <label> (<classes, or "structure only">)`
- `disable <name>`: Flip `enabled` to `false` in the global catalog; stored credentials are
  never touched
- `test <name>`: Re-probe the endpoint and print the classified result; exit 0 on a clean
  2xx, 1 otherwise
- `add <file.yaml> [--no-verify] [--yes]`: Register a full `kind: exporter` document, verified
  like `enable`; a document sharing beyond `minimal` follows the same widening rule, compared
  against any existing catalog entry of the same name
- `remove <name> [--yes]`: Remove a global override after a confirmation; a built-in with none
  refuses naming it as built-in before asking
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

**`setup mcp`**
**Purpose**: Configure the external stdio MCP tool servers docket connects to as a client, whose
tools reach a live turn through the same `dispatch_tool` chokepoint (`mcp-client.spec.md`)
**Syntax**: `docket setup mcp <list|add|remove>` (a real sub-app of `setup`)
**Subcommands**:
- `list`: Every configured server's name, launch command, `kind`, `tools` allow-list (empty =
  all), timeout and whether it runs in the jail or on the host; `env` values are masked
- `add <name> [--env K=V ...] [--timeout S] [--kind read|write] [--tools NAME,...] [--no-isolate]
  -- <command> [args]`: Everything after `--` is the launch command, verbatim. `--kind` declares
  the server's trust level (default `write`); `--no-isolate` starts the server on the host
  instead of in the turn's jail (audited, shown by `list`). A bad `--kind`, a malformed `--env`,
  a bad or duplicate name exits 1 writing nothing; a missing command exits 2
- `remove <name>`: Remove a configured server; an unknown name exits 1
**Return**: 0 on success, 1 on a refused value, 2 on a usage error

#### docket start
**Purpose**: Start the background service — refresh fleet status, serve the local HTTP API and
optionally drive pod dispatch pipelines
**Syntax**: `docket start [--port <n>] [--interval <s>] [--dispatch] [--telegram] [--mcp] [--token-file <path>]`
**Options**:
- `--port`/`-p <n>`: Listen port for the HTTP API (default: 7331)
- `--interval`/`-i <s>`: Sweep refresh interval in seconds (default: 30)
- `--dispatch`: On each refresh, also run every pod's pending tasks through its pipeline (real, costed LLM turns; budget-gated and traced). Off by default — plain `docket start` never dispatches on its own.
- `--telegram`: Long-poll docket's own Telegram bot for `/approve` `/deny` `/status` `/delegate`
  (needs `TELEGRAM_BOT_TOKEN`; see telegram-integration.spec.md)
- `--mcp`: Serve docket's control plane as an MCP stdio server instead of the HTTP service
  (`mcp-server.spec.md`); it prints nothing to stdout but JSON-RPC and exits 2 when combined with
  `--dispatch`, `--telegram` or `--token-file`
- `--token-file <path>`: Write the Bearer token for the authenticated routes to this file (0600)
  instead of printing it
**Output**: Serves the HTTP API on `http://localhost:<port>/` — unauthenticated read routes
(`/status.json`, `/metrics`, `/health`) plus Bearer-authenticated routes (`/approvals`, `/runs`,
`/tasks`, `/traces`, `POST /approvals/<token>`, `POST /dispatch/<project>`, `POST /pods`); full
contract in serve-read-api.spec.md.
With `--dispatch`, also logs each dispatch hop. Records its pid in `$DOCKET_HOME/serve.pid`
before serving and removes it on exit
**Return**: 0 on clean shutdown (Ctrl-C or `docket stop`); 1 when a service is already running
(its pid names it); 2 for `--mcp` with a flag that prints to stdout

#### docket stop
**Purpose**: Stop the background service started by `docket start`
**Syntax**: `docket stop [--wait <s>]`
**Options**:
- `--wait <s>`: Seconds to let running sweeps finish after the first signal before sending the
  second, which abandons them (default: 15)
**Output**: One line; nothing running is reported as such and is not an error
**Return**: 0 when stopped or nothing was running; 1 when the process is still alive after the
second signal

#### docket exec
**Purpose**: Run one agent, for one turn, to completion, in a workspace and `DOCKET_HOME` the
caller supplies — for an external plan-of-record that spawns docket as a subprocess. Full
contract (wire shapes, refusal table, result mapping) in `harness-mode.spec.md`
**Syntax**: `docket exec --workspace DIR (--task TEXT | --task-file PATH) --model PROVIDER/ID
[--role implementer] [--timeout SECONDS] [--agent-id ID] [--contract 1.0|1.1] [--answers stdin]
[--answer-timeout S] [--token-file PATH] [--max-tokens N] [--policy FILE]... [--recipe NAME|DIR]
[--verify CMD]`; every option is a declared Typer option, an unknown one exits 2
**Output**: Streams NDJSON `HarnessEvent` lines and exactly one `HarnessResult` on stdout;
every log goes to stderr
**Return**: 0 `ok`, 1 `failed`/`blocked`/`cancelled`, 2 refused before any run began (the one
named exception to the flat convention, see Return Code Convention)

### Help

`docket --help` shows the tagline and the eleven commands in three panels, in this order: **Daily**
(`init`, `status`, `inbox`, `task`, `run`), **The pod** (`pod`, `log`) and **Machine** (`setup`,
`start`, `stop`, `exec`). The panels are declared on the registrations in `cli/__init__.py`;
`cli/_help.py` orders them. The project description in `pyproject.toml` is the same tagline.

An unknown top-level word is a usage error (exit 2, `No such command`). Its message offers, from
the live command tree only, the top-level commands the word resembles and every group that has a
verb of that name (a top-level `add x` names `docket task add` and `docket pod add`; a top-level
`approve` names `docket task approve`). A word that resembles nothing and is no verb gets no suggestion.
No table of retired names exists.

## Output Formats

### The console voice

`src/docket/ui.py` is the only module that knows symbols, colours and layout.

- **Five symbols**: `✓` done, `✗` failed or refused, `⚠` attention, `→` next step, `·` detail.
- **Five colour roles**: `success`, `error`, `warn`, `accent` (names, ids, commands), `dim`.
- **Shapes**: `header(noun, name)` renders `docket · pod myapp`; `section(title)` renders one of the
  shared section names `Needs you`, `Running`, `Done`, `Failed`; `table(rows, columns)` wraps cells
  at word boundaries and never cuts a word; `error(what, do)` renders `✗ <what>. <do>` on **stderr**
  (without `do`, `✗ Error: <what>`); `hint(command)` renders `→ Next: <command>` on stderr.
- **Plain mode**: when stdout is not a TTY or `NO_COLOR` is set, output carries no colour, no
  boxes and only the ASCII symbols `ok`, `x`, `!`, `->`, `-`. `DOCKET_NO_COLOR` is not read.
- **Tagline**: `ui.TAGLINE` is "docket runs teams of coding agents and governs what they may do".
- **Copy rule**: a command that changes state ends with exactly one `→ Next:` line (on stderr,
  silent under `DOCKET_NO_HINTS=1`); a read command ends with none; an error is one line that says
  what happened and what to do.
- A shrink-only guard (`tests/guards/test_console_voice.py`) counts Rich markup literals outside
  `ui.py`.

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
| `DOCKET_SERVE_TOKEN` | Fix `docket start`'s Bearer token instead of generating one | unset |

There is no `DOCKET_DEBUG`, `DOCKET_NO_COLOR`, `DOCKET_MODEL_DEFAULT` or `DOCKET_EDITOR`.
`DOCKET_APPROVAL_MODE` is not an environment variable despite its name: it is a key of the `env`
dict `run_turn` receives (see harness-mode.spec.md), never read from `os.environ`.

## Return Code Convention

docket uses a deliberately flat convention — the printed message, not the exit code,
distinguishes error kinds:

| Code | Meaning | Used By |
|------|---------|---------|
| 0 | Success | All commands |
| 1 | Any failure (not found, permission, refused confirmation, driver/model error, …) | All commands |
| 2 | Usage: an unknown command, flag, subcommand or action, or a required action word left out | All commands |

`docket exec` is the one live exception, and it is deliberate. Its stdout is a wire protocol
that a caller outside this repository parses, so the exit code has to separate "the run happened and
ended badly" from "the run never started", which a printed message cannot do for a program:

| Code | `docket exec` meaning |
|------|-----------------------|
| 0 | The turn completed; the final `result` line carries `status: "ok"` |
| 1 | The turn ran and ended `failed`, `blocked` or `cancelled` |
| 2 | Refused before any turn began: preflight rejected the environment, or the arguments were unusable. Exactly one `result` line with `status: "refused"`, no run record, no meta written |

No other exit codes are produced by docket's own commands. Typer/Click's own usage errors (an
unknown option, command or verb, before any command body runs) exit `2`; the unknown-word
message names the live commands the word could mean (Help above). `docket init`, the one
command that parses its own trailing flags, reports an unrecognized one with `2` too
(`find_unknown_flag`).

## Validation

Input validation rules that every command MUST enforce before performing side effects.
The authoritative rule set lives in [input-validation.spec.md](../validation/input-validation.spec.md);
the contract-level summary follows.

### Agent ID Validation
- Pattern: `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- Length: 3-50 characters
- Reserved IDs: system, docket
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
- Budget values: non-negative USD (`pod set budgetUsd N`)
- History window: non-negative days (`status --history --days N`)
- Timeout values: 1-3600

## Interactive Features

### Confirmation Prompts
`cli/_contract.py` owns the interaction contract; no command prompts on its own.

- `confirm(action, *, yes, typed=None)`: with a TTY, a `y/N` prompt, or the typed name when
  `typed` is given; without a TTY it refuses with exit 1 naming `--yes` (or `--confirm <name>`
  when `typed` is given). `yes=True` returns without prompting.
- `require_value(name, value, flag)`: with no TTY and no value, exit 1 naming the flag; never a
  picker.
- `emit_json(obj)`: plain `json.dumps` to stdout, never Rich.
- `next_step(command)`: the one `→ Next:` line described under "The console voice".
- `sys.stdin.isatty()` is probed in one function, `_contract._is_tty`.

## Foreground dispatch progress and in-place approval

### Rendering

`docket run` MUST
render one line per event on stderr while the dispatch runs, whenever stderr is a real TTY or
`--progress` is given:

- `session_start` → `▶ <role> …`
- `approval_requested` → `⏸ <role> wants: <action> · token <token> · denies in <n>s · docket
  task approve <token>`, where `<n>` is `TOOL_APPROVAL_TIMEOUT` minus the elapsed time since the event
- `approval_required` (the hop-level gate) → `⏸ <role> hop needs approval · token <token> ·
  docket task approve <token>`
- `session_end` → `■ <role> finished — status=<status>`

No other trace event type renders a line. Without a TTY and without `--progress`, no worker
thread runs, no trace subscription opens, and stdout/stderr MUST stay byte-identical to a build
with no progress view (the no-change oracle the golden suite pins).

### In-place approval

When the rendering above is active, stdin is also a real TTY, and `--no-prompt` is absent, every
`approval_requested` event additionally prints `[a]pprove  [d]eny  [Enter] keep waiting` and reads
one line from stdin. `a` MUST call `core.approval.approval_grant(token, channel="cli")` then
`core.dispatch.resolve_waiting_approval(token, "granted")`; `d` MUST call the same pair with
`approval_deny`/`"denied"` — the identical pair `docket task approve`/`docket task deny` use, so an in-place
answer is indistinguishable from a second terminal's. Any other input (including a bare Enter)
keeps waiting. A token already resolved through another channel (`ApprovalNoop`) prints one dim
notice and the prompt keeps waiting on the next event; it MUST NOT raise out of the dispatch call.

### Flags

- `--progress` forces the rendering above even when stderr is not a TTY.
- `--no-prompt` disables the in-place prompt even when stdin is a TTY; rendering is unaffected.

Neither flag applies to `docket exec` or a non-interactive dispatch caller (`start
--dispatch`, a due schedule, the MCP `dispatch` tool) — this section governs only the foreground
CLI path (`cli/_run.py::_pod_dispatch`, `cli/_progress.py`).

## Error Message Standards

### Format
One `ui.error` line on stderr (`✗ Error: <what failed>`), optionally followed by a usage or
recovery hint line, then `typer.Exit(1)`. There is no multi-line Details/Suggestion block.

### Example
```
✗ No pod for /work/app (looked for a registered codebase containing it). Run 'docket init' here, or pass --pod <name>.
```

## Performance Requirements

### Response Times
- Simple queries (`status`, `task list`, `pod show`): < 500ms
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
  retired-command notice, no deprecated no-op flag, no suggestion of a former name (ADR 0022
  decision 4). A name docket used to have, or a former alias, is an ordinary unknown command
  (exit 2); `CHANGELOG.md` is the only record of what went and what replaced it.
- Direct JSON editing → Use docket commands

## Changelog

### Version 2.1.2 (2026-10-08)

- `docket status` counts `waiting_input` tasks (`N waiting input`, pod `waiting`) and its `Isolation:` line reports the sandbox posture.

### Version 2.1.1 (2026-10-08)

- `task approve <apr-token>` ends with the run hint like the task-ref form (the pod comes from
  the approval record); `task deny --reason` puts the reason on the failed task.

### Version 2.1.0 (2026-10-08)

- `docket init` declares its two arguments and eight options on the command instead of parsing
  `ctx.args` by hand: `--help` is one screen listing each option with its meaning (the blueprint
  rosters and the `--from` format stay in pod-blueprints.spec.md), `setup shell` completes them,
  and a `--pod` value other than `full`, `--from` beside any other option, or a third positional
  exits 2 as a usage error, as an undefined option already did. `agentic-product` is listed with
  the other blueprints. The syntax line names every option, so the invocation guard checks it.

### Version 2.0.0 (2026-10-08)

- The registry is the eleven commands of ADR 0022 and nothing else: one `#### docket <cmd>` section
  per top-level command (`init`, `status`, `inbox`, `task`, `run`, `pod`, `log`, `setup`, `start`,
  `stop`, `exec`), each carrying its verbs (`task` with its answering verbs, `pod` with its
  configuration half and `pod roles`, `setup` with `notify`, `export` and `mcp`). The grouped
  headings, the retirement notes for `workflow`, `team` and `eval`, the project picker, the
  positional pod id and the `profile`/`keys` examples are gone, not struck through. Arguments are
  the task ref, the member, the setting key and the catalog name; excess positionals exit 2.
  Retired names are an ordinary unknown command and `CHANGELOG.md` is their only record.

### Version Detection
- Docket's supported state root is `~/.docket` (or `DOCKET_HOME`). It does not import state from a
  retired runtime; the first `docket init` writes a Docket-owned home.

### Version 1.80.0 (2026-10-08)

- Help is grouped: `docket --help` shows three panels (Daily, The pod, Machine) under the tagline;
  `-h` works at every level; an unknown word suggests the live commands and group verbs it could
  mean. The bare `docket` greeting is the tagline, the five daily commands and the setup pointer.
  `docket setup shell` renders both scripts from the live command tree (every group's verbs and
  long options, pod names after `--pod`, task ids after `task <verb>`).

### Version 1.79.0 (2026-10-08)

- The pod group gains its configuration half: `docket pod apply [NAME|DIR|FILE]` (a file installs one role or policy document; no argument re-syncs stale instructions), `pod export [DIR]`, `pod validate [PATH]` (one validator for every `kind:` document), `pod plan [--pipeline FILE]`, `pod check TEXT --role R`, `pod recipes|roles|policies [NAME]` (with `--json`; `--plugins` on `policies`). The commands `validate`, `pipeline`, `roles`, `policies`, `recipes`, `plugins` and the pod actions `apply`, `export`, `sync` are unknown. `policies init` and the whole-registry `roles validate` have no replacement; `docket setup` installs the baseline policies.
### Version 1.78.0 (2026-10-08)

- Phase 39 (P39-10): `docket add`, `info`, `delete`, `maintain`, `profile` and `config` are
  removed and are ordinary unknown commands (exit 2), as are the pod actions `list`, `add`,
  `remove`, `set-verify` and `config`. The roster is `docket pod show|add|remove|reset|set|unset|
  delete`, a real Typer group resolving its pod from `--pod`, `DOCKET_POD` or the directory.
  `docket config explain` becomes `docket pod show <member>`; `docket profile --budget` becomes
  `docket pod set budgetUsd`.
### Version 1.77.0 (2026-10-08)

- Phase 39 (P39-9): `docket task approve|deny|answer|retry|cancel` are added; `docket approve`, `deny`, `chat`, `docket pod <p> answer|pregrant` and `docket runs cancel` are removed and are ordinary unknown commands (exit 2). The trace progress line names `docket task approve <token>`.
### Version 1.76.0 (2026-10-08)

- Phase 39 (P39-8): `docket task add|list|show|diff|trace|prune` replace `delegate`, `pod <p>
  delegate|queue|explain|evidence|corrections|worktrees`, `runs list|show|prune` and `trace`; the
  five old names are ordinary unknown commands or pod actions (exit 2 / exit 1). `task show`
  prints the task worktree (path, branch, base, diff and merge commands); `task trace --tail`
  ends at `session_end`; `task prune --traces` replaces `trace expire` and `runs prune`.

### Version 1.75.0 (2026-10-07)

- Phase 39 (P39-16): `docket list`, `context`, `logs`, `edit`, `scope`, `persona` and `help` are
  removed and are ordinary unknown commands (exit 2); `EDITOR`/`VISUAL` leave the environment
  table. The bare-`docket` guide drops the `help` line.

### Version 1.74.0 (2026-10-07)

- `docket run` (pod-dispatch.spec.md "CLI entry: `docket run`") replaces `docket pod <p> dispatch` and `docket pipeline run`; `docket status` absorbs `cost`, `metrics` and `snapshot` (per-pod tokens, labelled estimate, outcomes, last run, `docket start` state; `--all --json` carries the inventory); `docket inbox` takes declared options only, prints the exact `docket task ...` command per item and never truncates. `dispatch`, `pod dispatch`, `pipeline run`, `cost`, `metrics` and `snapshot` are unknown commands.

### Version 1.73.0 (2026-10-07)

- Phase 39 (P39-14): `audit` is `docket log [N] [--json]` and `docket log verify` (an unknown
  verb exits 2); `serve` is `docket start` (plus `--mcp`, which replaces `mcp serve`) and
  `docket stop`, with the service's pid in `$DOCKET_HOME/serve.pid`; `harness run` is `docket
  exec` with Typer-declared options; `harness status` is removed.

### Version 1.72.0 (2026-10-07)

- Phase 39 (P39-13): `channels`, `wire`, `unwire`, `notify`, `conversations`, `exporters` and
  `mcp servers` are removed; an undefined name exits 2. `docket setup notify` carries the channel
  catalog, `enable telegram --chat <id>` (token, actors and every Lead's binding in one
  operation; nothing is sent without `--test`), `bind`/`unbind`, `privacy` (was `content`) and
  `flush`; `docket setup export` carries the exporter verbs; `docket setup mcp` carries
  `list|add|remove`. `remove` confirms (`--yes` off a TTY). The conversation registry has no CLI:
  `show telegram` lists it.

### Version 1.71.0 (2026-10-07)

- Phase 39 (P39-12): `setup` is the first-run flow. Bare `docket setup` prints the readiness
  report (model endpoint, notifications, sandbox, shell completion, background service), asks
  only for what is missing on a terminal, and off one exits 1 when the endpoint is missing;
  `--json` emits the report and `--fix` repairs. `setup provider` (`add` stores the credential,
  probes `/models` and applies the preset), `setup model`, `setup sandbox` and `setup shell` are
  real sub-apps. `doctor`, `models`, `models provider`, `keys`, `gates` and `completions` are
  unknown commands. `init` no longer bootstraps the home: with no endpoint it builds the team and
  ends with `No model endpoint yet` and `docket setup`.


### Version 1.70.0 (2026-10-07)

- Phase 39 (P39-6): `docket init` no longer bootstraps shared org specialists or accepts
  `--portfolio`; an undefined `init` option exits 2. `list`, `snapshot` and `/status.json` show pod
  members only; `delete` text drops the specialist refusal; the no-argument guide drops the
  "Org Specialists" entry.

### Version 1.69.0 (2026-10-07)

- `docket runs show <id>` exits 1 when the run or any task it returned failed, and for an unknown run; it exits 0 for any other recorded state, including `waiting_input`/`waiting_approval`.
- `docket doctor` counts only lines marked with a red cross as critical issues (a warning never is), exits 0 with no critical line, and its footer hint names `docket doctor --fix`.
- `docket metrics` success/failure/aborted counts come from the terminal task status each dispatch `session_end` event records (`done` success, `failed` failure, `cancelled`/`blocked` aborted; a parked task is not terminal and is not counted), not from a hard-coded `success`/`failure` payload no dispatch ever wrote.

### Version 1.68.0 (2026-10-07)

- One interaction contract (`cli/_contract.py`) and one console voice (`ui.py`): plain mode off a
  TTY or under `NO_COLOR`, shared symbols and roles, `TAGLINE`, exit 2 for usage.

### Version 1.67.0 (2026-10-07)

- Adds "Pod targeting": one resolver (`--pod`, `DOCKET_POD`, then the deepest codebase containing
  the current directory) with a single no-match error; `status` and `add` use it.


### Version 1.66.0 (2026-10-06)

- Releases `0.2.0-beta.4`; artifact metadata and `docket --version` report its PEP 440 form
  `0.2.0b4`.

### Version 1.65.0 (2026-10-06)

- `docket gates`: isolation is opt-in (ADR 0021); `status` reports `off (default)` with no
  recorded choice.

### Version 1.64.0 (2026-10-06)

- `docket pod <p> answer --option <id>`; `docket chat` renders a consult's options and prompts
  for one (Enter takes the recommended); `docket inbox` prints a `waiting_input` task's
  question, options and the `docket chat` hint.
- `docket doctor` (human and `--json`) reports notification reach: a home with project agents
  and no channel that delivers beyond the console is a counted issue naming the fix.
  `docket serve --dispatch` prints the same warning once at startup, `docket init` after the
  created summary, and `docket pod <p> dispatch` after a flush that found events
  (operator-loop.spec.md Notifications 17). Nothing is enabled automatically.

### Version 1.62.0 (2026-10-05)

Waves 89-90 close (W89-10): the entries below were Unreleased and are now this version.

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
