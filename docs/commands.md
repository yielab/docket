# Command Reference

Generated from the live Typer registry by `scripts/gen_cli_docs.py` — do not hand-edit. Regenerate with `uv run python scripts/gen_cli_docs.py` after changing any CLI help string; `scripts/gen_cli_docs.py --check` fails CI on drift.

Complete reference for all docket commands, rendered from each command's own `--help` text so the CLI and this document can never drift apart.

## Table of Contents

- [Lifecycle Commands](#lifecycle-commands)
- [Session & Context Management](#session-context-management)
- [Pod Coordination](#pod-coordination)
- [Telegram Integration](#telegram-integration)
- [Keys & Authentication](#keys-authentication)
- [Utility Commands](#utility-commands)
- [Security & Audit](#security-audit)
- [Observability Commands](#observability-commands)
- [Global Options](#global-options)
- [Exit Codes](#exit-codes)
- [Environment Variables](#environment-variables)
- [Tips & Tricks](#tips-tricks)
- [Next Steps](#next-steps)

## Lifecycle Commands

### list

**Usage:** `docket list`

List all project agents.

Shows every registered agent -- pod members for each project and the shared
org specialists (manager, knowledge, security) -- with role/pod, model and
its source, Telegram binding, and last activity. Telegram status reflects
docket's own channel bindings (`~/.docket/fleet.json`); the session column
shows the agent's current project key. `--json` emits the same listing as
one JSON document instead of the Rich table, for scripting.


---

### init

**Usage:** `docket init`

Initialize the current project with its minimum isolated pod.

Creates a new project pod -- an isolated team of project-scoped agents
that owns one codebase. The default pod is lean: a Lead + an Implementer.
The first invocation also creates docket's shared workstation foundation
(fleet registry, org specialists, policies, default gates) -- there is no
separate setup step. See docs/AGENT-TEAMS.md.

With no arguments, docket derives the project id, path, and stack from the
current directory (non-interactive, deterministic). Member ids are
predictable: `<project>-lead`, `<project>-implementer`, `<project>-reviewer`,
`<project>-tester` (duplicated roles get `-2`, `-3` suffixes). A pod
always has exactly one Lead. Resize a pod later with `docket pod`; tear
the whole pod down with `docket delete`.

Flags (parsed from the extra CLI args, not fixed Typer options):
  --pod full            provision Lead, Implementer, Reviewer, and Tester.
                         Only applies to the default `software` blueprint;
                         ignored (with a warning) for any other blueprint,
                         which provisions its own fixed roster.
  --with <roles>        start from the lean pod and add named roles
                         (comma-separated: reviewer, tester, implementer).
                         Same `software`-only restriction as `--pod full`.
  --blueprint <name>    (default `software`) provision a named pod
                         blueprint instead of the plain lean/full pod --
                         `software` (codebase, lead+implementer), `research`
                         (workdir, lead/researcher/analyst/writer/critic,
                         $20 default budget, Critic gates the final step
                         with one rework cycle), `content` (workdir,
                         lead/writer/critic, $15), `ops` (workdir,
                         lead/operator/monitor, $30, Operator gated on its
                         own verifyCmd, Monitor is a human-approval gate),
                         `agentic-product` (codebase, full software
                         roster). A codebase blueprint treats the location
                         argument as an existing, never-auto-created
                         codebase path and auto-detects its stack; a
                         workdir blueprint treats it as the pod's one
                         shared working directory instead -- no stack is
                         auto-detected. `docket init` always passes the
                         cwd (or an explicit `--codebase`/`path`) as the
                         location, so it never hits the auto-provisioned
                         `~/.docket/workspaces/pods/<project>/` default;
                         that path is only reached via `--from` entries
                         that omit `workDir` or `POST /pods` calls that
                         omit `path`. Unknown
                         name errors with "unknown blueprint 'X'; valid
                         blueprints: software, research, content, ops,
                         agentic-product" and exits 1 before any prompt.
                         Only the five built-ins exist today -- there is
                         no `docket blueprints add <file>` to register a
                         custom one. See
                         specs/functional/pod-blueprints.spec.md.
  --codebase <path>     the codebase path (or, for a workdir-kind
                         blueprint, the pod's shared working directory) --
                         same value as the `path` positional; supplying it
                         up front skips its interactive prompt.
  --name <name>         display name -- same value as the 1st positional;
                         skips its prompt.
  --from <spec-file>    non-interactive, declarative provisioning -- one
                         or many agents/pods from a single JSON or YAML
                         file (`.yaml`/`.yml` needs PyYAML), the same
                         mechanism a CI job or fleet-bootstrap script would
                         use. The file is a bare list, `{"agents": \[...\]}`,
                         or one entry object. Each entry needs an `id`; an
                         entry with a `blueprint` field provisions a pod
                         (fields: `codebase`/`workDir`, `stack`,
                         `description`, `projectKey`, `budgetUsd`,
                         `telegram`); an entry with no `blueprint`
                         provisions a single flat agent the same shape
                         `docket add` always has (fields: `name`,
                         `codebase`, `stack`, `model`, `description`,
                         `telegram`, `budgetUsd`, `projectKey`). Mutually
                         exclusive with every other flag/prompt. An entry
                         whose id already exists, or names an unknown
                         blueprint, is skipped with a warning rather than
                         failing the rest of the file -- the command
                         always exits 0, so check the printed summary
                         rather than only the exit code in a script.
  --recipe <name|dir>   apply a shipped or local recipe directory after
                         provisioning -- a directory path as given, else a
                         shipped recipe by name (secure-build,
                         research-review, ops-approval). An unresolvable
                         name errors naming the shipped recipe names and
                         exits 1 before any provisioning. Mutually
                         exclusive with a present `<location>/.docket/` --
                         giving both errors naming both sources and exits
                         1 before any provisioning.
  --no-apply             provision the pod only, skipping the apply step
                         for a present `.docket/` or a resolved `--recipe`;
                         prints the `docket pod <p> apply <dir>` command
                         that would apply it.

A repository's own `<location>/.docket/` -- the same directory shape
`docket pod <p> apply` reads (roles/*.yaml, policies/*.json,
pipeline.yaml, pod.yaml) -- is discovered automatically: every document
under it is validated before anything is provisioned, and applied after
(unless `--no-apply`) through that same command's plan/apply path. A
validation error exits 1 naming the file and field, with nothing
provisioned. See specs/functional/pod-blueprints.spec.md, "Pod manifests:
apply".

Every project is a repo -- a pod tied to a codebase, defaulting to the cwd
(or the `path` argument / `--codebase`, in which case you are not
re-prompted); the project name is suggested from that directory's name.


---

### add

**Usage:** `docket add`

Add role agents to an existing project pod. Never creates a project.

Pod inferred from the current directory, or given explicitly with
`--project <pod>` when running outside the project's configured
`codebase`/`workDir`. Docket chooses the most-specific registered pod
containing the cwd and fails clearly when there is no match or the result
is ambiguous.

Flags (parsed from the extra CLI args, not fixed Typer options):
  --project <pod>     explicit pod, instead of directory inference
  --count N           add N indexed copies of the role
  --verify "<cmd>"    set the new Implementer's mechanical verify gate


---

### status

**Usage:** `docket status`

Show current-project status, or every project with --all.

The current-project view shows state without mixing in the global agent
inventory or workstation health: configured path, readiness, pod roles,
and task counts. `docket list` remains the detailed global agent
inventory; `docket doctor` remains the global technical health check.


---

### info

**Usage:** `docket info`

Detailed status of one agent.

Shows identity, codebase/stack, model and its source, session/project
keys, creation time, workspace path, and Telegram binding for one agent --
pulled from `.docket-meta.json`. With no agent id given, shows a numbered
picker.


---

### delete

**Usage:** `docket delete`

Remove a project agent or a whole pod, and optionally its workspace.

Given a pod id, lists every member and (in an interactive terminal)
requires typing the exact pod id to confirm, then removes every member's
registration, binding, conversation-registry entry, workspace/worktree,
pod runtime directory, durable session history, and traces. The global
audit record is preserved. Given a legacy flat agent id, separately asks
whether to also remove its workspace.

Cannot be undone -- back up first if unsure. Org specialists (manager,
knowledge, security) cannot be removed this way -- the command errors
outright rather than deleting a shared, fleet-wide agent. A deleted
member's git worktree is removed, but its dedicated branch remains in the
source repository so committed code is not silently destroyed; remove
that branch separately after reviewing it.


---

### maintain

**Usage:** `docket maintain`

Maintain an agent workspace (check/clean/reset/rebuild/sessions/distill).

Subcommands:
  check (default)  health check and auto-fix -- permissions (700/600),
                    missing workspace files, session-key sync between
                    `.docket-meta.json` and SOUL.md, memory directory,
                    and a per-turn context-footprint estimate (warns if
                    SOUL/AGENTS/TOOLS/HEARTBEAT/MEMORY together exceed
                    the configured token budget)
  clean             clear memory logs only (`memory/*.md`) -- distills
                    first by default (see below)
  reset             clear memory + MEMORY.md + HEARTBEAT.md -- distills
                    first by default
  rebuild           deep rebuild -- regenerate SOUL.md, AGENTS.md,
                    TOOLS.md from `.docket-meta.json`. Refuses a pod
                    member outright (its files are pod-provisioning's,
                    not this command's); never touches memory/
  sessions          report per-session message counts, on-disk size,
                    and last-active time for this agent -- sizes only,
                    no trimming or archiving
  distill           summarize `memory/*.md` into MEMORY.md via one
                    driver-backed turn, then archive the originals under
                    `memory/<archive-dir>/`

`--no-distill-first` (clean/reset only) skips the automatic pre-delete
distillation and deletes/clears memory undistilled.

Memory is never bare-deleted: before clean deletes `memory/*.md`, or reset
clears memory + HEARTBEAT.md, docket runs one driver-backed turn that
summarizes pending logs into MEMORY.md and archives the originals -- the
same work `distill` does standalone. A failed distillation aborts the
delete outright; nothing is touched. `failure_kind` (`timeout`,
`daemon_error`, `invalid_output`) tells you whether to just retry or
whether the model's output needs a closer look (`daemon_error` means the
turn didn't complete cleanly). When a reset runs a real distillation, MEMORY.md is
left freshly distilled rather than immediately cleared again in the same
breath.

Preserves identity (`.docket-meta.json`, fleet registration). clean/
reset/rebuild prompt for confirmation and require a TTY -- a
non-interactive call is cancelled, not silently applied.


---

## Session & Context Management

### scope

**Usage:** `docket scope`

Manage session scope / project isolation key.

Subcommands: `show` (default) prints the current scope and session key;
`set <project-key>` changes it; `reset` restores `default`. The session
key has the form `agent:<id>:<project>` and prevents cross-project
contamination between parallel work on the same agent; changing it
updates `.docket-meta.json` only -- it prints a reminder to update
SOUL.md yourself, it does not rewrite the file.


---

### context

**Usage:** `docket context`

Agent context views (show/project) -- read-only.

There is no separate semantic memory index: docket's own turn loop has no
`memory_search` tool, so an agent (and this command) reads memory files
the same way it reads any other file -- `context` is just two dashboards.

Subcommands:
  show (default)  the last 3 memory-log files (last 5 lines each), active
                  tasks parsed from HEARTBEAT.md, and quick stats
                  (memory-log count, session size from docket's own
                  durable per-session storage, last-active timestamp)
  project         a project-metadata-focused view -- codebase path,
                  stack, model, session key, active tasks, and MEMORY.md
                  section headers

Both subcommands are read-only and touch only the named agent's own
workspace; any other action exits 2. Use `docket snapshot` for a
whole-fleet JSON export.


---

### persona

**Usage:** `docket persona`

Set/clear an agent's optional display persona (docket-owned; rendered into SOUL.md).

Identity of record is the agent's role; a persona is only a display skin
docket controls -- never a self-authored IDENTITY.md.

Subcommands: (show, default) current persona + role; `set "<label>"`
assigns a display name; `clear` removes it (back to role/name).

Stored in `.docket-meta.json` (`persona`) and rendered into `SOUL.md`;
survives `maintain rebuild`. Use this command to give an agent a
friendly name.


---

## Pod Coordination

### pod

**Usage:** `docket pod`

Manage a project's pod: list members, add/remove a role, set an
implementer's verify command, and run its dispatch pipeline.

A pod is the isolated team of project-scoped agents created by
`docket init`; `pod <project> add <role>` extends an existing one. Every
member has its own permission-locked workspace, so no role is ever
shared between projects. See docs/AGENT-TEAMS.md.

Subcommands:
  list (default)   show the pod's members and their roles
  add <role>       \[--count N|-n N\] \[--verify "<cmd>"\]. Role is validated
                    against the open role-archetype registry
                    (`docket roles`), not a hardcoded
                    implementer|reviewer|tester list -- a blueprint role
                    or any user-defined archetype works too. The Lead
                    is unique and cannot be added this way. Duplicated
                    roles get `-2`, `-3` ids. `--count`/`-n` adds several
                    at once. `--verify "<cmd>"` sets the mechanical
                    verification gate dispatch runs after that member's
                    hop -- written into the new member's
                    `.docket-meta.json` (`verifyCmd`) and documented in
                    its TOOLS.md; passing it for a non-implementer role
                    is silently ignored with a warning, since only an
                    Implementer hop is verify-gated. A new member
                    inherits the pod's workspaceKind/workDir/blueprint
                    from its existing members.
  remove <id>      remove one member by id
  set-verify <id> "<cmd>"
                   set (or change) the verify command on an existing
                    Implementer -- the only public way to do this short
                    of the internal debug command. Rewrites the member's
                    TOOLS.md. Validated (no NUL/newline, length-capped)
                    and audit-logged (`pod.set-verify`); runs at dispatch
                    time in the Implementer's git worktree when one
                    exists, falling back to the pod's shared codebase
                    root, then the member's own workspace dir.
  config           \[get|set <key> <value>|unset <key>\] \[--json\]. Typed,
                    validated dispatch settings on the pod's Lead
                    (`core.pod.PodSettings`): `budgetUsd`, `maxReworkCycles`,
                    `turnTimeoutS`, `verifyTimeoutS`. `get` (default) shows
                    each key's effective value and whether it is `set` or
                    `default`; `--json` emits the same as a bare object --
                    see cli-json-shapes.spec.md. `set` validates before
                    writing (an invalid value exits 1, nothing persisted)
                    and audit-logs `pod.config`; `unset` removes an
                    override, falling back to the built-in default. A
                    stored value that fails validation (e.g. a hand-edited
                    `.docket-meta.json`) refuses `config get` and
                    `dispatch` alike, naming the key, instead of silently
                    substituting the default.
  delegate <task>  \[--priority high|normal|low\]. Queue a task on the
                    pod's task queue (in the Lead's workspace). Priority
                    defaults to normal. The description is capped at 500
                    characters. Queues only -- run it with `dispatch`.
  queue            \[--retry <task-id>\]. Show the queue with per-task
                    status (pending/running/done/failed/blocked) and
                    estimated cost. `--retry` moves one blocked task back
                    to pending -- the explicit, single-task way around a
                    reached budget cap (`docket profile <lead-id>
                    --budget`/`--resume` un-blocks every task in the pod
                    at once instead).
  dispatch         \[--resume\] \[--timeout <seconds>\]. Run the pod's
                    pending (and, with --resume, crash-recoverable) tasks
                    through its pipeline -- one real agent turn per hop:
                    Lead -> Implementer -> Reviewer (if present) ->
                    Tester (if present). Only the roles the pod actually
                    has take part. Each task is claimed under a filelock
                    before its first hop runs, so two dispatchers can
                    never double-run the same task, and each hop is
                    persisted as it completes so a crash loses at most
                    the in-flight hop. `--resume` also reclaims any task
                    a prior dispatcher left failed with a stale claim
                    or as `dispatch_refused` (a deterministic refusal
                    settled mid-task), and counts a still-`running`
                    task as work so the stale-claim sweep can judge it,
                    continuing from its last persisted hop. `--timeout`
                    overrides both the agent-turn timeout and the
                    verifyCmd timeout for this run only (otherwise each
                    falls back to the pod's own configured timeouts,
                    then a 300s default).
  sync             \[--dry-run\]. Re-render SOUL.md/AGENTS.md/TOOLS.md for
                    every member whose managed files have drifted from
                    the current archetype and stored metadata (a
                    template bump, or a role's own archetype content
                    changing). `--dry-run` prints the diff without
                    writing; without it, each stale member is rewritten
                    and its metadata restamped (audit-logged as
                    `pod.sync`). `INSTRUCTIONS.md` is operator-owned and
                    is never read, written, or diffed by this command --
                    an already-current pod changes nothing.
  apply \[<name|dir>\]  \[--dry-run\] \[--json\]. Apply a recipe/manifest
                    directory (role YAML, `pipeline.yaml`, and a small
                    `pod.yaml` naming `members`/`settings`/`pipeline`) to
                    this pod in one command, composing the same writers
                    `roles add`/`add <role>`/`config set pipeline`/
                    `config set <key> <value>` already use. A directory
                    path if one exists there, else a shipped recipe name
                    (secure-build, research-review, ops-approval) as
                    `init --recipe` resolves it; default `<codebase>/.docket`. Validates
                    everything -- roles, the roster the pipeline would
                    resolve against once `members` join, and every
                    setting -- before writing anything; an invalid
                    manifest exits 1 naming the problem with nothing
                    written. Idempotent: applying the same directory
                    twice plans every item `skip` the second time and
                    writes nothing. `--dry-run` prints the plan without
                    writing. Audit-logged once as `pod.apply`, only when
                    something actually changed.
  export \[<dir>\]   \[--force\]. Write this pod's own scope -- pod-overlay
                    `roles/*.yaml`, this pod's own `policies/*`, a
                    bound `pipeline.yaml` copy (if any), and a `pod.yaml`
                    naming non-Lead `members` and every non-default
                    `setting` -- into `<dir>`, the same shape `apply`
                    reads back. `<dir>` defaults to `<codebase>/.docket`,
                    like `apply`. Global scope (the operator's own role
                    overlay, fleet-wide policies, other pods) is never
                    exported. Refuses a non-empty `<dir>` unless
                    `--force`, which overwrites any same-named file
                    already there. Audit-logged as `pod.export`.

Dispatch guarantees: budget-gated with real auto-pause (checked before
each hop against the Lead's cap; over budget leaves the task blocked and
pauses the pod's Lead until `docket profile <project>-lead --resume`); a
timed-out or daemon-error hop retries in place (linear backoff, small
per-role budget) before failing, a real non-zero exit or bad verdict is
never retried; a Reviewer's REQUEST-CHANGES sends the task back to the
Implementer for one rework cycle (default) before a second rejection
fails it; a set verifyCmd runs in the Implementer's git worktree when one
exists; every hop/retry/gate outcome/claim/sweep event is traced
(`docket trace`) on a per-task session; every invocation creates a
queryable `docket runs` record; dispatch only ever targets the project's
own pod -- there is no cross-pod dispatch path. See
specs/functional/pod-dispatch.spec.md.


---

### pipeline

**Usage:** `docket pipeline`

Validate, plan, and run a docket-native pipeline -- the one dialect
docket actually executes.

A pipeline file declares a pod's hop order, gates, and rework edges
instead of relying on the built-in default order.

Subcommands:
  validate <file>   pure structural validation -- no project involved,
                     nothing dispatched. Checks step ids are unique, each
                     step has exactly one of role/agent, gate shapes are
                     well-formed, and rework edges point at an earlier
                     step id.
  plan <project>    \[--file <path>\]. Resolves the pipeline against a
                     project's actual pod roster and prints the plan --
                     the exact function `run`/`docket pod <p> dispatch`
                     use internally, not a second pretty-printer. Never
                     executes anything or spends tokens. Without --file,
                     resolves the pod's zero-migration default order
                     (lead -> implementer -> reviewer -> tester,
                     whichever roles the pod has).
  run <project>     \[--file <path>\] \[--resume\] \[--timeout <seconds>\]
                     \[--var key=value\]... \[--follow\]. Dispatches a
                     project's pod through the given (or default)
                     pipeline -- delegates to the exact same executor as
                     `docket pod <project> dispatch`, so it is equally
                     budget-gated, verify/Reviewer/Tester-gated, traced,
                     and recorded in `docket runs`. --resume/--timeout
                     behave identically to pod dispatch. Repeatable --var
                     key=value supplies the pipeline's variable
                     namespace (the same one a webhook dispatch resolves
                     from its JSON body); a step's own `instructions` may
                     reference `${key}`, and a missing `required`
                     variable or an unresolved `${key}` reference
                     refuses the run before any hop. --follow tails the
                     run's trace events live in the foreground (Ctrl-C
                     stops watching, not the dispatch itself, which
                     keeps running).

Pipeline file schema (YAML or JSON; unknown keys rejected): `name`
(required), `description`, `variables` (a name->{default, description,
required} map, resolved at dispatch time against --var/a webhook body);
`steps`: each has `id` (unique), exactly one of `role` (a role-archetype
slug) or `agent` (a specific member id), optional `retries`, `timeout`
(seconds), optional `instructions` (overrides the target role's own hop
instruction for this step; may reference `${var}`), optional `gate`, or
a `parallel` list of child steps (one nesting level). `gate.type`:
`mechanical` (a `command`, or null to defer to the target's own
verifyCmd), `verdict` (a `pattern` regex, `passValues`, optional
`rework: {to, when, maxCycles}` edge back to an earlier step), or
`approval` (a human sign-off message).

A pod with no pipeline file runs the built-in default order -- declaring
a pipeline is opt-in. `archetype` references inside a step are
shape-validated only, never checked against the live role registry. See
specs/functional/pipeline-format.spec.md.


---

### roles

**Usage:** `docket roles`

Manage declarative role archetypes: list/show/add/validate.

A role archetype is the data-driven definition behind every pod role
(lead, implementer, reviewer, tester, and the blueprint-only roles
researcher, analyst, writer, critic, operator, monitor) -- SOUL/AGENTS
templates, model class, gate contract, token budget -- not a hardcoded
branch, so `docket pod <p> add <role>` accepts any name in this registry.

Subcommands:
  list (default)   all archetypes (built-in + user-defined) with source,
                    scope, model class, gate, and description
  show <name>      the full wire-format definition (YAML, falling back
                    to JSON if PyYAML is missing) -- name, version, scope
                    (org|pod), modelClass (cheap|strong), soulTemplate,
                    agentsTemplate, gateContract
                    (none|verdict|mechanical|approval), toolProfile,
                    tokenBudget, hopInstruction (this role's hop-message
                    instruction; unset means "generate one from
                    gateContract" for a gated role)
  add <file.yaml>  registers a new archetype from a standalone YAML file
                    into the user overlay (`~/.docket/docket-roles.json`)
                    -- built-ins are never edited, only shadowed by name
  validate \[file\]  structural field validation (closed enums, name
                    regex, non-blank templates) plus a dry-run render of
                    both templates against a representative variable set
                    -- catches a template referencing an unknown `${var}`
                    before add persists it. With no file argument,
                    validates every entry in the merged live registry
                    instead.

Built-ins and the 6-role starter library are Python literals, never
loaded from files; a user archetype in `~/.docket/docket-roles.json`
overlays by name, and a malformed overlay entry is skipped rather than
crashing a live fleet. See specs/functional/role-archetypes.spec.md.


---

### recipes

**Usage:** `docket recipes`

List and inspect the recipe library.

Subcommands: `list \[--json\]` prints every recipe reachable by name --
the operator's own `~/.docket/recipes/<name>/` before the shipped
library, nearest scope wins -- with its derived kind (team/policies/
pipeline/mixed) and description. `show <name|dir> \[--json\]` prints one
recipe's description, scope, directory, derived summary, and README
body. Installs, removes, or fetches nothing; `docket pod <p> apply`/
`docket init --recipe` remain the only writers.


---

## Telegram Integration

### wire

**Usage:** `docket wire`

Wire or update a channel group binding (Telegram by default).

Inbound only: the binding authorizes a chat to send /approve, /deny,
/status and /delegate; docket never messages the group on its own --
there is no notification on a pending approval and no report when a task
finishes, you poll with /status.

With `TELEGRAM_BOT_TOKEN` configured, docket shows a one-time command such
as `/wire A1B2C3` -- send it in the Telegram group, return to the
terminal, and press Enter, and docket discovers and binds that group
automatically. You can paste a numeric group ID instead; manual entry is
also the fallback when the bot token is missing, Telegram cannot be
reached, or no matching message is found.

`--channel <name>` (default telegram) selects which channel to wire; the
flag exists so additional channels can be added without a breaking
change to this command's syntax, though Telegram is the only one shipped
today.

Updates docket's own fleet registry (`~/.docket/fleet.json`) bindings,
and seeds an entry in the conversation registry (`docket conversations`).
The binding is the entire authorization boundary once
`docket serve --telegram` is running: anyone who can post in that chat
can act as this agent. Guided discovery reads the matching one-time
/wire message without advancing the Telegram poller's durable offset or
processing unrelated messages -- if `docket serve --telegram` is already
polling, stop it during setup so it does not receive the one-time
command first.


---

### unwire

**Usage:** `docket unwire`

Remove a channel binding (Telegram by default).

`--channel <name>` (default telegram) selects which channel binding to
remove. Removes the entry from docket's own fleet registry
(`~/.docket/fleet.json`); the agent can still function without it, but
approvals then require CLI, HTTP, or MCP interaction.


---

### conversations

**Usage:** `docket conversations`

Inspect and resume the conversation registry (list/show/resume/set/prune).

docket's durable index of channel threads: docket's own turn loop keeps
no durable transcript of its own, so this registry tracks which agent
handles each thread, its topic, status, and a resume pointer.

Subcommands: `list` (default) all tracked conversations; `show <id|
agent-id>` full detail for one; `resume <id|agent-id>` marks it
in_progress and prints a resume brief; `set <agent-id> <peer-id>
\[--topic\] \[--status\] \[--last\] \[--task\]` edits an entry directly;
`prune \[--dry-run\] \[--days N\]` deletes `done` conversations past the
retention window (default `TRACE_RETENTION_DAYS`) -- the same pruning
`docket serve`'s periodic sweep already does.

Auto-seeded when you `docket wire` an agent to a channel; cleaned up on
`docket delete`. `status` is one of active | in_progress | waiting |
done. Durable conversation content lives in the agent's HEARTBEAT.md +
memory/ (resumed on its next turn via the durability contract); this
registry tracks state only.


---

## Keys & Authentication

### keys

**Usage:** `docket keys`

API key management (add/list/remove/rotate/validate/export/setup).

Docket's model client reads keys centrally.

Subcommands:
  list (default)     masked table of stored keys with a format badge and
                      the date added
  add <KEY_NAME>      name must be UPPERCASE_WITH_UNDERSCORES (e.g.
                       ANTHROPIC_API_KEY); prompts for the hidden value
                       via getpass; errors (exit 1) if the name already
                       exists -- use rotate instead
  remove <KEY_NAME>    deletes a stored key, confirming interactively if
                        stdin is a TTY
  rotate <KEY_NAME>    replaces the value of an existing key (errors,
                        exit 1, if it doesn't already exist)
  validate \[KEY_NAME\]  checks stored key(s) against known provider
                        prefix/length rules (e.g. ANTHROPIC_API_KEY must
                        start `sk-ant-` and be >= 40 chars); no name
                        validates everything; exit 1 on any failure
  export               prints `export NAME='value'` lines (unmasked,
                        shell-quoted) for every stored key, for
                        `eval "$(docket keys export)"`
  setup                interactive wizard (requires a TTY) through
                        every credential the provider catalog declares,
                        in catalog order, one at a time

Stored in `~/.docket/secrets.json` (values, 0600) and
`secrets.meta.json` (added/rotated timestamps) -- docket-owned JSON,
written through `edges/store.py`. Recognized provider keys:
ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_AI_API_KEY, OPENROUTER_API_KEY,
AI_GATEWAY_API_KEY, VERCEL_OIDC_TOKEN, GROQ_API_KEY, MISTRAL_API_KEY,
XAI_API_KEY, CEREBRAS_API_KEY, HUGGINGFACE_TOKEN. The runtime reads a
selected provider's stored credential directly -- exporting is optional.
Under DOCKET_SECRETS_BACKEND=keyring, add/rotate store the value in the
OS keyring (secret-tool) instead of secrets.json, which then keeps only
a name index; remove clears the keyring entry too.


---

## Utility Commands

### logs

**Usage:** `docket logs`

View an agent's latest memory log.

Prints the most recent `memory/YYYY-MM-DD.md` file's first 40 lines (with
a note if there are more). Memory logs are the durable, docket-owned
activity record. For active tasks, read
HEARTBEAT.md directly (`docket edit <id>`) or use
`docket context <id> show`. Shows the single latest file only, not a
rolling tail across days -- use `tail -f` on the file directly for live
monitoring. Memory logs rotate daily.


---

### edit

**Usage:** `docket edit`

Open agent workspace files in $EDITOR.

Opens SOUL.md (identity and session key), AGENTS.md (delegation rules),
TOOLS.md (project commands), HEARTBEAT.md (active tasks), and
.docket-meta.json (metadata). Respects $EDITOR, falling back to `vi` if
unset. Be careful editing `.docket-meta.json` by hand -- use
`docket maintain <id> check` to fix drift afterward.


---

### profile

**Usage:** `docket profile`

Pin or unpin an agent's model; set a budget cap; resume from auto-pause.

Every agent follows its role's policy model by default
(`modelSource: policy`). Pinning (`modelSource: pinned`) detaches it --
policy and preset changes will no longer touch it.

With no model argument, shows the current model, role, source, and
budget. A `provider/model` argument pins it; `default` re-attaches it to
the role policy. `--budget <USD>` sets a per-agent spend cap (0 = none).
`--resume` clears an auto-pause (e.g. a reached budget cap) -- when the
target is a pod's Lead it also un-blocks that pod's blocked tasks so
dispatch can claim them again, and writes a `profile.resume` audit entry.
A model argument must be a full `provider/model` id; `docket models`
shows and sets the role policy.


---

### models

**Usage:** `docket models`

View and edit the role->model policy -- the single place that decides
which model each kind of agent runs on.

Built-in defaults put high-volume/low-reasoning roles (manager, reviewer,
tester, knowledge) on the cheap model class and reasoning-dense roles
(programmer, security, repo) on the strong class.

Subcommands: (bare) show the role->model policy with pricing and why;
`set <role> <provider/model>` change one role's model, or
`set default <provider/model>` the fallback; `preset \[name\]` list or
apply a provider preset from the catalog (anthropic (default), openai,
google, openrouter-free (experimental zero-cost router), openrouter,
ai-gateway (Vercel), local (no API key, priced at $0 (local)) among
others) -- a built-in hosted preset needs only its credential, never a
separate registration; `reset` restore built-in defaults (asks for
confirmation); `provider <action>` manage the provider catalog: `add
<file.yaml>` a `kind: provider` document, or the shortcut `add <name>
<base-url> \[--model ID\] \[--ctx N\] \[--max-tokens N\] \[--credential NAME\]`
(registration verifies `<base-url>/models` with the resolved credential
and classifies the result -- only a transport failure refuses; every
HTTP status registers, with a warning when it is not a clean 200);
`list` every provider (name, scope, dialect, base URL, credential);
`show <name> \[--json\]` one entry; `remove <name>` a global override
(a built-in with none refuses); `export <name> \[<file>\]` its document.

Policy changes are live: every policy-following agent is re-resolved
immediately; pinned agents (`docket profile <id> <model>`) are never
touched. Overrides persist in `~/.docket/docket-models.json` (`roles:`
map); delete it or run `reset` to restore built-ins -- `reset` prompts
`Continue? \[y/N\]` and a non-interactive call that can't answer aborts
rather than silently resetting the fleet. Applying a preset also writes
its own economy/standard/premium anchors, re-resolves every
policy-following agent, and prints a readiness line naming the preset's
credential as present or missing. Unknown models are accepted if
well-formed (`provider/model`) -- an id absent from the catalog only
surfaces the first time an agent actually calls the endpoint; pricing
shows n/a (or "n/a (bring your own)" for an OpenRouter/AI Gateway route
other than the explicit free router, and "$0 (local)" for a
local/ollama/lmstudio provider -- never a fabricated dollar figure).
An invalid model prints the current role policy table alongside the
error.


---

### cost

**Usage:** `docket cost`

Token usage and cost breakdown, with per-agent budget caps and
runaway-session detection.

With no agent id, aggregates all agents; with one, shows its own
breakdown. `--json` emits machine-readable output for either form.
`--history` shows a per-day cost breakdown instead of the current
totals; `--days N` (default 0 = no limit) restricts `--history` to the
last N days.

Token counts (input/output/cache read/cache write, turns) are real and
measured -- reported by the model endpoint per call and accumulated by
docket's own session storage. The dollar total is not: docket's own turn
loop (DocketDriver) reports no billed spend at all, so `Total cost`
always reads as "none recorded for these sessions" rather than a dollar
figure -- a known, plainly-stated gap, not a bug, because converting a
token count into a dollar figure is exactly the estimate-to-billing-claim
conversion docket refuses to make inside this command. See
`docket models` for a comparative, clearly-labelled estimate (never
presented as billed spend), and the same estimate's use by the
budget-auto-pause gate. docket does not print a projected "savings if
you switched models" figure either -- that would compound one estimate
on top of another. `--history`/`--days` currently return no rows against
the production driver: per-day breakdowns aren't tracked by docket's own
session store (a session's usage is one running total for its lifetime,
not timestamped per turn) -- a documented, known limitation. The pricing
table (`docket models`) is a manual snapshot, not a live feed, and is
not surfaced inside this command. Useful for detecting runaway sessions
by turn count; budget management works off the token-based estimate the
pod-dispatch gate itself computes, not this command's dollar column.


---

### doctor

**Usage:** `docket doctor`

System-wide health check and diagnostics, with an optional auto-fix
pass.

`--json` emits a machine-readable health probe instead of the Rich
report; `--fix` applies auto-fixes for detected drift (permission
repairs, missing workspace files, session-key resync) -- this mutates
state.

Runs (in order): required dependencies (python3); per-project agent
workspace/registration/binding checks; model validity across every
registered agent; the dispatch task ledger (`TASK_LIST.json` vs. the pod Lead's
HEARTBEAT.md dispatch ledger must agree -- a mismatch prints exactly
which task ids are missing/stale, and `--fix` re-syncs the ledger, always
safe since TASK_LIST.json is dispatch's own source of truth); budget-cap
sanity and runaway-session detection; key hygiene and provider coverage;
security-gate configuration; template/runtime-contract version (reseeds
a missing or stale WORKFLOW_AUTO.md).

`doctor` is diagnostic-only by default; `--fix` is not read-only -- it
mutates workspace files and permissions to correct detected drift.
Review its findings before running with `--fix` on a workspace you
haven't backed up.


---

### config

**Usage:** `docket config`

Read-only inspection of an agent's effective configuration.

Subcommands:
  explain <agent-id> \[--json\]  The configuration a real dispatch turn would
                    actually use for this agent, with the source that set
                    each value: resolved model + endpoint (policy/pinned);
                    the composed system prompt's sections with their bytes
                    and fit status (full/truncated/omitted); tools after
                    role denial, plus configured MCP servers; the
                    guardrail policies that apply to this role; the
                    effective pipeline and its source (bound
                    pipeline/blueprint/built-in default); and, for a pod
                    member, the pod's dispatch settings (budgetUsd,
                    maxReworkCycles, turnTimeoutS, verifyTimeoutS,
                    approvalMode, allowCommands) with each key's
                    set/default source. Composes existing resolvers only
                    -- writes nothing, adds no new configuration surface.
                    See specs/data/cli-json-shapes.spec.md.


---

### serve

**Usage:** `docket serve`

Local HTTP endpoints: /status.json /metrics /health.

Binds to 127.0.0.1 (loopback-only) -- not reachable off this host. With
--dispatch, each refresh also runs every pod's queue through the
Lead->Implementer->Reviewer->Tester pipeline. Each hop is a real agent
turn and is budget-gated; leave it off for a read-only monitor. With
--telegram, also polls docket's own Telegram bot so a chat bound via
`docket wire` can /approve, /deny, /status, or /delegate -- idle until a
bot token is stored.

`-p`/`--port <N>` (default 7331) binds a port -- 127.0.0.1 only, never
reachable off the host. `-i`/`--interval <seconds>` (default 30) sets
the sweep refresh interval. `--token-file <path>` writes the bearer
token needed for /approvals, /dispatch, and /runs to a 0600 file instead
of printing it to stdout.

HTTP endpoints while running: GET /status.json, /metrics, /health (no
auth); GET /approvals, POST /approvals/<token>
{"action": "grant"|"deny"}, GET /runs and /runs?project=<p>, GET
/runs/<id>, GET /tasks/<project>, GET /traces/<project>?since=<cursor>,
POST /tasks/<project>, POST /dispatch/<project>, POST /pods (all
Bearer-token-authed). The
bearer token is generated fresh per invocation (printed to stdout,
written to --token-file if given, or overridable via
DOCKET_SERVE_TOKEN) and compared with secrets.compare_digest. POST
/dispatch/<project> returns {"run": "<id>"} immediately and runs the
pipeline in the background -- poll GET /runs/<id> (or
`docket runs show <id>`) for the outcome.

Plain `docket serve` never dispatches and never polls Telegram; both are
opt-in. Read-only by default, so it's safe to leave running for
monitoring. --dispatch spends real budget; over-budget tasks are left
blocked, not run. Per-task dispatch is traced (`docket trace`) for
auditability.


---

### completions

**Usage:** `docket completions`

Shell completion helpers.

Prints a shell-completion script for bash or zsh. With no argument,
prints usage/install instructions. Only bash and zsh are supported (no
fish) -- an unknown shell name errors with exit 1.

The top-level command-name list is generated live from the real Typer
command registry, so it can never drift from `docket --help`.
Second-level subcommand words (e.g. `gates status isolate
classes`) are hand-maintained in the completion templates, since those
subcommands are parsed manually rather than being Click subgroups --
only the top-level command list is regression-tested against drift, so
hand-maintained subcommand words for `pipeline`, `conversations`,
`runs`, and `persona` can and have drifted out of sync with their real
subcommands.


---

### validate

**Usage:** `docket validate`

Validate role, pipeline, policy, and pod configuration documents.

With no argument, validates `<cwd>/.docket` if it exists, else the current
directory. A directory argument validates every `roles/*.yaml|yml|json`,
`policies/*.yaml|yml|json`, `pipeline.yaml`, and `pod.yaml` found under it;
a file argument validates that one file. Prints one line per file -- `ok
<file> (<kind> <name>)` or its error -- with invalid files listed first,
plus a `note:` line for a file loaded without a top-level `kind:` key.
Exits 1 if any file is invalid.


---

### snapshot

**Usage:** `docket snapshot`

Export system state snapshot as JSON.

Every project agent and specialist, its model, registration/binding
status, last activity, and measured cost, plus the channel list. `-o`/
`--output <path>` writes the JSON to a file instead of stdout.
`costUsd`/`totalCostUsd` are 0.0 for the same reason `docket cost` shows
no recorded spend today:
this is a snapshot of measured-token agents, not of billed dollars.
Useful for backups, dashboards, or feeding fleet state into another
tool.


---

### mcp

**Usage:** `docket mcp`

Expose the control plane as an MCP server (`mcp serve`), or configure external MCP tool servers (`mcp servers`).

"Rent the protocol": external tools are configuration, not code.

Subcommands:
  serve      expose docket's own control plane as an MCP server over
              stdio, so an external MCP client (an IDE, another agent
              runtime) can inspect and drive the fleet through typed
              tool calls instead of shelling out to the CLI. Requires
              the optional \[mcp\] extra (`pip install 'docket\[mcp\]'` or
              `uv sync --extra mcp`) -- prints an install hint to stderr
              and exits 1 if missing. Transport: newline-delimited
              JSON-RPC 2.0 on stdin/stdout -- no HTTP, no bind address,
              no bearer token; the trust boundary is whoever can spawn
              the process. Exposes 13 tools (every call audit-logged as
              `mcp.<tool>`): status, pods, queue, delegate, dispatch,
              runs, approvals_list, approvals_grant, approvals_deny,
              task_answer, task_pregrant, inbox, cost -- each mirrors the
              equivalent CLI/HTTP path through the exact same `core/` function, no
              parallel logic, no auto-approve. `dispatch` creates a run
              record and returns its id immediately, then runs the
              pipeline in the background -- poll `runs` for the outcome.
  servers    list/add/remove external MCP tool servers (stdio transport)
              so their tools become available to an agent's turn, gated
              by the same pre_tool_call policy and dispatch_tool
              chokepoint as any built-in -- a remote server can never
              shadow bash/read/write/edit/glob/grep. `add <name>
              \[--env K=V ...\] \[--timeout S\] \[--kind read|write\]
              \[--tools NAME,NAME,...\] -- <command> \[args...\]`:
              everything after `--` is passed to the server verbatim as
              its launch command and arguments; --env/--timeout/--kind/
              --tools must come before `--`. Tools register as
              `mcp__<name>__<tool>`. `--kind` declares the server's
              trust level (default: write) -- a role that denies write
              gets no tools from a server left at the default, but does
              get tools from one declared `--kind read`, since docket's
              role narrowing excludes by tool kind, not by name.
              `--tools` restricts registration to a comma-separated
              allow-list of that server's own tool names (default: all).

Its tools are reachable from a live turn: the client namespaces them
`mcp__<server>__<tool>`, and the turn loop folds them into the registry
before gating and before per-role narrowing, so a Reviewer (or any role
that denies write) never gets a write-capable MCP tool no matter what a
configured server advertises. `docket mcp` alone prints usage and exits
0; an unrecognized subcommand exits 1. A tool call's own success/failure
is expressed inside the MCP protocol (isError), never as a process exit
code. Configured servers persist in
`~/.docket/docket-mcp-servers.json` (docket-owned JSON); env values are
masked when listed. Every `mcp servers add`/`remove` is audit-logged.
See specs/functional/mcp-client.spec.md and specs/api/mcp-server.spec.md.


---

## Security & Audit

### gates

**Usage:** `docket gates`

Show docket's tool-call gate and manage workspace isolation.

The tool-call gate itself -- the policy engine plus the argument-aware
high-risk command classifier, both evaluated in `core/tools.py`'s
`dispatch_tool` chokepoint on every call docket's turn loop makes -- is
always active and cannot be turned off. An "ask" verdict sits in
docket's own approval store, answerable identically by the CLI, HTTP,
MCP, and Telegram channels.

Subcommands:
  status (default)  reports that the tool-call gate is always active,
                      plus the workspace-isolation mode
  isolate on|off    records whether tool execution should run inside a
                      Docker sandbox. `on` requires docker on PATH --
                      errors, exit 1, if missing. Enforced on the live
                      turn: with isolation on, DocketDriver runs tools
                      sandboxed (docker or bwrap), and refuses the whole
                      turn -- audited as `isolation.refused` -- when no
                      backend is usable, rather than running it
                      unsandboxed.
  network none|open records whether jailed tool calls may reach the
                      network (default open). `none` drops bwrap's
                      --share-net / adds docker's --network none, and
                      refuses any turn that would run with isolation
                      off -- audited as `network.refused`. A pod's
                      `network` setting can only narrow it. `fetch`
                      is untouched (its domain allowlist stays).
  classes           lists the built-in high-risk action classes
                      (`HIGH_RISK_PATTERNS` in `core/security.py`) --
                      money-movement, prod-deploy, and secret-access --
                      wired onto every bash call docket's turn loop
                      dispatches: the whole command line, including
                      every segment behind a `;`/`&&`/`||`/pipe, is
                      classified before a call is allowed to run, so
                      `git push origin production` asks even though
                      `git` itself stays on the curated allowlist
                      (`git status` does not). A pod's verifyCmd
                      separately refuses a matching command outright
                      before the shell starts; a hop's real output is
                      scanned for a match on the way through the
                      pipeline (flagged, not blocked, by itself).
                      Read-only; the pattern list is not yet
                      user-configurable.

Any other subcommand prints usage and exits 2. Approvals are answerable
headlessly via `docket approve`/`docket deny` or `POST
/approvals/<token>` (`docket serve`), or MCP, in addition to Telegram --
all four channels are audit-logged. See
specs/functional/security-gates.spec.md.


---

### audit

**Usage:** `docket audit`

Show the audit log, or verify its tamper-evidence chain.

A durable, append-only, tamper-evident record of docket-initiated
mutations (key changes, gate toggles, profile pins, scope changes,
agent/pod add/delete, persona changes, etc.).

With no argument, shows the last 20 entries (human-readable); `\[N\]`
shows the last N; `--json` dumps the raw audit.log JSONL file verbatim;
`verify` walks the hash chain and reports the first broken link (exit 1)
or that it verified clean (exit 0).

Stored at `~/.docket/audit.log` -- one JSON object per line (seq, ts
(millisecond resolution), user, pid, action, detail, prev_hash), never
containing secret values. Every line chains to the previous one via a
SHA-256 prev_hash (stdlib hashlib, no new dependency); `verify` detects a
hand-tampered line, and a line without `seq`/`prev_hash` is a break.
Rotates to a single-generation `audit.log.1` backup once past
AUDIT_LOG_MAX_BYTES (default 5 MiB, env-overridable); the first entry
after a rotation claims continuity, and `verify` checks that claim
against the backup. Best-effort and never raises; there
is no environment kill switch -- recording cannot be silently disabled.
Always exits 0 for the listing forms (malformed lines are skipped, not
fatal); `verify` exits 1 on a detected broken chain link.


---

### policies

**Usage:** `docket policies`

Manage tool-approval policies.

Manages declarative guardrail policies evaluated on each agent turn.

Subcommands: `list` installed policies; `show <name>` prints one
policy's JSON; `init` copies the 6 baseline templates
(block-destructive, prompt-injection, secret-pii-redact, and the three
high-risk-action-class policies: high-risk-payment, high-risk-deploy,
high-risk-credentials); `validate \[id|file.json\]` schema-checks one (or
every) installed policy, including that its regex compiles; `test <hook>
<role> <text> \[--tool <name>\]` dry-runs the evaluator, emitting no
traces. Valid `<hook>` values for `test` are pre_input, pre_tool_call,
and pre_output -- a policy can fire at enqueue time, before a tool call,
or on a hop's output. For pre_tool_call, `--tool` (default `bash`) names
the built-in tool being simulated: an exec tool is judged by the command
classifier plus the policy hook, exactly like the live gate; any other
kind is judged by the policy hook alone, because the live gate
classifies exec commands only.

A policy file that fails validation is never silently skipped: every
call it could have governed fails closed (`block`, attributed to the
file) until it is fixed or removed, and `docket doctor` reports it.


---

### plugins

**Usage:** `docket plugins`

List predicate plugins an operator has applied.

Subcommand: `list \[--pod <p>\]` prints every predicate a policy's `when:
{plugin: ...}` can reach -- global (`~/.docket/plugins/`) then that
pod's own `config/plugins/`, each with its scope, file and sha256.
Docket never loads a plugin from a codebase; `docket pod <p> apply` is
what copies a recipe's `plugins/*.py` into pod scope.


---

### approve

**Usage:** `docket approve`

Approve a pending tool-action.

Grants a pending HITL approval token from docket's own approval store
($APPROVALS_DIR). With no token, lists pending approvals; with a token,
grants it. Token format: apr-*. Returns exit 1 if the token is not
found, or if you resolve it to the opposite verdict from what it already
has; re-resolving to the same verdict it already has is treated as an
idempotent no-op -- a warning, but exit 0. An apr-* token is created by
docket itself, from an in-turn `ask` verdict on a tool call
(`dispatch_tool`, blocking that call until answered), a pod-dispatch hop
held on a requireApprovalRoles/pipeline approval step, or a task a
guardrail policy flagged at enqueue. This store is the only approval
mechanism, and
`docket approve`/`docket deny` (plus the HTTP and MCP equivalents, and a
Telegram reply in a wired chat) are the only ways to answer it, each
audit-logged with the channel that answered. See also `docket deny`.


---

### deny

**Usage:** `docket deny`

Deny a pending tool-action.

Denies a pending HITL approval token from docket's own approval store
($APPROVALS_DIR). With no token, lists pending approvals; with a token,
denies it. Same token format, idempotency, and provenance rules as
`docket approve` -- see its help for the full contract.


---

### inbox

**Usage:** `docket inbox`

List everything across every pod that needs you: waiting/blocked tasks and pending
approvals, plus failed/done/running context.

`docket inbox \[--json\] \[--since <iso>\] \[--peek\]`. A plain call advances a durable cursor so a
repeat call's `Done` section only shows newly-terminal tasks; `--peek` reads without
advancing it, and `--since <iso>` overrides the stored cursor for one call without touching
it either. `--json` emits the same shape `docket serve`'s `GET /inbox` returns.


---

### chat

**Usage:** `docket chat`

See and answer one task's parked question.

`docket chat <task-id> \[--pod <project>\]` -- searches every pod for *task-id* (or just
*pod* when given), then shows its brief, its pending question (if any) and its earlier
answers. On a TTY, a pending question is followed by one prompt per schema property and
then answered through the same `core.answers.answer_task` every other surface calls
(`channel="cli"`, `actor=<OS user>`). Off a TTY, or with no pending question, this only
ever displays -- use `docket pod <p> answer` to answer non-interactively.


---

## Observability Commands

### runs

**Usage:** `docket runs`

Inspect the dispatch run registry (list/show/cancel/prune) -- one record per invocation.

One persisted record per pod-dispatch invocation, whatever triggered it
(the CLI, the `docket serve` webhook, a due schedule, or the sweep loop).
Answers "is it done, did it fail, or did it never run" for background
dispatch, whose failures are otherwise invisible.

Subcommands: `list \[--project <project>\] \[--json\]`; `show <run-id>
\[--json\]`; `cancel <run-id>` persists one cancellation request and
signals every in-flight hop process group -- queued work is terminal
immediately, a running record stays "running (cancel requested)" until
the executor observes the request and fully stops, then the task and run
become cancelled; writes one audit entry; in-process backend work
already executing returns to a safe checkpoint, where its late response
is discarded before any tool or later pipeline hop can start. `prune
\[--dry-run\] \[--days N\]` deletes terminal (succeeded/failed/cancelled)
records past the retention window (default `TRACE_RETENTION_DAYS`) --
the same pruning `docket serve`'s periodic sweep already does; queued
and running records are never touched.

A run record's `source` is one of cli|webhook|schedule|sweep|mcp;
`state` is one of queued|running|succeeded|failed|cancelled. A failed
run carries the exception text in `error`. Persisted to
`~/.docket/docket-runs.json`. `show` and both JSON read surfaces expose
cancellation requestedAt/observedAt/stoppedAt; a missing stop timestamp
means the executor has not fully returned yet. `POST /dispatch/<project>`
(see `docket serve`) returns {"run": "<id>"} immediately, before any
dispatch work is attempted; `GET /runs/<id>` and `GET /runs?project=`
mirror this command over HTTP (Bearer-authed, same as /approvals).


---

### trace

**Usage:** `docket trace`

View agent execution traces.

Every dispatch hop emits a JSONL trace event; use this to inspect them.
Subcommands: `<session-id>` renders one session human-readable; `tail
<project>` follows the latest open session live; `export <project>
\[--since DATE\]` is a raw JSONL passthrough; `ingest <project>` projects
docket's own session store into the trace store.

Traces are stored at `~/.docket/traces/<project>/<session-id>.jsonl`.
Each dispatch hop writes events such as tool_call, cost_charged,
approval_requested.


---

### metrics

**Usage:** `docket metrics`

Show session success-rate and drift metrics.

Computes success rate, latency, cost, and guardrail trip counts from
trace data. `-r`/`--role` filters to a specific agent role; `-p`/
`--project` to a specific project; `-w`/`--window N` (default 50,
METRICS_WINDOW env-overridable) sets the rolling window size in
sessions. Output: success rate, duration (mean/p95), cost (total/mean),
and guardrail trip counts.

`--escalation` prints escalation metrics instead: task starts (dispatch claims),
operator questions by kind and outcome, and decision latency.


---

### harness

**Usage:** `docket harness`

Run one agent, one turn, to completion, for a caller-owned workspace and home.

`run --workspace DIR (--task TEXT | --task-file PATH) --model
PROVIDER/ID \[--role implementer\] \[--timeout S\] \[--agent-id ID\]` executes
synchronously and streams newline-delimited JSON events on stdout,
finishing with exactly one versioned result object -- see
`docs/adr/0001-harness-mode.md` and `specs/api/harness-mode.spec.md` for
the full wire contract. stdout carries only that NDJSON; every log goes
to stderr.

Refuses (exit 2, one `result` with `status: refused`) unless `DOCKET_HOME`
is set to a caller-owned directory (never the operator's own default
home), `DOCKET_LLM_BASE_URL` is set, `DOCKET_NO_TRACE` is unset, and
`--workspace` is a real directory -- this command never touches the
operator's own approvals or audit log. Approval mode is fixed to
non-interactive refusal: a tool call that would otherwise wait for a
human is denied immediately as `blocked` rather than hanging for up to
two minutes. On `SIGTERM` it persists a cancellation request, kills any
in-flight tool subprocess's process group, and exits with a `cancelled`
result. Exit codes: 0 the run's result is `ok`; 1 it ended `failed`,
`blocked`, or `cancelled`; 2 refused before any run started -- the one
named exception to this CLI's flat 0/1 convention.

`status TOKEN` reports whether a run token from a prior `run` invocation
is `live`, `finished` (with a best-effort reconstructed result), or
`unknown`.


---

### exporters

**Usage:** `docket exporters`

Observability export destinations: list, inspect, and enable by authenticating.

Subcommands: `list \[--json\]` prints every catalog exporter's dialect,
activation state, credential names and its privacy level (SHARES). `show
<name> \[--json\]` prints one exporter's effective document, source, state,
health counters and a "Leaves this host" disclosure of every content
class. `enable <name> \[--endpoint URL\] \[--privacy <level>|--share a,b\]
\[--events ...\] \[--no-verify\] \[--yes\]` prompts for a missing credential on
a TTY (else names `docket keys add` and exits), probes the endpoint, and
writes only the `enabled` flag plus the overrides given. `disable <name>`
turns it back off; stored keys are kept. `test <name>` re-probes without
changing anything. `add <file.yaml> \[--no-verify\] \[--yes\]` and `remove
<name>` manage a full document; `export <name> \[<file>\]` prints or writes
one back out. `privacy <name> \[<level>|--share a,b\] \[--max-chars N\]
\[--yes\]` shows or changes what an exporter shares beyond bare structure;
widening the shared classes prints what is newly granted and the
destination host, then asks for confirmation on a TTY or refuses off one
without `--yes` -- narrowing never asks. `preview <name> \[--session <id>\] \[--level
<level>|--share a,b\] \[--json\]` projects a local session through the
exporter's policy and prints what it would send -- no network call, no
write.


---

### channels

**Usage:** `docket channels`

Notification/conversation/decision destinations: list, inspect, and enable.

Subcommands: `list \[--json\]` prints every catalog channel's dialect,
enabled state, capabilities and content level. `show <name> \[--json\]`
prints one channel's effective document and scope. `enable <name> \[--set
k=v ...\]` writes only the `enabled` flag plus the overrides given (`--set
actors=a,b` sets the actors list, `--set secret=NAME` sets the credential
name, anything else lands in `config`); it refuses without writing when a
required field the built-in names is still empty (`ntfy` needs a
non-empty `topic`, `telegram` needs a non-empty `actors`). `disable
<name>` turns it back off. `add <file.yaml>` and `remove <name>` manage a
full document; `export <name> \[<file>\]` prints or writes one back out.
`content <name> \[<level>\] \[--yes\]` shows or changes how much a delivery
carries (`minimal < actions < conversation`); widening prints the change
and asks for confirmation on a TTY or refuses off one without `--yes` --
narrowing never asks. `test <name>` sends one synthetic
`dev.docket.channel.test` event through that one channel and reports
success or failure -- useful to verify a webhook URL or a command binary
before relying on it. Every other subcommand here only edits the catalog;
`test` and `docket notify` are the only things in this command group that
ever send anything.


---

### notify

**Usage:** `docket notify`

Flush operator events to every enabled channel.

`docket serve`'s sweep and `docket pod <p> dispatch` already flush after every real
state change; this command forces one in between, or previews it. `docket notify
flush \[--dry-run\]` -- with no `--dry-run`, diffs the inbox against the last flush,
delivers each new event (`dev.docket.task.*`/`approval.*`) to every enabled channel
whose `on` matches, and prints the counts; `--dry-run` prints what would be sent
without delivering or advancing the dedupe snapshot.


---

## Global Options

### --help / -h

Show Typer's auto-generated help for `docket` or any subcommand.

**Syntax:**
```bash
docket --help
docket -h
docket <command> --help
```

### help

Show help.

With no topic, docket's full hand-written command reference (common
commands and the current role->model policy) -- richer than
`docket --help`'s auto-generated command list; always exits 0. With a
topic, that command's own usage text (exit 0), or an unknown-command
error naming it (exit 1).

**Syntax:**
```bash
docket help
```

**Aliases:** None

### --version / -V

Show the installed docket version.

**Syntax:**
```bash
docket --version
docket -V
```


---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (includes `approve`/`deny` re-resolving a token to the verdict it already has) |
| 1 | Error (generic; also used by `approve`/`deny` on an unknown token or one being flipped to the opposite verdict, and `docket init`'s missing-dependency check) |
| 2 | Usage/refusal error: Typer's own automatic response to a missing or invalid argument, `docket harness run`'s `--workspace`/`--task`/preflight refusal, or an unrecognized flag or subcommand on a manually parsed command (e.g. `gates`, `context`, `maintain`) |

No command emits any other exit code today.


---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCKET_HOME` | Root of everything docket owns — the only state root; no external daemon directory exists | `~/.docket` |
| `TRACES_DIR` | Root of per-session trace JSONL files (`docket trace`) | `$DOCKET_HOME/traces` |
| `POLICIES_DIR` | Root of installed/edited policy JSON (`docket policies`, `docket gates`) | `$DOCKET_HOME/policies` |
| `PLUGINS_DIR` | Root of operator-applied predicate plugins (`docket plugins`, a policy's `when.plugin`) | `$DOCKET_HOME/plugins` |
| `SKILLS_DIR` | The operator's own Agent Skills, the outermost of the three scopes `core.skills.discover_skills` reads | `$DOCKET_HOME/skills` |
| `APPROVALS_DIR` | Where `docket approve`/`deny`'s approval-token store lives | `$DOCKET_HOME/approvals` |
| `CORRECTIONS_DIR` | Per-pod append-only ledger of operator decisions and rejections (`docket pod <p> corrections`) | `$DOCKET_HOME/corrections` |
| `SCHEDULE_FILE` | The persisted `docket schedule` registry | `$DOCKET_HOME/docket-schedules.json` |
| `RUNS_FILE` | The persisted dispatch-run registry — one record per `dispatch_pod` invocation | `$DOCKET_HOME/docket-runs.json` |
| `SESSIONS_DIR` | Root of durable per-session turn history (`core/session.py`) | `$DOCKET_HOME/sessions` |
| `MCP_SERVERS_FILE` | Registry of configured external MCP tool servers (`docket mcp servers`) | `$DOCKET_HOME/docket-mcp-servers.json` |
| `PROVIDERS_FILE` | Global provider catalog scope (`docket models provider add`, `core/provider.py`) | `$DOCKET_HOME/docket-providers.json` |
| `EXPORTERS_FILE` | Global exporter catalog scope (`core/exporter.py`) | `$DOCKET_HOME/docket-exporters.json` |
| `EXPORTERS_HEALTH_FILE` | Per-exporter delivery counters and last-error state (`core/exporter.py::read_health`) | `$DOCKET_HOME/exporters-health.json` |
| `CHANNELS_FILE` | Global channel catalog scope (`core/channel.py`) | `$DOCKET_HOME/docket-channels.json` |
| `NOTIFY_STATE_FILE` | `core/notify.py::flush`'s dedupe snapshot, so two flushes over the same state deliver each event once | `$DOCKET_HOME/notify-state.json` |
| `CHANNELS_HEALTH_FILE` | Per-channel delivery counters and last-error state (`core/notify.py::flush`) | `$DOCKET_HOME/channels-health.json` |
| `FLEET_FILE` | Agent registration, channel bindings, gate/isolation flags, org default model | `$DOCKET_HOME/fleet.json` |
| `AUDIT_LOG_MAX_BYTES` | Audit-log rotation threshold (`docket audit`) | `5242880` (5 MiB) |
| `SESSION_TIMEOUT` | Age past which an expired approval is denied (fail-closed) | `3600` |
| `APPROVAL_TIMEOUT` | The async approval-gate window (`core/dispatch.py`'s `require_approval`) — a task waits `waiting_approval`; no process or turn is blocked on it | `900` |
| `TOOL_APPROVAL_TIMEOUT` | The in-turn approval wait (`core/approval.py`'s `wait_for_approval`) — blocks a live tool call, so it is far shorter than `APPROVAL_TIMEOUT` | `120` |
| `TOOL_APPROVAL_POLL_INTERVAL_S` | How often the in-turn approval wait re-checks the record while blocked | `2` |
| `CLAIM_STALE_TIMEOUT` | A pod task claimed longer than this without finishing is presumed crashed and failed by the dispatch sweep | `1800` |
| `METRICS_WINDOW` | Rolling terminal-session count for `docket metrics` | `50` |
| `RUNAWAY_TURNS_THRESHOLD` | Past this many turns, `docket doctor`/`docket cost` flag a session as runaway | `200` |
| `RUNAWAY_COST_THRESHOLD` | Past this estimated USD, `docket doctor`/`docket cost` flag a session as runaway | `20` |
| `DOCKET_KEY_MAX_AGE_DAYS` | `docket doctor`'s key-hygiene report flags a stored secret STALE past this age — a rotation nudge, never an expiry | `90` |
| `TRACE_RETENTION_DAYS` | How long a terminated trace file survives before `docket trace expire` deletes it | `30` |
| `EXPORT_QUEUE_MAX` | Bound on the in-memory span queue the background exporter sender drains | `1000` |
| `EXPORT_FLUSH_TIMEOUT_S` | Per-flush wall-clock bound for the background exporter sender | `5.0` |
| `TEMPLATE_VERSION` | Workspace-prompt schema version; `docket doctor` flags older agents for rebuild past a bump | `4` |
| `CONTEXT_BYTES_PER_TOKEN` | Bytes-per-token estimator behind the static-context guards in `docket maintain check` | `4` |
| `CONTEXT_TOKEN_BUDGET` | Soft cap on the static per-turn context (SOUL+AGENTS+TOOLS+HEARTBEAT+MEMORY.md); `docket maintain check` warns past this | `6000` |
| `DISTILL_TIMEOUT_S` | Wall-clock bound on `docket maintain distill`'s one driver-backed turn | `120` |
| `DISTILL_MAX_INPUT_BYTES` | How much daily-log content goes into a distillation turn's prompt | `49152` (48 KiB) |
| `DISPATCH_RETRIES_DEFAULT` | Retry attempts after the first try for a retryable dispatch-hop failure (timeout/`daemon_error` only), for any role with no per-role override | `2` |
| `DISPATCH_RETRIES_LEAD`, `DISPATCH_RETRIES_IMPLEMENTER`, `DISPATCH_RETRIES_REVIEWER`, `DISPATCH_RETRIES_TESTER` | Per-role override of `DISPATCH_RETRIES_DEFAULT` | same as `DISPATCH_RETRIES_DEFAULT` |
| `DISPATCH_RETRY_BACKOFF_S` | Linear backoff base between retries — attempt N waits N times this many seconds | `2` |
| `DISPATCH_RETRY_MAX_WAIT_S` | Ceiling on a retry's sleep, whichever of the linear backoff or the endpoint's own `Retry-After` asked for longer | `60` |
| `DISPATCH_TURN_TIMEOUT_S` | `docket serve`-only ceiling on a dispatch hop's turn timeout, overriding a pod's own Lead-meta value for serve-triggered dispatches | unset (no serve-wide override) |
| `DISPATCH_SWEEP_WORKERS` | `docket serve --dispatch`: how many pods one sweep tick runs at once (`1` is serial) | `4` |
| `DISPATCH_VERIFY_TIMEOUT_S` | Same as `DISPATCH_TURN_TIMEOUT_S`, for the verify step | unset (no serve-wide override) |
| `AGENT_LOOP_MAX_ITERATIONS` | Hard cap on model round-trips within one turn | `20` |
| `AGENT_LOOP_MAX_TOOL_CALLS` | Hard cap on total tool calls dispatched across one turn | `40` |
| `AGENT_LOOP_NO_PROGRESS_ROUNDS` | Stops a turn after this many consecutive tool rounds that only repeat earlier results; `0` disables | `3` |
| `AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS` | Stops a denial-only loop before it consumes the iteration/tool/token limits | `3` |
| `DOCKET_TOOL_MAX_OUTPUT_CHARS` | Ceiling on one tool result's text before it is visibly truncated — tune down for a small-context endpoint | `30000` |
| `AGENT_LOOP_WALL_CLOCK_TIMEOUT_S` | Default overall wall-clock budget for one turn with no explicit `LoopConfig` | `300` |
| `AGENT_LOOP_TOKEN_BUDGET` | Hard cap on one turn's cumulative measured token usage | `100000` |
| `AGENT_LOOP_REQUEST_TIMEOUT_S` | Per-HTTP-call timeout passed to the chat backend | `120` |
| `MCP_CLIENT_TIMEOUT_S` | Default per-call bound for an MCP server with no timeout of its own | `10` |
| `MCP_CLIENT_MAX_TIMEOUT_S` | Hard ceiling every server-specified MCP timeout is clamped to | `60` |
| `FETCH_ALLOWED_DOMAINS` | Comma-separated exact hostnames the `fetch` tool may reach | empty (nothing allowed until opted in) |
| `FETCH_MAX_RESPONSE_BYTES` | Response-body cap for the `fetch` tool before truncation | `200000` |
| `FETCH_TIMEOUT_S` | Default per-call wall-clock bound for the `fetch` tool | `15` |
| `TELEGRAM_POLL_TIMEOUT_S` | The Telegram-side long-poll wait passed to `getUpdates` | `25` |
| `TELEGRAM_REQUEST_TIMEOUT_S` | This process's own socket timeout for Telegram calls — must exceed `TELEGRAM_POLL_TIMEOUT_S` | `35` |
| `DOCKET_SECRETS_BACKEND` | Stored-secret backend: `file` (default, `secrets.json`) or `keyring` (secret-tool/libsecret) | `file` |
| `DOCKET_KEYRING_SERVICE` | The libsecret service name secrets are stored under when `DOCKET_SECRETS_BACKEND=keyring` | `docket-cli` |
| `DOCKET_NO_TRACE` | Set to `1` to disable trace-store writes | unset (tracing on) |
| `DOCKET_NO_EXPORT` | Set to `1` to disable every export queue/flush action | unset (export on) |
| `DOCKET_SANDBOX_IMAGE` | Image for the Docker exec-jail (`docket gates isolate on`) | `alpine:3.20` |
| `DOCKET_SANDBOX_BACKEND` | Force or disable the sandbox backend (`docker`/`bwrap`/`none`) regardless of what is actually installed | auto-detected (docker > bwrap > none) |
| `EDITOR` | Text editor for `docket edit`, checked before `VISUAL` | `nano` |
| `VISUAL` | Fallback text editor for `docket edit` when `EDITOR` is unset | `nano` |
| `DOCKET_SERVE_TOKEN` | Fix `docket serve`'s bearer token instead of generating one per run | unset (random) |
| `DOCKET_LLM_BASE_URL` | Process-wide override that points every model at one endpoint (local dev, tests without stored config) | unset |
| `DOCKET_LLM_API_KEY` | Process-wide API key override, paired with `DOCKET_LLM_BASE_URL` | unset |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `OPENROUTER_API_KEY`, `AI_GATEWAY_API_KEY`, `VERCEL_OIDC_TOKEN`, `GROQ_API_KEY`, `MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `CEREBRAS_API_KEY`, `TOGETHER_API_KEY` | Per-provider API key, named by a built-in provider document's `auth.credentials` (`core/provider.py`'s catalog), checked when neither `DOCKET_LLM_API_KEY` nor a catalog-resolved credential is already present; also checked against docket's own secret store (`docket keys add`). A provider absent from the catalog falls back to `<PROVIDER>_API_KEY` | unset |
| `DOCKET_CLI_ROOT` | Repo root override used by the `bin/docket` launcher to select which project to `uv run` against | package/launcher location |
| `DOCKET_PYTHON` | Explicit interpreter for `bin/docket` to exec (e.g. a Homebrew venv) | unset (auto-resolved) |

There is **no** environment kill switch for the audit log — a prior `DOCKET_NO_AUDIT` escape hatch was removed because it let anyone silently disable docket's only tamper record; audit writes are unconditional and best-effort (a write failure never raises, but it also can't be turned off).


---

## Tips & Tricks

### Interactive Pickers

If you have fzf installed, omit the agent-id for fuzzy search:

```bash
docket info      # Opens fzf picker
docket delete    # Opens fzf picker
docket logs      # Opens fzf picker
```

### Batch Operations

Use bash loops for batch operations:

```bash
# Reset all agents
for id in $(docket list | awk '{print $1}' | tail -n +2); do
  docket maintain "$id" clean
done

# Cheaper models fleet-wide: change the policy once — every
# policy-following agent updates automatically (pins are untouched)
docket models preset openrouter-free
```

### Cost Monitoring

Track daily costs:

```bash
# Add to crontab
0 23 * * * docket cost >> ~/docket-costs-$(date +%Y-%m).log
```

### Backup Strategy

Regular backups:

```bash
# Backup script
#!/bin/bash
tar -czf ~/backups/docket-$(date +%s).tar.gz \
  ~/.docket/fleet.json \
  ~/.docket/workspaces/

# Or a single-file fleet snapshot
docket snapshot -o ~/backups/fleet-$(date +%s).json
```


---

## Next Steps

- [Agent Teams (Pods)](AGENT-TEAMS.md)
- [Workflow Guide](WORKFLOW-GUIDE.md)
- [Main README](../README.md)
