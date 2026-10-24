"""The gated tool registry, its chokepoint, and the built-in tools (`agent/tools/registry.py`).

Pins the argument-aware command classifier (`git push origin production`
reads as a deploy, not a benign `git`), that a source-tree walk finds
exactly one path to tool execution through `dispatch_tool`, and that
containment holds at the handler as well as at the chokepoint.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest
from tests.support import home as _support_home
from tests.support import llm as _support_llm
from tests.support import pods as _support_pods
from tests.support.cli import call as _call

from docket.agent.tools.registry import (
    ToolContext,
    dispatch_tool,
)
from docket.hops.application import builtin_tools
from docket.hops.application.builtin_tools import builtin_registry
from docket.kernel.home import current_home, use_home

_isolate_gates = _support_home.isolate_gates
workspace = _support_pods.workspace_2
ctx = _support_llm.ctx_2

SUBJECT = "docket.hops.application.builtin_tools"


class TestRegistry:
    @pytest.fixture(autouse=True)
    def _fetch_allowlisted(self) -> Iterator[None]:
        """`fetch` is offered only with an allowlist (agent-loop requirement 83); these tests
        describe the full built-in set."""
        with use_home(
            dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
        ):
            yield

    def test_builtins_present(self) -> None:
        assert builtin_registry().names() == [
            "bash",
            "consult",
            "edit",
            "fetch",
            "glob",
            "grep",
            "read",
            "skill",
            "write",
        ]

    def test_specs_carry_schemas_the_model_can_use(self) -> None:
        specs = {s.name: s for s in builtin_registry().specs()}
        assert specs["bash"].parameters["required"] == ["command"]
        assert specs["read"].description

    def test_without_narrows_the_set(self) -> None:
        readonly = builtin_registry().without("write", "edit", "bash")
        assert "write" not in readonly and "read" in readonly
        assert len(readonly) == 6

    def test_a_narrowed_registry_denies_the_removed_tool(self, ctx: ToolContext) -> None:
        readonly = builtin_registry().without("write")
        res = dispatch_tool(_call("write", '{"path":"x","content":"y"}'), ctx, readonly)
        assert res.denied and not (ctx.roots[0] / "x").exists()


class TestBashDescriptionPrefersTheFileTools:
    """The bash schema description steers file changes to write/edit."""

    def test_description_names_write_and_edit_over_heredocs(self) -> None:
        tool = builtin_tools.builtin_registry().get("bash")

        assert tool is not None
        assert "`write`/`edit`" in tool.description
        assert "heredocs" in tool.description
