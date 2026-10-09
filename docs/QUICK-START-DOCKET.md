# Quick start: from install to a governed run in ten minutes

docket runs a team of coding agents that you define in files: a `.docket/` directory next to
your code names the roles, the order they work in, the gates between them and the rules they
cannot cross. This page takes you from nothing to one governed run, then shows how to make the
team yours. Everything below was captured from a real run against a local model on 2026-10-09;
the terminal output shown is what docket printed. It was captured through a pipe, so it carries
docket's plain voice (`ok`, `->`, `!`); on a terminal the same lines read `✓`, `→`, `⚠`.

> [!WARNING]
> **Beta / early-stage software.** The steps work and are test-backed, but expect rough edges
> and breaking changes between versions. Verify results against your own install, and treat
> every cost figure as an estimate, not a provider bill.

**You need:** Python 3.11+, Git, Bash, and one OpenAI-compatible chat-completions endpoint with
function-tool support. **Optional:** a sandbox for the agents' shell. Isolation is opt-in: turn it
on with `docket setup sandbox on`, which needs bubblewrap (`bwrap`) on Linux or a running Docker
(the only choice on macOS); see
[Workspace isolation](SECURITY-SIMPLE.md#workspace-isolation-opt-in-the-sandbox-for-the-agents-shell).
The route below uses a local model on `127.0.0.1:8081` (llama.cpp, vLLM,
LM Studio, Ollama all work); a hosted provider is a one-line variant in step 2.

---

## 1. Install

Homebrew:

```bash
brew tap yielab/docket-cli https://github.com/yielab/docket
brew trust yielab/docket-cli            # Homebrew 7 loads a third-party tap only once trusted
brew install docket-cli
```

Or the version-pinned installer, which needs no `sudo`. It downloads and verifies
`https://github.com/yielab/docket/releases/download/v0.2.0-beta.4/docket-v0.2.0-beta.4.tar.gz`
before extracting; it never installs from a moving branch:

```bash
curl -fsSL https://raw.githubusercontent.com/yielab/docket/v0.2.0-beta.4/install.sh \
  | DOCKET_VERSION=0.2.0-beta.4 bash
export PATH="$HOME/.local/bin:$PATH"
docket --version
```

---

## 2. Register a model

docket never guesses an endpoint. Run `docket setup`: it prints what is configured and what is
missing, and on a terminal asks for the missing model endpoint first. Answer `local` for a server
on this machine:

```text
$ docket setup
PIECE               STATE     DETAIL                              COMMAND
model endpoint      missing   lead ->                             docket setup provider add <name>
                              anthropic/claude-haiku-4-5:
                              ANTHROPIC_API_KEY is required for
                              the resolved endpoint
notifications       optional  console only (nobody is told)       docket setup notify enable desktop
sandbox             optional  off; backend found: bwrap           docket setup sandbox on
shell completion    optional  not enabled                         docket setup shell zsh
background service  optional  not installed                       docket start
Provider [local]: local
```

Without a terminal, register the endpoint in one command:

```bash
docket setup provider add local http://127.0.0.1:8081/v1 \
  --model local-model --ctx 16384 --max-tokens 4096
```

`provider add` probes the endpoint before anything else is written, stores a readable
`kind: provider` document (`docket setup provider export local` prints it) and applies the
provider's preset, so every role resolves to `local/local-model`. Without a preset the built-in
role policy would still route the Lead and Implementer to a hosted model you may have no key
for; `--no-preset` skips it and `docket setup model preset <name>` applies one later.

Against a small-context local server, also set `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` in your shell;
the default suits a large hosted model.

**Hosted provider instead?** Name it and give its key; the preset is applied for you:

```bash
docket setup provider add openrouter --credential <key>   # or anthropic, openai, google, ai-gateway, ...
```

Fourteen providers ship as documents (`docket setup provider list`). Mixed setups, gateways and
per-role overrides are in [Models, gateways and harnesses](MODEL-GATEWAYS.md).

---

## 3. Create the team

Go to a repository and start from a shipped recipe. This one adds a read-only security vetter to
the default Lead + Implementer pod and binds a three-step pipeline with a verify gate:

```bash
cd ~/code/myapp
docket init --recipe secure-build
```

```text
-> Provisioning 'software' pod 'myapp' (lead, implementer)...
ok   myapp-lead  [lead]  local/local-model
ok   myapp-implementer  [implementer]  local/local-model

docket - Apply plan myapp <- .../templates/recipes/secure-build
A read-only security vetter gates the Implementer's change behind an explicit APPROVE, with one bounded rework cycle.
  roles 1 · policies 1 · members 1 · pipeline secure-build · plugins 0 · skills 1 · settings 0
  [add] role: security-vetter
  [add] policy: require-approval-secret-writes.yaml
  [add] skill: security-review
  [add] member: security-vetter
  [add] pipeline: pipeline.yaml
ok Applied 5 change(s) to pod 'myapp' from .../templates/recipes/secure-build.

ok Pod 'myapp' created with 3 members!
  - myapp-lead
  - myapp-implementer
  - myapp-security-vetter
```

A **pod** is the team of agents attached to one repository: its members, its rules, its queue,
its ports and worktrees. The first `init` on a machine also creates the shared foundation (global
state, baseline policies). Every later `init` creates one pod for one repository, and from then on
every command run inside that repository finds its pod by where you stand; outside it, pass
`--pod <name>`. Two other ways to start:

| You have | Run | You get |
| --- | --- | --- |
| nothing yet | `docket init` | the lean default: `myapp-lead` + `myapp-implementer`, no gates beyond the built-in ones |
| a `.docket/` committed next to the code | `docket init` | that team, validated before anything is provisioned and applied after; an error names the file and field and provisions nothing |
| a shipped or local recipe | `docket init --recipe secure-build` (`docket pod recipes` shows all eighteen, or a directory) | the recipe applied onto the default pod |

Give the Implementer a real check. A non-zero exit fails the task instead of letting it advance:

```bash
docket pod set verify "python3 -m pytest -q" --member myapp-implementer
docket pod plan                       # what would run, resolved against the real roster
```

```text
docket - Pipeline plan myapp
Source: bound pipeline (hash 45f7aaf31d1f...)

Pipeline: secure-build
  [plan] role=lead -> myapp-lead [gate: none]
  [build] role=implementer -> myapp-implementer [gate: mechanical(verifyCmd)]
  [vet] role=security-vetter -> myapp-security-vetter [gate: verdict(approve, rework->build)]
```

---

## 4. Run a task

Queue work, then run the pipeline once. Each hop is one real, costed model turn, so running is
always explicit:

```bash
docket task add "Fix calc.add so it returns the sum of a and b"
docket run
```

```text
-> Running 1 pending task(s) through: lead → implementer → security-vetter
ok   [task-6e046891-e910-4778-92ce-4560364bfaa9] done — 3 hop(s)
ok 1 done · 0 failed · 36.3k tokens (~$0.00 est.)
-> Next: docket status
!   Only console is on, and console sends nothing.
  A parked task waits unseen until you run docket inbox.
  Before running unattended, enable a channel:
    docket setup notify enable desktop                   # this machine
    docket setup notify enable ntfy --set topic=<topic>  # your phone
```

The token count is measured; the dollar figure is a labelled estimate, never a bill. The warning
is step 7's subject: a small local model may also park a question before delegating (the Lead
asks, the task waits as `waiting_input`); `docket inbox` shows it and `docket task answer <id>
--option <id>` resumes the run.

