"""Each way a task stops for a person opens one escalation record and lists its id on the task
(operator-loop.spec.md "Escalations"), without changing anything the pause already did.

Real dispatch for the consult, input, gate and check_changed sites, and the real tool gate for the
approval site; nothing touches the real DOCKET_HOME.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.support.git import git as _git
from tests.support.home import record_isolation_off
from tests.support.llm import final as _final
from tests.support.pods import build_pod
from tests.support.trace import trace_events as _trace_events

from docket.agent.ports import (
    PIPELINE_WORKTREE_ENV,
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    TurnResult,
    assistant,
)
from docket.agent.tools.registry import ToolContext, dispatch_tool
from docket.governance import approval as _ap
from docket.governance.policy import install_policies
from docket.hops.application import driver as _dr
from docket.hops.application import sweep as _sweep
from docket.hops.application.builtin_tools import builtin_registry
from docket.hops.application.driver import DocketDriver
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel import clock as _clock
from docket.kernel.home import Home, current_home, use_home
from docket.kernel.operator_contract import Escalation, TaskView
from docket.operator import inbox as _inbox
from docket.platform import store as _store
from docket.tasks.application import escalation_sweep as _escalation_sweep
from docket.tasks.application import escalations as _escalations
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import pod_settings as _pod_settings

SUBJECT = "docket.tasks.application.escalations"

_CONSULT = {
    "kind": "decision",
    "message": "Which store should the cache use?",
    "options": [
        {"id": "redis", "label": "Redis", "description": "fast"},
        {"id": "sqlite", "label": "SQLite", "description": "simple"},
    ],
    "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
}

_ASK_YAML = """\
name: ask
steps:
  - lead: lead
  - ask:
      input:
        from: lead
        expiresHours: 2
  - implementer: implementer
"""

_GATED_YAML = (
    "name: gated\nsteps:\n  - lead: lead\n  - implementer: implementer\n    approval: true\n"
)
_PLAIN_YAML = "name: two\nsteps:\n  - lead: lead\n  - implementer: implementer\n"


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        yield


def _only_escalation() -> Escalation:
    (escalation,) = _store.list_escalations()
    return escalation


def _events(event_type: str) -> list[dict[str, Any]]:
    """The payloads of every *event_type* in the demo pod's traces, oldest first."""
    return [e["payload"] for e in _trace_events("demo") if e["event_type"] == event_type]


def _asked_matches(escalation: Escalation) -> dict[str, Any]:
    """The one ``escalation_asked`` payload, checked against the record it describes."""
    (asked,) = _events("escalation_asked")
    assert asked["escalation"] == escalation.id
    assert (asked["kind"], asked["task"], asked["step"]) == (
        escalation.kind,
        escalation.task,
        escalation.step,
    )
    assert asked["options"] == [o.id for o in escalation.options]
    assert asked["onExpiry"] == escalation.on_expiry
    assert asked["prompt"] == escalation.prompt
    return asked


def _the_task() -> TaskRecord:
    (task,) = TaskRepository.for_pod("demo").list()
    return task


def _bind_pipeline(text: str) -> None:
    path = _pod.pod.bound_pipeline_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)


