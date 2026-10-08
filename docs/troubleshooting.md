# Troubleshooting Guide

## Agents Not Responding in Telegram

### Symptom
Agents don't respond to messages in Telegram groups, even though they're registered and wired.

### Common Causes

#### 0. **It isn't a chat**
docket's inbound Telegram bot is inbound-only and understands exactly five verbs: `/approve`,
`/deny`, `/status`, `/delegate <task>`, and `/answer <task-id> <text>` (for a parked question).
Plain prose is refused by design, this bot never messages a chat first, and `/delegate`/`/answer`
answer with a task id or a confirmation, never the pipeline's output. Use `docket pod <p>
queue`/`docket task trace --tail` to see results. A *push* notification into the chat is a separate,
opt-in mechanism — the `telegram` channel (`docket setup notify enable telegram --set
actors=<chat-id>`) — scoped to the chat ids you explicitly list; it never turns on by itself and
never replaces the five verbs above.

#### 1. **Invalid Model Name**

**Error you might see:** `HTTP 404 from https://api.anthropic.com/v1/...: model not found` (or
similar — the exact text comes straight from the model provider's error response, since docket's
own turn loop calls the endpoint directly and does not pre-validate model names against a
catalog).

**Root cause:** a stale or misspelled model id in an agent's `.docket-meta.json` (e.g.
`haiku-3-5` instead of `haiku-4-5`).

**How to diagnose:**
```bash
docket pod show <agent-id>      # the agent's resolved model
docket setup model               # the role-to-model mapping
```

**How to fix:**
```bash
# Re-resolve all policy-following agents at once
docket setup model preset anthropic

# Or change one role's model across all its members
docket setup model set reviewer anthropic/claude-opus-4-6
```

> **Never edit an agent's `.docket-meta.json` model field directly** — use `docket setup model`
> so the change is validated, applied consistently, and audit-logged.

**Valid model names (Anthropic defaults):**
- `anthropic/claude-haiku-4-5` (cheap class — manager, reviewer, tester, knowledge)
- `anthropic/claude-sonnet-4-6` (strong class — programmer, security, repo)
- `anthropic/claude-opus-4-6` (strong class, premium)

Check the live mapping anytime with `docket setup model`.

#### 2. **Missing Telegram Bindings**
**How to fix:**
```bash
docket setup notify bind <agent-id>
```

#### 3. **Unbound / unauthorized chat**
Since docket owns the Telegram bot itself, the `docket setup notify bind` binding **is** the entire
authorization boundary — there is no separate daemon-side allowlist to also configure. A message
from a chat that isn't bound to an agent gets a plain refusal, and the attempt is audit-logged
(`telegram.unauthorized`) rather than silently dropped.

**How to diagnose:**
```bash
docket log | grep telegram.unauthorized
```

**How to fix:**
```bash
docket setup notify bind <agent-id>
```

#### 4. **The Telegram poller isn't running, or no bot token is stored**
Telegram is docket's own bot (ROADMAP Phase 19 P19-8) — there is no external gateway process to
be "down." Two things have to both be true for a wired chat to get an answer:

**How to diagnose:**
```bash
docket setup provider list                    # is TELEGRAM_BOT_TOKEN stored?
# and: is a `docket start --telegram` process actually running?
```

**How to fix:**
```bash
docket setup provider add TELEGRAM_BOT_TOKEN --credential  # if not already stored
docket start --telegram             # or: docket start --dispatch --telegram
```

## High Costs / Context Bloat

### Symptom
A session accumulates an unusually large context, or an agent's turn count keeps climbing.

### Root Cause
docket's turn loop keeps a growing message history for a session across turns. With enough turns,
cached/re-sent context grows — the same shape of problem any long-lived chat session has.

### Solutions

#### 1. **Reset Agent Sessions**
```bash
# Reset a pod member's session: distills memory, clears context, rebuilds workspace
docket pod reset <agent-id>
```

#### 2. **Switch to a cheaper model policy**

Set the whole fleet to a lower-cost provider preset:

```bash
# Switch the role policy for all agents at once
docket setup model preset openrouter-free
```

See `docket setup model` for the current role→model table and all available presets.

