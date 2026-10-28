"""The on-disk split of the home into authored configuration and state, and the one-way move from
the old layout, where both shared one level. Imports nothing in docket."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

CONFIG_DIRNAME = "config"
STATE_DIRNAME = "state"

# What the operator authors: catalogs, recipes, skills, policies and plugins. A pod's overlay
# is `config/pods/<pod>`, moved here from under the pod's workspaces directory.
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


class LayoutConflict(Exception):
    """Both layouts exist in one home, so neither can be moved over the other."""


def _belongs_to(name: str, bases: tuple[str, ...]) -> bool:
    """*name* is one of *bases* or a sidecar of one (`.bak`, `.corrupt`, `.1`, a hidden lock)."""
    bare = name.lstrip(".")
    return any(bare == base or bare.startswith(base + ".") for base in bases)


def _top_level(root: Path) -> list[Path]:
    try:
        return sorted(root.iterdir())
    except OSError:
        return []


def legacy_entries(root: Path) -> list[Path]:
    """The old-layout entries directly under *root*, config and state alike."""
    return [
        entry
        for entry in _top_level(root)
        if _belongs_to(entry.name, _CONFIG_NAMES) or _belongs_to(entry.name, _STATE_NAMES)
    ]


def is_legacy(root: Path) -> bool:
    """True for a home that has old-layout entries and neither `config/` nor `state/`."""
    if (root / CONFIG_DIRNAME).is_dir() or (root / STATE_DIRNAME).is_dir():
        return False
    return bool(legacy_entries(root))


def _pod_overlays(root: Path) -> list[Path]:
    pods = root / "workspaces" / "pods"
    return [p / "config" for p in _top_level(pods) if (p / "config").is_dir()]


def migrate(root: Path) -> list[str]:
    """Move an old-layout home into `config/` and `state/`, once; return what moved, as paths
    relative to *root*. Nothing to move is a no-op. Raises `LayoutConflict`, before moving
    anything, when `config/` or `state/` already exists beside old-layout entries."""
    entries = legacy_entries(root)
    if not entries:
        return []
    present = [d for d in (CONFIG_DIRNAME, STATE_DIRNAME) if (root / d).exists()]
    if present:
        raise LayoutConflict(
            f"{root} holds the old layout and also {', '.join(present)}/; "
            "merge or remove one of them by hand, then run `docket init` again"
        )
    config, state = root / CONFIG_DIRNAME, root / STATE_DIRNAME
    for directory in (config, state):
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)
    moved: list[str] = []
    overlays = _pod_overlays(root)
    if overlays:
        (config / "pods").mkdir(mode=0o700)
        os.chmod(config / "pods", 0o700)
    for overlay in overlays:
        shutil.move(str(overlay), str(config / "pods" / overlay.parent.name))
        moved.append(f"workspaces/pods/{overlay.parent.name}/config")
    for entry in entries:
        target = config if _belongs_to(entry.name, _CONFIG_NAMES) else state
        shutil.move(str(entry), str(target / entry.name))
        moved.append(entry.name)
    return moved
