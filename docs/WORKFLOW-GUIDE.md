# Complete Workflow Guide: Pods and Dispatch

**Status:** Production Guide

> **See also:** [Agent Teams (Pods)](AGENT-TEAMS.md) is the canonical reference for docket's
> agent-team model (scope vs. role, the pipeline, isolation). This guide shows that model in
> **end-to-end use** — provisioning a pod, growing it, queueing work, and running the real
> dispatch loop. Read Agent Teams first; read this for the worked examples.

---

## The Two Actors

### 1. Engineer (You)
The human who:
- Creates projects (each becomes a **pod**)
- Sends tasks (CLI `docket task add`, or `/delegate` from a Telegram chat bound to a pod's Lead)
- Reviews diffs and commits the code
- Makes architectural decisions and approves any HITL gates
- Sets budget caps and watches measured token usage

### 2. Project Pods
One **pod per project/codebase**, created with `docket init`. A pod is a small team of
project-scoped agents (`scope: project`) that owns exactly one codebase — never shared with
another project:

- **Lead** (`<project>-lead`) — orchestrates the pod, owns its memory + human (Telegram) comms,
  decomposes work and dispatches it. **Never edits code.**
- **Implementer** (`<project>-implementer`) — runs *inside* the project workspace and writes the code.
- **Reviewer** *(optional)* — read-only veto on the diff (correctness + security gate).
- **Tester** *(optional)* — behaviour-only PASS / FAIL validation.

The default pod is **lean** (Lead + Implementer). Add Reviewer/Tester when the work warrants it.


## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                ENGINEER (You)                        │
│  • queue tasks (CLI or Telegram)  • review diffs     │
│  • set budget caps                • approve gates    │
└────────────────┬─────────────────────────────────────┘
                 │
                 ▼
        ┌──────────────────────────┐
        │  Pod: myapp              │
        │  ┌────────────────────┐  │
        │  │ lead  (never edits)│  │
        │  └─────────┬──────────┘  │
        │            ▼             │
        │  implementer → reviewer? │
        │            → tester?     │  ← `docket run`
        └──────────────────────────┘     one real agent turn per hop
```

Each pod is isolated: its own per-member workspaces (`700`/`600`), its own session-key
namespace (`agent:<project>:…`), its own queue. **There is no cross-pod dispatch path.**

---

## End-to-End: a pod from `init` to committed code

This is the headline workflow — provision a pod, grow it when the work earns it, queue a task,
**dispatch the real pipeline**, then inspect the trace, queue, and cost.

### Step 1 — Provision a lean pod

```bash
docket init myapp ~/code/myapp     # or: cd ~/code/myapp && docket init
# creates two project-scoped agents:
#   myapp-lead          (orchestrator, never edits code)
#   myapp-implementer   (writes code inside ~/code/myapp)

docket pod show             # inspect the pod and its roles
docket status --all         # every pod, its tasks and measured tokens
```

A lean pod is the right default for prototyping and low-risk changes: one owner of completion
(the Lead) and one doer (the Implementer). A repository with a committed `.docket/` gets that team
instead (validated before anything is provisioned, applied after), and `docket init --recipe
secure-build` starts from a shipped recipe; see
[Configuration §3.11](CONFIGURATION.md#311-keep-the-team-in-the-repo).

### Step 2 — Set a budget cap on the Lead

Dispatch is budget-gated against the **Lead's** cap, so set it before you run work:

```bash
docket pod set budgetUsd 5     # cap pod spend at $5 (token-based estimate)
```

Before *each* hop, docket compares the pod's token-based dollar estimate to this cap — docket's
own turn loop reports real, measured token counts but no billed dollar figure, so the gate always
runs off the labelled estimate (`core/dispatch.py`'s `pod_gating_cost`), never a claimed "recorded
spend". Over budget → the task is set to **blocked** and the Lead is paused, never silently
run.

### Step 3 — Grow the pod when the work warrants it

A login bug touching auth deserves a correctness/security gate and independent validation, so
add a Reviewer and a Tester:

```bash
docket pod add reviewer     # adds myapp-reviewer (read-only veto on the diff)
docket pod add tester       # adds myapp-tester  (behaviour-only PASS/FAIL)

docket pod show                   # now: lead, implementer, reviewer, tester
```

> You could have provisioned this up front with `docket init myapp ~/code/myapp --pod full` or
> `--with reviewer,tester`. From outside the repository, `docket pod add reviewer --pod myapp` does the same as
> `docket pod add reviewer` run inside it. The pod also scales doers: `docket pod add implementer` adds
> `myapp-implementer-2` for parallel work. A pod always has **exactly one Lead.**

### Step 4 — Queue a task on the pod

```bash
docket task add "Fix the null-token login crash"
docket task add --priority high "Patch the open-redirect on /auth/callback"
```

The task lands on the pod's own queue (owned by the Lead). Nothing runs yet — `task add` only
queues. Each task gets an id (`task-<uuid>`) and its own per-task trace session
(`agent:myapp:<task_id>`) so tasks never bleed into each other.

### Step 5 — Inspect the queue

```bash
docket task list
```

```
                                Pod queue — myapp
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ID                 ┃ PRI    ┃ STATUS  ┃ COST ┃ DESCRIPTION                               ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ task-6443ff59-cfca │ normal │ pending │    — │ Fix the null-token login crash            │
│ task-9c745f95-984d │ high   │ pending │    — │ Patch the open-redirect on /auth/callback │
└────────────────────┴────────┴─────────┴──────┴───────────────────────────────────────────┘
```

### Step 6 — Dispatch the pipeline (the real hand-off)

```bash
docket run
```

The `docket run` command drives every pending task through the pod's pipeline, highest priority first, **one
real, costed agent turn per hop** — and only through the roles this pod actually has:

```
Lead  →  Implementer  →  Reviewer  →  Tester
```

```
→ Running 2 pending task(s) through: lead → implementer → reviewer → tester
  Pod budget cap: $5.00 (spent $0.00)
verification skipped — verifyCmd not set for myapp-implementer
✓   [task-9c745f95-984d-497b-abdd-1bed9ec9b0b0] done — 4 hop(s)
verification skipped — verifyCmd not set for myapp-implementer
✓   [task-6443ff59-cfca-41a5-9ca0-f8686233e0bf] done — 4 hop(s)
✓ 2 done · 0 failed · <n>k tokens (~$0.00 est.)
→ Next: docket status
```

The summary line's token count is measured; its dollar figure is a labelled estimate, because
docket's own driver never records spend, and the budget gate works on that estimate (Step 2).
The command
exits `1` when a task's run ends `failed`, so `docket run && …` stops there;
`blocked`, `waiting_approval` and `waiting_input` are expected pauses and exit `0`. An unattended
`ask` — under this same `docket run` off a TTY, or under `docket start --dispatch`'s sweep — resolves to
`waiting_approval` without blocking the turn at all (`approvalMode: park`, the default for an
unattended caller); see [SECURITY-SIMPLE.md](SECURITY-SIMPLE.md)'s operator-loop section and
[CONFIGURATION.md §3.15](CONFIGURATION.md#315-notify-a-human-and-answer-without-blocking) for
how a human finds out and answers.

The dispatch orchestrator invokes each hop through its own turn loop
(`core/agent_loop.py`), captures the result, and threads it to the next role. The Lead plans,
the Implementer is the **single writer**, the Reviewer can **veto** the diff, the Tester gives
an independent PASS/FAIL.

### Step 7 — Budget gating in action

Say the pod's estimate crosses its cap partway through a task:

```bash
docket run
```

```
⚠   [task-6443ff59-cfca-41a5-9ca0-f8686233e0bf] blocked — pod budget reached (~$5.02 (estimated — no cost recorded) ≥ $5.00) before implementer
```

Over-budget tasks are blocked **between hops**, not abandoned mid-write, and the pod's Lead is
paused so no further task is claimed. Raising the Lead's cap un-blocks the pod's budget-blocked
tasks and clears the pause; then re-dispatch:

```bash
docket pod set budgetUsd 10
docket run
```

### Step 8 — Inspect the trace

Every hop emits a trace event on the per-task session, so a run is fully auditable with no
manual Telegram relay:

```bash
docket task trace task-9c745f95-984d --tail      # follow one task's session live
docket task trace task-9c745f95-984d              # just this task's pipeline, in order
```

Each line is `timestamp  event_type  (role)` plus any status and cost/duration fields, for
example (abridged):

```
  2026-10-09T10:38:26  session_start              (lead)
  2026-10-09T10:38:26  tool_call                  (lead)  hop=lead
  2026-10-09T10:38:41  llm_call                   (lead)  local-model  in=1900/out=36  [15246ms]
  2026-10-09T10:38:41  tool_call                  (lead)  tool=glob
  2026-10-09T10:38:41  tool_result                (lead)  tool=glob
  ...
  2026-10-09T10:38:58  tool_call                  (implementer)  hop=implementer
  ...
  2026-10-09T10:40:32  session_end                (lead)  status=done
```

The same session is what a trace exporter sends when you enable one: a `docket.session` span
with a child span per model call and per tool call, so Langfuse or an OpenTelemetry backend
shows the pipeline hop by hop. What each span carries depends on the exporter's privacy level,
structure only by default; `docket setup export preview <name> --session <id>` prints it for this
exact session before anything is sent
([Configuration §3.14](CONFIGURATION.md#314-export-traces-to-opentelemetry-or-langfuse)).

### Step 9 — Check the cost

```bash
docket task list     # per-task status (COST is recorded spend, so it reads — today)
docket status                # measured token usage across every agent
```

Token counts are real and measured. Dollar figures are **not** — docket's own turn loop reports
no billed spend, so `docket status` reports "none recorded" for dollars rather than inventing a number.
(The bundled pricing table only powers the budget gate's labelled estimate and `docket setup model`'s
comparative display — docket never projects dollar *savings*.) See
[Cost reporting and its limits](../README.md#the-gate-and-the-record).

### Step 10 — Review and commit

The commit is yours to make — the Implementer wrote the code, but you own the merge:

```bash
cd ~/code/myapp
git diff                  # review the Implementer's changes
git add -p
git commit -m "Fix open-redirect on /auth/callback"
git push
```

The Lead records the outcome in the pod's memory log
(`~/.docket/workspaces/projects/myapp-lead/memory/YYYY-MM-DD.md`).

---

## Autonomous dispatch (opt-in)

`docket run` is a one-shot, run-it-now command. To let docket drain every
pod's queue continuously, run the background loop with the dispatch flag:

```bash
docket start --dispatch    # background: drive every pod's queue on each refresh
```

```bash
docket start               # READ-ONLY monitor — health checks only, never dispatches
```

> Because every hop is a real, costed LLM turn, dispatch is **never silent**: it is either
> explicit (`docket run`) or opt-in (`docket start --dispatch`). Plain `docket start`
> only watches health. Budget caps gate the autonomous loop exactly as they gate a manual
> dispatch — an over-budget pod's tasks are set to `blocked` (not `pending`) and the pod's Lead
> is paused. A blocked task does **not** resume on its own: raise the Lead's cap
> (`docket pod set budgetUsd N`) or run `docket run --resume`, either of
> which unpauses the Lead and unblocks the pod's budget-blocked tasks, or requeue one with
> `docket task retry <task-id>`.
> Leaving them blocked is deliberate — rewriting them straight back to `pending` would let a
> budget-capped task retry forever on every sweep.

---

## Pipelines: the one dialect

Everything in Step 6 above — Lead → Implementer → Reviewer → Tester, one hop per role — is
docket's **built-in pipeline**. It is not hardcoded prose; it is a real, typed pipeline document
(`core/pipeline.py`) that `docket run` runs whenever a pod has no pipeline
file of its own. Writing a pipeline file lets you change the step order, add a parallel fan-out,
or swap in a different gate — without touching pod membership at all.

### Zero migration: nothing changes until you opt in

A pod with no pipeline file behaves **exactly** like `core/dispatch.py`'s hardcoded pipeline
always has: Lead (no gate) → Implementer (mechanical check against its own `verifyCmd`) →
Reviewer (APPROVE/REQUEST-CHANGES, bounded rework back to the Implementer) → Tester
(PASS/FAIL, hard gate, no rework). A lean pod without a Reviewer/Tester simply never reaches
those steps — same skip-absent-roles behavior `docket run` always had.
A pod runs its own pipeline only once you write a file and bind it (`docket pod set pipeline
<file>`) or pass `--pipeline`.

### `docket pod validate` — check a file before you point a pod at it

Pure structural validation, no project or pod involved. Every level of the document rejects an
unrecognized key — a typo fails loudly instead of being silently ignored:

```bash
$ docket pod validate workflows/release.yml
✓ workflows/release.yml (pipeline release)

$ docket pod validate workflows/broken.yml
✗ workflows/broken.yml:1 steps.0.verifyCommand: Extra inputs are not permitted
```

### `docket pod plan` — see what would actually run, without running it

`plan` renders straight from the real executor (`core.orchestrator.resolve_plan`/`render_plan`)
— never a second, drift-prone pretty-printer, and never a token spent:

```bash
$ docket pod plan

Pipeline plan — myapp
Source: built-in default

Pipeline: default
  [lead] role=lead -> myapp-lead [gate: none]
  [implementer] role=implementer -> myapp-implementer [gate: mechanical(verifyCmd)]
  [reviewer] role=reviewer -> myapp-reviewer [gate: verdict(approve, rework->implementer)]
  [tester] role=tester -> myapp-tester [gate: verdict(pass)]
```

A lean pod (no Reviewer/Tester) shows those two lines marked `(skipped — role not in pod)`
instead of a resolved member id — `plan` always renders every step the spec declares, it just
tells you honestly which ones this pod's current roster can run.

### A custom pipeline: parallel fan-out, bounded rework, a human sign-off

You already scaled myapp's Implementer for parallel work (`docket pod add implementer`
→ `myapp-implementer-2`, mentioned above). A pipeline file is how you actually put both
implementers to work on one task, then require a human OK before the fix ships instead of an
automated PASS/FAIL:

```yaml
# ~/code/myapp/workflows/release.yml
name: release
description: Fan the fix out across both implementers, then require a human OK before it ships.

steps:
  - id: plan
    role: lead

  - id: fanout
    parallel:
      - id: impl-a
        agent: myapp-implementer
      - id: impl-b
        agent: myapp-implementer-2

  - id: review
    role: reviewer
    gate:
      type: verdict
      pattern: "^(APPROVE|REQUEST-CHANGES)\\b"
      passValues: [approve]
      rework:
        to: fanout
        when: [request-changes]
        maxCycles: 2

  - id: ship
    role: tester
    gate:
      type: approval
      message: "Tests passed — ready to deploy?"
```

```bash
$ docket pod plan --pipeline workflows/release.yml

Pipeline plan — myapp
Source: file 'workflows/release.yml'

Pipeline: release
  [plan] role=lead -> myapp-lead [gate: none]
  [fanout] parallel:
    - myapp-implementer -> myapp-implementer [gate: none]
    - myapp-implementer-2 -> myapp-implementer-2 [gate: none]
  [review] role=reviewer -> myapp-reviewer [gate: verdict(approve, rework->fanout)]
  [ship] role=tester -> myapp-tester [gate: approval]

$ docket run --pipeline workflows/release.yml
```

`docket run --pipeline` uses the exact same rendering, run-registry
recording, budget/approval gating, retries, and crash resume as a plain `docket run`.
`--pipeline` only swaps which `PipelineSpec` is walked; nothing else about how a hop runs changes,
including the exit status: `1` when a task's run ends `failed`.

Three gate kinds, plus one step kind that isn't a gate at all — it doesn't judge a hop's output,
it asks a question before one runs — and what each does to the task:

| Gate | Where it shows up | On failure |
|---|---|---|
| `mechanical` | Implementer's `verifyCmd` by default (or a `command` you set) | Task → **failed**, a `verification_failed` trace event, no advance to the next step. An unset command is never silently skipped — it prints `verification skipped — verifyCmd not set for <id>` and emits its own trace event |
| `verdict` | Reviewer's APPROVE/REQUEST-CHANGES (bounded rework), Tester's PASS/FAIL (hard gate) | A rejected/unparseable verdict past the rework budget → task **failed**. Rework re-runs the named earlier step, up to `maxCycles` |
| `approval` | A pipeline `approval` step, or a pod-level `requireApprovalRoles` list | Task → **waiting_approval** — the hop doesn't run at all until a human decides. See [SECURITY-SIMPLE.md](SECURITY-SIMPLE.md) for the approval channels |
| `input` (not a gate — no hop runs) | `- ask: {input: {from: <step-id>}}`, or the richer per-question schema a Lead's own typed intake brief supplies (the `intake` recipe) | Task → **waiting_input** — a question, not a permission. Routes on `answered`/`declined` via the step's own `on:` map. Answer with `docket task answer <task-id>`; unanswered past its deadline → **blocked** (`blockedReason: "input_expired"`), never failed. See [CONFIGURATION.md §3.15](CONFIGURATION.md#315-notify-a-human-and-answer-without-blocking) |

### Declared variables — interpolated into step instructions

A pipeline can declare `variables` (defaults, descriptions, `required`). A step's own
`instructions` text can reference one with `${name}`, and it is substituted from the run's
resolved variable namespace before that hop runs:

```yaml
steps:
  - id: deploy
    role: implementer
    instructions: "Deploy to ${env}, then verify the health check."
```

```bash
$ docket run --var env=staging
```

`--var key=value` is repeatable and works from `docket run`; the `docket start` webhook
resolves the same namespace from its JSON body. Either way, resolution happens once, up front: a
`required` variable with no value supplied is rejected before a run record is even created, and if
any step's `instructions` still reference a `${name}` the resolved namespace doesn't cover, the
whole run refuses before any hop starts rather than sending a literal `${name}` to a model. The
resolved namespace is persisted on the run record (`docket task show <id>`), so you can see exactly
what a dispatch saw.

---

## The run registry, `--progress`, and cancellation

Every dispatch invocation — CLI, the `docket start` webhook, a due schedule, the `--dispatch` sweep loop,
or an MCP client — writes one record to a persisted run registry, so "is it done, did it fail, or
did it never run" has an answer instead of vanishing behind a fire-and-forget thread:

```bash
$ docket task show task-9c745f95-984d     # the task's hops, evidence and every run that carried it
$ docket task show run-3f2a1c9e-... --json # a non-interactive exec run, by its run id
$ docket task list --pod myapp --json      # for scripting/dashboards
```

`--progress` on `docket run` shows hop-by-hop progress live instead of only the final summary:

```bash
$ docket run --progress

  2026-07-29T10:02:00  tool_call                  (lead)
  2026-07-29T10:02:05  tool_result                (lead)
  2026-07-29T10:02:05  tool_call                  (implementer)
  ...
```

Ctrl-C stops *watching only* — the dispatch keeps running and recording in the background,
exactly like closing a `tail -f` window doesn't kill the process being tailed.

A run stuck mid-hop can be asked to stop:

```bash
$ docket task cancel task-9c745f95-984d
✓ requested cancellation for run run-3f2a1c9e-... (1 process group(s) killed)
```

`cancel` records one durable request before killing an in-flight hop's **whole process group**, not
just the immediate child (it may have shelled out further). Queued work is cancelled immediately.
Running work remains visibly `running (cancel requested)` until its executor observes the request
and fully returns; only then are the task and run terminal `cancelled`. An in-process model/backend
call already executing is not forcibly aborted, but its late response is discarded at the next
safe checkpoint and no later tool or pipeline hop starts. `docket task show` and its JSON form
expose the request, observation, and stop timestamps. A genuine cancellation writes one
`runs.cancel` audit entry naming the run, its project, its pre-cancel state, and how many process
groups were killed. A task still marked `running` whose dispatcher is gone is settled as `failed`,
ready for `docket task retry`. Cancelling a task with nothing in flight changes
nothing and writes no audit entry — but it still exits `1`, printed as an error
(`Task <id> is <status>`), not a silent success; "no-op" describes its side effects, not
its exit code.

---

## Scheduling and webhooks (unattended dispatch)

Two ways to trigger a pod's pipeline without a human typing `docket run`:

### Schedules — cron, a daily time, or a fixed interval

Schedules live in `~/.docket/docket-schedules.json`. Set one with `docket pod set
schedule "<spec>"` — it validates the spec and writes the file for you; `docket pod unset
schedule` removes the entry. The file's shape:

```json
{
  "schedules": {
    "myapp": "@every 30m",
    "otherapp": "09:00",
    "athird": "*/15 9-17 * * 1-5"
  }
}
```

Three formats: `@every <N>s|m|h`, a daily `HH:MM` (UTC), or a standard 5-field cron expression
(`minute hour dom month dow`, UTC, numeric only — no `MON`/`JAN` name aliases). A schedule is
checked at most once per matching minute and **only while `docket start --dispatch` is running**
— plain read-only `docket start`, or no `docket start` at all, never fires one. Each due project
gets its own run record (`source: "schedule"`), so a scheduled dispatch is exactly as inspectable
via `docket task list` as a manual one. An invalid spec (however it got into the file) is never treated
as silently never-due: the sweep logs `schedule '<project>' skipped — <reason>` once per sweep
instead of dropping it quietly; `docket setup` reports the same problem outside of `docket start`.

### Webhooks — trigger from CI or any external system

`docket start` always exposes `POST /dispatch/<project>` (bearer-token authenticated), independent
of `--dispatch` — a webhook call is an explicit request, not part of the passive monitor loop:

```bash
TOKEN=...   # printed at `docket start` startup, or $DOCKET_SERVE_TOKEN

curl -s -H "Authorization: Bearer $TOKEN" -X POST \
  -H "Content-Type: application/json" -d '{"env": "staging"}' \
  http://127.0.0.1:7331/dispatch/myapp
# {"ok": true, "run": "run-3f2a1c9e-...", "project": "myapp", "status": "dispatched"}

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:7331/runs/run-3f2a1c9e-... | jq .
```

The JSON body is resolved against the pod's own configured/default pipeline's declared
`variables` **before** a run record is even created, exactly like `--var` on `docket run`
(see the section above): a missing `required` variable is rejected with `400` and no run record is
created at all; an unresolved `${name}` in a step's `instructions` also refuses the run before any
hop starts. The resolved namespace is persisted on the run record (`docket task show <id>` shows
it), so you can answer "what did this dispatch actually see". The webhook always uses the pod's own
pipeline; it has no way to supply a `--pipeline` of its own, only variable *values*.

---

## One queue: per-pod dispatch

There is no org-level task queue. **Per-pod dispatch is the only queue:**

| | **Per-pod dispatch** |
|---|---|
| Command | `docket task add`, `docket task list`, `docket run` |
| Scope | one project's pod |
| Runs code? | yes — Implementer writes inside the project workspace |
| Isolation | pod-local; no cross-pod path |

Use it for "do this work in *this* codebase":

```bash
docket task add "Add a contact form to the homepage"
docket run
```

### Looking across pods

There is **no command that runs one pod's work from another pod.** To see across pods (where to focus, what to rebalance or pause), use:

```bash
docket status --all              # every pod: tasks, tokens, outcomes
docket inbox                     # every pod that needs you, in one place
```

Then queue tasks and run each pod individually:

```bash
docket task add "..." --pod myapp
docket run --pod myapp
```

---

## Composing a team — how big should a pod be?

Start lean; grow only when the work earns it.

| Situation | Pod |
|-----------|-----|
| Prototyping, low-risk changes, solo project | **lean** (Lead + Implementer) — the default |
| Code that needs a correctness/security gate before it lands | add a **Reviewer** (`--with reviewer`) |
| Behaviour you want validated independently of the diff | add a **Tester** (`--with tester`) |
| Production-grade, regulated, or high-blast-radius work | **full** pod (`--pod full`) |
| One Implementer is the bottleneck | `docket pod add implementer` (parallel doers) |

The Reviewer and Tester are the line between "an agent changed the code" and "a change was
reviewed and validated before it landed."

---

## Pod configuration

### Pod dispatch settings — `docket pod show`

A pod's dispatch behavior is sixteen typed keys on the Lead's meta, read/written through one
generic command instead of hand-editing files: `budgetUsd`, `maxReworkCycles`, `turnTimeoutS`,
`verifyTimeoutS`, `approvalMode`, `approvalExpiryHours`, `inputExpiryHours`, `allowCommands`,
`pipeline`, `schedule`, `projectInstructions`, `mcpServers`, `deniedTools`, `requireVerify`,
`maxConsultationsPerTask`, `network`. A repository's `.docket/pod.yaml` can carry the same keys under
`settings:`, applied by `docket init` or `docket pod apply`.

```bash
docket pod show                    # every key, with its source (default vs. set)
docket pod show --json             # same, machine-readable
docket pod set budgetUsd 5
docket pod unset budgetUsd
```

Every write is validated before it's stored (bad type, out-of-range, or an unknown key refuses
the write) and audited as `pod.config`; a value that somehow ends up malformed in storage refuses
dispatch rather than being silently coerced, naming the key. `pipeline` and `schedule` are
validate-then-store: `pod set pipeline <file>` checks the file and writes a hashed copy into
the pod's own workspace before recording it, and `pod set schedule "<spec>"` validates the cron/
interval spec the same way (see "Schedules" above). Binding a pipeline this way makes it the
**default for every trigger** — CLI dispatch, the `docket start` webhook, a due schedule — whereas `docket
run --pipeline <f>` only swaps the spec for that one invocation. See
[CONFIGURATION.md](CONFIGURATION.md) for the full reference on every key.

To check what will actually run for a given agent before you dispatch, `docket pod show
<agent-id> [--json]` reports its effective configuration with provenance (policy vs. pinned model,
which pod settings are in play, and where each came from).

### What makes a pod member

Each member is an ordinary registered agent with its **own** permission-locked workspace, so
`docket status --all` and `docket setup` cover every member for free.

```
~/.docket/workspaces/projects/myapp-implementer/
├── SOUL.md              # identity + scope + session key
├── AGENTS.md            # session protocol, role boundaries
├── TOOLS.md             # project-specific commands (Implementer, when ports or verify are set)
├── HEARTBEAT.md         # active tasks/decisions
├── MEMORY.md            # curated long-term memory
├── WORKFLOW_AUTO.md     # startup contract for reading the workspace by hand
├── .docket-meta.json    # docket metadata (role, codebase, model, sessionKey, projectKey)
└── memory/
    └── 2026-06-24.md    # daily log
```

### Session keys & isolation

Pod members share the project's session-key namespace (`agent:myapp:<key>`), which keeps the
pod's conversation context together and **isolated from every other project**. Dispatch runs
each task on its own per-task session (`agent:myapp:<task_id>`).

The load-bearing isolation primitive is the **per-member workspace** — session keys isolate
conversation; separate workspaces isolate files, memory, and identity.

### Per-role model policy

Each role maps to the **cheapest model adequate for its workload**. Change a role once and every
policy-following agent re-resolves; override per-pod with a role overlay or per-step with `model:` in the pipeline.

| Role | Default class |
|------|---------------|
| Lead | cheap (coordination) |
| Implementer | strong (reasoning-dense) |
| Reviewer | cheap |
| Tester | cheap |

```bash
docket setup model                                   # show the role→model policy
docket setup model set implementer anthropic/claude-… # re-resolves every policy-following Implementer
```

Models come from the role policy, a pod role overlay, or a step's `model:` in the pipeline.

---

## Engineer's daily workflow

### Morning

```bash
docket status --all              # every pod member
docket setup                   # health check (add --fix to repair drift)
```



### Assign and run work

```bash
# Queue and run a single project's work:
docket task add "Add contact form to homepage"
docket run

# Or let the background loop drain every pod's queue:
docket start --dispatch
```

You can also queue work from Telegram: bind the Lead once with `docket setup notify bind myapp-lead`, run
`docket start --telegram`, and send `/delegate <task>` in that group. The task lands on the same
pod queue and the reply is its task id, not the pipeline's output. Plain messages are refused;
the only verbs are `/approve`, `/deny`, `/status`, `/delegate` and `/answer <task-id> <text>` (for
a parked question). This bot only ever replies to a message it received — it never messages the
group first. Pushing a notification into the group instead is a separate, opt-in mechanism
(`docket setup notify enable telegram --set actors=<chat-id>`, §3.15 in CONFIGURATION.md), scoped to
the chat ids you explicitly list, never every wired binding.

### Monitor

```bash
docket task list          # this pod's queue + per-task status/cost
docket task trace <task-id> --tail   # follow one task's trace session
```

### Review and commit

```bash
cd ~/code/myapp
git diff
git add -p && git commit -m "Feature: contact form" && git push
```

### End of day

```bash
docket status                     # measured token usage across the fleet
docket setup                   # any alerts?
```

---

## Token & cost notes

These are **token** estimates — the thing docket's routing actually controls. Dollars are only
ever estimated: the budget gate uses a labelled token-based estimate and `docket setup model` shows
comparative pricing; `docket status` reports measured tokens and no recorded spend, so we don't
project dollars here. See
[Cost reporting and its limits](../README.md#the-gate-and-the-record).

A dispatched task is the sum of its hops, each a real costed turn:

```
Simple change (lean pod, 2 hops):
  lead         ~2K   (plan + decompose, cheap model)
  implementer  ~2K   (small edit, strong model)
  ── total    ~4K · ~2 min

Feature (full pod, 4 hops):
  lead         ~5K
  implementer ~20K   (multi-step logic, strong model)
  reviewer     ~5K   (veto on diff)
  tester       ~3K   (PASS/FAIL)
  ── total   ~33K · ~10 min

Refactor (full pod, high blast radius):
  lead        ~10K
  implementer ~50K   (multi-file)
  reviewer    ~10K   (security-critical)
  tester       ~5K
  ── total   ~75K · ~20 min
```

To bound the dollar cost of any of these, set a per-pod cap on the Lead
(`docket pod set budgetUsd <usd>`) and watch measured tokens with
`docket status`; a hop that would cross the cap leaves the task blocked with the estimate in its
reason (`docket task list`). The cap is enforced between hops on every dispatch.

---

## Troubleshooting

Pod/dispatch and Telegram issues (including "pod not running a queued task" and
"pipeline stops after the Implementer") are all covered in
**[troubleshooting.md](troubleshooting.md)**'s "Pods & Dispatch" and "Agents Not Responding in
Telegram" sections — kept in one place rather than duplicated here.

---

## Summary

**Project pods** (`scope: project`, one per codebase):
- Lead orchestrates and owns comms — **never edits code**.
- Implementer is the **single writer**, inside the project workspace.
- Reviewer/Tester are optional gates you add when the work warrants it.
- `docket task add` queues; `docket run` runs the real pipeline,
  one costed turn per hop, **budget-gated, traced, and pod-local**.

**Engineer:**
- Queues tasks, runs the pipeline, reviews diffs, commits, approves gates.

```
task add → run → Lead → Implementer → (Reviewer) → (Tester) → you review + commit
```

**Pipelines** (`docket pod validate`, `docket pod plan`, `docket run`):
- The docket-native pipeline is the dialect the system executes; a pod with no pipeline file runs the built-in one unchanged.
- Every dispatch — CLI, `--progress`, a schedule, a webhook, or the sweep loop — lands one record
  in the run registry; `docket task cancel` kills an in-flight hop's process group for real.

**Key guarantees:**
- One owner of completion (Lead) and one doer (Implementer) — no two-doer ambiguity.
- Per-member workspaces — no worker agent ever serves two projects.
- Real hand-off — the pipeline actually runs; every hop is costed, budget-gated, and traced.
- No cross-pod dispatch — one pod can never run another pod's agents.

---

**Next:** Read [Agent Teams (Pods)](AGENT-TEAMS.md) for the canonical model, or
[QUICK-START-DOCKET.md](QUICK-START-DOCKET.md) to run your first pod.