#### 3. **Monitor token usage**
```bash
docket status
docket status  # All agents
```
Token counts here are real and measured; the dollar column is not — docket's own turn loop
reports no billed spend today. See
[Cost reporting and its limits](../README.md#the-gate-and-the-record).

#### 4. **Check the per-turn context footprint**
`docket setup --fix` estimates the tokens re-sent every turn from the files that
actually get re-injected (SOUL.md, AGENTS.md, TOOLS.md, HEARTBEAT.md, MEMORY.md) and warns when
they exceed the configured budget:
```bash
docket setup --fix
# ⚠ Context footprint: ~7,400 tok re-sent each turn (budget 6,000 via default) — trim MEMORY.md/HEARTBEAT.md
```
The budget itself scales with the model's registered context window (`via window`), not a flat
number — `via default` is the 6,000-token floor used when no larger window is registered.
If it's over budget, summarize the daily logs into MEMORY.md and archive them instead of letting
`memory/` grow unbounded:
```bash
docket pod reset <agent-id>
```

#### 5. **A single turn is running away**
docket's own turn loop bounds every turn: a hard cap on model round-trips
(`AGENT_LOOP_MAX_ITERATIONS`, default 20), a hard cap on total tool calls
(`AGENT_LOOP_MAX_TOOL_CALLS`, default 40), a wall-clock timeout
(`AGENT_LOOP_WALL_CLOCK_TIMEOUT_S`, default 300s), a measured-token budget
(`AGENT_LOOP_TOKEN_BUDGET`, default 100,000), and a cap on consecutive denied tool calls
(`AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS`, default 3). These are deliberate stop conditions, not
throughput knobs — if you're hitting one legitimately, override it via its environment variable
rather than assuming something is broken.

## Model / Endpoint Errors

### "no endpoint configured for this model"
**Cause:** `edges/adapters/llm.py`'s `resolve_endpoint` couldn't find a base URL for the model's
provider — no `DOCKET_LLM_BASE_URL`, no registered global document, and the provider isn't one of
the built-in catalog documents (`docket setup provider list`). Every built-in document has a
mapping now — not only OpenRouter (`openrouter/...`) and Vercel AI Gateway (`ai-gateway/...`), but
also `anthropic`, `openai`, `google`, `groq`, `mistral`, `deepseek`, `xai`, `cerebras`, `together`,
`ollama`, `lmstudio` and `local` — so this now means an arbitrary hosted prefix outside that set.

**Fix:** for a built-in provider, apply the matching preset (`docket setup model preset <name>`) and
store its credential — no separate registration needed. For any other hosted or local server,
register it first (`docket setup provider add <file.yaml>`, or the shortcut `docket setup model
provider add <name> <base-url>`). A credential authenticates a known endpoint; it cannot supply a
missing URL.

### "⚠ `<CREDENTIAL>` is missing (HTTP 401)" after `provider add`
**Cause:** registration probes `<base-url>/models` with the resolved credential and classifies
the response rather than refusing outright — a 401/403 still registers the provider, with this
warning naming the missing or rejected credential (model-profiles.spec.md, "Provider readiness"
3). For example:

```
$ docket setup provider add mygw https://api.example.com/v1 --model gpt-4 --credential MYGW_API_KEY
→ Checking the endpoint is alive: https://api.example.com/v1/models
→ Registering provider 'mygw'
✓ Provider wired: mygw  ->  https://api.example.com/v1
⚠ MYGW_API_KEY is missing (HTTP 401)
  Store it: docket setup provider add MYGW_API_KEY --credential
```

**Fix:** `docket setup provider add <CREDENTIAL> --credential`, then confirm with `docket setup provider show <name>`
(or `--json`) — it names the resolved scope, dialect, base URL and which credential name the
provider expects. `docket pod show <agent-id> --json`'s `provider.credential.source` shows
whether a given agent actually resolved that credential (`env`/`store`) or not (`none`).

### "cannot reach `<url>`: ..." / "timed out after Ns calling `<url>`"
**Cause:** the configured endpoint (hosted or local) isn't reachable — wrong URL, the local
server isn't running, or a network/firewall issue.

**Fix:** confirm the endpoint is up (`curl <base-url>/models`), check for typos from
`docket setup provider add`, and re-run.

### "HTTP 4xx/5xx from `<url>`: ..."
**Cause:** the provider itself rejected the request — most commonly an invalid model id, an
invalid/expired API key, or a context-length overflow. The detail text in the error is the
provider's own response body, truncated to 500 characters.

**Fix:** see "Invalid Model Name" above for a bad model id; `docket setup provider rotate <KEY>` for a bad
credential; `docket pod reset <agent-id>` if the context has grown
past what the model accepts. On a small-context endpoint the usual overflow is tool output: lower
`DOCKET_TOOL_MAX_OUTPUT_CHARS` (default 30,000 characters per tool result; about 2,500 suits a
16k-token window).

## Trace Export

### Traces arrive in Langfuse, but Input and Output are empty
**Cause:** the exporter is at `privacy: minimal`, the default for every built-in. It sends the
run's structure (model and tool names, timing, token counts, pass or fail) and none of its
content, so Langfuse has nothing to put in those columns. This is the intended default, not a
lost field.

**Fix:** decide what that destination may receive, then widen it deliberately:

```bash
docket setup export privacy langfuse               # what leaves today
docket setup export preview langfuse --level conversation   # what would leave, without sending it
docket setup export privacy langfuse conversation  # lists the new classes and asks
```

`actions` adds tool arguments and error text; `conversation` adds prompts, replies and tool
results, and gives the trace itself the task as its Input and the last answer as its Output;
`full` adds the system prompt, when the turn has one (a `docket exec` workspace composes
none). The next session shows the content. An earlier one
cannot: content is captured only while an exporter grants it.

### A level change has no effect
**Cause:** export pipelines start once per process. A running `docket start --dispatch` keeps
the exporters and levels it started with, narrowing included.

**Fix:** restart `docket start` after `docket setup export enable`, `disable` or `privacy`. A
one-shot `docket run` or `docket exec` picks the change up at once.

### Nothing arrives at the destination
**Cause:** the exporter is disabled, its credential no longer resolves (then it is skipped
silently at the start of a turn), or deliveries are failing.

**Fix:** `docket setup export list` shows whether it is enabled; `docket setup export show <name>`
shows its `exported`/`dropped`/`failed` counters and last error; `docket setup export test <name>`
re-probes the endpoint without changing anything; `docket setup` warns about an enabled
exporter with a failure since its last success. Check that `DOCKET_NO_EXPORT` and
`DOCKET_NO_TRACE` are unset.

## Permission Denied Errors
**Fix:**
```bash
docket setup --fix
```

This fixes:
- Workspace permissions (700 for dirs, 600 for files)
- Missing workspace files and memory directory
- Missing fleet registration

## Telegram Issues

### Bot Not Receiving Messages
**Diagnose:**
```bash
# Is the bot actually in the group?
# Is TELEGRAM_BOT_TOKEN stored?
docket setup provider list

# Is a docket start --telegram process actually running?
# (docket has no separate gateway process or log to check instead)
```

### Messages Not Being Sent
Since docket owns the Telegram integration directly, a send failure surfaces in whatever terminal
is running `docket start --telegram` (or in `docket log`/`docket task trace` for the triggering
action), not in a separate daemon log.

**Fix:**
```bash
# Confirm the poller is actually running
docket start --telegram

# Re-wire agent
docket setup notify unbind <agent-id>
docket setup notify bind <agent-id>
```

## Session/Scope Issues

### Agent Accessing Wrong Project
**Symptom:** Agent mentions files from other projects

**Cause:** The agent's workspace points at the wrong codebase.

**Fix:**
```bash
docket pod show <agent-id>      # check the codebase path and session key
```

## Pods & Dispatch

### `docket run` does nothing / "No pending tasks"
There's nothing queued for the pod to run.
```bash
docket task add <task>     # quote only when shell metacharacters require it
docket task list               # check what's pending
```

### A dispatched task stays "blocked" (budget cap reached)

Dispatch checks the pod's token-based dollar estimate against the Lead's budget cap before
*every* hop (docket's own turn loop reports no billed spend, so the gate always runs off this
estimate). Once the cap is reached, the task is left `blocked` (never silently retried or
rewritten back to `pending`) **and the pod's Lead is marked paused** — every further claim
against this pod is refused outright (`paused_refused`) until the pause is explicitly cleared,
not just re-blocked hop by hop:

```bash
$ docket run
  [task-c410e91a-...] blocked — pod budget reached ($5.12 ≥ $5.00) before implementer
```

Check the estimated spend, then either raise the cap or resume from the pause. Resuming a pod's
Lead also un-blocks every `blocked` task in that pod at once:

```bash
docket status                    # see measured token usage
docket pod set budgetUsd <N>    # raise the cap (USD), if the spend is expected
docket run --resume        # clear the auto-pause + unblock the pod's queue
# → Unblocked 1 budget-blocked task(s) in pod 'myapp'.
# ✓ Resumed 'myapp-lead' — auto-pause cleared.
```

To retry a single blocked task without touching the pod-wide pause, use `docket task list
--retry <task-id>` instead — it moves just that task back to `pending`.

### A dispatched task stays "waiting_approval" and nobody seems to have noticed

**Cause:** a gated tool call parked. Under `serve --dispatch`'s sweep or a non-interactive
`docket run` (an unattended caller resolves an unset `approvalMode` to `park`), an
in-turn `ask` no longer blocks the hop — it records the exact call and parks the task
immediately, so it never shows up as a long-running turn. Nothing pushes this at you unless a
delivering notification channel is enabled. `console` is on by default but sends nothing, so with
nothing else enabled a parked task waits unseen until `docket inbox`; `docket setup` warns about
exactly this.

**Fix:**

```bash
docket inbox                              # everything across every pod that needs you, right now
docket task approve <token>                    # grant it -- the exact same hop re-runs, once
docket task deny <token>                       # deny it -- the task fails with approval_denied
docket setup notify enable desktop            # this machine; or webhook/ntfy/telegram/email
```

Left unanswered, a parked approval expires after the pod's `approvalExpiryHours` (24h by
default) and denies on its own — it is not a silent forever-wait, but 24h is a long time to
discover one by accident. Granting it does not skip ahead: the exact hop that parked re-runs,
carrying a single-use pre-grant so the model's identical next call passes without asking twice.

