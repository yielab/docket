"""Phase functions extracted from `run_agent_turn` (`core/agent_loop.py`).

Each function here is pure and module-level, unlike the loop's stateful
nested closures, so it is exercised directly instead of only end to end.
The full turn is still `tests/integration/test_agent_loop.py`'s job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.core import agent_loop as _loop
from docket.core.llm import ChatResponse
from docket.core.tools import Tool as _Tool
from docket.core.tools import ToolContext, ToolRegistry
from docket.edges.adapters.toolbox import ToolOutcome

SUBJECT = "docket.core.agent_loop"


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ToolRegistry:
    """A registry with one read tool and one write tool, enough to prove narrowing."""
    reg = ToolRegistry()
    reg.register(
        _Tool(
            name="echo",
            description="Echo the given text back.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args, ctx: ToolOutcome(ok=True, content=str(args.get("text", ""))),
            kind="read",
        )
    )
    reg.register(
        _Tool(
            name="write",
            description="Write a file.",
            parameters={"type": "object", "properties": {}},
            handler=lambda args, ctx: ToolOutcome(ok=True, content=""),
            kind="write",
        )
    )
    return reg


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="demo-agent", role="implementer", project="demo", roots=(tmp_path,), timeout=10
    )


class _FakeBoundsBackend:
    """Reports fixed window/output attributes; `complete` is never called here."""

    def __init__(self, context_window_tokens: object, max_output_tokens: object) -> None:
        self.context_window_tokens = context_window_tokens
        self.max_output_tokens = max_output_tokens

    def complete(self, *args: object, **kwargs: object) -> ChatResponse:
        raise AssertionError("this fake only exercises attribute resolution")


# ── _resolve_context_bounds ──────────────────────────────────────────────────


class TestResolveContextBounds:
    """Config wins; a backend value only fills a gap the config leaves unset."""

    def test_config_values_win_over_the_backend(self) -> None:
        """An explicit LoopConfig bound is never overridden by the backend."""
        backend = _FakeBoundsBackend(context_window_tokens=999, max_output_tokens=999)
        cfg = _loop.LoopConfig(context_window_tokens=1_000, max_tokens=200)
        window, reserve, max_tokens = _loop._resolve_context_bounds(backend, cfg)
        assert (window, reserve, max_tokens) == (1_000, 200, 200)

    def test_backend_fills_an_unset_config_value(self) -> None:
        """An unset LoopConfig bound is filled from the backend's own report."""
        backend = _FakeBoundsBackend(context_window_tokens=1_000, max_output_tokens=200)
        cfg = _loop.LoopConfig()
        window, reserve, max_tokens = _loop._resolve_context_bounds(backend, cfg)
        assert (window, reserve, max_tokens) == (1_000, 200, 200)

    def test_non_positive_or_missing_backend_values_are_ignored(self) -> None:
        """A non-positive or absent backend value never fills the gap."""
        backend = _FakeBoundsBackend(context_window_tokens=0, max_output_tokens=-5)
        cfg = _loop.LoopConfig()
        window, reserve, max_tokens = _loop._resolve_context_bounds(backend, cfg)
        assert (window, reserve, max_tokens) == (None, 0, None)


# ── _resolve_trace_coordinates ───────────────────────────────────────────────


class TestResolveTraceCoordinates:
    """Explicit overrides win, then `ctx`, then the durable session key."""

    def test_explicit_overrides_win(self, ctx: ToolContext) -> None:
        """An explicit trace project/key is never replaced by a fallback."""
        project, trace_key = _loop._resolve_trace_coordinates(
            ctx, "agent:demo:default", "explicit-project", "explicit-key"
        )
        assert (project, trace_key) == ("explicit-project", "explicit-key")

    def test_falls_back_to_ctx_project_then_session_key(self, ctx: ToolContext) -> None:
        """With no override, project comes from ctx and trace_key from session_key."""
        project, trace_key = _loop._resolve_trace_coordinates(ctx, "agent:demo:default", None, None)
        assert (project, trace_key) == (ctx.project, "agent:demo:default")

    def test_falls_back_to_agent_id_when_ctx_project_is_unset(self, tmp_path: Path) -> None:
        """With no ctx.project either, the agent id is the last fallback."""
        bare_ctx = ToolContext(agent_id="bare-agent", roots=(tmp_path,), timeout=10)
        project, _ = _loop._resolve_trace_coordinates(bare_ctx, "agent:bare:default", None, None)
        assert project == "bare-agent"


# ── _resolve_role_registry_and_prompt ────────────────────────────────────────


class TestResolveRoleRegistryAndPrompt:
    """Narrows the registry by role, then composes today's system prompt."""

    def test_narrows_the_registry_to_the_role_and_returns_matching_specs(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """A role's denied_tools drops that tool from the returned specs."""
        reviewer_ctx = ToolContext(
            agent_id=ctx.agent_id, role="reviewer", project=ctx.project, roots=ctx.roots, timeout=10
        )
        narrowed, _prompt, specs = _loop._resolve_role_registry_and_prompt(registry, reviewer_ctx)
        names = {spec.name for spec in specs}
        assert "write" not in names
        assert "echo" in names
        assert specs == narrowed.specs()

    def test_a_role_with_no_denials_keeps_every_tool(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """implementer denies nothing, so both registered tools survive."""
        _narrowed, _prompt, specs = _loop._resolve_role_registry_and_prompt(registry, ctx)
        assert {spec.name for spec in specs} == {"echo", "write"}

    def test_prompt_is_empty_for_an_unprovisioned_agent(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """No workspace/identity files means a fail-open empty prompt, not an error."""
        _narrowed, prompt, _specs = _loop._resolve_role_registry_and_prompt(registry, ctx)
        assert prompt == ""
