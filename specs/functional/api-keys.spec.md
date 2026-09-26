# API Key Management Specification

**Version**: 1.4.0
**Status**: Complete
**Last Updated**: 2026-09-25

## Purpose

This specification defines centralized API key management: storing provider keys once, exactly
where Docket's model client resolves them, with no secondary copy anywhere else.

## Scope

This specification covers:

- Listing, adding, validating, removing, and exporting keys (`docket keys`)
- The supported key names
- The storage backends (file and OS keyring)

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

1. Keys **MUST NOT** be propagated to any per-agent file. There is no per-agent `.env` (or
   equivalent) sync path — nothing on the live turn path ever read one; `docket doctor --fix`
   deletes any workspace `.env` left over from a docket version prior to 1.4.0.
2. Docket's model endpoint resolver **MUST** read the selected provider credential directly from
   this store when no explicit process or provider-block credential overrides it; users **MUST NOT**
   need to export the key after `docket keys add`.
3. Credential presence **MUST NOT** be reported as provider readiness when the selected model has
   no callable endpoint. In particular, Anthropic/OpenAI/Google keys are stored and masked normally
   but require an explicitly registered OpenAI-compatible endpoint until Docket ships a native
   adapter for that provider.

### Backends

1. The default backend (`DOCKET_SECRETS_BACKEND` unset, or set to `file`) stores every value in
   `secrets.json`.
2. `DOCKET_SECRETS_BACKEND=keyring` **MUST** store the value itself in the OS keyring
   (`secret-tool store`) when `secret-tool` is on `PATH`; `secrets.json` then holds only a name
   index (an empty placeholder), never the secret. `add`/`rotate` **MUST** fail (exit 1) rather
   than silently fall back to plaintext storage when `secret-tool store` fails. `remove` **MUST**
   also clear the keyring entry (best-effort — a missing entry is not an error).
3. `list`, `validate`, and `export` of a keyring-backed key **MUST** resolve the real value
   through the same lookup the runtime uses (`secret-tool lookup`), never the raw index value.

## Interface Contracts

### CLI Command Signatures

```bash
docket keys                       # List (masked) — default
docket keys setup                 # Interactive wizard
docket keys add <KEY_NAME>        # Add one new key
docket keys rotate <KEY_NAME>     # Replace an existing key's value
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
Enter value for ANTHROPIC_API_KEY (hidden):
✓ Key 'ANTHROPIC_API_KEY' stored.

$ docket keys list
Stored API Keys

  ✓ ANTHROPIC_API_KEY                 sk-a****wxyz  added 2026-09-19
```

`list` shows only stored keys (an unset provider key has no row). A value longer than 12
characters is masked to its first and last four characters; anything shorter prints `****`. The
leading badge is `✓` when the value passes the local format rule for that name and `⚠` when it
does not.

## Validation

### Pre-conditions

- For `add`/`remove`, a syntactically valid `KEY_NAME` **MUST** be supplied. `add` requires an
  absent name; `rotate`/`remove` require an existing name.

### Post-conditions

- After `add`, the key **MUST** be stored, immediately resolvable by the selected model provider,
  and copied nowhere else (see Backends above for where "stored" means under `keyring`).
- After `remove`, the key **MUST NOT** remain in the central store.

### Invariants

- Listed key values **MUST** always be masked.
- The central store **MUST** be the durable source of truth for provider keys. A process environment
  variable **MAY** override it for that process without mutating the store.

## Changelog

### Version 1.4.0 (2026-09-25)

- Removed per-agent `.env` propagation entirely (P26-13): nothing on the live turn path ever
  read it, and the write left a plaintext copy of every stored key in each agent workspace with
  a brief pre-`chmod` window at umask permissions. `docket doctor --fix` now deletes any leftover
  file; `cli/_keys.py::_sync_keys_to_agents` is gone.
- The keyring backend (`DOCKET_SECRETS_BACKEND=keyring`) now actually stores through
  `secret-tool store` — previously it only changed lookups, so `keys add` under keyring still
  wrote the plaintext value to `secrets.json`. `add`/`rotate` fail closed (exit 1), never falling
  back to file storage, when the keyring write fails; `remove` clears the keyring entry too;
  `list`/`validate`/`export` resolve the real value through the same lookup instead of the
  index secrets.json now holds.

### Version 1.3.1 (2026-09-19)

- Doc-truth pass, no behavior change. Propagation requirement 1 now includes `remove`, which
  re-syncs agent `.env` files like `add`/`rotate`/`setup` (`cli/_keys.py`). The example now shows
  the real hidden-input prompt, the `Stored API Keys` header, the format badge, the
  first-four/last-four mask, and the `added` date, and drops the `(not set)` row that `list`
  never prints.

### Version 1.3.0 (2026-08-30)

- Separated credential presence from endpoint readiness so a stored direct-vendor key cannot make
  an unresolvable first run appear configured.

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