### A dispatched task stays "waiting_input"

**Cause:** a pipeline `input` step (or a Lead's own typed intake brief marking `NEEDS-INPUT`)
asked a real question, not a permission — this is a different state from `waiting_approval` even
though both read as `INPUT_REQUIRED` over the MCP/A2A surfaces.

**Fix:**

```bash
docket task answer <task-id>                     # see the question (and any brief/earlier answers); on a
                                           # TTY, prompts and answers it in one step
docket task answer <task-id> "<answer>"                    # non-interactive, single-property question
docket task answer <task-id> --field name=value ...        # non-interactive, multi-property question
```

An unanswered question past its own deadline moves the task to `blocked`
(`blockedReason: "input_expired"`), never `failed` — `docket task retry <task-id>`
re-queues it once you're ready to answer.

### A dispatched task fails with "verification_failed" / the verify command failed

The Implementer's hop is gated on its `verifyCmd` (if one is set — see `docket pod add
--verify`/`docket pod set verify`). A non-zero exit from that command moves the task to `failed` with a
`verification_failed` trace event; it is **not** retried automatically (only a
timeout or an endpoint hiccup on the *agent turn* itself is retried — a real, deterministic
non-zero exit or a bad verdict never is). Inspect the recorded output and either fix the
underlying failure or clear/adjust the gate:

```bash
docket task trace --tail                       # see the verify command's (redacted) output
docket pod set verify "npm test" --member <p>-implementer   # change the gate command
docket task add <task>              # re-queue once you believe it will pass
```

The command runs in the Implementer's git worktree when one exists, otherwise the pod's shared
codebase root — if it's failing only because it ran in the wrong directory, that's the first
thing to check.

### A task fails with "tester reported FAIL" (or an unparseable verdict)

The Tester gate is a structural PASS/FAIL parse: exactly one distinct `PASS` or `FAIL` marker at
the start of a non-blank line of its reply. `FAIL`, no marker, or both markers
(`tester_verdict_failed`) fails the task outright —
there is no rework cycle for a Tester verdict (only a Reviewer's `REQUEST-CHANGES` gets one):

```bash
$ docket run
  [task-91a2c410-...] failed — tester reported FAIL
```

Read the Tester's full reply via `docket task trace --tail`, fix the underlying issue, then queue it
again (`queue --retry` only moves a `blocked` task back to `pending`, not a `failed` one):

```bash
docket task add <task>
```

### "pod has no lead — cannot dispatch"
The pod is missing its Lead. A pod must have exactly one Lead, which orchestrates dispatch.
Add one back (only a *second* Lead is refused):
```bash
docket pod add lead
```

### A pod member wasn't created
Inspect the pod and run diagnostics to find and fix the gap:
```bash
docket pod show     # list the pod's members and status
docket setup      # system-wide diagnostics (add --fix to repair drift)
```

### Implementer touching the wrong project?
Check its session key:
```bash
grep "Session Key" ~/.docket/workspaces/projects/<p>-implementer/SOUL.md   # verify identity
```

## Memory & Context

There is no per-agent `SNAPSHOT.md` or `.memory-index.json`, and there is no separate semantic memory
index: docket's own turn loop has no `memory_search` tool of its own, so an agent searches
its memory files with the same `read`/`grep` tools it uses for anything else. The real per-agent
memory contract is: `WORKFLOW_AUTO.md` (the startup contract for reading the workspace by hand; a docket
turn composes its own startup contract instead), `HEARTBEAT.md` (the durable task ledger), `MEMORY.md`, and the dated
`memory/YYYY-MM-DD.md` logs.

### Agents still using large context?

1. **Get the real per-turn footprint estimate and distill if it's over budget:**

   ```bash
   docket setup --fix     # look for the "Context footprint" line
   docket pod reset <agent-id>   # summarize memory/*.md into MEMORY.md, archive originals, rebuild
   ```

2. **Verify the fleet is healthy:**

   ```bash
   docket status --all
   docket setup
   ```

### Startup contract stale, or HEARTBEAT.md wrong on resume?

`docket setup` re-seeds a missing or stale `WORKFLOW_AUTO.md` (the contract-version marker is
checked; a docket turn does not replay the file, but a human or tool reading the workspace does):

```bash
docket setup
# Runtime startup contract:
# ✓ myproject-implementer: seeded WORKFLOW_AUTO.md (codebase /home/user/code/myproject)
```

If HEARTBEAT.md itself looks wrong (not just the startup file), reset it; memory is distilled
into MEMORY.md first:

```bash
docket pod reset <agent-id>
```

For a pod member's generated files (SOUL/AGENTS/TOOLS) use `docket pod apply`.

## Harness Mode (`docket exec`)

Harness mode is a machine-facing entry point for an external caller that owns its own workspace
and `DOCKET_HOME` — not the interactive CLI most of this guide covers. Its failures show up as an
exit code and a printed `HarnessResult`, not a human-readable message, so read the result object
rather than trying to interpret the exit code alone.

### Exit code 2 — refused before any turn started

**Symptom:** `docket exec` exits `2` and prints exactly one JSON line with
`"status":"refused"`, and no agent turn ran at all.

**Cause:** `core.harness.preflight` rejected the environment before starting. The common cases:
`DOCKET_HOME` is unset or resolves to the operator's own default home (harness mode refuses to
touch a real install's approvals/audit log), `DOCKET_LLM_BASE_URL` is unset, `DOCKET_NO_TRACE=1`
is set (harness mode refuses to run unobserved), or `--workspace` is not a real directory. A
missing `--model` or a missing/duplicated `--task`/`--task-file` is refused the same way, before
`preflight` even runs. (`docket task show` with no `TOKEN` is different: it prints a usage
line on stderr and exits `1`, with no JSON.)

**Fix:** the caller must supply its own `DOCKET_HOME` (never the operator's `~/.docket`) and a
`DOCKET_LLM_BASE_URL`, unset `DOCKET_NO_TRACE`, and pass an existing `--workspace` directory. The
`error` field on the printed result names which condition failed.

### Exit code 1 with `"status":"blocked"` — a tool call needed approval

**Symptom:** the run exits `1`, and the terminal `HarnessResult` carries `"status":"blocked"` with
a non-null `blocked` object naming a `tool`, `call_id`, `denial_kind` (`approval_unavailable`),
`policy_id`, and `reason`.

**Cause:** harness mode always runs with approvals forced to non-interactive refusal — there is no
human on the other end of a caller-owned subprocess
to approve a gated tool call, so a verdict of `ask` ends the run immediately instead of waiting.
This is expected behavior, not a bug: it is the one thing an interactive dispatch would instead
block on for up to two minutes.

**Fix:** adjust the policy so the task's tool calls don't need approval (see
[SECURITY-SIMPLE.md](SECURITY-SIMPLE.md)), or re-scope the task to avoid the gated action. There
is no flag to make harness mode wait for a human — see
[ADR 0001](adr/0001-harness-mode.md) for why that is a separate, unbuilt decision.

### Distinguishing `failed`/`cancelled` from `blocked`/`refused`

`"status":"failed"` and `"status":"cancelled"` (also exit `1`) mean a turn actually ran — check
`docket task show TOKEN` and the NDJSON event stream on stdout for what happened during the
run. `"status":"blocked"` and `"status":"refused"` both mean **no completed turn produced the
outcome** — one stopped on a specific denied tool call, the other never started. See
[`specs/api/harness-mode.spec.md`](../specs/api/harness-mode.spec.md) for the full result shape.

## Getting Help

1. **Run diagnostics:**
   ```bash
   docket setup
   ```

2. **Check logs:**
   ```bash
   ls ~/.docket/workspaces/projects/<agent-id>/memory   # daily memory logs
   docket task trace --tail  # live dispatch trace, if it's pod-related
   docket log                 # recent docket-initiated changes
   ```

3. **Verify configuration:**
   ```bash
   docket pod show <agent-id>
   docket status --all
   ```

4. **Test agent:**
   ```bash
   # Send a test message in Telegram (if wired), or:
   docket task add "test task"
   docket run
   ```

5. **Emergency reset:**
   ```bash
   # If all else fails: re-render a pod's member files
   docket pod apply
   ```
