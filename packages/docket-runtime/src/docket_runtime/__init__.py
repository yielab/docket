"""The stable, embeddable Docket runtime facade.

Only the names exported here are public. The implementation remains private
so embedding applications keep one supported path to Docket's policy and tool
dispatch chokepoint.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock

from docket_runtime._execution import ExecutionLimits, ExecutionResult, GovernedExecution
from docket_runtime._internal.docket.core import approval as _approval
from docket_runtime._internal.docket.core.handoff import HandoffArtifact
from docket_runtime._internal.docket.core.llm import TokenUsage, ToolCall, ToolSpec
from docket_runtime._internal.docket.core.tools import Tool, ToolContext, ToolRegistry, ToolResult
from docket_runtime._internal.docket.core.tools import dispatch_tool as _dispatch_tool
from docket_runtime._internal.docket.edges.adapters.toolbox import ToolOutcome

__version__ = "0.3.0"
__all__ = [
    "ExecutionLimits",
    "ExecutionResult",
    "GovernedExecution",
    "HandoffArtifact",
    "Runtime",
    "TokenUsage",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolOutcome",
    "ToolResult",
    "ToolSpec",
    "__version__",
]

ApprovalStub = Callable[[str], bool]
_APPROVAL_STUB_LOCK = RLock()


@dataclass
class Runtime:
    """One embedding-owned registry that always dispatches through Docket's gate.

    ``approval_stub`` is intentionally a test/host seam, not a second driver:
    it answers a token created by the existing approval store, then the normal
    dispatch path continues to audit and execute (or deny) the call.
    """

    approval_stub: ApprovalStub | None = None
    _registry: ToolRegistry = field(default_factory=ToolRegistry, init=False, repr=False)

    def register(self, tool: Tool) -> None:
        self._registry.register(tool)

    def tool_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._registry.specs())

    def dispatch(self, call: ToolCall, context: ToolContext) -> ToolResult:
        with self._approval_stubbed():
            return _dispatch_tool(call, context, self._registry)

    def start_execution(self, context: ToolContext, limits: ExecutionLimits) -> GovernedExecution:
        return GovernedExecution(self.dispatch, context, limits)

    @contextmanager
    def _approval_stubbed(self) -> Iterator[None]:
        if self.approval_stub is None:
            yield
            return

        with _APPROVAL_STUB_LOCK:
            original = _approval.wait_for_approval

            def respond(token: str) -> object:
                if self.approval_stub is not None and self.approval_stub(token):
                    _approval.approval_grant(token, channel="runtime")
                else:
                    _approval.approval_deny(token, channel="runtime")
                return original(token)

            _approval.wait_for_approval = respond
            try:
                yield
            finally:
                _approval.wait_for_approval = original
