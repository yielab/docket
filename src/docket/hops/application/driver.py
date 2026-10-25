"""``DocketDriver``: the ``RuntimeDriver`` implementation.

Implements ``agent.ports.RuntimeDriver`` on ``agent/loop.py`` so ``hops/application/runner.py``,
the pipeline executor, and every Protocol caller work unchanged. ``default_driver()`` is the single
resolution point production callers -- pod dispatch, distillation, cost aggregation, trace
ingestion -- use, running on docket's gated loop.

Every ``run_turn`` runs through ``agent.loop.run_agent_turn``, dispatching every tool call
through ``agent.tools.registry.dispatch_tool`` -- the one chokepoint every policy/approval/audit guardrail is
built onto. This module never calls a tool handler directly, nor imports
``agent/tools/builtins/toolbox.py``.
"""

from __future__ import annotations

import atexit
import contextlib
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote as _url_unquote

from docket.agent import loop as _loop
from docket.agent import session as _session
from docket.agent.ports import (
    DOCKET_APPROVAL_EXPIRES_AT,
    DOCKET_APPROVAL_MODE,
    DOCKET_APPROVAL_TIMEOUT,
    DOCKET_MAX_CONSULTATIONS,
    DOCKET_PREGRANTS,
    DOCKET_TASK_DENIED_TOOLS,
    DOCKET_TASK_NETWORK,
    DOCKET_TASK_POLICIES,
    DOCKET_TURN_TOKEN_BUDGET,
    PIPELINE_WORKTREE_ENV,
    ChatBackend,
    DriverCapabilities,
    SessionSummary,
    TurnResult,
    UsageReport,
    UsageTotals,
)
from docket.agent.tools import mcp_tools as _mcp
from docket.agent.tools import mcp_types as _mcp_types
from docket.agent.tools.registry import Pregrant, ToolContext, ToolRegistry
from docket.governance import policy as _policy
from docket.hops.application.builtin_tools import builtin_registry, state_bash_rules
from docket.kernel.errors import DispatchError
from docket.kernel.gate import DEFAULT_MAX_CONSULTATIONS
from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.kernel.ports import process as _process
from docket.models.adapters import openai_http as _llm
from docket.observability import telemetry as _telemetry
from docket.observability import trace as _trace
from docket.observability.adapters import sinks as _exporters
from docket.platform import read_json, write_json
from docket.tasks.application import runs as _runs
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import pod as _pod
from docket.teams import pod_settings as _pod_settings
from docket.teams.isolation_posture import hop_read_only, jail_cache_dir, resolve_posture
from docket.teams.models import AgentMeta
from docket.teams.roles import BUILTIN_TOOL_KINDS
from docket.teams.workspace import repo_view as _repo_view

__all__ = ["DocketDriver"]


def _close_telemetry() -> None:
    """Close every started exporter and record the final flush's counters -- the session root
    is sent there, so its delivery belongs in the health file too."""
    final = _telemetry.close()
    if final:
        with contextlib.suppress(Exception):
            write_json(current_home().exporters_health_file, final)


# Runs once per process at import time. `telemetry.close()` returns `{}` when nothing was
# ever started, so this is harmless in every test process and CLI invocation that never
# enables an exporter.
atexit.register(_close_telemetry)


# Reads and validates *only* the mcpServers meta key, through `PodSettings.coerce` --
# not `PodSettings.load_for`, which validates every stored key at once the way
# `_resolve_allow_commands` above deliberately avoids for `allowCommands`. This
# turn's live path must not refuse over an unrelated stored key (e.g. a hand-edited
# `turnTimeoutS`); only a bad `mcpServers` value itself is this function's concern.
# Unlike `allowCommands`'s fail-open pattern, a bad value here *is* re-raised as
# `DispatchError`, never swallowed: `coerce`'s validator checks every stored name
# against the live MCP catalog on every read, not only at `pod set` time, so a
# selection valid when written but since renamed/removed surfaces here as this
# pod's own stale configuration -- not an ordinary turn failure like an
# unreachable/hung/malformed remote server (which `load_mcp_tools` already
# degrades to "unavailable" for, never raising).
def _pod_mcp_selection(project: str) -> tuple[str, ...] | None:
    """*project*'s own `mcpServers` pod setting, or ``None`` (load every configured
    server) for a non-pod caller or an unset setting."""
    if not project:
        return None
    lead_id = _pod.member_id(project, "lead")
    raw = _fleet.meta_get(lead_id, "mcpServers", "")
    if not raw:
        return None
    try:
        coerced = _pod_settings.PodSettings.coerce("mcpServers", raw, project=project)
    except _pod_settings.PodSettingsError as exc:
        raise DispatchError(str(exc)) from exc
    return tuple(str(coerced).split(","))


