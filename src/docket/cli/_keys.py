"""docket keys — API key management, the only model-provider-credential path.

``run_keys(sub, extra)`` returns the process exit code; the coordinator wraps
it in a Typer command and raises ``typer.Exit(code)``. Secrets live in
``~/.docket/secrets.json`` / ``secrets.meta.json`` (``core/secrets.py``) —
docket-owned JSON written through ``edges/store.py``.

``docket auth`` is a removed command: there is no docket-native login flow, and the provider
catalog (``docket models provider add``, ``core/provider.py``) is the credential-status surface
now. There is no ``run_auth`` here — see ``__main__.py``'s ``_REMOVED["auth"]`` for the
retirement notice. ``_keys_setup`` below is the interactive wizard onto stored credentials; it
walks the provider catalog (``core/provider.py::load_catalog``) rather than a fixed provider
list, so it never lags a newly cataloged provider.
"""

from __future__ import annotations

import getpass as _getpass
import re as _re
import sys
from typing import Any

import docket.config as _cfg
from docket import ui
from docket.cli._flags import find_unknown_flag
from docket.core import provider as _provider
from docket.core import secrets as _secrets
from docket.core.audit import audit_log
from docket.edges.adapters import system as _system


def _load_secrets() -> dict[str, str]:
    return _secrets.load_secrets()


def _save_secrets(secrets: dict[str, str]) -> None:
    _secrets.save_secrets(secrets)


def _load_secrets_meta() -> dict[str, Any]:
    return _secrets.load_secrets_meta()


def _touch_secrets_meta(name: str, event: str) -> None:
    _secrets.touch_meta(name, event)


def _keyring_active() -> bool:
    """True when the keyring backend is requested and `secret-tool` is on PATH -- the same
    check `core/secrets.py`'s `secret_value()`/`secret_values()` each make locally (no shared
    cache to invalidate; see those functions for why)."""
    return _cfg.secrets_backend_requested() == "keyring" and _system.secret_tool_available()


def _resolve_display_value(name: str, raw_value: str) -> str:
    """Resolve the value to mask/validate/export for *name* -- under the keyring backend,
    secrets.json holds only a name index, so this goes through `core.secrets.secret_value`
    (file vs. keyring) rather than trusting the raw dict value directly."""
    return _secrets.secret_value(name) or raw_value


def _mask_key(value: str) -> str:
    if len(value) > 12:
        return value[:4] + "****" + value[-4:]
    return "****"


