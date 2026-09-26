# Configuring docket: the files it creates and how to use them

This guide maps every file docket writes, on the machine and per project, to what it controls,
how to change it, and what reads it while an agent is actually running. Its focus is the question
the other guides leave open: **how do I customize my agents, the orchestration between them, and
what they are allowed to do?**

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
creates the **workstation foundation** (global state, shared org agents, baseline policies). Every
time it runs, it creates one **pod** for the current project. There is no separate setup step.

`docket init` stops before creating the pod unless a model endpoint is ready. On a fresh machine,
register one first:

```bash
docket models provider add local http://127.0.0.1:8081/v1 --model qwen --name "Qwen local" \
  --ctx 16384 --max-tokens 4096
docket models preset local          # every role now resolves to local/qwen
docket init --pod full              # Lead + Implementer + Reviewer + Tester
```

The result, with the moment each file appears. Files are `0600` and directories `0700` unless
noted.

```text
~/.docket/                              DOCKET_HOME: every piece of docket state lives here
├── fleet.json                          init         agent registry, provider endpoints, flags
├── docket-models.json                  init/preset  role -> model policy
├── port-allocations.json               first pod    per-pod port range bases
├── audit.log                           first change hash-chained record of every mutation
├── policies/*.json                     init         6 baseline guardrail policies
├── docket-roles.json                   roles add    your custom role archetypes
├── docket-mcp-servers.json             mcp servers  external MCP tool servers
├── docket-schedules.json               you          dispatch schedules (no CLI writer)
├── secrets.json, secrets.meta.json     keys add     stored API keys + timestamps
├── docket-runs.json                    dispatch     one record per dispatch invocation
├── docket-conversations.json           wire         Telegram conversation registry
├── sessions/<session-key>/session.json dispatch     durable per-session turn history
├── traces/<pod>/<session>.jsonl        dispatch     observable events per session
├── approvals/<apr-id>.json             gated call   pending/granted/denied approvals
└── workspaces/
    ├── manager/  knowledge/  security/ init         shared org specialists
    ├── projects/<pod>-<role>/          init/pod add one private workspace per pod member
    │   ├── .docket-meta.json           the agent's facts and per-pod settings
    │   ├── SOUL.md                     identity and role instructions
    │   ├── AGENTS.md                   red lines (and a startup section, see §2)
    │   ├── TOOLS.md                    implementers only: ports, scratch dir, verify gate
    │   ├── HEARTBEAT.md                task ledger
    │   ├── MEMORY.md                   durable project facts
    │   ├── WORKFLOW_AUTO.md            startup contract (versioned, regenerated)
    │   ├── memory/YYYY-MM-DD.md        daily logs
    │   ├── TASK_LIST.json              Lead only, after the first `delegate`: the pod's queue
    │   └── worktree/                   implementers in a git repo: a git worktree
    └── pods/<pod>/.scratch/            first pod   the pod's isolated scratch directory
```

**Inside your repository**, docket writes almost nothing, but not nothing. For each Implementer of
a pod whose codebase is a git repository:

- a branch `docket/<pod>/<pod>-implementer`, created in your repo;
- an entry under `<repo>/.git/worktrees/`;
- a checkout of that branch at `~/.docket/workspaces/projects/<pod>-implementer/worktree/`.

The Implementer edits that worktree, never your checked-out branch. Dispatch never commits: unless
the agent ran `git commit` itself, its changes stay **uncommitted** in the worktree, so you see them with
`git -C ~/.docket/workspaces/projects/<pod>-implementer/worktree diff`, then commit on its branch
and merge it like any other. Your verify command's by-products (`__pycache__/`, caches) land
there too. `docket delete` also deletes that branch when it is merged into your
current branch; an unmerged branch is kept, with the removal command printed. Reviewer and Tester run with the codebase root as
their working directory, so a test run can leave caches in your checkout. Outside the repo,
`docket init` also creates `~/Sites` (`SITES_DIR`) and `/tmp/docket` (`DOCKET_LOG_DIR`) if they
are missing.

To try any of this without touching your real setup, point `HOME` (or `DOCKET_HOME`) at a scratch
directory. Every docket path resolves under it.

---

## 2. How the files reach a running agent

