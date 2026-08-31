"""The stable, embeddable Docket runtime facade.

Only the names exported here are public. The implementation remains private
so embedding applications keep one supported path to Docket's policy and tool
dispatch chokepoint.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from docket_runtime._internal.docket.core import approval as _approval
from docket_runtime._internal.docket.core.llm import ToolCall
from docket_runtime._internal.docket.core.tools import Tool, ToolContext, ToolRegistry, ToolResult
from docket_runtime._internal.docket.core.tools import dispatch_tool as _dispatch_tool
from docket_runtime._internal.docket.edges.adapters.toolbox import ToolOutcome

__version__ = "0.2.0"
__all__ = [
    "Runtime",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolOutcome",
    "ToolResult",
    "__version__",
]

ApprovalStub = Callable[[str], bool]


@dataclass
class Runtime:
    """One embedding-owned registry that always dispatches through Docket's gate.

    ``approval_stub`` is intentionally a test/host seam, not a second driver:
    it answers a token created by the existing approval store, then the normal
    dispatch path continues to audit and execute (or deny) the call.
    """

    approval_stub: ApprovalStub | None = None
    registry: ToolRegistry = field(default_factory=ToolRegistry)

    def register(self, tool: Tool) -> None:
        self.registry.register(tool)

    def dispatch(self, call: ToolCall, context: ToolContext) -> ToolResult:
        with self._approval_stubbed():
            return _dispatch_tool(call, context, self.registry)

    @contextmanager
    def _approval_stubbed(self) -> Iterator[None]:
        if self.approval_stub is None:
            yield
            return

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
