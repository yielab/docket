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
> (`--no-gates` opts out; `--gates` is the explicit, redundant form of the default). `docket
> gates enable [--force]` remains available to (re-)apply the same configuration to an
> already-installed fleet, or one that opted out at install time. Gates
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

### High-risk action classes (implemented, FD-3)

1. `core/security.py` **MUST** define a small, built-in, named list of high-risk action
   classes (`HIGH_RISK_PATTERNS`): today, `money-movement`, `prod-deploy`, and `secret-access`.
   Each class's pattern **MUST** be matched, case-insensitively, against the full command
   string (e.g. `"git push origin production"`), not just the invoked binary name. This is
   intentionally a small policy seed, not exhaustive coverage; it is not yet user-configurable
   (a config-file override is a natural follow-up, not implemented today).
2. For any caller that has an actual command string to classify (`resolve_command_action`,
   used by tests and available to any future daemon hook or docket subprocess call site), a
   high-risk pattern match **MUST** always resolve to `ask`, regardless of whether the invoked
   binary's resolved path is present in the curated allowlist — allowlist membership **MUST
   NOT** bypass a high-risk match in this decision function.
3. **Money-movement** and **secret-access** classes **MUST** be treated as fully enforced by
   the shipped allowlist gate today: none of their named bins (`stripe`, `paypal`,
   `ssh-keygen`, `vault`, etc.) are members of the curated `SAFE_BINS` allowlist, so any live
   agent invocation matching these classes already falls through to `ask` under
   `docket gates enable`'s existing exec-approval config — no additional wiring was needed.
4. **Prod-deploy** is a documented policy, **not fully daemon-enforced**, for its two bins that
   overlap the curated allowlist (`git`, `npm`): the OpenClaw daemon's own exec-approval
   allowlist gates by resolved binary path only, with no argument-aware matching (confirmed via
   `openclaw approvals allowlist --help` — entries are bare glob paths like `/usr/bin/git`, no
   denylist concept). It genuinely cannot distinguish `git push origin main` from
   `git status`, or `npm publish` from `npm test`, at the binary-path level the daemon actually
   gates on. Excluding `git`/`npm` from the allowlist wholesale to force prod-deploy
   invocations to `ask` was evaluated and rejected — it would also force every benign,
   constant-use invocation of those tools to `ask`, an unacceptable usability regression. **This
   MUST NOT be described as fully enforced** in user-facing material; per-argument enforcement
   for allowlisted bins is deferred pending a daemon-side capability that does not exist today,
   and is tracked as a backlog item, not shipped behavior.
5. The full high-risk class list — name, description, pattern, and (for prod-deploy) which
   allowlisted bins it overlaps and therefore does not yet fully gate — **MUST** be visible,
   read-only, via `docket gates classes`. This command **MUST NOT** change any configuration.

## Interface Contracts

### `docket gates` command (implemented)

```bash
docket gates status            # MUST report exec-approval policy, routing, isolation, audit
docket gates enable [--force]  # MUST apply conservative exec-approval defaults + curated
                             #   allowlist and enable approval routing
docket gates disable           # MUST reset gate defaults + routing (reversible escape hatch)
docket gates isolate [on|off]  # MUST set/clear Docker workspace isolation (requires Docker; opt-in)
docket gates classes           # MUST list the documented high-risk action classes, read-only
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

### High-risk action classes (implemented)

```text
$ docket gates classes
High-risk action classes

  Documented action classes considered especially consequential
  (money movement, prod deploys, secret access).

money-movement — Payment/financial operations: charges, refunds, payouts, transfers
  pattern: \bstripe\b|\bpaypal\b|\bbraintree\b|charge\s+customer|refund.*amount|...
  none of this class's bins are in the curated allowlist — always asks today

prod-deploy — Production deploys and release pushes
  pattern: git\s+push\s+.*\b(main|master|production|prod)\b|npm\s+publish|...
  overlaps curated allowlist bins: git, npm — daemon gates by binary path only, so these
  bins stay allowlisted; per-argument enforcement is not yet available (deferred)

secret-access — Secret/credential writes and key generation
  pattern: vault\s+(write|kv\s+put)|ssh-keygen|openssl\s+genrsa|...
  none of this class's bins are in the curated allowlist — always asks today
```

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
- A high-risk pattern match **MUST NOT** be bypassed by allowlist status in
  `resolve_command_action` for classes with no allowlist overlap (money-movement,
  secret-access) — those are fully enforced today. Prod-deploy's `git`/`npm` overlap **MUST
  NOT** be claimed as enforced until per-argument daemon support exists; it remains a
  documented policy only.

## Changelog

### Version 0.3.0 (2026-07-02)

- **Gates-default-on**: `docket install` now applies exec-approval gates by default;
  `--no-gates` is the explicit opt-out. Condition for the flip (headless approval routing) is
  met: the CLI (`docket approve`/`docket deny`) and HTTP (`serve.py` `GET/POST /approvals`)
  channels work without an interactive chat session, on top of the pre-existing Telegram
  channel.
- Documented the high-risk action-class policy (`core/security.py`'s `HIGH_RISK_PATTERNS`,
  `docket gates classes`) and its always-`ask` decision rule (`resolve_command_action`):
  money-movement and secret-access classes are fully enforced today (no allowlist overlap —
  those bins were never allowlisted, so any invocation already falls through to `ask`);
  prod-deploy's `git`/`npm` overlap is documented policy, not daemon-enforced, since the
  daemon's exec-allowlist gates by binary path only and can't distinguish
  `git push origin main` from `git status` — per-argument enforcement is deferred as a
  backlog item, not claimed as shipped. Added the read-only `docket gates classes` command to
  the interface contract with an example of its output.
- Documented audit-log parity: every approval grant/deny, on any channel, writes an
  `audit_log()` entry tagged with the channel (`cli`, `http`, `telegram`).
- Docker workspace isolation (`docket gates isolate on`) remains opt-in — unaffected by this flip.
- Fixed a pre-existing spec inconsistency: the gated-example used to be `git push origin main`,
  but `git` is on the curated allowlist — replaced with `docker stop`, with an explicit note
  that `git push` is not blocked by the base gate alone.

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