def _stdio_launch(ctx: ToolContext) -> _mcp_types.StdioLaunch:
    """How this turn starts stdio servers: its root, and its jail when the turn is isolated."""
    return _mcp_types.StdioLaunch(
        cwd=str(ctx.roots[0]),
        sandbox=ctx.sandbox,
        network=ctx.network,
        roots=ctx.roots,
        read_only=ctx.read_only,
    )


# Filters the shared catalog by *project*'s pod `mcpServers` selection (see
# `_pod_mcp_selection`, which is what actually raises `DispatchError` for a stale
# selection) before handing the rest to `load_mcp_tools`. ``None`` (no selection
# stored, or *project* names no pod) loads every configured server -- byte-for-byte
# the pre-selection behavior, including the zero-server fast path.
def _load_mcp_tools(
    registry: ToolRegistry,
    role: str,
    project: str = "",
    launch: _mcp_types.StdioLaunch | None = None,
) -> list[Any]:
    """Fold MCP servers' tools into *registry*; *launch* is how this turn starts stdio servers."""
    servers = _mcp_servers.load_mcp_servers(project)
    selection = _pod_mcp_selection(project)
    if selection is not None:
        servers = [s for s in servers if s.name in selection]
    if launch is None:
        return _mcp.load_mcp_tools(registry, servers=servers, role=role, project=project)
    return _mcp.load_mcp_tools(registry, servers=servers, role=role, project=project, launch=launch)


def _load_agent_meta(agent_id: str) -> AgentMeta | None:
    """Read *agent_id*'s ``.docket-meta.json`` via ``platform/store.py``. Returns ``(None, "")`` for
    a missing or malformed record rather than raising, per the Protocol's "never raises for an
    ordinary failure" contract."""
    raw = read_json(current_home().meta_path(agent_id))
    if not raw:
        return None
    try:
        return AgentMeta.model_validate(raw)
    except Exception:
        return None


def _resolve_roots(meta: AgentMeta | None, agent_id: str) -> tuple[Path, ...]:
    """The containment boundary ``dispatch_tool`` enforces: codebase > work_dir > the agent's
    own workspace (a dispatched task's worktree arrives as the pipeline root instead) --
    mirrors ``teams.pod.resolve_member_cwd``, extended here (not there) to also cover a
    ``workdir`` pod, which that helper's signature cannot express."""
    if meta is not None and meta.codebase:
        return (Path(meta.codebase),)
    if meta is not None and meta.work_dir:
        return (Path(meta.work_dir),)
    return (current_home().workspace_dir(agent_id),)


def _approval_timeout(raw: str | None) -> int | None:
    """A positive whole number of seconds from the env coordinate, else ``None``."""
    try:
        seconds = int(raw) if raw else 0
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def _validated_pipeline_worktree(agent_id: str, env: dict[str, str] | None) -> str:
    """Accept a task root only when it is a directory under a same-pod Implementer's
    ``tasks/`` worktree directory."""
    candidate = str((env or {}).get(PIPELINE_WORKTREE_ENV, "")).strip()
    project = _pod.pod_of(agent_id)
    if not candidate or project is None:
        return ""
    candidate_path = Path(candidate).resolve()
    for registered in _fleet.list_agents():
        parsed = _pod.parse_member_id(registered.id, project)
        if parsed is None or parsed[0] != "implementer":
            continue
        tasks_dir = (current_home().projects_dir / registered.id / "tasks").resolve()
        if candidate_path.parent == tasks_dir and candidate_path.is_dir():
            return str(candidate_path)
    return ""