This is the model you need to customize anything. Every live turn, whether a dispatch hop, a
`docket serve` sweep or a Telegram `/delegate`, rebuilds the agent's **system prompt from disk**.
Nothing is cached, so an edit takes effect on the next turn with nothing to restart.

The system prompt is, in this order:

1. **`SOUL.md`**, with the persona block re-rendered from `.docket-meta.json`. An oversized
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
(`docket trace`). Nothing is dropped silently. `docket maintain <id> check` warns when the static
context passes the budget.

**Not sent to the model**, despite what the file names suggest:

| File | What it is actually for |
|---|---|
| `WORKFLOW_AUTO.md` | The startup contract for an agent reading its workspace by hand. A live turn replaces it with the runtime contract above. Editing it changes nothing a docket turn sees. |
| `memory/YYYY-MM-DD.md` | Input to `docket maintain distill` (and to `clean`/`reset`, which distill first). Not in the prompt. Distill to move its content into `MEMORY.md`, which is. |
| `workflows/*.yaml` in a workspace | Nothing reads it. Pipelines are passed with `--file` or bound with `pod config set pipeline` (see §3.5). |

### Who decides what: the ownership map

Six layers make up the orchestration, and each answers exactly one question. When you are unsure
where a change belongs, find the question first:

| Question | Layer | Lives in | Change it with |
|---|---|---|---|
| What needs doing? | **Task** | the Lead's `TASK_LIST.json` | `docket pod <p> delegate` |
| Which team shape does a new pod get? | **Blueprint** | Lead meta `blueprint` (creation-time only) | `docket init --blueprint` |
| Who works a task, in what order, behind which quality gates, with how much rework? | **Pipeline** | the blueprint's built-in default; a YAML file for a custom route, run once or bound as the pod default | `docket pipeline validate/plan/run`, `docket pod <p> config set pipeline` |
| How does each *kind* of agent behave, and which tools is it structurally denied? | **Role archetype** | built-ins + `~/.docket/docket-roles.json` | `docket roles`, `docket pod <p> add <role>` |
| What does *this* agent know about *this* project? | **Workspace instructions** | `SOUL.md`, `TOOLS.md`, `MEMORY.md` | `docket edit` |
| What is forbidden or human-gated, across everything? | **Policies + command classifier** | `~/.docket/policies/*.json` (+ fixed `SAFE_BINS`) | `docket policies` |
| What budget, timeouts, approval posture, extra allowed commands and verify gate bound this pod? | **Pod settings** | the Lead's / member's `.docket-meta.json` | `docket pod <p> config get/set/unset` (`budgetUsd`, `maxReworkCycles`, `turnTimeoutS`, `verifyTimeoutS`, `approvalMode`, `allowCommands`, `pipeline`); `set-verify` |

Two boundaries worth stating because they are easy to get backwards:

- **The pipeline is the route and its controls, never the instructions.** A step says *who* runs
  and *how the output is judged* (mechanical exit code, verdict marker, human approval). What the
  agent is told comes from its role template and workspace files (§2), plus the task text.
- **Every pod always has a pipeline.** `docket pod <p> dispatch` runs the blueprint's default with
  no setup. For a *custom* route: `docket pipeline validate` checks a file, `plan` shows it against
  the real roster without spending tokens, `run --file` executes it once by hand, and
  `docket pod <p> config set pipeline <file>` **binds it as the pod's default for every trigger**
  (dispatch, serve sweep, schedules, webhooks, MCP). Binding validates and plans the file first,
  stores a docket-owned copy with its hash, and a later hash mismatch refuses dispatch loudly.
  `docket pipeline plan <p>` prints a `Source:` line naming which route would run.

**The task itself** arrives as the turn's user message, built by dispatch: the task description,
an instruction line, and the previous hops' output trimmed to the role's `tokenBudget`. The
instruction is, in order of precedence: the pipeline step's own `instructions` (which may
interpolate declared `${variables}`, fed by `docket pipeline run --var key=value` or the webhook
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
| Register an endpoint (OpenAI-compatible) | `docket models provider add <name> <base-url> --model <id> [--name <label>] [--ctx N] [--max-tokens N]` | `fleet.json` → `providers` |
| Point every role at one provider | `docket models preset <anthropic\|openai\|google\|openrouter\|openrouter-free\|ai-gateway\|local>` | `docket-models.json` |
| Change one role's model | `docket models set <role> <provider/model>` (or `set default …`) | `docket-models.json` → `roles` |
| Pin one agent, ignoring policy | `docket profile <agent-id> <provider/model>` (`default` un-pins) | that agent's `.docket-meta.json` → `model`, `modelSource: pinned` |
| Store the API key | `docket keys add OPENROUTER_API_KEY` (or `docket keys setup`) | `secrets.json` |

