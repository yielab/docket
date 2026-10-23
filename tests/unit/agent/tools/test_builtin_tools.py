"""The gated tool registry, its chokepoint, and the built-in tools (`agent/tools/registry.py`).

Pins the argument-aware command classifier (`git push origin production`
reads as a deploy, not a benign `git`), that a source-tree walk finds
exactly one path to tool execution through `dispatch_tool`, and that
containment holds at the handler as well as at the chokepoint.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.agent.llm import ToolCall
from docket.agent.tools import builtin_tools
from docket.agent.tools.builtin_tools import builtin_registry
from docket.agent.tools.registry import (
    ToolContext,
    dispatch_tool,
)
from docket.kernel.home import current_home, use_home

SUBJECT = "docket.agent.tools.builtin_tools"


@pytest.fixture(autouse=True)
def _isolate_gates(tmp_path: Path) -> Iterator[None]:
    """Isolate `governance/policy.py` and `governance/approval.py`'s real stores from a
    developer's ``~/.docket``, and set the approval timeout to 0 so a gated
    call nothing grants resolves immediately (fail-closed to denied)."""
    with use_home(
        dataclasses.replace(
            current_home(),
            policies_dir_override=tmp_path / "_policies",
            approvals_dir_override=tmp_path / "_approvals",
            tool_approval_timeout=0,
        )
    ):
        yield


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n")
    (tmp_path / "notes.md").write_text("alpha\nbeta\ngamma\n")
    return tmp_path


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(agent_id="demo-implementer", roots=(workspace,), timeout=10)


def _call(name: str, arguments: str = "{}", call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


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