def _base_commit_view(
    pipeline_worktree: str, project: str, task_id: str
) -> _repo_view.RepoView | None:
    """The codebase's files at the task's recorded ``baseCommit``, or ``None`` (read the filesystem)
    without a task worktree, a base commit or recorded git dirs: without those, host-side git
    could not be kept off the worktree's own agent-writable ``.git`` file."""
    if not pipeline_worktree or not task_id:
        return None

    try:
        task = TaskRepository.for_pod(project).get(task_id)
    except Exception:  # an unreadable queue file must not fail the turn
        return None
    if task is None or task.worktree is None:
        return None
    record = task.worktree
    base, git_dir = record.base_commit, record.git_dir or ""
    common_dir, recorded = record.common_dir or "", record.dir
    if not (base and git_dir and common_dir and recorded):
        return None
    if Path(recorded).resolve() != Path(pipeline_worktree).resolve():
        return None
    _git.trust_worktree(pipeline_worktree, git_dir, common_dir)
    return _repo_view.RepoView(
        base,
        lambda rel: _git.git_read_blob(pipeline_worktree, base, rel),
        lambda rel: _git.git_list_tree_dirs(pipeline_worktree, base, rel),
    )


def _resolve_allow_commands(agent_id: str) -> tuple[str, ...]:
    """This pod's ``allowCommands`` setting, or empty for a non-pod agent or an
    unreadable settings store -- fail closed, never grants more than SAFE_BINS."""
    project = _pod.pod_of(agent_id)
    if project is None:
        return ()
    try:
        return _pod_settings.PodSettings.load_for(project).allow_commands
    except _pod_settings.PodSettingsError:
        return ()


def _max_consultations(agent_id: str, raw: str | None) -> int:
    """This turn's ``consult`` budget: the caller's env value, else the agent's pod setting
    ``maxConsultationsPerTask``, else the default; a malformed value never raises."""
    if raw is not None:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    project = _pod.pod_of(agent_id)
    if project is not None:
        try:
            return _pod_settings.PodSettings.load_for(project).max_consultations_per_task
        except _pod_settings.PodSettingsError:
            pass
    return DEFAULT_MAX_CONSULTATIONS


def _turn_token_budget(raw: str | None) -> int:
    """*raw* as a positive measured-token ceiling, else the configured loop default -- a
    malformed value never raises here."""
    try:
        value = int(raw or "")
    except ValueError:
        return current_home().agent_loop_token_budget
    return value if value > 0 else current_home().agent_loop_token_budget


def _task_scope(registry: ToolRegistry, tool_env: dict[str, str]) -> AbstractContextManager[None]:
    """The policy scope for the turn's task restrictions; pops their coordinates from *tool_env*
    so no tool sees them (the network one was read by ``resolve_posture``)."""
    tool_env.pop(DOCKET_TASK_NETWORK, None)
    denied_raw = tool_env.pop(DOCKET_TASK_DENIED_TOOLS, None)
    policies_raw = tool_env.pop(DOCKET_TASK_POLICIES, None)
    return _policy.task_policies(_task_policy_documents(registry, denied_raw, policies_raw))


def _loop_config(backend: ChatBackend, timeout: int, token_budget: int) -> _loop.LoopConfig:
    """The turn loop's bounds: wall clock, measured-token budget and the endpoint's own windows."""
    context_window = getattr(backend, "context_window_tokens", None)
    max_output_tokens = getattr(backend, "max_output_tokens", None)
    return _loop.LoopConfig(
        wall_clock_timeout_s=float(timeout),
        token_budget=token_budget,
        context_window_tokens=(
            context_window if isinstance(context_window, int) and context_window > 0 else None
        ),
        max_tokens=(
            max_output_tokens
            if isinstance(max_output_tokens, int) and max_output_tokens > 0
            else None
        ),
    )


def _task_policy_documents(
    registry: ToolRegistry, denied_raw: str | None, policies_raw: str | None
) -> list[dict[str, Any]]:
    """The turn's task-restriction policy documents: one block document for the denied tools
    (closed by kind, like ``registry_for_role``) plus the task's own, already-checked documents."""

    documents: list[dict[str, Any]] = []
    try:
        denied = [str(n) for n in json.loads(denied_raw)] if denied_raw else []
        if denied:
            kinds = {kind for name in denied if (kind := BUILTIN_TOOL_KINDS.get(name))}
            named = {
                name
                for name in registry.names()
                if (tool := registry.get(name)) is not None and tool.kind in kinds
            }
            documents.append(_policy.denied_tools_document(sorted({*denied, *named})))
        for doc in json.loads(policies_raw) if policies_raw else []:
            documents.append(_policy.checked_task_document(doc))
    except ValueError as exc:
        raise DispatchError(f"task restrictions refused: {exc}") from exc
    return documents


