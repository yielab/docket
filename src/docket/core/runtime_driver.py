"""RuntimeDriver port (Phase 18 L-1 / decision D-14).

A 2026-07-29 platform audit found the execution slice half-escaping the ACL:
session-JSONL cost parsing lived in ``core/utils.py``, ``trace_ingest`` knew the
daemon's session-log record shapes from inside ``core/trace.py``, and callers
shelled out to ``openclaw`` through a growing pile of ad-hoc argv shapes. This
module is the fix: a single typed ``Protocol`` that ``core/`` and ``cli/``
program against, so that *no* module outside ``edges/adapters/`` ever needs to
know what a session JSONL line, a daemon CLI invocation, or a cost record
actually looks like on disk.

ROADMAP §4.5 has a standing ban on an ``AbstractBackend`` — decision D-14
*revises* that ban, not repeals it: **one typed port, one shipped driver**
(``edges.adapters.openclaw.OpenClawDriver``), plus a ``FakeDriver`` test double
(``tests/python/fakes.py``). This is containment of coupling that already
existed, not speculative plugin-framework generality. A second real driver
still needs a §4.5 trigger (upstream stall/breakage) or a paying user — adding
driver discovery, entry points, or a config-selectable backend here would be
scope creep beyond this card.

The six required members mirror an agent's whole lifecycle:

- ``run_turn``    — one costed agent turn (the hot path; ``core/dispatch.py``'s
  pipeline and, per D-18, docket's own first self-originated LLM call go
  through this).
- ``provision`` / ``teardown`` — register/unregister an agent with the daemon.
- ``list_sessions`` / ``usage`` — durable-session enumeration and token/cost
  aggregation, reading the daemon's on-disk session JSONL — the format
  knowledge this card pulls out of ``core/``.
- ``capabilities`` — what this driver instance can actually promise (e.g.
  whether the daemon reports real USD cost at all), so callers never have to
  hardcode an assumption about the one shipped driver's quirks.

Nothing in this module touches a filesystem, a subprocess, or an OpenClaw file
format — it is pure typing, exactly like ``core/oc_models.py`` mirrors
openclaw.json's *schema* without being the thing that reads or writes it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

# ── run_turn ──────────────────────────────────────────────────────────────────

# Only "timeout"/"daemon_error" are retryable (a transient hiccup talking to the
# daemon/CLI, not a real answer) — see core/dispatch.py's _RETRYABLE_FAILURE_KINDS.
FailureKind = Literal["timeout", "daemon_error", "nonzero_exit", "invalid_output"]


@dataclass
class TurnResult:
    """Outcome of one agent turn, however the driver executed it.

    Field order is load-bearing: dozens of existing tests construct this
    positionally (``TurnResult(False, "", 0.0, {}, "boom")`` via its
    ``edges.adapters.openclaw.AgentRunResult`` alias) — do not reorder or
    insert a field before ``failure_kind`` without a matching sweep of those
    call sites.
    """

    ok: bool
    output: str
    cost_usd: float  # 0.0 when the driver's backing daemon doesn't report a USD cost
    raw: dict[str, Any]  # full parsed daemon response (empty when unparseable)
    error: str = ""
    failure_kind: FailureKind | None = None


# ── provision / teardown ─────────────────────────────────────────────────────


@dataclass
class ProvisionResult:
    """Outcome of registering one agent with the driver's backing runtime."""

    ok: bool
    message: str = ""


@dataclass
class TeardownResult:
    """Outcome of unregistering one agent from the driver's backing runtime."""

    ok: bool
    message: str = ""


# ── list_sessions ─────────────────────────────────────────────────────────────


@dataclass
class SessionSummary:
    """One durable session the driver knows about for an agent.

    ``session_id`` is the only field callers may treat as stable identity —
    everything else is best-effort metadata for display/ingestion, not a
    contract other modules should branch on.
    """

    session_id: str
    turns: int = 0
    last_active: str = ""  # ISO-ish timestamp string, '' if unknown


# ── session-turn ingestion (feeds core/trace.py's trace_ingest) ──────────────
#
# Not one of the six headline members, but part of closing the same leak:
# trace_ingest used to open daemon session JSONL directly and switch on its
# raw record `type` field ("tool_use"/"tool_result"/"message"). That decoding
# now lives entirely in the driver; core/trace.py only ever sees the neutral
# ``SessionTurn``/``SessionSlice`` shapes below and applies docket's own
# trace-event policy (redaction, timeout handling, its own event vocabulary)
# on top.


