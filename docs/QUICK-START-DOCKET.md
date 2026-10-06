# Quick start: from install to a governed run in ten minutes

docket runs a team of coding agents that you define in files: a `.docket/` directory next to
your code names the roles, the order they work in, the gates between them and the rules they
cannot cross. This page takes you from nothing to one governed run, then shows how to make the
team yours. Everything below was captured from a real run against a local model; the terminal
output shown is what docket printed.

> [!WARNING]
> **Beta / early-stage software.** The steps work and are test-backed, but expect rough edges
> and breaking changes between versions. Verify results against your own install, and treat
> every cost figure as an estimate, not a provider bill.

**You need:** Python 3.11+, Git, Bash, a sandbox for the agents' shell (bubblewrap, `bwrap`, on
Linux, or a running Docker, the usual choice on macOS), and one OpenAI-compatible chat-completions
endpoint with function-tool support. Isolation is on by default: with neither sandbox, docket
refuses to run a turn until you record the opt-out with `docket gates isolate off`. The route below uses a local model on `127.0.0.1:8081` (llama.cpp, vLLM,
LM Studio, Ollama all work); a hosted provider is a two-line variant in step 2.

---

## 1. Install

Homebrew:

```bash
brew tap yielab/docket-cli https://github.com/yielab/docket
brew install docket-cli
```

Or the version-pinned installer, which needs no `sudo`. It downloads and verifies
`https://github.com/yielab/docket/releases/download/v0.2.0-beta.3/docket-v0.2.0-beta.3.tar.gz`
before extracting; it never installs from a moving branch:

```bash
curl -fsSL https://raw.githubusercontent.com/yielab/docket/v0.2.0-beta.3/install.sh \
  | DOCKET_VERSION=0.2.0-beta.3 bash
export PATH="$HOME/.local/bin:$PATH"
docket --version
```

---

## 2. Register a model

docket never guesses an endpoint. Register the one you have, then point every role at it:

```bash
docket models provider add local http://127.0.0.1:8081/v1 \
  --model local-model --ctx 16384 --max-tokens 4096
docket models preset local                # every role now resolves to local/local-model
```

`provider add` probes the endpoint before anything else is written, and stores a readable
`kind: provider` document (`docket models provider export local` prints it). `preset local`
matters: without it the built-in role policy still routes the Lead and Implementer to a hosted
model you may have no key for.

Against a small-context local server, also set `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` in your shell;
the default suits a large hosted model.

**Hosted provider instead?** Store the key by name and pick the preset:

```bash
docket keys add OPENROUTER_API_KEY         # or ANTHROPIC_API_KEY, OPENAI_API_KEY, ...
docket models preset openrouter            # anthropic | openai | google | ai-gateway | ...
```

Fourteen providers ship as documents (`docket models provider list`). Mixed setups, gateways and
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
→ Provisioning 'software' pod 'myapp' (lead, implementer)...
✓   myapp-lead  [lead]  local/local-model
✓   myapp-implementer  [implementer]  local/local-model
Apply plan — myapp <- .../templates/recipes/secure-build
  [add] role: security-vetter
  [add] policy: require-approval-secret-writes.yaml
  [add] member: security-vetter
  [add] pipeline: pipeline.yaml
✓ Applied 4 change(s) to pod 'myapp' from .../templates/recipes/secure-build.

✓ Pod 'myapp' created with 3 members!
  - myapp-lead
  - myapp-implementer
  - myapp-security-vetter
