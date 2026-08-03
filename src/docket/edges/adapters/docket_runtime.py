"""``DocketDriver``: the daemon-free ``RuntimeDriver`` (Phase 19 P19-5 / D-19).

Implements ``core.runtime_driver.RuntimeDriver`` on top of ``core/agent_loop.py``
so ``core/dispatch.py``, the pipeline executor and every existing caller that
programs against the Protocol work unchanged.

P19-5 shipped this driver fully tested but unused in production: nothing yet
repointed the callers that resolve a driver, so every real turn still ran
through ``edges/adapters/openclaw.py``'s ``OpenClawDriver``. **P19-7a (the
runtime cutover) is what flips it** -- this module's own ``default_driver()``
below is now the single resolution point every production caller uses, so a
production pod-dispatch hop (and every other driver-backed turn: distillation,
cost aggregation, trace ingestion) executes here, on docket's own gated loop,
not the daemon. ``edges/adapters/openclaw.py`` and its ``OpenClawDriver`` are
untouched and still importable directly -- deleting them is P19-7b.

Every ``run_turn`` goes through ``core.agent_loop.run_agent_turn``, which in
turn dispatches every tool call through ``core.tools.dispatch_tool`` — the one
chokepoint every policy/approval/audit guardrail in this phase was built onto.
This module never calls a tool handler directly and never imports
``edges/adapters/toolbox.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote as _url_unquote

import docket.config as _cfg
from docket.core import agent_loop as _loop
from docket.core import session as _session
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

__all__ = ["DocketDriver"]


def _load_agent_meta(agent_id: str) -> tuple[AgentMeta | None, str]:
    """Read *agent_id*'s ``.docket-meta.json`` directly through ``edges/store.py``.

    Deliberately bypasses ``edges/adapters/openclaw.py``'s ``meta_get`` helper:
    that module owns the OpenClaw ACL boundary (openclaw.json / auth-profiles /
    provider config) and is slated for deletion in P19-7, while
    ``.docket-meta.json`` is docket's own metadata and has never needed the
    ACL to read. Returns ``(None, "")`` for a missing or malformed record
    rather than raising — every driver method here follows the Protocol's
    "never raises for an ordinary failure" contract.
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
    for this card (that module is not owned by P19-5) and this driver should
    not repeat a known incompleteness in new code it fully controls.
    """
    if worktree_dir:
        return (Path(worktree_dir),)
    if meta is not None and meta.codebase:
        return (Path(meta.codebase),)
    if meta is not None and meta.work_dir:
        return (Path(meta.work_dir),)
    return (_cfg.workspace_dir(agent_id),)


@dataclass
class DocketDriver:
    """The daemon-free ``RuntimeDriver``.

    ``backend_factory``/``registry_factory`` are the two injection seams a
    test needs (a stubbed ``ChatBackend``, a narrower tool set); both default
    to the real production functions, so a bare ``DocketDriver()`` is what
    every non-test caller constructs.
    """

    backend_factory: Callable[[str], ChatBackend | None] = _llm.client_for
    registry_factory: Callable[[], ToolRegistry] = builtin_registry

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
        )
        loop_config = _loop.LoopConfig(wall_clock_timeout_s=float(timeout))
        result = _loop.run_agent_turn(
            backend, self.registry_factory(), ctx, session_key, message, config=loop_config
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
        ``False`` precisely so a caller does not mistake this for the real
        registration step it can rely on from ``OpenClawDriver``.
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
        directly. Session-file lifecycle tied to fleet deletion belongs to
        the P19-6/P19-7 fleet-registry cards, not this one.
        """
        return TeardownResult(
            ok=True,
            message="no daemon to unregister from; session-file cleanup is not this driver's concern",
        )

    def list_sessions(self, agent_id: str) -> list[SessionSummary]:
        """Enumerate this agent's sessions from docket's own store, not daemon JSONL.

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
        same ``ts`` — coarser than daemon JSONL's per-record timestamps, but
        this method's only documented consumer (idle/timeout detection over
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
        per-turn timestamp to bucket by day), unlike the daemon JSONL
        ``OpenClawDriver.usage`` reads, which timestamps every record. Adding
        a per-turn usage log to fabricate a daily breakdown would be new
        scope for ``core/session.py`` (not owned by this card); reporting an
        honest empty list beats a single-bucket approximation mislabeled as
        a real daily breakdown.
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
            # docket-owned session storage (core/session.py), not a daemon
            # JSONL file that may or may not exist.
            supports_sessions=True,
        )


_DRIVER: DocketDriver | None = None


def default_driver() -> DocketDriver:
    """Return the process-wide ``DocketDriver`` singleton (P19-7a: the runtime cutover).

    Mirrors ``edges.adapters.openclaw.default_driver()``'s singleton pattern --
    stateless, so a fresh instance would behave identically; this just gives
    every real caller one named object. This is now the driver every
    production turn resolves through: ``core/dispatch.py``'s two pod-dispatch
    hop-execution call sites, ``core/trace.py``'s session-ingestion sweep,
    ``core/utils.py``'s cost aggregation, and ``cli/_agents.py``'s
    distillation turn (D-18's first self-originated LLM call) all resolve
    the driver here rather than through the ACL.

    ``edges.adapters.openclaw.default_driver()`` still exists and still
    resolves ``OpenClawDriver`` -- nothing outside its own module and test
    file calls it anymore after this card, which is exactly what leaves it
    for P19-7b to delete outright along with the rest of the ACL.
    """
    global _DRIVER
    if _DRIVER is None:
        _DRIVER = DocketDriver()
    return _DRIVER
