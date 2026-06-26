"""Runtime path and constant resolution.

All path lookups funnel through here so the rest of the codebase stays
independent of the on-disk layout. Override OPENCLAW_DIR in tests or CI.
"""

from __future__ import annotations

import os
from pathlib import Path

OPENCLAW_DIR = Path(os.environ.get("OPENCLAW_DIR", Path.home() / ".openclaw"))

CONFIG_FILE = OPENCLAW_DIR / "openclaw.json"
MODEL_REGISTRY_FILE = OPENCLAW_DIR / "docket-models.json"
PROJECTS_DIR = OPENCLAW_DIR / "workspaces" / "projects"
SITES_DIR = Path(os.environ.get("SITES_DIR", Path.home() / "Sites"))
LOG_DIR = Path(os.environ.get("OPENCLAW_LOG_DIR", "/tmp/openclaw"))

DOCKET_HOME = Path(os.environ.get("DOCKET_HOME", OPENCLAW_DIR))
TRACES_DIR = Path(os.environ.get("TRACES_DIR", DOCKET_HOME / "traces"))
AUDIT_LOG = OPENCLAW_DIR / "audit.log"
POLICIES_DIR = Path(os.environ.get("POLICIES_DIR", DOCKET_HOME / "policies"))
APPROVALS_DIR = Path(os.environ.get("APPROVALS_DIR", DOCKET_HOME / "approvals"))
SCHEDULE_FILE = Path(os.environ.get("SCHEDULE_FILE", DOCKET_HOME / "docket-schedules.json"))
# Expired approvals are denied (fail-closed).
SESSION_TIMEOUT = int(os.environ.get("SESSION_TIMEOUT", "3600"))
APPROVAL_TIMEOUT = int(os.environ.get("APPROVAL_TIMEOUT", "900"))
# METRICS_WINDOW: rolling terminal-session count for drift's "current" rate.
METRICS_WINDOW = int(os.environ.get("METRICS_WINDOW", "50"))
# BASELINE_WINDOW: terminal sessions establishing the success-rate baseline.
BASELINE_WINDOW = int(os.environ.get("BASELINE_WINDOW", "100"))
# DRIFT_THRESHOLD: percentage-point drop from baseline that triggers an alert.
DRIFT_THRESHOLD = float(os.environ.get("DRIFT_THRESHOLD", "15"))
# DRIFT_COOLDOWN: seconds between drift alerts for the same role (86400 = 24 h).
DRIFT_COOLDOWN = int(os.environ.get("DRIFT_COOLDOWN", "86400"))

# docket cannot trim a live prompt (OpenClaw owns inference), but it CAN keep the
# artifacts OpenClaw re-feeds every turn small. These power the token guards in
# `maintain check` / `maintain sessions`. Token counts are a rough bytes/divisor
# estimate — good enough to catch runaway context, not a billing figure.
CONTEXT_BYTES_PER_TOKEN = max(1, int(os.environ.get("CONTEXT_BYTES_PER_TOKEN", "4")))
# CONTEXT_TOKEN_BUDGET: soft cap on the static context re-sent every turn
# (SOUL+AGENTS+TOOLS+HEARTBEAT+MEMORY.md). `maintain check` warns past this.
CONTEXT_TOKEN_BUDGET = int(os.environ.get("CONTEXT_TOKEN_BUDGET", "6000"))
# SESSION_WARN_BYTES: a transcript past this is re-read in full on every resume —
# flag it for trim/archive. 256 KB ≈ 64k tokens.
SESSION_WARN_BYTES = int(os.environ.get("SESSION_WARN_BYTES", str(256 * 1024)))
# SESSION_TRIM_KEEP_TURNS: recent message lines kept when trimming a transcript.
SESSION_TRIM_KEEP_TURNS = max(1, int(os.environ.get("SESSION_TRIM_KEEP_TURNS", "40")))

# TEMPLATE_VERSION: workspace-prompt schema version. Bump when the generated
# SOUL/AGENTS/TOOLS prose changes so `doctor` flags older agents for rebuild.
TEMPLATE_VERSION = int(os.environ.get("TEMPLATE_VERSION", "4"))

