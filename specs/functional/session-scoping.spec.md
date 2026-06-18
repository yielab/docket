# Session Scoping Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-09

## Purpose

This specification defines session scoping: the mechanism that isolates an agent's memory and
context per project using a session key, so work on one project does not contaminate another.

## Scope

This specification covers:

- The session-key format and its relationship to the project key
- Showing, setting, and resetting an agent's scope (`docket scope`)
- How scope changes propagate to the daemon

This specification does NOT cover the workspace file layout (see workspace-structure.spec.md).

## Requirements

### Session key

1. Every agent **MUST** have a session key of the form `agent:<id>:<project>`.
2. The `<project>` component **MUST** equal the agent's `projectKey` field.
3. The default project key **MUST** be `default`.
4. Session keys **MUST** be stored in both `.docket-meta.json` and mirrored into
   `openclaw.json` so the daemon scopes memory correctly.

### Scope operations (docket scope)

1. `show` **MUST** display the current session and project keys (default action).
2. `set <project-key>` **MUST** update both the session key and project key and re-sync the
   daemon.
3. `reset` **MUST** return the agent to the `default` project key.
4. A project key **MUST** be alphanumeric with dashes (see input-validation.spec.md).
5. After any change, the command **MUST** restart the gateway so the daemon reloads scope.

### Isolation guarantee

1. Two agents, or one agent under two project keys, **MUST NOT** share memory context.
2. Changing scope **MUST NOT** delete existing memory; it switches the active context.

## Interface Contracts

### CLI Command Signatures

```bash
docket scope <agent-id> show           # Show current session/project key
docket scope <agent-id> set <project>  # Switch to a project context
docket scope <agent-id> reset          # Return to the default context
```

### Return Codes

- `0`: Success
- `2`: Agent not found
- `4`: Invalid action or project key

## Examples

### Switching project context

```bash
$ docket scope mywebsite set alpha
[INFO] Session key: agent:mywebsite:alpha
[SUCCESS] Scope set to 'alpha' for 'mywebsite'
[INFO] Restarting gateway...

$ docket scope mywebsite reset
[SUCCESS] Scope reset to 'default' for 'mywebsite'
```

## Validation

### Pre-conditions

- The target agent **MUST** exist.
- For `set`, a project-key argument **MUST** be supplied and valid.

### Post-conditions

- After `set`, `sessionKey` and `projectKey` in `.docket-meta.json` **MUST** reflect the new
  project, and the same value **MUST** be mirrored into `openclaw.json`.
- After `reset`, the project key **MUST** be `default`.

### Invariants

- `sessionKey` **MUST** always equal `agent:<id>:<projectKey>`.
- A scope change **MUST** be followed by a gateway restart.

## Changelog

### Version 1.0.0 (2026-06-09)

- Initial session-scoping specification
- Defined session-key format, scope operations, and isolation guarantee
