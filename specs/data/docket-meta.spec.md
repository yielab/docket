# Agent Metadata (.docket-meta.json) Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-09

## Purpose

This specification defines the schema for `.docket-meta.json`, the per-agent metadata file
that docket treats as its source of truth for an agent's identity and configuration. One file
exists per agent at `~/.openclaw/workspaces/projects/<agent-id>/.docket-meta.json` and is read
and written exclusively through the `meta_get` / `meta_set` helpers.

## Scope

This specification covers:

- The fields stored in `.docket-meta.json`, their types, and their meaning
- Which fields are required versus optional
- The synchronization relationship with `~/.openclaw/openclaw.json`
- Validation rules applied on read and write

It does NOT cover the OpenClaw daemon's own configuration schema (`openclaw.json`), which is
owned by the daemon; docket only mirrors a subset of fields into it via `sync_session_key()`.

## Structure

`.docket-meta.json` is a single flat JSON object. Identity fields are written once at agent
creation (`docket add`); configuration fields are updated over the agent's lifetime by commands
such as `docket profile`, `docket scope`, and `docket mode`.

| Field | Type | Required | Written by | Description |
|-------|------|----------|------------|-------------|
| `type` | string enum | Yes | `add` | Agent kind: `repo` or `task` |
| `name` | string | Yes | `add` | Human-readable display name |
| `codebase` | string (path) | repo only | `add` | Absolute path to the project; empty for `task` agents |
| `stack` | string | No | `add` | Comma-separated detected stack (e.g. `Docker,git`) |
| `model` | string | Yes | `add`, `profile` | Provider-qualified model id (e.g. `anthropic/claude-sonnet-4-6`) |
| `description` | string | No | `add` | Free-text purpose |
| `created` | string (ISO-8601) | Yes | `add` | Creation timestamp |
| `sessionKey` | string | Yes | `add`, `scope` | Isolation key `agent:<id>:<project>` |
| `projectKey` | string | Yes | `add`, `scope` | Project component of the session key (default `default`) |
| `budgetUsd` | number | No | `profile --budget` | Per-agent spend cap in USD |
| `paused` | boolean | No | `doctor`, `profile` | Whether the agent is paused (e.g. budget exceeded) |
| `pausedReason` | string | No | `doctor`, `profile` | Human-readable reason the agent was paused |

## Schema

```json
{
  "type": "repo | task",
  "name": "string",
  "codebase": "string (absolute path, repo agents only)",
  "stack": "string (comma-separated, optional)",
  "model": "string (provider/model-id)",
  "description": "string (optional)",
  "created": "string (ISO-8601)",
  "sessionKey": "agent:<id>:<project>",
  "projectKey": "string",
  "budgetUsd": 0,
  "paused": false,
  "pausedReason": "string (optional)"
}
```

Field rules:

- `type` MUST be either `repo` or `task`.
- `codebase` MUST be present and a readable absolute path when `type` is `repo`; it MAY be
  empty when `type` is `task`.
- `model` MUST be a provider-qualified id and SHOULD resolve to a known profile tier.
- `sessionKey` MUST match `agent:<id>:<project>` and its `<project>` component MUST equal
  `projectKey`.
- `budgetUsd`, when present, MUST be a non-negative number.
- Unknown fields SHOULD be preserved on write rather than dropped, so the daemon and future
  docket versions can extend the object.

## Validation

- On write, `meta_set` MUST produce valid JSON; malformed input MUST fail the command rather
  than corrupt the file.
- On read, a missing file MUST be treated as "agent not found" (return code 2), not an empty
  object.
- `sessionKey` and `projectKey` MUST stay consistent; `docket scope` updates both atomically
  and then calls `sync_session_key()` to mirror the value into `openclaw.json`.
- After any mutation, the writing command MUST call `restart_gateway()` so the daemon reloads
  the changed configuration.
- See [input-validation.spec.md](../validation/input-validation.spec.md) for the field-level
  validation functions (`validate_agent_id`, `validate_path`, `validate_model`,
  `validate_session_key`).

## Examples

A repo agent created by `docket add myshop ~/Sites/myshop`:

```json
{
  "type": "repo",
  "name": "My Shop",
  "codebase": "/home/user/Sites/myshop",
  "stack": "Docker,git",
  "model": "anthropic/claude-sonnet-4-6",
  "description": "work",
  "created": "2026-03-05T12:08:17-03:00",
  "sessionKey": "agent:myshop:default",
  "projectKey": "default"
}
```

The same agent after `docket profile myshop economy --budget 5` and being paused:

```json
{
  "type": "repo",
  "name": "My Shop",
  "codebase": "/home/user/Sites/myshop",
  "stack": "Docker,git",
  "model": "anthropic/claude-haiku-4-5",
  "description": "work",
  "created": "2026-03-05T12:08:17-03:00",
  "sessionKey": "agent:myshop:default",
  "projectKey": "default",
  "budgetUsd": 5,
  "paused": true,
  "pausedReason": "Budget cap of $5 reached"
}
```

## Changelog

### Version 1.0.0 (2026-06-09)

- Initial `.docket-meta.json` schema specification
- Documented all identity and configuration fields
- Defined required/optional fields and the openclaw.json sync contract
- Linked field-level validation to input-validation.spec.md
