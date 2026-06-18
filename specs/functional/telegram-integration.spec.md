# Telegram Integration Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-09

## Purpose

This specification defines how docket binds agents to Telegram groups so an operator can
interact with an agent from a mobile device. docket owns the *wiring* (which group maps to
which agent); the OpenClaw daemon owns message delivery and command handling.

## Scope

This specification covers:

- Binding a Telegram group to an agent (`docket wire`)
- Removing a binding (`docket unwire`)
- Discovery of available groups from daemon activity
- The synchronization of bindings into `openclaw.json`

This specification does NOT cover:

- The Telegram Bot API transport itself (owned by the OpenClaw daemon)
- Tool-approval gate semantics (see input-validation and security configuration)

## Requirements

### Wiring a group (docket wire)

1. **MUST** present the Telegram groups discoverable from recent daemon activity for the
   operator to choose from.
2. **MUST** write a binding mapping the selected group's chat to the target agent into
   `~/.openclaw/openclaw.json`.
3. **MUST** restart the gateway (`restart_gateway`) after writing a binding so the daemon
   picks up the change.
4. **SHOULD** show already-bound versus unbound groups so the operator does not double-bind.
5. **MUST** fall back to the interactive agent picker when no agent id is supplied.
6. **MUST NOT** invent a binding when no groups are available; it MUST instead instruct the
   operator how to create a group and add the bot.

### Unwiring a group (docket unwire)

1. **MUST** remove the binding for the given agent from `openclaw.json`.
2. **MUST** restart the gateway after removal.
3. **SHOULD** succeed silently (idempotent) if no binding exists.

### Ownership boundary

1. docket **MUST** treat message send/receive, formatting, and approval prompts as the
   daemon's responsibility; docket only manages binding state.
2. Bindings **MUST** be the single source of truth that links a chat to an agent.

## Interface Contracts

### CLI Command Signatures

```bash
# Bind a Telegram group to an agent (interactive group selection)
docket wire [agent-id]

# Remove an agent's Telegram binding
docket unwire [agent-id]
```

### Return Codes

- `0`: Success (bound / unbound / nothing to do)
- `2`: Agent not found
- `7`: OpenClaw daemon error (gateway restart failed)

## Examples

### Wiring an agent to a group

```bash
$ docket wire mywebsite
[INFO] Discovering Telegram groups from recent activity...
  1. Website Ops      (unbound)
  2. Personal Notes   (bound: blog-writer)
Select group to wire to 'mywebsite': 1
[SUCCESS] Wired 'mywebsite' to group 'Website Ops'
[INFO] Restarting gateway...
```

### Removing a binding

```bash
$ docket unwire mywebsite
[INFO] Removing Telegram binding for 'mywebsite'
[SUCCESS] Unwired 'mywebsite'
```

## Validation

### Pre-conditions

- OpenClaw daemon **MUST** be running and its bot **MUST** be a member of the target group.
- The group **MUST** have produced at least one message so it is discoverable from logs.

### Post-conditions

- After `docket wire`, `openclaw.json` **MUST** contain a binding linking the chosen chat to
  the agent, and the gateway **MUST** have been restarted.
- After `docket unwire`, no binding for the agent **MUST** remain in `openclaw.json`.

### Invariants

- A chat **MUST** map to at most one agent at a time.
- Binding changes **MUST** be followed by a gateway restart so daemon and config agree.

## Changelog

### Version 1.0.0 (2026-06-09)

- Initial Telegram integration specification
- Defined wire/unwire binding contract and the docket/daemon ownership boundary