class TestApproval:
    def _ctx(self, tmp_path: Path, task_id: str, mode: str) -> ToolContext:
        workspace = tmp_path / "ws"
        workspace.mkdir(exist_ok=True)
        ctx = ToolContext(
            agent_id="demo-implementer",
            role="implementer",
            project="demo",
            roots=(workspace,),
            task_id=task_id,
        )
        ctx.approval_mode = mode  # type: ignore[assignment]
        return ctx

    def _call(self) -> ToolCall:
        return ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))

    def test_a_parked_tool_call_opens_an_approval_escalation_on_its_task(
        self, tmp_path: Path
    ) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(tmp_path))
        install_policies()
        task = _queue.enqueue_task_once("demo", "tidy", channel="cli")[0]

        result = dispatch_tool(
            self._call(), self._ctx(tmp_path, str(task.id), "park"), builtin_registry()
        )

        assert result.denial_kind == "approval_parked"
        escalation = _only_escalation()
        assert escalation.kind == "approval"
        assert (escalation.task, escalation.pod, escalation.role) == (
            task.id,
            "demo",
            "implementer",
        )
        assert escalation.caused_by == "c1"
        assert escalation.on_expiry == "deny"
        assert [o.id for o in escalation.options] == ["approve_once", "approve_task", "deny"]
        assert escalation.state == "pending"
        assert _ap.approval_of(escalation.id) == result.approval_token
        assert "rm -rf build" in escalation.prompt
        assert escalation.expires_at == _ap.approval_get(result.approval_token)["expiresAt"]
        assert _the_task().escalations == [escalation.id]
        asked = _asked_matches(escalation)
        assert asked["causedBy"] == "c1"
        (traced,) = [e for e in _trace_events("demo") if e["event_type"] == "escalation_asked"]
        assert (traced["session_id"], traced["task_id"]) == (f"agent:demo:{task.id}", task.id)

    def test_a_wait_without_a_queued_task_stores_the_record_and_lists_it_nowhere(
        self, tmp_path: Path
    ) -> None:
        install_policies()
        with use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)):
            result = dispatch_tool(
                self._call(), self._ctx(tmp_path, "", "wait"), builtin_registry()
            )

        assert result.denial_kind == "approval_timeout"
        escalation = _only_escalation()
        assert (escalation.kind, escalation.task, escalation.caused_by) == ("approval", "", "c1")
        assert TaskRepository.for_pod("demo").list() == []
        _asked_matches(escalation)
        (traced,) = [e for e in _trace_events("demo") if e["event_type"] == "escalation_asked"]
        assert traced["session_id"] == "demo-approval"