What happened, hop by hop:

1. **Lead** read the task and wrote a plan. It has no `write`, `edit` or `bash` tool, so it
   cannot touch the code.
2. **Implementer** worked in the task's own git worktree on its own branch, made the change, and the
   verify command ran. A failing command ends the task as `failed` with a `verification_failed`
   event; it never reaches the vetter.
3. **security-vetter** reviewed the diff read-only and ended its reply with `APPROVE`.
   `REQUEST-CHANGES` would have sent the task back to the Implementer once, then failed it.

The change lives only in the task's worktree until you merge its branch:

```bash
docket task diff <id>                     # what the task changed, against the commit it started from
git worktree list                         # the task's worktree, on its own branch
```

<p align="center">
  <img src="assets/isolation.png" alt="Real terminal output: the Implementer's workspace and model, isolation on with bwrap, the task's git worktree on its own branch beside a clean main checkout, and the one-line fix living only in the worktree" width="760">
</p>

---

## 5. See what happened

Every run leaves a record you can read without trusting the model's own summary:

```bash
docket task list                          # the queue: state, cost, worktree per task
docket task show <id>                     # one task's whole story: hops, evidence, runs, worktree
docket task trace <id> --tail             # that task's session, step by step (Ctrl-C stops watching)
docket log                                # every gate decision and operator action
docket log verify                         # the audit chain hashes clean
docket pod show myapp-implementer         # the effective configuration, with where each value came from
```

`docket pod show` ends with the team's source of record:

