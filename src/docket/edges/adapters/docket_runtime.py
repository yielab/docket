"""``DocketDriver``: the ``RuntimeDriver`` implementation.

Implements ``core.runtime_driver.RuntimeDriver`` on ``core/agent_loop.py`` so ``core/dispatch.py``,
the pipeline executor, and every Protocol caller work unchanged. ``default_driver()`` is the single
resolution point production callers -- pod dispatch, distillation, cost aggregation, trace
ingestion -- use, running on docket's gated loop.

Every ``run_turn`` runs through ``core.agent_loop.run_agent_turn``, dispatching every tool call
through ``core.tools.dispatch_tool`` -- the one chokepoint every policy/approval/audit guardrail is
built onto. This module never calls a tool handler directly, nor imports
``edges/adapters/toolbox.py``.
"""

from __future__ import annotations

import atexit
import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote as _url_unquote

import docket.config as _cfg
from docket.core import agent_loop as _loop
from docket.core import fleet as _fleet
from docket.core import mcp_tools as _mcp
from docket.core import pod as _pod
from docket.core import runs as _runs
from docket.core import session as _session
from docket.core import telemetry as _telemetry
from docket.core import trace as _trace
from docket.core.audit import audit_log
from docket.core.consult import DEFAULT_MAX_CONSULTATIONS
from docket.core.llm import ChatBackend
from docket.core.models import AgentMeta
from docket.core.runtime_driver import (
    DOCKET_APPROVAL_EXPIRES_AT,
    DOCKET_APPROVAL_MODE,
    DOCKET_MAX_CONSULTATIONS,
    DOCKET_PREGRANTS,
    DOCKET_TURN_TOKEN_BUDGET,
    PIPELINE_WORKTREE_ENV,
    DriverCapabilities,
    SessionSlice,
    SessionSummary,
    SessionTurn,
    TurnResult,
    UsageReport,
    UsageTotals,
)
from docket.core.tools import Pregrant, ToolContext, ToolRegistry, builtin_registry
from docket.edges import store as _store
from docket.edges.adapters import exporters as _exporters
from docket.edges.adapters import llm as _llm
from docket.edges.adapters import system as _system

__all__ = ["DocketDriver"]


def _close_telemetry() -> None:
    """Close every started exporter and record the final flush's counters -- the session root
    is sent there, so its delivery belongs in the health file too."""
    final = _telemetry.close()
    if final:
        with contextlib.suppress(Exception):
            _store.write_json(_cfg.EXPORTERS_HEALTH_FILE, final)


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
# against the live MCP catalog on every read, not only at `config set` time, so a
# selection valid when written but since renamed/removed surfaces here as this
# pod's own stale configuration -- not an ordinary turn failure like an
# unreachable/hung/malformed remote server (which `load_mcp_tools` already
# degrades to "unavailable" for, never raising). Deferred import of
# `core.dispatch.DispatchError`: `core.dispatch` imports this module at module
# scope, so importing it back here would be circular -- by the time any real turn
# calls this function both modules are already fully loaded.
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
        coerced = _pod.PodSettings.coerce("mcpServers", raw)
    except _pod.PodSettingsError as exc:
        from docket.core.dispatch import DispatchError

        raise DispatchError(str(exc)) from exc
    return tuple(str(coerced).split(","))


# Filters the shared catalog by *project*'s pod `mcpServers` selection (see
# `_pod_mcp_selection`, which is what actually raises `DispatchError` for a stale
# selection) before handing the rest to `load_mcp_tools`. ``None`` (no selection
# stored, or *project* names no pod) loads every configured server -- byte-for-byte
# the pre-selection behavior, including the zero-server fast path.
def _load_mcp_tools(registry: ToolRegistry, role: str, project: str = "") -> list[Any]:
    """Fold MCP servers' tools into *registry* in the 3-positional shape ``mcp_loader`` needs."""
    servers = _mcp.load_mcp_servers()
    selection = _pod_mcp_selection(project)
    if selection is not None:
        servers = [s for s in servers if s.name in selection]
    return _mcp.load_mcp_tools(registry, servers=servers, role=role)


def _load_agent_meta(agent_id: str) -> AgentMeta | None:
    """Read *agent_id*'s ``.docket-meta.json`` via ``edges/store.py``. Returns ``(None, "")`` for
    a missing or malformed record rather than raising, per the Protocol's "never raises for an
    ordinary failure" contract."""
    raw = _store.read_json(_cfg.meta_path(agent_id))
    if not raw:
        return None
    try:
        return AgentMeta.model_validate(raw)
    except Exception:
        return None