The model an agent actually calls is the `model` in its own `.docket-meta.json`. Policy changes
rewrite that field on every agent whose `modelSource` is `policy`, immediately. Pins are never
touched.

`--ctx` and `--max-tokens` matter: they are the limits docket checks requests against. Against a
small-context local server, also export `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` (the 30000 default
suits a large hosted model, and two full tool results overflow a 16k window).

Key lookup order for a provider: `DOCKET_LLM_API_KEY`, then the provider's `apiKey` in `fleet.json`,
then the `<PROVIDER>_API_KEY` environment variable, then `secrets.json`. `DOCKET_LLM_BASE_URL`
overrides every endpoint at once, which is handy for tests.

### 3.2 Change what an agent is told

Edit the agent's workspace files directly. `docket edit <agent-id>` opens them in `$EDITOR`.

| To change… | Edit | Notes |
|---|---|---|
| Role instructions, scope, tone, house rules | `SOUL.md` | Always sent in full. The highest-leverage file. |
| Project commands, conventions, where things are | `TOOLS.md` (create it for non-implementers) | Sent verbatim. The Implementer's is generated. See the caution below. |
| Durable facts about the product | `MEMORY.md` | Sent last, so it is the first thing dropped when the budget is tight. |
| Red lines shared by a role | `AGENTS.md` | Everything except `## Session Startup` is sent. |
| Display name | `docket persona <id> set "Rita"` | Written to meta and rendered between `<!-- docket-persona:begin/end -->` in `SOUL.md`. Never edit that block by hand. |

**What overwrites your edits:**

- `docket pod <p> add <role>` writes a *new* member's `SOUL.md`, `AGENTS.md`, `HEARTBEAT.md` and
  (for an Implementer) `TOOLS.md` from its role template. Existing members are not touched.
- `docket pod <p> set-verify` regenerates the Implementer's `TOOLS.md`. Put your own
  Implementer notes in `SOUL.md` or `MEMORY.md` instead, or re-add them after changing the verify
  command.
- `docket maintain <id> reset` resets `HEARTBEAT.md` and clears `MEMORY.md` (after distilling
  into it). `clean` deletes `memory/*.md` (after distilling).
- `docket doctor` rewrites `WORKFLOW_AUTO.md` whenever its contract version is stale. That costs
  nothing, since the file is not sent to the model.
- `docket maintain <id> rebuild` refuses pod members and specialists, so it will not clobber them.

To change the instructions of **every future** member of a role, define a custom role (§3.4).
Existing members keep the `SOUL.md` they were provisioned with; there is no re-render command, so
edit those by hand.

### 3.3 Configure a pod: verify gate, budget, rework, timeouts

Pod-wide settings live in the **Lead's** `.docket-meta.json`. The verify command lives on the
member it gates.

| Setting | Key and file | How to set it | Effect |
|---|---|---|---|
| Verify gate | `verifyCmd` in the Implementer's meta | `docket pod <p> set-verify <p>-implementer "pytest -q"`, or `--verify` on `docket init`/`pod add` | Runs after every Implementer hop in its worktree. A non-zero exit **fails** the task (`verification_failed`). |
| Budget cap (USD, estimated) | `budgetUsd` in the Lead's meta | `docket profile <p>-lead --budget 5` (`0` = none) | Checked before each hop. Over the cap, the task is blocked and the Lead paused until `docket profile <p>-lead --resume`. The figure is an estimate, not your bill. |
| Rework cycles | `maxReworkCycles` in the Lead's meta | no command; edit the Lead's meta (see below) | How many times a Reviewer `REQUEST-CHANGES` sends work back (default `1`, `0` = none). Ignored when you run a pipeline file, which carries its own `maxCycles`. |
| Hop timeout | `turnTimeoutS` in the Lead's meta | no command; edit the Lead's meta | Per-hop wall clock (default 300 s). `--timeout` on `dispatch` overrides it for one run. Under `docket serve`, `DISPATCH_TURN_TIMEOUT_S` overrides it. |
| Verify timeout | `verifyTimeoutS` in the Lead's meta | no command; edit the Lead's meta | Same precedence, `DISPATCH_VERIFY_TIMEOUT_S` under serve. |
| Retries | environment only | `DISPATCH_RETRIES_DEFAULT`, `DISPATCH_RETRIES_<ROLE>`, `DISPATCH_RETRY_BACKOFF_S` | Timeouts and transport errors only. A failed verify or a bad verdict is never retried. |
| Pod roster | members' workspaces | `docket pod <p> add <role> [--count N]` / `docket pod <p> remove <id>` | Dispatch only runs the roles the pod has. |