# Opt-in org Portfolio Manager: cross-pod planning, never a default specialist.
# Installed via `docket install --portfolio`; excluded from ORG_SPECIALIST_ORDER
# so it is never auto-provisioned or flagged missing on a default install.
PORTFOLIO_MANAGER_ROLE = "portfolio-manager"

SPECIALIST_ROLES: frozenset[str] = frozenset(
    ["manager", "programmer", "reviewer", "tester", "knowledge", "security", PORTFOLIO_MANAGER_ROLE]
)

META_FILE = ".docket-meta.json"

DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

SPECIALIST_ORDER: tuple[str, ...] = (
    "manager",
    "programmer",
    "reviewer",
    "tester",
    "knowledge",
    "security",
)

# Org agents are shared across projects; project roles are per-pod (provisioned by docket add).
ORG_ROLES: frozenset[str] = frozenset(["security", "knowledge", "manager", PORTFOLIO_MANAGER_ROLE])
PROJECT_ROLES: frozenset[str] = frozenset(["programmer", "reviewer", "tester"])

# Install order: shared org agents only. Portfolio Manager is excluded — it is opt-in and
# must never be auto-provisioned or flagged "missing" on a standard install.
ORG_SPECIALIST_ORDER: tuple[str, ...] = tuple(r for r in SPECIALIST_ORDER if r in ORG_ROLES)

# Display order includes the opt-in Portfolio Manager. Consumers skip entries whose workspace
# doesn't exist, so the Portfolio Manager appears only after `docket install --portfolio`.
ORG_DISPLAY_ORDER: tuple[str, ...] = (*ORG_SPECIALIST_ORDER, PORTFOLIO_MANAGER_ROLE)


def role_scope(role: str) -> str:
    """Returns 'project' for per-pod workers, 'org' for shared specialists."""
    return "project" if role in PROJECT_ROLES else "org"


ROLE_WHY: dict[str, str] = {
    "manager": "high-volume coordination, shallow reasoning",
    "reviewer": "triage and review, low reasoning density",
    "tester": "run tests and report",
    "knowledge": "retrieval and summarization",
    "task": "project default for task agents",
    "programmer": "code generation",
    "security": "audit depth",
    "repo": "project default for repo agents",
    "portfolio-manager": "cross-pod planning over fleet metadata, shallow reasoning",
}

TELEGRAM_GROUP_NAMES: dict[str, str] = {
    "manager": "Manager",
}


def is_specialist(agent_id: str) -> bool:
    return agent_id in SPECIALIST_ROLES


def workspace_dir(agent_id: str) -> Path:
    """Resolve the workspace path for any agent (project or specialist)."""
    project_path = PROJECTS_DIR / agent_id
    if project_path.is_dir():
        return project_path
    if is_specialist(agent_id):
        specialist_path = OPENCLAW_DIR / "workspaces" / agent_id
        if specialist_path.is_dir():
            return specialist_path
    return project_path


def meta_path(agent_id: str) -> Path:
    return workspace_dir(agent_id) / META_FILE


def auth_profiles_path(agent_id: str = "main") -> Path:
    return OPENCLAW_DIR / "agents" / agent_id / "agent" / "auth-profiles.json"


def cli_root() -> Path:
    """Repo/install root (DOCKET_CLI_ROOT env override, else package parent)."""
    override = Path(os.environ.get("DOCKET_CLI_ROOT", ""))
    if override.is_dir():
        return override
    return Path(__file__).resolve().parents[2]


def templates_dir() -> Path:
    """Templates shipped inside the package."""
    return Path(__file__).resolve().parent / "templates"


def policy_templates_dir() -> Path:
    """Baseline policy templates shipped with docket."""
    return templates_dir() / "policies"


PORT_ALLOC_FILE = DOCKET_HOME / "port-allocations.json"


def pod_scratch_dir(project: str) -> Path:
    """Isolated scratch data directory for a pod's runtime state.

    Created by docket at pod provisioning (0700); removed on pod teardown.
    Injected into the Implementer's TOOLS.md as $DOCKET_SCRATCH_DIR.
    """
    return OPENCLAW_DIR / "workspaces" / "pods" / project / ".scratch"
