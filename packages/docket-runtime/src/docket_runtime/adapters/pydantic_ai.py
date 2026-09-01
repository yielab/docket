"""PydanticAI toolset backed solely by Docket's governed execution facade.

``pydantic-ai`` is intentionally an optional integration dependency.  Importing
this module therefore requires the host to install it, while importing
``docket_runtime`` itself does not.
"""

from __future__ import annotations

import json
from typing import Any

from docket_runtime import (
    ExecutionLimits,
    ExecutionResult,
    GovernedExecution,
    Runtime,
    TokenUsage,
    ToolCall,
    ToolContext,
)
from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from pydantic_core import SchemaValidator


class DocketToolset(AbstractToolset[None]):
    """Expose one runtime's Docket tools to a PydanticAI agent sequentially."""

    def __init__(self, *, runtime: Runtime, context: ToolContext, limits: ExecutionLimits) -> None:
        self._runtime = runtime
        self._context = context
        self._execution: GovernedExecution = runtime.start_execution(context, limits)
        self._reported_usage = TokenUsage()
        self._terminal: ExecutionResult | None = None

    @property
    def id(self) -> str | None:
        """This in-process toolset needs no durable-execution identity."""
        return None

    async def get_tools(self, ctx: RunContext[None]) -> dict[str, ToolsetTool[None]]:
        """Return precisely the Docket runtime's stable, sequential tool specs."""
        validator = SchemaValidator(
            {
                "type": "dict",
                "keys_schema": {"type": "str"},
                "values_schema": {"type": "any"},
            }
        )
        return {
            spec.name: ToolsetTool(
                toolset=self,
                tool_def=ToolDefinition(
                    name=spec.name,
                    description=spec.description,
                    parameters_json_schema=spec.parameters,
                    sequential=True,
                ),
                max_retries=0,
                args_validator=validator,
            )
            # PydanticAI preserves this mapping order in the model request.  Keep
            # its narrow fixture list deterministic while still deriving every
            # advertised definition from the runtime facade.
            for spec in reversed(self._runtime.tool_specs())
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[None],
        tool: ToolsetTool[None],
    ) -> str:
        """Record provider usage, then dispatch the exact call through Docket."""
        if tool.toolset is not self or tool.tool_def.name != name:
            raise RuntimeError("PydanticAI attempted to call a tool outside this Docket toolset")
        if self._terminal is not None:
            return self._terminal.error
        if ctx.tool_call_id is None:
            raise RuntimeError("PydanticAI omitted the tool call id")

        call = ToolCall(
            id=ctx.tool_call_id,
            name=name,
            arguments=json.dumps(tool_args, separators=(",", ":")),
        )
        terminal = self._execution.record_response(self._usage_since_last_report(ctx), (call,))
        if terminal is not None:
            self._terminal = terminal
            return terminal.error
        return str(self._execution.dispatch(call).as_tool_output())

    def finish(self, summary: str) -> ExecutionResult:
        """Return the one terminal Docket result for the completed agent run."""
        if self._terminal is None:
            self._terminal = self._execution.finish(summary)
        return self._terminal

    def _usage_since_last_report(self, ctx: RunContext[None]) -> TokenUsage:
        usage = ctx.usage
        current = TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cache_read_tokens,
        )
        delta = TokenUsage(
            input_tokens=current.input_tokens - self._reported_usage.input_tokens,
            output_tokens=current.output_tokens - self._reported_usage.output_tokens,
            cached_tokens=current.cached_tokens - self._reported_usage.cached_tokens,
        )
        self._reported_usage = current
        return delta
