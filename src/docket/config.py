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
LOG_DIR = Path(os.environ.get("OPENCLAW_LOG_DIR", "/tmp/openclaw"))

# DOCKET_HOME aliases OPENCLAW_DIR so spec paths read literally (config.sh).
DOCKET_HOME = Path(os.environ.get("DOCKET_HOME", OPENCLAW_DIR))
# Per-session JSONL trace store: $TRACES_DIR/<project>/<session_id>.jsonl
TRACES_DIR = Path(os.environ.get("TRACES_DIR", DOCKET_HOME / "traces"))
# Mutating-operation audit log (one JSON line per change).
AUDIT_LOG = OPENCLAW_DIR / "audit.log"
# Declarative guardrail policy store: $POLICIES_DIR/*.json (config.sh).
POLICIES_DIR = Path(os.environ.get("POLICIES_DIR", DOCKET_HOME / "policies"))
# Durable pending-approval store: $APPROVALS_DIR/<token>.json (config.sh).
APPROVALS_DIR = Path(os.environ.get("APPROVALS_DIR", DOCKET_HOME / "approvals"))
# Seconds before an open trace is coerced to "aborted" by the sweep.
SESSION_TIMEOUT = int(os.environ.get("SESSION_TIMEOUT", "3600"))
# Seconds before a pending approval becomes expired (denied — fail-closed).
APPROVAL_TIMEOUT = int(os.environ.get("APPROVAL_TIMEOUT", "900"))

SPECIALIST_ROLES: frozenset[str] = frozenset(
    ["manager", "programmer", "reviewer", "tester", "knowledge", "security"]
)

META_FILE = ".docket-meta.json"

DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

# Display order for specialist agents (matches DOCKET_SPECIALISTS in config.sh).
SPECIALIST_ORDER: tuple[str, ...] = (
    "manager",
    "programmer",
    "reviewer",
    "tester",
    "knowledge",
    "security",
)

# One-line rationale for each role's model-class choice (mirrors ROLE_WHY in config.sh).
ROLE_WHY: dict[str, str] = {
    "manager": "high-volume coordination, shallow reasoning",
    "reviewer": "triage and review, low reasoning density",
    "tester": "run tests and report",
    "knowledge": "retrieval and summarization",
    "task": "project default for task agents",
    "programmer": "code generation",
    "security": "audit depth",
    "repo": "project default for repo agents",
}

# Expected Telegram group names for agents that should be wired (mirrors
# TELEGRAM_GROUP_NAMES in config.sh). Drives the "Telegram Setup Needed" hint.
TELEGRAM_GROUP_NAMES: dict[str, str] = {
    "manager": "Manager",
}


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


def cli_root() -> Path:
    """Repo root that holds lib/ (mirrors LIB_DIR resolution in bin/docket).

    Honours DOCKET_CLI_ROOT, else walks up from this module to the package root.
    """
    override = Path(os.environ.get("DOCKET_CLI_ROOT", ""))
    if override.is_dir():
        return override
    return Path(__file__).resolve().parents[2]


def policy_templates_dir() -> Path:
    """Baseline policy templates shipped with docket (lib/templates/policies)."""
    return cli_root() / "lib" / "templates" / "policies"
