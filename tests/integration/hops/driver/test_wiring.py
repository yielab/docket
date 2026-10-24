"""What reaches a driver turn: isolation, approval mode, allowed commands, pod scope and waits."""

from __future__ import annotations

import dataclasses
import json
import time as _time
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.support.driver_harness import (
    _final_response,
    _never_called,
    _probe_call_response,
    _ScriptedBackend,
)
from tests.support.fakes import FakeJail
from tests.support.pods import write_meta_overrides as _write_meta

from docket.agent.ports import (
    DOCKET_APPROVAL_MODE,
    ChatResponse,
    TokenUsage,
    ToolCall,
    assistant,
)
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry
from docket.governance.audit import read_audit
from docket.hops.application import driver as _docket_runtime
from docket.hops.application.driver import DocketDriver
from docket.interfaces.cli.commands import setup_sandbox as _setup_sandbox
from docket.kernel.home import current_home, use_home
from docket.kernel.ports import SandboxAvailability
from docket.sandbox.launch import Launcher
from docket.tasks.domain.task import DispatchError
from docket.teams import fleet as _fleet

SUBJECT = "docket.hops.application.driver"


def _no_recorded_isolation_choice() -> None:
    current_home().fleet_file.unlink(missing_ok=True)


def _probe_registry() -> ToolRegistry:
    """A one-tool registry reporting back the exact `ctx.sandbox` value `run_turn` built, so a
    test observes it without hand-constructing a `ToolContext` -- the real construction path
    is the thing under test."""
    registry = ToolRegistry()

    def _probe(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(True, content=f"sandbox={ctx.sandbox}")

    registry.register(
        Tool(
            name="probe",
            description="reports ctx.sandbox",
            parameters={"type": "object", "properties": {}},
            handler=_probe,
            kind="read",
        )
    )
    return registry


def _approval_mode_probe_registry() -> ToolRegistry:
    """A one-tool registry reporting back the exact `ctx.approval_mode`
    `run_turn` built -- the DOCKET_APPROVAL_MODE wiring's own oracle, mirroring
    `_probe_registry`'s `ctx.sandbox` pattern above."""
    registry = ToolRegistry()

    def _probe(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(True, content=f"approval_mode={ctx.approval_mode}")

    registry.register(
        Tool(
            name="probe",
            description="reports ctx.approval_mode",
            parameters={"type": "object", "properties": {}},
            handler=_probe,
            kind="read",
        )
    )
    return registry


def _allow_commands_probe_registry() -> ToolRegistry:
    """One-tool registry reporting `ctx.allow_commands` -- the pod
    `allowCommands` setting's own oracle, mirroring the approval-mode probe."""
    registry = ToolRegistry()

    def _probe(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(True, content=f"allow_commands={','.join(ctx.allow_commands)}")

    registry.register(
        Tool(
            name="probe",
            description="reports ctx.allow_commands",
            parameters={"type": "object", "properties": {}},
            handler=_probe,
            kind="read",
        )
    )
    return registry


def _pod_overlay_denying(project: str, role: str, denied: list[str]) -> None:
    path = current_home().pod_config_dir(project) / "roles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "roles": {
                    role: {
                        "name": role,
                        "version": 1,
                        "scope": "pod",
                        "modelClass": "cheap",
                        "soulTemplate": "x",
                        "agentsTemplate": "y",
                        "gateContract": {"kind": "none"},
                        "toolProfile": "read-only",
                        "deniedTools": denied,
                    }
                }
            }
        )
    )


def _bash_then_done(command: str) -> _ScriptedBackend:
    call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": command}))
    return _ScriptedBackend(
        [
            ChatResponse(
                ok=True,
                message=assistant("", tool_calls=[call]),
                finish_reason="tool_calls",
                usage=TokenUsage(10, 5),
            ),
            _final_response("done"),
        ]
    )


