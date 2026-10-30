"""The on-disk split of the home into authored configuration and state, and the names a home
keeps at one level instead. Imports nothing in docket."""

from __future__ import annotations

from pathlib import Path

CONFIG_DIRNAME = "config"
STATE_DIRNAME = "state"

# What the operator authors: catalogs, recipes, skills, policies and plugins. A pod's overlay
# is `config/pods/<pod>`.
_CONFIG_NAMES = (
    "docket-models.json",
    "docket-mcp-servers.json",
    "docket-providers.json",
    "docket-exporters.json",
    "docket-channels.json",
    "recipes",
    "skills",
    "policies",
    "plugins",
)

# What docket writes while it runs. Anything else at the top of the home (a token file the
# operator placed there) is neither, and stays where it is.
_STATE_NAMES = (
    "workspaces",
    "jail-tmp",
    "cache",
    "traces",
    "audit.log",
    "audit.head",
    "serve.pid",
    "approvals",
    "corrections",
    "consult-parked",
    "escalations",
    "docket-schedules.json",
    "docket-runs.json",
    "port-allocations.json",
    "docket-conversations.json",
    "sessions",
    "provider-models.json",
    "exporters-health.json",
    "notify-state.json",
    "channels-health.json",
    "fleet.json",
    "docket-telegram-offset.json",
    "inbox-cursor.json",
    "reviewed-repos.json",
    "secrets.json",
    "secrets.meta.json",
    "docket.lock",
)


def _belongs_to(name: str, bases: tuple[str, ...]) -> bool:
    """*name* is one of *bases* or a sidecar of one (`.bak`, `.corrupt`, `.1`, a hidden lock)."""
    bare = name.lstrip(".")
    return any(bare == base or bare.startswith(base + ".") for base in bases)


def _top_level(root: Path) -> list[Path]:
    try:
        return sorted(root.iterdir())
    except OSError:
        return []


def single_level_entries(root: Path) -> list[Path]:
    """The entries directly under *root* that the layout places under `config/` or `state/`.
    A home holds none: they belong a level down."""
    return [
        entry
        for entry in _top_level(root)
        if _belongs_to(entry.name, _CONFIG_NAMES) or _belongs_to(entry.name, _STATE_NAMES)
    ]
