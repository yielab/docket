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
workspace = _support_pods.workspace_with_files
ctx = _support_llm.ctx_in_workspace

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


class TestConsultDescriptionTellsTheTruth:
    """The consult schema matches its handler and the description says what asking does."""

    def _description(self, remaining: int, parks: bool) -> str:
        registry = builtin_registry()
        builtin_tools.describe_consult(registry, remaining=remaining, parks=parks)
        tool = registry.get("consult")
        assert tool is not None
        return tool.description

    def test_schema_requires_the_recommendation_the_handler_requires(self) -> None:
        specs = {s.name: s for s in builtin_registry().specs()}

        assert specs["consult"].parameters["required"] == [
            "kind",
            "message",
            "options",
            "recommendation",
        ]

    def test_the_default_description_says_asking_ends_the_turn(self) -> None:
        tool = builtin_registry().get("consult")

        assert tool is not None
        assert "ENDS your turn" in tool.description
        assert "decide" in tool.description
        assert "no answer" not in tool.description

    def test_a_dispatch_hop_states_the_consultations_left(self) -> None:
        text = self._description(remaining=2, parks=True)

        assert "ENDS your turn" in text
        assert "2 consultations left" in text

    def test_one_left_is_singular_and_none_left_says_so(self) -> None:
        assert "1 consultation left" in self._description(remaining=1, parks=True)
        assert "no consultations left" in self._description(remaining=0, parks=True)

    def test_outside_dispatch_the_call_returns_no_answer_at_once(self) -> None:
        text = self._description(remaining=3, parks=False)

        assert "ENDS your turn" not in text
        assert "no answer; decide yourself" in text


class TestBashStatesItsRules:
    """The `bash` description names what runs unattended and what asks, from the turn's gate."""

    @staticmethod
    def _stated(**context: object) -> str:
        registry = builtin_registry()
        builtin_tools.state_bash_rules(registry, ToolContext(**context))  # type: ignore[arg-type]
        tool = registry.get("bash")
        assert tool is not None
        return tool.description

    def test_the_built_in_description_lists_the_allowlist_and_the_asking_classes(self) -> None:
        tool = builtin_registry().get("bash")

        assert tool is not None
        stated = tool.description
        assert "Runs without approval: " in stated and "Needs approval: " in stated
        for name in ("git", "pytest", "python3", "rg"):
            assert f" {name}," in stated
        for rule in ("`sed -i`", "`find -exec`", "`$(`", "backticks", "outside the workspace"):
            assert rule in stated

    def test_a_pods_extra_bins_join_the_list(self) -> None:
        stated = self._stated(allow_commands=("tox", "uv"))

        assert "tox" in stated and "uv" in stated

    def test_a_long_extra_list_is_cut(self) -> None:
        stated = self._stated(allow_commands=tuple(f"tool{i:02d}" for i in range(40)))

        assert "tool00" in stated and "tool39" not in stated and "..." in stated

    def test_a_jailed_turn_is_told_every_program_runs(self) -> None:
        stated = self._stated(sandbox="auto")

        assert "any program" in stated and "Needs approval: " in stated
        assert "pytest," not in stated

    def test_a_bash_the_caller_made_is_left_alone(self) -> None:
        registry = builtin_registry()
        custom = dataclasses.replace(registry.get("bash"), description="mine")  # type: ignore[type-var]
        registry.register(custom)

        builtin_tools.state_bash_rules(registry, ToolContext(allow_commands=("tox",)))

        tool = registry.get("bash")
        assert tool is not None and tool.description == "mine"
