# docket documentation

**docket — agent teams as configuration. Your rules, in YAML.** A repository's `.docket/`
directory names the roles, the order they work in, the gates between them and the rules they
cannot cross; `docket init` turns it into an isolated team of agents, `docket pod <p> dispatch`
runs it one real model turn per hop, and every gate decision lands in a hash-chained audit log.
docket is a Python CLI that owns the agent turn loop itself. It has no daemon and talks to any
OpenAI-compatible chat-completions endpoint, hosted or local.

<p align="center">
  <img src="assets/hero.gif" alt="Animated docket terminal journey captured from a real run against a local model: provision a pod from a recipe, validate and plan the team, dispatch a fix through Lead, Implementer and a read-only vetter with a verify gate, and verify the audit chain" width="720">
</p>

> [!WARNING]
> **docket is early-stage / beta software.** What these guides describe is implemented and
> automated-test-backed, but not QA-hardened in production. Expect rough edges and breaking
> changes between versions, and **verify anything important against your own install**. Every
> cost or dollar figure is an accounting estimate, never your provider's bill; see
> [Known limits](../README.md#known-limits).

## Start here

1. **[Quick start](QUICK-START-DOCKET.md)**: install, register a model, create the team from a
   recipe, run one governed task, read the record, then export the team and make it yours.
2. **[Agent teams](AGENT-TEAMS.md)**: the model behind it. Roles as data, pods per project,
   blueprints and recipes, and what each gate does during a dispatch.
3. **[Configuration](CONFIGURATION.md)**: every file docket creates, what reads it on the live
   path, and the customization recipes: models, instructions, roles, pipelines, policies, tools,
   unattended runs, and keeping the team in the repo.

## Guides

| Doc | What it covers |
|-----|----------------|
| [Quick start](QUICK-START-DOCKET.md) | Ten minutes from install to a governed run, then the customization loop |
| [Agent teams (pods)](AGENT-TEAMS.md) | The core model: org specialists vs project pods, the roles, blueprints, recipes and real pipeline dispatch |
| [Configuration](CONFIGURATION.md) | Every file, globally and per project: what it controls, what reads it, and recipes for customizing agents, roles, pipelines, policies and tools |
| [Workflow guide](WORKFLOW-GUIDE.md) | End-to-end examples: a pod from `init` to committed code, custom pipelines, the run registry, schedules and webhooks |
| [Command reference](commands.md) | Every command with syntax, options and examples, generated from the CLI |
| [Models, gateways and harnesses](MODEL-GATEWAYS.md) | Hosted providers, OpenRouter and Vercel AI Gateway, other OpenAI-compatible endpoints, and what "compatible" does not promise |
| [Security](SECURITY-SIMPLE.md) | The layered model: the always-on tool-call gate, policies, high-risk command classes, approvals and the audit log |
| [Architecture (deep dive)](DOCKET.md) | The `cli`/`core`/`edges` layering, the RuntimeDriver port, dispatch internals, durable state, [harness mode](DOCKET.md#harness-mode-one-agent-one-turn-for-an-external-caller) |
| [Adoption evidence](ADOPTION-EVIDENCE.md) | Reproducible governance and recovery results, with their limits |
| [Troubleshooting](troubleshooting.md) | Common issues and fixes |
| [Contributor harness](DEVELOPMENT-HARNESS.md) | For people and agents working *on* docket's own codebase. Not `docket harness run`, which is the CLI's single-agent mode for an external caller |
| [Decision records (ADRs)](adr/) | One reasoned architectural decision per file |
| [Cycles ended](cycles-ended/README.md) | The archive of closed waves and phases; verbatim, hash-verified, never a source of work |

Requirements live in [`../specs/`](../specs/); the [SSD workflow guide](../SSD-WORKFLOW.md)
explains how a feature is specified before it is built.

---

## The commands you use most

```bash
# The team
docket init                                   # this directory -> a Lead + Implementer pod
docket init --recipe secure-build             # ... plus a shipped recipe (research-review, ops-approval)
docket validate                               # check every document under ./.docket/
docket pod myapp apply [--dry-run]            # apply ./.docket/ (or a recipe name/dir) onto the pod
docket pod myapp export                       # write the pod's own scope back to ./.docket/
docket roles list                             # every role: built-in, starter, yours

# Work
docket pod myapp delegate "<task>"            # queue a task
docket pipeline plan myapp                    # what would run, without running it
docket pod myapp dispatch                     # run the pipeline once, now
docket serve --dispatch                       # drain every pod's queue in the background

# The record
docket runs list                              # one row per dispatch
docket trace tail myapp                       # the latest session, step by step
docket audit && docket audit verify           # gate decisions, and the chain verifies
docket config explain myapp-implementer       # effective configuration with provenance
docket cost myapp-lead                        # measured tokens and the labelled estimate

# Models and keys
docket models provider add local http://127.0.0.1:8081/v1 --model m --ctx 16384 --max-tokens 4096
docket models preset local                    # or anthropic | openai | google | openrouter | ai-gateway
docket models set programmer <provider/model> # one role; `docket profile <id> <model>` pins one agent
docket keys add OPENROUTER_API_KEY            # stored once by name, never written into a workspace

# Health
docket status --all                           # every project at a glance
docket doctor [--fix]                         # workstation diagnostics and repairs
```

The full surface is in the [command reference](commands.md).

---

## Where things live

Everything docket owns is under `~/.docket/` (`DOCKET_HOME` relocates it). The team itself lives
in your repository:

```
<your repo>/.docket/                  # the team's configuration of record (commit it)
├── pod.yaml                          # kind: pod — members to add, settings, optional pipeline file
├── roles/<name>.yaml + <name>.md     # kind: role — what a kind of agent is, and its instructions
├── pipeline.yaml                     # kind: pipeline — who works, in what order, behind which gates
├── policies/*.yaml                   # kind: policy — what is forbidden or needs a human
└── .schemas/                         # JSON Schemas for editor autocompletion (export writes them)

~/.docket/
├── fleet.json                        # agent registration, channel bindings, isolation flag
├── docket-providers.json             # your kind: provider documents; fourteen ship built in
├── secrets.json                      # stored credentials (0600), referenced by name
├── docket-models.json                # role -> model policy and the default model
├── docket-roles.json                 # your global role overlay
├── policies/                         # global policies (most-restrictive wins with a pod's own)
├── plugins/                          # operator-scope predicate plugins (rare)
├── docket-mcp-servers.json           # external MCP tool servers
├── docket-runs.json  docket-schedules.json  docket-conversations.json
├── audit.log                         # hash-chained audit log (docket audit verify)
├── traces/  sessions/  approvals/    # per-session traces, durable history, pending approvals
└── workspaces/
    ├── manager/ knowledge/ security/ # the shared org specialists
    ├── pods/<project>/config/        # this pod's own overlay: roles.json, policies/, plugins/
    └── projects/<project>-<role>/    # one isolated workspace per pod member
        ├── SOUL.md  AGENTS.md  TOOLS.md  HEARTBEAT.md  MEMORY.md
        ├── INSTRUCTIONS.md           # yours; docket never writes it
        ├── .docket-meta.json         # role, codebase, model, verify command, pod settings (Lead)
        ├── worktree/                 # the Implementer's git worktree on its own branch
        └── memory/                   # daily logs
```

Org specialists (`manager`, `knowledge`, `security`, and the opt-in `portfolio-manager`) have one
shared workspace each. Pod members each get an isolated one; no role is ever shared between
projects. Which of these files reach a model, and which only look like settings, is the subject
of [Configuration §2](CONFIGURATION.md#2-how-the-files-reach-a-running-agent).

---

## Contributing to docs

1. **Accurate over comprehensive.** Every example runs against the current CLI; the terminal
   output shown was captured from a real run.
2. **User-focused.** Answer "how do I…" and link to the [command reference](commands.md) for detail.
3. **One owner per fact.** Adapter versions live in [COMPATIBILITY.md](../COMPATIBILITY.md),
   requirements in `specs/`, decisions in `adr/`.

Questions: `docket help`, or the [Quick start](QUICK-START-DOCKET.md).
