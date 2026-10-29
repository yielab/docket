"""What a hop is offered and how many calls it may make: the model profile's surface, the step's
allow-list and cap, and the role's denials, through a real catalog row and the real driver."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.fakes import FakeJail
from tests.support.home import record_isolation_on
from tests.support.model_server import FakeModel, Request, call, register_lab_provider, say
from tests.support.pods import write_meta_overrides as _write_meta
from tests.support.roles import write_role_overlay

from docket.agent.ports import (
    DOCKET_HOP_MAX_TOOL_CALLS,
    DOCKET_HOP_TOOLS,
    DOCKET_VERDICT_VALUES,
    DOCKET_VERIFY_PLAN,
    TurnResult,
)
from docket.hops.application.driver import DocketDriver
from docket.hops.application.verify_tool import VerifyPlan, plan_env_value
from docket.kernel.home import current_home
from docket.kernel.ports import SandboxAvailability
from docket.models.adapters.openai_wire import request_part_bytes

SUBJECT = "docket.hops.application.driver"

VALUES = json.dumps({"values": ["APPROVE", "REQUEST-CHANGES"], "caseSensitive": False})
# A bound on the tool schemas a small local model is sent for an implementer hop: measured 3,376
# bytes with bash, read, edit, write, verify and handoff, against 6,240 under the full surface.
LOCAL_TOOLS_CEILING = 3500


def _run(role: str, workspace: Path, env: dict[str, str] | None = None) -> TurnResult:
    _write_meta("hop-agent", role=role, model="lab/m", codebase=str(workspace))
    return DocketDriver().run_turn("hop-agent", "agent:hop-agent:default", "go", 60, env)


def _names(request: Request) -> set[str]:
    return {t["function"]["name"] for t in request.body.get("tools", [])}


def _implementer_env(workspace: Path) -> dict[str, str]:
    """What an implementer step with a verify command and a verdict gate carries."""
    plan = VerifyPlan("true", str(workspace), 30)
    return {DOCKET_VERIFY_PLAN: plan_env_value(plan), DOCKET_VERDICT_VALUES: VALUES}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "w"
    path.mkdir()
    return path


class TestSurface:
    def test_a_local_row_offers_the_implementer_the_minimal_surface(
        self,
        fake_model: Callable[..., FakeModel],
        fake_jail: FakeJail,
        workspace: Path,
        tmp_path: Path,
    ) -> None:
        # The posture `docket init` records where a backend exists: bash's description is then the
        # jailed one, not the classifier's whole allow-list.
        fake_jail.availability = SandboxAvailability(backend="landlock", docker=False)
        record_isolation_on(tmp_path / "docket")
        server = fake_model(sequence=[say("done")])
        register_lab_provider(server, local=True)

        _run("implementer", workspace, _implementer_env(workspace))

        request = server.requests[0]
        assert _names(request) == {"bash", "read", "edit", "write", "verify", "handoff"}
        assert request_part_bytes(request.body)["tools"] < LOCAL_TOOLS_CEILING

    def test_a_hosted_row_offers_the_implementer_every_tool_it_may_hold(
        self, fake_model: Callable[..., FakeModel], workspace: Path
    ) -> None:
        server = fake_model(sequence=[say("done")])
        register_lab_provider(server)

        _run("implementer", workspace, _implementer_env(workspace))

        names = _names(server.requests[0])
        assert {"bash", "read", "write", "edit", "grep", "glob", "consult", "verify"} <= names
        assert {"process_output", "process_stop", "handoff"} <= names
        assert request_part_bytes(server.requests[0].body)["tools"] > LOCAL_TOOLS_CEILING

    def test_a_row_that_declares_the_full_surface_overrides_a_local_default(
        self, fake_model: Callable[..., FakeModel], workspace: Path
    ) -> None:
        server = fake_model(sequence=[say("done")])
        register_lab_provider(server, local=True, toolSurface="full")

        _run("implementer", workspace)

        assert {"write", "edit", "grep"} <= _names(server.requests[0])


class TestRoleDenials:
    @pytest.mark.parametrize("role", ["reviewer", "lead"])
    def test_a_role_denied_bash_is_not_offered_the_background_process_tools(
        self, fake_model: Callable[..., FakeModel], workspace: Path, role: str
    ) -> None:
        server = fake_model(sequence=[say("done")])
        register_lab_provider(server)

        _run(role, workspace)

        names = _names(server.requests[0])
        assert "read" in names
        assert not {"bash", "write", "edit", "process_output", "process_stop"} & names


class TestStepAllowList:
    def test_a_step_allow_list_narrows_a_hosted_hop(
        self, fake_model: Callable[..., FakeModel], workspace: Path
    ) -> None:
        server = fake_model(sequence=[say("done")])
        register_lab_provider(server)

        _run("implementer", workspace, {DOCKET_HOP_TOOLS: json.dumps(["read", "grep"])})

        assert _names(server.requests[0]) == {"read", "grep"}


class TestMaxToolCalls:
    @staticmethod
    def _script(workspace: Path) -> list[Any]:
        (workspace / "f.txt").write_text("x\n")
        return [call("read", call_id=f"c{i}", path=f"f{i}.txt") for i in range(4)] + [say("done")]

    def test_a_step_cap_ends_the_hop_after_that_many_calls(
        self, fake_model: Callable[..., FakeModel], workspace: Path
    ) -> None:
        server = fake_model(sequence=self._script(workspace))
        register_lab_provider(server)

        result = _run("implementer", workspace, {DOCKET_HOP_MAX_TOOL_CALLS: "3"})

        assert not result.ok
        assert result.stop_reason == "max_tool_calls"
        assert "exceeded max_tool_calls=3" in result.error
        assert len(server.requests) == 3

    def test_a_role_cap_applies_when_the_step_sets_none(
        self, fake_model: Callable[..., FakeModel], workspace: Path
    ) -> None:
        server = fake_model(sequence=self._script(workspace))
        register_lab_provider(server)
        write_role_overlay("hop-pod", "implementer", [], extra="maxToolCalls: 2\n")
        _write_meta("hop-pod-agent", role="implementer", model="lab/m", codebase=str(workspace))

        result = DocketDriver().run_turn(
            "hop-pod-agent", "agent:hop-pod-agent:hop-pod", "go", 60, None, trace_project="hop-pod"
        )

        assert result.stop_reason == "max_tool_calls"
        assert "exceeded max_tool_calls=2" in result.error

    def test_the_step_cap_wins_over_the_roles(
        self, fake_model: Callable[..., FakeModel], workspace: Path
    ) -> None:
        server = fake_model(sequence=self._script(workspace))
        register_lab_provider(server)
        write_role_overlay("hop-pod", "implementer", [], extra="maxToolCalls: 2\n")
        _write_meta("hop-pod-agent", role="implementer", model="lab/m", codebase=str(workspace))

        result = DocketDriver().run_turn(
            "hop-pod-agent",
            "agent:hop-pod-agent:hop-pod",
            "go",
            60,
            {DOCKET_HOP_MAX_TOOL_CALLS: "3"},
            trace_project="hop-pod",
        )

        assert "exceeded max_tool_calls=3" in result.error

    def test_a_cap_that_is_not_a_positive_integer_is_ignored(
        self, fake_model: Callable[..., FakeModel], workspace: Path
    ) -> None:
        server = fake_model(sequence=self._script(workspace))
        register_lab_provider(server)

        result = _run("implementer", workspace, {DOCKET_HOP_MAX_TOOL_CALLS: "0"})

        assert result.stop_reason != "max_tool_calls"
        assert current_home().agent_loop_max_tool_calls > 4
