# CLI Interface Contract Specification

**Version**: 5.7.0
**Status**: Complete. Every command, verb and flag below is in the live command tree (`docket
--help`, generated `docs/commands.md`).
**Last Updated**: 2026-10-30

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
MUST run from an artifact-only installation.  `docket --version` prints
`docket <version>` from an artifact; from a git checkout (the package's source root holds
`.git`) it appends ` (git <sha8>)`, and `, dirty` inside the parentheses when `git status`
reports changes, so a tree ahead of its tag is told apart from the release that tag built.
Installed project metadata MUST
report a PEP 440-equivalent form of declared version `0.2.0-beta.6`, Python
requirement `>=3.11`, Apache-2.0 licensing, and the canonical project source,
issues, and homepage URLs.  Uninstalling the
distribution MUST remove its executable, package, and distribution metadata
without deleting dependencies shared by other installed packages.

The release sdist MUST exclude the repository-only `Formula/` directory. The
Homebrew formula hashes that exact archive, so including the formula would make
the published input depend on its own output digest.  No sdist member name may
contain `:`: uv 0.13 refuses to extract such a member, so it could neither build
a wheel from the sdist nor install it.

The `[project.scripts]` console-command object MUST be the same entry point that
`python -m docket` runs (`docket.__main__:main`), which only invokes the Typer
app, so an installed `docket` and `python -m docket` parse every argv identically.
There is no command alias table: a name that is not a registered command is Click's
ordinary unknown-command usage error (`No such command`, exit 2).