def _approval_wait_probe_registry() -> ToolRegistry:
    """A one-tool registry reporting the approval wait `run_turn` built."""
    registry = ToolRegistry()

    def _probe(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(True, content=f"timeout={ctx.approval_timeout}")

    registry.register(
        Tool(
            name="probe",
            description="reports ctx.approval_timeout",
            parameters={"type": "object", "properties": {}},
            handler=_probe,
            kind="read",
        )
    )
    return registry


class TestIsolationWiring:
    """`docket setup sandbox on` writes `security.isolationMode` to fleet.json;
    `DocketDriver.run_turn` resolves it via `_resolve_sandbox`, so isolation ON is no longer
    silently indistinguishable from OFF on the live turn path."""

    def test_explicit_isolation_off_leaves_ctx_sandbox_off(self) -> None:
        # The recorded opt-out (`docket setup sandbox off`) is the only way a turn runs with
        # `sandbox="off"`; the `ToolContext` a real turn builds then carries it unchanged.
        _write_meta("solo-agent")
        _fleet.disable_sandbox_isolation()
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_probe_registry
        )

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "sandbox=off"

    def test_no_recorded_choice_runs_on_the_host_without_probing_a_backend(
        self, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        # No fleet.json at all: isolation is opt-in, so the turn runs unjailed and a host
        # with no sandbox backend is never asked for one.
        _no_recorded_isolation_choice()
        _write_meta("solo-agent")

        def no_probe() -> SandboxAvailability:
            raise AssertionError("probed a sandbox backend with isolation off")

        fake_jail.sandbox_availability = no_probe
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_probe_registry
        )

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "sandbox=off"
        assert not [e for e in read_audit() if e["action"] == "isolation.refused"]

    def test_isolation_on_with_no_backend_refuses_naming_the_fixes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_meta("solo-agent")
        _fleet.set_sandbox_isolation(mode="non-main")
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        driver = DocketDriver(backend_factory=_never_called)

        with pytest.raises(DispatchError) as excinfo:
            driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert "landlock" in str(excinfo.value)
        assert "setup sandbox backend docker" in str(excinfo.value)
        assert "docket setup sandbox off" in str(excinfo.value)
        assert [e for e in read_audit() if e["action"] == "isolation.refused"]

    def test_isolation_on_with_backend_available_sets_sandbox_auto(
        self, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        _write_meta("solo-agent")
        fake_jail.sandbox_availability = lambda: SandboxAvailability(backend="docker", docker=True)
        _fleet.set_sandbox_isolation(mode="non-main")
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_probe_registry
        )

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "sandbox=auto"

    def test_isolation_on_no_backend_refuses_the_turn_rather_than_running_unsandboxed(
        self, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        # The failure mode this card exists to end: isolation is ON but
        # no sandbox backend is usable. The turn must refuse outright
        # -- not silently downgrade to an unsandboxed run -- and the LLM
        # backend must never even be reached (`_never_called` fails the test
        # if it is).
        _write_meta("solo-agent")
        fake_jail.sandbox_availability = lambda: SandboxAvailability(backend="none", docker=False)
        _fleet.set_sandbox_isolation(mode="non-main")
        driver = DocketDriver(backend_factory=_never_called)

        with pytest.raises(DispatchError) as excinfo:
            driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert "docker" in str(excinfo.value).lower()
        assert "landlock" in str(excinfo.value).lower()

        refusals = [e for e in read_audit() if e["action"] == "isolation.refused"]
        assert len(refusals) == 1
        assert "agent=solo-agent" in refusals[0]["detail"]
        assert "docker=False" in refusals[0]["detail"]
        assert "landlock=False" in refusals[0]["detail"]

    def test_docket_sandbox_backend_override_still_wins(
        self, monkeypatch: pytest.MonkeyPatch, bind_launcher: Callable[..., Launcher]
    ) -> None:
        # Both real backends report usable, but the operator's own override
        # forces "none" -- this wire adds no parallel backend-selection
        # mechanism, it only gates in front of the existing one
        # (`system.sandbox_availability`), so the override must still be the
        # last word, exactly as it already is for `toolbox.run_bash`.
        _write_meta("solo-agent")
        bind_launcher(docker=True)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        _fleet.set_sandbox_isolation(mode="non-main")
        driver = DocketDriver(backend_factory=_never_called)

        with pytest.raises(DispatchError):
            driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

    def test_the_flag_docket_gates_isolate_on_writes_is_the_one_the_turn_reads(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_jail: FakeJail,
    ) -> None:
        # End-to-end through fleet: drive the real `docket setup sandbox on`
        # CLI path (not `set_sandbox_isolation` directly, and not a
        # hand-built `ToolContext`), then confirm a real turn observes
        # exactly the flag it wrote.
        _write_meta("solo-agent")
        fake_jail.sandbox_availability = lambda: SandboxAvailability(
            backend="landlock", docker=False, landlock=True
        )
        rc = _setup_sandbox.isolate("on")
        capsys.readouterr()
        assert rc == 0

        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_probe_registry
        )
        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "sandbox=auto"


