# API Key Management Specification

**Version**: 1.8.0
**Status**: Complete
**Last Updated**: 2026-10-03

## Purpose

This specification defines centralized API key management: storing provider keys once, exactly
where Docket's model client resolves them, with no secondary copy anywhere else.

## Scope

This specification covers:

- Storing, rotating and removing a provider's credential (`docket setup provider`)
- The supported key names
- The storage backends (file and OS keyring)

This specification does NOT cover provider key *format* rules (see input-validation.spec.md).

## Requirements

### Key store and supported names

1. Keys **MUST** be stored centrally and **MUST** support at least:
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `OPENROUTER_API_KEY`,
   `AI_GATEWAY_API_KEY`.
2. A credential value **MUST NOT** be echoed, printed or written to the audit log.
3. Additional `UPPERCASE_WITH_UNDERSCORES` names **MAY** be stored for tools or future providers;
   syntactically invalid names **MUST** fail clearly.

### Operations (docket setup provider)

Credentials belong to a provider; there is no separate key command.

1. `provider add <name> [url] [--credential KEY]` **MUST** store the provider's credential (the
   first name its catalog document declares under `auth.credentials`) from the flag, else from the
   process environment variable of that name, else from a hidden prompt on a terminal. Off a
   terminal with none of the three it **MUST** exit 1 naming `--credential` and write nothing.
   A name already stored is replaced (audited as `keys.rotate`), a new one is audited as
   `keys.add`; a value that fails the document's credential-format hint **MUST** warn, not refuse.
2. `provider rotate <name> [--credential KEY]` **MUST** replace the stored value and refuse (exit
   1) when no credential is stored for that provider.
3. `provider remove <name> [--yes]` **MUST** confirm on a terminal and, off one, exit 1 naming
   `--yes`. It removes the provider's global document and each of its stored credentials that no
   other catalog document declares.
4. The first-run flow (`docket setup`) **MUST** reach credentials only through these functions.

### Propagation

1. Keys **MUST NOT** be propagated to any per-agent file. There is no per-agent `.env` (or
   equivalent) sync path — nothing on the live turn path ever read one.
2. Docket's model endpoint resolver **MUST** read the selected provider credential directly from
   this store when no explicit process or provider-block credential overrides it; users **MUST NOT**
   need to export the key after `docket setup provider add`.
3. Credential presence **MUST NOT** be reported as provider readiness when the selected model has
   no callable endpoint. A built-in hosted provider's base URL comes from its shipped
   `kind: provider` document (`core.provider`'s catalog), so a stored Anthropic/OpenAI/Google
   key is sufficient readiness on its own — no separate endpoint registration is required.

### Backends

1. The default backend (`DOCKET_SECRETS_BACKEND` unset, or set to `file`) stores every value in
   `secrets.json`.
2. `DOCKET_SECRETS_BACKEND=keyring` **MUST** store the value itself in the OS keyring
   (`secret-tool store`) when `secret-tool` is on `PATH`; `secrets.json` then holds only a name
   index (an empty placeholder), never the secret. Storing **MUST** fail (exit 1) rather
   than silently fall back to plaintext storage when `secret-tool store` fails. Removing **MUST**
   also clear the keyring entry (best-effort — a missing entry is not an error).
3. Resolving a keyring-backed credential **MUST** use the same lookup the runtime uses
   (`secret-tool lookup`), never the raw index value.

## Interface Contracts

### CLI Command Signatures

```bash
docket setup provider add <name> [url] [--credential KEY]   # Store, probe, register, apply preset
docket setup provider rotate <name> [--credential KEY]      # Replace the stored value
docket setup provider remove <name> [--yes]                 # Remove the provider and its credential
```

### Return Codes

- `0`: Success
- `1`: Any error (missing credential or confirmation, unreachable endpoint, unknown provider —
  CLI-wide convention, see ../api/cli-interface.spec.md)

## Examples

### Adding a provider with its credential

```bash
$ docket setup provider add anthropic
Enter value for ANTHROPIC_API_KEY (hidden):
✓ Provider anthropic: https://api.anthropic.com/v1
✓ lead -> anthropic/claude-haiku-4-5, implementer -> anthropic/claude-sonnet-4-6
→ Next: docket setup
```

## Validation

### Pre-conditions

- For `rotate`, a credential **MUST** already be stored; `remove` requires a known provider.

### Post-conditions

- After `provider add`, the credential **MUST** be stored, immediately resolvable by the selected model provider,
  and copied nowhere else (see Backends above for where "stored" means under `keyring`).
- After `provider remove`, the credential **MUST NOT** remain in the central store.

### Invariants

- A credential value **MUST** never be printed.
- The central store **MUST** be the durable source of truth for provider keys. A process environment
  variable **MAY** override it for that process without mutating the store.

## Changelog

### Version 1.8.0 (2026-10-07)

- `docket keys` is removed; credentials belong to a provider. Operations are now
  `setup provider add|rotate|remove` (`cli/_setup_model.py`); `list`, `validate`, `export` and
  the `keys setup` wizard are gone, and the first-run flow reaches credentials only through
  these functions. Removal asks for confirmation (`--yes` off a terminal).

### Version 1.7.0 (2026-10-03)

- Propagation 1 no longer promises that `docket doctor --fix` deletes a workspace `.env` left
  by a pre-1.4.0 docket: that doctor check was removed with the other legacy cleanups (no users;
  legacy compatibility removed). The no-propagation rule itself is unchanged.

### Version 1.6.0 (2026-09-27)

- `setup` (Operations requirement 2) now iterates the provider catalog instead of a hard-coded
  five-provider tuple: every built-in document that declares `auth.credentials` is prompted for,
  in catalog order, hinted by the document's credential-format field when present
  (`cli/_keys.py::_keys_setup`). This is the wizard's only path onto those credentials now that
  `docket auth` is retired (Phase 29, D-45) -- see ../api/cli-interface.spec.md 1.42.0.
### Version 1.5.0 (2026-09-27)

- **P29-2: a stored key is sufficient for a built-in hosted provider.** Amended "Propagation"
  3: the "until Docket ships a native adapter" clause is gone — Anthropic, OpenAI and Google now
  ship as built-in `kind: provider` documents (model-profiles.spec.md v2.12.0), so their base
  URL needs no separate registration and a stored credential alone satisfies readiness.

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
