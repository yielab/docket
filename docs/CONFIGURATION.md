# Configuring docket: the files it creates and how to use them

This guide maps every file docket writes, on the machine and per project, to what it controls,
how to change it, and what reads it while an agent is actually running. Its focus is the question
the other guides leave open: **how do I customize my agents, the orchestration between them,
what they are allowed to do, and what of it leaves this machine?**

Everything here was checked against a real install (`docket init --pod full` under a throwaway
`HOME`, then a real dispatch against a local model) and against the code on the live turn path.
When a file is written but nothing on the live path reads it, this guide says so. Several files
look like settings and are not.

> Related: [Agent Teams](AGENT-TEAMS.md) explains the pod model, [Command Reference](commands.md)
> lists every flag, and its [Environment Variables](commands.md#environment-variables) table lists
> every tunable. This guide links to both instead of repeating them.

---

## Contents

1. [What an install creates](#1-what-an-install-creates)
2. [How the files reach a running agent](#2-how-the-files-reach-a-running-agent)
3. [Customizing: recipes by use case](#3-customizing-recipes-by-use-case)
4. [File reference](#4-file-reference)
5. [Sharp edges](#5-sharp-edges)

---

## 1. What an install creates

`docket init` in a project directory does two things. The first time it runs on a machine, it
creates the **workstation foundation** (global state, baseline policies). Every
time it runs, it creates one **pod** for the current project. There is no separate setup step.

`docket init` stops before creating the pod unless a model endpoint is ready. On a fresh machine,
register one first:

```bash
docket setup provider add local http://127.0.0.1:8081/v1 --model qwen \
  --ctx 16384 --max-tokens 4096
docket setup model preset local          # every role now resolves to local/qwen
docket init --pod full              # Lead + Implementer + Reviewer + Tester
```

The result, with the moment each file appears. Files are `0600` and directories `0700` unless
noted.

```text
~/.docket/                              DOCKET_HOME: every piece of docket state lives here
├── fleet.json                          init         agent registry, bindings, flags
├── docket-providers.json               setup provider your kind: provider documents (built-ins ship in the wheel)
├── docket-models.json                  init/setup model  role -> model policy
├── port-allocations.json               first pod    per-pod port range bases
├── audit.log                           first change hash-chained record of every mutation
├── policies/*.yaml                     init         6 baseline guardrail policies (JSON also loads)
├── docket-roles.json                   you          your custom role archetypes (global scope)
├── docket-mcp-servers.json             setup mcp   external MCP tool servers
├── docket-exporters.json               setup export your kind: exporter overrides (built-ins ship in the wheel, all off)
├── exporters-health.json               first export delivery counters per enabled exporter
├── docket-channels.json                setup notify your kind: channel overrides (built-ins ship in the wheel, only console on)
├── channels-health.json                first notify delivery counters per enabled channel
├── notify-state.json                   first notify the dedupe snapshot `docket setup notify flush` diffs against
├── inbox-cursor.json                   inbox        the last `docket inbox` call's cursor (skipped by --peek/--since)
├── docket-schedules.json               pod set      dispatch schedules (`docket pod set schedule`)
├── secrets.json, secrets.meta.json     setup provider stored API keys + timestamps
├── docket-runs.json                    dispatch     one record per dispatch invocation
├── docket-conversations.json           setup notify Telegram conversation registry
├── sessions/<session-key>/session.json dispatch     durable per-session turn history
├── traces/<pod>/<session>.jsonl        dispatch     observable events per session
├── approvals/<id>.json                 gated call   pending/granted/denied approvals
├── consult-parked/<q-id>.json         consult      a parked question, until dispatch reads it
└── workspaces/
    ├── projects/<pod>-<role>/          init/pod add one private workspace per pod member
    │   ├── .docket-meta.json           the agent's facts and per-pod settings
    │   ├── SOUL.md                     identity and role instructions
    │   ├── AGENTS.md                   red lines (and a startup section, see §2)
    │   ├── TOOLS.md                    implementers only: ports, scratch dir, verify gate
    │   ├── HEARTBEAT.md                task ledger
    │   ├── MEMORY.md                   durable project facts
    │   ├── WORKFLOW_AUTO.md            startup contract (versioned, regenerated)
    │   ├── memory/YYYY-MM-DD.md        daily logs
    │   ├── TASK_LIST.json              Lead only, after the first `task add`: the pod's queue
    │   └── tasks/<taskId>/             implementers in a git repo: one git worktree per task
    └── pods/<pod>/.scratch/            first pod   the pod's isolated scratch directory
```

**Inside your repository**, docket writes almost nothing, but not nothing. `docket pod add` and `init`
create no worktree; each task of a pod whose codebase is a git repository gets one when it is
claimed:

- a branch `docket/<pod>/<taskId>`, created in your repo from its HEAD at that moment;
- an entry under `<repo>/.git/worktrees/`;
- a checkout of that branch at `~/.docket/workspaces/projects/<pod>-implementer/tasks/<taskId>/`,
  recorded on the task as `worktree` (`dir`, `branch`, `baseCommit`).

The Implementer edits that worktree, never your checked-out branch. Dispatch never commits: unless
the agent ran `git commit` itself, its changes stay **uncommitted** in the worktree, so you see them with
`git -C ~/.docket/workspaces/projects/<pod>-implementer/tasks/<taskId> diff`, then commit on its
branch and merge it like any other. Your verify command's by-products (`__pycache__/`, caches) land
there too. `docket pod delete` removes all task worktrees with the member
and deletes the merged task branches (an unmerged branch is kept, with the removal command printed).
An Implementer marked `inPlace` works in the codebase itself and gets no task worktree. Reviewer and Tester run with the codebase root as
their working directory, so a test run can leave caches in your checkout.

To try any of this without touching your real setup, point `HOME` (or `DOCKET_HOME`) at a scratch
directory. Every docket path resolves under it.

---

## 2. How the files reach a running agent

This is the model you need to customize anything. Every live turn, whether a dispatch hop, a
`docket start` sweep or a Telegram `/delegate`, rebuilds the agent's **system prompt from disk**.
Nothing is cached, so an edit takes effect on the next turn with nothing to restart.

The system prompt is, in this order:

1. **`SOUL.md`**. An oversized
   `SOUL.md` is visibly middle-truncated rather than starving the sections below.
2. **A fixed runtime contract** written by docket (not a file). It lists the directories the
   agent's tools may touch and tells it that its private workspace files are read-only.
3. **Workspace state**, in this order: `HEARTBEAT.md`, `AGENTS.md`, `TOOLS.md`, `MEMORY.md`.
   - `HEARTBEAT.md` is included from its first `##` heading on, with HTML comments removed.
   - `AGENTS.md` is included without its `## Session Startup` section.
   - `TOOLS.md` and `MEMORY.md` are included verbatim.

Section 3 shares one budget, resolved per turn from the model actually being called: half the
registered context window (minus the output reserve and a labelled tool-schema allowance),
floored at `CONTEXT_TOKEN_BUDGET` (default 6000) × `CONTEXT_BYTES_PER_TOKEN` (default 4) ≈ 24 KB.
A 16k local endpoint resolves below that floor, so it gets exactly the floor; a 200k hosted model
fits every section in full. Setting `CONTEXT_TOKEN_BUDGET` explicitly overrides both. The
`prompt_composed` trace event names the resolved `budgetTokens` and its `budgetSource`
(`env`/`window`/`default`). An oversized `SOUL.md` is capped (middle-truncated with a visible
marker) so it cannot crowd out the contract or the state sections; a state file that does not fit
is truncated or omitted **with a one-line marker in the prompt naming it**, and every composition
emits a `prompt_composed` trace event listing each section as full, truncated or omitted
(`docket task trace`). Nothing is dropped silently. `docket setup --fix` warns when the static
context passes the budget.

**Not sent to the model**, despite what the file names suggest:

| File | What it is actually for |
|---|---|
| `WORKFLOW_AUTO.md` | The startup contract for an agent reading its workspace by hand. A live turn replaces it with the runtime contract above. Editing it changes nothing a docket turn sees. |
| `memory/YYYY-MM-DD.md` | Daily logs. Not in the prompt. `docket pod reset <member>` distills and moves its content into `MEMORY.md`, which is. |
| `workflows/*.yaml` in a workspace | Nothing reads it. Pipelines are passed with `--pipeline` or bound with `docket pod set pipeline` (see §3.5). |

### Who decides what: the ownership map

Six layers make up the orchestration, and each answers exactly one question. When you are unsure
where a change belongs, find the question first. **Scope** is which of the three provenance
levels a resolved value can come from — `built-in` (shipped, unwritable), `global`
(`~/.docket/`, every pod), or `pod` (this pod's own `config/` directory, nearest-wins above
global) — the same three `docket pod show <member> --json` labels per value.

| Question | Layer | Scope | Lives in | Change it with |
|---|---|---|---|---|
| What needs doing? | **Task** | pod | the Lead's `TASK_LIST.json` | `docket task add` |
| Which team shape does a new pod get? | **Blueprint** | pod (creation-time only) | Lead meta `blueprint` | `docket init --blueprint` |
| Who works a task, in what order, behind which quality gates, with how much rework? | **Pipeline** | global \| pod | the blueprint's built-in default; a YAML file for a custom route, run once or bound as the pod default | `docket pod validate`, `docket pod plan`, `docket run`, `docket pod set pipeline` |
| How does each *kind* of agent behave, and which tools is it structurally denied? | **Role archetype** | built-in \| global \| pod | built-ins + `~/.docket/docket-roles.json` + this pod's own `config/roles.json` | `docket pod roles [--pod <p>]`, `docket pod add <role>` |
| What does *this* agent know about *this* project? | **Workspace instructions** | pod (per-agent) | `SOUL.md`, `TOOLS.md`, `MEMORY.md`; operator-owned `INSTRUCTIONS.md` (never regenerated); the codebase root's `AGENTS.md` by default, or the files `projectInstructions` names | edit `INSTRUCTIONS.md` directly; `docket pod set projectInstructions CONTRIBUTING.md` |
| What is forbidden or human-gated, across everything? | **Policies + command classifier** | global \| pod | `~/.docket/policies/*.yaml|json` + this pod's own `config/policies/*.yaml|json` (+ fixed `SAFE_BINS`) | `docket pod policies [--pod <p>]` |
| What budget, timeouts, approval posture, extra allowed commands, tool/MCP-server denials and verify gate bound this pod? | **Pod settings** | pod | the Lead's / member's `.docket-meta.json` | `docket pod show`, `pod set`, `pod unset` (`budgetUsd`, `maxReworkCycles`, `turnTimeoutS`, `verifyTimeoutS`, `approvalMode`, `approvalExpiryHours`, `inputExpiryHours`, `requireVerify`, `maxConsultationsPerTask`, `network`, `allowCommands`, `pipeline`, `schedule`, `projectInstructions`, `mcpServers`, `deniedTools`); `pod set verify "<cmd>" --member <id>` |

**A pod's own overlay lives at `~/.docket/workspaces/pods/<pod>/config/`** (`docket.config.pod_config_dir(project)`) — `roles.json` (same shape as the global `docket-roles.json`) and `policies/*.yaml|json` (same shape as the global policy store), each resolving *above* the global layer for that pod alone, never shared with any other pod. `docket setup` flags a malformed entry in either file, naming the pod.

Two boundaries worth stating because they are easy to get backwards:

- **The pipeline is the route and its controls, never the instructions.** A step says *who* runs
  and *how the output is judged* (mechanical exit code, verdict marker, human approval). What the
  agent is told comes from its role template and workspace files (§2), plus the task text.
- **Every pod always has a pipeline.** `docket run` runs the blueprint's default with
  no setup. For a *custom* route: `docket pod validate` checks a file, `docket pod plan --pipeline` shows it
  against the real roster without spending tokens, `docket run --pipeline` executes it once by hand, and
  `docket pod set pipeline <file>` **binds it as the pod's default for every trigger**
  (dispatch, the `docket start` sweep, schedules, webhooks, MCP). Binding validates and plans the file first,
  stores a docket-owned copy with its hash, and a later hash mismatch refuses dispatch loudly.
  `docket pod plan` prints a `Source:` line naming which route would run.

**The task itself** arrives as the turn's user message, built by dispatch: the task description,
an instruction line, and the previous hops' output trimmed to the role's `tokenBudget`. The
instruction is, in order of precedence: the pipeline step's own `instructions` (which may
interpolate declared `${variables}`, fed by `docket run --var key=value` or the webhook
body), the built-in role's hardcoded line, or a custom role's `hopInstruction` (declared, or
generated from its `gateContract` so a verdict role always knows its marker). Workspace files are
not re-read into it.

**Private means read-only for the agent.** The generated `SOUL.md`, `AGENTS.md` and
`WORKFLOW_AUTO.md` tell an agent to write its plan into `HEARTBEAT.md` and its day into `memory/`.
In a docket turn it cannot. Its tools are confined to the codebase (or worktree, or workdir), and
the runtime contract forbids touching private files. Durability comes from docket instead: session
history in `sessions/`, and a docket-owned region in the **Lead's** `HEARTBEAT.md` that dispatch
rewrites at every claim, hop and finish. That prose exists for an agent operating the workspace
outside a docket turn. **You** are the one who edits these files.

---

## 3. Customizing: recipes by use case

### 3.1 Choose which model each agent runs on

Three layers, from broad to narrow:

| Goal | Command | File written |
|---|---|---|
| Register an endpoint (OpenAI-compatible) | `docket setup provider add <file.yaml>` (a `kind: provider` document), or the shortcut `docket setup provider add <name> <base-url> [--model ID] [--ctx N] [--max-tokens N] [--credential NAME]` | `docket-providers.json` → `providers` |
| List every provider | `docket setup provider list` | — (read-only) |
| Show one provider's resolved entry and scope | `docket setup provider show <name> [--json]` | — (read-only) |
| Remove a global override | `docket setup provider remove <name>` | `docket-providers.json` → `providers` |
| Print or write a provider as a document | `docket setup provider export <name> [<file>]` | the given file, or stdout |
| Point every role at one provider | `docket setup model preset <anthropic\|openai\|google\|openrouter\|openrouter-free\|ai-gateway\|local>` | `docket-models.json` |
| Change one role's model | `docket setup model set <role> <provider/model>` (or `set default …`) | `docket-models.json` → `roles` |
| Store the API key | `docket setup provider add openrouter --credential <key>` (stored by name, never in a workspace) | `secrets.json` |

The model an agent actually calls is the `model` in its own `.docket-meta.json`. Policy changes
rewrite that field on every agent whose `modelSource` is `policy`, immediately. Pins are never
touched.

`--ctx` and `--max-tokens` matter: they are the limits docket checks requests against. Against a
small-context local server, also export `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` (the 30000 default
suits a large hosted model, and two full tool results overflow a 16k window).

Credential lookup order, per name in the provider document's `auth.credentials`:
`DOCKET_LLM_API_KEY`, then that name as an environment variable, then the same name in
`secrets.json`. A document never holds a credential value — only names. `DOCKET_LLM_BASE_URL`
overrides every endpoint at once, which is handy for tests. `docket pod show <member>
--json` reports which provider, scope and credential source an agent actually resolved to
(`model-profiles.spec.md`, "Provider catalog").

### 3.2 Change what an agent is told

Edit the agent's workspace files directly, under `~/.docket/workspaces/projects/<agent-id>/`.

| To change… | Edit | Notes |
|---|---|---|
| Role instructions, scope, tone, house rules | `SOUL.md` | Always sent in full. The highest-leverage file. |
| Project commands, conventions, where things are | `TOOLS.md` (create it for non-implementers) | Sent verbatim. The Implementer's is generated. See the caution below. |
| Durable facts about the product | `MEMORY.md` | Sent last, so it is the first thing dropped when the budget is tight. |
| Red lines shared by a role | `AGENTS.md` | Everything except `## Session Startup` is sent. |
| What the repository tells every coding agent | `AGENTS.md` at the codebase root | Read by default when `projectInstructions` is unset, screened as untrusted (§3.12). |

**What overwrites your edits:**

- `docket pod add <role>` writes a *new* member's `SOUL.md`, `AGENTS.md`, `HEARTBEAT.md` and
  (for an Implementer) `TOOLS.md` from its role template. Existing members are not touched.
- `docket pod set verify` regenerates the Implementer's `TOOLS.md`. Put your own
  Implementer notes in `SOUL.md` or `MEMORY.md` instead, or re-add them after changing the verify
  command.
- `docket pod reset <member>` resets `HEARTBEAT.md` and clears `MEMORY.md` (after distilling
  into it) and rebuilds the member's workspace.
- `docket setup` rewrites `WORKFLOW_AUTO.md` whenever its contract version is stale. That costs
  nothing, since the file is not sent to the model.

To change the instructions of **every future** member of a role, define a custom role (§3.4).
Existing members keep the `SOUL.md` they were provisioned with; there is no re-render command, so
edit those by hand.

### 3.3 Configure a pod: verify gate, budget, rework, timeouts

Pod-wide settings live in the **Lead's** `.docket-meta.json`. The verify command lives on the
member it gates.

| Setting | Key and file | How to set it | Effect |
|---|---|---|---|
| Verify gate | `verifyCmd` in the Implementer's meta | `docket pod set verify "pytest -q" --member <p>-implementer`, or `--verify` on `docket init`/`pod add` | Runs after every Implementer hop in its worktree. A non-zero exit **fails** the task (`verification_failed`). |
| Budget cap (USD, estimated) | `budgetUsd` in the Lead's meta | `docket pod set budgetUsd 5` (`0` = none) | Checked before each hop. Over the cap, the task is blocked and the Lead paused until `docket run --resume`. The figure is an estimate, not your bill. |
| Rework cycles | `maxReworkCycles` in the Lead's meta | `docket pod set maxReworkCycles 2` | How many times a Reviewer `REQUEST-CHANGES` sends work back (default `1`, `0` = none). Ignored when you run a pipeline file, which carries its own `maxCycles`. |
| Hop timeout | `turnTimeoutS` in the Lead's meta | `docket pod set turnTimeoutS 900` | Per-hop wall clock (default 300 s). `--timeout` on `docket run` overrides it for one run. Under `docket start`, `DISPATCH_TURN_TIMEOUT_S` overrides it. |
| Verify timeout | `verifyTimeoutS` in the Lead's meta | `docket pod set verifyTimeoutS 300` | Same precedence, `DISPATCH_VERIFY_TIMEOUT_S` under `docket start`. |
| Retries | environment only | `DISPATCH_RETRIES_DEFAULT`, `DISPATCH_RETRIES_<ROLE>`, `DISPATCH_RETRY_BACKOFF_S` | Timeouts and transport errors only. A failed verify or a bad verdict is never retried. |
| Pod roster | members' workspaces | `docket pod add <role> [--count N]` / `docket pod remove <id>` | Dispatch only runs the roles the pod has. |

`docket pod set <key> <value>` validates before writing and is audited as
`pod.config`; `docket pod unset <key>` restores the default. A hand-edited value that fails validation is
not ignored: `pod show` and `docket run` both refuse, naming the key. Confirm with
`docket pod plan`, which prints the resolved rework budget and steps.

```json
{
  "role": "lead",
  "budgetUsd": "5",
  "maxReworkCycles": 2,
  "turnTimeoutS": 900,
  "verifyTimeoutS": 300
}
```

(These are the relevant keys only. Keep the rest of the file as docket wrote it.)

### 3.4 Define a custom role

Roles are data. A role archetype carries its `SOUL.md`/`AGENTS.md` templates, the model class it
resolves to, the tools it is denied, its gate contract and its context budget. Built-ins (`lead`,
`implementer`, `reviewer`, `tester`, plus `researcher`, `analyst`, `writer`, `critic`, `operator`,
`monitor`) cannot be edited, only shadowed by name. See all of them with `docket pod roles`, and
dump one as a starting point with `docket pod roles reviewer`.

```yaml
# security-reviewer.yaml — the short form; `docket pod roles reviewer` dumps the canonical
# form this normalizes to (role-archetypes.spec.md, "Wire format")
kind: role
name: security-reviewer
description: read-only security pass over the implementer's change
model: strong                        # cheap | strong -> resolved through docket-models.json
cannot: [write, edit, bash]          # the only enforcement field
verdict: [APPROVE, REQUEST-CHANGES]  # or verify: true | approval: <message> | nothing
instructions: security-reviewer.md   # default: <name>.md next to this file
```

```markdown
# security-reviewer.md
# SOUL.md — ${project} · ${role}

You are the **${role}** of the **${project}** pod (agent id `${memberId}`).
Codebase: ${codebaseOrConfigured} (stack: ${stack}).

## Role — Security reviewer
- Review the change for injection, secrets in code, unsafe deserialization and authz gaps.
- You are read-only. Start exactly one line with `APPROVE` or `REQUEST-CHANGES`.

## AGENTS

# AGENTS.md — ${project} · ${role}

## Red Lines
- Stay within the `${project}` pod. No cross-project access.
```

```bash
docket pod validate security-reviewer.yaml    # checks fields and dry-renders both templates
docket pod apply security-reviewer.yaml         # -> ~/.docket/docket-roles.json
docket pod add security-reviewer          # provisions myapp-security-reviewer
```

Template variables: `project`, `role`, `memberId`, `sessionKey`, `objective`, `codebase`,
`codebaseOrConfigured`, `codebaseOrIt`, `stack`, `workDir`, `requiredStartupFile`. An unknown
`${var}` fails `validate`.


What is read **when**:

- The instructions file (`soulTemplate`/`agentsTemplate` in the canonical form) and `model` are
  used **once**, when a member is provisioned. Changing the overlay later does not touch
  existing members.
- `cannot`, `tokenBudget` and the gate (`verdict`/`verify`/`approval`) are read **live** on every
  hop, from the merged registry.
- A custom role gets **no built-in per-hop instruction line**, so everything it must do belongs in
  its instructions file.
- The default pipeline only runs `lead → implementer → reviewer → tester`. A custom role joins a
  dispatch **only through a pipeline file** (§3.5).

### 3.5 Change the orchestration: pipelines and blueprints

**Blueprints** pick a pod's shape at creation: `docket init --blueprint
software|research|content|ops|agentic-product`. Only these five exist, and the choice is stored as
`blueprint` in the Lead's meta. Dispatch uses the blueprint's built-in pipeline.

**Pipeline files** declare your own hop order, gates and rework edges. This one runs the custom role
from §3.4, in the short form — `docket pod validate` normalizes it to the canonical form
`pipeline-format.spec.md` defines, which is what `plan`/`run` actually execute:

```yaml
# pipeline.yaml
kind: pipeline
name: build-then-security
description: Lead plans, Implementer builds (verify-gated), security reviewer vets with rework
steps:
  - plan: lead
  - build: implementer
    timeout: 900
    verify: true                        # -> gate: {type: mechanical} (member's own verifyCmd)
  - vet: security-reviewer
    verdict: [APPROVE, REQUEST-CHANGES] # first marker passes; the rest can trigger `on:`
    on: {REQUEST-CHANGES: {goto: build, max: 2}}
```

```bash
docket pod validate pipeline.yaml              # structure only, no pod needed
docket pod plan --pipeline pipeline.yaml       # resolves against the real roster, runs nothing
docket run --pipeline pipeline.yaml            # executes; same budget/gates/traces/runs as dispatch
```

Short form (unknown keys are rejected at every level; `pipeline-format.spec.md`, "Short form",
"Outcome routing", "Conditional steps and command steps" define the full mapping and canonical
form):

- **Top level:** `kind: pipeline`, `name` (required), `description`, `variables`, `steps`.
- **Each step:** one `<id>: <role-or-agent>` key, plus optional `timeout`, `retries`,
  `instructions`, and at most one of `verify`/`verdict`/`approval` (the gate) or `until`+`max`
  (a bounded mechanical self-retry).
- **Gate sugar:** `verify: true` (or a command string) for a mechanical gate; `verdict: [...]`
  for a verdict gate, first marker passing; `approval: "<message>"` for a human sign-off (the
  task waits in `waiting_approval`). No sugar key at all falls back to the role's own gate.
- **`on: {<label>: {goto: <step>, max: <n>}}`** routes any named outcome — not only a verdict's
  rework — to an earlier or later step, `fail`, or `stop`; a backward or self target requires
  `max`. **`when:`** (`changed`, `var`+`is`, `memberPresent`) skips a step; a **command step**
  (`- lint: {run: "ruff check ."}`) runs no agent turn at all, its exit code and last stdout
  line becoming its outcome.

One rule to plan around: a **bound** pipeline (`docket pod set pipeline`) is treated like a
caller-supplied `--pipeline` — the pod's `maxReworkCycles` setting never patches it, so the file's own
rework edges are what run. Only the blueprint/built-in default is patched by that setting.

### 3.6 Govern what agents may do

Every tool call passes one chokepoint that applies, in order:

1. The role's tool denials.
2. The argument-aware high-risk command classifier. It is always on and not configurable.
3. Your policies.

**Tool denials (per role).** The built-in tools are `read`, `glob`, `grep`, `fetch` (read kind),
`write` and `edit` (write kind), and `bash` (exec kind). MCP tools arrive as
`mcp__<server>__<tool>` and carry the kind their server declares (`docket setup mcp add --kind
read|write`, default `write`; `--tools a,b` limits which of its tools register).

- Denying a tool also denies every tool of its kind. That is how a read-only role gets **no** MCP
  tools from a server left at the default kind.
- Built-in denials:
  - `lead`, `reviewer`, `critic`, `monitor`: `write`, `edit`, `bash`.
  - `tester`: `write`, `edit`.
- Denials are per role, plus an optional per-pod list: `docket pod set deniedTools fetch`
  removes `fetch` from every role of that pod. To restrict one agent, give it a custom role.

**Shell commands (the curated allowlist).** A `bash` call runs unattended only when **every**
segment's binary (behind `;`, `&&`, `||` and pipes) is on a fixed list and no high-risk class
matches. Anything else asks a human.

- **On the list:** `ls cat head tail wc sort uniq cut tr nl grep egrep rg fd find file stat tree
  realpath dirname basename sed awk jq yq diff comm git node npm npx pnpm yarn python3 pip pip3 go
  cargo rustc make cmake date env printf which xargs tee less mkdir touch cp mv ln`, plus the
  side-effect-free builtins `cd pwd echo true false test [`. A redirected `echo` (`>`, `>>`, `&>`)
  still asks.
- **Not on the list,** so each one asks: `pytest`, `python`, `uv`, `bash`, `rm`, `export`,
  `source`.
- **Per-pod widening, scoped and audited:** `docket pod set allowCommands pytest,uv`
  adds exact binary basenames to the allowlist *for that pod's turns only*. Paths, shell
  metacharacters, opaque names (`eval`, `source`, …) and high-risk-class bins (`git`, `npm`) are
  rejected at write time; a redirected call still asks. Policies remain stricter-only: an `allow`
  policy cannot loosen the classifier.
- **In an unattended run today,** an ask does not block at all by default: `docket start --dispatch`'s
  sweep and a non-interactive `docket run` both resolve an unset `approvalMode` to
  `park` (§3.15) — the first ask records the call and parks the task `waiting_approval`
  immediately, ending the turn rather than eating a 120-second wait. An explicit `approvalMode:
  wait` (or an interactive foreground TTY, which still defaults to `wait`) keeps the older
  behavior: each ask blocks the turn for `TOOL_APPROVAL_TIMEOUT` (120 s) and is then denied, and
  after three denials in a row (`AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS`) the hop fails. For a
  pod that should never wait *or* park — a CI job with no one to grant it later — set
  `docket pod set approvalMode refuse`: a gated call then fails the hop immediately
  with `approval_unavailable`, naming the tool and policy.
- **This is not hypothetical.** Verifying this guide (pre-Phase-34, under the always-`wait`
  behavior), a real dispatch passed Lead, Implementer and Reviewer, then **failed the task** at
  the Tester on three asks. The asks were for `cd <worktree> && python3 …`, which W37-C1 has
  since allowed. `pytest` and `uv` still ask — and today, an unattended run hits `park` on the
  very first one rather than accumulating three denials.

Three ways to avoid it:

- **Allowlist the bins for that pod.** `docket pod set allowCommands pytest,uv`
  (see above) is the direct fix for exactly this failure.

- **Run checks through the verify gate.** Put them in the mechanical gate (`pod set verify`, or a
  pipeline `mechanical` gate). That command runs outside the tool classifier; only high-risk
  commands are refused there.
- **Use allowlisted forms.** Add this to `SOUL.md`: use `python3 -m pytest` rather than `pytest`
  or `uv run pytest`. `bash` already starts in the agent's first project root (the worktree, for an
  Implementer), so relative paths work.


**Policies** (`~/.docket/policies/*.yaml|yml|json`, relocatable with `POLICIES_DIR`). Every file
in the directory is loaded, and all of them are re-read on every call, so a new file is live
immediately. Write the short form (the shipped templates under `policies/` are examples);
`core.policy.normalize_policy` turns it into the canonical shape the evaluator actually reads —
see `security-gates.spec.md`, "Policy format v1" for that mapping and the canonical field names:

```yaml
kind: policy
name: no-curl
appliesTo: [implementer]
when: {matches: '\bcurl\b'}
then: ask
message: curl needs approval
```

| Field | Values |
|---|---|
| `appliesTo` | Role names as dispatch sees them (`implementer`, `reviewer`, … or a custom role), or `"*"`. |
| `on` | `input` (a task entering the queue; always evaluated as role `lead`), `toolCall` (tool name and arguments, the default), `output` (a hop's output). |
| `when` | `tool`, `path` (glob over a path/file argument), `matches` (regex over the rendered call, case-insensitive), `branch` (glob over the worktree branch), `anyOf` (OR over a list of the above); sibling keys AND. |
| `then` | `allow`, `warn` (record only), `redact`, `ask` (require approval), `block` (deny). There is no `deny` action; use `block`. |

How policies combine and what they ignore:

- **Precedence.** The most restrictive matching action wins: `block` > `ask` > `redact` >
  `warn` > `allow`.
- **A broken policy fails closed.** A file with bad JSON/YAML, an uncompilable regex or an
  unknown action evaluates as `block` within its readable scope (the hook and roles it declares,
  or every hook and role when the file itself will not parse), attributed to the file so you know
  what to fix; `docket setup` names it before a live turn does. After every edit, run
  `docket pod check` with a string the policy must match, for example
  `docket pod check "make deploy" --role implementer`, and confirm the expected result.
- **`redact`** uses docket's generic secret redactor, not your pattern.
- **Ignored fields.** `description` is documentation only.

**Extending with a predicate plugin.** The closed `when` vocabulary above covers most policies;
for a check no built-in predicate expresses, `~/.docket/plugins/` (operator scope) or a pod's own
`config/plugins/` (copied there by `docket pod apply`, never read live from a codebase) can
hold a small Python file registering a named predicate, referenced as `when: {plugin: <name>,
with: {...}}` — `then:` still decides the action. Every predicate plugin is loaded only from
operator/pod scope (never the agent's own workspace), audited by name and file hash, and a
plugin that raises, times out, or returns a non-`bool` fails **closed** (`deny`), never open.
`docket pod policies --plugins` shows each one's name, scope, file and hash. See
[ADR 0010](adr/0010-config-format-v1-and-extension-points.md) §4 for the trust boundary this is
built around.

**Approvals.** A `require_approval` hit, or a high-risk command such as `git push origin main`,
creates `approvals/<id>.json`.

- **Answering.** Answer it with `docket task approve <task-id>`/`docket task deny <task-id>`,
  `POST /approvals/<token>` under `docket start`, MCP, or Telegram `/approve`. Every channel is
  audited.
- **Expiry.** Unanswered requests are denied: after `TOOL_APPROVAL_TIMEOUT` (120 s) when a live
  tool call is waiting, after `APPROVAL_TIMEOUT` (900 s) at a pipeline approval gate.
- **Non-interactive runs.** `docket exec` never waits. It returns `approval_unavailable` instead.

**Network.** `fetch` refuses every host until you allow it:
`FETCH_ALLOWED_DOMAINS=docs.python.org,api.github.com`. That makes `fetch` the *inspectable*
path; by default it is not the only one, since `bash` can still reach the network through
allowlisted interpreters. `docket setup sandbox network none` (or a pod's `network` setting) cuts the
jail's network, leaving `fetch` as the only path.

**Isolation (opt-in).** Off by default: tools run on the host. `docket setup sandbox on` jails
`bash` and stdio MCP servers in bwrap (Linux) or Docker (Linux or macOS), and refuses to record
on when neither is usable; once on, a turn is refused rather than run unjailed if the backend
disappears. The Docker image is `DOCKET_SANDBOX_IMAGE`. The choice is `isolationMode` in
`fleet.json`; `networkMode` (`docket setup sandbox network`) is the other `security` flag the live path
enforces. Requirements and coverage:
[SECURITY-SIMPLE.md](SECURITY-SIMPLE.md#workspace-isolation-opt-in-the-sandbox-for-the-agents-shell).

### 3.7 Give agents external tools (MCP)

```bash
docket setup mcp add github --env GITHUB_TOKEN=... --timeout 20 -- npx -y @modelcontextprotocol/server-github
docket setup mcp list
```

The command writes `docket-mcp-servers.json`. Its tools appear in a turn as
`mcp__github__<tool>`, gated like built-ins.

- **Declare the kind.** A server is `--kind write` unless you say `--kind read`; nothing can
  prove a remote tool is read-only, so the declaration is your audited assertion. A role that
  denies `write`/`edit`/`bash` (§3.6) gets MCP tools only from a server declared `read`.
  `--tools a,b` limits which of a server's tools register at all.
- **Servers are per install; a pod picks its own.** `docket pod set mcpServers
  github,fs` limits that pod to those servers (`unset` restores every configured one); a name
  absent from the catalog refuses dispatch loudly. `docket pod set deniedTools fetch`
  removes a tool from every role of that pod.
- **Spawn cost.** Each selected server is spawned once per turn, about 0.6 s measured.
- **Plaintext env.** `--env` values are stored in plaintext; they are masked only in `list`.

### 3.8 Run unattended

- **Continuous sweep.** `docket start --dispatch` drains every pod's queue. Add `--telegram` for
  the approval channel. A gated tool call an unattended hop hits doesn't block the sweep: it
  resolves to `approvalMode: park` by default (an explicit stored value always wins) and moves on
  — see §3.15 for parking, the derived inbox, and how a human answers.
- **Schedules.** `docket pod set schedule "<spec>"` validates and writes one
  (`unset schedule` removes it); an invalid spec is refused at `set`, and the `docket start` sweep logs a
  line for any hand-edited spec it has to skip. Schedules fire
  only while `docket start --dispatch` runs:

  ```json
  {"schedules": {"myapp": "@every 30m", "otherapp": "09:00", "third": "*/15 9-17 * * 1-5"}}
  ```

  - **Formats.** `@every Ns|m|h`, a daily `HH:MM` in **UTC**, or a numeric 5-field cron in UTC.
  - **Skips are named.** An entry docket cannot parse never fires; the `docket start` sweep logs a line
    for it and `docket setup` reports it.
  - **Don't add other keys.** `docket start` rewrites the file with `lastRun` and drops any other
    top-level key.
- **Webhooks.** Use `POST /dispatch/<project>` with the `docket start` bearer token. Set
  `DOCKET_SERVE_TOKEN` to make that token stable.
- **Telegram.** `docket setup notify bind <p>-lead` binds a chat. It writes `fleet.json` `bindings` and
  `docket-conversations.json`.

### 3.9 Turn-loop limits

The per-turn stop conditions are all environment variables:

- `AGENT_LOOP_MAX_ITERATIONS`
- `AGENT_LOOP_MAX_TOOL_CALLS`
- `AGENT_LOOP_TOKEN_BUDGET`
- `AGENT_LOOP_WALL_CLOCK_TIMEOUT_S`
- `AGENT_LOOP_REQUEST_TIMEOUT_S`
- `AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS`

They apply process-wide, to every agent. There is no per-role or per-pod value. See the
[Environment Variables](commands.md#environment-variables) table for defaults. For
`docket start`, set them in its unit file or shell.

---

### 3.10 Start from a recipe

A recipe is a directory in the same shape as a repository's `.docket/` (§3.11): `pod.yaml`,
`roles/`, `pipeline.yaml`, `policies/`, `plugins/`, `skills/`, every part optional. **What a recipe
brings is derived from what the directory holds, never declared**: `docket pod validate <dir>`,
`docket pod apply --dry-run`, `docket init --recipe` and `docket pod recipes` all print the
same summary line (`roles 1 · policies 1 · members 1 · pipeline secure-build · ...`). Eighteen
ship with docket, of five kinds; the full page, generated from the recipes themselves, is
[the recipe library](recipes.md).

| Kind | Recipes | What `apply` plans on a lean pod |
|---|---|---|
| Team | `secure-build`, `research-review`, `ops-approval`, `intake` | roles and members it needs, a pipeline, sometimes a policy |
| Policy pack | `git-safety`, `no-egress`, `secrets-guard`, `prod-approval` | policy items only: no roster change, no pipeline change |
| Methodology | `tdd`, `spec-first`, `spec-writer`, `reflexion`, `dual-review`, `cross-family-review`, `frugal` | the members the practice needs from the built-in and starter roles, and the smallest pipeline that *is* the practice (`frugal` also sets a budget) |
| Check | `anti-tautology`, `mutation` | a pipeline with a `run:` step that fails the task when its tests prove nothing (`mutation` needs mutmut installed) |
| Tooling | `code-intel` | MCP servers for the pod (structural search, read-only language intelligence) |

```bash
docket pod recipes                        # every recipe reachable by name, what each brings
docket pod recipes tdd                    # description, summary, the recipe's own README
docket init --recipe secure-build          # a new pod for this repository, recipe applied after provisioning
docket pod apply git-safety          # a policy pack onto a pod that already exists
docket pod apply ./team-recipes/ci   # a directory of your own, same shape
docket pod apply --dry-run           # no argument: <codebase>/.docket/, plan only
```

A name resolves in three places, nearest wins: a directory path as given, then your own
`~/.docket/recipes/<name>/`, then the shipped library. Dropping a directory under
`~/.docket/recipes/` makes it addressable from `init --recipe` and `apply` with no registration.

`apply` copies the directory's roles into this pod's own overlay (`config/roles.json`),
validates and binds its `pipeline.yaml` as the pod's default (§3.5), adds the `members` its
`pod.yaml` names, copies its policy pack into this pod's own `config/policies/` (§3.6) and its
skills into `config/skills/` (§3.13) — the same steps you would otherwise do by hand, scoped to
this pod alone, validated as a whole before anything is written. `--dry-run` shows the plan;
re-running is idempotent (an applied recipe plans every item `skip`). Every apply records the
directory as the pod's `configSource` (§3.11), the all-`skip` one included.

**Compose, then commit.** Recipes are seeds; the repository is where they combine. Apply the
team you want, then the policy packs security asks for, then write the result back next to the
code and apply that once so the record names the repo:

```bash
docket init --recipe tdd
docket pod apply git-safety
docket pod apply secrets-guard
docket pod export --force          # the merged team, in .docket/
docket pod apply                   # plans every item skip; configSource is now ./.docket
git add .docket && git commit -m "Add: the myapp agent team"
```

Two pipelines applied in sequence replace each other (the plan says `replace`); policies and
roles accumulate. `docket pod export <dir>` writes the reverse of `apply`: this pod's own
scope, in the same directory shape and the short form, with a `# yaml-language-server:` header
resolved against the `config-v1` JSON Schemas it copies into `<dir>/.schemas/` (the same schemas
`scripts/gen_config_schemas.py` publishes under `docs/contracts/config-v1/`).

### 3.11 Keep the team in the repo

A team is a directory named `.docket/` next to the code, in the same shape `docket pod
export` writes and every shipped recipe ships:

```text
.docket/
  pod.yaml            kind: pod       members (roles to add), settings, optional pipeline filename
  roles/<name>.yaml   kind: role      short form: model, cannot, verdict|verify|approval, instructions
  roles/<name>.md                     the role's instructions, plain Markdown
  pipeline.yaml       kind: pipeline  short form: `- id: role` steps with verify/verdict/approval/on
  policies/*.yaml     kind: policy    when/then; JSON still loads
  plugins/*.py                        hashed predicate plugins (rare)
  skills/<name>/SKILL.md              Agent Skills: name + description up front, the body read on demand
  .schemas/                           generated JSON Schemas the `# yaml-language-server` headers point at
```

A complete, small one. `pod.yaml` names the members to add beyond the Lead + Implementer the
blueprint provisions, and any pod setting (§3.3, §3.6) to set; the other files are the same short
forms §3.4, §3.5 and §3.6 describe:

```yaml
# .docket/pod.yaml
kind: pod
name: myapp
members: [security-vetter]
settings:
  budgetUsd: 5
  allowCommands: pytest,uv
  approvalMode: refuse
```

```yaml
# .docket/pipeline.yaml
kind: pipeline
name: secure-build
steps:
  - plan: lead
    model: cheap
  - build: implementer
    verify: true
  - vet: security-vetter
    verdict: [APPROVE, REQUEST-CHANGES]
    on: {REQUEST-CHANGES: {goto: build, max: 1}}
```

`roles/security-vetter.yaml` and `.md` are the `secure-build` recipe's (`export` writes them after
`init --recipe`); a role of your own is the §3.4 example, and `policies/no-curl.yaml` the §3.6
one. The loop you run each time the team changes:

```bash
docket pod export             # first time: write what the pod has now into ./.docket/
$EDITOR .docket/pipeline.yaml       # change the route, a rule, a role
docket pod validate                     # every document, invalid files first, exit 1 on any error
docket pod apply --dry-run    # the plan: add / replace / skip per item
docket pod apply              # write it (one pod.apply audit entry when something changed)
git add .docket && git commit       # the team is versioned with the code
```

Three commands read it, and nothing else does:

| Moment | Command | What happens |
|---|---|---|
| Creating the pod | `docket init` (with `.docket/` present) or `docket init --recipe <name\|dir>` | every document is validated **before** the pod is provisioned (an error exits 1 naming file, line and field, and provisions nothing); after provisioning, the directory is applied exactly as `pod apply` would, with one `pod.apply` audit entry. `--no-apply` provisions only. `--recipe` and a present `.docket/` together are refused: one source of record. |
| Re-applying after a change | `docket pod apply` (defaults to `<codebase>/.docket/`) | additive and idempotent: a second run plans every item `skip`; `--dry-run` shows the plan |
| Writing it back | `docket pod export` (defaults to `<codebase>/.docket/`; refuses a non-empty one without `--force`) | the pod's own scope in the short form, ready to commit |

Rules worth knowing:

- **Nothing is applied without an operator command.** Dispatch, `docket start`, schedules and
  `docket exec` never read `.docket/`: an Implementer editing it in its worktree changes nothing until
  you apply it. `docket pod show` prints `configSource`, `configDigest` and
  `drift: yes|no`, so you can see that the directory moved on since it was applied.
- **A repository cannot loosen your rules.** Its policies land in the pod scope and accumulate
  with the global ones under the most-restrictive rule; a global `block` stays a block.
- **A credential value never appears.** Provider documents and policies carry names; keys live in
  `docket setup provider`.
- **Validate from the repo root** with `docket pod validate` (no argument: `.docket/` when present).
  Commit `.schemas/` if you want editor autocompletion offline; `export` regenerates it.
- **A step may name its model** (`model: cheap|strong|<provider/id>`): it applies to that hop
  only and is never persisted to the agent's own metadata.

### 3.12 `AGENTS.md`: the instructions your repository already keeps

Many repositories keep an `AGENTS.md` at the root for coding agents (Codex, Copilot, Cursor and
Claude Code all read it). docket reads it too, by default: when a pod's `projectInstructions`
setting is unset and the codebase root holds `AGENTS.md`, it is composed into every member's
system prompt as the project-instructions section, right after `INSTRUCTIONS.md`. It is treated
as content from the codebase, not from you: screened through the `pre_input` policy hook as
untrusted (a `block` replaces it with an audited one-line marker), middle-truncated to its budget
share, and reported as `projectInstructions` in the `prompt_composed` trace event.

```bash
docket pod show myapp-implementer   # ... Project instr.:   AGENTS.md (default)
docket pod set projectInstructions CONTRIBUTING.md,docs/STYLE.md   # an explicit list replaces the default
docket pod unset projectInstructions                                # back to the default
```

An explicit list never adds to the default: name `AGENTS.md` in it if you want both. The
`AGENTS.md` docket writes inside each agent's private workspace is a different file (a role's
red lines, §2); the two are composed in different sections. Nested `AGENTS.md` files deeper in
the tree are not read: a turn has one root.

### 3.13 Skills: instructions an agent pulls on demand

A skill is a directory holding a `SKILL.md` in the Agent Skills shape: YAML front matter with
`name` (equal to the directory name, `[a-z0-9-]`, up to 64 characters) and `description` (one
sentence, up to 1024 characters), then the instructions as Markdown, with optional
`scripts/`, `references/` and `assets/` beside it. docket looks in three places, nearest wins by
name:

| Scope | Directory | How it gets there |
|---|---|---|
| repository | `<codebase>/.docket/skills/<name>/` | committed with the code, read in place |
| pod | `~/.docket/workspaces/pods/<project>/config/skills/<name>/` | a recipe's `skills/` copied by `apply`; `export` writes it back |
| global | `~/.docket/skills/<name>/` | you put it there, for every pod on this machine |

Disclosure is progressive, as the shape intends. The system prompt gets a `# Skills` section of
`- name: description` lines (each description screened through `pre_input` as untrusted, the
section capped and reported as `skills`), and the body is read only when the agent calls the
`skill` tool with a name (or a name and a file inside the skill's directory). That tool is a
built-in of kind `read`, goes through the same chokepoint as every other, and is denied per role
with `cannot: [skill]` like any other tool. A skill whose front matter is invalid (a `name` that
does not match its directory, a missing `description`) is skipped and audited once, never raised
into a turn. `allowed-tools` and other keys are accepted and ignored: a role's denials are the
only capability statement.

```bash
mkdir -p .docket/skills/release-checklist
$EDITOR .docket/skills/release-checklist/SKILL.md     # front matter + the checklist
docket pod show myapp-implementer                # ... Skills: release-checklist (repo), security-review (pod)
```

`secure-build` ships one (`security-review`, a concrete review checklist the vetter can pull);
`tdd` and `spec-first` ship `test-first` and `writing-a-spec`. Instructions from the repository,
`AGENTS.md` and skills alike, are read live and screened; rules from the repository (roles,
policies, pipelines, settings) are still applied only by an operator command (§3.11).

### 3.14 Export traces to OpenTelemetry or Langfuse

The record `docket task trace` reads can also go to a tool you already run: an OpenTelemetry
collector, Jaeger, Phoenix, Honeycomb or Langfuse. A destination is a `kind: exporter` YAML
document, the same shape as a `kind: provider` (§3.1). Five ship in the wheel, all off:
`otel-collector`, `jaeger` and `phoenix` need no credential, `honeycomb` takes a header key and
`langfuse` a basic-auth pair. Credentials resolve as a provider's do, from the environment first
and then from `docket setup provider add`. Nothing is sent until you run `docket setup export enable`, and a
present credential never turns an exporter on by itself.

Every turn docket runs (a dispatch hop, a `docket start --dispatch` sweep, `docket exec`) hands
the records it writes to the local trace, already redacted, to `core/telemetry.py`, which turns
each session into spans: a `docket.session` root with `gen_ai.chat` and `execute_tool` children,
their ids derived from the session id so a re-send lands on the same trace. A pod dispatch runs
every hop in one session, so its lead, implementer, reviewer and tester appear as one trace, each
model call its own span, under one root that stays open from the first hop to the last. A background
pipeline delivers them to every enabled exporter as OTLP/HTTP JSON over the standard library
(the `otlp-http` dialect; D-24's cut of the OpenTelemetry SDK stands, D-48). It holds a bounded
queue, counts what it drops, and never raises into a turn. The pipelines start with the first
turn of a process and keep that set of exporters and levels for its life, so a change made with
the commands below reaches the next `docket run` or `docket exec` at once and a running
`docket start` only after a restart. `DOCKET_NO_EXPORT=1` turns export off for one process;
`DOCKET_NO_TRACE=1` stops the local write and, with it, the export.

#### What leaves this host: the privacy level

Each exporter document declares what it shares beyond bare structure (ADR 0015). Structure —
model and tool names, timing, measured token counts, pass/fail, ids — is always sent. Content is
split into six classes, and a level is a named set of them:

| `privacy:` | Adds | The destination sees |
|---|---|---|
| `minimal` (default, every built-in) | nothing | structure only; Input/Output columns stay empty |
| `actions` | `toolArguments`, `errors` | what the agent did: tool arguments (`gen_ai.tool.call.arguments`), an approval's command line, error text |
| `conversation` | + `toolResults`, `completions`, `prompts` | what was said and read: `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.tool.call.result` |
| `full` | + `instructions` | also the system prompt (`gen_ai.system_instructions`), sent once per session and again only when it changes |

Or name the classes exactly: `share: [completions, toolArguments]`. `contentMaxChars` (default
4000) cuts every content value, keeping JSON intact. The attribute names are the OpenTelemetry
GenAI ones, which Langfuse reads natively as a generation's Input/Output. Credentials and
secret-shaped values are redacted before anything is written, at every level.

Three rules keep the level honest. The projection is an **allowlist**: an attribute leaves only
when its class is granted, so a new trace field stays home until someone classifies it. A
conversation is filtered **per part**: sharing `prompts` sends your task and the model's text
but replaces a tool result inside it with `{"type": "withheld", "class": "toolResults"}`.
And content is **captured only on demand**: prompts, replies and tool output enter the local
trace only while some enabled exporter grants them, so at `minimal` everywhere the local trace
is exactly what it was without exporters.

#### Choosing a level

Widening is a command, not an edit you can make by accident. It lists what starts leaving and
where, and asks; off a TTY it refuses unless you pass `--yes`. Narrowing never asks. Both are
written to the audit log as `exporter.privacy name=… from=… to=… host=…`. Real transcripts from
this machine:

```bash
$ docket setup export privacy langfuse conversation
⚠ 'langfuse' will widen from 'minimal' to 'conversation':
    + toolArguments  (e.g. gen_ai.tool.call.arguments)
    + errors  (e.g. docket.error.message)
    + toolResults  (e.g. gen_ai.tool.call.result)
    + completions  (e.g. gen_ai.output.messages)
    + prompts  (e.g. gen_ai.input.messages)
  destination: cloud.langfuse.com
✗ Error: Refusing to widen 'langfuse' off a TTY without --yes.

$ docket setup export show langfuse
  ...
  privacy       conversation

  Leaves this host:
    ✓ toolArguments  (gen_ai.tool.call.arguments, docket.approval.action)
    ✓ errors  (docket.error.message)
    ✓ toolResults  (gen_ai.tool.call.result)
    ✓ completions  (gen_ai.output.messages)
    ✓ prompts  (gen_ai.input.messages)
    ✗ instructions  (gen_ai.system_instructions)
    never: credentials, secret-shaped values (redacted)
```

`docket setup export preview <name>` shows what a destination would receive from a real local
session (the newest, or `--session <id>`) before anything is sent: every span, every attribute
with its class, and a footer counting them. `--level`/`--share` try another level without
writing it; `--json` prints the exact wire document. It opens no socket and writes nothing.
Because content is captured only on demand, a session recorded at `minimal` holds no
conversation to preview at `conversation`; the footer says so rather than showing less than a
later session would send.

```bash
$ docket setup export preview langfuse
Preview: langfuse  (session agent:harness-e262ed07e5a2:default)
  privacy: actions   shares: errors, toolArguments

  execute_tool read
    gen_ai.tool.name [structure]  read
    gen_ai.tool.call.arguments [toolArguments]  {"path": "notes.txt"}
    docket.tool.ok [structure]  True
  ...
  spans: 4
  attributes:
    structure: 21
    toolArguments: 1
    ...
  bytes: 2934
```

The level also travels with the data: every `docket.session` root span carries
`docket.privacy` and `docket.privacy.classes`, so the destination shows what it was allowed to
receive. From `conversation` up the root also carries the session's task and its last answer
(`docket.session.input`, `docket.session.output`); the built-in `langfuse` document aliases them to
the root observation's input and output, which Langfuse shows as the trace's own. `docket setup export list` has a `SHARES` column, `docket pod show` prints the level
per exporter, and `docket setup` notes any exporter sharing `conversation` or `full` with a host
that is not this machine.

#### Turning a destination on

`enable` resolves the credential (a TTY prompt, or a refusal naming `docket setup provider add <NAME> --credential`
when there is none), probes the endpoint with it, and classifies the result before writing
anything. A transport failure refuses the enable; a reachable-but-unauthenticated endpoint still
enables, because only a transport failure is disqualifying. `enable --privacy <level>` (or
`--share a,b`) sets the level in the same step, under the same confirmation rule.

```bash
$ docket setup export enable langfuse --privacy actions --yes
✓ Exporter enabled: langfuse  ->  https://cloud.langfuse.com/api/public/otel/v1/traces
  scope: global  shares: actions (errors, toolArguments)

$ docket setup export enable honeycomb          # no key stored yet
✗ Error: Exporter 'honeycomb' needs credentials that are not set:
  docket setup provider add HONEYCOMB_API_KEY --credential
```

Store the missing credential(s) with `docket setup provider add <NAME> --credential` (prompts, never take a value as an
argument) and re-run `enable` -- it re-probes with the stored credential before writing anything.

| Command | Effect |
|---|---|
| `docket setup export list [--json]` | Every built-in and global exporter, dialect, activation state, required credentials, scope, `SHARES` |
| `docket setup export show <name> [--json]` | One exporter's effective document, health counters (`exported`/`dropped`/`failed`) and the "Leaves this host" block |
| `docket setup export enable <name> [--endpoint URL] [--privacy <level>\|--share a,b] [--events ...] [--no-verify] [--yes]` | Resolves credentials, probes, writes a minimal global override (never the whole inherited document) |
| `docket setup export privacy <name> [<level>\|--share a,b] [--max-chars N] [--yes]` | Without a level, prints what leaves; otherwise changes it, confirming a widening |
| `docket setup export preview <name> [--session <id>] [--level <level>\|--share a,b] [--json]` | What the destination would receive from a local session; no network, no write |
| `docket setup export disable <name>` | Writes `enabled: false` to the override, nothing else |
| `docket setup export test <name>` | Re-probes the currently-configured endpoint without changing anything |
| `docket setup export add <file.yaml> [--yes]` | Registers a new `kind: exporter` document; one above `minimal` follows the widening rule |
| `docket setup export remove <name>` | Removes a global override; a built-in reverts to its shipped defaults instead of disappearing |
| `docket setup export export <name> [<file>]` | Writes the effective document back out, short-form YAML |

A pod names the destinations it wants in `pod.yaml`'s `exporters:` list (validated against the
live catalog by `apply`/`validate`/`init --recipe`; unknown names refuse before anything is
written); the list is recorded and reported, never itself the thing that turns an exporter on --
`docket setup export enable` is still the one write that flips `enabled: true`, so naming a
destination in a recipe documents intent without silently starting to ship data anywhere.

```yaml
# .docket/pod.yaml
exporters: [otel-collector, langfuse]
```

**Live proof, this machine, 2026-09-28:** one real `docket exec` turn per level against
the local llama.cpp endpoint, with `otel-collector` (a local `otel/opentelemetry-collector`,
`debug` exporter) and `langfuse` both enabled at that level, a unique canary in the task and
another in the file the agent read. `minimal`: no canary in the collector log, in Langfuse, in
`preview --json` or even in the local trace; Langfuse's Input/Output empty. `actions`: tool
spans carried `{"path": "notes.txt"}`, still no canary. `conversation`: Langfuse showed each
generation's Input and Output and the `read` tool's result, both canaries present. Full detail:
`specs/functional/observability-export.spec.md` §"External verification".

### 3.15 Notify a human, and answer without blocking

An unattended pod's gated tool call used to have two choices: block the hop for up to
`TOOL_APPROVAL_TIMEOUT` (120s) with nobody watching, or `approvalMode: refuse` and lose the call
outright. A third posture, `park` (ADR 0016, D-50), records the exact call and moves the task to
`waiting_approval` without blocking anything — the sweep moves on to the next pod in the same
pass. `approvalMode` resolves per caller when a pod hasn't set one explicitly: `docket start
--dispatch`'s sweep and a non-interactive `docket run` both resolve to `park`; an
interactive foreground dispatch (a real TTY) resolves to `wait`. A pod's own stored
`approvalMode` (`docket pod set approvalMode wait|park|refuse`) always wins over the
caller's default. A parked approval is granted or denied exactly like any other (CLI, HTTP, MCP,
Telegram); granting it re-runs the same hop, carrying a single-use pre-grant matched by a stable
argument digest so the model's identical next call passes once without asking again. Left
untouched past the pod's `approvalExpiryHours` (`docket pod set approvalExpiryHours
N`, default 24), it expires and denies — the same fail-closed sweep a pre-hop `approval` gate's
pending approval already used.

A pipeline can also pause a task to ask a real *question*, not a permission: an `input` step
(`- ask: {input: {from: <step-id>}}`) mints a question from another step's output and moves the
task to `waiting_input`, distinct from `waiting_approval` in the CLI/HTTP/MCP surfaces even
though both read the same `INPUT_REQUIRED` A2A state. The `intake` recipe (§3.10) wires this to a
Lead's own typed brief: the Lead writes an `objective`/`acceptance`/`resources`/`questions`
brief and ends with `READY`/`NEEDS-INPUT`/`REJECT`; `READY` runs a deterministic check that every
declared resource (`secret:NAME`, `path:P`, or `verify`) actually exists before handing off to
the Implementer, `NEEDS-INPUT` asks the brief's own `questions[]` and returns to the Lead once
they're answered, `REJECT` fails the task outright naming the reason. An unanswered question past
its own deadline (`docket pod set inputExpiryHours N`, default 72 — a separate knob
from `approvalExpiryHours`, since a question is reasonable to leave open longer than a
permission) moves the task to `blocked` (`blockedReason: "input_expired"`), never `failed`.

```yaml
# pipeline.yaml — a generic input step
steps:
  - id: lead
    role: lead
  - id: ask
    input:
      from: lead
    on:
      answered: {goto: lead, max: 3}
      declined: {goto: lead, max: 3}
  - build: implementer
```

**Finding out.** Nothing above pushes a notification by itself. `docket inbox [--json] [--since
<iso>] [--peek]` (also `GET /inbox`, the MCP `inbox` tool, and Telegram's `/status`) is read-only
and computed live: every pod is enumerated, each task sorted into `needsYou` (any `waiting_*`
status, plus `blocked`), `failed`, `doneSince` or `running`, and a pending approval added to
`needsYou` unless its own task already carries it. A plain `docket inbox` call advances a durable
cursor so the next one's `doneSince` only shows tasks that finished meanwhile; `--peek` and an
explicit `--since` don't.

**Pushing.** A destination is a `kind: channel` YAML document, the same shape as `kind: exporter`
(§3.14). Seven dialects ship, all disabled except `console` (your own terminal, already the
inbox): `desktop`, `webhook`, `command`, `ntfy`, `email` and `telegram` notify only; `console` and
`telegram` may also `decide` (act on an approval from inside the channel). Console sends
nothing, so with nothing else enabled a parked task waits unseen until `docket inbox`: `docket
setup` counts that as an issue once a pod exists (`checks.notifications` in `--json`), and
`docket init`, `docket start --dispatch` and a foreground dispatch that found events print the
same warning; `docket setup notify enable desktop` is the zero-configuration fix. A channel declares
`content: minimal|actions|conversation` (default `minimal`) the same way an exporter declares
`privacy`, and widening it is the same confirmed, audited command shape:

```bash
docket setup notify enable webhook --set url=https://example.com/hook --set secret=WEBHOOK_SECRET
docket setup notify privacy webhook actions --yes
docket setup notify test webhook          # one synthetic event, to check the URL/binary/topic works
docket setup notify flush [--dry-run]       # push what's pending now; the `docket start` sweep and `docket run` already do this
```

`webhook` signs its POST per Standard Webhooks (`webhook-signature: v1,<hmac-sha256>`); `command`
runs a local binary with the event as JSON on stdin; `ntfy`/`desktop`/`email`/`telegram` each wrap
one more stdlib-only transport. Unlike `exporters:` (§3.14), a channel is a global catalog
entry, not something a `pod.yaml` names or scopes — every enabled channel watches every pod's
inbox.

**Answering.** A parked approval: `docket task approve <task-id>` / `docket task deny <task-id>`. A parked
question: `docket task answer <task-id> [--pod <name>]` (interactive — shows the brief and any prior
answers, prompts once per schema property on a TTY, then answers) or non-interactively `docket
task answer <task-id> [text] [--field name=value]... [--decline]` — a bare `text` fills a
single-property question, `--field` names each property of a richer one. Both, plus `POST
/tasks/<id>/answer` and the MCP `task_answer` tool, resolve through the same
`core.answers.answer_task` function, so an answer is screened by the same input policy hook
regardless of which surface sent it.

## 4. File reference

**Hand-editing.** Docket writes its JSON atomically: a file lock, a `.bak` of the previous
version, and a `0600` replace. If a file is later unreadable, docket restores it from `.bak` and
keeps the bad copy as `.corrupt`. Your editor does not take that lock, so **hand-edit only while no
`docket` process (`docket run`, `docket start`) is running.** For files marked *no*, use the command instead.

### Global (`~/.docket/`)

| File | Format and key fields | Written by | Read on the live path by | Hand-edit |
|---|---|---|---|---|
| `fleet.json` | `agents[{id}]`, `bindings[{agentId,channel,peerKind,peerId}]`, `security{isolationMode,networkMode}` | init, `setup sandbox` | isolation and network mode (`isolationMode`, `networkMode`), Telegram auth (`bindings`) | careful. Use commands where they exist. |
| `docket-providers.json` | `providers{<name>: kind: provider document}` (fields in "Provider catalog" above) | `setup provider add/remove` | endpoint resolution (`baseUrl`, `dialect`, `auth`, `models[].id/contextWindow/maxTokens`) | via `setup provider add/remove/export`. Malformed entries are named by `docket setup`. |
| `docket-models.json` | `default`, `roles{role: provider/model}`, `rankAnchors{economy,standard,premium}` | `setup model set/preset/reset` | policy resolution for agents following policy; `economy`/`standard` back `modelClass` cheap/strong | yes, but prefer `setup model set`. Malformed entries are ignored silently. |
| `docket-roles.json` | `{"roles": {name: archetype}}` (fields in §3.4) | you | tool narrowing, hop budget, gate contract; templates at provisioning | by hand; `pod apply <file>` writes the pod's own overlay |
| `policies/*.yaml\|json` | one policy per file (§3.6) | `docket setup`, init, you | every tool call, task enqueue and hop output | **yes, this is the intended interface** |
| `docket-mcp-servers.json` | `servers[{name,command,args,env,timeout,kind,tools,isolate}]` | `setup mcp add/remove` | every turn | via command |
| `docket-exporters.json` | `exporters{<name>: kind: exporter override}` — only the keys you changed (`enabled`, `endpoint`, `privacy`/`share`, `contentMaxChars`, `events`) over the built-in | `setup export enable/disable/privacy/add/remove` | the export pipeline at the start of every turn: which destinations run, and at what level (§3.14) | via command. A hand edit that widens `privacy` skips the confirmation and the `exporter.privacy` audit entry. |
| `exporters-health.json` | `{<name>: {exported,dropped,failed,…}}` | the export pipeline, after every turn | `setup export show`, `setup` | no |
| `docket-channels.json` | `channels{<name>: kind: channel override}` — only the keys you changed (`enabled`, `capabilities`, `on`, `content`, `actors`, `config`, `secret`) over the built-in | `setup notify enable/disable/privacy/add/remove` | `docket setup notify flush`, `docket start`'s sweep and a foreground `docket run`, each after their own work: which channels run, and how much they carry (§3.15) | via command. A hand edit that widens `content` skips the confirmation and audit entry. |
| `channels-health.json` | `{<name>: {delivered,failed,lastOk,lastError,…}}` | `core.notify.flush`, after every delivery attempt | nothing yet — no CLI surface reads it back | no |
| `notify-state.json` | `{<dedupe-key>: version}` plus an `expiring` list | `core.notify.flush`, saved before delivering | `core.notify.diff_events` on the next flush, to avoid re-sending an unchanged item | no |
| `inbox-cursor.json` | `{"next": "<iso timestamp>"}` | a plain `docket inbox` call | the next plain `docket inbox` call's `doneSince` filter | no |
| `docket-schedules.json` | `schedules{pod: spec}`, `lastRun{pod: epoch}` | `pod set/unset schedule`, `docket start` (`lastRun`) | `docket start --dispatch` sweep | via command; `docket setup` names a bad hand edit |
| `secrets.json` / `secrets.meta.json` | `{NAME: value}` / `{NAME:{added_at,rotated_at}}` | `setup provider add/rotate/remove` | endpoint key lookup (after env) | no |
| `port-allocations.json` | `allocations{pod: base}`, 100 ports each from 3000 | pod create/delete | implementer env `DOCKET_PORT_BASE` | no |
| `docket-runs.json` | `runs[{id,source,project,state,taskIds,…}]` | every dispatch | `docket task list`, `/runs` | no (never pruned) |
| `docket-conversations.json` | `conversations[{id,agentId,peerId,topic,status,…}]` | Telegram | Telegram channel | no |
| `sessions/<key>/session.json` | `messages[]`, `usage{inputTokens,outputTokens,turns}` | every turn | every turn (history, compaction) | no |
| `traces/<pod>/<session>.jsonl` | one event per line `{ts,session_id,agent_role,event_type,payload}` | every turn | `docket task trace`, `docket status`, `/traces`; each record also reaches the enabled exporters as it is written | no. `docket task prune` prunes after `TRACE_RETENTION_DAYS`. |
| `approvals/<id>.json` | `{token,project,role,action,state,created,context}` | gated calls | the approval wait | no. Answer with `docket task approve`/`deny`. |
| `consult-parked/<q-id>.json` | one operator-v1.1 `QuestionV11` | a pod hop's `consult` | dispatch, once, when it parks the task | no. Dispatch removes it; the task keeps the question. |
| `audit.log` (+ `.1`) | JSONL `{seq,ts,user,pid,action,detail,prev_hash}` | every mutating command | `docket log`, `docket log verify` | **never.** It breaks the hash chain. |

**Built-in provider documents** ship in the wheel at `templates/providers/NN-<name>.yaml`
(`anthropic`, `openai`, `google`, `openrouter`, `ai-gateway`, `groq`, `mistral`, `deepseek`,
`xai`, `cerebras`, `together`, `ollama`, `lmstudio`, `local`), not under `~/.docket/`. The
catalog merges them with `docket-providers.json`, nearest-wins by name — a global write under a
built-in's name overrides that document but inherits its presets and pricing unless set
explicitly.

**Built-in exporter documents** follow the same pattern at `templates/exporters/NN-<name>.yaml`
(`otel-collector`, `jaeger`, `langfuse`, `honeycomb`, `phoenix`), every one `enabled: false` at
`privacy: minimal`. `docket-exporters.json` stores only what you changed on top of one.

**Built-in channel documents** follow the same pattern at `templates/channels/NN-<name>.yaml`
(`console`, `desktop`, `webhook`, `command`, `ntfy`, `email`, `telegram`); only `console` ships
`enabled: true`, and every one carries `content: minimal`. `docket-channels.json` stores only
what you changed on top of one.

### Per agent (`~/.docket/workspaces/projects/<pod>-<role>/`)

`.docket-meta.json`, with each key and what uses it:

| Key | Used for | Set by |
|---|---|---|
| `model`, `modelSource` | the model this agent calls; whether policy changes follow it | `setup model set` |
| `role`, `pod`, `blueprint` | tool narrowing, gate, pipeline choice (Lead) | provisioning |
| `codebase`, `workDir` | the directories tools may touch; verify cwd (a dispatched task uses its own worktree) | provisioning |
| `verifyCmd` | the mechanical gate after this member's hop | `pod set verify`, `--verify` |
| `budgetUsd`, `paused`, `pausedReason` | pod budget and auto-pause, **Lead only** | `pod set budgetUsd`, `run --resume` |
| `maxReworkCycles`, `turnTimeoutS`, `verifyTimeoutS` | pod dispatch, **Lead only** | `pod set` (§3.3) |
| `approvalMode`, `approvalExpiryHours` | unattended posture for a gated call (`wait`/`park`/`refuse`); how long a parked approval stays open before it expires and denies, **Lead only** | `pod set approvalMode/approvalExpiryHours` (§3.15) |
| `inputExpiryHours` | how long a parked *question* (`waiting_input`) stays open before it expires to `blocked`, **Lead only** — a separate knob from `approvalExpiryHours`, default 72 | `pod set inputExpiryHours` (§3.15) |
| `portRangeStart`, `portRangeCount`, `scratchDir` | Implementer environment `DOCKET_PORT_BASE/COUNT`, `DOCKET_SCRATCH_DIR` | provisioning |
| `sessionKey`, `projectKey` | the base session key; dispatch builds its own per-task session key | provisioning |
| `templateVersion`, `kind`, `scope`, `stack`, `name`, `description`, `created` | informational. `stack` and `name` fill templates at provisioning | provisioning |

The Markdown files are covered in [§2](#2-how-the-files-reach-a-running-agent) (what reaches the
model) and [§3.2](#32-change-what-an-agent-is-told) (what to edit, and what overwrites it). Only
the Lead has `TASK_LIST.json`, the pod queue. Change it with `docket task add` and
`docket task retry`, never by hand while a dispatch holds a claim.

---

## 5. Sharp edges

These are true of the current code. Each one is a reason to check a setting's effect instead of
assuming it. Phase 26 ([ADR 0008](adr/0008-configuration-contract.md), closed 2026-09-26) fixed the
rest of the original list; what remains below is the honest boundary, not a backlog.

- **`WORKFLOW_AUTO.md` and `memory/` are not in the prompt** (§2). Edit `SOUL.md`/`MEMORY.md`.
- **Your prompt text belongs in `INSTRUCTIONS.md`.** It is operator-owned (docket never writes
  it), composes right after `SOUL.md`, and survives `pod set verify` and `pod apply`; generated files
  are re-rendered wholesale by `docket pod apply` when a template or archetype changes
  (`--dry-run` shows the diff, `docket setup` flags stale members).
- **A skipped file is silent on the live path, but `docket setup` names it.** An invalid schedule spec,
  model-policy entry or overlay role — global or pod-scoped — never crashes a fleet — the loader
  skips it — and `docket setup` reports each one with pod (when applicable), file, key and reason
  (a broken *policy* file instead fails closed at evaluation, §3.6). Run `docket setup` after hand-editing
  any registry.
- **A live `warn`/`redact` policy hit is recorded in the audit log** (`docket log`, action
  `tool.warn`), not in traces — so `docket task trace`/`docket status` won't show it.
- **A running `docket start` keeps the exporters it started with.** Export pipelines start once
  per process (§3.14), so `docket setup export enable`, `disable` and `privacy` reach a
  long-running `docket start --dispatch` only after it restarts, and that includes **narrowing**: until
  the restart, it keeps sending at the old level. Restart it after any change to what leaves.
- **A destination gets only what was captured while it was allowed to.** Prompts, replies and
  tool output are recorded only while an enabled exporter grants them (§3.14), so a wider level
  cannot send an earlier session's conversation, and `preview --level conversation` on that
  session says so.
- **`docket pod delete` keeps an unmerged branch.** Teardown deletes `docket/<pod>/<member>` when it
  is merged into your current branch; an unmerged one is kept and the command to remove it is
  printed.
