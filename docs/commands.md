# Command Reference

Generated from the live Typer registry by `scripts/gen_cli_docs.py` — do not hand-edit. Regenerate with `uv run python scripts/gen_cli_docs.py` after changing any CLI help string; `scripts/gen_cli_docs.py --check` fails CI on drift.

Complete reference for all docket commands, rendered from each command's own `--help` text so the CLI and this document can never drift apart.

## Table of Contents

- [Daily](#daily)
- [The pod](#the-pod)
- [Machine](#machine)
- [Global Options](#global-options)
- [Exit Codes](#exit-codes)
- [Environment Variables](#environment-variables)
- [Tips and Tricks](#tips-and-tricks)
- [Next Steps](#next-steps)

## Daily

### init

**Usage:** `docket init`

Initialize the current project with its minimum isolated pod.

Creates a new project pod -- an isolated team of project-scoped agents
that owns one codebase. The default pod is lean: a Lead + an Implementer.
The first invocation also creates docket's shared workstation foundation
(fleet registry, policies, default gates) -- there is no
separate setup step. See docs/AGENT-TEAMS.md.

With no arguments, docket derives the project id, path, and stack from the
current directory (non-interactive, deterministic). Member ids are
predictable: `<project>-lead`, `<project>-implementer`, `<project>-reviewer`,
`<project>-tester` (duplicated roles get `-2`, `-3` suffixes). A pod
always has exactly one Lead. Resize a pod later with `docket pod add|remove`; tear
the whole pod down with `docket pod delete`.

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
                         no command to register a custom one.
                         See
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
                         `docket init` always has (fields: `name`,
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
                         shipped recipe by name (`docket pod recipes`
                         shows all of them). An unresolvable
                         name errors naming the shipped recipe names and
                         exits 1 before any provisioning. Mutually
                         exclusive with a present `<location>/.docket/` --
                         giving both errors naming both sources and exits
                         1 before any provisioning.
  --no-apply             provision the pod only, skipping the apply step
                         for a present `.docket/` or a resolved `--recipe`;
                         prints the `docket pod apply <dir>` command
                         that would apply it.

A repository's own `<location>/.docket/` -- the same directory shape
`docket pod apply` reads (roles/*.yaml, policies/*.json,
pipeline.yaml, pod.yaml) -- is discovered automatically: every document
under it is validated before anything is provisioned, and applied after
(unless `--no-apply`) through that same command's plan/apply path. A
validation error exits 1 naming the file and field, with nothing
provisioned. See specs/functional/pod-blueprints.spec.md, "Pod manifests:
apply".

Every project is a repo -- a pod tied to a codebase, defaulting to the cwd
(or the `path` argument / `--codebase`, in which case you are not
re-prompted); the project name is suggested from that directory's name.

Example: docket init


---

### status

**Usage:** `docket status`

Show where a pod stands: tasks, tokens, outcomes and the last run; every pod with --all.

Tokens are measured; the dollar figure is a labelled estimate, never billed spend.
--all --json also carries the fleet inventory (agents, channels, total cost).

Example: docket status --all


---

### inbox

**Usage:** `docket inbox`

List what needs you across every pod: approvals, questions, failures, finished work.

Every item carries the exact docket command that moves it forward. A plain call advances
a cursor so a repeat call shows only newly finished tasks; --peek and --since do not.

Example: docket inbox --peek


---

### task

**Usage:** `docket task`

Queue, inspect and answer a pod's tasks.

### task add

**Usage:** `docket task add`

Queue a task for the pod; `docket run` works the queue.

Example: docket task add "fix the login redirect"

### task list

**Usage:** `docket task list`

The pod's task queue with status, cost and the worktree path when one exists.

Example: docket task list --json

### task show

**Usage:** `docket task show`

One task's whole story: hops, evidence, runs, corrections and its worktree.

Example: docket task show task-04ff

### task diff

**Usage:** `docket task diff`

Print what the task changed in its worktree, against the commit it started from.

Example: docket task diff task-04ff

### task trace

**Usage:** `docket task trace`

The task's trace: every tool call, model call, cost and approval, in order.

Example: docket task trace task-04ff --tail

### task prune

**Usage:** `docket task prune`

Remove finished tasks' worktrees; with --traces, also expire old traces and run records.

A dirty worktree or unmerged branch is kept unless --force.

Example: docket task prune --dry-run

### task approve

**Usage:** `docket task approve`

Approve what a task is waiting on, or pre-grant one command before it asks.

Resolves the task's pending approval and grants it; with --task the same call is also
allowed for the rest of the task. --for records a single-use pre-grant for one exact
command instead.

Example: docket task approve 2026-10-08T10-00 --reason "reviewed the diff"

### task deny

**Usage:** `docket task deny`

Deny what a task is waiting on; the task fails and nothing runs.

Example: docket task deny 2026-10-08T10-00 --reason "touches production"

### task answer

**Usage:** `docket task answer`

Answer the question a task is parked on and let it continue.

On a terminal with no text or option it shows the question and prompts. Off a terminal
pass text, --field name=value or --option <id>; a question with options needs --option.

Example: docket task answer 2026-10-08T10-00 --option opt2

### task retry

**Usage:** `docket task retry`

Put a failed or blocked task back on the queue, keeping the hops it finished.

Example: docket task retry 2026-10-08T10-00

### task cancel

**Usage:** `docket task cancel`

Stop the run a task is in and settle a claim left behind by a dead dispatch.

A live run is asked to stop and its processes are signalled. A task still marked running
whose dispatcher is gone is settled as failed, ready for `docket task retry`.

Example: docket task cancel 2026-10-08T10-00


---

### run

**Usage:** `docket run`

Run the pod's pending tasks through its pipeline, one real agent turn per hop.

Each task is claimed before its first hop and every hop is saved as it finishes, so a
crash loses at most the hop in flight. --dry-run prints the plan the executor would
follow and starts nothing; --resume reclaims stale claims and clears a budget pause.

Example: docket run --dry-run


---

## The pod

### pod

**Usage:** `docket pod`

Manage this project's pod: members, settings and configuration.

### pod show

**Usage:** `docket pod show`

The pod: members, settings and the approval mode dispatch will use, with sources.

With a member id, that member's whole effective configuration instead.

Example: docket pod show

### pod add

**Usage:** `docket pod add`

Add members of a role to the pod.

Example: docket pod add reviewer

### pod remove

**Usage:** `docket pod remove`

Remove a member and its workspace. The Lead is removed only with the pod.

Example: docket pod remove demo-reviewer

### pod reset

**Usage:** `docket pod reset`

Distill a member's memory, then clear it and rebuild its workspace files.

Example: docket pod reset demo-implementer

### pod delete

**Usage:** `docket pod delete`

Destroy the pod: every member, workspace, session and trace. The audit log stays.

Example: docket pod delete --confirm demo

### pod set

**Usage:** `docket pod set`

Set a pod setting; with --member, set an implementer's verify command.

Example: docket pod set budgetUsd 5

### pod unset

**Usage:** `docket pod unset`

Clear a pod setting back to its default; with --member, clear a verify command.

Example: docket pod unset verify --member demo-implementer

### pod apply

**Usage:** `docket pod apply`

Install configuration onto the pod, or re-sync its instructions.

A recipe name or a directory is planned and written whole. A single role or
policy file installs that document. With no argument, members whose SOUL,
AGENTS or TOOLS are stale are re-rendered from the current archetypes.

Example: docket pod apply .docket --dry-run

### pod export

**Usage:** `docket pod export`

Write the pod's own configuration into a directory.

The default is the repository's .docket/, the form `pod apply` and `docket
init` read back. A non-empty directory is refused unless --force.

Example: docket pod export .docket --force

### pod validate

**Usage:** `docket pod validate`

Validate any configuration document, or every document in a directory.

The default is .docket/ in the current directory when it exists, else the
directory itself. Roles, policies, pipelines, pod manifests and MCP server
documents are each checked by the validator that owns their kind. Exit 1 when
any is invalid.

Example: docket pod validate .docket

### pod plan

**Usage:** `docket pod plan`

Show the steps the pod's pipeline would run, from the real executor.

Without --pipeline the pod's bound pipeline is planned, else its default
order. Nothing is started and no tokens are spent.

Example: docket pod plan --pipeline review.yaml

### pod check

**Usage:** `docket pod check`

Would the pod's rules allow this? A dry run; no traces are written.

An exec tool is judged by the command classifier plus the policy hook, as the
live gate does; any other tool by the policy hook alone.

Example: docket pod check "git push origin production" --role implementer

### pod recipes

**Usage:** `docket pod recipes`

List the recipe library, or show one recipe.

Recipes resolve nearest scope first: your own ~/.docket/recipes/ before the
shipped library. Nothing is installed; `pod apply` installs.

Example: docket pod recipes tdd

### pod roles

**Usage:** `docket pod roles`

List the role archetypes, or show one in full.

The registry is built-ins, the starter library, your overlay and, inside a
pod, the pod's own overlay (nearest wins). Install one with `pod apply`.

Example: docket pod roles reviewer

### pod policies

**Usage:** `docket pod policies`

List the guardrail policies in force, or show one.

The global set plus, inside a pod, the pod's own files; a pod only ever adds.
--plugins adds the predicate plugins a rule's `when:` can reach. Judge a call
with `pod check`.

Example: docket pod policies block-destructive


---

### log

**Usage:** `docket log`

The hash-chained record of what was authorized and done.

### log verify

**Usage:** `docket log verify`

Check the chain; exit 1 and name the first broken line if it was altered.

Example: docket log verify


---

## Machine

### setup

**Usage:** `docket setup`

Set up this workstation: model endpoint, notifications, sandbox, shell.

Bare, this is the first run: the report, then only what is missing. On a terminal it asks for what is missing, required first, and prints every
command it runs. Off a terminal it prints the report and exits 1 when the
model endpoint is missing. --fix repairs detected drift.

Example: docket setup

### setup shell

**Usage:** `docket setup shell`

Print the completion script for bash or zsh.

Enable it for the current shell with: eval "$(docket setup shell bash)"

Example: docket setup shell zsh

### setup provider

**Usage:** `docket setup provider`

Model endpoints and their credentials.

### setup provider add

**Usage:** `docket setup provider add`

Add a provider: store its credential, probe /models, apply its preset.

Example: docket setup provider add anthropic --credential <key>

### setup provider list

**Usage:** `docket setup provider list`

List every provider with its scope, dialect, URL and credential.

Example: docket setup provider list

### setup provider show

**Usage:** `docket setup provider show`

Show one provider's document.

Example: docket setup provider show local

### setup provider remove

**Usage:** `docket setup provider remove`

Remove a provider's global document and its stored credential.

Example: docket setup provider remove local --yes

### setup provider export

**Usage:** `docket setup provider export`

Print a provider as a kind: provider document.

Example: docket setup provider export local provider.yaml

### setup provider rotate

**Usage:** `docket setup provider rotate`

Replace a provider's stored credential.

Example: docket setup provider rotate anthropic

### setup model

**Usage:** `docket setup model`

Which model each role runs on (bare: show the policy).

Example: docket setup model

### setup model list

**Usage:** `docket setup model list`

Show the role to model policy with pricing and source.

Example: docket setup model list --json

### setup model set

**Usage:** `docket setup model set`

Pin one role (or the default) to a model.

Example: docket setup model set implementer anthropic/claude-sonnet-4-5

### setup model preset

**Usage:** `docket setup model preset`

List the provider presets, or apply one to every role.

Example: docket setup model preset local

### setup model reset

**Usage:** `docket setup model reset`

Remove every override and restore the built-in role policy.

Example: docket setup model reset --yes

### setup sandbox

**Usage:** `docket setup sandbox`

Workspace isolation and sandbox network (bare: show the state).

Example: docket setup sandbox

### setup sandbox status

**Usage:** `docket setup sandbox status`

Show the gate, isolation and network posture.

Example: docket setup sandbox status --json

### setup sandbox on

**Usage:** `docket setup sandbox on`

Run tools inside a sandbox (bwrap, else docker).

Example: docket setup sandbox on

### setup sandbox off

**Usage:** `docket setup sandbox off`

Run tools on the host.

Example: docket setup sandbox off

### setup sandbox network

**Usage:** `docket setup sandbox network`

Cut the sandbox's network (none) or leave it open.

Example: docket setup sandbox network none

### setup sandbox classes

**Usage:** `docket setup sandbox classes`

List the high-risk action classes that always ask.

Example: docket setup sandbox classes

### setup notify

**Usage:** `docket setup notify`

Notification channels: Telegram in one step, desktop, ntfy, webhooks.

### setup notify list

**Usage:** `docket setup notify list`

List every channel with its dialect, state and content level.

Example: docket setup notify list

### setup notify show

**Usage:** `docket setup notify show`

Show one channel's effective document; telegram adds bindings and conversations.

Example: docket setup notify show telegram

### setup notify enable

**Usage:** `docket setup notify enable`

Turn a channel on; telegram also stores the token and binds every pod Lead.

Nothing is sent unless --test is passed.
Example: docket setup notify enable telegram --chat 42 --test

### setup notify disable

**Usage:** `docket setup notify disable`

Turn a channel off; stored keys and bindings are kept.

Example: docket setup notify disable ntfy

### setup notify add

**Usage:** `docket setup notify add`

Add a channel from a document.

Example: docket setup notify add ./my-channel.yaml

### setup notify remove

**Usage:** `docket setup notify remove`

Remove a channel document.

Example: docket setup notify remove my-webhook --yes

### setup notify export

**Usage:** `docket setup notify export`

Print or write one channel document.

Example: docket setup notify export telegram ./telegram.yaml

### setup notify privacy

**Usage:** `docket setup notify privacy`

Show or change how much a delivery carries; widening asks, narrowing never does.

Example: docket setup notify privacy telegram actions --yes

### setup notify test

**Usage:** `docket setup notify test`

Send one synthetic test event through one channel.

Example: docket setup notify test desktop

### setup notify bind

**Usage:** `docket setup notify bind`

Bind one pod member to a chat (the per-pod exception to enable).

The binding is the whole authorization boundary: anyone who can post in that chat can
approve, deny and delegate as this member once docket is serving Telegram.
Example: docket setup notify bind demo-lead --chat -100123

### setup notify unbind

**Usage:** `docket setup notify unbind`

Remove a member's chat binding.

Example: docket setup notify unbind demo-lead --yes

### setup notify flush

**Usage:** `docket setup notify flush`

Deliver new operator events to every enabled channel now.

Example: docket setup notify flush --dry-run

### setup export

**Usage:** `docket setup export`

Observability export: destinations, credentials, privacy and a preview.

### setup export list

**Usage:** `docket setup export list`

List every export destination with its state and privacy level.

Example: docket setup export list

### setup export show

**Usage:** `docket setup export show`

Show one exporter: document, state, health and what leaves this host.

Example: docket setup export show langfuse

### setup export enable

**Usage:** `docket setup export enable`

Enable an exporter: collect missing credentials, probe the endpoint, then write.

Example: docket setup export enable langfuse --privacy actions

### setup export disable

**Usage:** `docket setup export disable`

Turn an exporter off; stored keys are kept.

Example: docket setup export disable langfuse

### setup export test

**Usage:** `docket setup export test`

Probe an exporter's endpoint without changing anything.

Example: docket setup export test langfuse

### setup export add

**Usage:** `docket setup export add`

Add an exporter from a document.

Example: docket setup export add ./my-exporter.yaml

### setup export remove

**Usage:** `docket setup export remove`

Remove an exporter document.

Example: docket setup export remove my-exporter --yes

### setup export export

**Usage:** `docket setup export export`

Print or write one exporter document.

Example: docket setup export export langfuse ./langfuse.yaml

### setup export privacy

**Usage:** `docket setup export privacy`

Show or change what an exporter shares; widening asks, narrowing never does.

Example: docket setup export privacy langfuse conversation --yes

### setup export preview

**Usage:** `docket setup export preview`

Show what an exporter would send for a local session; no network call, no write.

Example: docket setup export preview langfuse --level actions

### setup mcp

**Usage:** `docket setup mcp`

External MCP tool servers: list, add and remove (stdio transport).

### setup mcp list

**Usage:** `docket setup mcp list`

List the configured MCP tool servers; env values are masked.

Example: docket setup mcp list

### setup mcp add

**Usage:** `docket setup mcp add`

Configure a server; everything after -- is its launch command, verbatim.

A role that denies write gets tools only from a server declared --kind read.
Example: docket setup mcp add playwright -- npx -y @playwright/mcp@latest

### setup mcp remove

**Usage:** `docket setup mcp remove`

Remove a configured server.

Example: docket setup mcp remove playwright


---

### start

**Usage:** `docket start`

Start the background service: the local HTTP API, sweeps, and what you turn on.

Binds 127.0.0.1 only. Always runs the sweeps and /status.json /metrics /health.
--dispatch also runs every pod's queue (spends budget), --telegram polls the
Telegram bot, --mcp serves docket's tools over stdio and runs nothing else.
Stop it with `docket stop`.

Example: docket start --dispatch


---

### stop

**Usage:** `docket stop`

Stop the background service: let sweeps finish, then abandon them if they hang.

Sends the service one signal and waits up to --wait seconds for it to exit; a
second signal abandons any sweep still running.

Example: docket stop


---

### exec

**Usage:** `docket exec`

Run one agent for one task in a workspace you own, for programs.

Streams newline-delimited JSON events on stdout and ends with exactly one
versioned result line; every log goes to stderr. Needs DOCKET_HOME set to a
caller-owned directory and DOCKET_LLM_BASE_URL set. A tool call that would need
a human is denied at once. SIGTERM cancels the run. Exit 0 the result is ok,
1 it failed, was blocked or cancelled, 2 refused before any run started.

Example: docket exec --workspace . --task "fix the failing test" --model local/qwen


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
| 0 | Success (includes `task approve`/`task deny` re-resolving a token to the verdict it already has) |
| 1 | Error (generic; also used by `task approve`/`task deny` on an unknown token or one being flipped to the opposite verdict, and `docket init`'s missing-dependency check) |
| 2 | Usage/refusal error: Typer's own automatic response to a missing or invalid argument, `docket exec`'s `--workspace`/`--task`/preflight refusal, or an unrecognized flag or command (an unknown command word names the live commands it could mean) |

No command emits any other exit code today.


---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCKET_HOME` | Root of everything docket owns — the only state root; no external daemon directory exists | `~/.docket` |
| `TRACES_DIR` | Root of per-session trace JSONL files (`docket task trace`) | `$DOCKET_HOME/traces` |
| `POLICIES_DIR` | Root of installed/edited policy JSON (`docket pod policies`, `docket setup sandbox`) | `$DOCKET_HOME/policies` |
| `PLUGINS_DIR` | Root of operator-applied predicate plugins (`docket pod policies --plugins`, a policy's `when.plugin`) | `$DOCKET_HOME/plugins` |
| `SKILLS_DIR` | The operator's own Agent Skills, the outermost of the three scopes `core.skills.discover_skills` reads | `$DOCKET_HOME/skills` |
| `APPROVALS_DIR` | Where `docket task approve`/`deny`'s approval-token store lives | `$DOCKET_HOME/approvals` |
| `CORRECTIONS_DIR` | Per-pod append-only ledger of operator decisions and rejections (`docket task show`) | `$DOCKET_HOME/corrections` |
| `SCHEDULE_FILE` | The persisted pod schedules (`docket pod set schedule`) | `$DOCKET_HOME/docket-schedules.json` |
| `RUNS_FILE` | The persisted dispatch-run registry — one record per `dispatch_pod` invocation | `$DOCKET_HOME/docket-runs.json` |
| `SESSIONS_DIR` | Root of durable per-session turn history (`core/session.py`) | `$DOCKET_HOME/sessions` |
| `MCP_SERVERS_FILE` | Registry of configured external MCP tool servers (`docket setup mcp`) | `$DOCKET_HOME/docket-mcp-servers.json` |
| `PROVIDERS_FILE` | Global provider catalog scope (`docket setup provider add`, `core/provider.py`) | `$DOCKET_HOME/docket-providers.json` |
| `EXPORTERS_FILE` | Global exporter catalog scope (`core/exporter.py`) | `$DOCKET_HOME/docket-exporters.json` |
| `EXPORTERS_HEALTH_FILE` | Per-exporter delivery counters and last-error state (`core/exporter.py::read_health`) | `$DOCKET_HOME/exporters-health.json` |
| `CHANNELS_FILE` | Global channel catalog scope (`core/channel.py`) | `$DOCKET_HOME/docket-channels.json` |
| `NOTIFY_STATE_FILE` | `core/notify.py::flush`'s dedupe snapshot, so two flushes over the same state deliver each event once | `$DOCKET_HOME/notify-state.json` |
| `CHANNELS_HEALTH_FILE` | Per-channel delivery counters and last-error state (`core/notify.py::flush`) | `$DOCKET_HOME/channels-health.json` |
| `FLEET_FILE` | Agent registration, channel bindings, gate/isolation flags, org default model | `$DOCKET_HOME/fleet.json` |
| `AUDIT_LOG_MAX_BYTES` | Audit-log rotation threshold (`docket log`) | `5242880` (5 MiB) |
| `SESSION_TIMEOUT` | Age past which an expired approval is denied (fail-closed) | `3600` |
| `APPROVAL_TIMEOUT` | The async approval-gate window (`core/dispatch.py`'s `require_approval`) — a task waits `waiting_approval`; no process or turn is blocked on it | `900` |
| `TOOL_APPROVAL_TIMEOUT` | The in-turn approval wait (`core/approval.py`'s `wait_for_approval`) — blocks a live tool call, so it is far shorter than `APPROVAL_TIMEOUT` | `120` |
| `TOOL_APPROVAL_POLL_INTERVAL_S` | How often the in-turn approval wait re-checks the record while blocked | `2` |
| `CLAIM_STALE_TIMEOUT` | A pod task claimed longer than this without finishing is presumed crashed and failed by the dispatch sweep | `1800` |
| `METRICS_WINDOW` | Rolling terminal-session count for `docket status` | `50` |
| `RUNAWAY_TURNS_THRESHOLD` | Past this many turns, `docket setup` flags a session as runaway | `200` |
| `RUNAWAY_COST_THRESHOLD` | Past this estimated USD, `docket setup` flags a session as runaway | `20` |
| `DOCKET_KEY_MAX_AGE_DAYS` | `docket setup --fix`'s key-hygiene report flags a stored secret STALE past this age — a rotation nudge, never an expiry | `90` |
| `TRACE_RETENTION_DAYS` | How long a terminated trace file survives before `docket task prune --traces` deletes it | `30` |
| `EXPORT_QUEUE_MAX` | Bound on the in-memory span queue the background exporter sender drains | `1000` |
| `EXPORT_FLUSH_TIMEOUT_S` | Per-flush wall-clock bound for the background exporter sender | `5.0` |
| `TEMPLATE_VERSION` | Workspace-prompt schema version; `docket setup --fix` flags older agents for rebuild past a bump | `4` |
| `CONTEXT_BYTES_PER_TOKEN` | Bytes-per-token estimator behind the static-context guards behind the prompt budget | `4` |
| `CONTEXT_TOKEN_BUDGET` | Soft cap on the static per-turn context (SOUL+AGENTS+TOOLS+HEARTBEAT+MEMORY.md); prompt composition truncates past it | `6000` |
| `DISTILL_TIMEOUT_S` | Wall-clock bound on the one driver-backed distillation turn `docket pod reset` runs | `120` |
| `DISTILL_MAX_INPUT_BYTES` | How much daily-log content goes into a distillation turn's prompt | `49152` (48 KiB) |
| `DISPATCH_RETRIES_DEFAULT` | Retry attempts after the first try for a retryable dispatch-hop failure (timeout/`daemon_error` only), for any role with no per-role override | `2` |
| `DISPATCH_RETRIES_LEAD`, `DISPATCH_RETRIES_IMPLEMENTER`, `DISPATCH_RETRIES_REVIEWER`, `DISPATCH_RETRIES_TESTER` | Per-role override of `DISPATCH_RETRIES_DEFAULT` | same as `DISPATCH_RETRIES_DEFAULT` |
| `DISPATCH_RETRY_BACKOFF_S` | Linear backoff base between retries — attempt N waits N times this many seconds | `2` |
| `DISPATCH_RETRY_MAX_WAIT_S` | Ceiling on a retry's sleep, whichever of the linear backoff or the endpoint's own `Retry-After` asked for longer | `60` |
| `DISPATCH_TURN_TIMEOUT_S` | `docket start`-only ceiling on a dispatch hop's turn timeout, overriding a pod's own Lead-meta value for serve-triggered dispatches | unset (no serve-wide override) |
| `DISPATCH_SWEEP_WORKERS` | `docket start --dispatch`: how many pods one sweep tick runs at once (`1` is serial) | `4` |
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
| `NO_COLOR` | Any value switches output to plain mode (no colour, ASCII symbols) | unset |
| `DOCKET_POD` | Pod a command acts on when `--pod` is not given | unset (the pod whose codebase contains the current directory) |
| `DOCKET_NO_HINTS` | Set to `1` to silence the closing `Next:` line | unset |
| `DOCKET_POD` | Pod that commands taking `--pod` act on when the flag is omitted | unset |
| `DOCKET_NO_EXPORT` | Set to `1` to disable every export queue/flush action | unset (export on) |
| `DOCKET_SANDBOX_IMAGE` | Image for the Docker exec-jail (`docket setup sandbox on`) | `alpine:3.20` |
| `DOCKET_SANDBOX_BACKEND` | Force or disable the sandbox backend (`docker`/`bwrap`/`none`) regardless of what is actually installed | auto-detected (docker > bwrap > none) |
| `SHELL` | Login shell name; `docket setup` uses it to name the completion command it offers | unset (bash assumed) |
| `DOCKET_SERVE_TOKEN` | Fix `docket start`'s bearer token instead of generating one per run | unset (random) |
| `DOCKET_LLM_BASE_URL` | Process-wide override that points every model at one endpoint (local dev, tests without stored config) | unset |
| `DOCKET_LLM_API_KEY` | Process-wide API key override, paired with `DOCKET_LLM_BASE_URL` | unset |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `OPENROUTER_API_KEY`, `AI_GATEWAY_API_KEY`, `VERCEL_OIDC_TOKEN`, `GROQ_API_KEY`, `MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `CEREBRAS_API_KEY`, `TOGETHER_API_KEY` | Per-provider API key, named by a built-in provider document's `auth.credentials` (`core/provider.py`'s catalog), checked when neither `DOCKET_LLM_API_KEY` nor a catalog-resolved credential is already present; also checked against docket's own secret store (`docket setup provider add`). A provider absent from the catalog falls back to `<PROVIDER>_API_KEY` | unset |
| `DOCKET_CLI_ROOT` | Repo root override used by the `bin/docket` launcher to select which project to `uv run` against | package/launcher location |
| `DOCKET_PYTHON` | Explicit interpreter for `bin/docket` to exec (e.g. a Homebrew venv) | unset (auto-resolved) |

There is **no** environment kill switch for the audit log — a prior `DOCKET_NO_AUDIT` escape hatch was removed because it let anyone silently disable docket's only tamper record; audit writes are unconditional and best-effort (a write failure never raises, but it also can't be turned off).


---

## Tips and Tricks

### Batch Operations

Use bash loops for batch operations:

```bash
# Reset every member of a pod (each distills its memory first)
for id in $(docket pod show --json | jq -r '.members[].id'); do docket pod reset "$id" --yes; done

# Cheaper models fleet-wide: change the policy once — every
# agent updates automatically
docket setup model preset openrouter-free
```

### Usage Monitoring

Track daily usage:

```bash
# Add to crontab
0 23 * * * docket status --all --json >> ~/docket-status-$(date +%Y-%m).log
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
docket status --all --json > ~/backups/fleet-$(date +%s).json
```


---

## Next Steps

- [Agent Teams (Pods)](AGENT-TEAMS.md)
- [Workflow Guide](WORKFLOW-GUIDE.md)
- [Main README](../README.md)