- `global-options` MUST precede the command (see [Options](#options)).
- `command` MUST be one of the entries in the Command Registry below.
- `arguments` are positional and command-specific (see [Arguments](#arguments)).

The per-command entries in the Command Registry are the authoritative source for each
command's exact syntax.

## Arguments

Positional arguments are command-specific; the following conventions apply across commands:

| Argument | Applies to | Rules |
|----------|------------|-------|
| `<ref>` | `task show|diff|trace|answer|pregrant|retry|cancel` | A full task id, the short id `task list` prints, a unique prefix, or a run id (`resolve_task`); never omitted, never picked from a menu |
| `ID` | `pod memory approve|refuse|revert` | A memory entry id as `pod memory list` prints it (`mem-` and ten hex characters); unknown to the resolved pod exits 1 |
| `MEMBER` | `pod show|remove|reset`, `pod set|unset --member` | MUST match `^[a-z0-9][a-z0-9-]*[a-z0-9]$`; a member of the resolved pod |
| `KEY VALUE` | `pod set|unset` | A `PodSettings` key, or `verify` with `--member` |
| `location` | `init` | Tilde-expanded and recorded as given; `init` neither makes it absolute nor checks that a codebase exists (see Path Validation). For a `workdir`-kind blueprint (`research`/`content`/`ops`) docket creates the working directory if absent |
| `provider/model` | `setup model set` | MUST be well-formed `<provider>/<model-id>`; `setup model set` also accepts the literal `default` |
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
| --version | -V | Show version info: `docket <version>`, plus ` (git <sha8>[, dirty])` from a git checkout | - |

These two are the whole global surface (`docket --help`); `-h` is declared once on the root
and every child command inherits it, so `docket task show -h` equals `docket task show --help`.
Any other option before the command is an unknown option (exit 2); the state location is
chosen with `DOCKET_HOME`, not a config file flag.

### Pod targeting

Every pod-scoped command resolves its pod (`resolve_pod`) from three sources in this order:
the `--pod`/`-p` option (declared by `pod_option()`), then the `DOCKET_POD` environment
variable, then the registered pod whose codebase contains the current directory. When several
registered codebases contain it, the deepest wins; two pods matching at the same depth are both
named in the error. `docket status`, `docket run`, `docket task add|list|prune` and every
`docket pod` verb use it; a task `<ref>` given without `--pod`/`DOCKET_POD` is searched in every
pod instead.

When no pod matches, the command prints one error line and exits 1:

```
No pod for <cwd> (looked for a registered codebase containing it). Run 'docket init' here, or pass --pod <name>.
```

## Command Registry


Ten commands, in the order `docket --help` shows them (Daily: `init`, `status`, `inbox`,
`task`, `run`; The pod: `pod`, `log`; Machine: `setup`, `start`, `stop`). Each top-level
command has one section below with every verb it owns. A name that is not one of the ten, or
a verb a group does not have, is an ordinary unknown-command usage error (exit 2).


Invoking `docket` with no command **MUST** print only a compact guide of three parts, in this
order: the tagline (`ui.TAGLINE`), the five daily commands with one-line meanings (`docket init`,
`docket task add "..."`, `docket run`, `docket status`, `docket inbox`), and the line
`Not set up yet? docket setup`. It is rendered by `ui.guide` and **MUST NOT** read or render the
fleet, project agents, costs, bindings, or health checks.

#### docket init
**Purpose**: Provision a project pod from a blueprint (Lead + Implementer against a codebase by
default — see pod-blueprints.spec.md). It **MUST NOT** bootstrap the workstation-wide home
beyond creating the directories it needs and installing the shipped guardrail policies (an
existing policy file is never overwritten); the endpoint and the security posture belong to
`docket setup`.
**Syntax**: `docket init [project] [location] [--blueprint <name>] [--pod full] [--with <roles>] [--codebase <path>] [--name <text>] [--from <file>] [--recipe <name|dir>] [--no-apply] [--accept CODE] [--json]`

`init` provisions the pod's own members and no shared agent. Its arguments and options are
declared on the command, so `docket init --help` lists each with its meaning and `setup shell`
completes them; the command builds one `InitRequest` and `run_init` provisions from it. An
option it does not define, a `--pod` value other than `full`, `--from` combined with any other
argument or option, or a third positional is a usage error: it prints one line and exits `2`
before anything is provisioned. The help is one screen: the default team, the `.docket/`
discovery and `--recipe`, one `Example:`; the blueprint rosters and the `--from` file format
live in pod-blueprints.spec.md, not in the help.

When `docket setup`'s readiness report (`readiness()`) shows no model endpoint (the selected
role models do not resolve to a callable OpenAI-compatible endpoint; an API key without a
compatible endpoint is not ready), `init` still builds the team and ends with
`⚠ No model endpoint yet` and the single next step `docket setup`. A registered local endpoint
passes without a key.
**Arguments**:
- `project` (optional): Project name / pod identifier, slugified (lowercased, every run of other
  characters becomes one `-`, leading and trailing `-` dropped); the slug MUST be non-empty, at
  most 64 characters and match `^[a-z0-9]+(?:-[a-z0-9]+)*$`. Omitted defaults to the current
  directory name
- `location` (optional): Meaning depends on the selected blueprint's `workspaceKind` — a codebase
  path for `software` (the default), or a working directory for `research`/`content`/`ops`.
  Omitted, it is the current directory. It is stored absolute (a relative path is taken from the
  current directory), a codebase that is not an existing directory is refused with exit 2, and a
  working directory is created when missing; provisioning never changes the mode of a directory
  it did not create
**Options**:
- `--blueprint <name>`: Select a pod blueprint (`software` | `research` | `content` | `ops` |
  `agentic-product`); omitted defaults to `software`. An unknown name fails
  cleanly (exit 1) before any prompt is shown
- `--codebase <path>`: The location, as an option instead of the second argument
- `--name <text>`: The pod's name, as an option instead of the first argument; an option wins
  over its positional
- `--pod full`: Provision a full pod — Lead, Implementer, and Reviewer. Applies only to
  the `software` blueprint
- `--with <roles>`: Start from the lean pod and add named roles (comma-separated: `reviewer`,
  `implementer`). Applies only to the `software` blueprint; passing it with another
  blueprint warns and is ignored (that blueprint's own fixed roster is used instead)
- `--from <file>`: Declarative provisioning from a JSON/YAML spec file (idempotent); each entry
  names a `blueprint` and provisions a pod the same way `--blueprint` does interactively. An
  entry without one, or with a location that is not usable, is refused and the command exits 2
  once every entry has been processed
- `--recipe <name|dir>`: Apply a shipped or local recipe directory after provisioning —
  resolved exactly as `docket pod update` resolves a name (`resolve_recipe`); an unresolvable
  name fails cleanly (exit 1) naming the recipes it knows, before any prompt or provisioning.
  Mutually exclusive with a present `<location>/.docket/`: giving both fails cleanly (exit 1)
  naming both sources, before provisioning
- `--no-apply`: Provision the pod only, skipping the apply step for a present `.docket/` or a
  resolved `--recipe`; prints the `docket pod update <dir>` command that would apply it
- `--accept CODE`: Allow exactly the run-on-this-machine items whose review code is CODE, so a
  repository's commands are allowed off a terminal (pod-blueprints.spec.md requirement 12)
- `--json`: `init` never asks on a terminal, and a stop of the operator's review or a refused name
  or location prints one JSON object on stdout instead of prose. `{"status": "needs_review", "reviewCode", "items": [{kind, name,
  runs}]}` when the operator's review is needed; `{"status": "refused", "refused": [name],
  "items"}` when the repository allows a shell; `{"status": "code_mismatch", "items": [{kind,
  name, runs, before}]}` when `--accept` names a code the repository no longer matches (the
  current code is never printed); `{"status": "invalid", "reason"}` when the pod name or the
  location is refused

A repository's own `<location>/.docket/` (never docket's own state root, which is not a
repository's configuration; the same directory shape `docket pod update` reads,
see pod-blueprints.spec.md, "Pod manifests: apply") is discovered automatically: `init` validates
every document under it before provisioning anything, and — unless `--no-apply` is given — applies
it after provisioning through the same `plan_apply`/`apply` path `docket pod update` uses. A
validation error exits 1 naming the file and field, with nothing provisioned. When
`.docket/teams/` holds several teams and none is named after the pod, `init` exits 2 naming them
(`--name` picks one), unless `--recipe` is given.

Before anything is created, the commands the `.docket/` or a non-shipped recipe would run on
this machine go through the operator's review (pod-blueprints.spec.md requirement 12): on a
terminal `init` lists them and asks `[y/N]`, remembering a yes; off a terminal, or with
`--json`, it prints the items and their review code and exits 2 unless `--accept` names that
code. A shell-like command is refused (exit 2), and a code that no longer matches what the
repository runs exits 2 showing each item before and now. Every one of these stops creates
nothing.
**Output**: Creation progress and confirmation with member IDs. The closing `created with N
members` line and the id list that follows it count every member of the pod as it stands after
the apply step, so a member a present `.docket/` or `--recipe` added is counted and listed.
When no enabled channel delivers beyond the console, the summary ends with
`unreached_warning`'s text; on a TTY with a desktop session it then asks
`Enable desktop notifications now? [Y/n]` and, on yes, enables `desktop` and sends one test
notification (operator-loop.spec.md Notifications 17). Off a TTY it only warns. Then comes a
`This machine` block (followed only by the missing-endpoint warning above, when it applies)
whose `Sandbox` line is the sandbox posture (the lines
below, shared with `status` and `setup sandbox --json`): `Sandbox   off. The agent's commands run
with your user's permissions.` then `Turn it on: docket setup sandbox on`; `Sandbox   on
(landlock, network none)`; or `Sandbox   not available: Linux needs a kernel with Landlock (5.13
or newer).` / `Sandbox   not available on native Windows; use WSL2.` when no backend exists
**Return**: 0 on success, 1 on error (pod already exists, unknown blueprint, an invalid
`.docket/`, or provisioning registered no member — docket's flat convention, see Return Code
Convention below); 2 on a usage error, when the pod name or the location is refused, when the
operator's review stops `init`, or when several teams leave the pod's team unnamed

With no explicit project or location, `init` **MUST** derive both from the current working
directory without an interactive questionnaire. The intended first-run flow is package-manager
installation followed directly by `docket init` once per project. Declarative `--from`
provisioning belongs to `init`, including multi-project automation.

#### docket status
**Purpose**: Show where a pod stands — tasks, tokens, outcomes, the last run — or every pod.
**Syntax**: `docket status [--all] [--json] [--history] [--days N] [--pod <name>]`
**Behavior**:
- Output opens with the `Sandbox` line (the `init` closing lines; JSON `isolation` keeps the
  string `on (<backend>, network <open|none>)` or `off (default); <backend|no backend> found,
  network <open|none (not enforced: isolation off)>`). With no flag, resolve the pod (`--pod`, `DOCKET_POD`, then the most-specific initialized pod
  whose `codebase`/`workDir` contains the current directory) and report its path, members, task
  counts (including waiting approval, waiting input, failed and "approved, ready"; a pod with a
  `waiting_input` task is `waiting`), measured tokens with a labelled dollar
  estimate, the success/failure/aborted counts and latency from trace `session_end` events, the
  last run, and whether `docket start` is running (its `serve.pid` names a live process). The task
  counts are the queue counts `GET /pods` carries (`pod_report.task_counts`). A pod whose Lead is
  paused shows a `Paused` row naming the reason and `docket run --resume`; JSON carries `paused`
  and `pausedReason` for every pod.
  When the operator has allowed a repository's commands (`reviewed-repos.json`), a `Commands`
  row reads `N allowed on <date> (code <16 hex>)`, and when the repository's `.docket/` now
  holds a run-on-this-machine item that differs from the allowed one, a second row reads `N
  changed in the repository, waiting for your OK: docket run asks`; neither row exists without a
  remembered review. The remembered review is the pod's own: `status` reads the approvals this
  pod made for the repository, so a second pod's approval does not change this pod's row.
  `status` reads the repository and the store, and writes nothing.
- `--all` reports the same summary for every registered pod, once per project rather than once
  per agent, with failed counts; `--all --json` also carries the fleet inventory
  (`timestamp`, `channels`, `agents`, `totalCostUsd`).
- `--history [--days N]` shows tokens per day (empty against the production driver; see
  cost-tracking.spec.md "Known gap").
- No current-directory match **MUST** fail with the actionable Pod targeting message (`Run
  'docket init' here, or pass --pod <name>.`).
- `docket setup --fix` remains workstation-wide technical health. It is not an implicit side effect
  of `status` or bare `docket`.
**Return**: 0 on success, 1 when current-project resolution fails, 2 on an unknown flag.

#### docket inbox
**Purpose**: List everything across every pod that needs the operator, in one call (see
operator-loop.spec.md "One inbox, derived")
**Syntax**: `docket inbox [--json] [--since <iso>] [--peek]`
**Behavior**: Derives, fresh on every call, a pure `InboxView` (operator-v2) over
every pod's tasks and pending escalations — `Needs you` (waiting/blocked tasks, pending
escalations no task carries and "approved, ready" tasks), `Failed`, `Done`, `Running`. A plain call advances a durable
cursor (`~/.docket/inbox-cursor.json`) so a repeat call's `Done` only shows newly finished tasks;
`--peek` reads without advancing it; `--since <iso>` overrides the stored cursor for this one
call without touching it. Each item prints the exact `docket task answer <id>` (or
`retry`, `run`) command and the full held command or question, never truncated. `--json` emits
the `GET /inbox` shape with `state` and `command` added to every item (and to each
`escalations` entry). A `needs_answer` task prints the question's options and
`docket task answer <id> --option <id>`.
**Output**: A human-readable summary by section, or (with `--json`) the bare `InboxView`
**Return**: 0 always — an empty inbox is not an error; 2 on an unknown flag

#### docket task
**Purpose**: Queue a pod's tasks, read each one's whole story (status, hops, evidence, runs,
corrections, interruption forecast, worktree, diff and trace) and move one forward: grant or
refuse what it waits on, answer its question, retry it or stop it
**Syntax**: `docket task <add|list|show|diff|trace|prune|answer|pregrant|retry|cancel> [args] [--pod <p>]`
A `<ref>` is a full task id, the short id `task list` prints, a unique prefix, or a run id
(`resolve_task`); an unknown or ambiguous ref exits 1 and an ambiguous one lists every
candidate with its pod. Without `--pod`/`DOCKET_POD` a ref is searched in every pod.
**Verbs**:
- `add "<text>" [--priority high|normal|low] [--brief FILE.json] [--external-ref REF]
  [--idempotency-key KEY] [--base-ref REF] [--pipeline NAME] [--gate COMMAND]
  [--max-tokens N] [--autonomy L3|L4|L5] [--var NAME=VALUE]... [--pod <p>]`: Queue the task on
  the resolved pod's own list (`~/.docket/workspaces/projects/<project>-lead/TASK_LIST.json`).
  The text is one argument; empty text or text over 500 characters exits 1, an unknown priority
  exits 2. `--brief` loads and validates the file as a `TaskBrief` (operator-v2); an invalid one
  exits 1 and enqueues nothing, a valid one is stored with the task. Prints the one-line
  interruption forecast (`NOTHING_WILL_ASK`, or `May ask you: ...` naming `docket task show`) and
  ends with `Next: docket run`
  `--autonomy` sets the level the task's pauses are decided at and exits 1 naming the ceiling when it
  is above the pod profile's (`security-gates.spec.md` "Autonomy levels");
  `--var NAME=VALUE` (repeatable) sets a pipeline variable for this task alone, stored as the task's
  `variables` and merged over the run's at claim (`operator-api.spec.md` "Arguments"); an argument
  with no `=` or an empty name exits 2 (as `run --var` does) and enqueues nothing, a repeated name takes
  the last value;
  The six addressing flags are stored on the task verbatim (`operator-api.spec.md` "Arguments");
  `--gate` takes the command string alone and exits 1 when empty. A second `add` whose
  `--idempotency-key` is already in the queue enqueues nothing and prints the existing id with
  `ok already queued`
- `list [--json] [--pod <p>]`: The pod's queue, every status: short id, priority, status, cost,
  the worktree path when one exists, description. `--json` prints `{"pod", "tasks": [...]}`
  (`cli-json-shapes.spec.md`)
- `show <ref> [--json] [--pod <p>]`: Status, hop evidence (evidence-v1), the
  runs that worked the task, its corrections, and the interruption forecast (what could pause
  it: matching `require_approval` policies, pipeline approval and `input` steps,
  the resolved `approvalMode`, the always-on high-risk classes, notifying
  channels). A task that waits on a person also prints a `Waiting on you` section: for each
  pending escalation its title, prompt, option ids and the command that answers it
  (`operator-loop.spec.md` area 11). A task with a recorded, unpruned worktree also prints its path, branch, base commit
  and the exact diff and merge commands (`git -C <path> diff <base>`, or, when the task record
  holds the git dirs docket recorded, `GIT_DIR=<gitDir> GIT_COMMON_DIR=<commonDir> GIT_WORK_TREE=<path> git diff <base>` (naming the common dir too, because the worktree's own `commondir` file is agent-writable), so
  the hint never reads the `.git` file the agent could rewrite); a task that ran in place prints no
  worktree block. A `run-` ref resolves its task and exits 1 when the run failed
- `diff <ref> [--json] [--pod <p>]`: Print the patch of the task's branch against the commit it
  started from, read from the codebase repository, so it works after the worktree is pruned.
  `--json` prints the whole diff object (`task`, `branch`, `baseCommit`, `head`, `patch`,
  `untracked`, `worktreePresent`; the same object operator-api.spec.md defines for the task's
  diff route). A task that ran in place, or whose branch no longer exists, exits 1. Every
  CLI-side git call on a present task worktree first registers the record's `gitDir`/`commonDir`
  (`trust_worktree`), so git reads the recorded repository and never the worktree's `.git` file
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
  and terminal run records of the pod past the same window (another pod's records are never
  touched; only the `docket start` sweep prunes run records fleet-wide) and the settled
  escalation records past the same window (`prune_settled_escalations`: the store keeps them in
  one directory, so this part is not limited to the pod, and a resolved record not yet applied is
  kept); `--days N` overrides the window and without `--traces` exits 2. `--dry-run` changes nothing. Ends with
  `Next: docket task list`
**Output**: Every bracketed identifier and every task description or failure reason is printed
literally, never interpreted as terminal markup
**Return**: `0` on success, `1` on error (no pod, unknown or ambiguous ref, invalid input)

**`task answer | pregrant | retry | cancel`**
The answering verbs (operator-loop.spec.md area 10, pod-dispatch.spec.md "Cancellation"):
**Syntax**:
- `docket task answer <ref> [text...] [--option <id>] [--field name=value]... [--decline] [--reason TEXT] [--pod <p>]`
- `docket task pregrant <ref> "<command>" [--tool bash] [--pod <p>]`
- `docket task retry <ref> [--pod <p>]`
- `docket task cancel <ref> [--pod <p>]`
**Arguments**:
- `ref` (required): a task id, its short id, a unique prefix, or a run id (`resolve_task`);
  every pod is searched unless `--pod` or `DOCKET_POD` names one. `answer` also accepts an
  `esc-*` escalation id, for a pause no queued task carries. The approval store has three
  production producers (pod-level/pipeline-step `require_approval` gates, a `pre_input` policy
  match at enqueue, the in-turn tool-call gate at `dispatch_tool`), each backed by an escalation,
  and is the only approval system. There is no `task approve` or `task deny`: an approval is
  settled with `answer --option`
**Behavior**:
- `answer` resolves an escalation (`resolve`, `operator-loop.spec.md` area 10): *ref* is an
  `esc-` escalation id, or a task, whose newest pending escalation it takes (a task that waits on
  none exits 1). On a question it answers it (text, `--field`, `--option`, `--decline`); on a
  TTY with no text, field or option it prompts, off a TTY it exits 1 naming `--option`; a
  `--field` that is not `name=value` exits 2. A consult that a running turn waits on in place
  (the task is `running`, not parked) is answered the same way, by its `esc-` id or by its task,
  through `resolve`: the record becomes `resolved` and the turn reads the answer.
  On an approval, gate or changed check, `--option approve_once|approve_task|deny` settles it
  (`approve_task` also allows the same call for the rest of the task) and `--reason` is carried
  with it, so a denied task reads `reason: approval denied: <reason>` (what the inbox's Failed
  entry shows); text, `--field` and `--decline` are refused there (exit 1). A repeat on an
  escalation already settled that way is a warning, exit 0
- `pregrant` records a single-use pre-grant for one exact command ahead of dispatch
  (`record_pregrant`) and resolves nothing; a task not in the pod exits 1
- `retry` puts a `failed` or `blocked` task back to `pending`, keeping the hops it finished, and
  audits `task.retry`; a task in any other status exits 1
- `cancel` requests cancellation of the task's live run (one `runs.cancel` audit entry; every
  tracked process group is killed) and settles a stale `running` claim whose dispatcher is gone
  as `failed`. A task parked in `waiting_input` or `waiting_approval` is cancelled too: it
  ends `cancelled` (the status a cancelled live run gives), its pause stops waiting (the approval
  record behind it is denied) so `docket inbox` no longer lists it, no hop runs, and one
  `task.cancel` audit entry names the project, task, prior status and channel `cli`
**Output**: One confirmation line. `answer` (except a denial and a changed-check approval, which
ends its task `done`), `pregrant` and `retry` end with the run hint: `docket is running and will
pick it up` when `docket start` is running, else `Next: docket run --pod <p>` on stderr; `cancel`
ends with `Next: docket task retry <id>` when it settled a stale claim
**Return**: 0 on success (an escalation already in the requested state is a warning, exit 0); 1 on
an unknown or ambiguous ref, a task that waits on nothing, an escalation already resolved the
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
Before dispatching (not with `--dry-run`), `run` compares the pod's recorded `configDigest` with
the digest of its repository's `.docket/` when that is the recorded `configSource`: unchanged
runs; a change that adds only (roles, policies, skills, settings, pipeline text) is applied with
the single line `-> Updated from the repository: <kind name>[, ...].`; a changed
run-on-this-machine item (pod-blueprints.spec.md requirement 12) is shown as before/now on a
terminal and `Allow the new version? [y/N]` asked, `y` remembering and applying it and `n`
running the allowed version (`-> Running with the version you allowed on <date>.`); off a
terminal the allowed version runs and `! The repository changed a command that needs your OK.
Running with the version you allowed on <date>. To review it, run docket run on a terminal.` is
printed. A shell-like `allowCommands` in the changed repository is never applied. Only the typed
`run` reads `.docket/`: `docket start --dispatch` and every other dispatch path never do
(ADR 0012).
**Output**: the banner of runnable steps, one line per task, one summary line, one `Next:` line.
**Return**: `0` on success or an expected pause, `1` when a task ended `failed`, the run record
ends `failed`, the pod is unknown, the `--pipeline` file is invalid or no endpoint is
configured, `2` on an unknown flag or a `--var` that is not `key=value`.

#### docket pod

**Purpose**: The pod: its roster, its settings and its configuration of record
**Syntax**: `docket pod <show|add|remove|reset|set|unset|delete|update|export|validate|plan|check|recipes|roles|policies|memory|routine|records> [args] [--pod <p>]`

A real Typer sub-app: every verb declares its arguments and options, a
bare `docket pod` prints help, an unknown verb or flag is a usage error (exit 2), and every leaf's
help ends with an `Example:` line. Each verb that acts on a pod (every verb but `validate` and
`recipes`, which take no `--pod`) resolves it through `--pod`/`-p`, `DOCKET_POD`, then the
current directory (Pod targeting above); there is no positional pod id.
Each state-changing verb ends with one `Next:` line on stderr.

- `show [MEMBER] [--json]`: the pod, or one member's whole effective configuration
  (agent-lifecycle.spec.md "Pod Information"; the JSON shapes are `docket pod show --json` and
  `docket pod show <member> --json` in cli-json-shapes.spec.md). Read-only, no `Next:` line.
- `add ROLE [--count N] [--verify "<cmd>"]`: add members to the existing pod; never creates a
  project. `--verify` is implementer-only (warned and ignored otherwise). An unknown role prints
  one line and exits 1; a second Lead is refused.
- `remove MEMBER [--yes]`: remove one member. Confirms on a terminal; off one it exits 1 naming
  `--yes`. The Lead is refused ("delete the pod instead").
- `reset MEMBER [--yes]`: rebuild the member's workspace files from metadata and reset its
  ledger; no model call, and `MEMORY.md`, `memory/` and the pod's memory are left alone
  (agent-lifecycle.spec.md "Member Reset").
- `set KEY VALUE [--member ID]` / `unset KEY [--member ID]`: the one writer of every
  `PodSettings` key (`budgetUsd` included); `verify` with `--member` writes or clears an
  implementer's `verifyCmd` (pod-blueprints.spec.md "Pod settings: set and unset").
- `delete [--confirm NAME]`: destroy the pod. The name is typed on a terminal; off one,
  `--confirm NAME` is required. A member id is refused; there is no picker.
- `memory <list|approve|refuse|revert|reset>`: the operator's controls over the pod's learned
  memory (workspace-structure.spec.md "Pod memory"), a sub-group of `pod`, not a top-level
  command. `memory list [--status accepted|pending|refused] [--json]` prints every entry (id,
  kind, status, subject, note, reason) and is read-only; `memory approve ID` accepts a pending
  entry; `memory refuse ID --reason TEXT` refuses a pending one; `memory revert ID` takes an
  accepted one out of every prompt (it stays as a refusal); `memory reset [--yes]` removes every
  entry after confirmation (off a terminal, `--yes` is required, else exit 1). An unknown id or
  an entry in the wrong state prints one line naming it and exits 1; an unknown `--status` exits
  1. Each state-changing leaf ends with a `Next:` line and is audited as `pod.memory.<action>`
  with actor `cli`.

- `routine list [--json]`: the pod's routines (pod-dispatch.spec.md "Routines"), a sub-group of
  `pod`, read-only: one row per routine with its name, schedule, tz, next slot (UTC), last fired
  slot (`-` when it never fired) and `enabled`, nearest scope first; a file in the pod's scopes that
  does not load is listed with its error and exits 1. `--json` prints a list of `{name, schedule,
  tz, scope, enabled, catchUp, overlap, next, last}`. A pod with none prints `No routines in
  pod '<pod>'.` and exits 0. A routine fires only under `docket start --dispatch`.

- `records [SET] [--sql "<SELECT>"] [--limit N] [--csv FILE] [--json]`: what the pod keeps in its
  records file (pod-records.spec.md "The CLI"), read-only. With no `SET`, one row per set the pod's
  `records/` documents declare: name, rows, columns, key and description; `--json` prints a list of
  `{name, rows, columns, key, description}`, a pod with none prints `No records in pod '<pod>'.`.
  With a `SET`, its rows in `_id` order, at most `--limit` (default 50) and a line saying how many
  were left out; `--sql` replaces the statement and runs it on a read-only connection, so anything
  but one `SELECT` exits 1 with the rows unchanged; `--csv FILE` writes every row of the statement
  to FILE and prints the count; `--json` prints `{set, columns, rows, cut}`. A set no document
  declares exits 1 naming it. A pod's agent cannot yet read or write these records; the tools are a
  later card.

**Return**: `0` on success, `1` on any refusal or error (unknown pod, member or role; Lead
removal; missing confirmation), `2` on a usage error.

**`pod update`**
**Purpose**: Install configuration onto the pod, or re-sync its instructions
**Syntax**: `docket pod update [NAME|DIR|FILE] [--dry-run] [--json] [--accept CODE] [--pod <p>]`
**Arguments**:
- `NAME|DIR|FILE` (optional): a directory (`roles/*.yaml`, `policies/*`, `pipeline.yaml`, a small
  `pod.yaml` naming `members`/`settings`/`pipeline`/`description`/`exporters`) or, failing that, a
  recipe name resolved exactly as `docket init --recipe` resolves it (an unresolvable name exits
  1 naming both scopes' recipes), is planned and written whole; an existing file is one `kind:
  role` or `kind: policy` document installed into the pod's own scope (any other kind exits 1);
  with no argument, members whose stored template version is stale are re-rendered from the
  current archetype and metadata (`INSTRUCTIONS.md` is never touched)
**Options**: `--dry-run` prints the plan or the diffs and writes nothing; `--json` prints `{"items":
[{kind, name, action, note}]}` (exit 1 with no argument); `--accept CODE` allows exactly the
run-on-this-machine items whose review code is CODE, off a terminal. A directory that is not a
shipped recipe goes through the operator's review exactly as `docket init` does
(pod-blueprints.spec.md requirement 12; the repository is the pod's recorded codebase): exit 2
with the items and code off a terminal without `--accept`, a `[y/N]` ask on one. A `--dry-run`
writes nothing and asks nothing
**Output**: For a directory or recipe: a header (`Apply plan`, the directory's `description` when
set, `summarize_recipe`'s derived summary line), one `[action] kind: name` line per
item, then one line per named exporter — its state from `activation_state` and,
unless `enabled`, the exact `docket setup export enable <name>` command; nothing is ever written
to `docket-exporters.json` from this path. Validates every role, the roster the pipeline would
resolve against once `members` join, every setting, and every `exporters` name before writing
anything; idempotent (a second run plans every item `skip`). A state-changing run ends with `->
Next: docket pod show`. See `pod-blueprints.spec.md`, "Pod manifests: apply"
**Return**: 0 on success, 1 on an invalid document, an unresolvable name, or no pod; 2 when the
operator's review stops the update

**`pod export`**
**Purpose**: Write the pod's own configuration into a directory
**Syntax**: `docket pod export [DIR] [--force] [--pod <p>]`
**Output**: This pod's own scope (its `records/` documents too, byte for byte; never a row of
them, which stay in the pod's `records.sqlite`, and the output says so), every YAML file in the short form with a `# yaml-language-server:`
header — pod-overlay `roles/<name>.yaml` (+ paired `roles/<name>.md` instructions), this pod's
own `policies/<stem>.yaml`, a bound `pipeline.yaml` copy (if any), a `pod.yaml` naming `kind: pod`,
`name`, non-Lead `members`, every non-default `setting`, this pod's recorded `exporters` (when
set), and the four config-v1 JSON Schemas copied into `.schemas/` — into `DIR`, the same shape
`pod update` reads back. `DIR` defaults to `<codebase>/.docket`, or `<codebase>/.docket/teams/<pod>/`
when that directory exists or the repository keeps `.docket/teams/`. Global scope (the operator's own role
overlay, fleet-wide policies, other pods) is never exported. Refuses a non-empty `DIR` (including
the default) unless `--force`. Ends with `-> Next: docket pod validate <DIR>`. See
`pod-blueprints.spec.md`, "Pod manifests: export"
**Return**: 0 on success, 1 on a refusal or no pod

**`pod validate`**
**Purpose**: Validate any configuration document — role, pipeline, policy, pod manifest, MCP
server — or every document in a directory (see `config-format.spec.md`); one validator for every
kind (`validate_path`)
**Syntax**: `docket pod validate [PATH]`
**Arguments**:
- `PATH` (optional): A directory to validate every document under (default `<cwd>/.docket`
  when it exists, else the current directory), or a single file to validate alone
**Output**: One line per file — `ok <file> (<kind> <name>)` on stdout, or its error on stderr —
invalid files first, plus a warning per file loaded without a `kind:` key. A pipeline whose step
`model` names a provider absent from the catalog is invalid. A directory target also prints,
after the per-file lines, `summarize_recipe`'s derived summary line (pod-blueprints.spec.md)
and the directory's own `description` when its `pod.yaml` sets
one; a file target prints neither
**Return**: 0 if every file is valid, 1 if any file is invalid or the target does not exist

**`pod plan`**
**Purpose**: Show the steps the pod's pipeline would run, from the real executor
(`resolve_plan`/`render_plan`) — never a second, drift-prone pretty-printer. See
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
**Purpose**: List and inspect the recipe library (ADR 0013) -- read-only discovery over both
scopes `resolve_recipe` reads. Installs, removes, or fetches nothing; `docket pod update`/`docket
init --recipe` remain the only writers
**Syntax**: `docket pod recipes [NAME|DIR] [--json]`
**Output**: With no argument, a table (NAME, SCOPE, BRINGS, DESCRIPTION) of every recipe
`list_recipes()` returns -- the operator's own `$DOCKET_HOME/recipes/<name>/` before the shipped
library, nearest scope wins by name, sorted by name. BRINGS is derived, never a stored field: the
non-empty parts of the recipe's summary joined with `+` in the order roles, policies, members,
pipeline, plugins, skills, mcp-servers, settings (`roles+policies+members+pipeline`, `policies`,
`members+pipeline+skills`, ...; `nothing` for an empty directory). With an argument, the recipe resolved through the same
`resolve_recipe` order `docket pod update` uses: its scope, directory, derived summary line
(pod-blueprints.spec.md), one line per exporter its `pod.yaml` names — the same state lines
`docket pod update` prints — and `README.md` body when present. `--json` prints a list of objects
carrying `name`, `scope`, `brings`, `directory`, `description`, the counts `roles`, `policies`,
`members`, `plugins`, `skills`, `settings`, the `pipeline` name and the `mcp_servers` list; with
an argument one such object plus a `readme` field
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
**Options**: `--plugins` adds the predicate plugins `discover` finds — global
(`$PLUGINS_DIR`) first, then the pod's own `config/plugins/`; never a codebase's own
`.docket/plugins/`; combined with `ID` it is a usage error (exit 2)
**Output**: The installed policies in `$POLICIES_DIR` plus the pod's own policy directory (a pod's
policies only ever add), or one policy's JSON; `--json` prints a list of
`{id, hook, action, description}` (with `--plugins`, `{policies, plugins}` where each plugin is
`{name, scope, file, sha256}`)
**Return**: `0` on success, `1` on an unknown `ID` or a `PluginError`, `2` on a usage error

#### docket log
**Purpose**: Show recent recorded operator events, or verify the log's tamper-evidence chain
(see audit.spec.md for the exact recorded families and the coverage gap)
**Syntax**: `docket log [N] [--json|--summary]` · `docket log verify`
**Arguments**:
- `N` (optional): Number of recent entries to show (default: 20)
**Options/Actions**:
- `--json`: Emit the raw JSONL passthrough instead of a formatted table
- `--summary`: Print the measured figures instead of the entries: `tokens per accepted task` and
  the cache-hit ratio (cost-tracking.spec.md requirement 6); refused (exit 2) together with `--json`
- `verify`: Walk the current log's `seq`/`prev_hash` hash chain and report the first broken link,
  instead of listing entries
**Output**: Timestamped log of mutating operations, or a chain-verification result
**Return**: 0 for the listing form; for `verify`, 0 when the chain is clean (or no log exists
yet), 1 when a broken link is detected; 2 for an argument that is neither a count nor a verb,
the message naming it (`'abc' is not an entry count or a command. Usage: docket log [N] | verify`)

#### docket setup
**Purpose**: Set up this workstation. `docket setup` with no verb is the first run: a flow, not a
catalog, idempotent, in two modes chosen by the terminal (the interaction contract's rule).
**Syntax**: `docket setup [--json] [--fix]` · `docket setup profile|shell|provider|model|sandbox|notify|export|mcp|secret|service ...`
**Bare `setup`** always starts with a report: one line per piece with its state and the exact
command that fixes it — the model endpoint (the only required piece: a provider, its credential,
and `lead`/`implementer` resolving to a model), notifications (`console only (nobody is told)` is
a warning), the sandbox (state and the backend found: landlock, seatbelt or a chosen docker), shell completion and the
background service. The report is computed by `readiness()`, which prints and writes nothing;
`init` and `run` read it.
- **On a terminal** it continues by asking only for what is missing, required first: choose a
  provider (the catalog's built-ins plus `local`), the credential (stored 0600, never echoed),
  probe `/models`, apply the preset and confirm the two roles resolve; then the optional pieces,
  each defaulting to `N` and asked only while that piece is not ready: desktop notifications
  when a desktop session exists, Telegram, the sandbox when a backend exists, shell completion.
  It prints every command it runs (`ran: docket setup provider add anthropic --credential`) and
  ends with `Ready.` and `→ Next: cd into a repo and run docket init`. A run where every piece
  is ready prints `Ready.` and asks nothing; an optional piece left off is offered again on the
  next run.
- **Off a terminal** it prints the report with the commands and exits 1 when the model endpoint
  is missing, 0 otherwise; it writes nothing. `--json` emits the report
  (`{"ready": bool, "pieces": [{name, ok, reason, command}]}`) with the same exit code.
- `--fix` tightens the modes of `fleet.json` and the secrets files, installs the missing baseline
  guardrail policies, then runs the health checks, re-syncing the dispatch ledger from
  `TASK_LIST.json` (not with `--json`, which only reports it). It writes no workspace file other
  than a missing or stale `WORKFLOW_AUTO.md`, which the text report re-seeds; a pod member's
  missing managed file is named with `docket pod update --pod <p>` as its remedy. Under `--json`
  the repair lines go to stderr. Its option help lists only these repairs.
The wizard has no logic of its own: it calls the functions the verbs call, so every store keeps
one writer.

**`setup provider`** — `add <name> [url] [--credential KEY] [--model ID] [--ctx N]
[--max-tokens N] [--no-preset]` does the whole intent: store the credential (the flag, else the
provider's environment variable, else a hidden prompt on a terminal; off a terminal with none it
exits 1 naming `--credential`), probe `<url>/models` with it and classify the result
(model-profiles.spec.md "Provider readiness" 3), register the provider, then apply the provider's
preset unless `--no-preset` and print which role resolves to what, plus each pod whose members the
preset moved (model-profiles.spec.md "Provider catalog" 3). `add <file.yaml>` registers a
`kind: provider` document. `--ctx` and `--max-tokens` have no default: a given value is the
model's declared limit, an absent one is what the registration probe observes, else unknown.
`list [--json]`, `show <name> [--json]` (one row per model with `window` and `output`, each
naming its source: declared, observed on a date, or unknown), `remove <name> [--yes]`
(confirms on a terminal; off one it exits 1 naming `--yes`), `export <name> [<file>]`,
`rotate <name> [--credential KEY]`.
**`setup model`** — bare or `list [--json]` shows the role→model table (role, model, price,
source, why); `set <role|default> <provider/model>`; `preset [name]` lists or applies a provider
preset to every role; `reset [--yes]` restores the built-in policy.
**`setup sandbox`** — bare or `status [--json]` is a read: the gate is always active, plus the
isolation state, the network mode and a per-platform probe report: the backend found
(`landlock (kernel 6.14)`, `seatbelt`, `docker`) or what is missing (`Linux: a kernel with
Landlock (>= 5.13)`; `macOS: /usr/bin/sandbox-exec`; `Windows: use WSL2; native runs without a
sandbox`), then the `Sandbox` line. `--json` adds `platform`, `kernel`, `available`, `missing`,
`line` and `hint`. `on` needs a usable backend (landlock on Linux 5.13+, seatbelt on macOS, or a
chosen reachable docker; exit 1 naming the fixes otherwise), `off`, `backend auto|docker` (records
the choice in fleet.json; `auto` is landlock or seatbelt, `docker` is docker only; any other word
is a usage error, exit 2), `network none|open` (any other word is a usage error,
exit 2), `classes` lists the high-risk action classes, `read add PATH` records a resolved path
every sandbox may read and execute but never write (a toolchain under the home; a refused path
exits 1 naming why), and `read remove PATH` drops a recorded one (a path that is not recorded
exits 1). Writes are audited as `gates.isolate`, `gates.backend`, `gates.network` and
`gates.read`. See security-gates.spec.md.
**`setup profile [lights-out|attended]`** — bare is a read of the recorded profile (`attended` when
nothing is recorded); `lights-out` records it in fleet.json and prints each fleet-level
requirement (isolation, network) still unmet with its fix (exit 0: recording is not refusal;
the per-pod requirements show in `status`); `attended` clears the record; any other word is a
usage error (exit 2). Writes are audited as `gates.profile`. `pod set profile lights-out|attended`
sets a pod's profile and refuses `attended` under a global `lights-out` (exit 1). See
security-gates.spec.md "Profiles".
**`setup shell <bash|zsh>`** — prints the completion script generated from the live command tree;
any other shell is a usage error (exit 2). Enable it with `eval "$(docket setup shell bash)"`.
**Return**: 0 on success; 1 when the model endpoint is missing off a terminal, a provider is
unreachable, a required value or confirmation is missing, or the sandbox has no backend; 2 on a
usage error.

**`setup notify`**
**Purpose**: Manage `kind: channel` documents -- notification/conversation/decision
destinations -- and connect Telegram in one step (see operator-loop.spec.md "Notifications" and
telegram-integration.spec.md)
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
document) by authenticating -- the requested experience is "the YAML exists,
I only put the key" (observability-export.spec.md "Activation"); and show or change what an
exporter shares beyond bare structure, as a confirmed command
(observability-export.spec.md "Privacy commands and disclosure")
**Syntax**: `docket setup export <list|show|enable|disable|test|add|remove|export|privacy|preview>`
(a real sub-app of `setup`; bare `docket setup export` prints its help)
**Subcommands**:
- `list [--json]`: Table (NAME, DIALECT, STATE, CREDENTIALS, SCOPE, SHARES) of every catalog
  exporter, state from `activation_state`, SHARES its `privacy_label`; `--json`
  prints the same fields as objects (not including SHARES)
- `show <name> [--json]`: One exporter's effective document (dialect, endpoint, auth, enabled,
  state, aliases, privacy label), its scope, today's health counters, and a "Leaves this host"
  disclosure of every content class (`describe`: granted or not, its example
  attributes, and the fixed line naming that credentials and secret-shaped values are never
  sent); `--json` adds `missingCredentials` and the raw `health` record
- `enable <name> [--endpoint URL] [--privacy <level>|--share a,b] [--events ...] [--no-verify]
  [--yes]`: For each of *name*'s credentials that resolves to no value, prompts on a TTY and
  stores it in the 0600 secret store, or on a non-TTY names the missing credentials and exits 1
  writing nothing. A `--privacy`/`--share` that widens what the exporter shares
  (`is_widening`) follows the same confirm-or-refuse rule as `privacy`. Then probes
  the (possibly overridden) endpoint and classifies it exactly like `docket setup provider add`;
  a transport failure exits 1 and writes nothing unless `--no-verify` is given. On success,
  writes only `{kind, name, enabled: true, <overrides given>}` to the global catalog through
  `enable_exporter` -- every other field is inherited from the built-in of the
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
  change never asks. Writes only the changed field(s) through `set_privacy` and
  audits `exporter.privacy` (`name`, `from`, `to`, `host` -- never content)
- `preview <name> [--session <id>] [--level minimal|actions|conversation|full] [--share a,b]
  [--json]`: Project a real local session (default: the newest trace under `TRACES_DIR`,
  across every project) through *name*'s resolved `ExportPolicy` -- or the given `--level`/
  `--share` override, which is never written -- and print each span's attributes with their
  content class, content truncated to 200 characters for display, plus a footer counting spans,
  attributes per class, and total bytes; `--json` prints the exact OTLP/HTTP document the exporter would send (`encode`)
  byte-for-byte. No network call, no write, no audit entry (observability-export.spec.md
  "Preview")
**Output**: Exporter listing, one exporter's detail, an enable/disable/test/add/remove/
privacy confirmation or refusal, or a preview of what a destination would receive
**Return**: 0 on success, 1 on an unknown exporter, a missing credential, an unreachable
endpoint, a refused widening, or (`preview`) an unknown session

**`setup secret`**
**Purpose**: Store, list and remove a secret under any name, so a `secret:<name>` reference
(`api-keys.spec.md`, "A secret stored under any name") has a value to resolve
**Syntax**: `docket setup secret <set|list|remove>` (a real sub-app of `setup`)
**Subcommands**:
- `set <name> [--stdin]`: The value comes from `--stdin` or a hidden prompt on a terminal, never
  from an argument; a value given as a second positional exits 2 and is not echoed. Off a terminal
  without `--stdin`, an empty value, a name outside `[A-Za-z0-9_.-]+` or a refused backend exits 1
  writing nothing
- `list [--json]`: Each stored name with its added and rotated times; never a value; `--json`
  prints an array of `{name, added_at, rotated_at}`
- `remove <name>`: Delete a stored secret; a name not stored exits 1
**Return**: 0 on success, 1 on a refused name, value or backend, 2 on a value given as an argument

**`setup mcp`**
**Purpose**: Configure the external stdio MCP tool servers docket connects to as a client, whose
tools reach a live turn through the same `dispatch_tool` chokepoint (`mcp-client.spec.md`)
**Syntax**: `docket setup mcp <list|add|remove>` (a real sub-app of `setup`)
**Subcommands**:
- `list [--json]`: Every configured server's name, launch command, `kind`, `tools` allow-list
  (empty = all) and timeout; `env` values are masked; `--json` prints the same as objects
- `add <name> [--env K=V ...] [--timeout S] [--kind read|write] [--tools NAME,...]
  -- <command> [args]`: Everything after `--` is the launch command, verbatim. `--kind` declares
  the server's trust level (default `write`). A bad `--kind`, a malformed `--env`,
  a bad or duplicate name exits 1 writing nothing; a missing command exits 2
- `remove <name>`: Remove a configured server; an unknown name exits 1
**Return**: 0 on success, 1 on a refused value, 2 on a usage error

**`setup service`**
**Purpose**: Register the external HTTP services a pod may reach, each declared by a `kind: service`
document (`service-client.spec.md`); this registers and lists them, it makes no call
**Syntax**: `docket setup service <add|list|remove>` (a real sub-app of `setup`)
**Subcommands**:
- `add <file.yaml>`: Load and store one document, audit `services.add`, and print its operations
  with their access. A document that fails the format, a name already stored and a name an MCP
  server holds exit 1 writing nothing; a `${secret:<name>}` reference whose secret is not stored
  warns and succeeds
- `list [--json]`: Each stored service's name, base URL, operation count, auth header and the
  secret names it references, never an auth value; `--json` prints the same as objects
- `remove <name>`: Delete a stored service and audit `services.remove`; an unknown name exits 1
**Return**: 0 on success, 1 on a refused document or name, 2 on a usage error

#### docket start
**Purpose**: Start the background service — refresh fleet status, serve the local HTTP API and
optionally drive pod dispatch pipelines
**Syntax**: `docket start [--port <n>] [--bind <addr>] [--interval <s>] [--dispatch] [--telegram] [--mcp] [--token-file <path>]`
**Options**:
- `--port`/`-p <n>`: Listen port for the HTTP API (default: 7331)
- `--bind <addr>`: Listen address for the HTTP API (default: `127.0.0.1`, loopback only; any other address is reachable off this host)
- `--interval`/`-i <s>`: Sweep refresh interval in seconds (default: 30)
- `--dispatch`: On each refresh, also run every pod's pending tasks through its pipeline (real, costed LLM turns; budget-gated and traced). Off by default — plain `docket start` never dispatches on its own.
- `--telegram`: Long-poll docket's own Telegram bot for `/status` `/delegate`
  `/answer` (needs the stored `TELEGRAM_BOT_TOKEN` credential; without it the channel stays
  idle; see telegram-integration.spec.md)
- `--mcp`: Serve docket's control plane as an MCP stdio server instead of the HTTP service
  (`mcp-server.spec.md`); it prints nothing to stdout but JSON-RPC and exits 2 when combined with
  `--dispatch`, `--telegram` or `--token-file`
- `--token-file <path>`: Write the Bearer token for the authenticated routes to this file (0600)
  instead of printing it
**Output**: Serves the HTTP API on `http://<bind>:<port>/` — three unauthenticated read routes
(`/status.json`, `/metrics`, `/health`); every other route needs the Bearer token. The route
contracts live in serve-read-api.spec.md and operator-api.spec.md.
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
**Output**: One line, then `Next: docket start` after a stop; nothing running is reported as
such and is not an error
**Return**: 0 when stopped or nothing was running; 1 when the process is still alive after the
second signal

### Help

`docket --help` shows the tagline and the ten commands in three panels, in this order: **Daily**
(`init`, `status`, `inbox`, `task`, `run`), **The pod** (`pod`, `log`) and **Machine** (`setup`,
`start`, `stop`). Each command declares its panel where it is registered. The project
description in `pyproject.toml` is the same tagline.

An unknown top-level word is a usage error (exit 2, `No such command`). Its message offers, from
the live command tree only, the top-level commands the word resembles and every group that has a
verb of that name (a top-level `add x` names `docket task add` and `docket pod add`; a top-level
`answer` names `docket task answer`). A word that resembles nothing and is no verb gets no suggestion.

## Output Formats

### The console voice

One console module (`ui`) owns the symbols, colours and layout.

- **Five symbols**: `✓` done, `✗` failed or refused, `⚠` attention, `→` next step, `·` detail.
- **Five colour roles**: `success`, `error`, `warn`, `accent` (names, ids, commands), `dim`.
- **Shapes**: `header(noun, name)` renders `docket · pod myapp`; `section(title)` renders one of the
  shared section names `Needs you`, `Running`, `Done`, `Failed`; `table(rows, columns)` wraps cells
  at word boundaries and never truncates a cell (a word longer than its column folds onto the next
  line); `error(what, do)` renders `✗ <what>. <do>` on **stderr**
  (without `do`, `✗ Error: <what>`); `hint(command)` renders `→ Next: <command>` on stderr.
- **Plain mode**: when stdout is not a TTY or `NO_COLOR` is set, output carries no colour, no
  boxes and only the ASCII symbols `ok`, `x`, `!`, `->`, `-`.
- **Tagline**: `ui.TAGLINE` is "docket runs teams of coding agents and governs what they may do".
- **Copy rule**: a command that changes state ends with exactly one `→ Next:` line (on stderr,
  silent under `DOCKET_NO_HINTS=1`); a read command ends with none; an error is one line that says
  what happened and what to do.
- Rich markup literals outside the console module are counted by a shrink-only guard, so their
  number can only fall.

There is no debug output level.

### JSON Output Schema

When `--json` is specified, commands emit bare JSON objects or arrays — **no envelope wrapper**.
There is no `{success, data, error, version}` outer object. Each command's actual output shape
is documented in [specs/data/cli-json-shapes.spec.md](../data/cli-json-shapes.spec.md).

Key naming: the keys docket builds for CLI output are camelCase (`costUsd`, `totalUsd`,
`budgetUsd`, `sessionKey`), with one exception, `mcp_servers` in `pod recipes --json`. Records
passed through as stored keep their stored keys: trace events in `task trace --json` (`event_type`,
`agent_role`, `cost_usd`) and the raw JSONL of `log --json`.

### Table Output Format

Tables align every column left and wrap cells at word boundaries (`table` above); no column is
right- or centre-aligned.

## Environment Variables

The complete, code-derived table lives in the generated `docs/commands.md` ("Environment
Variables", checked by `scripts/gen_cli_docs.py --check`). The variables a CLI user most often
sets:

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCKET_HOME` | Base directory for all Docket-owned state | `~/.docket` |
| `DOCKET_POD` | The pod a pod-scoped command acts on when `--pod` is absent (Pod targeting) | unset |
| `DOCKET_LLM_BASE_URL` / `DOCKET_LLM_API_KEY` | Process-wide override of the OpenAI-compatible chat endpoint `DocketDriver` talks to (`resolve_endpoint`) | (per-provider resolution) |
| `DOCKET_TOOL_MAX_OUTPUT_CHARS` | Ceiling on one tool result's text before visible truncation | `30000` |
| `DOCKET_NO_TRACE` | `1` disables trace-store writes | unset |
| `DOCKET_NO_HINTS` | `1` silences every `→ Next:` line | unset |
| `DOCKET_SERVE_TOKEN` | Fix `docket start`'s Bearer token instead of generating one | unset |
| `NO_COLOR` | Any value selects plain mode (The console voice) | unset |

`DOCKET_APPROVAL_MODE` is not an environment variable despite its name: it is a key of the `env`
dict `run_turn` receives, never read from the process environment.

## Return Code Convention

docket uses a deliberately flat convention — the printed message, not the exit code,
distinguishes error kinds:

| Code | Meaning | Used By |
|------|---------|---------|
| 0 | Success | All commands |
| 1 | Any failure (not found, permission, refused confirmation, driver/model error, …) | All commands |
| 2 | Usage: an unknown command, flag, subcommand or action, or a required action word left out | All commands |

No other exit codes are produced by docket's own commands. Typer/Click's own usage errors (an
unknown option, command or verb, before any command body runs) exit `2`; the unknown-word
message names the live commands the word could mean (Help above). A few refusals reuse `2`
because they stop before any work for a reason the operator settles by giving different input:
`init` and `pod update` when the operator's review is not given, and `start --mcp` with a flag
it cannot honour.

## Validation

Input validation rules that every command MUST enforce before performing side effects.
The authoritative rule set lives in [input-validation.spec.md](../validation/input-validation.spec.md);
the contract-level summary follows.

### Pod ID Validation
- A pod id is the slug of the given name (see `docket init` Arguments): non-empty, at most 64
  characters, matching `^[a-z0-9]+(?:-[a-z0-9]+)*$` (`validate_project_id`). No id is reserved.
- A member id is `<pod>-<role>` (with a numeric suffix for a second member of a role) and so
  matches `^[a-z0-9][a-z0-9-]*[a-z0-9]$`.

### Path Validation
- A location given to `init` is tilde-expanded and recorded as given; it is not made absolute
  and a codebase location is not checked for existence or readability (see input-validation.spec.md)

### Model Validation
- Must be well-formed `provider/model-id` (e.g. `anthropic/claude-sonnet-4-6`)
- docket does not itself validate that the named model exists at the provider; it accepts any
  well-formed string and warns if pricing is unknown (an unresolvable model surfaces as a
  driver-level error the first time a turn actually runs, not at validation time)
- A bare word such as a tier name (`economy`, `standard`, `premium`) is malformed and exits 1
  like any other (see input-validation.spec.md)

### Numeric Validation
- Budget values: non-negative USD (`pod set budgetUsd N`)
- History window: non-negative days (`status --history --days N`)
- `run --timeout`: at least 1 second; no upper bound

## Interactive Features

### Confirmation Prompts
One interaction contract serves every command:

- `confirm(action, *, yes, typed=None)`: with a TTY, a `y/N` prompt, or the typed name when
  `typed` is given; without a TTY it refuses with exit 1 naming `--yes` (or `--confirm <name>`
  when `typed` is given). `yes=True` returns without prompting. Every confirming verb uses it.
- `emit_json(obj)`: plain `json.dumps` to stdout, never Rich.
- `require_pod(pod)`: the pod from `--pod`, then `DOCKET_POD`, then the cwd; with none, exit 1
  naming what was looked for.
- `is_tty()`: whether stdin is a terminal; the one reading every prompting flow consults.
- `next_step(command)`: the one `→ Next:` line described under "The console voice".

Besides `confirm`, only a fixed set of flows prompt, each after checking for a terminal itself:
the first-run `setup` flow, channel and exporter enabling, credential entry, `task answer`,
`init`'s review and desktop offer, `run`'s changed-command ask and the in-place approval. A
shrink-only guard counts the direct prompt calls per module, so a new prompt site is a
deliberate change.

## Foreground dispatch progress and in-place approval

### Rendering

`docket run` MUST
render one line per event on stderr while the dispatch runs, whenever stderr is a real TTY or
`--progress` is given:

- `session_start` → `▶ <task> …`, where `<task>` is the short id (the form `task list` prints)
  of the task the session id names (`agent:<project>:<task-id>`), or the role when the session id
  names no task
- dispatch's hop marker (the `tool_call` event whose JSON payload has exactly the keys `hop` and
  `agent`, written just before each hop runs) → `  ▶ <hop> …`, indented two spaces under the
  task line
- `escalation_asked` for an `approval` → `⏸ <role> wants: <prompt> · <esc-id> · denies in <t> ·
  docket task answer <esc-id> --option approve_once`, where `<t>` is the time left until the
  escalation's `expiresAt` (seconds under an hour, else hours; absent when it has none)
- `escalation_asked` for a `gate` or `check_changed` → `⏸ <role> needs approval: <prompt> ·
  <esc-id> · denies in <t> · docket task answer <esc-id> --option approve_once`
- `escalation_asked` for a `consult` or `input` → `⏸ <role> asks: <title>: <prompt> · options
  <ids> (recommended <id>) · docket task answer <task> --option <id>`, the `options` part only
  when it offers any (operator-loop.spec.md area 11 item 10)
- `session_end` → `■ <task> finished — status=<status>`, `<task>` resolved as for `session_start`

No other trace event renders a line; in particular the agent loop's own `tool_call` events do not.
There is no hop-end line: nothing in the trace marks a hop's end without a new event type. Without a TTY and without `--progress`, no worker
thread runs, no trace subscription opens, and stdout/stderr MUST stay byte-identical to a build
with no progress view (the no-change oracle the golden suite pins).

### In-place approval

When the rendering above is active, stdin is also a real TTY, and `--no-prompt` is absent, every
approval, gate or changed-check `escalation_asked` event additionally prints `[a]pprove  [d]eny
[Enter] keep waiting` and reads one line from stdin. `a` MUST resolve the escalation
`approve_once` on channel `cli` and `d` `deny` — the same `resolve` `docket task answer`
performs, so an in-place answer is indistinguishable from a second terminal's. Any other input
(including a bare Enter) keeps waiting. A pause already resolved through another channel prints
one dim notice (`(already resolved elsewhere)`) and the prompt keeps waiting on the next event; it
MUST NOT raise out of the dispatch call. That covers a pause resolved the same way, one the
opposite decision already won, one that ended, and one with no record.

### Flags

- `--progress` forces the rendering above even when stderr is not a TTY.
- `--no-prompt` disables the in-place prompt even when stdin is a TTY; rendering is unaffected.

Neither flag applies to a non-interactive dispatch caller (`start
--dispatch`, a due schedule, the MCP `dispatch` tool) — this section governs only the foreground
`docket run`.

## Error Message Standards

### Format
One `ui.error` line on stderr — `✗ Error: <what failed>`, or `✗ <what failed>. <what to do>`
when the error names its fix — optionally followed by a usage or recovery hint line, then exit
`1` (or `2` for a usage error). There is no multi-line Details/Suggestion block.

### Example
```
✗ Error: No pod for /work/app (looked for a registered codebase containing it). Run 'docket init' here, or pass --pod <name>.
```

## Compatibility

### State location
- docket reads and writes its state only under `DOCKET_HOME` (default `~/.docket`) and imports
  nothing from another tool's state; the first `docket init` creates what it needs there.

### Names
- docket carries no compatibility layer for its own CLI: no alias table, no notice for a
  removed name, no no-op flag, no suggestion for a removed name (ADR 0022). A name the command
  tree does not have is an ordinary unknown command (exit 2); `CHANGELOG.md` is the only record
  of what was removed and what replaced it.

## Implementation

- `pyproject.toml`: the distribution metadata, `[project.scripts]` `docket`, the sdist excludes
- `src/docket/__main__.py`: `main`
- `src/docket/interfaces/cli/app/__init__.py`: the command registry (`app`), the panel of each registration, the
  bare-`docket` guide lines
- `src/docket/interfaces/cli/render/help.py`: `DocketGroup` (panel order, unknown-word suggestions)
- `src/docket/interfaces/cli/commands/target.py`: `resolve_pod`, `pod_option`
- `src/docket/interfaces/cli/commands/contract.py`: `confirm`, `emit_json`, `next_step`, `require_pod`, `is_tty`
- `src/docket/interfaces/cli/commands/agents.py`: `docket init` (`cmd_init`, `InitRequest`, `run_init`, the review)
- `src/docket/interfaces/cli/commands/status.py`: `docket status`
- `src/docket/interfaces/cli/commands/inbox.py`: `docket inbox`
- `src/docket/interfaces/cli/commands/task.py`: `docket task` and its verbs
- `src/docket/interfaces/cli/commands/run.py`: `docket run`, the repository pick-up before dispatch
- `src/docket/interfaces/cli/render/progress.py`: the foreground progress view and in-place approval
- `src/docket/interfaces/cli/commands/pod.py`, `src/docket/interfaces/cli/commands/pod_show.py`: `docket pod` roster, settings and memory verbs
- `src/docket/interfaces/cli/commands/pod_config.py`: `pod update|export|validate|plan|check|recipes|roles|policies`
- `src/docket/interfaces/cli/commands/log.py`: `docket log`
- `src/docket/interfaces/cli/commands/setup.py`: `docket setup`, `readiness`, `--version`
- `src/docket/interfaces/cli/commands/setup_check.py`: `setup --fix` health checks
- `src/docket/interfaces/cli/commands/setup_model.py`: `setup provider`, `setup model`
- `src/docket/interfaces/cli/commands/setup_sandbox.py`: `setup sandbox`, `setup profile`
- `src/docket/interfaces/cli/commands/setup_shell.py`: `setup shell`
- `src/docket/interfaces/cli/commands/setup_notify.py`: `setup notify`
- `src/docket/interfaces/cli/commands/setup_export.py`: `setup export`
- `src/docket/interfaces/cli/commands/setup_mcp.py`: `setup mcp`
- `src/docket/interfaces/cli/commands/setup_secret.py`: `setup secret`
- `src/docket/interfaces/cli/commands/setup_service.py`: `setup service`
- `src/docket/interfaces/cli/commands/pod_records.py`: `pod records`
- `src/docket/interfaces/cli/commands/service.py`: `docket start`, `docket stop`
- `src/docket/interfaces/cli/render/ui.py`: `TAGLINE`, `guide`, `header`, `section`, `table`, `error`, `hint`, plain mode
- `src/docket/tasks/domain/refs.py`: `resolve_task`
- `src/docket/teams/provisioning.py`: `slugify`, `validate_project_id`
- `src/docket/teams/pod.py`: `PodSettings`, member ids
- `src/docket/kernel/operator_contract.py`: `InboxView`, `TaskBrief`
- `src/docket/hops/application/interruptions.py`: `record_pregrant`, `NOTHING_WILL_ASK`
- `src/docket/tasks/application/escalations.py`: `resolve`
- `src/docket/governance/approval.py`: `approval_grant`, `approval_deny`, `ApprovalNoop`
- `src/docket/tasks/application/queue.py`: task enqueue
- `src/docket/tasks/application/lifecycle.py`: `task_diff`, retry, cancel of a parked task,
  stale-claim settling
- `src/docket/tasks/application/actions.py`: `resolve_waiting_approval`
- `src/docket/tasks/application/runs.py`: `cancel_run`, `prune_terminal`
- `src/docket/teams/apply/plan.py`: `plan_apply`, `apply`, `resolve_recipe`, `list_recipes`,
  `summarize_recipe`, `RecipeSummary`, `repo_config_dir`
- `src/docket/teams/config_docs.py`: `validate_path`
- `src/docket/pipeline/domain/plan.py`: `resolve_plan`, `render_plan`
- `src/docket/governance/plugins.py`: `discover`
- `src/docket/observability/exporter.py`: `activation_state`, `enable_exporter`, `set_privacy`, `is_widening`, `privacy_label`
- `src/docket/observability/telemetry.py`: `ExportPolicy`
- `src/docket/governance/privacy.py`: `describe`
- `src/docket/operator/channel.py`: `unreached_warning`
- `src/docket/teams/network_posture.py`: the `network <mode>` wording in the `isolation` string
- `src/docket/agent/tools/registry.py`: `dispatch_tool`
- `src/docket/platform/git.py`: `trust_worktree`
- `src/docket/models/application/endpoint.py`: `resolve_endpoint`
- `src/docket/observability/adapters/otlp_http.py`: `encode`
- `src/docket/kernel/home.py`: the `Home` members `tool_approval_timeout`, `trace_retention_days`,
  `root`
- `tests/guards/test_console_voice.py`: the shrink-only markup guard
- `tests/guards/test_cli_prompt_sites.py`: the shrink-only prompt-site guard