def _resolve_roots(meta: AgentMeta | None, agent_id: str) -> tuple[Path, ...]:
    """The containment boundary ``dispatch_tool`` enforces: codebase > work_dir > the agent's
    own workspace (a dispatched task's worktree arrives as the pipeline root instead) --
    mirrors ``core.pod.resolve_member_cwd``, extended here (not there) to also cover a
    ``workdir`` pod, which that helper's signature cannot express."""
    if meta is not None and meta.codebase:
        return (Path(meta.codebase),)
    if meta is not None and meta.work_dir:
        return (Path(meta.work_dir),)
    return (_cfg.workspace_dir(agent_id),)


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
        tasks_dir = (_cfg.PROJECTS_DIR / registered.id / "tasks").resolve()
        if candidate_path.parent == tasks_dir and candidate_path.is_dir():
            return str(candidate_path)
    return ""


def _resolve_allow_commands(agent_id: str) -> tuple[str, ...]:
    """This pod's ``allowCommands`` setting, or empty for a non-pod agent or an
    unreadable settings store -- fail closed, never grants more than SAFE_BINS."""
    project = _pod.pod_of(agent_id)
    if project is None:
        return ()
    try:
        return _pod.PodSettings.load_for(project).allow_commands
    except _pod.PodSettingsError:
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
            return _pod.PodSettings.load_for(project).max_consultations_per_task
        except _pod.PodSettingsError:
            pass
    return DEFAULT_MAX_CONSULTATIONS


def _turn_token_budget(raw: str | None) -> int:
    """*raw* as a positive measured-token ceiling, else the configured loop default -- a
    malformed value never raises here (the harness CLI validates its own flag first)."""
    try:
        value = int(raw or "")
    except ValueError:
        return _cfg.AGENT_LOOP_TOKEN_BUDGET
    return value if value > 0 else _cfg.AGENT_LOOP_TOKEN_BUDGET


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


def _resolve_sandbox(agent_id: str, role: str) -> tuple[bool, TurnResult | None]:
    """Fail-closed go/no-go for this turn's isolation posture. Returns ``(want_sandbox,
    refusal)``; a non-``None`` refusal means isolation is on but no backend (docker/bwrap) is
    usable, so the whole turn is refused up front and audited (``isolation.refused``) rather than
    letting ``toolbox.run_bash`` silently degrade per call. See
    specs/functional/security-gates.spec.md ("Fail closed, not fail open, when isolation is on
    and no backend is usable")."""
    if not _fleet.get_isolation_enabled():
        return False, None
    availability = _system.sandbox_availability()
    if availability.backend != "none":
        return True, None
    detail = (
        f"agent={agent_id} role={role or '?'} "
        f"docker={availability.docker} bwrap={availability.bwrap}"
    )
    audit_log("isolation.refused", detail)
    refusal = TurnResult(
        False,
        "",
        0.0,
        {},
        (
            "isolation is enabled (docket gates isolate on) but no sandbox backend "
            "(docker or bwrap) is available on this host -- refusing to run this turn "
            "unsandboxed rather than silently downgrading it. Install/start docker or "
            "bwrap, or turn isolation off ('docket gates isolate off') to run without a "
            "jail."
        ),
        failure_kind="daemon_error",
    )
    return False, refusal


