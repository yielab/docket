"""Runtime path and constant resolution.

All path lookups funnel through here so the rest of the codebase stays
independent of the on-disk layout. Override OPENCLAW_DIR in tests or CI.
"""

from __future__ import annotations

import os
from pathlib import Path

# Mirrors Bash: OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw}"
OPENCLAW_DIR = Path(os.environ.get("OPENCLAW_DIR", Path.home() / ".openclaw"))

CONFIG_FILE = OPENCLAW_DIR / "openclaw.json"
MODEL_REGISTRY_FILE = OPENCLAW_DIR / "docket-models.json"
PROJECTS_DIR = OPENCLAW_DIR / "workspaces" / "projects"

SPECIALIST_ROLES: frozenset[str] = frozenset(
    ["manager", "programmer", "reviewer", "tester", "knowledge", "security"]
)

META_FILE = ".docket-meta.json"


def is_specialist(agent_id: str) -> bool:
    return agent_id in SPECIALIST_ROLES


def workspace_dir(agent_id: str) -> Path:
    """Resolve workspace path using the same logic as the Bash agent_workspace_dir."""
    project_path = PROJECTS_DIR / agent_id
    if project_path.is_dir():
        return project_path
    if is_specialist(agent_id):
        specialist_path = OPENCLAW_DIR / "workspaces" / agent_id
        if specialist_path.is_dir():
            return specialist_path
    # Default to project path (creation path — may not exist yet)
    return project_path


def meta_path(agent_id: str) -> Path:
    return workspace_dir(agent_id) / META_FILE


def auth_profiles_path(agent_id: str = "main") -> Path:
    return OPENCLAW_DIR / "agents" / agent_id / "agent" / "auth-profiles.json"
