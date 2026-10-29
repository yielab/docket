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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote as _url_unquote

from docket.agent import loop as _loop
from docket.agent import session as _session
from docket.agent.ports import (
    DOCKET_APPROVAL_EXPIRES_AT,
    DOCKET_APPROVAL_MODE,
    DOCKET_APPROVAL_TIMEOUT,
    DOCKET_CONSULT_MODE,
    DOCKET_HANDOFF,
    DOCKET_MAX_CONSULTATIONS,
    DOCKET_PREGRANTS,
    DOCKET_TURN_TOKEN_BUDGET,
    DOCKET_VERDICT_VALUES,
    DOCKET_VERIFY_PLAN,
    PIPELINE_WORKTREE_ENV,
    ChatBackend,
    DriverCapabilities,
    SessionSummary,
    TurnResult,
    UsageReport,
    UsageTotals,
)
from docket.agent.tools.builtins import background
from docket.agent.tools.registry import ToolContext, ToolRegistry
from docket.hops.application import verify_tool as _verify
from docket.hops.application.builtin_tools import builtin_registry, describe_tools
from docket.hops.application.driver_support import (
    _approval_mode,
    _approval_timeout,
    _base_commit_view,
    _build_on_process,
    _consult_mode,
    _load_agent_meta,
    _load_mcp_tools,
    _loop_config,
    _max_consultations,
    _parse_pregrants,
    _resolve_allow_commands,
    _resolve_roots,
    _stdio_launch,
    _task_scope,
    _turn_budgets,
    _turn_result_from,
    _turn_token_budget,
    _validated_pipeline_worktree,
)
from docket.hops.application.handoff_tool import HANDOFF_TOOL, parse_values, register_closing_tool
from docket.kernel.home import current_home
from docket.kernel.ports import process as _process
from docket.models.adapters import openai_http as _llm
from docket.models.application.endpoint import resolve_profile
from docket.observability import telemetry as _telemetry
from docket.observability.adapters import sinks as _exporters
from docket.platform import write_json
from docket.tasks.application import runs as _runs
from docket.teams import pod as _pod
from docket.teams.isolation_posture import (
    hop_read_only,
    jail_cache_dir,
    process_log_dir,
    resolve_posture,
)
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
        profile = resolve_profile(effective_model)
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
        approval_mode = _approval_mode(approval_mode_raw)
        consult_mode_raw = tool_env.pop(DOCKET_CONSULT_MODE, None)
        approval_timeout = _approval_timeout(tool_env.pop(DOCKET_APPROVAL_TIMEOUT, None))
        pregrants_raw = tool_env.pop(DOCKET_PREGRANTS, None)
        verify_plan = _verify.parse_plan(tool_env.pop(DOCKET_VERIFY_PLAN, None))
        pregrants = _parse_pregrants(pregrants_raw)
        approval_expires_at = tool_env.pop(DOCKET_APPROVAL_EXPIRES_AT, None) or None
        max_consultations = _max_consultations(
            agent_id, tool_env.pop(DOCKET_MAX_CONSULTATIONS, None)
        )
        token_budget = _turn_token_budget(tool_env.pop(DOCKET_TURN_TOKEN_BUDGET, None))
        verdict_gate = parse_values(tool_env.pop(DOCKET_VERDICT_VALUES, None))
        offer = tool_env.pop(DOCKET_HANDOFF, None)
        cancellation_signal = _runs.current_cancellation_signal()
        # Same resolution `project=` below applies -- so the `on_process` callback files its
        # trace events under the identical coordinate `agent/loop.py`'s own
        # `_trace_tool_call`/`_trace_tool_result` resolve for the very same turn.
        resolved_project = trace_project or _pod.pod_of(agent_id) or agent_id
        resolved_session_key = trace_session_key or session_key

        ctx_roots = (
            (Path(pipeline_worktree),) if pipeline_worktree else _resolve_roots(meta, agent_id)
        )
        output_cap, read_window = _turn_budgets(profile)
        cache_dir = jail_cache_dir(agent_id, want_sandbox)
        ctx = ToolContext(
            agent_id=agent_id,
            session_key=session_key,
            trace_session_key=trace_session_key or "",
            roots=ctx_roots,
            timeout=timeout,
            output_cap=output_cap,
            read_window=read_window,
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
            consult_mode=_consult_mode(agent_id, consult_mode_raw),
            task_id=trace_task_id or "",
            allow_commands=_resolve_allow_commands(agent_id),
            pregrants=pregrants,
            approval_expires_at=approval_expires_at,
            approval_timeout=approval_timeout,
            cache_dir=cache_dir,
            process_dir=process_log_dir(agent_id, cache_dir),
            read_only=hop_read_only(resolved_project, ctx_roots[0]) if want_sandbox else (),
            on_process=_build_on_process(
                resolved_project, resolved_session_key, meta.role, trace_task_id or ""
            ),
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
        describe_tools(registry, ctx, profile.descriptions)
        register_closing_tool(registry, verdict_gate, offer)
        self.mcp_loader(registry, meta.role, ctx.project, launch=_stdio_launch(ctx))
        if verify_plan is not None:
            registry.register(_verify.verify_tool(verify_plan, ctx.project))
        loop_config = _loop_config(
            backend, timeout, token_budget, profile, HANDOFF_TOOL if verdict_gate else "", ctx
        )
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
            background.stop_all(ctx.processes, ctx.on_process, reason="turn_end")
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