```text
  Pipeline: bound pipeline (hash 45f7aaf31d1f...)
  Network: open (default)
  Config source: .../templates/recipes/secure-build (digest ec69082e5924..., drift: no)
```

This record stays on the machine. To read it in a tool you already run, such as Langfuse or an
OpenTelemetry collector, turn on one of the built-in exporters. By default it sends only the
run's structure (model and tool names, timing, token counts, pass or fail), and
`docket setup export preview` shows exactly what would leave before you enable it:

```bash
docket setup export list                     # five built-in destinations, all off
docket setup export preview langfuse         # what it would receive from your latest session
docket setup export enable langfuse          # asks for the key, checks the endpoint, then turns it on
```

Sharing prompts and replies is a separate, confirmed step
([Configuration §3.14](CONFIGURATION.md#314-export-traces-to-opentelemetry-or-langfuse)).

A gate looks like this when it fires. Ask docket what it would do with a command before an agent
tries it:

```bash
docket pod check 'git push origin production' --role implementer
```

```text
  Hook:   pre_tool_call
  Role:   implementer
  Text:   git push origin production
  Result: ask
  Reason: matches high-risk action class 'prod-deploy': Production deploys and release pushes
  Policy: 'high-risk-deploy' -> require_approval
```

In a live run from a terminal that call waits for `docket task approve <token>` (also over HTTP,
MCP or Telegram) and is denied on timeout with an `approval.deny ... channel=timeout` audit
line; unattended it parks the task as `waiting_approval` instead. Either way the command never
executes, the audit log carries `tool.ask`, and the trace records the denial with
`executed: false`:

<p align="center">
  <img src="assets/governance.png" alt="Real terminal output: the policy dry-run answers ask; the Lead parks a question that docket task answer resolves; the Implementer's git push origin production parks the task for approval under high-risk-deploy; the audit log shows tool.ask, the trace shows the denial with executed false, and the chain verifies clean" width="760">
</p>

---

## 6. Make it yours

Write the team back next to the code, edit it, check it, apply it. This is the whole
customization loop; every file starts with `kind:` and validates before anything is written:

```bash
docket pod export                   # writes ./.docket/ (refuses a non-empty one without --force)
find .docket -type f | sort
```

```text
.docket/pipeline.yaml
.docket/pod.yaml
.docket/policies/require-approval-secret-writes.yaml
.docket/roles/security-vetter.md
.docket/roles/security-vetter.yaml
.docket/.schemas/pipeline.schema.json
.docket/.schemas/pod.schema.json
.docket/.schemas/policy.schema.json
.docket/.schemas/role.schema.json
.docket/skills/security-review/SKILL.md
```

Three edits most teams make first. Each is one file:

**A rule.** `.docket/policies/no-curl.yaml` — live on the next tool call once applied:

```yaml
kind: policy
name: no-curl
appliesTo: [implementer]
when: {matches: '\bcurl\b'}
then: ask
message: curl needs approval
```

**The route.** `.docket/pipeline.yaml` — who works, in what order, behind which gate, with how
much rework. Add `model: cheap` to a step to run that hop on the cheap tier only:

```yaml
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

**A role.** `.docket/roles/security-vetter.yaml` plus its Markdown. `cannot` is the only
capability statement: a tool listed there is absent from the role's turn, not merely discouraged:

```yaml
kind: role
name: security-vetter
model: strong
cannot: [write, edit, bash]
verdict: [APPROVE, REQUEST-CHANGES]
instructions: security-vetter.md
```

Then:

```bash
docket pod validate                           # every document under .docket/, invalid files first
docket pod apply --dry-run          # the plan: add / replace / skip per item
docket pod apply                    # writes it; a second run plans every item skip
git add .docket && git commit -m "Add: the myapp agent team"
```

Nothing is applied without that command. `docket run`, `start`, schedules and `exec` never
re-read `.docket/`, and `docket pod show` shows `drift: yes` once the directory moves on from
what was applied. A policy in the repo can only add restrictions: it accumulates with your
global policies under most-restrictive-wins.

**Add one thing later.** A recipe does not have to be a whole team. `docket pod recipes` shows
eighteen shipped ones: teams, policy packs that change no roster, methodology pipelines, checks
that fail a task whose tests prove nothing, and a tool pack. `docket pod apply git-safety` adds two guardrail policies and nothing else;
`docket pod apply tdd` swaps the route for a test-first one. Apply what you need, then
`docket pod export --force` writes the merged team back to `.docket/` for the commit.

Pod-level knobs are one command each: `docket pod set budgetUsd 5`,
`docket pod set allowCommands pytest,uv`, `approvalMode refuse`, `maxReworkCycles 2`. Your own
words for one agent go in its operator-owned `INSTRUCTIONS.md`, in the workspace path
`docket pod show myapp-implementer` prints; docket never regenerates it. The file-by-file reference, with what reads each file on the live path, is
[Configuration](CONFIGURATION.md); the shipped recipes and every role are listed by
`docket pod roles` and in [Agent teams](AGENT-TEAMS.md).

---

## 7. Run unattended

**First, give docket a way to reach you.** The only channel on by default is `console`, and
console sends nothing: it is the terminal you are already looking at. Unattended, a gated call
**parks** its task and waits, silently, until you run `docket inbox` or the approval expires and
the task fails. `docket setup` counts a home with pods and no delivering channel as an issue,
`docket init` and `docket start --dispatch` print the same warning. The one shortcut: `init`
run from a terminal with a desktop session asks `Enable desktop notifications now? [Y/n]` and,
on yes, turns `desktop` on and sends a test notification so you see it work. Pick the rung you
need:

```bash
docket setup notify enable desktop                        # this machine: a native notification, nothing to configure
docket setup notify enable ntfy --set topic=<private>     # your phone: the ntfy app, one topic, no account
docket setup notify enable telegram --chat <chat>        # your phone, and you can also answer from it
docket setup notify test desktop                          # one synthetic event, so you see it before you need it
```

`desktop` needs only a desktop session on the host running docket. `ntfy` reaches you anywhere;
pick a topic nobody can guess, since the public server shows it to anyone who does (a
notification carries `content: minimal` by default: pod, task and state, nothing more).
`telegram` is the one channel that can also *decide* (`/approve`, `/answer`); `enable telegram
--chat <id>` also stores the bot token (`--token`, else `TELEGRAM_BOT_TOKEN` in the environment,
else a hidden prompt) and binds every pod's Lead. `webhook` and `command` wire anything
else (Slack, n8n, a pager); `email` notifies and never decides.

```bash
docket start --dispatch                   # drain every pod's queue each sweep (loopback by default)
docket pod set schedule "@every 30m"   # or a daily HH:MM in UTC, or 5-field cron
docket inbox                              # everything across every pod that needs you, derived
```

A gated call hit by an unattended sweep no longer waits on a thread: it **parks** instead,
recorded as an ordinary `waiting_approval` task with nothing blocking behind it. `docket inbox`
lists every task and approval that needs you (`--peek` reads without advancing its cursor); grant
or deny it exactly like any other approval: `docket task approve <id>` (also HTTP, MCP or Telegram).
`docket setup notify flush` pushes what changed since the last flush to every enabled channel;
`docket start --dispatch` and a real `docket run` already call it after every state change. Prefer a hard failure
over a parked one in CI?
`docket pod set approvalMode refuse` fails the task at once instead, naming the tool
and the policy that asked.

`docket start` also exposes a read API and `POST /dispatch/<project>` for CI. `--telegram`
adds an inbound-only approval channel with five verbs (`/status`, `/delegate`, `/approve`,
`/deny`, `/answer`); it is not a chat, and its poll loop only replies; a push to your phone comes from the `telegram`
channel you enabled above. Schedules, webhooks and the
run registry are in the [Workflow guide](WORKFLOW-GUIDE.md).

---

## Before trusting it with more

Start with the lean pod and add a reviewer, tester or vetter once a concrete quality gate
justifies the extra turns. Give the Implementer an objective check with `docket pod set verify`, so
advancement blocks on an exit code rather than on how confident the prose sounds. Keep `docket run`
explicit before enabling schedules or `start --dispatch`, and set a budget cap first
(`docket pod set budgetUsd 5`; over it, the task is left blocked and the Lead
paused). Read the run, the trace and the audit chain before accepting a consequential change.
Keep docket behind your own boundary: `docket start` binds loopback and does not terminate TLS.

## Where next

- [Agent teams](AGENT-TEAMS.md): roles, pods, blueprints, recipes and how a run is gated
- [Configuration](CONFIGURATION.md): every file docket creates, what reads it, the
  customization recipes by use case, and trace export with its privacy levels
- [Workflow guide](WORKFLOW-GUIDE.md): end-to-end examples, custom pipelines, schedules, webhooks
- [Security](SECURITY-SIMPLE.md): the layers, the approval channels, the audit log
- [Command reference](commands.md) and [Troubleshooting](troubleshooting.md)
- Issues: https://github.com/yielab/docket/issues
