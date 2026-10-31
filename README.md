# docket — staff, govern and record teams of AI agents.

```text
██████╗  ██████╗  ██████╗██╗  ██╗███████╗████████╗
██╔══██╗██╔═══██╗██╔════╝██║ ██╔╝██╔════╝╚══██╔══╝
██║  ██║██║   ██║██║     █████╔╝ █████╗     ██║
██║  ██║██║   ██║██║     ██╔═██╗ ██╔══╝     ██║
██████╔╝╚██████╔╝╚██████╗██║  ██╗███████╗   ██║
╚═════╝  ╚═════╝  ╚═════╝╚═╝  ╚═╝╚══════╝   ╚═╝
 staff  ·  govern  ·  record  ·  teams of AI agents
```

[![CI](https://github.com/yielab/docket/actions/workflows/ci.yml/badge.svg)](https://github.com/yielab/docket/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-green.svg)](https://www.python.org/)
[![Specs: validated](https://img.shields.io/badge/specs-validated-success.svg)](specs/)

**docket runs teams of AI agents: roles with job descriptions, a pipeline that decides who does
what and who signs off, and a checkpoint that applies your rules to every action. The team is files
in your repository, and the work is assigned, not chatted.**

You describe a task in plain words. A Lead agent plans it, an Implementer makes the change on its
own git branch, and a reviewer can check it before you merge anything. `git status` runs,
`git push origin production` waits for your approval, anything a policy forbids is refused, and
every decision goes to a tamper-evident log you can verify.

[Website](https://yielab.com/docket) · [Documentation](docs/README.md) ·
[Quick start](docs/QUICK-START-DOCKET.md) · [Recipes](docs/recipes.md) ·
[Security](SECURITY.md) · [Adoption evidence](docs/ADOPTION-EVIDENCE.md) ·
[Changelog](CHANGELOG.md)

> [!WARNING]
> docket is beta software. Core contracts are spec-first and test-backed, but the
> project has not been hardened against large deployments or adversarial public-host workloads.
> Expect breaking changes between beta releases and verify consequential outcomes yourself.

## How it works

```text
┌──────┐   ┌─────────────┐   ┌────────┐   ┌──────────┐   ┌───────────┐
│ Lead │──▶│ Implementer │──▶│ verify │──▶│ Reviewer │──▶│ you merge │
└──────┘   └─────────────┘   └────────┘   └──────────┘   └───────────┘
plans      edits on its own  your test    approves or    nothing lands
           git branch        command      sends it back  until you do
═════════════════════════════════════════════════════════════════════════════
 CHECKPOINT  every tool call of every agent:  allow  ·  ask a person  ·  deny
═════════════════════════════════════════════════════════════════════════════
 hash-chained log  ·  a trace of every call  ·  tokens measured
```

| Concept | What it is |
| --- | --- |
| **Pod** | The team attached to one repository (or, for work with no repository, one working directory): its members, rules, task queue and the git worktrees its agents work in. `docket init` creates it; inside the repository you never type its name. |
| **Role** | What an agent is, what it is told and which tools it lacks. A reviewer without a write tool *cannot* write; it is not merely asked not to. |
| **Pipeline** | Who works a task, in what order, and the gate after each step: the exit code of your verify command or of an independent verifier, or a reviewer's `APPROVE` / `REQUEST-CHANGES`. A step closes with a structured handoff (summary, verdict, files changed) that is all the next step reads. A pipeline can route on an outcome, skip a step on a condition, run a command, or stop and ask you. |
| **Policy** | A rule checked on every tool call, by every agent: allow it, ask a human, or deny it. |
| **Recipe** | A ready-made team, policy pack or method added with one command: test-first (`tdd`), spec-first, mutation testing, a read-only vetter (`secure-build`), a builder on one provider's model checked by a reviewer on another's (`cross-family-review`). |

Day to day:

| Command | Does |
| --- | --- |
| `docket init` | creates the team |
| `docket task add "…"` | queues work |
| `docket run` | takes the next task through the pipeline |
| `docket status` · `docket inbox` | where things stand, and what needs you across every team (`status --all`) |
| `docket task answer` | settles whatever a task waits on, an approval or a question |

Autonomy is a setting per task (`docket task add --autonomy L3|L4|L5`), and the model is a setting
per role:

```text
  L3                       L4                        L5
  a person validates       a person is asked only    nobody waits: a call that
  everything               for a call that needs     needs approval is refused
                           approval                  and you are told
  ◀── more control ───────────────────────────── more autonomy ──▶
```

docket is not an agent framework you program and not an interactive pair-programming assistant: it
runs the team your files describe, beside the coding assistant you already use. It has no web UI of
its own; `/status.json` and `/metrics` feed your own board. Agents use only the tools a role
allows: read, search and edit files, shell commands (background processes stop when the turn ends)
and `fetch`, which reads a web page as text from hosts you allow and nowhere else. The
`web-research` recipe adds search through a server you declare.

## What a team can do

A pod does not have to work on code. `docket init --blueprint <shape>` creates one of four shapes.

| Shape | Team | Flow | Status |
| --- | --- | --- | --- |
| `build` | Lead, Implementer, Reviewer | plan → change on a branch behind your tests → review | ✔ run end to end on real repositories |
| `respond` | Lead, Researcher, Writer, Reviewer, Actor | intake → research → draft → review → send | ◐ approve-and-send-once ran against a local model; no real external service yet |
| `operate` | Lead, Monitor, Operator, Reviewer | watch → propose (approval) → act → review | ○ shape only, not run against a real system |
| `routine` | Lead, Analyst, Writer, Reviewer | compile → draft → review, on a schedule | ✔ ran against the real Hacker News search API |

- The last three work in a plain directory, not a repository. Plain `docket init` is a lean `build`
  team, a Lead and an Implementer; `--pod full` adds the Reviewer.
- A routine creates tasks on its schedule while `docket start --dispatch` runs.
- A role cannot send anything outside the machine unless it names a send tool, and every send is
  audited. A `respond` pod needs the operator's role overlay to name the Actor's send tool; the
  `outward` recipe adds a daily quota per pod and makes the sender ask a person first.

## Install

```bash
brew tap yielab/docket-cli https://github.com/yielab/docket
brew trust yielab/docket-cli            # Homebrew 7 loads a third-party tap only once trusted
brew install docket-cli
```

Or use the installer, which needs no `sudo` and is pinned to a release tag: the
[quick start](docs/QUICK-START-DOCKET.md#1-install) has the command. You need Python 3.11+, Git,
Bash and a model endpoint with function tools: the OpenAI chat-completions format, or Anthropic's
Messages API natively (docket marks the prompt cache there). Hosted providers (Anthropic, OpenAI,
Google, OpenRouter, Vercel AI Gateway and others) and local servers (llama.cpp, vLLM, LM Studio,
Ollama) both work.

## Quick start

```bash
docket setup                              # shows what is missing; asks for the model endpoint first
docket setup provider add local http://127.0.0.1:8081/v1 \
  --model local-model --ctx 32768 --max-tokens 4096

cd ~/code/myapp
docket init                               # a Lead that plans + an Implementer that edits
docket init --recipe secure-build         # or: that team plus a read-only security vetter

docket task add "Create FIRST_TURN.md containing: governed first turn"
docket run

docket status                             # the queue, the last run, tokens used, what needs you
docket task trace <id>                    # every step the agents took
docket log verify                         # check the hash chain over every decision
```

The change stays in the Implementer's worktree until you merge it. The
[ten-minute quick start](docs/QUICK-START-DOCKET.md) walks the same path with real output.

## Make the team yours

`docket pod export` writes the team into your repository. A plain pod is only `pod.yaml`; each of
the other files appears when the team has one:

```text
.docket/
  pod.yaml                 kind: pod       who is on the team, the pod's settings
  roles/*.yaml             kind: role      what a role may not do, how it is gated, its model
  pipeline.yaml            kind: pipeline  who works a task, in what order, behind which gates
  policies/*.yaml          kind: policy    what always needs a human
  prompts/<layer>/*.md     kind: prompt    the text a hop or an identity is built from, by name
  skills/<name>/           SKILL.md        instructions an agent reads on demand
```

Edit a file, check it with `docket pod validate`, preview the run with `docket pod plan`, apply it
with `docket pod update .docket`, and commit the directory: a plain `docket init` builds the same
team on any machine. [Configuration](docs/CONFIGURATION.md) covers every file and setting; the
[recipe library](docs/recipes.md) shows what each recipe adds.

**Prompts are versioned configuration.**

- The nearest of four places wins: your repository, the pod, your own configuration, then docket's.
- `docket pod update` records each applied file with its SHA-256 in a lock file, and every hop
  records the name, version, SHA-256 and source of each prompt it was built from, so two runs show
  whether a prompt changed.
- A prompt can carry test cases: `docket pod test <prompt>` runs them against a model, and a role
  can refuse a model that failed them.

## See what happened

```bash
docket task trace <id>                    # one task, step by step
docket log --summary                      # tokens per accepted task, and input read from the cache
docket setup export enable langfuse       # or otel-collector, jaeger, honeycomb, phoenix
```

- Both token figures are measured. An exporter sends each run as OpenTelemetry spans: one trace
  per task, a span per hop with its model calls (tokens, cache reads and writes) and tool calls,
  and a span for each pause that waited on a person.
- Nothing leaves your machine until you enable an exporter. Its privacy level decides what does:
  the structure alone by default, up to the full conversation with
  `docket setup export privacy <name> full`. `docket setup export preview <name>` shows the exact
  payload first.

## Known limits

What docket does not do, so you know what to arrange yourself:

- **The sandbox needs a backend.** `docket init` turns it on where the machine has Landlock or
  Seatbelt. Without one, or after `docket setup sandbox off`, an agent's shell commands run on your
  machine and can reach the network.
- **The checkpoint covers what docket runs.** Your rules apply to the tool calls docket makes for
  its agents, not to anything else on the machine.
- **The audit log shows tampering; it does not prevent it.** Deleting it is visible, not
  impossible.
- **An exporter shares what you allow.** At `conversation` or `full`, the destination receives
  prompts, replies and tool output, which can include your code.
- **The model must support tool calling.** Agents act only through tool calls, so an endpoint that
  only chats cannot do the work. Small local models call tools less reliably.
- **It runs on one machine for one operator.** There are no tenants and no hosted service; a
  routine fires only while `docket start --dispatch` runs here.
- **Costs are estimates.** Token counts are measured; docket records no dollar spend, and its
  budget limit works on a labelled estimate.

The reasoning behind each limit, and the ones that matter less, are in
[Known limits](docs/README.md#known-limits). Read [SECURITY.md](SECURITY.md) before exposing a
service and [COMPATIBILITY.md](COMPATIBILITY.md) before relying on a model endpoint or MCP server.

## Documentation

| I want to… | Read |
| --- | --- |
| Go from install to a first governed run | [Quick start](docs/QUICK-START-DOCKET.md) |
| Understand roles, pods, pipelines and gates | [Agent teams](docs/AGENT-TEAMS.md) |
| Change any file or setting | [Configuration](docs/CONFIGURATION.md) |
| Write, version and test prompts | [Configuration](docs/CONFIGURATION.md#32-change-what-an-agent-is-told) |
| Send runs to Langfuse or OpenTelemetry | [Export traces](docs/CONFIGURATION.md#314-export-traces-to-opentelemetry-or-langfuse) |
| Pick a ready-made team or method | [Recipe library](docs/recipes.md) |
| Look up a command or flag | [Command reference](docs/commands.md) |
| Connect a hosted or local model | [Models and gateways](docs/MODEL-GATEWAYS.md) |
| Know what the gate enforces | [Security model](docs/SECURITY-SIMPLE.md) |
| Fix a problem | [Troubleshooting](docs/troubleshooting.md) |
| Embed the gate in my own application | [Architecture](docs/DOCKET.md) and [Compatibility](COMPATIBILITY.md) |

The embeddable runtime ships as a separate package, **`docket-runtime`**, built from this
repository's source and not published to any index. Every guide is listed in the
[documentation index](docs/README.md).

## Contributing

docket is built spec-first and test-first. Start with [CONTRIBUTING.md](CONTRIBUTING.md); the
[roadmap](ROADMAP.md) records current plans and decisions, and [specs/](specs/README.md) holds the
executable contracts.

## License

Apache-2.0. See [LICENSE](LICENSE).