class TestLevel:
    """A pause evaluates the autonomy table when it is created and records ``level`` and
    ``policy`` (operator-loop.spec.md "Escalations" item 12)."""

    def _ctx(self, tmp_path: Path, task_id: str, mode: str) -> ToolContext:
        workspace = tmp_path / "ws"
        workspace.mkdir(exist_ok=True)
        ctx = ToolContext(
            agent_id="demo-implementer",
            role="implementer",
            project="demo",
            roots=(workspace,),
            task_id=task_id,
        )
        ctx.approval_mode = mode  # type: ignore[assignment]
        return ctx

    def _call(self) -> ToolCall:
        return ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))

    def _pod(self, tmp_path: Path) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(tmp_path))
        install_policies()

    def test_a_pause_records_the_level_its_policy_and_its_expiry(self, tmp_path: Path) -> None:
        self._pod(tmp_path)
        _fleet.set_profile("lights-out")
        task = _queue.enqueue_task_once("demo", "tidy", channel="cli", autonomy="L4")[0]

        dispatch_tool(self._call(), self._ctx(tmp_path, task.id, "park"), builtin_registry())

        escalation = _only_escalation()
        assert (escalation.level, escalation.policy, escalation.on_expiry) == (
            "L4",
            "person",
            "deny",
        )
        assert _asked_matches(escalation)["level"] == "L4"

    def test_a_task_with_no_level_records_the_profile_default(self, tmp_path: Path) -> None:
        self._pod(tmp_path)
        task = _queue.enqueue_task_once("demo", "tidy", channel="cli")[0]

        dispatch_tool(self._call(), self._ctx(tmp_path, task.id, "park"), builtin_registry())

        assert _only_escalation().level == "L3"

    def test_a_pause_that_names_no_queued_task_has_no_level(self, tmp_path: Path) -> None:
        install_policies()
        with use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)):
            dispatch_tool(self._call(), self._ctx(tmp_path, "", "wait"), builtin_registry())

        assert _only_escalation().level is None
        assert "level" not in _asked_matches(_only_escalation())

    def test_l5_denies_a_tool_ask_and_stores_the_decision_on_the_task(self, tmp_path: Path) -> None:
        self._pod(tmp_path)
        _fleet.set_profile("lights-out")
        task = _queue.enqueue_task_once("demo", "tidy", channel="cli", autonomy="L5")[0]

        result = dispatch_tool(
            self._call(), self._ctx(tmp_path, task.id, "refuse"), builtin_registry()
        )

        assert result.denial_kind == "approval_unavailable"
        escalation = _only_escalation()
        assert (escalation.kind, escalation.state, escalation.policy, escalation.level) == (
            "approval",
            "decided",
            "deny",
            "L5",
        )
        assert escalation.resolution is not None
        assert (escalation.resolution.option_id, escalation.resolution.by) == ("deny", "policy")
        assert "rm -rf build" in escalation.prompt
        assert _the_task().escalations == [escalation.id]
        assert _events("escalation_asked") == []
        (decided,) = _events("escalation_decided")
        assert (decided["escalation"], decided["policy"], decided["level"]) == (
            escalation.id,
            "deny",
            "L5",
        )
        assert (decided["by"], decided["optionId"]) == ("policy", "deny")

    def test_an_explicit_refuse_setting_is_not_a_decision_of_the_table(
        self, tmp_path: Path
    ) -> None:
        self._pod(tmp_path)
        _fleet.set_profile("lights-out")
        _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "approvalMode", "refuse")
        task = _queue.enqueue_task_once("demo", "tidy", channel="cli", autonomy="L5")[0]

        result = dispatch_tool(
            self._call(), self._ctx(tmp_path, task.id, "refuse"), builtin_registry()
        )

        assert result.denial_kind == "approval_unavailable"
        assert _store.list_escalations() == []

    def test_a_consult_the_pod_decides_is_stored_on_its_task_with_its_level(
        self, tmp_path: Path
    ) -> None:
        self._pod(tmp_path)
        _fleet.set_profile("lights-out")
        task = _queue.enqueue_task_once("demo", "tidy", channel="cli")[0]
        ctx = self._ctx(tmp_path, task.id, "park")
        ctx.consult_park, ctx.consult_mode = True, "decide"

        result = dispatch_tool(
            ToolCall(id="k1", name="consult", arguments=json.dumps(_CONSULT)),
            ctx,
            builtin_registry(),
        )

        assert result.ok
        escalation = _only_escalation()
        assert (escalation.state, escalation.policy, escalation.level) == (
            "decided",
            "recommendation",
            "L4",
        )
        assert _the_task().escalations == [escalation.id]
        (decided,) = _events("escalation_decided")
        assert (decided["level"], decided["optionId"], decided["by"]) == ("L4", "sqlite", "policy")

    def test_l3_and_l4_leave_a_refuse_posture_without_a_record(self, tmp_path: Path) -> None:
        self._pod(tmp_path)
        task = _queue.enqueue_task_once("demo", "tidy", channel="cli")[0]

        dispatch_tool(self._call(), self._ctx(tmp_path, task.id, "refuse"), builtin_registry())

        assert _store.list_escalations() == []


class _Backend:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: Any = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        tool_choice: str | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        return self._responses.pop(0)