```

The first `init` on a machine also creates the shared foundation (global state, the three org
specialists `manager`/`knowledge`/`security`, baseline policies). Every later `init` creates one
pod for one repository. Two other ways to start:

| You have | Run | You get |
| --- | --- | --- |
| nothing yet | `docket init` | the lean default: `myapp-lead` + `myapp-implementer`, no gates beyond the built-in ones |
| a `.docket/` committed next to the code | `docket init` | that team, validated before anything is provisioned and applied after; an error names the file and field and provisions nothing |
| a shipped or local recipe | `docket init --recipe secure-build` (`docket recipes list` shows all twelve, or a directory) | the recipe applied onto the default pod |

Give the Implementer a real check. A non-zero exit fails the task instead of letting it advance:

```bash
docket pod myapp set-verify myapp-implementer "python3 -m pytest -q"
docket pipeline plan myapp                # what would run, resolved against the real roster
```

```text
Pipeline plan — myapp
Source: bound pipeline (hash 45f7aaf31d1f...)
Pipeline: secure-build
  [plan] role=lead -> myapp-lead [gate: none]
  [build] role=implementer -> myapp-implementer [gate: mechanical(verifyCmd)]
  [vet] role=security-vetter -> myapp-security-vetter [gate: verdict(approve, rework->build)]
```

---

## 4. Run a task

Queue work, then run the pipeline once. Each hop is one real, costed model turn, so dispatch is
always explicit:

```bash
docket pod myapp delegate "Fix calc.add so it returns the sum of a and b"
docket pod myapp dispatch
```

```text
→ Dispatching 1 pending task(s) through: lead → implementer → security-vetter
✓   [task-efbd46e7-...] done — 3 hop(s), $0.0000
```

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
git worktree list                         # ~/.docket/workspaces/projects/myapp-implementer/tasks/<taskId>
git -C ~/.docket/workspaces/projects/myapp-implementer/tasks/<taskId> diff
```

---

## 5. See what happened

Every run leaves a record you can read without trusting the model's own summary:

```bash
docket runs list                          # one row per dispatch: state, tasks, error
docket trace tail myapp                   # the latest session, step by step (Ctrl-C stops watching)
docket audit                              # every gate decision and operator action
docket audit verify                       # the audit chain hashes clean
docket config explain myapp-implementer   # the effective configuration, with where each value came from
```

`config explain` ends with the team's source of record:

```text
  Pipeline:        bound pipeline (hash 45f7aaf31d1f...)
  Config source:   .../templates/recipes/secure-build  (digest 441848f22bd2..., drift: no)
```

This record stays on the machine. To read it in a tool you already run, such as Langfuse or an
OpenTelemetry collector, turn on one of the built-in exporters. By default it sends only the
run's structure (model and tool names, timing, token counts, pass or fail), and
`docket exporters preview` shows exactly what would leave before you enable it:

```bash
docket exporters list                     # five built-in destinations, all off
docket exporters preview langfuse         # what it would receive from your latest session
docket exporters enable langfuse          # asks for the key, checks the endpoint, then turns it on
```