def _build_on_process(
    project: str, session_key: str, role: str
) -> Callable[[str, dict[str, Any]], None]:
    """A `ToolContext.on_process` for one turn: trace a tool call's process lifecycle and,
    while a dispatch run is current, register/clear its pgid against it so `docket runs
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


@dataclass
class DocketDriver:
    """The ``RuntimeDriver`` implementation. ``backend_factory``/``registry_factory``/
    ``mcp_loader`` are test-only injection seams; all three default to production functions, so
    a bare ``DocketDriver()`` is what every non-test caller constructs."""

    backend_factory: Callable[[str], ChatBackend | None] = _llm.client_for
    registry_factory: Callable[[], ToolRegistry] = builtin_registry
    mcp_loader: Callable[[ToolRegistry, str, str], list[Any]] = _load_mcp_tools

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
        """Run one turn through ``core/agent_loop.py``. Never raises, with one deliberate
        exception: ``self.mcp_loader`` raises ``DispatchError`` when this turn's pod
        selects an ``mcpServers`` name absent from the live catalog (see
        ``_load_mcp_tools``'s own docstring) -- a caller misconfiguration, not an
        ordinary turn failure, and every production call site (``core/dispatch.py``'s
        pipeline runner, ``cli/_harness.py``) already lets a raised ``DispatchError``
        propagate to its own settle/fail path rather than treating this driver as
        exception-free. ``on_spawn`` is ignored: this driver backs onto no OS process to
        track -- the loop makes HTTP calls in-process -- and the Protocol allows a
        process-less driver to ignore it. ``timeout`` overrides
        ``LoopConfig.wall_clock_timeout_s`` directly, the same per-hop figure ``core/dispatch.py``
        already resolves, not a second independently-tuned number. ``model``, when given, wins
        over *agent_id*'s own configured model for this call's endpoint only -- a caller (e.g. a
        pipeline step's own override, resolved to a literal by ``core/dispatch.py`` first) is
        responsible for handing this a real ``provider/id``, never a rank word; this driver never
        writes it back to ``.docket-meta.json``. Starts the observability export pipeline lazily
        before the turn and flushes it (recording ``telemetry.health()``) in a ``finally``, so
        both run on every return path -- see ``_run_turn_body`` for the turn itself."""
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
            _telemetry.flush(_cfg.EXPORT_FLUSH_TIMEOUT_S)
            _store.write_json(_cfg.EXPORTERS_HEALTH_FILE, _telemetry.health())

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

        want_sandbox, refusal = _resolve_sandbox(agent_id, meta.role)
        if refusal is not None:
            return refusal

        effective_model = model or meta.model or _cfg.DEFAULT_MODEL
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
        pregrants_raw = tool_env.pop(DOCKET_PREGRANTS, None)
        pregrants = _parse_pregrants(pregrants_raw)
        approval_expires_at = tool_env.pop(DOCKET_APPROVAL_EXPIRES_AT, None) or None
        max_consultations = _max_consultations(
            agent_id, tool_env.pop(DOCKET_MAX_CONSULTATIONS, None)
        )
        token_budget = _turn_token_budget(tool_env.pop(DOCKET_TURN_TOKEN_BUDGET, None))
        cancellation_signal = _runs.current_cancellation_signal()
        # Same resolution `project=` below applies -- so the `on_process` callback files its
        # trace events under the identical coordinate `core/agent_loop.py`'s own
        # `_trace_tool_call`/`_trace_tool_result` resolve for the very same turn.
        resolved_project = trace_project or _pod.pod_of(agent_id) or agent_id
        resolved_session_key = trace_session_key or session_key

        ctx = ToolContext(
            agent_id=agent_id,
            session_key=session_key,
            roots=(Path(pipeline_worktree),)
            if pipeline_worktree
            else _resolve_roots(meta, agent_id),
            timeout=timeout,
            env=tool_env,
            role=meta.role,
            # trace_project (the pod, when a dispatch hop supplies one) is what an
            # in-turn approval gate's trace event must file under. Absent that, resolve
            # the calling agent's own pod, so a standalone pod-member turn still sees
            # that pod's own policy files, not just the global set -- falling back to
            # agent_id only for a non-pod agent (e.g. an org specialist, or the
            # harness), which keeps that caller's behavior unchanged.
            project=resolved_project,
            sandbox="auto" if want_sandbox else "off",
            cancellation_check=(
                cancellation_signal.observe if cancellation_signal is not None else None
            ),
            approval_mode=approval_mode,
            max_consultations=max_consultations,
            # A pod dispatch hop (it names its task): a consult parks the task.
            consult_park=trace_task_id is not None,
            allow_commands=_resolve_allow_commands(agent_id),
            pregrants=pregrants,
            approval_expires_at=approval_expires_at,
            on_process=_build_on_process(resolved_project, resolved_session_key, meta.role),
        )
        # Folded in before the turn loop narrows by role
        # (core.archetypes.registry_for_role, called once inside
        # run_agent_turn) -- narrowing has to see whatever a configured MCP
        # server contributed, or a write-denying role would keep a
        # write-capable MCP tool. See core/archetypes.py's registry_for_role
        # docstring for the kind-based rule that makes this safe. ``ctx.project``
        # (already resolved above) is also this turn's pod for `mcpServers`
        # filtering -- the same value an in-turn approval gate files traces under.
        registry = self.registry_factory()
        self.mcp_loader(registry, meta.role, ctx.project)
        context_window = getattr(backend, "context_window_tokens", None)
        max_output_tokens = getattr(backend, "max_output_tokens", None)
        loop_config = _loop.LoopConfig(
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

        # cost_usd stays 0.0: real token counts are recorded (result.usage,
        # folded into the session's MeasuredUsage by core/session.py), but
        # turning tokens into dollars here would silently convert an estimate
        # into a billing claim — the standing rule this driver does not cross.
        return TurnResult(
            result.ok,
            result.output,
            0.0,
            result.raw,
            result.error,
            failure_kind=result.failure_kind,
            retry_after_s=result.retry_after_s,
            usage=result.usage if result.usage.total_tokens else None,
        )

    def list_sessions(self, agent_id: str) -> list[SessionSummary]:
        """Enumerate this agent's sessions. A directory name is the percent-encoded session KEY
        (``agent:<id>:<project>``), not the bare id, so matching by the ``agent:<id>:`` prefix
        also surfaces every project this agent has ever been scoped to (``docket scope ... set``)."""
        if not _cfg.SESSIONS_DIR.is_dir():
            return []
        prefix = f"agent:{agent_id}:"
        out: list[SessionSummary] = []
        for entry in sorted(_cfg.SESSIONS_DIR.iterdir()):
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

    def read_new_turns(self, agent_id: str, session_id: str, offset: int) -> SessionSlice:
        """Translate stored messages past *offset* (a message index into
        ``core.session.SessionRecord.messages``, the driver-defined cursor unit) into neutral
        turn shapes: one ``tool_call`` per call in an assistant ``tool_calls`` entry, one
        ``tool_result`` per ``tool``-role message, else ``"other"`` (matching
        ``core/trace.py``'s ``trace_ingest`` filter). ``core/session.py`` only records
        session-level ``created``/``updated`` timestamps, so every turn in a slice shares one
        ``ts`` -- coarser than per-record timestamps, but the only documented consumer
        (idle/timeout detection) only needs the last one."""
        record = _session.load_session(session_id)
        messages = record.messages
        total = len(messages)
        if offset >= total:
            return SessionSlice(
                session_id=session_id,
                had_new_content=False,
                session_start_ts="",
                turns=[],
                last_ts=None,
                next_offset=offset,
            )

        turns: list[SessionTurn] = []
        for stored in messages[offset:]:
            if stored.role == "assistant" and stored.tool_calls:
                for call in stored.tool_calls:
                    turns.append(
                        SessionTurn(
                            ts=record.updated,
                            kind="tool_call",
                            daemon_type="assistant.tool_calls",
                            record_id=call.id,
                        )
                    )
            elif stored.role == "tool":
                turns.append(
                    SessionTurn(
                        ts=record.updated,
                        kind="tool_result",
                        daemon_type="tool",
                        record_id=stored.tool_call_id,
                    )
                )
            else:
                turns.append(SessionTurn(ts=record.updated, kind="other", daemon_type=stored.role))

        return SessionSlice(
            session_id=session_id,
            had_new_content=True,
            session_start_ts=record.created if offset == 0 else "",
            turns=turns,
            last_ts=record.updated or None,
            next_offset=total,
        )

    def usage(self, agent_id: str) -> UsageReport:
        """Aggregate this agent's *measured*, non-estimated usage (``core.llm.TokenUsage``) across
        its sessions. ``cost_usd`` stays ``0.0`` and ``by_day`` is always ``[]`` -- see
        specs/functional/cost-tracking.spec.md ("Known gap: --history is always empty")."""
        totals = UsageTotals()
        for summary in self.list_sessions(agent_id):
            record = _session.load_session(summary.session_id)
            totals.input_tokens += record.usage.input_tokens
            totals.output_tokens += record.usage.output_tokens
            totals.cache_read += record.usage.cached_tokens
            totals.turns += record.usage.turns
        return UsageReport(totals=totals, by_day=[])

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            driver_name="docket",
            # cost_usd is 0.0 everywhere in this driver by design (see
            # run_turn/usage docstrings and CLAUDE.md's standing rule) --
            # MODEL_PRICING powers comparative estimates only, never a
            # billing claim.
            reports_cost_usd=False,
            # list_sessions/read_new_turns/usage read real, durable
            # docket-owned session storage (core/session.py).
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