def _parse_pregrants(raw: str | None) -> tuple[Pregrant, ...]:
    """Decode ``DOCKET_PREGRANTS``' JSON list into ``Pregrant`` tuples; malformed or
    incomplete entries are dropped rather than raised, fail closed (a dropped entry
    just asks again instead of granting)."""
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return ()
    if not isinstance(parsed, list):
        return ()
    out: list[Pregrant] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        token = str(item.get("token", ""))
        tool = str(item.get("tool", ""))
        args_digest = str(item.get("argsDigest", ""))
        if token and tool and args_digest:
            out.append(Pregrant(token=token, tool=tool, args_digest=args_digest))
    return tuple(out)


def _build_on_process(
    project: str, session_key: str, role: str
) -> Callable[[str, dict[str, Any]], None]:
    """A `ToolContext.on_process` for one turn: trace a tool call's process lifecycle and,
    while a dispatch run is current, register/clear its pgid against it so `docket task
    cancel` reaches a live subprocess."""

    def _on_process(kind: str, data: dict[str, Any]) -> None:
        run_id = _runs.current_run_id()
        pgid = data.get("pgid")
        if run_id is not None and isinstance(pgid, int):
            if kind == "started":
                _runs.add_hop_pid(run_id, pgid)
            elif kind == "exited":
                _runs.remove_hop_pid(run_id, pgid)
        _trace.trace_event(project, session_key, role, f"process_{kind}", json.dumps(data))

    return _on_process


def _turn_result_from(result: _loop.AgentLoopResult) -> TurnResult:
    """The loop outcome as the driver port's ``TurnResult``, field for field plus the loop's own
    stop reason. ``cost_usd`` stays 0.0: tokens are measured, and turning them into dollars
    here would silently convert an estimate into a billing claim."""
    return TurnResult(
        result.ok,
        result.output,
        0.0,
        result.raw,
        result.error,
        failure_kind=result.failure_kind,
        retry_after_s=result.retry_after_s,
        usage=result.usage if result.usage.total_tokens else None,
        stop_reason=result.stop_reason,
        model=result.model,
        provider=result.provider,
    )


