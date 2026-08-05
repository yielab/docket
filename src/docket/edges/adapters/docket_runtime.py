"""``DocketDriver``: the ``RuntimeDriver`` implementation.

Implements ``core.runtime_driver.RuntimeDriver`` on top of ``core/agent_loop.py``
so ``core/dispatch.py``, the pipeline executor and every existing caller that
programs against the Protocol work unchanged.

This module's own ``default_driver()`` below is the single resolution point
every production caller uses, so a production pod-dispatch hop (and every
other driver-backed turn: distillation, cost aggregation, trace ingestion)
executes here, on docket's own gated loop.

Every ``run_turn`` goes through ``core.agent_loop.run_agent_turn``, which in
turn dispatches every tool call through ``core.tools.dispatch_tool`` — the one
chokepoint every policy/approval/audit guardrail is built onto. This module
never calls a tool handler directly and never imports
``edges/adapters/toolbox.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote as _url_unquote

import docket.config as _cfg
from docket.core import agent_loop as _loop
from docket.core import fleet as _fleet
from docket.core import mcp_tools as _mcp
from docket.core import session as _session
from docket.core.audit import audit_log
from docket.core.llm import ChatBackend
from docket.core.models import AgentMeta
from docket.core.runtime_driver import (
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
    """Fold every configured MCP server's tools into *registry* for this turn.

    Thin wrapper around ``core.mcp_tools.load_mcp_tools`` so
    ``DocketDriver``'s injection seam (``mcp_loader``) has a fixed
    two-positional shape a test can substitute without matching
    ``load_mcp_tools``'s full keyword surface. Called with zero configured
    servers on every install that has never run ``docket mcp servers add``
    (the overwhelming default) -- that path is one cheap JSON read
    (``core.mcp_tools.load_mcp_servers``) and returns immediately, never
    spawning a subprocess or mutating *registry*. Never raises: see
    ``core/mcp_tools.py``'s "Failure isolation" docstring section -- an
    unreachable, slow, or malformed server degrades to "unavailable" rather
    than failing the turn this registry is about to be used for.
    """
    return _mcp.load_mcp_tools(registry, role=role)


def _load_agent_meta(agent_id: str) -> tuple[AgentMeta | None, str]:
    """Read *agent_id*'s ``.docket-meta.json`` directly through ``edges/store.py``.

    ``.docket-meta.json`` is docket's own metadata and has never needed
    anything beyond ``edges/store.py`` to read. Returns ``(None, "")`` for a
    missing or malformed record rather than raising — every driver method
    here follows the Protocol's "never raises for an ordinary failure"
    contract.
    """
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
    """The containment boundary ``dispatch_tool`` enforces for this agent's calls.

    Precedence — worktree > codebase > work_dir > the agent's own docket
    workspace — mirrors ``core.pod.resolve_member_cwd``, but also covers a
    ``workdir``-kind pod (``codebase`` empty, ``work_dir`` set): that helper's
    signature has no ``work_dir`` parameter, so a ``workdir`` pod falls
    straight through to the raw workspace dir. Written fresh here, rather
    than reused, because closing that gap in ``core/pod.py`` is out of scope
    for this module, and this driver should not repeat a known incompleteness
    in new code it fully controls.
    """
    if worktree_dir:
        return (Path(worktree_dir),)
    if meta is not None and meta.codebase:
        return (Path(meta.codebase),)
    if meta is not None and meta.work_dir:
        return (Path(meta.work_dir),)
    return (_cfg.workspace_dir(agent_id),)


def _resolve_sandbox(agent_id: str, role: str) -> tuple[bool, TurnResult | None]:
    """Turn the operator's isolation posture into a go/no-go for this turn.

    ``core/fleet.py``'s ``get_isolation_enabled`` is the single coherent
    source ``docket gates isolate on``/``off`` and the ``non-main``/``all``
    mode setters all funnel through (``set_isolation_enabled``,
    ``set_sandbox_isolation``, ``disable_sandbox_isolation`` all write the
    same ``security.isolation_enabled`` field) -- reading it here, rather
    than ``get_isolation_mode``, means this can never disagree with what
    ``docket gates status`` prints.

    Returns ``(want_sandbox, refusal)``. ``want_sandbox=False`` with no
    refusal is the byte-identical-to-today default path (isolation off, or
    never configured): the caller passes ``sandbox="off"`` and nothing about
    ``ToolContext`` construction changes. ``want_sandbox=True`` means a real
    backend was actually probed and found usable *right now*
    (``edges.adapters.system.sandbox_availability``, which itself honours
    ``DOCKET_SANDBOX_BACKEND`` -- this function adds no parallel backend
    selection, it only adds the go/no-go gate in front of the existing one).

    A non-``None`` refusal is the fail-closed half this function exists for:
    isolation is turned on, but neither docker nor bwrap is usable on this
    host. The alternative -- handing ``sandbox="auto"`` to the loop anyway
    and letting ``toolbox.run_bash`` degrade per call to an honest
    ``[sandbox: none (...)]``-tagged *unsandboxed* run -- is exactly the
    silent downgrade this card exists to end: an operator who ran ``docket
    gates isolate on`` reads that marker, if they read it at all, buried in
    one tool call's output, long after the command already ran on the bare
    host. Refusing the whole turn up front is the loud, audited version of
    the same fact, and it is audited here (``isolation.refused``) precisely
    because nothing else will run to record it -- a refused turn produces no
    tool calls, so there is no ``dispatch_tool`` entry to carry this reason.
    """
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
    """The ``RuntimeDriver`` implementation.

    ``backend_factory``/``registry_factory``/``mcp_loader`` are the injection
    seams a test needs (a stubbed ``ChatBackend``, a narrower tool set, a
    fake MCP server without a real subprocess); all three default to the
    real production functions, so a bare ``DocketDriver()`` is what every
    non-test caller constructs.
    """

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
    ) -> TurnResult:
        """Run one turn through ``core/agent_loop.py``. Never raises.

        ``on_spawn`` is ignored: this driver backs onto no OS process for a
        caller to track or cancel — the loop makes HTTP calls in-process, not
        a subprocess. The Protocol's own docstring says a driver with no real
        process to report may simply ignore this, and every existing caller
        treats it as optional.

        ``timeout`` is the whole turn's wall-clock budget (the same per-hop
        figure ``core/dispatch.py`` already resolves via its own
        ``DEFAULT_TIMEOUT``/overrides) — it becomes
        ``LoopConfig.wall_clock_timeout_s`` directly, not a second,
        independently-tuned number.
        """
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

        ctx = ToolContext(
            agent_id=agent_id,
            session_key=session_key,
            roots=_resolve_roots(meta, worktree_dir, agent_id),
            timeout=timeout,
            env=dict(env or {}),
            role=meta.role,
            project=agent_id,
            sandbox="auto" if want_sandbox else "off",
        )
        # Folded in before the turn loop narrows by role
        # (core.archetypes.registry_for_role, called once inside
        # run_agent_turn) -- narrowing has to see whatever a configured MCP
        # server contributed, or a write-denying role would keep a
        # write-capable MCP tool. See core/archetypes.py's registry_for_role
        # docstring for the kind-based rule that makes this safe.
        registry = self.registry_factory()
        self.mcp_loader(registry, meta.role)
        loop_config = _loop.LoopConfig(wall_clock_timeout_s=float(timeout))
        result = _loop.run_agent_turn(
            backend, registry, ctx, session_key, message, config=loop_config
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
        """No daemon exists to register *agent_id* with.

        An honest no-op, not a silent ``ok=True`` standing in for real work:
        ``docket add``/``docket install`` already create the workspace and
        ``.docket-meta.json`` directly, with no daemon-registration step in
        between, and ``run_turn`` above needs nothing pre-created — it reads
        ``.docket-meta.json`` and resolves an endpoint fresh on every call,
        and ``core/session.py`` creates a session's storage lazily on first
        ``append_messages``. ``capabilities().supports_provisioning`` is
        ``False`` precisely so a caller does not mistake this for a real
        registration step -- no driver has one any more.
        """
        return ProvisionResult(
            ok=True,
            message=(
                "no daemon to register with; a docket-native agent needs no "
                "provisioning step beyond the workspace/meta docket already writes"
            ),
        )

    def teardown(self, agent_id: str) -> TeardownResult:
        """No daemon exists to unregister *agent_id* from.

        Also an honest no-op, and deliberately not reaching for something to
        delete: this Protocol member takes only an ``agent_id``, but a
        session's on-disk location is keyed by its full session KEY
        (``agent:<id>:<project>``), of which one agent may have had several
        over its lifetime (``docket scope ... set``). Guessing at, or
        enumerating and deleting, "this agent's" session files from an id
        alone is exactly the kind of silent, unreviewed destructive action
        this codebase's approval/audit stack exists to gate — and
        ``docket delete`` already removes the whole workspace directory
        directly. Session-file lifecycle tied to fleet deletion is a
        separate concern from this driver method.
        """
        return TeardownResult(
            ok=True,
            message="no daemon to unregister from; session-file cleanup is not this driver's concern",
        )

    def list_sessions(self, agent_id: str) -> list[SessionSummary]:
        """Enumerate this agent's sessions from docket's own session store.

        A session's directory name is its percent-encoded session KEY
        (``agent:<id>:<project>``), not the bare agent id, so every directory
        is decoded and matched by the ``agent:<id>:`` prefix — this also
        naturally surfaces every project this agent has ever been scoped to
        (``docket scope ... set``), not only its current one.
        """
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
        """Translate stored messages past *offset* into the neutral turn shapes.

        ``session_id`` here is the full session key (what ``list_sessions``
        above returns as ``session_id`` for this driver). ``offset`` is a
        message index into ``core.session.SessionRecord.messages`` — a
        driver-defined cursor unit, per the Protocol's own contract. One
        assistant ``tool_calls`` entry becomes one ``tool_call`` turn per
        call; one ``tool``-role message becomes one ``tool_result`` turn;
        everything else is ``"other"`` (never projected into a trace event,
        matching ``core/trace.py``'s ``trace_ingest`` filter).

        ``core/session.py`` records only session-level ``created``/``updated``
        timestamps, not one per message, so every turn in a slice carries the
        same ``ts`` — coarser than per-record timestamps would be, but this
        method's only documented consumer (idle/timeout detection over
        ``last_ts``) only ever needs the *last* one.
        """
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
        """Aggregate this agent's *measured* usage across all its sessions.

        Real per-exchange token counts (``core.llm.TokenUsage``, accumulated
        by ``core.session.append_messages`` into each session's
        ``MeasuredUsage``) — docket's first non-estimated token numbers.
        ``cost_usd`` on the returned totals stays ``0.0`` for the same reason
        ``run_turn`` never populates one: converting a token count into a
        dollar figure is exactly the estimate-to-billing-claim conversion
        CLAUDE.md has a standing rule against.

        ``by_day`` is always empty: a session's stored usage is one running
        total for its whole lifetime (``core.session.MeasuredUsage`` has no
        per-turn timestamp to bucket by day). Adding a per-turn usage log to
        fabricate a daily breakdown would be new scope for ``core/session.py``;
        reporting an honest empty list beats a single-bucket approximation
        mislabeled as a real daily breakdown.
        """
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
    """Return the process-wide ``DocketDriver`` singleton.

    Stateless, so a fresh instance would behave identically; this just gives
    every real caller one named object. This is the only driver docket ships:
    ``core/dispatch.py``'s two pod-dispatch hop-execution call sites,
    ``core/trace.py``'s session-ingestion sweep, ``core/utils.py``'s cost
    aggregation, and ``cli/_agents.py``'s distillation turn (docket's first
    self-originated LLM call) all resolve the driver here.
    """
    global _DRIVER
    if _DRIVER is None:
        _DRIVER = DocketDriver()
    return _DRIVER