def _consult_response() -> ChatResponse:
    call = ToolCall(id="c1", name="consult", arguments=json.dumps(_CONSULT))
    return ChatResponse(
        ok=True,
        message=assistant("", [call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


def _run_with_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    responses: list[ChatResponse],
    pipeline_yaml: str | None = None,
) -> TaskRecord:
    workspace = tmp_path / "codebase"
    workspace.mkdir()
    build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(workspace))
    _fleet.meta_set("demo-implementer", "codebase", str(workspace))
    _fleet.meta_set("demo-implementer", "verifyCmd", "true")
    _fleet.meta_set(
        "demo-lead", "approvalMode", _pod_settings.PodSettings.coerce("approvalMode", "park")
    )
    _fleet.meta_set(
        "demo-lead", "requireVerify", _pod_settings.PodSettings.coerce("requireVerify", "true")
    )
    _fleet.meta_set(
        "demo-lead", "inputExpiryHours", _pod_settings.PodSettings.coerce("inputExpiryHours", "1")
    )
    if pipeline_yaml is not None:
        _bind_pipeline(pipeline_yaml)
    backend = _Backend(responses)
    driver = DocketDriver(backend_factory=lambda model_name: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    _queue.enqueue_task_once("demo", "in-place task", channel="cli")
    _sweep.dispatch_pod("demo", turn_timeout=60, max_tasks=1)
    return _the_task()


class TestConsult:
    def test_a_parked_consult_opens_an_escalation_carrying_its_options(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _run_with_model(
            tmp_path, monkeypatch, [_final("plan"), _consult_response()], _PLAIN_YAML
        )

        assert task.status == "waiting_input"
        escalation = _only_escalation()
        assert escalation.kind == "consult"
        assert escalation.task == task.id
        assert escalation.step == "implementer"
        assert escalation.on_expiry == "block"
        assert [o.id for o in escalation.options] == ["redis", "sqlite", "decline"]
        assert escalation.recommendation is not None
        assert escalation.recommendation.option_id == "sqlite"
        assert _ap.approval_of(escalation.id) == ""
        assert escalation.prompt
        assert "note" in (escalation.requested_schema or {}).get("properties", {})
        assert escalation.expires_at is not None
        assert task.escalations == [escalation.id]
        _asked_matches(escalation)

    def test_the_inbox_lists_the_parked_task_once_and_the_sweep_expires_the_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _run_with_model(
            tmp_path, monkeypatch, [_final("plan"), _consult_response()], _PLAIN_YAML
        )
        view = _inbox.build_inbox(now=_clock.iso())
        assert [v.id for v in view.needs_you if getattr(v, "pod", "") == "demo"] == [task.id]
        (listed,) = [v for v in view.needs_you if isinstance(v, TaskView)]
        assert listed.escalation == _only_escalation().id

        later = "2999-01-01T00:00:00+00:00"
        assert _escalation_sweep.sweep_escalations(later) == 1

        escalation = _only_escalation()
        assert escalation.state == "expired"
        assert _the_task().status == "blocked"
        (expired,) = _events("escalation_expired")
        assert (expired["escalation"], expired["kind"], expired["by"]) == (
            escalation.id,
            "consult",
            "timeout",
        )
        assert expired["askedAt"] == escalation.asked_at
        assert _escalation_sweep.sweep_escalations(later) == 0
        assert len(_events("escalation_expired")) == 1


class TestInput:
    def test_an_input_step_opens_an_escalation_with_its_schema(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _run_with_model(tmp_path, monkeypatch, [_final("plan")], _ASK_YAML)

        assert task.status == "waiting_input"
        escalation = _only_escalation()
        assert escalation.kind == "input"
        assert (escalation.task, escalation.step) == (task.id, "ask")
        assert escalation.caused_by == "ask"
        assert escalation.on_expiry == "block"
        assert [o.id for o in escalation.options] == ["decline"]
        assert escalation.requested_schema == {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
        assert escalation.expires_at is not None
        assert task.escalations == [escalation.id]
        asked = _asked_matches(escalation)
        assert asked["expiresAt"] == escalation.expires_at


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    _git(path, "config", "user.email", "t@t.test")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("hello\n")
    (path / "package.json").write_text('{"scripts": {"test": "vitest"}}\n')
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")


class _Editor:
    def __init__(self, edits: dict[str, str]) -> None:
        self.edits = edits

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        if agent_id.endswith("-implementer"):
            root = Path((env or {})[PIPELINE_WORKTREE_ENV])
            for rel, text in self.edits.items():
                (root / rel).write_text(text)
        return TurnResult(True, "done", 0.0, {})


@contextmanager
def _seed_git_pod(tmp_path: Path, pipeline: str) -> Iterator[None]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(repo))
    _bind_pipeline(pipeline)
    yield


class TestPipelineGate:
    def test_a_fired_approval_gate_opens_a_gate_escalation(self, tmp_path: Path) -> None:
        with _seed_git_pod(tmp_path, _GATED_YAML):
            _queue.enqueue_task_once("demo", "gated", channel="cli")
            _sweep.dispatch_pod("demo", runner=_Editor({}), max_tasks=1)

            task = _the_task()
            assert task.status == "waiting_approval"
            escalation = _only_escalation()
            assert escalation.kind == "gate"
            assert (escalation.task, escalation.role, escalation.step) == (
                task.id,
                "implementer",
                "implementer",
            )
            assert escalation.on_expiry == "deny"
            assert [o.id for o in escalation.options] == ["approve_once", "deny"]
            assert _ap.approval_of(escalation.id).startswith("apr-")
            assert task.escalations == [escalation.id]
            _asked_matches(escalation)
            assert len(_events("approval_required")) == 1


class TestCheckChanged:
    def test_a_change_that_edits_its_check_opens_a_check_changed_escalation(
        self, tmp_path: Path
    ) -> None:
        with _seed_git_pod(tmp_path, _PLAIN_YAML):
            _queue.enqueue_task_once("demo", "bump", channel="cli")
            _sweep.dispatch_pod("demo", runner=_Editor({"package.json": "{}\n"}), max_tasks=1)

            task = _the_task()
            assert task.status == "waiting_approval"
            escalation = _only_escalation()
            assert escalation.kind == "check_changed"
            assert (escalation.task, escalation.role) == (task.id, "lead")
            assert escalation.on_expiry == "deny"
            assert "package.json" in escalation.prompt
            assert _ap.approval_of(escalation.id).startswith("apr-")
            assert task.escalations == [escalation.id]
            _asked_matches(escalation)

    def test_the_approval_sweep_expires_the_escalation_with_its_approval(
        self, tmp_path: Path
    ) -> None:
        with _seed_git_pod(tmp_path, _PLAIN_YAML):
            _queue.enqueue_task_once("demo", "bump", channel="cli")
            _sweep.dispatch_pod("demo", runner=_Editor({"package.json": "{}\n"}), max_tasks=1)
            token = _ap.approval_of(_only_escalation().id)

            with use_home(dataclasses.replace(current_home(), approval_timeout=-1)):
                data = _ap.approval_get(token)
                data["expiresAt"] = "2000-01-01T00:00:00+00:00"
                _store.write_json(current_home().approvals_dir / f"{token}.json", data)
                assert _escalation_sweep.sweep_escalations() == 1

            escalation = _only_escalation()
            assert escalation.state == "expired"
            (expired,) = _events("escalation_expired")
            assert (expired["escalation"], expired["kind"], expired["by"]) == (
                escalation.id,
                "check_changed",
                "timeout",
            )
            (traced,) = [
                e for e in _trace_events("demo") if e["event_type"] == "escalation_expired"
            ]
            assert traced["session_id"] == f"agent:demo:{escalation.task}"


class TestInbox:
    def _park_standalone(self, tmp_path: Path) -> str:
        install_policies()
        workspace = tmp_path / "ws"
        workspace.mkdir()
        ctx = ToolContext(
            agent_id="demo-implementer", role="implementer", project="demo", roots=(workspace,)
        )
        ctx.approval_mode = "park"
        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
        return dispatch_tool(call, ctx, builtin_registry()).approval_token

    def test_a_standalone_approval_is_listed_until_it_is_resolved(self, tmp_path: Path) -> None:
        token = self._park_standalone(tmp_path)
        escalation = _only_escalation()
        assert _ap.approval_of(escalation.id) == token

        view = _inbox.build_inbox(now=_clock.iso())
        assert [v.id for v in view.needs_you] == [escalation.id]

        _escalations.resolve(escalation.id, "approve_once", None, by="a", channel="cli")

        assert _only_escalation().state == "resolved"
        assert _inbox.build_inbox(now=_clock.iso()).needs_you == []

    def test_a_pending_approval_that_backs_no_escalation_is_not_listed(self) -> None:
        _ap.approval_create("demo", "lead", "ship it")

        assert _inbox.build_inbox(now=_clock.iso()).needs_you == []
        assert _store.list_escalations() == []
