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
# Default work directory for task agents (mirrors SITES_DIR in config.sh).
SITES_DIR = Path(os.environ.get("SITES_DIR", Path.home() / "Sites"))
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
# METRICS_WINDOW: rolling terminal-session count for drift's "current" rate.
METRICS_WINDOW = int(os.environ.get("METRICS_WINDOW", "50"))
# BASELINE_WINDOW: terminal sessions establishing the success-rate baseline.
BASELINE_WINDOW = int(os.environ.get("BASELINE_WINDOW", "100"))
# DRIFT_THRESHOLD: percentage-point drop from baseline that triggers an alert.
DRIFT_THRESHOLD = float(os.environ.get("DRIFT_THRESHOLD", "15"))
# DRIFT_COOLDOWN: seconds between drift alerts for the same role (86400 = 24 h).
DRIFT_COOLDOWN = int(os.environ.get("DRIFT_COOLDOWN", "86400"))

# ── token-efficiency guards ───────────────────────────────────────────────────
# docket cannot trim a live prompt (OpenClaw owns inference), but it CAN keep the
# artifacts OpenClaw re-feeds every turn small. These power the token guards in
# `maintain check` / `maintain sessions`. Token counts are a rough bytes/divisor
# estimate — good enough to catch runaway context, not a billing figure.
# CONTEXT_BYTES_PER_TOKEN: divisor for the byte→token estimate (~4 for English+md).
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

# The optional org Portfolio Manager (AA-6): a single cross-pod planning agent,
# opt-in via `docket install --portfolio`. Not a default specialist and never a
# pod member; see ORG_DISPLAY_ORDER.
PORTFOLIO_MANAGER_ROLE = "portfolio-manager"

SPECIALIST_ROLES: frozenset[str] = frozenset(
    ["manager", "programmer", "reviewer", "tester", "knowledge", "security", PORTFOLIO_MANAGER_ROLE]
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

# Phase 10 (AA-2): the scope split of the specialist roles — the fix for the
# shared-singleton isolation defect.
#   ORG_ROLES     — genuinely cross-cutting; installed once as shared singletons
#                   (`scope: org`) by `docket install`.
#   PROJECT_ROLES — become per-pod workers provisioned by `docket add` (AA-3);
#                   NOT installed as global workspaces.
# `manager` stays in ORG_ROLES transitionally; AA-5 converts it to per-pod Leads
# and AA-6 adds an optional org Portfolio Manager.
ORG_ROLES: frozenset[str] = frozenset(["security", "knowledge", "manager", PORTFOLIO_MANAGER_ROLE])
PROJECT_ROLES: frozenset[str] = frozenset(["programmer", "reviewer", "tester"])

# Install order for the shared org agents (a subset of SPECIALIST_ORDER). The
# Portfolio Manager is deliberately NOT here — it is opt-in, so it must not be
# auto-provisioned or flagged "missing" on a default install.
ORG_SPECIALIST_ORDER: tuple[str, ...] = tuple(r for r in SPECIALIST_ORDER if r in ORG_ROLES)

# Display/monitor order for org agents = the default-installed specialists plus
# the opt-in Portfolio Manager. Consumers (list, serve) skip any whose workspace
# doesn't exist, so the Portfolio Manager appears only once it's been installed.
ORG_DISPLAY_ORDER: tuple[str, ...] = (*ORG_SPECIALIST_ORDER, PORTFOLIO_MANAGER_ROLE)


def role_scope(role: str) -> str:
    """Scope a specialist role resolves to (Phase 10). Mirrors the AgentMeta
    backfill in core/models.py: project workers vs. cross-cutting org agents."""
    return "project" if role in PROJECT_ROLES else "org"


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
    "portfolio-manager": "cross-pod planning over fleet metadata, shallow reasoning",
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
    """Repo/install root (honours DOCKET_CLI_ROOT, else the package parent)."""
    override = Path(os.environ.get("DOCKET_CLI_ROOT", ""))
    if override.is_dir():
        return override
    return Path(__file__).resolve().parents[2]


def templates_dir() -> Path:
    """Templates shipped inside the package (specialist .md, policy JSON, …)."""
    return Path(__file__).resolve().parent / "templates"


def policy_templates_dir() -> Path:
    """Baseline policy templates shipped with docket."""
    return templates_dir() / "policies"


# ── CD-1: pod runtime-resource paths ─────────────────────────────────────────

# Flat JSON allocation table tracking project → portRangeStart.
# One entry per live pod; removed on pod teardown.
PORT_ALLOC_FILE = DOCKET_HOME / "port-allocations.json"


def pod_scratch_dir(project: str) -> Path:
    """Isolated scratch data directory for a pod's runtime state.

    Created by docket at pod provisioning (0700); removed on pod teardown.
    Injected into the Implementer's TOOLS.md as $DOCKET_SCRATCH_DIR.
    """
    return OPENCLAW_DIR / "workspaces" / "pods" / project / ".scratch"
