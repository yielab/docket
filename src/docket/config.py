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
# ARCHETYPE_REGISTRY_FILE: user overlay for role archetypes (ROADMAP Phase 16 W-6) —
# the same overlay pattern as MODEL_REGISTRY_FILE (built-ins + starter library,
# overlaid by a user `roles:` map). See core/archetypes.py.
ARCHETYPE_REGISTRY_FILE = OPENCLAW_DIR / "docket-roles.json"
PROJECTS_DIR = OPENCLAW_DIR / "workspaces" / "projects"
SITES_DIR = Path(os.environ.get("SITES_DIR", Path.home() / "Sites"))
LOG_DIR = Path(os.environ.get("OPENCLAW_LOG_DIR", "/tmp/openclaw"))

# DOCKET_HOME (Phase 19 P19-6, "docket-native home"): docket's own state root,
# independent of OPENCLAW_DIR -- the daemon's directory, which P19-7 deletes.
# Before this card DOCKET_HOME aliased OPENCLAW_DIR (same physical directory,
# convenient while docket's files and the daemon's lived side by side); now it
# is genuinely docket's own home. Every file already resolved via DOCKET_HOME
# (traces/policies/approvals/schedules/runs/sessions/conversations/mcp-servers/
# FLEET_FILE below) moves with it automatically -- no other constant changes.
# Files that remain daemon-owned (openclaw.json, auth-profiles, workspaces,
# session JSONL) stay under OPENCLAW_DIR until P19-7 deletes that tree outright.
DOCKET_HOME = Path(os.environ.get("DOCKET_HOME", Path.home() / ".docket"))
TRACES_DIR = Path(os.environ.get("TRACES_DIR", DOCKET_HOME / "traces"))
AUDIT_LOG = OPENCLAW_DIR / "audit.log"
# AUDIT_LOG_MAX_BYTES: audit.log rotates to a single-generation backup
# (audit.log.1, overwriting any prior one) once it reaches this size. `docket
# audit verify` only verifies the current file — each rotation starts a fresh
# hash chain (see specs/functional/audit.spec.md).
AUDIT_LOG_MAX_BYTES = int(os.environ.get("AUDIT_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
POLICIES_DIR = Path(os.environ.get("POLICIES_DIR", DOCKET_HOME / "policies"))
APPROVALS_DIR = Path(os.environ.get("APPROVALS_DIR", DOCKET_HOME / "approvals"))
SCHEDULE_FILE = Path(os.environ.get("SCHEDULE_FILE", DOCKET_HOME / "docket-schedules.json"))
# RUNS_FILE: the persisted dispatch-run registry (R-3 / D-17) — one record per
# `dispatch_pod` invocation, whatever triggered it (cli|webhook|schedule|sweep).
# Docket-owned JSON, so all reads/writes go through edges/store.py.
RUNS_FILE = Path(os.environ.get("RUNS_FILE", DOCKET_HOME / "docket-runs.json"))
# Expired approvals are denied (fail-closed).
SESSION_TIMEOUT = int(os.environ.get("SESSION_TIMEOUT", "3600"))
# APPROVAL_TIMEOUT: the ASYNC path (core/dispatch.py's require_approval gate).
# A task just sits `waiting_approval` while this runs out -- no process, hop,
# or turn is blocked on it, so a generous 15 minutes costs nothing but wall
# clock and gives a human on Telegram/CLI a realistic window to notice.
APPROVAL_TIMEOUT = int(os.environ.get("APPROVAL_TIMEOUT", "900"))
# TOOL_APPROVAL_TIMEOUT (P19-3): the IN-TURN path (core/approval.py's
# wait_for_approval, called from core/tools.py's dispatch_tool). This one
# blocks a live call -- the model's turn, a real thread, and under `docket
# serve` a whole dispatch worker slot -- so APPROVAL_TIMEOUT's 15 minutes
# would starve unattended throughput on every gated tool call. 120s is
# deliberately well under core/dispatch.py's DEFAULT_TIMEOUT (300s, one hop's
# whole budget): a grant still leaves ~180s for the tool to actually run
# before the hop itself would time out, while a human watching for the
# approval still gets a full two minutes to react. Fails closed to denied on
# expiry, exactly like APPROVAL_TIMEOUT's sweep.
TOOL_APPROVAL_TIMEOUT = int(os.environ.get("TOOL_APPROVAL_TIMEOUT", "120"))
# TOOL_APPROVAL_POLL_INTERVAL_S: how often wait_for_approval re-checks the
# record while blocked. Small enough to feel responsive once a human answers,
# large enough not to busy-spin a thread that may sit here for the whole
# timeout.
TOOL_APPROVAL_POLL_INTERVAL_S = float(os.environ.get("TOOL_APPROVAL_POLL_INTERVAL_S", "2"))
# CLAIM_STALE_TIMEOUT: a pod task 'claimed' (status=running) longer than this
# without finishing is presumed crashed — the dispatch sweep fails it with a
# stale_claim trace event so it stops looking active forever (R-1).
CLAIM_STALE_TIMEOUT = int(os.environ.get("CLAIM_STALE_TIMEOUT", "1800"))
# METRICS_WINDOW: rolling terminal-session count for `docket metrics`.
METRICS_WINDOW = int(os.environ.get("METRICS_WINDOW", "50"))

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


# DISTILL_TIMEOUT_S / DISTILL_MAX_INPUT_BYTES: ROADMAP Phase 17 C-2 — `docket
# maintain distill`'s one driver-backed turn (D-18, docket's first
# self-originated LLM call). DISTILL_MAX_INPUT_BYTES bounds how much daily-log
# content goes into that turn's prompt, using the same bytes estimator as the
# rest of this file's context guards; it is a safety cap on the prompt docket
# composes, not token-accurate budgeting (Phase 17 C-1 owns real budgeting).
DISTILL_TIMEOUT_S = int(os.environ.get("DISTILL_TIMEOUT_S", "120"))
DISTILL_MAX_INPUT_BYTES = int(os.environ.get("DISTILL_MAX_INPUT_BYTES", str(48 * 1024)))

# R-2: per-role retry budget for a *retryable* TurnResult failure (timeout or
# daemon_error only — see core/dispatch.py's _RETRYABLE_FAILURE_KINDS; a non-zero
# exit or a bad tester/reviewer verdict is a real answer and is never retried).
# Value = retry attempts AFTER the first try, so "2" means up to 3 total tries.
# A role not listed here falls back to DISPATCH_RETRIES_DEFAULT.
DISPATCH_RETRIES_DEFAULT = int(os.environ.get("DISPATCH_RETRIES_DEFAULT", "2"))
DISPATCH_RETRIES_PER_ROLE: dict[str, int] = {
    role: int(os.environ.get(f"DISPATCH_RETRIES_{role.upper()}", str(DISPATCH_RETRIES_DEFAULT)))
    for role in ("lead", "implementer", "reviewer", "tester")
}
# DISPATCH_RETRY_BACKOFF_S: linear backoff base — retry attempt N (1-indexed) waits
# N * this many seconds before the next try.
DISPATCH_RETRY_BACKOFF_S = float(os.environ.get("DISPATCH_RETRY_BACKOFF_S", "2"))


def _optional_int_env(name: str) -> int | None:
    raw = os.environ.get(name, "")
    return int(raw) if raw else None


# R-2: process-wide timeouts for the serve dispatch loop (the "serve config
# knob" — serve.py runs unattended, with no CLI flags to read). These are read
# *only* by serve.py; the CLI never consults them.
#
# Precedence is per-caller, because each passes its own value as dispatch's
# `explicit` argument (see core/dispatch.py's _resolve_timeout):
#   CLI    `docket pod <p> dispatch --timeout N` > Lead-meta turn/verifyTimeoutS > DEFAULT_TIMEOUT
#   serve  these envs (when set)                 > Lead-meta turn/verifyTimeoutS > DEFAULT_TIMEOUT
#
# Note the asymmetry: a set serve env knob *overrides* a pod's own Lead-meta
# timeout for serve-triggered dispatches — it is a process-wide ceiling for
# unattended runs, not a fallback beneath per-pod config.
#
# None (the default) means "no serve-wide override" — unset envs change nothing
# from pre-R-2 behaviour, and Lead-meta then applies as usual.
DISPATCH_TURN_TIMEOUT_S: int | None = _optional_int_env("DISPATCH_TURN_TIMEOUT_S")
DISPATCH_VERIFY_TIMEOUT_S: int | None = _optional_int_env("DISPATCH_VERIFY_TIMEOUT_S")

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
    "programmer": "code generation",
    "security": "audit depth",
    "repo": "project default for project (repo) agents",
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

# docket-owned registry of channel conversations (Telegram threads etc.). OpenClaw
# persists no durable transcript, so docket tracks conversation state here for
# resume/visibility. See internal-docs/telegram-conversation-memory.md.
CONVERSATIONS_FILE = DOCKET_HOME / "docket-conversations.json"

# SESSIONS_DIR: durable per-session turn history (ROADMAP Phase 19 P19-4,
# core/session.py). One self-contained subdirectory per session key (its own
# JSON file, its own edges/store.py lock file) rather than one shared
# registry, so that appending to or compacting one session's history can
# never block on, or corrupt, another session's -- see core/session.py's
# module docstring for the full rationale.
SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", DOCKET_HOME / "sessions"))


def pod_scratch_dir(project: str) -> Path:
    """Isolated scratch data directory for a pod's runtime state.

    Created by docket at pod provisioning (0700); removed on pod teardown.
    Injected into the Implementer's TOOLS.md as $DOCKET_SCRATCH_DIR.
    """
    return OPENCLAW_DIR / "workspaces" / "pods" / project / ".scratch"


def pod_work_dir(project: str) -> Path:
    """Default working directory for a `workdir`-kind pod blueprint (ROADMAP
    Phase 16 W-7 — research/content/ops pods, which have no codebase).

    Auto-provisioned (mkdir -p, 0700) at pod creation the same way
    `pod_scratch_dir` is, unless the operator supplies an explicit path
    (``docket add --codebase <path>`` doubles as "the working directory" for
    a `workdir` blueprint). Shared by the whole pod, mirroring how a
    `codebase` path is shared by every member of a `software` pod.
    """
    return OPENCLAW_DIR / "workspaces" / "pods" / project / "workdir"


# ── Phase 19 P19-5: the turn loop (core/agent_loop.py, edges/adapters/docket_runtime.py) ──
#
# Every bound below is a deliberate stop condition, not a throughput knob: an
# unbounded loop burning money on a confused model is exactly the failure
# mode P19-5 exists to prevent (ROADMAP Phase 19 / decision D-19). All are
# env-overridable, matching every other tunable in this file.

# AGENT_LOOP_MAX_ITERATIONS: hard cap on model round-trips within one
# run_agent_turn call. One iteration = one ChatBackend.complete() call — the
# primary defense against a model that never stops requesting tool calls.
AGENT_LOOP_MAX_ITERATIONS = int(os.environ.get("AGENT_LOOP_MAX_ITERATIONS", "20"))
# AGENT_LOOP_MAX_TOOL_CALLS: hard cap on total tool calls actually dispatched
# across the whole turn, independent of how they are batched across
# iterations — a single response requesting many calls at once is a distinct
# risk from many responses requesting one each, so both are capped.
AGENT_LOOP_MAX_TOOL_CALLS = int(os.environ.get("AGENT_LOOP_MAX_TOOL_CALLS", "40"))
# AGENT_LOOP_WALL_CLOCK_TIMEOUT_S: default overall budget for one turn,
# checked between iterations (not by interrupting an in-flight HTTP call).
# edges.adapters.docket_runtime.DocketDriver.run_turn overrides this with its
# own `timeout` argument — the same per-hop budget core/dispatch.py's
# DEFAULT_TIMEOUT already resolves — so this default only matters for a bare
# run_agent_turn() call with no explicit LoopConfig.
AGENT_LOOP_WALL_CLOCK_TIMEOUT_S = float(os.environ.get("AGENT_LOOP_WALL_CLOCK_TIMEOUT_S", "300"))
# AGENT_LOOP_TOKEN_BUDGET: hard cap on one turn's cumulative *measured* token
# usage (core.llm.TokenUsage's real counts — never the bytes/divisor estimate
# core/context.py uses elsewhere; see core/session.py's "Budgeting honesty").
AGENT_LOOP_TOKEN_BUDGET = int(os.environ.get("AGENT_LOOP_TOKEN_BUDGET", "100000"))
# AGENT_LOOP_REQUEST_TIMEOUT_S: per-HTTP-call timeout passed to
# ChatBackend.complete(), capped against whatever wall-clock budget remains.
AGENT_LOOP_REQUEST_TIMEOUT_S = int(os.environ.get("AGENT_LOOP_REQUEST_TIMEOUT_S", "120"))

# ── P19-10: MCP client (D-19 "rent the protocol") ────────────────────────────
# MCP_SERVERS_FILE: docket-owned registry of configured external MCP tool
# servers (core/mcp_tools.py's McpServerConfig/McpServerRegistry), written
# through edges/store.py like every other docket-owned JSON file.
MCP_SERVERS_FILE = Path(os.environ.get("MCP_SERVERS_FILE", DOCKET_HOME / "docket-mcp-servers.json"))
# MCP_CLIENT_TIMEOUT_S: default per-call bound (connect+list, or connect+call)
# used when a server config does not specify its own `timeout`.
MCP_CLIENT_TIMEOUT_S = float(os.environ.get("MCP_CLIENT_TIMEOUT_S", "10"))
# MCP_CLIENT_MAX_TIMEOUT_S: hard ceiling every server-specified timeout is
# clamped to (`McpServerConfig.resolved_timeout`) — an operator (or a
# careless config) cannot ask for an effectively unbounded wait that could
# stall a whole turn on one misbehaving external server.
MCP_CLIENT_MAX_TIMEOUT_S = float(os.environ.get("MCP_CLIENT_MAX_TIMEOUT_S", "60"))

# ── P19-11: the `fetch` tool (decisions D-23/D-24 — ship the tool, not the lockdown) ──
#
# Network egress stays open by default (`bash` + curl/wget correctly ask, but
# python3/node/git-clone are curated-allowlist escape hatches that reach the
# network unattended — see security-gates.spec.md's "Network egress and the
# `fetch` tool" section). These three constants are what make `fetch` an
# *inspectable* path instead of a third unattended one: a domain allowlist, a
# response size cap, and a timeout — enforced inside `edges/adapters/fetch.py`
# itself (mechanism, the same way `resolve_within`'s containment lives in
# `edges/adapters/toolbox.py` rather than in `core/tools.py`'s gate).

# FETCH_ALLOWED_DOMAINS: comma-separated exact hostnames `fetch` may reach.
# Empty by default — an operator opts a domain in explicitly rather than the
# tool defaulting to "anywhere", which would just be a second unattended
# escape hatch with extra steps.
FETCH_ALLOWED_DOMAINS: tuple[str, ...] = tuple(
    d.strip().lower() for d in os.environ.get("FETCH_ALLOWED_DOMAINS", "").split(",") if d.strip()
)
# FETCH_MAX_RESPONSE_BYTES: response bodies are fed straight into a model's
# context, same reasoning as `toolbox.MAX_OUTPUT_CHARS` for the other
# built-ins; truncation is always announced in the returned text.
FETCH_MAX_RESPONSE_BYTES = int(os.environ.get("FETCH_MAX_RESPONSE_BYTES", str(200_000)))
# FETCH_TIMEOUT_S: default per-call wall-clock bound, overridable per call via
# the tool's own `timeout` argument up to this same order of magnitude.
FETCH_TIMEOUT_S = float(os.environ.get("FETCH_TIMEOUT_S", "15"))

# ── P19-6: docket-native fleet registry (core/fleet.py, edges/adapters/openclaw.py) ──
# FLEET_FILE replaces openclaw.json as the source of truth for agent
# registration, channel bindings, gates/isolation flags, and the org-wide
# default model. Docket-owned JSON, so it is read/written only through
# edges/store.py (atomic, filelocked, 0600) -- never through the ACL's raw
# openclaw.json helpers. Per-agent facts that already have a home in
# .docket-meta.json (model, sessionKey, projectKey) are NOT duplicated here;
# the fleet registry tracks only what has no other home (see core/fleet.py's
# module docstring for the full rationale — this is what makes the old
# meta<->openclaw.json drift check obsolete rather than merely relocated).
FLEET_FILE = Path(os.environ.get("FLEET_FILE", DOCKET_HOME / "fleet.json"))
