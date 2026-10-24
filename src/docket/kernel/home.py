"""Where docket lives and every tunable value, as one frozen object built once from the
environment and asked for with current_home(); use_home() sets another one for a block."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

_RETRY_ROLES = ("lead", "implementer", "reviewer", "tester")


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    return int(env.get(name, str(default)))


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    return float(env.get(name, str(default)))


def _optional_int(env: Mapping[str, str], name: str) -> int | None:
    raw = env.get(name, "")
    return int(raw) if raw else None


def _optional_path(env: Mapping[str, str], name: str) -> Path | None:
    return Path(env[name]) if name in env else None


@dataclass(frozen=True)
class Home:
    """A `<name>_override` field holds a path the environment set; the `<name>` property
    falls back to a path under root, so a Home on another root moves every unset path."""

    # The state root (DOCKET_HOME).
    root: Path
    traces_dir_override: Path | None = None
    # audit.log rotates to one backup (audit.log.1) at this size. The new file carries the
    # old one's last seq and hash, so `docket log verify` checks one rotation back, no more.
    audit_log_max_bytes: int = 5 * 1024 * 1024
    policies_dir_override: Path | None = None
    plugins_dir_override: Path | None = None
    skills_dir_override: Path | None = None
    approvals_dir_override: Path | None = None
    corrections_dir_override: Path | None = None
    schedule_file_override: Path | None = None
    runs_file_override: Path | None = None
    # A trace idle longer than this with no session_end is closed by the sweep
    # (observability/trace.py::sweep_all).
    session_timeout: int = 3600
    # How long a task waits in `waiting_approval`. Nothing is blocked while it waits, so
    # 15 minutes costs only wall clock and gives a human time to notice; expiry denies.
    approval_timeout: int = 900
    # How long a gated tool call blocks inside a turn (governance/approval.py::wait_for_approval).
    # It holds a thread and, under `docket start`, a dispatch worker, so it stays well
    # under one hop's 300 s budget: a grant still leaves the tool time to run. Expiry denies.
    tool_approval_timeout: int = 120
    # How often a blocked call re-reads its approval: responsive once a human answers,
    # without busy-spinning.
    tool_approval_poll_interval_s: float = 2.0
    # A task claimed longer than this is presumed crashed; the sweep fails it with
    # stale_claim so it stops looking active.
    claim_stale_timeout: int = 1800
    # How many recent finished sessions `docket status` counts.
    metrics_window: int = 50
    # `docket setup --fix` flags a session past either threshold (turns, estimated cost)
    # as stuck. Generous on purpose: past them a human should look.
    runaway_turns_threshold: int = 200
    runaway_cost_threshold: float = 20.0
    # `docket setup --fix` flags a stored secret older than this: a rotation nudge, never
    # an expiry.
    key_max_age_days: int = 90
    # How long a finished trace (one with session_end) survives `docket task prune
    # --traces`. An open trace is never deleted by age (observability/trace.py::expire_old_traces),
    # and audit.log is never pruned.
    trace_retention_days: int = 30
    # Cap on the diff one hop hands the next (HandoffArtifact.diff).
    handoff_diff_max_chars: int = 8000
    # Cap on the repository map a hop message carries (teams/workspace/repo_map.py).
    repo_map_max_chars: int = 1600
    # The static-context budget when CONTEXT_TOKEN_BUDGET is unset and the model's window
    # is unknown. Kept apart so teams/identity.py can tell an explicit value from none.
    context_token_budget_default: int = 6000
    context_token_budget_override: int | None = None
    # Bounds the summarising turn session compaction runs (agent/session.py).
    distill_timeout_s: int = 120
    # Pod memory bounds (teams/memory.py). Accepted and undecided entries are capped
    # apart, so a flood of pending ones never pushes an accepted one out.
    pod_memory_max_accepted: int = 40
    pod_memory_max_undecided: int = 40
    pod_memory_max_per_task: int = 8
    pod_memory_note_max_chars: int = 200
    pod_memory_render_max_bytes: int = 3000
    # Retries after the first try for a retryable failure (hops/application/runner.py::
    # _RETRYABLE_FAILURE_KINDS); a non-zero exit or a verdict is an answer, never retried.
    dispatch_retries_default: int = 2
    # Retry N waits N times this many seconds.
    dispatch_retry_backoff_s: float = 2.0
    # Ceiling on one retry's wait, whether it comes from the backoff or a Retry-After.
    dispatch_retry_max_wait_s: float = 60.0
    # How many pods `docket start --dispatch` sweeps at once; 1 is serial.
    dispatch_sweep_workers: int = 4
    # Workspace-prompt schema version. Bump it when the generated SOUL/AGENTS/TOOLS prose
    # changes, so `docket setup` flags workspaces written by an older one.
    template_version: int = 5
    meta_file: str = ".docket-meta.json"
    default_model: str = "anthropic/claude-sonnet-4-6"
    sessions_dir_override: Path | None = None
    # Turn-loop bounds (agent/loop.py). Each is a stop condition against a confused
    # model, not a throughput knob: model round-trips, then tool calls however they are
    # batched, then denials in a row (one lets the model correct course), then rounds that
    # only repeat earlier call/result pairs (0 disables).
    agent_loop_max_iterations: int = 20
    agent_loop_max_tool_calls: int = 40
    agent_loop_max_consecutive_tool_denials: int = 3
    agent_loop_no_progress_rounds: int = 3
    # Cap on one tool result before it is truncated, visibly. The result goes back into
    # the model's window, so the right value depends on the endpoint: the default suits a
    # large hosted model, and a 16k-context local server needs about 2500.
    tool_max_output_chars: int = 30000
    # Cap on the verify output a hop stores (HopResult.verify): enough for a failure
    # trace, small enough to keep the task record small.
    verify_evidence_tail_chars: int = 4000
    # Bound on a task worktree's install, and the cached installs kept per codebase
    # (teams/workspace/prepare.py).
    prepare_timeout_s: int = 900
    prepare_cache_keep: int = 3
    # Default turn budget, checked between iterations. DocketDriver.run_turn passes the
    # hop's own timeout, so this applies only to run_agent_turn() without a LoopConfig.
    agent_loop_wall_clock_timeout_s: float = 300.0
    # Cap on a turn's measured token usage (agent.ports.TokenUsage), never an estimate.
    agent_loop_token_budget: int = 100000
    # Output reserve for a model that registers no maximum, so the window checks run.
    default_max_output_tokens: int = 4096
    # Per-request timeout, cut to whatever wall-clock budget remains.
    agent_loop_request_timeout_s: int = 120
    mcp_servers_file_override: Path | None = None
    providers_file_override: Path | None = None
    exporters_file_override: Path | None = None
    exporters_health_file_override: Path | None = None
    channels_file_override: Path | None = None
    notify_state_file_override: Path | None = None
    channels_health_file_override: Path | None = None
    # Bound on the span queue the background exporter drains, so an exporter that is slow
    # or down costs this much memory and no more.
    export_queue_max: int = 1000
    # Wall-clock bound on one flush of that queue.
    export_flush_timeout_s: float = 5.0
    # MCP call timeout when a server sets none.
    mcp_client_timeout_s: float = 10.0
    # Ceiling every server's own timeout is clamped to, so one server cannot stall a turn.
    mcp_client_max_timeout_s: float = 60.0
    # Cap on a `fetch` response body, which goes straight into the model's context;
    # truncation is announced.
    fetch_max_response_bytes: int = 200000
    # Default `fetch` timeout; a call may ask for its own.
    fetch_timeout_s: float = 15.0
    fleet_file_override: Path | None = None
    # The Telegram bot token is an ordinary stored secret under this name, so it gets the
    # same 0600 storage and trace redaction as every other credential.
    telegram_bot_token_key: str = "TELEGRAM_BOT_TOKEN"
    # Telegram's long-poll wait; an empty reply after it is normal. The request timeout
    # must exceed it or an empty poll looks like a local timeout, so
    # interfaces/telegram/bot.py::_resolved_request_timeout clamps a smaller one up.
    telegram_poll_timeout_s: int = 25
    telegram_request_timeout_s: float = 35.0
    # The libsecret service secrets live under with the keyring backend.
    keyring_service: str = "docket-cli"
    # Image for the docker jail. Small and generic: the jail contains a shell command, it
    # does not reproduce a project's runtime.
    sandbox_docker_image: str = "alpine:3.20"
    # Bytes per token for the rough estimate that bounds the static context re-sent every
    # turn; it catches runaway context and is never a billing figure. At least 1.
    context_bytes_per_token: int = 4
    # Per-role retry budgets set in the environment (DISPATCH_RETRIES_<ROLE>); a role not
    # listed uses dispatch_retries_default. A tuple, not a dict, so Home stays hashable.
    dispatch_retries_by_role: tuple[tuple[str, int], ...] = ()
    # Serve-wide timeouts for a hop's turn and verify step, read only by interfaces/http/server.py. A set
    # value overrides the pod's Lead meta for the dispatches `docket start` runs; None
    # leaves teams/settings.py::_resolve_timeout to decide.
    dispatch_turn_timeout_s: int | None = None
    dispatch_verify_timeout_s: int | None = None
    # Exact hostnames `fetch` may reach (comma-separated in the environment, lowercased).
    # Empty by default: an operator opts a domain in, so `fetch` is never a second
    # unattended way out to the network.
    fetch_allowed_domains: tuple[str, ...] = ()

    @classmethod
    def from_environ(cls, env: Mapping[str, str]) -> Home:
        return cls(
            root=Path(env.get("DOCKET_HOME", Path.home() / ".docket")),
            traces_dir_override=_optional_path(env, "TRACES_DIR"),
            audit_log_max_bytes=_int(env, "AUDIT_LOG_MAX_BYTES", 5 * 1024 * 1024),
            policies_dir_override=_optional_path(env, "POLICIES_DIR"),
            plugins_dir_override=_optional_path(env, "PLUGINS_DIR"),
            skills_dir_override=_optional_path(env, "SKILLS_DIR"),
            approvals_dir_override=_optional_path(env, "APPROVALS_DIR"),
            corrections_dir_override=_optional_path(env, "CORRECTIONS_DIR"),
            schedule_file_override=_optional_path(env, "SCHEDULE_FILE"),
            runs_file_override=_optional_path(env, "RUNS_FILE"),
            session_timeout=_int(env, "SESSION_TIMEOUT", 3600),
            approval_timeout=_int(env, "APPROVAL_TIMEOUT", 900),
            tool_approval_timeout=_int(env, "TOOL_APPROVAL_TIMEOUT", 120),
            tool_approval_poll_interval_s=_float(env, "TOOL_APPROVAL_POLL_INTERVAL_S", 2),
            claim_stale_timeout=_int(env, "CLAIM_STALE_TIMEOUT", 1800),
            metrics_window=_int(env, "METRICS_WINDOW", 50),
            runaway_turns_threshold=_int(env, "RUNAWAY_TURNS_THRESHOLD", 200),
            runaway_cost_threshold=_float(env, "RUNAWAY_COST_THRESHOLD", 20),
            key_max_age_days=_int(env, "DOCKET_KEY_MAX_AGE_DAYS", 90),
            trace_retention_days=_int(env, "TRACE_RETENTION_DAYS", 30),
            context_token_budget_override=_optional_int(env, "CONTEXT_TOKEN_BUDGET"),
            distill_timeout_s=_int(env, "DISTILL_TIMEOUT_S", 120),
            dispatch_retries_default=_int(env, "DISPATCH_RETRIES_DEFAULT", 2),
            dispatch_retry_backoff_s=_float(env, "DISPATCH_RETRY_BACKOFF_S", 2),
            dispatch_retry_max_wait_s=_float(env, "DISPATCH_RETRY_MAX_WAIT_S", 60),
            dispatch_sweep_workers=_int(env, "DISPATCH_SWEEP_WORKERS", 4),
            template_version=_int(env, "TEMPLATE_VERSION", 5),
            sessions_dir_override=_optional_path(env, "SESSIONS_DIR"),
            agent_loop_max_iterations=_int(env, "AGENT_LOOP_MAX_ITERATIONS", 20),
            agent_loop_max_tool_calls=_int(env, "AGENT_LOOP_MAX_TOOL_CALLS", 40),
            agent_loop_max_consecutive_tool_denials=_int(
                env, "AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS", 3
            ),
            agent_loop_no_progress_rounds=_int(env, "AGENT_LOOP_NO_PROGRESS_ROUNDS", 3),
            tool_max_output_chars=_int(env, "DOCKET_TOOL_MAX_OUTPUT_CHARS", 30000),
            agent_loop_wall_clock_timeout_s=_float(env, "AGENT_LOOP_WALL_CLOCK_TIMEOUT_S", 300),
            agent_loop_token_budget=_int(env, "AGENT_LOOP_TOKEN_BUDGET", 100000),
            agent_loop_request_timeout_s=_int(env, "AGENT_LOOP_REQUEST_TIMEOUT_S", 120),
            mcp_servers_file_override=_optional_path(env, "MCP_SERVERS_FILE"),
            providers_file_override=_optional_path(env, "PROVIDERS_FILE"),
            exporters_file_override=_optional_path(env, "EXPORTERS_FILE"),
            exporters_health_file_override=_optional_path(env, "EXPORTERS_HEALTH_FILE"),
            channels_file_override=_optional_path(env, "CHANNELS_FILE"),
            notify_state_file_override=_optional_path(env, "NOTIFY_STATE_FILE"),
            channels_health_file_override=_optional_path(env, "CHANNELS_HEALTH_FILE"),
            export_queue_max=_int(env, "EXPORT_QUEUE_MAX", 1000),
            export_flush_timeout_s=_float(env, "EXPORT_FLUSH_TIMEOUT_S", 5.0),
            mcp_client_timeout_s=_float(env, "MCP_CLIENT_TIMEOUT_S", 10),
            mcp_client_max_timeout_s=_float(env, "MCP_CLIENT_MAX_TIMEOUT_S", 60),
            fetch_max_response_bytes=_int(env, "FETCH_MAX_RESPONSE_BYTES", 200000),
            fetch_timeout_s=_float(env, "FETCH_TIMEOUT_S", 15),
            fleet_file_override=_optional_path(env, "FLEET_FILE"),
            telegram_poll_timeout_s=_int(env, "TELEGRAM_POLL_TIMEOUT_S", 25),
            telegram_request_timeout_s=_float(env, "TELEGRAM_REQUEST_TIMEOUT_S", 35),
            keyring_service=env.get("DOCKET_KEYRING_SERVICE", "docket-cli"),
            sandbox_docker_image=env.get("DOCKET_SANDBOX_IMAGE", "alpine:3.20"),
            context_bytes_per_token=max(1, _int(env, "CONTEXT_BYTES_PER_TOKEN", 4)),
            dispatch_retries_by_role=tuple(
                (role, n)
                for role in _RETRY_ROLES
                if (n := _optional_int(env, f"DISPATCH_RETRIES_{role.upper()}")) is not None
            ),
            dispatch_turn_timeout_s=_optional_int(env, "DISPATCH_TURN_TIMEOUT_S"),
            dispatch_verify_timeout_s=_optional_int(env, "DISPATCH_VERIFY_TIMEOUT_S"),
            fetch_allowed_domains=tuple(
                d.strip().lower()
                for d in env.get("FETCH_ALLOWED_DOMAINS", "").split(",")
                if d.strip()
            ),
        )

    @property
    def dispatch_retries_per_role(self) -> dict[str, int]:
        overrides = dict(self.dispatch_retries_by_role)
        return {role: overrides.get(role, self.dispatch_retries_default) for role in _RETRY_ROLES}

    @property
    def model_registry_file(self) -> Path:
        return self.root / "docket-models.json"

    # Pod members' workspaces live under projects/, per-pod runtime directories under pods/.
    @property
    def workspaces_dir(self) -> Path:
        return self.root / "workspaces"

    @property
    def jail_tmp_dir(self) -> Path:
        return self.root / "jail-tmp"

    # What a task worktree's install produced, one entry per codebase and lockfile hash.
    @property
    def prepare_cache_dir(self) -> Path:
        return self.root / "cache" / "prepare"

    @property
    def projects_dir(self) -> Path:
        return self.workspaces_dir / "projects"

    @property
    def pods_dir(self) -> Path:
        return self.workspaces_dir / "pods"

    @property
    def traces_dir(self) -> Path:
        if self.traces_dir_override is not None:
            return self.traces_dir_override
        return self.root / "traces"

    @property
    def audit_log(self) -> Path:
        return self.root / "audit.log"

    # The running `docket start`'s pid, so `docket stop` can find it.
    @property
    def serve_pid_file(self) -> Path:
        return self.root / "serve.pid"

    @property
    def policies_dir(self) -> Path:
        if self.policies_dir_override is not None:
            return self.policies_dir_override
        return self.root / "policies"

    # Operator-applied predicate plugins; never read from a codebase.
    @property
    def plugins_dir(self) -> Path:
        if self.plugins_dir_override is not None:
            return self.plugins_dir_override
        return self.root / "plugins"

    # The operator's skills, the outermost of the three scopes teams/workspace/skills.py reads.
    @property
    def skills_dir(self) -> Path:
        if self.skills_dir_override is not None:
            return self.skills_dir_override
        return self.root / "skills"

    @property
    def approvals_dir(self) -> Path:
        if self.approvals_dir_override is not None:
            return self.approvals_dir_override
        return self.root / "approvals"

    @property
    def corrections_dir(self) -> Path:
        if self.corrections_dir_override is not None:
            return self.corrections_dir_override
        return self.root / "corrections"

    # One 0600 file per parked consult question, read once by dispatch.
    @property
    def consult_parked_dir(self) -> Path:
        return self.root / "consult-parked"

    @property
    def schedule_file(self) -> Path:
        if self.schedule_file_override is not None:
            return self.schedule_file_override
        return self.root / "docket-schedules.json"

    # One record per dispatch run, whatever triggered it.
    @property
    def runs_file(self) -> Path:
        if self.runs_file_override is not None:
            return self.runs_file_override
        return self.root / "docket-runs.json"

    @property
    def trace_retention_s(self) -> int:
        return self.trace_retention_days * 86400

    # Soft cap on the static context re-sent every turn; prompt composition truncates past
    # it. An explicit value wins over the window-aware default.
    @property
    def context_token_budget(self) -> int:
        if self.context_token_budget_override is not None:
            return self.context_token_budget_override
        return self.context_token_budget_default

    @property
    def port_alloc_file(self) -> Path:
        return self.root / "port-allocations.json"

    # Channel conversation state (Telegram threads), so a conversation can resume.
    @property
    def conversations_file(self) -> Path:
        return self.root / "docket-conversations.json"

    # One directory per session key, so appending to or compacting one session's history
    # never blocks or corrupts another's.
    @property
    def sessions_dir(self) -> Path:
        if self.sessions_dir_override is not None:
            return self.sessions_dir_override
        return self.root / "sessions"

    @property
    def mcp_servers_file(self) -> Path:
        if self.mcp_servers_file_override is not None:
            return self.mcp_servers_file_override
        return self.root / "docket-mcp-servers.json"

    # The operator's provider documents, merged nearest-wins over the ones in the wheel.
    @property
    def providers_file(self) -> Path:
        if self.providers_file_override is not None:
            return self.providers_file_override
        return self.root / "docket-providers.json"

    # The limits each provider's /models published, and when they were observed.
    @property
    def provider_models_file(self) -> Path:
        return self.root / "provider-models.json"

    # The operator's exporter documents, merged nearest-wins over the ones in the wheel.
    @property
    def exporters_file(self) -> Path:
        if self.exporters_file_override is not None:
            return self.exporters_file_override
        return self.root / "docket-exporters.json"

    # Per-exporter delivery counters and last error.
    @property
    def exporters_health_file(self) -> Path:
        if self.exporters_health_file_override is not None:
            return self.exporters_health_file_override
        return self.root / "exporters-health.json"

    # The operator's channel documents, merged nearest-wins over the ones in the wheel.
    @property
    def channels_file(self) -> Path:
        if self.channels_file_override is not None:
            return self.channels_file_override
        return self.root / "docket-channels.json"

    # What operator/notify.py::flush already delivered. Saved before delivering, so a crash
    # mid-delivery never sends an event twice (at most once).
    @property
    def notify_state_file(self) -> Path:
        if self.notify_state_file_override is not None:
            return self.notify_state_file_override
        return self.root / "notify-state.json"

    # Per-channel delivery counters and last error.
    @property
    def channels_health_file(self) -> Path:
        if self.channels_health_file_override is not None:
            return self.channels_health_file_override
        return self.root / "channels-health.json"

    # Agent registration, channel bindings and gate flags; per-agent facts stay in each
    # workspace's meta file and are not repeated here.
    @property
    def fleet_file(self) -> Path:
        if self.fleet_file_override is not None:
            return self.fleet_file_override
        return self.root / "fleet.json"

    # The last processed Telegram update id + 1, so a restart does not redeliver the backlog.
    @property
    def telegram_offset_file(self) -> Path:
        return self.root / "docket-telegram-offset.json"

    # Where `docket inbox` last stopped, so a repeat call shows only newly finished tasks.
    @property
    def inbox_cursor_file(self) -> Path:
        return self.root / "inbox-cursor.json"

    @property
    def reviewed_repos_file(self) -> Path:
        return self.root / "reviewed-repos.json"

    # Stored provider credentials and their added/rotated bookkeeping (governance/secrets.py).
    @property
    def secrets_file(self) -> Path:
        return self.root / "secrets.json"

    @property
    def secrets_meta_file(self) -> Path:
        return self.root / "secrets.meta.json"

    @property
    def user_recipes_dir(self) -> Path:
        return self.root / "recipes"

    def workspace_dir(self, agent_id: str) -> Path:
        return self.projects_dir / agent_id

    def meta_path(self, agent_id: str) -> Path:
        return self.workspace_dir(agent_id) / self.meta_file

    def pod_scratch_dir(self, project: str) -> Path:
        """A pod's scratch directory, created 0700 at provisioning and removed on teardown;
        the Implementer sees it as $DOCKET_SCRATCH_DIR."""
        return self.pods_dir / project / ".scratch"

    def pod_cache_dir(self, project: str) -> Path:
        """A pod's cache and the hidden home for jailed commands (HOME, XDG_*, UV_CACHE_DIR)."""
        return self.pods_dir / project / "cache"

    def pod_memory_path(self, project: str) -> Path:
        return self.pods_dir / project / "memory.json"

    def pod_config_dir(self, project: str) -> Path:
        """A pod's configuration overlay, read above the global one for that pod alone."""
        return self.pods_dir / project / "config"

    def pod_work_dir(self, project: str) -> Path:
        """The shared working directory of a pod with no codebase (research, content, ops)."""
        return self.pods_dir / project / "workdir"


_CURRENT: ContextVar[Home | None] = ContextVar("docket_home", default=None)
_DEFAULT: Home | None = None


def current_home() -> Home:
    """The Home set by the innermost use_home(), else the process default built from
    os.environ on first use."""
    global _DEFAULT
    home = _CURRENT.get()
    if home is not None:
        return home
    if _DEFAULT is None:
        _DEFAULT = Home.from_environ(os.environ)
    return _DEFAULT


def reset_default() -> None:
    """Forget the process default, so the next current_home() reads os.environ again."""
    global _DEFAULT
    _DEFAULT = None


@contextmanager
def use_home(home: Home) -> Iterator[Home]:
    """Make *home* current for the block. A bare thread starts without it: start threads with
    kernel.threads so they see the home that started them."""
    token = _CURRENT.set(home)
    try:
        yield home
    finally:
        _CURRENT.reset(token)
