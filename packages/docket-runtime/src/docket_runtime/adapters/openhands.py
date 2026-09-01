"""OpenHands SDK adapter for Docket-governed tool execution."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docket_runtime import (
    ExecutionLimits,
    ExecutionResult,
    GovernedExecution,
    Runtime,
    TokenUsage,
    ToolCall,
    ToolContext,
    ToolSpec,
)
from openhands.sdk import LLM, Agent, AgentContext, Conversation
from openhands.sdk.llm import LLMResponse, Message, TextContent
from openhands.sdk.tool import (
    Action,
    Observation,
    ToolDefinition,
    ToolExecutor,
    register_tool,
)
from openhands.sdk.tool import (
    Tool as OpenHandsTool,
)
from pydantic import PrivateAttr


@dataclass
class _AdapterState:
    execution: GovernedExecution
    tool_names: frozenset[str]
    pending: list[ToolCall] = field(default_factory=list)
    terminal: ExecutionResult | None = None
    final_summary: str = ""

    def record(self, response: LLMResponse, usage: Any) -> LLMResponse:
        calls = tuple(
            ToolCall(id=call.id, name=call.name, arguments=call.arguments)
            for call in (response.message.tool_calls or ())
            if call.name in self.tool_names
        )
        terminal = self.execution.record_response(
            TokenUsage(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cached_tokens=usage.cache_read_tokens,
            ),
            calls,
        )
        if terminal is not None:
            self.terminal = terminal
            stopped = response.message.model_copy(
                update={
                    "content": [TextContent(text=terminal.error)],
                    "tool_calls": None,
                }
            )
            return response.model_copy(update={"message": stopped})

        self.pending.extend(calls)
        if not calls:
            self.final_summary = _message_text(response.message)
        return response

    def dispatch(self, tool_name: str) -> _DocketObservation:
        if not self.pending:
            return _DocketObservation.from_text(
                "Docket execution is already terminal", is_error=True
            )
        call = self.pending.pop(0)
        if call.name != tool_name:
            raise RuntimeError(
                f"OpenHands dispatched {tool_name!r} before admitted call {call.name!r}"
            )
        result = self.execution.dispatch(call)
        return _DocketObservation.from_text(result.as_tool_output(), is_error=not result.ok)


class _GovernedLLM(LLM):
    _docket_state: _AdapterState = PrivateAttr()

    def completion(
        self,
        messages: list[Message],
        tools: Sequence[ToolDefinition] | None = None,
        add_security_risk_prediction: bool = False,
        on_token: Any | None = None,
        call_context: Any | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        response = super().completion(
            messages,
            tools,
            add_security_risk_prediction=add_security_risk_prediction,
            on_token=on_token,
            call_context=call_context,
            **kwargs,
        )
        return self._docket_state.record(response, self.metrics.token_usages[-1])


class _DocketObservation(Observation):
    """Concrete OpenHands observation carrying the Docket tool output."""


class _DocketExecutor(ToolExecutor[Action, _DocketObservation]):
    def __init__(self, state: _AdapterState, tool_name: str) -> None:
        self._state = state
        self._tool_name = tool_name

    def __call__(self, action: Action, conversation: Any | None = None) -> _DocketObservation:
        del action, conversation
        return self._state.dispatch(self._tool_name)


class OpenHandsAdapter:
    """Run a standard OpenHands Agent with only Docket-owned tools."""

    def __init__(
        self,
        *,
        runtime: Runtime,
        context: ToolContext,
        limits: ExecutionLimits,
    ) -> None:
        self._runtime = runtime
        self._context = context
        self._limits = limits
        self.agent: Agent | None = None

    def run(
        self,
        *,
        llm: LLM,
        prompt: str,
        workspace: str | Path,
        persistence_dir: str | Path,
    ) -> ExecutionResult:
        specs = self._runtime.tool_specs()
        state = _AdapterState(
            execution=self._runtime.start_execution(self._context, self._limits),
            tool_names=frozenset(spec.name for spec in specs),
        )
        governed_llm = llm.model_copy(deep=False)
        governed_llm.__class__ = _GovernedLLM
        governed_llm._docket_state = state

        tools = [_register_tool(spec, state, index) for index, spec in enumerate(specs)]
        self.agent = Agent(
            llm=governed_llm,
            tools=tools,
            include_default_tools=[],
            mcp_config={},
            security_policy_filename="",
            agent_context=AgentContext(
                skills=[],
                load_user_skills=False,
                load_public_skills=False,
                load_project_skills=False,
                load_memory=False,
                marketplace_path=None,
            ),
            tool_concurrency_limit=1,
        )
        conversation = Conversation(
            agent=self.agent,
            workspace=workspace,
            plugins=[],
            persistence_dir=persistence_dir,
            max_iteration_per_run=self._limits.max_tool_calls + 1,
            stuck_detection=False,
            visualizer=None,
        )
        try:
            conversation.send_message(prompt)
            conversation.run()
        finally:
            conversation.close()

        if state.terminal is not None:
            return state.terminal
        return state.execution.finish(state.final_summary)


def _register_tool(spec: ToolSpec, state: _AdapterState, index: int) -> OpenHandsTool:
    action_type = Action.from_mcp_schema(f"DocketAction{index}", spec.parameters)

    def create(cls: type[ToolDefinition], *args: Any, **kwargs: Any) -> list[ToolDefinition]:
        del cls, args, kwargs
        raise RuntimeError("fixed Docket tool definitions are registered as instances")

    definition_type = type(
        f"DocketTool{index}",
        (ToolDefinition,),
        {
            "__module__": __name__,
            "name": spec.name,
            "create": classmethod(create),
        },
    )
    definition = definition_type(
        description=spec.description,
        action_type=action_type,
        observation_type=None,
        executor=_DocketExecutor(state, spec.name),
    )
    register_tool(spec.name, definition)
    return OpenHandsTool(name=spec.name)


def _message_text(message: Message) -> str:
    return "\n".join(
        content.text for content in message.content if isinstance(content, TextContent)
    )
