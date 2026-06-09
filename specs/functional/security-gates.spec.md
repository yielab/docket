# Security Gates Specification

**Version**: 0.1.0
**Status**: Planned (not yet enforced)
**Last Updated**: 2026-06-09

## Purpose

This specification defines the intended tool-approval and workspace-isolation model for rack
agents: requiring explicit approval before dangerous tool calls and confining agents to their
own workspace. It is written spec-first; the behavior below is the target design, not the
current runtime.

> **Implementation status.** `rack install` does not yet apply these gates — Step 6
> ("Configuring security best practices") currently reports "Security configuration skipped".
> This spec is the contract the implementation will be built against. Until it ships,
> security gates **MUST NOT** be described as active in user-facing material.

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

1. `rack install` **MUST** apply the gate configuration by default once implemented.
2. There **MUST** be a way to verify gate status (e.g. via `rack doctor`).

## Interface Contracts

Planned surface (subject to change as the feature is implemented):

```bash
rack doctor          # MUST report whether security gates are configured
rack maintain <id> check   # MUST (re)apply gate templates to an agent
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

### Version 0.1.0 (2026-06-09)

- Initial, spec-first definition of the intended security-gates design
- Explicitly marked Planned: install currently skips security configuration
