from __future__ import annotations

import getpass as _getpass

from docket.governance import secrets as _secrets
from docket.governance.audit import audit_log
from docket.interfaces.cli.render import ui
from docket.kernel.errors import Unavailable
from docket.kernel.home import current_home
from docket.kernel.process import process as _process
from docket.models import catalog as _prov

# -- credentials ---------------------------------------------------------------------------


def _keyring_active() -> bool:
    return _process.secrets_backend_requested() == "keyring" and _process.secret_tool_available()


def _validate_key_format(name: str, value: str) -> tuple[bool, str]:
    """(ok, reason); the prefix hint comes from the catalog entry that declares ``name``."""
    prefix = ""
    for spec in _prov.load_catalog().entries.values():
        if name in spec.auth.credentials and spec.credential_prefix:
            prefix = spec.credential_prefix
            break
    if prefix and not value.startswith(prefix):
        return False, f"should start with '{prefix}'"
    return True, ""


def _write_credential(name: str, value: str, event: str) -> bool:
    """Store ``value`` (keyring or 0600 file), touch the meta and audit ``keys.<event>``."""
    try:
        backend = _secrets.store_backend()
    except Unavailable as exc:
        ui.error(exc.message, exc.hint)
        return False
    secrets = _secrets.load_secrets()
    if backend == "keyring":
        if not _process.secret_tool_store(current_home().keyring_service, name, value):
            ui.error(
                f"Could not store {name} in the OS keyring",
                "It is not stored in plaintext under DOCKET_SECRETS_BACKEND=keyring",
            )
            return False
        secrets[name] = ""
    else:
        secrets[name] = value
    _secrets.save_secrets(secrets)
    meta_event = "added" if event == "add" else "rotated"
    _secrets.touch_meta(name, meta_event)
    audit_log(f"keys.{event}", name)
    return True


def _read_hidden(name: str, label: str = "Enter value for") -> str | None:
    try:
        return _getpass.getpass(f"{label} {name} (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.warn("Aborted.")
        return None


def credential_rotate(name: str, value: str | None = None) -> int:
    """Replace the value of an existing credential (prompting when ``value`` is None)."""
    if name not in _secrets.load_secrets():
        ui.error(f"Credential {name} does not exist", "Add it with docket setup provider add")
        return 1
    if value is None:
        value = _read_hidden(name, "Enter new value for")
    if not value:
        ui.error("Value cannot be empty")
        return 1
    ok, reason = _validate_key_format(name, value)
    if not ok:
        ui.warn(f"Key format: {reason}")
    return 0 if _write_credential(name, value, "rotate") else 1


def credential_remove(name: str) -> int:
    """Delete one stored credential."""
    secrets = _secrets.load_secrets()
    if name not in secrets:
        ui.error(f"Credential {name} is not stored")
        return 1
    if _keyring_active():
        _process.secret_tool_clear(current_home().keyring_service, name)
    del secrets[name]
    _secrets.save_secrets(secrets)
    _secrets.touch_meta(name, "removed")
    audit_log("keys.remove", name)
    return 0
