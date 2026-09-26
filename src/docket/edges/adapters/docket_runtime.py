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
from docket.core.audit import audit_log
from docket.core.llm import ChatBackend
from docket.core.models import AgentMeta
from docket.core.runtime_driver import (
    DOCKET_APPROVAL_MODE,
    PIPELINE_WORKTREE_ENV,
    DriverCapabilities,
    ProvisionResult,
    SessionSlice,
    SessionSummary,
    SessionTurn,
    TeardownResult,
    TurnResult,
    UsageReport,
    UsageTotals,
)
from docket.core.tools import ToolContext, ToolRegistry, builtin_registry
from docket.edges import store as _store
from docket.edges.adapters import llm as _llm
from docket.edges.adapters import system as _system

__all__ = ["DocketDriver"]


def _load_mcp_tools(registry: ToolRegistry, role: str) -> list[Any]:
    """Fold MCP servers' tools into *registry* in the 2-positional shape ``mcp_loader`` needs.
    Never raises; zero configured servers spawns nothing. See specs/functional/mcp-client.spec.md
    (Failure isolation; zero-server fast path)."""
    return _mcp.load_mcp_tools(registry, role=role)


def _load_agent_meta(agent_id: str) -> tuple[AgentMeta | None, str]:
    """Read *agent_id*'s ``.docket-meta.json`` via ``edges/store.py``. Returns ``(None, "")`` for
    a missing or malformed record rather than raising, per the Protocol's "never raises for an
    ordinary failure" contract."""
    raw = _store.read_json(_cfg.meta_path(agent_id))
    if not raw:
        return None, ""
    try:
        meta = AgentMeta.model_validate(raw)
    except Exception:
        return None, ""
    worktree_dir = str(raw.get("worktreeDir") or "")
    return meta, worktree_dir


def _resolve_roots(meta: AgentMeta | None, worktree_dir: str, agent_id: str) -> tuple[Path, ...]:
    """The containment boundary ``dispatch_tool`` enforces: worktree > codebase > work_dir >
    the agent's own workspace -- mirrors ``core.pod.resolve_member_cwd``, extended here (not
    there) to also cover a ``workdir`` pod, which that helper's signature cannot express."""
    if worktree_dir:
        return (Path(worktree_dir),)
    if meta is not None and meta.codebase:
        return (Path(meta.codebase),)
    if meta is not None and meta.work_dir:
        return (Path(meta.work_dir),)
    return (_cfg.workspace_dir(agent_id),)


def _validated_pipeline_worktree(agent_id: str, env: dict[str, str] | None) -> str:
    """Accept a downstream root only when same-pod Implementer metadata owns it."""
    candidate = str((env or {}).get(PIPELINE_WORKTREE_ENV, "")).strip()
    project = _pod.pod_of(agent_id)
    if not candidate or project is None:
        return ""
    candidate_path = Path(candidate).resolve()
    for registered in _fleet.list_agents():
        parsed = _pod.parse_member_id(registered.id, project)
        if parsed is None or parsed[0] != "implementer":
            continue
        raw = _store.read_json(_cfg.meta_path(registered.id))
        recorded = str(raw.get("worktreeDir") or "").strip()
        if recorded and Path(recorded).resolve() == candidate_path:
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


@dataclass
class DocketDriver:
    """The ``RuntimeDriver`` implementation. ``backend_factory``/``registry_factory``/
    ``mcp_loader`` are test-only injection seams; all three default to production functions, so
    a bare ``DocketDriver()`` is what every non-test caller constructs."""

    backend_factory: Callable[[str], ChatBackend | None] = _llm.client_for
    registry_factory: Callable[[], ToolRegistry] = builtin_registry
    mcp_loader: Callable[[ToolRegistry, str], list[Any]] = _load_mcp_tools

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
    ) -> TurnResult:
        """Run one turn through ``core/agent_loop.py``. Never raises. ``on_spawn`` is ignored:
        this driver backs onto no OS process to track -- the loop makes HTTP calls in-process --
        and the Protocol allows a process-less driver to ignore it. ``timeout`` overrides
        ``LoopConfig.wall_clock_timeout_s`` directly, the same per-hop figure ``core/dispatch.py``
        already resolves, not a second independently-tuned number."""
        meta, worktree_dir = _load_agent_meta(agent_id)
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

        model = meta.model or _cfg.DEFAULT_MODEL
        backend = self.backend_factory(model)
        if backend is None:
            return TurnResult(
                False,
                "",
                0.0,
                {},
                f"no endpoint configured for model {model!r}",
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
        approval_mode: Literal["wait", "refuse"] = (
            "refuse" if approval_mode_raw == "refuse" else "wait"
        )
        cancellation_signal = _runs.current_cancellation_signal()
        ctx = ToolContext(
            agent_id=agent_id,
            session_key=session_key,
            roots=(Path(pipeline_worktree),)
            if pipeline_worktree
            else _resolve_roots(meta, worktree_dir, agent_id),
            timeout=timeout,
            env=tool_env,
            role=meta.role,
            # trace_project (the pod, when a dispatch hop supplies one) is what an
            # in-turn approval gate's trace event must file under -- falling back to
            # agent_id keeps every non-dispatch caller (e.g. the harness) unchanged.
            project=trace_project or agent_id,
            sandbox="auto" if want_sandbox else "off",
            cancellation_check=(
                cancellation_signal.observe if cancellation_signal is not None else None
            ),
            approval_mode=approval_mode,
            allow_commands=_resolve_allow_commands(agent_id),
        )
        # Folded in before the turn loop narrows by role
        # (core.archetypes.registry_for_role, called once inside
        # run_agent_turn) -- narrowing has to see whatever a configured MCP
        # server contributed, or a write-denying role would keep a
        # write-capable MCP tool. See core/archetypes.py's registry_for_role
        # docstring for the kind-based rule that makes this safe.
        registry = self.registry_factory()
        self.mcp_loader(registry, meta.role)
        context_window = getattr(backend, "context_window_tokens", None)
        max_output_tokens = getattr(backend, "max_output_tokens", None)
        loop_config = _loop.LoopConfig(
            wall_clock_timeout_s=float(timeout),
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
        )

    def provision(self, agent_id: str, workspace: str, model: str) -> ProvisionResult:
        """Honest no-op, not a silent ``ok=True`` standing in for real work: there is no daemon
        to register with, and ``run_turn`` needs nothing pre-created -- it reads
        ``.docket-meta.json`` fresh and ``core/session.py`` creates session storage lazily.
        ``capabilities().supports_provisioning`` is ``False`` so this is never mistaken for a
        real registration step."""
        return ProvisionResult(
            ok=True,
            message=(
                "no daemon to register with; a docket-native agent needs no "
                "provisioning step beyond the workspace/meta docket already writes"
            ),
        )

    def teardown(self, agent_id: str) -> TeardownResult:
        """Honest no-op: no daemon to unregister from, and deliberately not reaching for
        something to delete. A session is keyed by its full session KEY
        (``agent:<id>:<project>``), not the bare id, so guessing at and deleting "this agent's"
        session files here would be exactly the silent destructive action this codebase's
        approval/audit stack exists to gate; ``docket delete`` already removes the whole
        workspace directly."""
        return TeardownResult(
            ok=True,
            message="no daemon to unregister from; session-file cleanup is not this driver's concern",
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
            # provision/teardown are honest no-ops (see their docstrings):
            # there is no daemon to register or unregister an agent with.
            supports_provisioning=False,
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