# DOCKET_APPROVAL_MODE travels the same internal env-coordinate route as
# PIPELINE_WORKTREE_ENV: popped from env before the tool env is built, then
# mapped onto ToolContext.approval_mode. Without this wire, a production
# dispatch could never reach approval_unavailable -- only a hand-built
# ToolContext in a unit test could set the field directly.
class TestApprovalModeWiring:
    """The DOCKET_APPROVAL_MODE env coordinate reaching a real driver call."""

    def test_env_unset_keeps_the_wait_default(self) -> None:
        _write_meta("mode-default-agent")
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=_approval_mode_probe_registry,
        )

        result = driver.run_turn("mode-default-agent", "agent:mode-default-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "approval_mode=wait"

    def test_env_refuse_reaches_the_tool_context(self) -> None:
        _write_meta("mode-refuse-agent")
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=_approval_mode_probe_registry,
        )

        result = driver.run_turn(
            "mode-refuse-agent",
            "agent:mode-refuse-agent:default",
            "go",
            30,
            {DOCKET_APPROVAL_MODE: "refuse"},
        )

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "approval_mode=refuse"

    def test_an_unrecognized_value_falls_back_to_wait(self) -> None:
        _write_meta("mode-garbage-agent")
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=_approval_mode_probe_registry,
        )

        result = driver.run_turn(
            "mode-garbage-agent",
            "agent:mode-garbage-agent:default",
            "go",
            30,
            {DOCKET_APPROVAL_MODE: "garbage"},
        )

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "approval_mode=wait"

    def test_the_env_coordinate_never_leaks_into_the_tool_visible_environment(self) -> None:
        # "env" (not "echo") is on governance.security.SAFE_BINS' curated allowlist,
        # mirroring test_env_flows_into_the_tool_context above.
        _write_meta("mode-leak-agent")
        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "env"}))
        backend = _ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
                _final_response("ran it"),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn(
            "mode-leak-agent",
            "agent:mode-leak-agent:default",
            "run it",
            30,
            {DOCKET_APPROVAL_MODE: "refuse"},
        )

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert "DOCKET_APPROVAL_MODE" not in tool_msg.content

    def test_refuse_mode_denies_a_real_gated_call_immediately_through_the_driver(self) -> None:
        """The whole-path proof: a real policy-gated `bash` call, through the
        real driver, denies in well under the 120s `TOOL_APPROVAL_TIMEOUT`
        instead of waiting -- the defect this wire exists to close."""
        with use_home(dataclasses.replace(current_home(), tool_approval_timeout=5)):
            from docket.governance.policy import install_policies

            install_policies()
            _write_meta("refuse-real-agent")
            call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
            backend = _ScriptedBackend(
                [
                    ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(10, 5),
                    ),
                ]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)

            started = _time.monotonic()
            result = driver.run_turn(
                "refuse-real-agent",
                "agent:refuse-real-agent:default",
                "delete the build dir",
                30,
                {DOCKET_APPROVAL_MODE: "refuse"},
            )
            elapsed = _time.monotonic() - started

            assert elapsed < 1.0, (
                f"took {elapsed:.2f}s -- did this actually skip the approval wait?"
            )
            assert result.ok is False
            assert result.failure_kind == "invalid_output"
            assert "approval_unavailable" in result.error
            assert "block-destructive" in result.error
            assert (
                not current_home().approvals_dir.exists()
                or list(current_home().approvals_dir.glob("*.json")) == []
            )


