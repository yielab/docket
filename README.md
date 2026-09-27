# docket — agent teams as configuration. Your rules, in YAML.

[![CI](https://github.com/yielab/docket/actions/workflows/ci.yml/badge.svg)](https://github.com/yielab/docket/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-green.svg)](https://www.python.org/)
[![Specs: 100%](https://img.shields.io/badge/spec%20coverage-100%25-success.svg)](specs/)

**docket runs a team of coding agents you define in files: which roles, in what order, behind
which gates, under which policies, on which models.** Start from a shipped recipe or write your
own, commit `.docket/` next to your code, and `docket init` provisions the team from it. A step
advances on an exit code or an explicit verdict, a risky call waits for a human or is refused, a
role that must not write has no write tool, and every run leaves a record you can verify.

Open source, one CLI, any OpenAI-compatible model (hosted or a local llama.cpp), no dashboard of
its own, no dollar figure it cannot measure. docket is not a framework you program an agent loop
with and not an interactive pair-programming harness: it runs the team your files describe.

> [!WARNING]
> docket is beta software (`v0.2.0-beta.3`). Core contracts are spec-first and test-backed, but the
> project has not been hardened against large deployments or adversarial public-host workloads.
> Expect breaking changes between beta releases and verify consequential outcomes yourself.

## The team you define

<p align="center">
  <img src="docs/assets/hero.gif" alt="Animated docket terminal journey captured from a real run against a local model: provision a pod from a recipe, validate and plan the team, dispatch a fix through Lead, Implementer and a read-only vetter with a verify gate, and verify the audit chain" width="820">
</p>

A team is a directory. Every file starts with `kind:`, reads as data, validates with one command
and has a consumer on the live path:

```text
.docket/
  pod.yaml            kind: pod       who is on the team, the pod's settings
  roles/vetter.yaml   kind: role      what a role may not do, how it is gated, its model
  roles/vetter.md                     what it is told, in plain Markdown
  pipeline.yaml       kind: pipeline  who works a task, in what order, behind which gates
  policies/*.yaml     kind: policy    what always needs a human, everywhere
```

```yaml
# roles/security-vetter.yaml          # pipeline.yaml
kind: role                             kind: pipeline
name: security-vetter                  name: secure-build
model: strong                          steps:
cannot: [write, edit, bash]              - plan: lead
verdict: [APPROVE, REQUEST-CHANGES]      - build: implementer
instructions: security-vetter.md           verify: true
                                         - vet: security-vetter
                                           verdict: [APPROVE, REQUEST-CHANGES]
                                           on: {REQUEST-CHANGES: {goto: build, max: 1}}
```

`cannot` removes the tool from the role's registry before the model sees it. `verify: true` runs
the member's verify command and a nonzero exit fails the task. `verdict` gates on the first
marker; `on` is a bounded route, never an expression. `docket init --recipe secure-build` starts
from this shipped recipe; `docket validate` checks the directory against published schemas;
`docket pipeline plan` shows the run before it happens; `docket pod <p> export` writes a pod back
into this shape; `docket config explain <agent>` prints every effective value with the layer that
set it, the provider it resolved to, and whether the repo's `.docket/` has drifted since it was
applied.

*Limit:* a pipeline is linear with bounded routes (`on`, `until`, `when`, `run`), not a DAG; the
five blueprints are code, so a new team shape is a recipe; and a recipe against a real model is
proven by running it. Nothing in `.docket/` is applied without an operator command.

## The run

<p align="center">
  <img src="docs/assets/isolation.png" alt="Real terminal output: the Implementer's dedicated workspace, codebase and session key, a separate git worktree on its own branch, a clean main checkout, and the one-line fix living only in the worktree" width="820">
</p>

`docket pod <p> delegate "<task>"` queues work; `docket pod <p> dispatch` runs one turn through
the pipeline: Lead plans, Implementer edits in its own git worktree, the verify command decides,
the Reviewer's `APPROVE` or `REQUEST-CHANGES` routes, the Tester's `PASS` closes. Rework is
counted, not hoped. The same file runs from a schedule (`@every 30m`, cron), an authenticated
`POST /dispatch/<project>`, the MCP `dispatch` tool, or `docket serve --dispatch`; nothing runs
on its own. `pod config set approvalMode refuse` makes an unattended pod fail fast instead of
waiting on nobody; `budgetUsd` pauses it on a labelled estimate. `docket harness run` executes
one agent for one turn for your own orchestrator, with a versioned result and exit codes 0 / 1 / 2.

*Limit:* one machine, one operator, no queue of workers and no tenant axis. A small local model
still varies run to run; a 16k-context endpoint is the honest integration test.

## The gate and the record

<p align="center">
  <img src="docs/assets/governance.png" alt="Real terminal output: an Implementer's git push origin production is held for approval by the high-risk-deploy policy, nobody answers, and the call is denied on timeout without executing; the audit chain then verifies clean" width="820">
</p>

Every tool call, built-in or MCP, passes one chokepoint: policy, then a classifier that reads the
whole command line (`git status` passes, `git push origin production` asks), then human approval
over CLI, HTTP, MCP or an inbound-only Telegram bot, then the budget. Fail-closed: an approval
nobody answers denies itself, and a policy file that no longer parses blocks what it governed.
`docket audit verify` checks the hash chain over every verdict, approval and execution.
`docket trace tail <p>` shows a run step by step. `docket cost` reports measured tokens and a
labelled estimate. `/status.json` and `/metrics` feed your own board; docket does not ship one.

*Limit:* the audit log is tamper-evident, not tamper-proof (one predecessor link survives
rotation). `fetch` is inspectable, but `bash` still reaches the network through allowlisted
interpreters; run untrusted work inside a stronger boundary.

## Quick start

```bash
brew tap yielab/docket-cli https://github.com/yielab/docket
brew install docket-cli
```

Or a version-pinned installer that needs no `sudo`:

```bash
curl -fsSL https://raw.githubusercontent.com/yielab/docket/v0.2.0-beta.3/install.sh \
  | DOCKET_VERSION=0.2.0-beta.3 bash
export PATH="$HOME/.local/bin:$PATH"
```

Requires Python 3.11+, Git, Bash, and a non-streaming OpenAI-compatible chat-completions endpoint
with function-tool support — hosted (Anthropic, OpenAI, Google, OpenRouter, Vercel AI Gateway and
others) or local (llama.cpp, vLLM, LM Studio, Ollama). Fourteen providers ship as readable
`kind: provider` documents (`docket models provider list`); any other endpoint is registered
explicitly, and nothing is guessed.

```bash
docket models provider add local http://127.0.0.1:8081/v1 \
  --model local-model --ctx 32768 --max-tokens 4096
docket models preset local                # every role now resolves to the local endpoint

cd ~/code/myapp
docket init --recipe secure-build         # or: commit .docket/ and run plain `docket init`
docket pod myapp delegate "Create FIRST_TURN.md containing: governed first turn"
docket pod myapp dispatch

docket runs list                          # what ran
docket trace tail myapp                   # what it did, step by step (Ctrl-C to stop)
docket audit verify                       # tamper-evident confirmation of the decision chain
docket pod myapp export                   # write the team back to .docket/ and commit it
```

`models preset local` matters: `set default` alone changes only the fallback, and the built-in role
policy would still route the Lead and Implementer to a hosted model you have no key for. For the
full walkthrough and hosted-provider variants, see the [ten-minute quick start](docs/QUICK-START-DOCKET.md).

## Use something else if

- **You want to pair with an agent interactively in your terminal.** A vendor coding harness is
  built for that; docket runs the team your files describe.
- **You want a board or a UI.** Use a worktree orchestrator, or point Tack (or your own consumer)
  at docket's read API.
- **You need hosted, multi-tenant execution.** docket is single-operator software with no tenant
  axis, hosted scheduler or quota system.

## Everything is configuration

Every layer is a file you edit or a command you run, with working defaults, so a custom setup is
configuration, never a fork:

| You want to change… | Layer | How |
| --- | --- | --- |
| The whole team, versioned with the code | Repository | commit `.docket/` (`pod.yaml`, `roles/`, `pipeline.yaml`, `policies/`); `docket init` applies it, `docket pod <p> apply` re-applies it, `docket pod <p> export` writes it back |
| A proven starting point instead of a blank page | Recipes | `docket init --recipe secure-build` (or `research-review`, `ops-approval`, or a directory of your own) |
| The team shape a new pod gets | Blueprint | `docket init --blueprint software\|research\|content\|ops\|agentic-product` |
| Who works a task, in what order, behind which gates, with how much rework | Pipeline | a `kind: pipeline` YAML; `docket pipeline validate/plan`; run once with `--file` or bind it as the pod's default for every trigger with `docket pod <p> config set pipeline <file>` |
| What a kind of agent is, what it is told each hop, which tools it structurally lacks, which model it uses | Role | a `kind: role` YAML plus its Markdown; `docket roles add`, globally or `--pod <p>`; a step may name its own `model` |
| Your own words in front of an agent | Instructions | edit the operator-owned `INSTRUCTIONS.md` (docket never touches it), or opt in your repo's own `AGENTS.md` with `pod config set projectInstructions` |
| What is forbidden or needs a human, everywhere | Policies | a `kind: policy` YAML (`when`/`then`), live on the next call; `docket policies test`/`validate`; a rare complex rule is a hashed Python predicate the operator applies |
| What one pod may run unattended | Pod settings | `pod config set allowCommands pytest,uv` · `approvalMode refuse` · `budgetUsd` · timeouts · `schedule` |
| Which model each role uses | Model policy | `docket models set <role> <provider/model>`; pin one agent with `docket profile` |
| What a provider name means: URL, dialect, model limits, which credential by name | Provider catalog | `docket models provider add <file.yaml>` (a `kind: provider` document); the key itself via `docket keys add <NAME>` |

One rule keeps the map honest: a guarantee is a docket-managed registry evaluated by code and
audited when it fires; a file the agent merely reads is advice. Every setting has one writer, is
validated when written, and is refused loudly when broken. The file-by-file map of everything an
install creates is [Configuration](docs/CONFIGURATION.md); the team-level reference is
[Agent teams](docs/AGENT-TEAMS.md).

## Also shipped

- **MCP in both directions**: `docket mcp serve` exposes the control surface; `docket mcp servers`
  wires external tool servers into the same chokepoint, `--kind read` for read-only roles.
- **Typed handoffs and context budgets** that follow the resolved model's window, with any
  truncation marked and traced rather than silent; session compaction on the live path.
- **Opt-in sandboxing** (`docket gates isolate on`, Docker or bwrap) and a deny-by-default `fetch`.
- **Retention and recovery**: `docket trace expire`, `runs prune`, `conversations prune`; a corrupt
  docket-owned JSON file recovers from its validated backup; `docket doctor --fix` repairs drift.
- **An embeddable runtime**: the standalone **`docket-runtime`** package (`pydantic` + `filelock`
  only) dispatches an application's tools through the same chokepoint; source-built, **not
  published to any index**; verified adapter configurations in [Compatibility](COMPATIBILITY.md).

## Known limits

Read these before trusting docket with anything consequential; they are the honest boundary of
what "governed" currently means. The mechanism above is automated-test-backed (see
[Adoption evidence](docs/ADOPTION-EVIDENCE.md) for reproducible results); it has not been hardened
the way the limits below describe.

- **Beta, single-operator software:** no tenant axis, hosted scheduler, quota system, or
  large-deployment claim.
- **Compatible HTTP, not provider SDK parity:** non-streaming `/chat/completions` with function
  tools. A text-only endpoint can answer text turns but cannot complete tool-dependent work.
  Anthropic documents its OpenAI-compatibility layer as intended for evaluation (no prompt caching)
  and Google documents its Gemini layer as beta; the built-in documents say so in their preset notes.
- **MCP tools are writes unless the operator says otherwise:** nothing can prove a remote tool is
  read-only, so a server left at the default reaches no read-only role. `--kind read` is an
  operator assertion, not a verified fact. Each configured stdio server is re-spawned per turn.
- **Telegram is inbound-only:** four verbs, no free-text chat, and docket never messages a chat
  first; no approval notifications, no completion reports.
- **Metrics counters are not monotonic:** they count what current storage holds, so audit
  rotation and trace retention can drop them. Do not alert on `rate()` over them.
- **Cancellation is cooperative:** `cancel requested` is durable immediately and a running `bash`
  command is killed, but a tool handler already executing may finish before its result is
  discarded at the next safe checkpoint.

Read [SECURITY.md](SECURITY.md) before exposing a service, and [COMPATIBILITY.md](COMPATIBILITY.md)
before relying on a model endpoint or MCP server.

## Documentation

| Need | Guide |
| --- | --- |
| Install and first governed turn | [Quick start](docs/QUICK-START-DOCKET.md) |
| Roles, pod shapes, handoffs, gates | [Agent teams](docs/AGENT-TEAMS.md) |
| Every installed file, every setting, recipes, the team in the repo | [Configuration](docs/CONFIGURATION.md) |
| Every command and flag | [Command reference](docs/commands.md) |
| Provider endpoints and coding harnesses | [Models and gateways](docs/MODEL-GATEWAYS.md) |
| Security posture and deployment limits | [Security model](SECURITY.md) |
| Runtime and protocol compatibility | [Compatibility](COMPATIBILITY.md) |
| Deterministic adoption evidence and limits | [Adoption evidence](docs/ADOPTION-EVIDENCE.md) |
| Architecture, state ownership, and embedding `docket-runtime` | [Architecture](docs/DOCKET.md) |
| Pipeline examples | [Workflow guide](docs/WORKFLOW-GUIDE.md) |
| Troubleshooting | [Troubleshooting](docs/troubleshooting.md) |
| Current plans and measured triggers | [Roadmap](ROADMAP.md) |
| Current executable contracts | [Specifications](specs/README.md) |
| Contributing, tests, and CI gates | [Contributing](CONTRIBUTING.md) |

## Contributing

docket uses spec-first, test-first development and a three-layer architecture, `cli → core →
edges`. Two boundaries are non-negotiable: `core/tools.py::dispatch_tool` is the sole
tool-execution chokepoint, and `edges/store.py` is the sole writer of docket-owned JSON. Start with
[CONTRIBUTING.md](CONTRIBUTING.md). New features need a measured trigger, an executable acceptance
case, and documentation that states limits as clearly as capabilities.

## License

Apache-2.0. See [LICENSE](LICENSE).
