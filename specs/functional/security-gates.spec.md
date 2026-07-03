# Security Gates Specification

**Version**: 0.3.0
**Status**: Implemented (on by default for new installs)
**Last Updated**: 2026-07-02

## Purpose

This specification defines the tool-approval and workspace-isolation model for docket agents:
requiring explicit approval before dangerous tool calls and confining agents to their own
workspace. It is implemented on the OpenClaw daemon's native exec-approval, approval-routing,
and sandbox primitives — docket configures and verifies; the daemon enforces.

> **Implementation status.** `docket install` applies exec-approval gates **by default**
> (`--no-gates` opts out); `docket gates enable` (re-)applies the same configuration to an
> existing fleet, and `docket install --gates`/`docket gates enable` remain idempotent
> front doors for anyone who opted out earlier or is upgrading a pre-existing install. Gates
> write conservative exec-approval defaults (`security: allowlist`, `ask: on-miss`,
> `askFallback: deny`) with a curated allowlist; enabling gates also routes approval prompts to
> each agent's session (`approvals.exec`, answerable via `docket approve`/`docket deny` or, when
> Telegram-bound, `/approve`); `docket gates isolate on` applies Docker workspace isolation.
> `docket doctor` reports gate status, approval routing, isolation, and config-permission
> hardening.
>
> **Why on-by-default now.** The previous version of this spec deferred on-by-default pending
> "per-agent headless approval routing," reasoning that session-mode (Telegram) delivery "only
> answers prompts during an interactive session" and default-on "could deny an unattended agent
> with no approver." That blocking condition is now met: docket ships two headless-capable
> approval channels alongside Telegram —
>
> - **CLI channel**: `docket approve [token]` / `docket deny <token>` grant or deny a pending
>   approval from any shell (interactive or scripted); omitting the token lists everything
>   pending. No chat session required.
> - **HTTP channel**: `docket serve`'s `GET /approvals` (list) and `POST /approvals/<token>`
>   (`{"action": "grant"|"deny"}`, bearer-token authenticated) let CI jobs, cron, or any
>   automation vote on a pending approval without a human at a keyboard.
>
> Both channels operate identically to the Telegram `/approve` flow and existed before this
> flip (shipped earlier in Phase 13); this version of the spec is the first to describe them as
> real, supported approval surfaces rather than treating Telegram as the only intended one.
> Pending approvals still expire to **denied** after `APPROVAL_TIMEOUT` regardless of channel
> (see `approval_sweep_expired`), so an unattended agent with no approver at all fails closed,
> not open — the scenario the original deferral worried about is handled by the timeout, not by
> withholding the default.

## Scope

This specification covers:

- Tool-approval gates for dangerous operations
- Workspace isolation between agents
- Audit logging of approvals and denials
- The high-risk action-class policy (money-movement, prod-deploy, secret-access)

This specification does NOT cover Telegram transport (see telegram-integration.spec.md), which
is *one* channel for approval prompts — the CLI and HTTP channels above are equally real and
are owned here, not there.

## Requirements

### Tool-approval gates (implemented)

1. Dangerous operations not on the curated allowlist (e.g. `rm`, `dd`, `docker`, `systemctl`)
   **MUST** require explicit approval before execution once gates are enabled (the default for
   new installs). Note: `git`/`npm` ARE on the curated allowlist (they're used constantly for
   benign work) and so do NOT prompt by default even for a high-risk invocation like
   `git push origin main` — see "High-risk action classes" below for that specific, narrower gap.
2. Approval requests **MUST** be answerable via at least one headless channel (CLI
   `docket approve`/`docket deny`, or HTTP `POST /approvals/<token>`) in addition to Telegram.
3. Pending approvals **MUST** time out after a bounded interval (`APPROVAL_TIMEOUT`) and default
   to denied (`approval_sweep_expired`).
4. Every approval grant and denial **MUST** be recorded in the audit log
   (`audit_log("approval.grant"|"approval.deny", ...)`), tagged with the channel it came
   through (`cli`, `http`, `telegram`, ...), regardless of which channel it came through.

### High-risk action classes (implemented, partial enforcement)

1. A small, named set of high-risk action classes **MUST** be documented: money-movement,
   prod-deploy, and secret-access (`core/security.py`'s `HIGH_RISK_PATTERNS`, visible via
   `docket gates classes`).
2. For a class whose binaries have **no overlap** with the curated exec-allowlist
   (money-movement, secret-access) — those binaries were never allowlisted to begin with, so
   any invocation **MUST** already fall through to "ask" today, with no additional daemon work
   required.
3. For a class whose binaries **do overlap** the curated allowlist (prod-deploy's `git`/`npm` —
   `git push origin main`, `npm publish`, ...) — the daemon's exec-allowlist gates by resolved
   binary path only, with no argument-aware matching (confirmed via
   `openclaw approvals allowlist --help`). It genuinely **cannot** distinguish
   `git push origin main` from `git status`, so excluding `git`/`npm` wholesale to force the
   high-risk invocation to ask would also force every benign invocation to ask — an
   unacceptable usability regression for tools used constantly. **This overlap is therefore
   documented policy, not daemon-enforced**: `git`/`npm` stay on the seeded allowlist today.
   Per-argument enforcement is a deferred backlog item pending a daemon capability that does
   not exist yet — this spec does **not** claim prod-deploy's git/npm path is gated.
