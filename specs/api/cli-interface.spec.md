# CLI Interface Contract Specification

**Version**: 1.13.1
**Status**: Complete
**Last Updated**: 2026-08-04

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

- `global-options` MUST precede the command (see [Options](#options)).
- `command` MUST be one of the entries in the Command Registry below.
- `arguments` are positional and command-specific (see [Arguments](#arguments)).

When a required `agent-id` argument is omitted, commands that operate on a single agent
MUST fall back to interactive selection (fzf when available, otherwise a numbered menu).
The per-command entries in the Command Registry are the authoritative source for each
command's exact syntax.

## Arguments

Positional arguments are command-specific; the following conventions apply across commands:

| Argument | Applies to | Rules |
|----------|------------|-------|
| `agent-id` | most commands | MUST match `^[a-z0-9][a-z0-9-]*[a-z0-9]$`; MAY be omitted where an interactive picker can supply it |
| `location` | `add` | MUST be absolute or tilde-expanded. For a `codebase`-kind blueprint (`software`) MUST exist and be readable, same as the pre-W-7 `codebase-path`; for a `workdir`-kind blueprint (`research`/`content`/`ops`) docket creates it if absent |
| `provider/model` | `profile` | MUST be well-formed `<provider>/<model-id>`; or the literal `default` to re-attach to the role policy |
| `action` | `scope`, `keys`, `pod`, `gates` | MUST be a verb from that command's documented action set |

Unrecognized or excess positional arguments MUST produce a clear error and exit 1.

## Options

Options are `--long` flags, some with a `-short` alias. The global options listed above are
accepted by every command; command-specific options are listed per command in the Command
Registry. Conventions:

- Boolean flags default to `false` and take no value (e.g. `--force`, `--debug`).
- Value options take exactly one argument (e.g. `--model <provider/model>`, `--days <N>`).
- `--help`/`-h` MUST be honored before any other parsing and exit 0.
- Unknown options MUST produce a clear error and exit non-zero (Typer's usage error).

## Global Command Structure

### Syntax Pattern

```
docket [global-options] <command> [command-options] [arguments]
```

### Global Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| --help | -h | Show help message | - |
| --version | -v | Show version info | - |
| --debug | -d | Enable debug output | false |
| --quiet | -q | Suppress informational output | false |
| --config | -c | Use alternate config file | ~/.docket/docket.conf |
| --no-color | - | Disable colored output | false |

## Command Registry

### Core Commands

#### docket install
**Purpose**: Bootstrap a docket-native home and specialist agents (ROADMAP Phase 19 P19-7b —
no external daemon involved any more)
**Syntax**: `docket install [--portfolio] [--gates]`
**Arguments**: None
**Options**:
- `--portfolio`: Also provision the optional org Portfolio Manager (one `portfolio-manager` agent, `scope: org`)
- `--gates`: Enable enforced exec-approval gates at install time (otherwise opt-in via `docket gates enable`)
**Output**: Progress messages and success confirmation
**Return**: 0 on success, 1-5 on various failures

#### docket add
**Purpose**: Provision a project pod from a blueprint (Lead + Implementer against a codebase by
default — see pod-blueprints.spec.md, ROADMAP Phase 16 W-7)
**Syntax**: `docket add <project> [location] [--blueprint <name>] [options]`
**Arguments**:
- `project` (required): Project name / pod identifier (slugified to `^[a-z0-9][a-z0-9-]*[a-z0-9]$`)
- `location` (optional): Meaning depends on the selected blueprint's `workspaceKind` — a codebase
  path for `software` (the default), or a working directory for `research`/`content`/`ops`
  (auto-provisioned if omitted)
**Options**:
- `--blueprint <name>`: Select a pod blueprint (`software` | `research` | `content` | `ops`);
  omitted defaults to `software` — unchanged from pre-W-7 `docket add`. An unknown name fails
  cleanly (exit 1) before any prompt is shown
- `--codebase <path>` / `--path <path>`: Explicit location, skipping its interactive prompt
- `--name <text>`: Explicit display name, skipping its interactive prompt
- `--pod full`: Provision a full pod — Lead, Implementer, Reviewer, and Tester. Applies only to
  the `software` blueprint
- `--with <roles>`: Start from the lean pod and add named roles (comma-separated: `reviewer`,
  `tester`, `implementer`). Applies only to the `software` blueprint; passing it with another
  blueprint warns and is ignored (that blueprint's own fixed roster is used instead)
- `--from <file>`: Declarative provisioning from a JSON/YAML spec file (idempotent); an entry
  carrying a `blueprint` field provisions a pod the same way `--blueprint` does interactively
**Output**: Creation progress and confirmation with member IDs
**Return**: 0 on success, 1 on error (pod already exists, invalid arguments, unknown blueprint,
or provisioning registered no member — docket's flat convention, see Return Code Convention below)

#### docket list
**Purpose**: Display all agents
**Syntax**: `docket list [options]`
**Arguments**: None
**Options**:
- `--format <table|json|csv>`: Output format (default: table)
- `--filter <active|stopped|all>`: Filter agents (default: all)
- `--sort <id|type|activity>`: Sort order (default: id)
**Output**: Formatted agent list
**Return**: 0 always

#### docket info
**Purpose**: Display detailed agent information
**Syntax**: `docket info <agent-id> [options]`
**Arguments**:
- `agent-id` (required): Agent identifier or interactive selection
**Options**:
- `--format <detailed|summary|json>`: Output detail level
- `--costs`: Include detailed cost breakdown
**Output**: Agent details in requested format
**Return**: 0 on success, 1 if not found

#### docket delete
**Purpose**: Remove agent completely
**Syntax**: `docket delete <agent-id> [options]`
**Arguments**:
- `agent-id` (required): Agent to delete
**Options**:
- `--force`: Skip confirmation prompt
- `--keep-logs`: Preserve memory logs before deletion
**Output**: Deletion confirmation
**Return**: 0 on success, 1 if not found

#### docket maintain
**Purpose**: Clear memory, repair, or rebuild an agent (replaces the retired `reset`/`repair`/`cleanup`)
**Syntax**: `docket maintain [agent-id] [mode] [--no-distill-first | --distill-first]`
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
- `--distill-first` (default): run `distill`'s summarize-then-archive step before the command's
  own destructive step; a failed distillation aborts the whole command before anything is deleted
- `--no-distill-first`: skip distillation and delete/clear immediately — the pre-C-2 behavior
**Output**: Maintenance progress and confirmation
**Return**: 0 on success (including a cancelled confirmation); 1 if the agent is not found, the
mode is unknown, or (`clean`/`reset`/`distill`) the distillation turn fails

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
**Purpose**: View and update the role→model policy; switch provider presets
**Syntax**: `docket models [set <role> <provider/model> | preset <name> | reset]`
**Actions**:
- (no args): Show the current role→model table (role, model, price, source, why)
- `set <role> <provider/model>`: Override the model for a specific role
- `preset <name>`: Switch all roles to a provider preset (`anthropic`, `openai`, `google`, `openrouter`, `openrouter-free`)
- `reset`: Restore built-in defaults
**Output**: Role→model table or update confirmation
**Return**: 0 on success, 1 on invalid role or preset

#### docket scope
**Purpose**: Manage session keys for project isolation
**Syntax**: `docket scope <agent-id> <action> [value]`
**Arguments**:
- `agent-id` (required): Target agent
- `action` (required): show/set/reset
- `value` (conditional): Required for 'set' action
**Output**: Current or updated session key
**Return**: 0 on success, 1 on error (agent not found, or invalid input)

#### docket keys
**Purpose**: Manage API keys centrally; keys auto-sync to all agents
**Syntax**: `docket keys [action] [key-name]`
**Actions**:
- `list`: Show all stored keys (values masked) — default
- `setup`: Interactive setup wizard for all keys
- `add <KEY_NAME>`: Add or update a specific key
- `validate [KEY_NAME]`: Test whether keys work
- `remove <KEY_NAME>`: Remove a key
- `export`: Print keys as shell environment variables
**Key names**: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `OPENROUTER_API_KEY`
**Output**: Key status or update confirmation
**Return**: 0 on success, 1 on invalid key name
**Note**: `keys` manages *workspace* secrets (project work, synced to agent `.env`). It does NOT set model auth — use `docket auth` for that.

#### docket auth
**Purpose**: Report which provider API-key credentials are stored. **ROADMAP Phase 19 P19-7b
deleted the daemon `docket auth login/key/setup` used to shell out to** (`openclaw models auth
setup-token`/`paste-token`) — there is no docket-native subscription/OAuth-style auth flow to
replace it with, and this command says so plainly rather than faking success. Distinct from
`docket keys`, which manages the workspace secrets that are the real working credential path.
**Syntax**: `docket auth [action] [--provider <name>]`
**Actions**:
- `status` (default, no subcommand): List which `<PROVIDER>_API_KEY` names are present in
  docket's own secret store (`core/secrets.py`) and point at `docket keys add` as the real path
- `login [--provider <name>]`, `key [--provider <name>]`, `setup [--provider <name>]`: **all
  return exit 1** with a message naming the real working path (`docket keys add
  <PROVIDER>_API_KEY`) — no docket-native replacement exists yet
**Options**: `--provider <name>` — which provider's env-var name to report/name in the message; defaults to `anthropic` when omitted.
**Output**: For `status`, the list of stored provider keys (or a warning that none are stored). For `login`/`key`/`setup`, the honest-gone error message.
**Return**: 0 for `status`; 1 for `login`/`key`/`setup` (always — there is nothing for them to succeed at)

### Pipeline Commands

`docket workflow` (the Lobster YAML surface: author/validate/plan a `.lobster.yml` template)
was **retired** in Phase 16 (D-16) — its validator silently ignored four constructs its own
template emitted, so docket was linting a dialect it could not fully execute. Running
`docket workflow <anything>` (or its former `wf` alias) prints a removed-command notice pointing
at `docket pipeline validate` / `docket pipeline plan` / `docket pipeline run` — the single
pipeline dialect docket actually executes (`pipeline-format.spec.md`, Phase 16 W-1/W-2). Any
existing `<workspace>/workflows/*.lobster.yml` files are left on disk untouched, but no longer
read by docket. (The former workflow-integration.spec.md was removed 2026-07-30; ROADMAP
decision D-16 is the durable retirement record.)

#### docket pipeline
**Purpose**: Validate, plan, and run a docket-native pipeline (ROADMAP Phase 16 W-1 format / W-2
executor). See pipeline-format.spec.md for the file format.
See pod-dispatch.spec.md for how it actually runs.
Not the Lobster dialect — `docket workflow` continues to serve that unchanged until ROADMAP
Phase 16 W-3 retires it in favor of this command.
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
**Return**: `0` on success; `1` on an invalid/missing file, an unknown project/pod, or a dispatch
error (see `docket runs show <id>` for the recorded error)

### Pod Commands

`docket team` (the old org-wide manual task queue) was **retired** in 0.2.0 (D-11) — it had no
dispatcher and never executed anything. Delegation now belongs to each project's pod
(pod-dispatch.spec.md). Running `docket team <anything>` prints a removed-command notice that
maps each old subcommand to its pod equivalent below. (The former team-coordination.spec.md
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
- `remove <member-id>`: Remove a pod member
- `delegate "<task>" [--priority high|normal|low]`: Queue a task on this pod's own list
  (one queue per pod, at `~/.docket/workspaces/<project>-lead/TASK_LIST.json`)
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
**Output**: Pod roster, queue listing, or per-hop dispatch results (including cost)
**Return**: `0` on success, `1` on error (project/member not found, malformed args, no pod for
the project, or dispatch raised an exception — see `docket runs show <id>` for the recorded
error)

#### docket roles
**Purpose**: Inspect and manage declarative role archetypes — built-in, starter-library, and
user-defined (ROADMAP Phase 16 W-6; see role-archetypes.spec.md)
**Syntax**: `docket roles <list|show|add|validate> [args]`
**Actions**:
- `list`: Show every registered archetype (name, scope, model class, gate contract, edit
  rights, description)
- `show <name>`: Print one archetype's full definition (YAML, or JSON if PyYAML is unavailable)
- `add <file.yaml>`: Validate a standalone archetype YAML file and merge it into the user
  overlay (`~/.docket/docket-roles.json`); overrides a built-in/starter archetype by reusing
  its name
- `validate [file.yaml]`: With no argument, validate every archetype in the live registry; with
  a file argument, validate that candidate definition without persisting it
**Output**: Archetype listing, one archetype's definition, or a per-archetype pass/fail report
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
  `variables` its payload was dispatched with)
- `cancel <run-id>`: Kill every hop subprocess currently recorded as in-flight for that run — its
  whole process group, not just the immediate child (see pod-dispatch.spec.md's "Cancellation")
  — and mark the run terminally `cancelled`. A no-op (reported, not an error-free success) against
  a run that's already terminal. A genuine cancellation writes a `runs.cancel` audit entry
  (ROADMAP Phase 16 W-4; see audit.spec.md) naming the run, its project, its pre-cancel state,
  and how many process groups were killed — the no-op paths write nothing
**Output**: A table (or, with `--json`, the bare record(s) — see `cli-json-shapes.spec.md`); a
confirmation message for `cancel`
**Return**: `0` on success; `1` if `show`'s run id is unknown or no id was given, or if `cancel`'s
run id is unknown or already terminal

#### docket mcp

**Purpose**: Expose docket's control plane as an MCP (Model Context Protocol) stdio server
(ROADMAP Phase 18 L-3) — full contract in `mcp-server.spec.md`
**Syntax**: `docket mcp serve`
**Actions**:
- `serve`: Start the stdio MCP server (blocks until the client disconnects). Requires the
  optional `mcp` extra (`pip install 'docket[mcp]'`); prints an actionable hint and exits 1 if
  it isn't installed, rather than a bare traceback
**Output**: Nothing on stdout (stdout is the JSON-RPC transport once serving); one stderr line at
startup naming the registered tools
**Return**: `0` on clean shutdown or bare `docket mcp` (prints usage), `1` if the SDK is missing or
an unrecognized subcommand was given

### Memory and Context Commands

#### docket context
**Purpose**: Inspect and manage an agent's memory/context
**Syntax**: `docket context [agent-id] [action]`
**Actions**:
- `show`: Recent activity overview (default; any unrecognized action falls through to this)
- `project`: Show project-level context

`search`/`snapshot`/`index`/`compress` and the `SNAPSHOT.md` artifact were **removed** — see the
CHANGELOG's Unreleased "Removed" entry. Semantic search over an agent's memory (`memory_search`/
`memory_get`) was the now-deleted OpenClaw daemon's job (ROADMAP Phase 19 P19-7b) — there is no
successor, and docket does not maintain a rival keyword index, so this is a real, named gap
rather than a capability delegated elsewhere. Folding logs into `MEMORY.md` is
`docket maintain <id> distill`.
**Output**: Context view or action confirmation
**Return**: 0 on success, 1 if not found

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
**Purpose**: System diagnostics
**Syntax**: `docket doctor [--verbose]`
**Options**:
- `--verbose`: Detailed diagnostic output
**Output**: System health report
**Checks** (ROADMAP Phase 19 P19-7b — no daemon left to check status of):
- Required commands availability (`python3`, etc.)
- Fleet registry (`fleet.json`) and agent-registration validity
- Model config/registry drift
- Workspace permissions and template drift
- Dispatch ledger sync, budget/runaway spend, key hygiene, security-gate posture
**Return**: 0 if healthy, count of issues found

#### docket cost
**Purpose**: Display usage and costs
**Syntax**: `docket cost [agent-id] [--period <days>]`
**Arguments**:
- `agent-id` (optional): Specific agent or all
**Options**:
- `--period <days>`: Time window (default: 30)
- `--by-model`: Group by model
- `--csv`: Export as CSV
**Output**: Cost breakdown table
**Return**: 0 always

### Monitoring Commands

#### docket snapshot
**Purpose**: Emit JSON system state for dashboards or CI artifacts
**Syntax**: `docket snapshot [--output <file>]`
**Options**:
- `--output <file>`: Write JSON to a file instead of stdout
**Output**: JSON object (gateway status, channels, agents)
**Return**: 0 on success

#### docket serve
**Purpose**: Background loop — refresh fleet status and optionally drive pod dispatch pipelines
**Syntax**: `docket serve [--port <n>] [--interval <s>] [--dispatch]`
**Options**:
- `--port <n>`: Listen port for the read-only HTTP API (default: 7331)
- `--interval <s>`: Snapshot refresh interval in seconds (default: 30)
- `--dispatch`: On each refresh, also run every pod's pending tasks through its pipeline (real, costed LLM turns; budget-gated and traced). Off by default — plain `docket serve` is read-only.
**Output**: Serves `http://localhost:<port>/status.json`, refreshed on the interval; with `--dispatch`, also logs each dispatch hop
**Return**: 0 on clean shutdown (Ctrl-C)

### Security and Gates

#### docket gates
**Purpose**: Report/manage docket's own tool-call gate posture. **ROADMAP Phase 19 P19-3
made the gate itself (the policy engine + argument-aware command classifier) unconditionally
active on every tool call docket dispatches — there is nothing left to "enable"; ROADMAP Phase
19 P19-7b then deleted the daemon this command used to configure**, so what remains is strictly
narrower: approval-routing destination and isolation-mode posture.
**Syntax**: `docket gates <action>`
**Actions**:
- `status`: Report the gate as always-active, plus current approval-routing/isolation posture
- `enable [--force]`: Turn approval routing on (`fleet.json`'s `approvalRoutingState`); `--force`
  is accepted for CLI compatibility but is a no-op — there is no exec-approval-allowlist
  config left to (re-)apply
- `disable`: Turn approval routing off
- `isolate <on|off>`: Record (not yet enforce — the turn loop does not consult this flag)
  whether tool execution should run inside a Docker sandbox
- `classes`: List the documented high-risk action classes (money-movement, prod-deploy,
  secret-access); read-only, makes no config changes. All three are now fully enforced by
  `core/tools.py`'s `dispatch_tool` (the only execution path since P19-7b) — see
  security-gates.spec.md v0.11.0 for why prod-deploy's `git`/`npm` overlap is no longer merely
  documented policy
**Output**: Gates status or update confirmation
**Return**: 0 on success

#### docket audit
**Purpose**: Show recent recorded operator events, or verify the log's tamper-evidence chain
(see audit.spec.md for the exact recorded families and the coverage gap)
**Syntax**: `docket audit [N | --json | verify]`
**Arguments**:
- `N` (optional): Number of recent entries to show (default: 20)
**Options/Actions**:
- `--json`: Emit the raw JSONL passthrough instead of a formatted table
- `verify` (ROADMAP Phase 15 G-4): Walk the current log's `seq`/`prev_hash` hash chain and report
  the first broken link, instead of listing entries
**Output**: Timestamped log of mutating operations, or a chain-verification result
**Return**: 0 always for the listing forms; for `verify`, 0 when the chain is clean (or no log
exists yet), 1 when a broken link is detected

#### docket eval
**Purpose**: Run specialist-role structural checks and optional live golden tasks
**Syntax**: `docket eval [--live]`
**Options**:
- `--live` (env: `DOCKET_EVAL_LIVE=1`): Run live tasks against the configured model endpoint (billable)
**Output**: Pass/fail per specialist role; model optimization hints
**Return**: 0 if all pass, 1 if any fail

### Observability

#### docket trace
**Purpose**: View, tail, export, or ingest agent-action JSONL traces
**Syntax**: `docket trace <session-id | subcommand> [args]`
**Subcommands**:
- `<session-id>`: Render one session's events human-readable
- `tail <project>`: Follow the most-recent open session live
- `export <project> [--since YYYY-MM-DD]`: Print raw JSONL to stdout
- `ingest <project>`: Project the active driver's session history (`core/session.py`, via
  `DocketDriver`) into the trace store — no daemon session-JSONL format left to parse
  (ROADMAP Phase 19 P19-7b)
**Output**: Human-readable event log or raw JSONL
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
- `list`: List installed policies in `$POLICIES_DIR`
- `show <name>`: Print one policy's JSON
- `init`: Copy baseline policies (block-destructive, prompt-injection, secret-pii-redact)
- `test <hook> <role> <text>`: Dry-run the evaluator (no traces emitted)
**Output**: Policy listing, JSON, or evaluation result
**Return**: 0 on success, 1 on invalid subcommand

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
**Syntax**: `docket conversations <list|show <id>|resume <id>|set <id> [fields]>`
**Actions**:
- `list`: Table of registered conversations (agent, channel, peer, status, topic)
- `show <id>`: Print one conversation's fields
- `resume <id>`: Mark in-progress and point at the agent's durable HEARTBEAT.md/memory
- `set <id> [fields]`: Upsert registry fields (topic, status, task ref, last message)
**Output**: Registry table or confirmation
**Return**: 0 on success, 1 on error

### Telegram Commands

`docket telegram` is accepted as a silent argv alias for `docket wire` (it is not a separate
command and does not appear in `docket --help`).

#### docket wire
**Purpose**: Bind a channel group/peer to an agent — manual ID entry only (see
telegram-integration.spec.md; ROADMAP Phase 19 P19-7b removed log-based Telegram group
auto-discovery, `scan_telegram_groups`, along with the daemon gateway log it read)
**Syntax**: `docket wire [agent-id] [--channel <name>]`
**Arguments**:
- `agent-id` (optional): Target agent; interactive picker if omitted
**Output**: Prompts for the peer/group ID, records the binding in `fleet.json`, and registers the
thread in the conversation registry. No docket-owned channel bot exists yet (P19-8) — a binding
is recorded but nothing listens on it until then. There is no gateway-restart step: it was
deleted outright, not kept as a no-op (CL-C, ROADMAP Phase 19 wave 14).
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
**Output**: Command list or per-command usage
**Return**: 0 always

## Output Formats

### Standard Output Structure

```
[LEVEL] Message text
```

Levels:
- `[INFO]`: Informational messages (blue)
- `[SUCCESS]`: Operation completed (green)
- `[WARN]`: Warning conditions (yellow)
- `[ERROR]`: Error conditions (red)
- `[DEBUG]`: Debug output (gray, only with --debug)

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

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCKET_HOME` | Base directory for all docket-owned state (renamed from `OPENCLAW_DIR`, ROADMAP Phase 19 P19-6/P19-7b — the old variable and its `~/.openclaw` default are deleted, no fallback) | `~/.docket` |
| `DOCKET_DEBUG` | Enable debug (0/1) | 0 |
| `DOCKET_NO_COLOR` | Disable colors (0/1) | 0 |
| `DOCKET_MODEL_DEFAULT` | Override the fallback default model (`provider/model`) | (role policy) |
| `DOCKET_EDITOR` | Preferred editor | $EDITOR or nano |
| `DOCKET_LLM_BASE_URL` / `DOCKET_LLM_API_KEY` | Process-wide override of the OpenAI-compatible chat endpoint `DocketDriver` talks to (`edges/adapters/llm.py`'s `resolve_endpoint`) — replaces the deleted `OPENCLAW_API` daemon endpoint; there is no daemon left to point at | (per-provider resolution; no daemon endpoint) |

## Return Code Convention

docket uses a deliberately flat convention — the printed message, not the exit code,
distinguishes error kinds:

| Code | Meaning | Used By |
|------|---------|---------|
| 0 | Success | All commands |
| 1 | Any failure (not found, invalid arguments, permission, driver/model error, …) | All commands |
| 2 | SKIP (role not installed / live mode off — non-blocking for CI) | `eval` only |

No other exit codes are produced. (Earlier revisions of this spec described codes 2–9 and
127 per failure kind; those were never implemented — removed in v1.5.0.)

## Validation

Input validation rules that every command MUST enforce before performing side effects.
The authoritative rule set lives in [input-validation.spec.md](../validation/input-validation.spec.md);
the contract-level summary follows.

### Agent ID Validation
- Pattern: `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- Length: 3-50 characters
- Reserved IDs: manager, system, docket

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
1. Try fzf if available
2. Fall back to numbered menu
3. Allow typing ID directly

### Confirmation Prompts
Required for destructive operations:
- `docket delete` (unless --force)
- `docket maintain` reset/rebuild
- `docket install --clean`

Format: `"Action description. Continue? (y/N): "`

## Error Message Standards

### Format
```
[ERROR] <component>: <description>
        Details: <specifics>
        Suggestion: <how to fix>
```

### Example
```
[ERROR] Agent not found: myproject
        Details: No workspace at ~/.docket/workspaces/projects/myproject
        Suggestion: Use 'docket list' to see available agents
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
- No config migration exists or is planned — ROADMAP decision D-19 (Phase 19) is an explicit
  clean break: a pre-P19-7b install's `~/.openclaw` state (including any version marker there)
  is not read, moved, or migrated. A fresh `docket install` simply writes a new `~/.docket` home.

### Deprecated Features
- `docket reset <level>` → Use `docket maintain clean|reset|rebuild`
- `docket repair` → Use `docket maintain check`
- `docket cleanup` → Use `docket maintain sessions`
- `docket model` → Use `docket profile`
- Direct JSON editing → Use docket commands

## Changelog

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