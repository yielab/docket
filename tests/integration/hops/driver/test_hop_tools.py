"""What a hop is offered and how many calls it may make: the model profile's surface, the step's
allow-list and cap, and the role's denials, through a real catalog row and the real driver."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.fakes import FakeJail
from tests.support.home import record_isolation_on
from tests.support.model_server import FakeModel, Request, call, register_lab_provider, say
from tests.support.pods import write_meta_overrides as _write_meta

from docket.agent.ports import (
    DOCKET_HOP_TOOLS,
    DOCKET_VERDICT_VALUES,
    DOCKET_VERIFY_PLAN,
    TurnResult,
)
from docket.hops.application.driver import DocketDriver
from docket.hops.application.verify_tool import VerifyPlan, plan_env_value
from docket.kernel.home import current_home, use_home
from docket.kernel.ports import SandboxAvailability
from docket.models.adapters.openai_wire import request_part_bytes

SUBJECT = "docket.hops.application.driver"

VALUES = json.dumps({"values": ["APPROVE", "REQUEST-CHANGES"], "caseSensitive": False})
# A bound on the tool schemas a small local model is sent for an implementer hop: measured 3,764
# bytes with bash, read, glob, edit, write, verify and handoff, against 6,240 under the full surface.
LOCAL_TOOLS_CEILING = 4000


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
        assert _names(request) == {"bash", "read", "glob", "edit", "write", "verify", "handoff"}
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


class TestRoundsGuard:
    """Rounds are the machine's guard: no step or role sets them, and the stop names the variable."""

    @staticmethod
    def _script(workspace: Path, rounds: int) -> list[Any]:
        (workspace / "f.txt").write_text("x\n")
        return [call("read", call_id=f"c{i}", path=f"f{i}.txt") for i in range(rounds)] + [
            say("done")
        ]

    def test_with_nothing_set_a_model_that_asks_for_a_tool_every_round_stops_at_the_guard(
        self, fake_model: Callable[..., FakeModel], workspace: Path
    ) -> None:
        guard = current_home().agent_loop_max_iterations
        server = fake_model(sequence=self._script(workspace, guard + 5))
        register_lab_provider(server)

        # Tokens stop a costly hop first, so the token budget is lifted to isolate the guard.
        with use_home(dataclasses.replace(current_home(), agent_loop_token_budget=10**9)):
            result = _run("implementer", workspace)

        assert guard == 200
        assert result.stop_reason == "max_iterations"
        assert result.failure_kind == "budget_exhausted"
        assert result.budget_stop is not None
        assert (result.budget_stop.source, result.budget_stop.raise_key) == (
            "default",
            "AGENT_LOOP_MAX_ITERATIONS",
        )
        assert (
            f"exceeded max_iterations={guard} "
            "(source: default; raise AGENT_LOOP_MAX_ITERATIONS)" in result.error
        )

    def test_with_the_guard_set_to_two_the_hop_makes_two_requests_and_the_landing(
        self, fake_model: Callable[..., FakeModel], workspace: Path
    ) -> None:
        server = fake_model(sequence=self._script(workspace, 8))
        register_lab_provider(server)

        with use_home(dataclasses.replace(current_home(), agent_loop_max_iterations=2)):
            result = _run("implementer", workspace)

        assert "exceeded max_iterations=2 (source: default; raise AGENT_LOOP_MAX_ITERATIONS)" in (
            result.error
        )
        assert len(server.requests) == 3  # two rounds and the landing


class TestToolCallsGuard:
    @staticmethod
    def _script(workspace: Path) -> list[Any]:
        (workspace / "f.txt").write_text("x\n")
        return [call("read", call_id=f"c{i}", path=f"f{i}.txt") for i in range(4)] + [say("done")]

    def test_the_guard_defaults_to_four_hundred(self) -> None:
        assert current_home().agent_loop_max_tool_calls == 400

    def test_a_guard_of_three_ends_the_hop_after_three_calls_and_names_the_variable(
        self, fake_model: Callable[..., FakeModel], workspace: Path
    ) -> None:
        server = fake_model(sequence=self._script(workspace))
        register_lab_provider(server)

        with use_home(dataclasses.replace(current_home(), agent_loop_max_tool_calls=3)):
            result = _run("implementer", workspace)

        assert not result.ok
        assert result.stop_reason == "max_tool_calls"
        assert "exceeded max_tool_calls=3 (source: default; raise AGENT_LOOP_MAX_TOOL_CALLS)" in (
            result.error
        )
        assert len(server.requests) == 4  # three rounds and the landing