4. `core/security.py`'s `match_high_risk`/`is_high_risk`/`resolve_command_action` **MUST**
   remain available for any caller that has a live command string to classify (tests, a future
   daemon hook, or docket's own subprocess call sites) even though the daemon's own allowlist
   does not yet call them at approval time for allowlisted bins.

### Workspace isolation (implemented, opt-in)

1. An agent **MUST NOT** read or write outside its own workspace and codebase path.
2. Path traversal out of the workspace **MUST** be rejected (see input-validation.spec.md,
   `prevent_path_traversal`).
3. Docker workspace isolation (`docket gates isolate on`) remains **opt-in** — it requires
   Docker and is not part of the gates-default-on flip (which covers exec-approval only).

### Enablement (implemented)

1. `docket install` **MUST** apply exec-approval gates by default; `--no-gates` **MUST** be
   available as an explicit escape hatch that skips gate application entirely.
2. `docket gates enable [--force]` **MUST** remain available to apply (or re-apply) the same
   configuration to an already-installed fleet, or one that opted out at install time.
3. There **MUST** be a way to verify gate status (`docket doctor`, `docket gates status`).

## Interface Contracts

### `docket gates` command (implemented)

```bash
docket gates status            # MUST report exec-approval policy, routing, isolation, audit
docket gates enable [--force]  # MUST apply conservative exec-approval defaults + curated
                             #   allowlist and enable approval routing
docket gates disable           # MUST reset gate defaults + routing (reversible escape hatch)
docket gates isolate [on|off]  # MUST set/clear Docker workspace isolation (requires Docker; opt-in)
docket gates classes           # MUST list the documented high-risk action classes
docket install                 # MUST apply the gate configuration by default
docket install --no-gates      # MUST skip gate application (explicit opt-out)
docket doctor                  # MUST report whether security gates are configured
```

### Approval channels (implemented)

```bash
docket approve                 # List pending approvals (any channel)
docket approve <token>         # Grant a pending approval — headless, no chat session needed
docket deny <token>            # Deny a pending approval — headless, no chat session needed
GET  /approvals                # docket serve: list pending approvals (bearer auth)
POST /approvals/<token>        # docket serve: {"action": "grant"|"deny"} (bearer auth)
/approve <id> allow-once|deny  # Telegram, when the agent has a chat binding
```

## Examples

### Approval flow (implemented, any channel)

```text
[GATE] Agent 'mywebsite' requested: docker stop mywebsite-db
       Approve via: docket approve <token>  ·  docket deny <token>
       ·  POST /approvals/<token>  ·  or, if Telegram-bound, reply ✅/❌
       Times out in APPROVAL_TIMEOUT → denied.
```

Note: `docker` is not on the curated allowlist, so this example is gated today by the base
exec-approval policy alone. `git push origin main` would *not* trigger this prompt by default —
see "High-risk action classes" above for why.

## Validation

### Pre-conditions

- The OpenClaw daemon **MUST** support tool-approval hooks for this to be enforceable.

### Post-conditions

- After a default install (no `--no-gates`), dangerous operations **MUST** be gated.
- Approvals and denials **MUST** appear in the audit log, on every channel.
- A pending approval past `APPROVAL_TIMEOUT` **MUST** resolve to denied even with no approver
  reachable on any channel.

### Invariants

- A denied or timed-out request **MUST NOT** execute.
- Audit log entries **MUST NOT** be silently editable by the agent.
- A high-risk class match **MUST** force "ask" over any allowlist status, for any caller that
  classifies a live command string (see `resolve_command_action`) — even though the daemon does
  not yet call this at approval time for allowlisted bins (prod-deploy's git/npm gap above).

## Changelog

### Version 0.3.0 (2026-07-02)

- **Gates-default-on**: `docket install` now applies exec-approval gates by default;
  `--no-gates` is the explicit opt-out. Condition for the flip (headless approval routing) is
  met: the CLI (`docket approve`/`docket deny`) and HTTP (`serve.py` `GET/POST /approvals`)
  channels work without an interactive chat session, on top of the pre-existing Telegram
  channel.
- Documented the high-risk action-class policy (`HIGH_RISK_PATTERNS`, `docket gates classes`):
  money-movement/secret-access are fully enforced (no allowlist overlap); prod-deploy's
  `git`/`npm` overlap is documented policy, not daemon-enforced (deferred — the daemon's
  allowlist cannot gate by argument text).
- Documented audit-log parity: every approval grant/deny, on any channel, writes an
  `audit_log()` entry tagged with the channel.
- Docker workspace isolation (`docket gates isolate on`) remains opt-in — unaffected by this flip.

### Version 0.2.0 (2026-06-10)

- Implemented opt-in on native daemon primitives: `docket gates enable` / `isolate`,
  `docket install --gates`, and config-permission hardening
- Exec-approval enforcement (allowlist + ask/on-miss + deny fallback), Telegram approval
  routing (`approvals.exec`, `/approve`), and Docker workspace isolation
- `docket doctor` reports gate status, routing, isolation, and audit posture
- On-by-default in `docket install` deferred pending per-agent headless approval routing

### Version 0.1.0 (2026-06-09)

- Initial, spec-first definition of the intended security-gates design
- Explicitly marked Planned: install currently skips security configuration