class TestAllowCommandsWiring:
    """A pod Lead's `allowCommands` setting reaching a member agent's real
    `ToolContext` (`teams.pod_settings.PodSettings` -> `hops/application/driver.py`)."""

    def test_a_non_pod_agent_gets_no_extra_bins(self) -> None:
        _write_meta("solo-agent")
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=_allow_commands_probe_registry,
        )

        result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "allow_commands="

    def test_a_pod_member_sees_its_leads_configured_setting(self) -> None:
        _write_meta("shop-implementer")
        _write_meta("shop-lead", role="lead", allowCommands="tox,uv")
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=_allow_commands_probe_registry,
        )

        result = driver.run_turn("shop-implementer", "agent:shop-implementer:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "allow_commands=tox,uv"

    def test_a_member_of_a_different_pod_sees_no_extra_bins(self) -> None:
        _write_meta("shop-implementer")
        _write_meta("shop-lead", role="lead", allowCommands="tox,uv")
        _write_meta("other-implementer")
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=_allow_commands_probe_registry,
        )

        result = driver.run_turn("other-implementer", "agent:other-implementer:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "allow_commands="

    def test_a_malformed_pod_setting_fails_closed_to_no_extra_bins(
        self, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
    ) -> None:
        # A malformed pod settings file also fails the network closed to `none`, which only a
        # jail can enforce: turn isolation on with a (stubbed) backend.
        _fleet.set_sandbox_isolation(mode="non-main")
        fake_jail.sandbox_availability = lambda: SandboxAvailability(
            backend="landlock", docker=False, landlock=True
        )
        _write_meta("shop-implementer")
        _write_meta("shop-lead", role="lead", turnTimeoutS="not-a-number", allowCommands="tox")
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=_allow_commands_probe_registry,
        )

        result = driver.run_turn("shop-implementer", "agent:shop-implementer:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert tool_msg.content == "allow_commands="

    def test_the_extra_bin_actually_reaches_the_real_gate_end_to_end(self) -> None:
        """The whole-path proof: `uname`, off SAFE_BINS, executes unattended
        through the real `bash` tool once its pod's Lead configures it."""
        _write_meta("shop-implementer")
        _write_meta("shop-lead", role="lead", allowCommands="uname")
        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "uname"}))
        backend = _ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
                _final_response("ran it"),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn("shop-implementer", "agent:shop-implementer:default", "uname", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert "not on the curated allowlist" not in tool_msg.content


class TestPodScopeWiring:
    """Seam test: a standalone member turn resolves its pod into `ToolContext.project`
    (`run_turn`), and that value reaches both the pod role overlay (`registry_for_role`) and
    the pod policy directory (`policy_eval_detail`) on the real gate."""

    def test_a_pod_role_overlay_narrows_a_standalone_member_turn(self) -> None:
        _write_meta("shop-implementer", pod="shop")
        _write_meta("shop-lead", role="lead", pod="shop")
        _pod_overlay_denying("shop", "implementer", ["bash"])
        backend = _bash_then_done("uname")
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn("shop-implementer", "agent:shop-implementer:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert "unknown tool 'bash'" in tool_msg.content

    def test_a_pod_policy_blocks_a_standalone_member_turn(self) -> None:
        _write_meta("shop-implementer", pod="shop")
        _write_meta("shop-lead", role="lead", pod="shop")
        pod_policies = current_home().pod_config_dir("shop") / "policies"
        pod_policies.mkdir(parents=True, exist_ok=True)
        (pod_policies / "no-uname.json").write_text(
            json.dumps(
                {
                    "kind": "policy",
                    "name": "shop-no-uname",
                    "appliesTo": ["*"],
                    "on": "toolCall",
                    "when": {"matches": "uname"},
                    "then": "block",
                    "message": "shop forbids uname",
                }
            )
        )
        backend = _bash_then_done("uname")
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn("shop-implementer", "agent:shop-implementer:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert "shop-no-uname" in tool_msg.content

    def test_another_pod_is_untouched_by_both(self) -> None:
        _write_meta("shop-implementer", pod="shop")
        _write_meta("other-implementer", pod="other")
        _pod_overlay_denying("shop", "implementer", ["bash"])
        backend = _bash_then_done("uname")
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn("other-implementer", "agent:other-implementer:default", "go", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert "unknown tool" not in tool_msg.content


class TestConsultBudgetReachesTheTurn:
    def test_env_value_wins_and_a_non_pod_agent_gets_the_default(self) -> None:
        resolve = _docket_runtime._max_consultations
        assert resolve("solo-x", "1") == 1
        assert resolve("solo-x", "bad") == 3
        assert resolve("solo-x", None) == 3

    def test_a_pod_member_reads_the_pods_setting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from docket.teams import pod as _pod
        from docket.teams.pod_settings import PodSettings

        monkeypatch.setattr(_pod, "pod_of", lambda agent_id: "shop")
        monkeypatch.setattr(
            PodSettings,
            "load_for",
            classmethod(lambda cls, project: PodSettings(maxConsultationsPerTask=2)),
        )
        assert _docket_runtime._max_consultations("shop-lead", None) == 2
        assert _docket_runtime._max_consultations("shop-lead", "0") == 0


class TestApprovalWaitWiring:
    """What a turn by an agent outside any pod hands its tool context."""

    def _run(self, agent_id: str, workspace: Path, env: dict[str, str] | None = None) -> str:
        _write_meta(agent_id, codebase=str(workspace))
        backend = _ScriptedBackend([_probe_call_response(), _final_response("done")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, registry_factory=_approval_wait_probe_registry
        )
        result = driver.run_turn(agent_id, f"agent:{agent_id}:default", "go", 30, env)
        assert result.ok is True
        return str(next(m for m in backend.calls[1] if m.role == "tool").content)

    def test_the_approval_wait_travels_in_the_env_and_leaves_the_global_alone(
        self, tmp_path: Path
    ) -> None:
        before = current_home().tool_approval_timeout
        out = self._run("solo-aaa111", tmp_path, {"DOCKET_APPROVAL_TIMEOUT": "7"})
        assert out == "timeout=7"
        assert before == current_home().tool_approval_timeout

    def test_an_absent_or_bad_wait_keeps_the_default(self, tmp_path: Path) -> None:
        assert self._run("solo-aaa222", tmp_path) == "timeout=None"
        bad = self._run("solo-aaa333", tmp_path, {"DOCKET_APPROVAL_TIMEOUT": "-3"})
        assert bad == "timeout=None"
