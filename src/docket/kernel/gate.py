"""The vocabulary of the tool-call gate: what the turn engine hands to governance and gets back.

``agent.tools.registry.dispatch_tool`` is the one place a tool call runs from; it asks the
``ToolGate`` port (``agent.ports``) whether a call may proceed and applies the answer. Both sides
need the same nouns, so they live here and neither imports the other: the engine's ``ToolContext``
and ``Tool`` satisfy the read-only protocols below, and ``governance.gate`` decides from them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

#: The built-in tool whose approval is the consultation itself (see ``governance.gate_rules``).
CONSULT_TOOL = "consult"

#: How many consultations one turn may spend when nothing sets a budget.
DEFAULT_MAX_CONSULTATIONS = 3

Decision = Literal["allow", "ask", "deny"]
ToolDenialKind = Literal[
    "invalid_call",
    "gate_denied",
    "approval_denied",
    "approval_timeout",
    "run_cancelled",
    "approval_unavailable",
    "approval_parked",
]


class HandlerUnavailable(Exception):
    """A tool handler found nobody who can answer it (``refuse`` posture); the turn ends blocked."""


class HandlerParked(HandlerUnavailable):
    """A tool handler parked its call for a later answer; ``token`` names the persisted question."""

    token: str = ""


class GatedTool(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def pregranted(self) -> bool: ...


class GatePregrant(Protocol):
    """A single-use pre-grant: a human already approved this exact call by its argument digest."""

    @property
    def token(self) -> str: ...
    @property
    def tool(self) -> str: ...
    @property
    def args_digest(self) -> str: ...


class GateContext(Protocol):
    """Who is making a call and under what posture; ``agent.tools.registry.ToolContext`` fits."""

    @property
    def agent_id(self) -> str: ...
    @property
    def role(self) -> str: ...
    @property
    def project(self) -> str: ...
    @property
    def roots(self) -> tuple[Path, ...]: ...
    @property
    def sandbox(self) -> str: ...
    @property
    def allow_commands(self) -> tuple[str, ...]: ...
    @property
    def approval_mode(self) -> str: ...
    @property
    def pregrants(self) -> tuple[GatePregrant, ...]: ...
    @property
    def approval_expires_at(self) -> str | None: ...
    @property
    def approval_timeout(self) -> int | None: ...
    @property
    def cancellation_check(self) -> Callable[[], bool] | None: ...
    @property
    def rationale(self) -> str: ...
    @property
    def task_id(self) -> str: ...


@dataclass(frozen=True)
class GateCall:
    """One call to decide: the tool, the model's call id and its parsed arguments."""

    tool: GatedTool
    call_id: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GateDecision:
    """The gate's answer for one call: it runs (``allow``) or it does not (``deny``).

    A call that needed a human is already resolved here (waited on, parked, refused or
    pre-granted). ``granted`` is the ``(token, tool, args_digest)`` of a pre-grant the caller
    must add to its context so one identical call later in the turn runs without asking again.
    """

    decision: Literal["allow", "deny"]
    reason: str = ""
    policy_id: str = ""
    denial_kind: ToolDenialKind | None = None
    error: str = ""
    approval_token: str = ""
    granted: tuple[str, str, str] | None = None


@dataclass(frozen=True)
class Screened:
    """How ``pre_input`` policy judged a text from outside docket: the policy ``action`` (``allow``,
    ``warn``, ``redact``, ``block`` or ``require_approval``), the policy that decided it and the
    text with secrets stripped (what to use for ``redact``)."""

    action: str
    policy_id: str = ""
    redacted: str = ""