Setting the keys that have no command: edit the Lead's meta with `docket edit <p>-lead` while no
dispatch is running, then run `docket maintain <p>-lead check`. Values may be numbers or numeric
strings. An invalid value is **silently ignored**, and the default applies. Confirm with
`docket pipeline plan <p>`, which prints the resolved rework budget and steps.

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
`monitor`) cannot be edited, only shadowed by name. See all of them with `docket roles list`, and
dump one as a starting point with `docket roles show reviewer`.

```yaml
# security-reviewer.yaml
name: security-reviewer
scope: pod                    # pod | org
modelClass: strong            # cheap | strong -> resolved through docket-models.json rankAnchors
editRights: read-only         # descriptive only; deniedTools is what enforces it
description: read-only security pass over the implementer's change
tokenBudget: 6000             # context budget for this role's hop message
deniedTools: [write, edit, bash]
gateContract:
  kind: verdict               # none | verdict | mechanical | approval
  regexes: [APPROVE, REQUEST-CHANGES]
soulTemplate: |
  # SOUL.md — ${project} · ${role}

  You are the **${role}** of the **${project}** pod (agent id `${memberId}`).
  Codebase: ${codebaseOrConfigured} (stack: ${stack}).

  ## Role — Security reviewer
  - Review the change for injection, secrets in code, unsafe deserialization and authz gaps.
  - You are read-only. Start exactly one line with `APPROVE` or `REQUEST-CHANGES`.
agentsTemplate: |
  # AGENTS.md — ${project} · ${role}

  ## Red Lines
  - Stay within the `${project}` pod. No cross-project access.
```

```bash
docket roles validate security-reviewer.yaml    # checks fields and dry-renders both templates
docket roles add security-reviewer.yaml         # -> ~/.docket/docket-roles.json
docket pod myapp add security-reviewer          # provisions myapp-security-reviewer
```

Template variables: `project`, `role`, `memberId`, `sessionKey`, `objective`, `codebase`,
`codebaseOrConfigured`, `codebaseOrIt`, `stack`, `workDir`, `requiredStartupFile`. An unknown
`${var}` fails `validate`.


What is read **when**:

- `soulTemplate`, `agentsTemplate` and `modelClass` are used **once**, when a member is
  provisioned. Changing the overlay later does not touch existing members.
- `deniedTools`, `tokenBudget` and `gateContract` are read **live** on every hop, from the merged
  registry.
- A custom role gets **no built-in per-hop instruction line**, so everything it must do belongs in
  its `soulTemplate`.
- The default pipeline only runs `lead → implementer → reviewer → tester`. A custom role joins a
  dispatch **only through a pipeline file** (§3.5).

### 3.5 Change the orchestration: pipelines and blueprints

**Blueprints** pick a pod's shape at creation: `docket init --blueprint
software|research|content|ops|agentic-product`. Only these five exist, and the choice is stored as
`blueprint` in the Lead's meta. Dispatch uses the blueprint's built-in pipeline.

**Pipeline files** declare your own hop order, gates and rework edges. This one runs the custom role
from §3.4:

```yaml
# pipeline.yaml
name: build-then-security
description: Lead plans, Implementer builds (verify-gated), security reviewer vets with rework
steps:
  - id: plan
    role: lead
  - id: build
    role: implementer
    timeout: 900
    gate: {type: mechanical}          # command omitted -> use the member's own verifyCmd
  - id: vet
    role: security-reviewer
    gate:
      type: verdict
      pattern: '^\s*(APPROVE|REQUEST-CHANGES)\b'
      passValues: [approve]
      rework: {to: build, when: [request-changes], maxCycles: 2}
