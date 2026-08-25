"""docket-owned secrets storage: ~/.docket/secrets.json + secrets.meta.json.

Provider API keys `docket keys` manages, and their bookkeeping metadata
(added/rotated timestamps). Always docket-owned — never an external-runtime file
format — and living under ``DOCKET_HOME``.

Consumers share this module rather than reading files directly: the keys CLI,
doctor checks, model endpoint resolver, and trace redaction. Centralising those
lookups keeps file/keyring behavior and secret handling consistent.
"""

from __future__ import annotations

from typing import Any

import docket.config as _cfg
from docket.edges import store
from docket.edges.adapters import system as _system

SECRETS_FILE = _cfg.DOCKET_HOME / "secrets.json"
SECRETS_META_FILE = _cfg.DOCKET_HOME / "secrets.meta.json"


def load_secrets() -> dict[str, str]:
    """Return the stored {KEY_NAME: value} map ({} if absent/malformed)."""
    raw = store.read_json(SECRETS_FILE)
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def save_secrets(secrets: dict[str, str]) -> None:
    store.write_json(SECRETS_FILE, secrets)


def load_secrets_meta() -> dict[str, Any]:
    """Return the raw secrets.meta.json contents ({} if absent/malformed)."""
    raw = store.read_json(SECRETS_META_FILE)
    return raw if isinstance(raw, dict) else {}


def save_secrets_meta(meta: dict[str, Any]) -> None:
    store.write_json(SECRETS_META_FILE, meta)


def secrets_keys() -> set[str]:
    """Return the set of stored key names."""
    return set(load_secrets().keys())


def secret_value(name: str) -> str | None:
    """Resolve one stored secret without exposing unrelated credentials."""
    raw = load_secrets()
    if name not in raw:
        return None
    if _cfg.secrets_backend_requested() == "keyring" and _system.secret_tool_available():
        value = _system.secret_tool_lookup(_cfg.KEYRING_SERVICE, name)
    else:
        value = raw.get(name)
    clean = str(value or "").strip()
    return clean or None


def secrets_meta() -> dict[str, Any]:
    """Return the raw secrets.meta.json contents."""
    return load_secrets_meta()


def secret_values() -> list[str]:
    """Return the stored secret VALUES (for trace/Telegram redaction).

    Mirrors the file-vs-keyring backend split ``docket keys`` uses: the file
    backend stores ``{KEY: value}`` in secrets.json, so the values are the
    dict values; the keyring backend keeps only an index there (no values at
    rest), so it returns nothing. Empty/short values are the caller's concern.
    """
    raw = load_secrets()
    if not raw:
        return []
    backend = "file"
    if _cfg.secrets_backend_requested() == "keyring" and _system.secret_tool_available():
        backend = "keyring"
    if backend == "keyring":
        service = _cfg.KEYRING_SERVICE
        out: list[str] = []
        for key in raw:
            value = _system.secret_tool_lookup(service, str(key))
            if value:
                out.append(value)
        return out
    return [v for v in raw.values() if v]


def touch_meta(name: str, event: str) -> None:
    """Record an add/rotate/remove event for *name* in secrets.meta.json.

    ``event``: "added" | "rotated" | "removed". Mirrors the timestamps
    ``docket doctor``'s key-hygiene report reads.
    """
    import datetime as _dt

    meta = load_secrets_meta()
    now = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if event == "removed":
        meta.pop(name, None)
    else:
        entry: dict[str, Any] = meta.get(name) or {}
        entry.setdefault("added_at", now)
        if event == "rotated":
            entry["rotated_at"] = now
        meta[name] = entry
    save_secrets_meta(meta)
