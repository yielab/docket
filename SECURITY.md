# Security Policy

## Supported Versions

docket is a personal R&D project under active development. Security fixes are applied to the
`main` branch only; there are no long-term support branches.

| Version | Supported |
| ------- | --------- |
| `main`  | ✅        |
| older tags | ❌     |

## Reporting a Vulnerability

If you find a security issue in docket itself (for example, command injection, unsafe handling
of API keys, or path traversal in workspace handling), please report it privately rather than
opening a public issue.

- **Preferred:** open a [private security advisory](https://github.com/yielab/docket/security/advisories/new) on this repository.
- **Alternative:** email the maintainer at `info@yielab.com` with the subject `docket security`.

Please include:

- A description of the issue and its impact
- Steps to reproduce (a minimal command sequence is ideal)
- The docket commit/version, your OS, and your Python version (`python3 --version`)

**Disclosure timeline.** You can expect an initial acknowledgement within a few days. I aim to
ship a fix or a documented mitigation within **90 days** of a valid report; the advisory is then
published with credit to the reporter (unless you prefer to remain anonymous). If a report is
being actively exploited, please say so and I will prioritize it.

## Threat model: what runs with what privileges

**docket runs the agent turn itself** (`core/agent_loop.py`) — it is not a thin wrapper around
an external daemon. The thing that holds privilege is docket's own tool dispatcher
(`core/tools.py`'s `dispatch_tool`, the single chokepoint every tool call passes through) and
the handlers it calls into (`edges/adapters/toolbox.py`'s `bash`/`write`/`edit`/`read`/`glob`/
`grep`, `edges/adapters/fetch.py`'s domain-allowlisted `fetch`, plus any MCP server an operator
has added). docket:

- writes its own config (`.docket-meta.json` per workspace, `~/.docket/fleet.json`, and the
  rest of `~/.docket/` — see `src/docket/config.py`) and reads cost and health data;
- runs as your user; it does **not** require or request root for normal operation;
- enforces `700` on workspace dirs and `600` on files, and keeps secrets out of `argv`
  (values flow via stdin/env/inside-Python, never as process arguments — no `/proc` leakage).

### External-runtime adapter boundary

The separately built `docket-runtime` package has artifact-tested adapters for OpenHands SDK
1.44.1 and PydanticAI 2.37.0. Their governance claim applies only when the model-visible tools are
exclusively Docket-backed: each translated call then reaches the existing policy, approval, trace,
audit, and dispatcher chokepoint. The adapter is not a sandbox around its host framework. Enabling
native/provider tools, plugins/MCP, or an additional toolset beside Docket creates execution paths
outside this proof and may bypass Docket policy entirely. See [Compatibility](COMPATIBILITY.md) for
the exact configurations and exclusions.

**The approval-gate model.** Agent-level safety constraints are *instruction-based* (written
into each agent's `SOUL.md` prompt) — guidance, not enforcement, on their own. On top of that,
`docket install` **enforces tool-approval gates by default** (opt out with `--no-gates`): a
curated allowlist plus an approval step for dangerous operations not on it (e.g. `rm`, `dd`,
`docker`), with a fail-closed default — a call gated `ask` blocks on docket's own approval
store (`core/approval.py`) and times out to **denied**, never left pending. Approvals are
answerable through **four channels** — `docket approve`/`docket deny` from any shell, `docket
serve`'s `POST /approvals/<token>` for CI/automation, MCP (a client like Claude Code or Codex
answering through `docket mcp serve`), and Telegram (`docket wire`) — and every grant, deny, or
timeout is audit-logged with the channel it came from
(`channel="cli"|"http"|"mcp"|"telegram"|"timeout"`). The classifier behind this
(`core/security.py`'s `classify_command`) is **argument-aware**: it reads the whole command
line, including every segment behind a `;`, `&&`, `||`, or pipe, so `git status` is allowed
while `git push origin production` asks — `git`/`npm` stay on the curated allowlist for
usability, but that no longer means their dangerous invocations are unexamined.

`docket gates isolate on` is a separate, still opt-in layer that additionally confines tool
execution to a per-agent Docker (or `bwrap`) sandbox. It **fails closed**: with isolation on and no
usable backend, the turn is refused before any model call or tool execution and the refusal is
audit-logged, rather than silently running unsandboxed.

Re-apply or reverse gate config anytime with `docket
gates enable`/`docket gates disable`. `docket doctor` and `docket gates status` report the live
posture. See
[`specs/functional/security-gates.spec.md`](specs/functional/security-gates.spec.md)
(Status: Implemented, on by default for new installs).

## `docket mcp serve`: the control plane over MCP

`docket mcp serve` (ROADMAP Phase 18 L-3) exposes docket's control plane — pods, task queue,
dispatch, the run registry, HITL approvals, and recorded cost — as MCP (Model Context Protocol)
tools over stdio, so a client like Claude Code or Codex can drive docket the same way a human
would from a shell. It changes docket's *surface*, not its *model*: every tool call goes through
the exact same audit log, approval gate, and dispatch pipeline a CLI invocation does — there is no
MCP-specific bypass, and every call (including read-only ones) is audit-logged. Trust boundary:
whoever can spawn the `docket mcp serve` process can do anything the CLI can do — the same
boundary the CLI itself already has, since the server only speaks stdio (no network listener, no
bearer token, unlike `docket serve`'s HTTP API). See
[`specs/api/mcp-server.spec.md`](specs/api/mcp-server.spec.md).

**This is a server, and separately also a client.** `docket mcp serve` never executes another MCP
server's tools inside an agent turn — that direction is a different feature, `docket mcp servers
add/list/remove` (`core/mcp_tools.py`, `edges/adapters/mcp_client.py`), which adapts a configured
external server's tools into ordinary registry entries so they are gated exactly like a built-in,
namespaced `mcp__<server>__<tool>` so a remote server cannot shadow `bash`. A remote tool's
name/description is screened through the `pre_input` policy hook before it is ever registered,
since it is untrusted input arriving as tool metadata rather than task text. See
[`specs/functional/mcp-client.spec.md`](specs/functional/mcp-client.spec.md) for the current
status, including what is configured/gated versus what is wired into a live turn today.

## Where you run docket matters: homelab vs. public VPS

> **Homelab / trusted single-user machine — relatively safe.** You are the only operator, the
> blast radius is your own box, and instruction-level constraints plus human review are usually
> proportionate. Budget caps and session isolation are the features doing the most work here.
>
> **Public VPS / shared / internet-exposed host — treat as dangerous.** An autonomous agent
> with exec access on an exposed host is a serious liability. Gates are on by default, but also
> **enable workspace isolation** (`docket gates isolate on` — it fails closed if no backend is
> available), use the `keyring` secret
> backend, and never run with broad ambient credentials. Instruction-level constraints alone
> are *not* sufficient here — and remember network egress is not fully locked down (see below):
> `bash` can still reach the network through interpreters and package managers on the curated
> allowlist even with gates on.

## Secret storage

API keys are stored via a pluggable backend (`DOCKET_SECRETS_BACKEND`):

- `file` (default) — a `0600`-permissioned JSON file at rest;
- `keyring` — the OS keyring (libsecret), with no plaintext key values at rest (docket keeps only
  a names-only index). Prefer this on any shared or exposed host.

## What docket does NOT protect against

docket is honest about its limits. It does **not**:

- **fully lock down network egress.** `fetch` is domain-allowlisted and refuses everything by
  default until you opt a domain in (`FETCH_ALLOWED_DOMAINS`) — but `bash` can still reach the
  network through interpreters and package managers on the curated allowlist (`SAFE_BINS` in
  `core/security.py`, e.g. `python3`, `pip`, `npm`, `git`). `fetch` is the *inspectable* path,
  not yet the *only* one. Tracked as an open gap, not glossed over — see `README.md`'s "What's
  next".
- sandbox or contain the model endpoint itself, or a remote MCP server's own process — if a
  model or an MCP server is compromised, docket's gates constrain what it can ask docket's
  tools to do, but do not contain the endpoint/server itself;
- defend against a malicious or prompt-injected agent when gates were explicitly disabled
  (`--no-gates` at install, or `docket gates disable` later);
- audit or vet the code your agents write or the third-party MCP servers they invoke — a
  gated MCP tool call still runs whatever that server implements;
- encrypt data at rest beyond the `0600`/keyring options above, or protect against an attacker
  who already has your user account or root;
- guarantee budget caps are instantaneous — they pause on the next reported usage tick, so a
  single in-flight call can overshoot;
- enforce anything on a process started **outside** docket's own turn loop — gating covers
  every tool call docket itself dispatches, which is not the same as being a system-wide
  enforcement daemon.

Run docket and its agents only in environments you trust, enable enforced gates on anything
exposed, and review agent output before acting on it.

See [docs/SECURITY-SIMPLE.md](docs/SECURITY-SIMPLE.md) for the full security model.
