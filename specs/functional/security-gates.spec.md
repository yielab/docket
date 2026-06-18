# Security Gates Specification

**Version**: 0.2.0
**Status**: Implemented (opt-in; on-by-default deferred)
**Last Updated**: 2026-06-10

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

## Interface Contracts

### `docket gates` command (implemented)

```bash
docket gates status            # MUST report exec-approval policy, routing, isolation, audit
docket gates enable [--force]  # MUST apply conservative exec-approval defaults + curated
                             #   allowlist and enable approval routing (opt-in)
docket gates disable           # MUST reset gate defaults + routing (reversible escape hatch)
docket gates isolate [on|off]  # MUST set/clear Docker workspace isolation (requires Docker)
docket install --gates         # MUST apply the gate configuration during install (opt-in)
docket doctor                  # MUST report whether security gates are configured
```

## Examples

### Intended approval flow (target)

```text
[GATE] Agent 'mywebsite' requested: git push origin main
       Approve? Reply ✅ to allow or ❌ to deny (times out in 5m → denied)
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

## Changelog

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
