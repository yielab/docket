"""The API key of a live run against a remote provider: where it comes from, and wiping it after.

``smoke_workflow.py`` and ``maint/live_eval.py`` share this. The key is read only to put it in the
smoke subprocess's environment and to find it again in what the run left behind; it is never an
argument, never printed, and never written by these scripts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from docket.kernel.home import Home

REMOTE_KEY_ENV: dict[str, str] = {"anthropic": "ANTHROPIC_API_KEY"}

REDACTED = "[redacted]"
_SECRETS_FILES = ("secrets.json", "secrets.meta.json")
_MIN_KEY_LENGTH = 8


def resolve_key(provider: str, environ: Mapping[str, str], home: Path) -> str | None:
    """The provider's key from its environment variable, else the stored secrets of the docket home
    under *home* (either layout), else None."""
    name = REMOTE_KEY_ENV[provider]
    value = environ.get(name, "").strip()
    if value:
        return value
    try:
        raw = json.loads(Home(home / ".docket").secrets_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    stored = raw.get(name) if isinstance(raw, dict) else None
    return stored.strip() if isinstance(stored, str) and stored.strip() else None


def scrub_file(path: Path, key: str) -> bool:
    """Replace every occurrence of *key* in one file; ``True`` when the file changed."""
    if len(key) < _MIN_KEY_LENGTH:
        return False
    try:
        data = path.read_bytes()
    except OSError:
        return False
    needle = key.encode()
    if needle not in data:
        return False
    try:
        path.write_bytes(data.replace(needle, REDACTED.encode()))
    except OSError:
        return False
    return True


def scrub_tree(root: Path, key: str) -> int:
    """Delete docket's secrets files under *root*, redact *key* elsewhere; symlinks are skipped."""
    if not root.is_dir():
        return 0
    changed = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if path.name in _SECRETS_FILES:
            try:
                path.unlink()
            except OSError:
                continue
            changed += 1
        elif scrub_file(path, key):
            changed += 1
    return changed
