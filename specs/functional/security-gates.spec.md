# Security Gates Specification

**Version**: 0.3.0
**Status**: Implemented (opt-in; on-by-default deferred)
**Last Updated**: 2026-07-02

## Purpose

This specification defines the tool-approval and workspace-isolation model for docket agents:
requiring explicit approval before dangerous tool calls and confining agents to their own
workspace. It is implemented on the OpenClaw daemon's native exec-approval, approval-routing,
and sandbox primitives — docket configures and verifies; the daemon enforces.

> **Implementation status.** Shipped **opt-in**: `docket gates enable` (or `docket install --gates`)
> writes conservative exec-approval defaults (`security: allowlist`, `ask: on-miss`,
> `askFallback: deny`) with a curated allowlist; `docket gates enable` also routes approval prompts
> to each agent's session (`approvals.exec`, answerable via `/approve`); `docket gates isolate on`
> applies Docker workspace isolation. `docket doctor` reports gate status, approval routing,
> isolation, and config-permission hardening. **On-by-default in `docket install` is deferred**
> pending per-agent *headless* approval routing — session-mode delivery only answers prompts
> during an interactive session, so default-on could deny an unattended agent with no approver.
> Until that flip, default `docket install` does not enable enforcement, and gates **MUST NOT** be
> described as on-by-default in user-facing material.

## Scope

This specification covers:

- Tool-approval gates for dangerous operations
- Workspace isolation between agents
- Audit logging of approvals and denials

This specification does NOT cover Telegram transport (see telegram-integration.spec.md), which
is the intended channel for approval prompts.

## Requirements

### Tool-approval gates (target)

1. Dangerous operations (e.g. `rm`, `git push`, `docker stop`) **MUST** require explicit
   approval before execution once gates are enabled.
2. Approval requests **SHOULD** be deliverable via the agent's Telegram binding.
3. Pending approvals **SHOULD** time out after a bounded interval and default to denied.
4. Every approval and denial **MUST** be recorded in an audit log.

### Workspace isolation (target)

1. An agent **MUST NOT** read or write outside its own workspace and codebase path.
2. Path traversal out of the workspace **MUST** be rejected (see input-validation.spec.md,
   `prevent_path_traversal`).

### Enablement (target)

1. `docket install` **MUST** apply the gate configuration by default once implemented.
2. There **MUST** be a way to verify gate status (e.g. via `docket doctor`).

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
                             #   allowlist and enable approval routing (opt-in)
docket gates disable           # MUST reset gate defaults + routing (reversible escape hatch)
docket gates isolate [on|off]  # MUST set/clear Docker workspace isolation (requires Docker)
docket gates classes           # MUST list the high-risk action classes, read-only (FD-3)
docket install --gates         # MUST apply the gate configuration during install (opt-in)
docket doctor                  # MUST report whether security gates are configured
```

## Examples

### Intended approval flow (target)

```text
[GATE] Agent 'mywebsite' requested: git push origin main
       Approve? Reply ✅ to allow or ❌ to deny (times out in 5m → denied)
```

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

### Post-conditions (once implemented)

- After install, dangerous operations **MUST** be gated by default.
- Approvals and denials **MUST** appear in the audit log.

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

- FD-6 spec truth pass for Phase 13's FD-3 card: documented the high-risk action-class policy
  (`core/security.py`'s `HIGH_RISK_PATTERNS`) and its always-`ask` decision rule
  (`resolve_command_action`) — money-movement and secret-access classes are fully enforced
  today (no allowlist overlap); prod-deploy's `git`/`npm` overlap is documented policy, not
  daemon-enforced, since the daemon's exec-allowlist gates by binary path only and can't
  distinguish `git push origin main` from `git status` — per-argument enforcement is deferred
  as a backlog item, not claimed as shipped. Added the read-only `docket gates classes` command
  to the interface contract and an example of its output.
- **Note:** this entry covers the high-risk-class behavioral contract only. The
  "on-by-default deferred" status line, channel documentation, and audit-log-parity references
  above are separately being brought current by a parallel FD-5 pass — expect a merge
  reconciliation between the two changes to this file.

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