@dataclass
class SessionTurn:
    """One decoded daemon session record, translated to docket's vocabulary.

    ``kind`` is ``"tool_call"`` / ``"tool_result"`` / ``"other"`` — only the
    first two are ever projected into a trace event. ``daemon_type`` is the
    *original* raw type string (kept for the ingested trace payload's
    ``daemon_type`` field) — the one place a raw daemon vocabulary word is
    allowed to surface outside the driver, since by that point it is inert
    string data in docket's own trace payload, not something being parsed.
    """

    ts: str
    kind: Literal["tool_call", "tool_result", "other"]
    daemon_type: str
    record_id: Any = None


@dataclass
class SessionSlice:
    """New turns available for one on-disk session since a prior offset.

    ``had_new_content`` distinguishes "nothing new" from "new lines that
    happened to produce zero ingestible turns" (e.g. a batch of only
    ``message``-type records) — the caller must still advance its stored
    offset in the latter case. ``session_start_ts`` is only meaningful when
    the caller's prior offset was 0 (a session it has never ingested before).
    ``last_ts`` is the timestamp of the last successfully-decoded record in
    this slice regardless of ``kind`` (used for idle/timeout detection), and
    may differ from ``turns[-1].ts`` when the tail of the slice was
    untranslatable content.
    """

    session_id: str
    had_new_content: bool
    session_start_ts: str
    turns: list[SessionTurn]
    last_ts: str | None
    next_offset: int


# ── usage ─────────────────────────────────────────────────────────────────────


@dataclass
class UsageTotals:
    """Aggregated token/cost totals for one agent across all its sessions."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float = 0.0
    turns: int = 0


@dataclass
class UsageDay:
    """Token/cost totals for a single calendar day."""

    date: str
    turns: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class UsageReport:
    """``usage()``'s full return: running totals plus a per-day breakdown."""

    totals: UsageTotals
    by_day: list[UsageDay] = field(default_factory=list)


# ── capabilities ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DriverCapabilities:
    """What one driver instance can actually promise.

    Exists so a caller (including C-2's later self-originated LLM call, D-18)
    never has to hardcode an assumption about the one shipped driver's
    quirks — e.g. today's OpenClaw daemon (v2026.2.23) reports only token
    counts, never a USD cost field, so ``reports_cost_usd`` is False even
    though ``run_turn`` always returns a (zero) ``cost_usd``.
    """

    driver_name: str
    reports_cost_usd: bool
    supports_provisioning: bool
    supports_sessions: bool


# ── the port itself ────────────────────────────────────────────────────────────


@runtime_checkable
class RuntimeDriver(Protocol):
    """The typed boundary between docket's domain logic and an agent runtime.

    ``core/`` and ``cli/`` depend on this Protocol, never on a concrete
    driver's on-disk format knowledge. ``edges.adapters.openclaw.OpenClawDriver``
    is the one shipped implementation; ``tests/python/fakes.py``'s
    ``FakeDriver`` is the one test double — see the module docstring for why
    there is exactly one of each.
    """

    def run_turn(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
        *,
        on_spawn: Callable[[int], None] | None = None,
    ) -> TurnResult:
        """Run one real, costed agent turn. Never raises for ordinary failure modes.

        ``on_spawn`` (ROADMAP Phase 16 W-2, cancellation) — if the driver
        backs onto a real OS process, fires with its pid immediately after
        it starts, before this call blocks on its result. A driver with no
        real process to report (or a test double) may simply ignore it —
        every existing caller omits it, so this is purely additive.
        """
        ...

    def provision(self, agent_id: str, workspace: str, model: str) -> ProvisionResult:
        """Register *agent_id* with the backing runtime."""
        ...

    def teardown(self, agent_id: str) -> TeardownResult:
        """Unregister *agent_id* from the backing runtime."""
        ...

    def list_sessions(self, agent_id: str) -> list[SessionSummary]:
        """Enumerate the durable sessions the driver knows about for *agent_id*."""
        ...

    def read_new_turns(self, agent_id: str, session_id: str, offset: int) -> SessionSlice:
        """Decode session records past *offset* (a driver-defined cursor unit).

        Feeds ``core/trace.py``'s ingestion sweep — the one extra member
        beyond the headline six, needed to fully retire ``trace_ingest``'s
        former direct parsing of daemon session JSONL.
        """
        ...

    def usage(self, agent_id: str) -> UsageReport:
        """Aggregate token/cost usage for *agent_id* across all its sessions."""
        ...

    def capabilities(self) -> DriverCapabilities:
        """Describe what this driver instance can actually promise."""
        ...
