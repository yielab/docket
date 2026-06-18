# API Key Management Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-09

## Purpose

This specification defines centralized API key management: storing provider keys once and
auto-syncing them to all agents, so individual agents never need keys configured by hand.

## Scope

This specification covers:

- Listing, adding, validating, removing, and exporting keys (`docket keys`)
- The supported key names
- Automatic propagation of keys to agents

This specification does NOT cover provider key *format* rules (see input-validation.spec.md).

## Requirements

### Key store and supported names

1. Keys **MUST** be stored centrally and **MUST** support at least:
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `OPENROUTER_API_KEY`.
2. Listing keys **MUST** mask their values.

### Operations (docket keys)

1. `list` (default) **MUST** show all stored keys with masked values.
2. `setup` **MUST** run an interactive wizard to set keys.
3. `add <KEY_NAME>` **MUST** add or update a single key.
4. `validate [KEY_NAME]` **MUST** test whether keys work.
5. `remove <KEY_NAME>` **MUST** remove a key.
6. `export` **MUST** print keys as shell environment variable assignments.

### Propagation

1. After `setup` or `add`, keys **MUST** be synced automatically to all agents.
2. An unknown key name **MUST** fail with return code 4.

## Interface Contracts

### CLI Command Signatures

```bash
docket keys                       # List (masked) — default
docket keys setup                 # Interactive wizard
docket keys add <KEY_NAME>        # Add or update one key
docket keys validate [KEY_NAME]   # Test keys
docket keys remove <KEY_NAME>     # Remove a key
docket keys export                # Print as env vars
```

### Return Codes

- `0`: Success
- `4`: Unknown key name

## Examples

### Adding and listing keys

```bash
$ docket keys add ANTHROPIC_API_KEY
Enter value for ANTHROPIC_API_KEY: ****
[SUCCESS] Key stored and synced to all agents

$ docket keys list
  ANTHROPIC_API_KEY    sk-ant-...••••
  OPENAI_API_KEY       (not set)
```

## Validation

### Pre-conditions

- For `add`/`remove`, a supported `KEY_NAME` **MUST** be supplied.

### Post-conditions

- After `add`, the key **MUST** be stored and propagated to every agent.
- After `remove`, the key **MUST NOT** remain in the central store.

### Invariants

- Listed key values **MUST** always be masked.
- The central store **MUST** be the single source of truth for provider keys.

## Changelog

### Version 1.0.0 (2026-06-09)

- Initial API-key management specification
- Defined operations, supported key names, and auto-sync behavior