@dataclass
class DocketDriver:
    """The ``RuntimeDriver`` implementation. ``backend_factory``/``registry_factory``/
    ``mcp_loader`` are test-only injection seams; all three default to production functions, so
    a bare ``DocketDriver()`` is what every non-test caller constructs."""

    backend_factory: Callable[[str], ChatBackend | None] = _llm.client_for
    registry_factory: Callable[[], ToolRegistry] = builtin_registry
    mcp_loader: Callable[..., list[Any]] = _load_mcp_tools

    def run_turn(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int = 300,
        env: dict[str, str] | None = None,
        *,
        on_spawn: Callable[[int], None] | None = None,
        trace_project: str | None = None,
        trace_session_key: str | None = None,
        trace_task_id: str | None = None,
        model: str | None = None,
    ) -> TurnResult:
        """Run one turn through ``agent/loop.py``. Never raises, with one deliberate
        exception: ``DispatchError`` for a deterministic refusal -- a refused isolation or
        network posture (``resolve_posture``), or ``self.mcp_loader`` finding an ``mcpServers``
        name absent from the live catalog (see ``_load_mcp_tools``'s own docstring). A caller
        misconfiguration, not an ordinary turn failure, and every production call site (``hops/application/executor.py``'s
        pipeline runner) already lets a raised ``DispatchError``
        propagate to its own settle/fail path rather than treating this driver as
        exception-free. ``on_spawn`` is ignored: this driver backs onto no OS process to
        track -- the loop makes HTTP calls in-process -- and the Protocol allows a
        process-less driver to ignore it. ``timeout`` overrides
        ``LoopConfig.wall_clock_timeout_s`` directly, the same per-hop figure ``hops/application/runner.py``
        already resolves, not a second independently-tuned number. ``model``, when given, wins
        over *agent_id*'s own configured model for this call's endpoint only -- a caller (e.g. a
        pipeline step's own override, resolved to a literal by ``hops/application/runner.py`` first) is
        responsible for handing this a real ``provider/id``, never a rank word; this driver never
        writes it back to ``.docket-meta.json``. Starts the observability export pipeline lazily
        before the turn and flushes it (recording ``telemetry.health()``) in a ``finally``, so
        both run on every return path -- see ``_run_turn_body`` for the turn itself."""
        _process.make_non_dumpable()
        _telemetry.start(_telemetry.load_enabled_exporters(), _exporters.sink_for)
        try:
            return self._run_turn_body(
                agent_id,
                session_key,
                message,
                timeout,
                env,
                trace_project=trace_project,
                trace_session_key=trace_session_key,
                trace_task_id=trace_task_id,
                model=model,
            )
        finally:
            _telemetry.flush(current_home().export_flush_timeout_s)
            write_json(current_home().exporters_health_file, _telemetry.health())

    def _run_turn_body(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None,
        *,
        trace_project: str | None,
        trace_session_key: str | None,
        trace_task_id: str | None,
        model: str | None,
    ) -> TurnResult:
        """The turn itself, unwrapped from ``run_turn``'s export-pipeline start/flush so that
        wrapper stays short and this keeps the original, unindented turn logic."""
        meta = _load_agent_meta(agent_id)
        if meta is None:
            return TurnResult(
                False,
                "",
                0.0,
                {},
                f"no .docket-meta.json found for agent {agent_id!r}",
                failure_kind="invalid_output",
            )

        want_sandbox, network_allowed = resolve_posture(agent_id, meta.role, env)
        effective_model = model or meta.model or current_home().default_model
        backend = self.backend_factory(effective_model)
        if backend is None:
            return TurnResult(
                False,
                "",
                0.0,
                {},
                f"no endpoint configured for model {effective_model!r}",
                failure_kind="daemon_error",
            )

        pipeline_worktree = _validated_pipeline_worktree(agent_id, env)
        tool_env = dict(env or {})
        tool_env.pop(PIPELINE_WORKTREE_ENV, None)
        # Same route as PIPELINE_WORKTREE_ENV: an internal env coordinate,
        # never a real tool-visible variable, so it is popped before
        # tool_env reaches ToolContext.env. An unset or unrecognized value
        # keeps today's default ("wait") byte for byte.
        approval_mode_raw = tool_env.pop(DOCKET_APPROVAL_MODE, None)
        approval_mode: Literal["wait", "park", "refuse"] = (
            "refuse"
            if approval_mode_raw == "refuse"
            else "park"
            if approval_mode_raw == "park"
            else "wait"
        )
        approval_timeout = _approval_timeout(tool_env.pop(DOCKET_APPROVAL_TIMEOUT, None))
        pregrants_raw = tool_env.pop(DOCKET_PREGRANTS, None)
        pregrants = _parse_pregrants(pregrants_raw)
        approval_expires_at = tool_env.pop(DOCKET_APPROVAL_EXPIRES_AT, None) or None
        max_consultations = _max_consultations(
            agent_id, tool_env.pop(DOCKET_MAX_CONSULTATIONS, None)
        )
        token_budget = _turn_token_budget(tool_env.pop(DOCKET_TURN_TOKEN_BUDGET, None))
        cancellation_signal = _runs.current_cancellation_signal()
        # Same resolution `project=` below applies -- so the `on_process` callback files its
        # trace events under the identical coordinate `agent/loop.py`'s own
        # `_trace_tool_call`/`_trace_tool_result` resolve for the very same turn.
        resolved_project = trace_project or _pod.pod_of(agent_id) or agent_id
        resolved_session_key = trace_session_key or session_key

        ctx_roots = (
            (Path(pipeline_worktree),) if pipeline_worktree else _resolve_roots(meta, agent_id)
        )
        ctx = ToolContext(
            agent_id=agent_id,
            session_key=session_key,
            roots=ctx_roots,
            timeout=timeout,
            env=tool_env,
            role=meta.role,
            # trace_project (the pod, when a dispatch hop supplies one) is what an
            # in-turn approval gate's trace event must file under. Absent that, resolve
            # the calling agent's own pod, so a standalone pod-member turn still sees
            # that pod's own policy files, not just the global set -- falling back to
            # agent_id only for a non-pod agent.
            project=resolved_project,
            sandbox="auto" if want_sandbox else "off",
            network=network_allowed,
            cancellation_check=(
                cancellation_signal.observe if cancellation_signal is not None else None
            ),
            approval_mode=approval_mode,
            max_consultations=max_consultations,
            # A pod dispatch hop (it names its task): a consult parks the task.
            consult_park=bool(trace_task_id),
            task_id=trace_task_id or "",
            allow_commands=_resolve_allow_commands(agent_id),
            pregrants=pregrants,
            approval_expires_at=approval_expires_at,
            approval_timeout=approval_timeout,
            cache_dir=jail_cache_dir(agent_id, want_sandbox),
            read_only=hop_read_only(resolved_project, ctx_roots[0]) if want_sandbox else (),
            on_process=_build_on_process(resolved_project, resolved_session_key, meta.role),
        )
        # Folded in before the turn loop narrows by role
        # (teams.roles.registry_for_role, called once inside
        # run_agent_turn) -- narrowing has to see whatever a configured MCP
        # server contributed, or a write-denying role would keep a
        # write-capable MCP tool. See teams/roles.py's registry_for_role
        # docstring for the kind-based rule that makes this safe. ``ctx.project``
        # (already resolved above) is also this turn's pod for `mcpServers`
        # filtering -- the same value an in-turn approval gate files traces under.
        registry = self.registry_factory()
        state_bash_rules(registry, ctx)
        self.mcp_loader(registry, meta.role, ctx.project, launch=_stdio_launch(ctx))
        loop_config = _loop_config(backend, timeout, token_budget)
        view = _base_commit_view(pipeline_worktree, resolved_project, trace_task_id or "")
        view_token = _repo_view.register(pipeline_worktree, view) if view is not None else None
        try:
            with _task_scope(registry, tool_env):
                result = _loop.run_agent_turn(
                    backend,
                    registry,
                    ctx,
                    session_key,
                    message,
                    config=loop_config,
                    trace_project=trace_project,
                    trace_session_key=trace_session_key,
                    trace_task_id=trace_task_id or "",
                )
        finally:
            if view_token is not None:
                _repo_view.unregister(view_token)

        turn = _turn_result_from(result)
        if view is not None:
            turn.repo_files = dict(view.composed)
        return turn

    def list_sessions(self, agent_id: str) -> list[SessionSummary]:
        """Enumerate this agent's sessions. A directory name is the percent-encoded session KEY
        (``agent:<id>:<project>``), not the bare id, so matching by the ``agent:<id>:`` prefix
        also surfaces every project key this agent has had."""
        if not current_home().sessions_dir.is_dir():
            return []
        prefix = f"agent:{agent_id}:"
        out: list[SessionSummary] = []
        for entry in sorted(current_home().sessions_dir.iterdir()):
            if not entry.is_dir():
                continue
            key = _url_unquote(entry.name)
            if not key.startswith(prefix):
                continue
            record = _session.load_session(key)
            out.append(
                SessionSummary(
                    session_id=key, turns=len(record.messages), last_active=record.updated
                )
            )
        return out

    def usage(self, agent_id: str) -> UsageReport:
        """Aggregate this agent's *measured*, non-estimated usage (``agent.ports.TokenUsage``) across
        its sessions. ``cost_usd`` stays ``0.0`` and ``by_day`` is always ``[]`` -- see
        specs/functional/cost-tracking.spec.md ("Known gap: --history is always empty")."""
        totals = UsageTotals()
        for summary in self.list_sessions(agent_id):
            record = _session.load_session(summary.session_id)
            totals.input_tokens += record.usage.input_tokens
            totals.output_tokens += record.usage.output_tokens
            totals.cache_read += record.usage.cached_tokens
            totals.cache_write += record.usage.cache_write_tokens
            totals.turns += record.usage.turns
        return UsageReport(totals=totals, by_day=[])

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            driver_name="docket",
            # cost_usd is 0.0 everywhere in this driver by design (see
            # run_turn/usage docstrings and CLAUDE.md's standing rule) --
            # the provider catalog's prices power comparative estimates only, never a
            # billing claim.
            reports_cost_usd=False,
            # list_sessions/usage read real, durable
            # docket-owned session storage (agent/session.py).
            supports_sessions=True,
        )


_DRIVER: DocketDriver | None = None


def default_driver() -> DocketDriver:
    """Return the process-wide ``DocketDriver`` singleton. Stateless, so a fresh instance would
    behave identically; this just gives every real caller one named object. See the module
    docstring for the full list of call sites that resolve the driver here."""
    global _DRIVER
    if _DRIVER is None:
        _DRIVER = DocketDriver()
    return _DRIVER
