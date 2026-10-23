# API Key Management Specification

**Version**: 2.0.1
**Status**: Complete
**Last Updated**: 2026-10-23

## Purpose

This specification defines centralized API key management: storing provider keys once, exactly
where Docket's model client resolves them, with no secondary copy anywhere else.

## Scope

This specification covers:

- Storing, rotating and removing a provider's credential (`docket setup provider`)
- The supported key names
- The storage backends (file and OS keyring)

This specification does NOT cover credential format rules beyond the warning in Operations item 1
(see input-validation.spec.md).

## Requirements

### Key store and supported names

1. Keys **MUST** be stored centrally and **MUST** support at least:
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `OPENROUTER_API_KEY`,
   `AI_GATEWAY_API_KEY`.
2. A credential value **MUST NOT** be echoed, printed or written to the audit log.
3. Additional `UPPERCASE_WITH_UNDERSCORES` names **MAY** be stored for tools or future providers
   (declared in a provider document's `auth.credentials`); syntactically invalid names **MUST**
   fail clearly when the document is loaded.

### Operations (docket setup provider)

Credentials belong to a provider; there is no separate key command.

1. `provider add <name> [url] [--credential KEY]` **MUST** store the provider's credential (the
   first name its catalog document declares under `auth.credentials`) from the flag, else from the
   process environment variable of that name, else from a hidden prompt on a terminal. Off a
   terminal with none of the three it **MUST** exit 1 naming `--credential` and write nothing.
   The value is stored only after the `/models` probe got an HTTP answer; a transport failure
   exits 1 and stores nothing.
   A value from the flag or the environment replaces a name already stored (audited as
   `keys.rotate`); a new name is audited as `keys.add`. When the name is already stored and neither
   the flag nor the environment gives a value, `add` keeps the stored value and does not prompt.
   A value that does not start with the document's `credentialPrefix` (no minimum length)
   **MUST** warn, not refuse.
2. `provider rotate <name> [--credential KEY]` **MUST** replace the stored value and refuse (exit
   1) when no credential is stored for that provider.
3. `provider remove <name> [--yes]` **MUST** confirm on a terminal and, off one, exit 1 naming
   `--yes`; a confirmation the operator declines exits 0. It removes the provider's global
   document (when it has one) and each of its stored credentials that no other catalog document
   declares. A built-in provider with no global document and nothing stored exits 1.
4. The first-run flow (`docket setup`) **MUST** store a provider's credential only through these
   functions.

### Propagation

1. Keys **MUST NOT** be propagated to any per-agent file. There is no per-agent `.env` (or
   equivalent) sync path — nothing on the live turn path ever read one.
2. Docket's model endpoint resolver **MUST** read the selected provider credential directly from
   this store when neither `DOCKET_LLM_API_KEY` nor the credential's environment variable supplies
   a value; users **MUST NOT** need to export the key after `docket setup provider add`.
3. Credential presence **MUST NOT** be reported as provider readiness when the selected model has
   no callable endpoint. A built-in hosted provider's base URL comes from its shipped
   `kind: provider` document, so a stored Anthropic/OpenAI/Google key is sufficient readiness on
   its own — no separate endpoint registration is required.

### Backends

1. The default backend (`DOCKET_SECRETS_BACKEND` unset, or set to `file`) stores every value in
   `secrets.json`.
2. `DOCKET_SECRETS_BACKEND=keyring` **MUST** store the value itself in the OS keyring
   (`secret-tool store`); `secrets.json` then holds only a name index (an empty placeholder),
   never the secret. Storing **MUST** fail (exit 1, naming `secret-tool` and
   `DOCKET_SECRETS_BACKEND`) rather than silently fall back to plaintext storage when
   `secret-tool` is not on `PATH` or `secret-tool store` fails. Removing **MUST**
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

- `0`: Success, and a `provider remove` the operator declines at the confirmation prompt
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
- After `provider remove`, each credential the removed document declares **MUST NOT** remain in the
  central store, unless another catalog document also declares it.

### Invariants

- A credential value **MUST** never be printed.
- The central store **MUST** be the durable source of truth for provider keys. When a credential
  is resolved at run time, a process environment variable **MAY** override it for that process
  without mutating the store.

## Implementation

- `src/docket/config.py`: `DOCKET_HOME`, `secrets_backend_requested` (`DOCKET_SECRETS_BACKEND`), `KEYRING_SERVICE`
- `src/docket/core/secrets.py`: `secret_value`, `secret_values`, `store_backend`, `touch_meta`, `SECRETS_FILE` (`secrets.json`)
- `src/docket/cli/_setup_model.py`: `provider add`, `provider rotate`, `provider remove` and the credential writes they share
- `src/docket/core/provider.py`: `resolve_credential`, `model_readiness`, `ProviderSpec` (`credentialPrefix`, `auth.credentials`) and its name validator
- `src/docket/edges/adapters/system.py`: `secret_tool_available`, `secret_tool_store`, `secret_tool_lookup`, `secret_tool_clear`
- `src/docket/templates/providers/`: the built-in `kind: provider` documents