Sharing prompts and replies is a separate, confirmed step
([Configuration §3.14](CONFIGURATION.md#314-export-traces-to-opentelemetry-or-langfuse)).

A gate looks like this when it fires. Ask docket what it would do with a command before an agent
tries it:

```bash
docket policies test pre_tool_call implementer 'git push origin production'
```

```text
  Result: ask
  Reason: matches high-risk action class 'prod-deploy': Production deploys and release pushes
  Policy: 'high-risk-deploy' -> require_approval
```

In a live run that call waits for `docket approve <token>` (also over HTTP, MCP or Telegram) and
is denied on timeout with an `approval.deny ... channel=timeout` audit line. The command never
executes.

---

## 6. Make it yours

Write the team back next to the code, edit it, check it, apply it. This is the whole
customization loop; every file starts with `kind:` and validates before anything is written:

```bash
docket pod myapp export                   # writes ./.docket/ (refuses a non-empty one without --force)
find .docket -type f | sort
```

```text
.docket/pipeline.yaml
.docket/pod.yaml
.docket/policies/require-approval-secret-writes.yaml
.docket/roles/security-vetter.md
.docket/roles/security-vetter.yaml
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
docket validate                           # every document under .docket/, invalid files first
docket pod myapp apply --dry-run          # the plan: add / replace / skip per item
docket pod myapp apply                    # writes it; a second run plans every item skip
git add .docket && git commit -m "Add: the myapp agent team"
```

Nothing is applied without that command. Dispatch, `serve`, schedules and the harness never
re-read `.docket/`, and `config explain` shows `drift: yes` once the directory moves on from
what was applied. A policy in the repo can only add restrictions: it accumulates with your
global policies under most-restrictive-wins.

**Add one thing later.** A recipe does not have to be a whole team. `docket recipes list` shows
twelve shipped ones of three kinds: teams, policy packs that change no roster, and methodology
pipelines. `docket pod myapp apply git-safety` adds two guardrail policies and nothing else;
`docket pod myapp apply tdd` swaps the route for a test-first one. Apply what you need, then
`docket pod myapp export --force` writes the merged team back to `.docket/` for the commit.

Pod-level knobs are one command each: `docket pod myapp config set budgetUsd 5`,
`allowCommands pytest,uv`, `approvalMode refuse`, `maxReworkCycles 2`. Your own words for one
agent go in its operator-owned `INSTRUCTIONS.md` (`docket edit myapp-implementer`), which docket
never regenerates. The file-by-file reference, with what reads each file on the live path, is
[Configuration](CONFIGURATION.md); the shipped recipes and every role are listed by
`docket roles list` and in [Agent teams](AGENT-TEAMS.md).

---

## 7. Run unattended

```bash
docket serve --dispatch                   # drain every pod's queue each sweep (loopback by default)
docket pod myapp config set schedule "@every 30m"   # or a daily HH:MM in UTC, or 5-field cron
docket inbox                              # everything across every pod that needs you, derived
```

A gated call hit by an unattended sweep no longer waits on a thread: it **parks** instead,
recorded as an ordinary `waiting_approval` task with nothing blocking behind it. `docket inbox`
lists every task and approval that needs you (`--peek` reads without advancing its cursor); grant
or deny it exactly like any other approval: `docket approve <token>` (also HTTP, MCP or Telegram).
To be told rather than have to ask, turn on a delivery channel — `docket channels enable ntfy
--set topic=<your-topic>` (or `desktop`, `webhook`, `command`, `email`) — and `docket notify`
pushes what changed since the last flush; `docket serve --dispatch` and a real dispatch already
call it after every state change. Prefer a hard failure over a parked one in CI?
`docket pod myapp config set approvalMode refuse` fails the task at once instead, naming the tool
and the policy that asked.

`docket serve` also exposes a read API and `POST /dispatch/<project>` for CI. `--telegram`
adds an inbound-only approval channel with five verbs (`/status`, `/delegate`, `/approve`,
`/deny`, `/answer`); it is not a chat, and docket never messages first. Schedules, webhooks and the
run registry are in the [Workflow guide](WORKFLOW-GUIDE.md).

---

## Before trusting it with more

Start with the lean pod and add a reviewer, tester or vetter once a concrete quality gate
justifies the extra turns. Give the Implementer an objective check with `set-verify`, so
advancement blocks on an exit code rather than on how confident the prose sounds. Keep dispatch
explicit before enabling schedules or `serve --dispatch`, and set a budget cap first
(`docket pod myapp config set budgetUsd 5`; over it, the task is left blocked and the Lead
paused). Read the run, the trace and the audit chain before accepting a consequential change.
Keep docket behind your own boundary: `docket serve` binds loopback and does not terminate TLS.

## Where next

- [Agent teams](AGENT-TEAMS.md): roles, pods, blueprints, recipes and how a dispatch is gated
- [Configuration](CONFIGURATION.md): every file docket creates, what reads it, the
  customization recipes by use case, and trace export with its privacy levels
- [Workflow guide](WORKFLOW-GUIDE.md): end-to-end examples, custom pipelines, schedules, webhooks
- [Security](SECURITY-SIMPLE.md): the layers, the approval channels, the audit log
- [Command reference](commands.md) and [Troubleshooting](troubleshooting.md)
- Issues: https://github.com/yielab/docket/issues