```

```bash
docket pipeline validate pipeline.yaml         # structure only, no pod needed
docket pipeline plan myapp --file pipeline.yaml # resolves against the real roster, runs nothing
docket pipeline run myapp --file pipeline.yaml  # executes; same budget/gates/traces/runs as dispatch
```

Schema (unknown keys are rejected at every level):

- **Top level:** `name` (required), `description`, `variables`, `steps`.
- **Each step:** `id`, exactly one of `role` or `agent` (a specific member id), plus optional
  `retries`, `timeout`, `gate`, and `parallel` (one level of child steps).
- **Gate types:**
  - `mechanical`: `command` (or null for the member's `verifyCmd`), and `timeout`.
  - `verdict`: `pattern`, `passValues`, `caseSensitive`, and `rework: {to, when, maxCycles}`.
  - `approval`: `message`. This is a human sign-off; the task waits in `waiting_approval`.
- **Defaults:** a step with no `gate` falls back to its role's `gateContract`, without a rework
  edge. A step whose role is not in the pod is skipped.

One rule to plan around: a **bound** pipeline (`pod config set pipeline`) is treated like a
caller-supplied `--file` — the pod's `maxReworkCycles` setting never patches it, so the file's own
rework edges are what run. Only the blueprint/built-in default is patched by that setting.

### 3.6 Govern what agents may do

Every tool call passes one chokepoint that applies, in order:

1. The role's tool denials.
2. The argument-aware high-risk command classifier. It is always on and not configurable.
3. Your policies.

**Tool denials (per role).** The built-in tools are `read`, `glob`, `grep`, `fetch` (read kind),
`write` and `edit` (write kind), and `bash` (exec kind). MCP tools arrive as
`mcp__<server>__<tool>` and count as write kind.

- Denying a tool also denies every tool of its kind. That is how a read-only role gets **no** MCP
  tools.
- Built-in denials:
  - `lead`, `reviewer`, `critic`, `monitor`: `write`, `edit`, `bash`.
  - `tester`: `write`, `edit`.
- Denials are **per role, not per agent or per pod.** To restrict one agent, give it a custom role.

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
- **Per-pod widening, scoped and audited:** `docket pod <p> config set allowCommands pytest,uv`
  adds exact binary basenames to the allowlist *for that pod's turns only*. Paths, shell
  metacharacters, opaque names (`eval`, `source`, …) and high-risk-class bins (`git`, `npm`) are
  rejected at write time; a redirected call still asks. Policies remain stricter-only: an `allow`
  policy cannot loosen the classifier.
- **In an unattended run,** each ask blocks the turn for `TOOL_APPROVAL_TIMEOUT` (120 s) and is
  then denied. After three denials in a row (`AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS`), the hop
  fails. For a pod that is *known* to run unattended, set
  `docket pod <p> config set approvalMode refuse`: a gated call then fails the hop immediately
  with `approval_unavailable`, naming the tool and policy, instead of eating the timeout.
- **This is not hypothetical.** Verifying this guide, a real dispatch passed Lead, Implementer
  and Reviewer, then **failed the task** at the Tester on three asks. The asks were for
  `cd <worktree> && python3 …`, which W37-C1 has since allowed. `pytest` and `uv` still ask.

Three ways to avoid it:

- **Allowlist the bins for that pod.** `docket pod <p> config set allowCommands pytest,uv`
  (see above) is the direct fix for exactly this failure.

- **Run checks through the verify gate.** Put them in the mechanical gate (`set-verify`, or a
  pipeline `mechanical` gate). That command runs outside the tool classifier; only high-risk
  commands are refused there.
- **Use allowlisted forms.** Add this to `SOUL.md`: use `python3 -m pytest` rather than `pytest`
  or `uv run pytest`. `bash` already starts in the agent's first project root (the worktree, for an
  Implementer), so relative paths work.


**Policies** (`~/.docket/policies/*.json`, relocatable with `POLICIES_DIR`). Every `*.json` file
in the directory is loaded, and all of them are re-read on every call, so a new file is live
immediately:

```json
{
  "id": "no-curl",
  "applies_to": ["implementer"],
  "hook": "pre_tool_call",
  "match": {"type": "regex", "pattern": "\\bcurl\\b"},
  "action": "require_approval",
  "message": "curl needs approval"
}
```

| Field | Values |
|---|---|
| `applies_to` | Role names as dispatch sees them (`implementer`, `reviewer`, … or a custom role), or `"*"`. |
| `hook` | `pre_input` (a task entering the queue; always evaluated as role `lead`), `pre_tool_call` (tool name and arguments), `pre_output` (a hop's output). |
| `match` | `{"type": "regex", "pattern": …}`, matched case-insensitive and multiline. |
| `action` | `allow`, `warn` (record only), `redact`, `require_approval` (ask a human), `block` (deny). There is no `deny` action; use `block`. |

How policies combine and what they ignore:

- **Precedence.** The most restrictive matching action wins: `block` > `require_approval` >
  `redact` > `warn` > `allow`.
- **A broken policy is skipped silently, and that fails open.** A file with bad JSON or an
  uncompilable regex is skipped, so a `block` policy with a typo **allows** the call.
  `docket policies validate` catches bad JSON but **not** a bad regex. After every edit, run
  `docket policies test` with a string the policy must match, for example
  `docket policies test pre_tool_call implementer "make deploy"`, and confirm the expected result.
  P26-1 in `TODO.md` makes a broken policy deny instead.
- **`redact`** uses docket's generic secret redactor, not your pattern.
- **Ignored fields.** `class` and `description` are documentation only.

**Approvals.** A `require_approval` hit, or a high-risk command such as `git push origin main`,
creates `approvals/<id>.json`.

- **Answering.** Answer it with `docket approve <token>`/`docket deny <token>`,
  `POST /approvals/<token>` under `docket serve`, MCP, or Telegram `/approve`. Every channel is
  audited.
- **Expiry.** Unanswered requests are denied: after `TOOL_APPROVAL_TIMEOUT` (120 s) when a live
  tool call is waiting, after `APPROVAL_TIMEOUT` (900 s) at a pipeline approval gate.
- **Harness mode.** `docket harness run` never waits. It returns `approval_unavailable` instead.

**Network.** `fetch` refuses every host until you allow it:
`FETCH_ALLOWED_DOMAINS=docs.python.org,api.github.com`. That makes `fetch` the *inspectable*
path, not the only one; `bash` can still reach the network through allowlisted interpreters.

**Isolation.** `docket gates isolate on` runs tools inside Docker or bwrap, and refuses the turn
when neither is usable. The image is `DOCKET_SANDBOX_IMAGE`. This sets `isolationEnabled` in
`fleet.json`, the only `security` flag the live path enforces. (`docket gates enable|disable` is
retired: the flag it wrote was never read on the live path.)

### 3.7 Give agents external tools (MCP)

```bash
docket mcp servers add github --env GITHUB_TOKEN=... --timeout 20 -- npx -y @modelcontextprotocol/server-github
docket mcp servers list
```

The command writes `docket-mcp-servers.json`. Its tools appear in every turn as
`mcp__github__<tool>`, gated like built-ins.

- **Read-only roles get none of them.** See §3.6.
- **Configure, not per agent.** Servers apply to the whole install.
- **Spawn cost.** Each server is spawned once per turn, about 0.6 s measured.
- **Plaintext env.** `--env` values are stored in plaintext; they are masked only in `list`.

### 3.8 Run unattended

- **Continuous sweep.** `docket serve --dispatch` drains every pod's queue. Add `--telegram` for
  the approval channel.
- **Schedules.** There is no CLI; write `~/.docket/docket-schedules.json` yourself. Schedules fire
  only while `serve --dispatch` runs:

  ```json
  {"schedules": {"myapp": "@every 30m", "otherapp": "09:00", "third": "*/15 9-17 * * 1-5"}}
  ```

  - **Formats.** `@every Ns|m|h`, a daily `HH:MM` in **UTC**, or a numeric 5-field cron in UTC.
  - **Silent skips.** An entry docket cannot parse is skipped silently.
  - **Don't add other keys.** `serve` rewrites the file with `lastRun` and drops any other
    top-level key.
- **Webhooks.** Use `POST /dispatch/<project>` with the serve bearer token. Set
  `DOCKET_SERVE_TOKEN` to make that token stable.
- **Telegram.** `docket wire <p>-lead` binds a chat. It writes `fleet.json` `bindings` and
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
`docket serve`, set them in its unit file or shell.

---

### 3.10 Start from a shipped recipe

`templates/recipes/<name>/` (inside the installed package; `docket.config.recipes_dir()`) ships
ready-to-apply role/pipeline/policy bundles for common shapes. Each carries its own `README.md`
with the exact commands:

| Recipe | Adds | Use it for |
|---|---|---|
| `secure-build` | a custom `security-vetter` role, verdict-gated with one rework cycle | a read-only security pass before an Implementer's change ships |
| `research-review` | the `researcher`/`analyst`/`writer`/`critic` starter roles | Critic-vetoed research, on a pod you did not create with `--blueprint research` |
| `ops-approval` | the `operator` starter role, approval-gated | a human sign-off before an operational action runs at all |

Applying one is always: add any role it needs (§3.4), `docket pipeline validate`/`plan` its
`pipeline.yaml`, then `docket pod <p> config set pipeline <file>` (§3.5) — and optionally copy its
policy pack (§3.6). There is no `docket recipes` command; a recipe is data, not a new surface.

## 4. File reference

**Hand-editing.** Docket writes its JSON atomically: a file lock, a `.bak` of the previous
version, and a `0600` replace. If a file is later unreadable, docket restores it from `.bak` and
keeps the bad copy as `.corrupt`. Your editor does not take that lock, so **hand-edit only while no
`docket` process (dispatch, serve) is running.** For files marked *no*, use the command instead.

### Global (`~/.docket/`)

| File | Format and key fields | Written by | Read on the live path by | Hand-edit |
|---|---|---|---|---|
| `fleet.json` | `agents[{id}]`, `bindings[{agentId,channel,peerKind,peerId}]`, `security{isolationEnabled,isolationMode,approvalRoutingState,approvalRoutingMode}`, `providers{<name>{baseUrl,apiKey,models[{id,contextWindow,maxTokens,…}]}}` | init, `models provider add`, `wire`, `gates` | endpoint resolution (`baseUrl`, `apiKey`, `models[].id/contextWindow/maxTokens`), isolation (`isolationEnabled`), Telegram auth (`bindings`) | careful. Use commands where they exist. |
| `docket-models.json` | `default`, `roles{role: provider/model}`, `rankAnchors{economy,standard,premium}` | `models set/preset/reset` | policy resolution for agents following policy; `economy`/`standard` back `modelClass` cheap/strong | yes, but prefer `models set`. Malformed entries are ignored silently. |
| `docket-roles.json` | `{"roles": {name: archetype}}` (fields in §3.4) | `roles add` | tool narrowing, hop budget, gate contract; templates at provisioning | via `roles add` |
| `policies/*.json` | one policy per file (§3.6) | `policies init`, init, you | every tool call, task enqueue and hop output | **yes, this is the intended interface** |
| `docket-mcp-servers.json` | `servers[{name,command,args,env,timeout}]` | `mcp servers add/remove` | every turn | via command |
| `docket-schedules.json` | `schedules{pod: spec}`, `lastRun{pod: epoch}` | you, serve (`lastRun`) | `serve --dispatch` sweep | **yes, the only interface** |
| `secrets.json` / `secrets.meta.json` | `{NAME: value}` / `{NAME:{added_at,rotated_at}}` | `keys add/rotate/remove` | endpoint key lookup (after env) | no |
| `port-allocations.json` | `allocations{pod: base}`, 100 ports each from 3000 | pod create/delete | implementer env `DOCKET_PORT_BASE` | no |
| `docket-runs.json` | `runs[{id,source,project,state,taskIds,…}]` | every dispatch | `docket runs`, `/runs` | no (never pruned) |
| `docket-conversations.json` | `conversations[{id,agentId,peerId,topic,status,…}]` | Telegram, `conversations set` | Telegram channel | no |
| `sessions/<key>/session.json` | `messages[]`, `usage{inputTokens,outputTokens,turns}` | every turn | every turn (history, compaction) | no. `maintain sessions` reports sizes. |
| `traces/<pod>/<session>.jsonl` | one event per line `{ts,session_id,agent_role,event_type,payload}` | every turn | `docket trace`, `metrics`, `/traces` | no. `trace expire` prunes after `TRACE_RETENTION_DAYS`. |
| `approvals/<id>.json` | `{token,project,role,action,state,created,context}` | gated calls | the approval wait | no. Answer with `approve`/`deny`. |
| `audit.log` (+ `.1`) | JSONL `{seq,ts,user,pid,action,detail,prev_hash}` | every mutating command | `docket audit`, `audit verify` | **never.** It breaks the hash chain. |

### Per agent (`~/.docket/workspaces/projects/<pod>-<role>/`)

`.docket-meta.json`, with each key and what uses it:

| Key | Used for | Set by |
|---|---|---|
| `model`, `modelSource` | the model this agent calls; whether policy changes follow it | `models`, `profile` |
| `role`, `pod`, `blueprint` | tool narrowing, gate, pipeline choice (Lead) | provisioning |
| `codebase`, `workDir`, `worktreeDir` | the directories tools may touch; verify cwd | provisioning |
| `verifyCmd` | the mechanical gate after this member's hop | `pod set-verify`, `--verify` |
| `budgetUsd`, `paused`, `pausedReason` | pod budget and auto-pause, **Lead only** | `profile --budget`, `--resume` |
| `maxReworkCycles`, `turnTimeoutS`, `verifyTimeoutS` | pod dispatch, **Lead only** | hand-edit (§3.3) |
| `portRangeStart`, `portRangeCount`, `scratchDir` | Implementer environment `DOCKET_PORT_BASE/COUNT`, `DOCKET_SCRATCH_DIR` | provisioning |
| `persona` | the persona block in the system prompt | `persona set/clear` |
| `sessionKey`, `projectKey` | shown by `docket scope`; dispatch builds its own per-task session key | `scope` |
| `templateVersion`, `schemaVersion`, `kind`, `scope`, `stack`, `name`, `description`, `created` | informational. `stack` and `name` fill templates at provisioning | provisioning |

The Markdown files are covered in [§2](#2-how-the-files-reach-a-running-agent) (what reaches the
model) and [§3.2](#32-change-what-an-agent-is-told) (what to edit, and what overwrites it). Only
the Lead has `TASK_LIST.json`, the pod queue. Change it with `docket pod <p> delegate` and
`queue --retry`, never by hand while a dispatch holds a claim.

### Org specialists (`~/.docket/workspaces/{manager,knowledge,security}/`)

These have the same files, minus `TOOLS.md`, `worktree/` and the pod keys. They are shared by
every project. Pod dispatch never uses them. Customize them the same way (§3.2).

---

## 5. Sharp edges

These are true of the current code. Each one is a reason to check a setting's effect instead of
assuming it. Phase 26 in `TODO.md` ([ADR 0008](adr/0008-configuration-contract.md)) schedules a fix
for most of them.

- **`WORKFLOW_AUTO.md` and `memory/` are not in the prompt** (§2). Edit `SOUL.md`/`MEMORY.md`.
- **Existing members keep their provisioned `SOUL.md`.** Changing a role template does not
  re-render them.
- **Tool denials are per role only.** Nothing allows or denies tools per agent or per pod.
- **Some files are skipped silently.** An invalid policy file, schedule spec, model-policy entry
  or overlay role is skipped without a warning. For a `block` policy that means the call is
  **allowed** (§3.6). Test after every edit.
- **The provider display name derives from `--model`.** `models provider add` without `--name`
  labels the entry after `--model` (only the shipped default model id keeps its shipped caption).
  The per-model `name`/`cost`/`reasoning`/`input` fields and the provider block's `api` field are
  display-only — only `id`, `contextWindow` and `maxTokens` drive request routing.
- **A live `warn`/`redact` policy hit is recorded in the audit log** (`docket audit`, action
  `tool.warn`), not in traces — so `docket trace`/`metrics` won't show it.
- **`docket delete` keeps an unmerged branch.** Teardown deletes `docket/<pod>/<member>` when it
  is merged into your current branch; an unmerged one is kept and the command to remove it is
  printed.