def _validate_key_format(name: str, value: str) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty if ok. The prefix hint comes from the catalog
    entry that declares *name* as one of its ``auth.credentials``."""
    from docket.core import provider as _prov

    prefix = ""
    for spec in _prov.load_catalog().entries.values():
        if name in spec.auth.credentials and spec.credential_prefix:
            prefix = spec.credential_prefix
            break
    if prefix and not value.startswith(prefix):
        return False, f"should start with '{prefix}'"
    return True, ""


def _keys_list() -> int:
    secrets = _load_secrets()
    if not secrets:
        ui.info("No API keys stored yet.")
        ui.console.print("  Add a key: docket keys add <KEY_NAME>")
        ui.console.print("  Interactive setup: docket keys setup")
        return 0

    ui.header("Stored API Keys")
    ui.console.print()
    meta = _load_secrets_meta()
    for name, raw_value in sorted(secrets.items()):
        value = _resolve_display_value(name, raw_value)
        masked = _mask_key(value)
        entry = meta.get(name, {})
        added = entry.get("added_at", "")[:10] if entry else ""
        date_str = f"  added {added}" if added else ""
        ok, _ = _validate_key_format(name, value)
        badge = "[green]✓[/green]" if ok else "[yellow]⚠[/yellow]"
        ui.console.print(f"  {badge} {name:<32}  {masked}{date_str}")
    ui.console.print()
    return 0


def _keys_add(name: str) -> int:
    if not _re.match(r"^[A-Z][A-Z0-9_]*$", name):
        ui.error(
            f"Invalid key name '{name}'. Use UPPERCASE_WITH_UNDERSCORES (e.g. ANTHROPIC_API_KEY)."
        )
        return 1

    secrets = _load_secrets()
    if name in secrets:
        ui.warn(f"Key '{name}' already exists. Use 'docket keys rotate' to update it.")
        return 1

    try:
        value = _getpass.getpass(f"Enter value for {name} (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.warn("\nAborted.")
        return 0

    if not value:
        ui.error("Value cannot be empty.")
        return 1

    ok, reason = _validate_key_format(name, value)
    if not ok:
        ui.warn(f"Key format warning: {reason}")

    if _keyring_active():
        if not _system.secret_tool_store(_cfg.KEYRING_SERVICE, name, value):
            ui.error(
                f"Could not store '{name}' in the OS keyring (secret-tool store failed).\n"
                "  Not falling back to plaintext storage under DOCKET_SECRETS_BACKEND=keyring."
            )
            return 1
        secrets[name] = ""  # index only; the real value lives in the keyring
    else:
        secrets[name] = value
    _save_secrets(secrets)
    _touch_secrets_meta(name, "added")
    audit_log("keys.add", name)

    ui.success(f"Key '{name}' stored.")
    return 0


def _keys_remove(name: str) -> int:
    secrets = _load_secrets()
    if name not in secrets:
        ui.error(f"Key '{name}' not found.")
        return 1

    if sys.stdin.isatty():
        ans = input(f"Remove '{name}'? [y/N]: ").strip().lower()
        if ans != "y":
            ui.warn("Cancelled.")
            return 0

    if _keyring_active():
        _system.secret_tool_clear(_cfg.KEYRING_SERVICE, name)

    del secrets[name]
    _save_secrets(secrets)
    _touch_secrets_meta(name, "removed")
    audit_log("keys.remove", name)

    ui.success(f"Key '{name}' removed.")
    return 0


def _keys_rotate(name: str) -> int:
    secrets = _load_secrets()
    if name not in secrets:
        ui.error(f"Key '{name}' does not exist. Use 'docket keys add' to create it.")
        return 1

    try:
        value = _getpass.getpass(f"Enter new value for {name} (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.warn("\nAborted.")
        return 0

    if not value:
        ui.error("Value cannot be empty.")
        return 1

    ok, reason = _validate_key_format(name, value)
    if not ok:
        ui.warn(f"Key format warning: {reason}")

    if _keyring_active():
        if not _system.secret_tool_store(_cfg.KEYRING_SERVICE, name, value):
            ui.error(
                f"Could not store '{name}' in the OS keyring (secret-tool store failed).\n"
                "  Not falling back to plaintext storage under DOCKET_SECRETS_BACKEND=keyring."
            )
            return 1
        secrets[name] = ""
    else:
        secrets[name] = value
    _save_secrets(secrets)
    _touch_secrets_meta(name, "rotated")
    audit_log("keys.rotate", name)

    ui.success(f"Key '{name}' rotated.")
    return 0


def _keys_validate(name: str | None) -> int:
    secrets = _load_secrets()
    if not secrets:
        ui.info("No keys stored.")
        return 0

    targets = {name: secrets[name]} if name and name in secrets else secrets
    if name and name not in secrets:
        ui.error(f"Key '{name}' not found.")
        return 1

    any_fail = False
    for key_name, raw_value in sorted(targets.items()):
        value = _resolve_display_value(key_name, raw_value)
        ok, reason = _validate_key_format(key_name, value)
        if ok:
            ui.console.print(f"  [green]✓[/green] {key_name}")
        else:
            ui.console.print(f"  [yellow]⚠[/yellow] {key_name}: {reason}")
            any_fail = True

    if any_fail:
        return 1
    return 0


def _keys_export() -> int:
    secrets = _load_secrets()
    if not secrets:
        ui.info("No keys stored.")
        return 0

    for name, raw_value in sorted(secrets.items()):
        value = _resolve_display_value(name, raw_value)
        # Shell-safe: escape single quotes
        safe_value = value.replace("'", "'\\''")
        print(f"export {name}='{safe_value}'")
    return 0


def _keys_setup() -> int:
    if not sys.stdin.isatty():
        ui.error("docket keys setup requires an interactive TTY.")
        return 1

    ui.header("API Key Setup Wizard")
    ui.console.print()
    ui.console.print("Walk through key providers. Press Enter to skip any.")
    ui.console.print()

    # Catalog order, not a fixed provider list: every catalog entry (built-in first, then the
    # operator's own) that declares a credential name is prompted for, so a newly cataloged
    # provider is picked up here without a code change. `getattr` guards a `credential_prefix`
    # field ProviderSpec does not always define, so this keeps working whether or not that
    # field is present on a given document.
    catalog = _provider.load_catalog()
    providers = [
        (cred, spec.name, getattr(spec, "credential_prefix", ""))
        for spec in catalog.entries.values()
        for cred in spec.auth.credentials
    ]

    secrets = _load_secrets()
    changed = False

    for key_name, label, _prefix in providers:
        exists = key_name in secrets
        status = (
            f"[already set: {_mask_key(_resolve_display_value(key_name, secrets[key_name]))}]"
            if exists
            else "[not set]"
        )
        ui.console.print(f"[bold]{label}[/bold] {status}")
        action = input(f"  Configure {key_name}? [y/N]: ").strip().lower()
        if action != "y":
            ui.console.print()
            continue

        try:
            value = _getpass.getpass(f"  {key_name}: ").strip()
        except (KeyboardInterrupt, EOFError):
            ui.warn("\nAborted.")
            return 0

        if not value:
            ui.warn("  Skipped (empty).")
            ui.console.print()
            continue

        ok, reason = _validate_key_format(key_name, value)
        if not ok:
            ui.warn(f"  Format warning: {reason}")
            if input("  Save anyway? [y/N]: ").strip().lower() != "y":
                ui.console.print()
                continue

        if _keyring_active():
            if not _system.secret_tool_store(_cfg.KEYRING_SERVICE, key_name, value):
                ui.warn(f"  Could not store {key_name} in the OS keyring; skipping.")
                ui.console.print()
                continue
            secrets[key_name] = ""
        else:
            secrets[key_name] = value
        event = "rotated" if exists else "added"
        _touch_secrets_meta(key_name, event)
        audit_log("keys.rotate" if exists else "keys.add", key_name)
        changed = True
        ui.success(f"  {key_name} saved.")
        ui.console.print()

    if changed:
        _save_secrets(secrets)
        ui.success("Keys saved.")
    else:
        ui.info("No changes made.")
    return 0


def run_keys(sub: str | None, extra: list[str]) -> int:
    """Dispatch the keys subcommand. Returns the process exit code.

    sub:   list (default) | add | remove | rotate | validate | export | setup
    extra: trailing positional args (e.g. KEY_NAME) from the Typer context.
    """
    bad = find_unknown_flag(extra, frozenset())
    if bad is not None:
        ui.error(f"docket keys: unrecognized flag '{bad}'")
        return 2
    action = sub or "list"

    if action == "list":
        return _keys_list()
    if action == "add":
        name = extra[0] if extra else None
        if not name:
            ui.error("Usage: docket keys add <KEY_NAME>")
            return 1
        return _keys_add(name)
    if action == "remove":
        name = extra[0] if extra else None
        if not name:
            ui.error("Usage: docket keys remove <KEY_NAME>")
            return 1
        return _keys_remove(name)
    if action == "rotate":
        name = extra[0] if extra else None
        if not name:
            ui.error("Usage: docket keys rotate <KEY_NAME>")
            return 1
        return _keys_rotate(name)
    if action == "validate":
        name = extra[0] if extra else None
        return _keys_validate(name)
    if action == "export":
        return _keys_export()
    if action == "setup":
        return _keys_setup()

    ui.console.print("[bold]docket keys — API key management[/bold]")
    ui.console.print()
    ui.console.print("  docket keys list                  Show stored keys (masked)")
    ui.console.print("  docket keys add <KEY_NAME>        Store a new key")
    ui.console.print("  docket keys remove <KEY_NAME>     Remove a key")
    ui.console.print("  docket keys rotate <KEY_NAME>     Update an existing key")
    ui.console.print("  docket keys validate [KEY_NAME]   Check format validity")
    ui.console.print("  docket keys export                Print export statements")
    ui.console.print("  docket keys setup                 Interactive setup wizard")
    ui.console.print()
    return 1
