# API Key Management Specification

**Version**: 1.2.0
**Status**: Complete
**Last Updated**: 2026-08-25

## Purpose

This specification defines centralized API key management: storing provider keys once, resolving
them in Docket's model client, and syncing only the credentials each agent needs.

## Scope

This specification covers:

- Listing, adding, validating, removing, and exporting keys (`docket keys`)
- The supported key names
- Automatic propagation of keys to agents

This specification does NOT cover provider key *format* rules (see input-validation.spec.md).

## Requirements

### Key store and supported names

1. Keys **MUST** be stored centrally and **MUST** support at least:
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `OPENROUTER_API_KEY`,
   `AI_GATEWAY_API_KEY`.
2. Listing keys **MUST** mask their values.
3. Additional `UPPERCASE_WITH_UNDERSCORES` names **MAY** be stored for tools or future providers;
   syntactically invalid names **MUST** fail clearly.

### Operations (docket keys)

1. `list` (default) **MUST** show all stored keys with masked values.
2. `setup` **MUST** run an interactive wizard to set keys.
3. `add <KEY_NAME>` **MUST** add a new key and refuse to overwrite an existing one.
4. `rotate <KEY_NAME>` **MUST** replace an existing value.
5. `validate [KEY_NAME]` **MUST** check local format rules only; it **MUST NOT** claim a live
   provider/network validation.
6. `remove <KEY_NAME>` **MUST** remove a key.
7. `export` **MUST** print keys as shell environment variable assignments.

### Propagation

1. After `setup`, `add`, or `rotate`, the key for an agent's selected model provider **MUST** be
   synced automatically to that agent. Generic custom keys **MAY** sync to every agent; Docket-owned
   operational credentials **MUST NOT**.
2. Docket's model endpoint resolver **MUST** read the selected provider credential directly from
   this store when no explicit process or provider-block credential overrides it; users **MUST NOT**
   need to export the key after `docket keys add`.

## Interface Contracts

### CLI Command Signatures

```bash
docket keys                       # List (masked) — default
docket keys setup                 # Interactive wizard
docket keys add <KEY_NAME>        # Add one new key
docket keys rotate <KEY_NAME>     # Replace an existing key and re-sync matching agents
docket keys validate [KEY_NAME]   # Check known local format rules
docket keys remove <KEY_NAME>     # Remove a key
docket keys export                # Print as env vars
```

### Return Codes

- `0`: Success
- `1`: Any error (missing/invalid arguments or invalid key-name syntax — CLI-wide convention,
  see ../api/cli-interface.spec.md)

## Examples

### Adding and listing keys

```bash
$ docket keys add ANTHROPIC_API_KEY
Enter value for ANTHROPIC_API_KEY: ****
✓ Key 'ANTHROPIC_API_KEY' stored.

$ docket keys list
  ANTHROPIC_API_KEY    sk-ant-...••••
  OPENAI_API_KEY       (not set)
```

## Validation

### Pre-conditions

- For `add`/`remove`, a syntactically valid `KEY_NAME` **MUST** be supplied. `add` requires an
  absent name; `rotate`/`remove` require an existing name.

### Post-conditions

- After `add`, the key **MUST** be stored, immediately resolvable by the selected model provider,
  and propagated only to matching agents (or according to the custom-key rule above).
- After `remove`, the key **MUST NOT** remain in the central store.

### Invariants

- Listed key values **MUST** always be masked.
- The central store **MUST** be the durable source of truth for provider keys. A process environment
  variable **MAY** override it for that process without mutating the store.

## Changelog

### Version 1.2.0 (2026-08-25)

- Added Vercel AI Gateway credentials and required the model resolver to consume centrally stored
  provider keys directly.
- Aligned propagation with the shipped least-privilege provider sync and documented supported
  custom key names instead of incorrectly rejecting all unknown names.

### Version 1.1.0 (2026-07-30)

- Truth pass (Platformization baseline): documented the shipped `docket keys rotate`
  subcommand (previously implemented but unspecified); return codes corrected to the
  real 0/1 convention (the spec'd code 4 never existed).

### Version 1.0.0 (2026-06-09)

- Initial API-key management specification
- Defined operations, supported key names, and auto-sync behavior
