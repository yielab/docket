"""docket-owned secrets storage: ~/.docket/secrets.json + secrets.meta.json.

Provider API keys `docket keys` manages, and their bookkeeping metadata
(added/rotated timestamps). Always docket-owned — never an OpenClaw file
format — but pre-Phase-19-P19-7b this lived under ``OPENCLAW_DIR`` purely
because that was the daemon's directory and docket colocated its own files
there. Now that ``OPENCLAW_DIR`` is retired, both files move under
``DOCKET_HOME``.

Three consumers share this module rather than each reading the files
directly: ``cli/_keys.py`` (add/remove/rotate/list), ``cli/_doctor.py``
(key-hygiene/provider-coverage checks), and ``core/trace.py`` (redacting
stored secret values out of every trace payload — security-relevant, not
cosmetic). Centralising here is what keeps those three consistent.
"""

from __future__ import annotations

import os
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
    if os.environ.get("DOCKET_SECRETS_BACKEND") == "keyring" and _system.secret_tool_available():
        backend = "keyring"
    if backend == "keyring":
        service = os.environ.get("DOCKET_KEYRING_SERVICE", "docket-cli")
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
