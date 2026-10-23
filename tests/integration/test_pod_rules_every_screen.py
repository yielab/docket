"""A pod's own policies, roles and allowCommands apply on every screen, not only in the tool gate.

Each test installs a rule that exists only in the pod (no global policy, no built-in role) and
drives one screen: enqueue, a hop's output, `/delegate`, approval rationale and reasons,
an answer, the resolved plan and `pod check`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.fakes import FakeDriver
from tests.support.home import record_isolation_off
from tests.support.pods import build_pod
from typer.testing import CliRunner

from docket.agent import ports as _rd
from docket.governance import approval as _approval
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.cli.commands import run as _run
from docket.interfaces.telegram import bot as _tg
from docket.kernel.home import Home, current_home, use_home
from docket.pipeline.application import executor as _executor
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import answers as _answers
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.tasks.domain import task as _task
from docket.teams import fleet as _fleet

SUBJECT = "docket.tasks.application.queue"

_runner = CliRunner()

_INPUT_BLOCK = """kind: policy
name: pod-block-input
appliesTo: ["*"]
on: input
when:
  matches: 'CANARY-PHRASE'
then: block
message: canary
"""

_OUTPUT_BLOCK = """kind: policy
name: pod-block-output
appliesTo: ["*"]
on: output
when:
  matches: 'CANARY-PHRASE'
then: block
message: canary
"""

_AUDITOR_ROLE = (
    "kind: role\nname: auditor\nmodel: cheap\nverdict: [PASS, FAIL]\ninstructions: auditor.md\n"
)

_AUDITOR_PIPELINE = """kind: pipeline
name: audited
steps:
  - id: lead
    role: lead
  - id: auditor
    role: auditor
"""


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        current_home().policies_dir.mkdir(parents=True, exist_ok=True)
        yield


def _pod_policy(name: str, body: str, project: str = "demo") -> None:
    policies = current_home().pod_config_dir(project) / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (policies / f"{name}.yaml").write_text(body, encoding="utf-8")


def _seed_pod(tmp_path: Path, roles: tuple[str, ...] = ("lead", "implementer")) -> None:
    build_pod("demo", roles, codebase=str(tmp_path / "code"))


def _pod_run(*args: str) -> Any:
    return _runner.invoke(_pod.pod_app, list(args))


def _seed_auditor_pod(tmp_path: Path) -> None:
    """A pod whose `auditor` role exists only in the pod's own roles overlay."""
    _seed_pod(tmp_path)
    (tmp_path / "auditor.md").write_text("You audit.\n", encoding="utf-8")
    (tmp_path / "auditor.yaml").write_text(_AUDITOR_ROLE, encoding="utf-8")
    assert _pod_run("update", str(tmp_path / "auditor.yaml"), "--pod", "demo").exit_code == 0
    build_pod("demo", ("lead", "implementer", "auditor"), codebase=str(tmp_path / "code"))
    digest = hashlib.sha256(_AUDITOR_PIPELINE.encode("utf-8")).hexdigest()
    bound = _pod.pod.bound_pipeline_path("demo")
    bound.parent.mkdir(parents=True, exist_ok=True)
    bound.write_text(_AUDITOR_PIPELINE, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)


class _OutputRunner:
    def __init__(self, outputs: dict[str, str]) -> None:
        self.calls: list[str] = []
        self.outputs = outputs

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append(role)
        output = self.outputs.get(role, f"done by {agent_id}")
        return _rd.TurnResult(True, output, 0.01, {"output": output})


class TestDefect39PodPolicyOnEveryScreen:
    def test_defect_39_enqueue_pre_input_refuses_on_a_pod_only_policy(self, tmp_path: Path) -> None:
        _seed_pod(tmp_path)
        _pod_policy("pod-block-input", _INPUT_BLOCK)

        with pytest.raises(_task.DispatchError, match="pod-block-input"):
            _queue.enqueue_task_once("demo", "please CANARY-PHRASE now", channel="cli")

        assert _queue.read_tasks("demo") == []

    def test_defect_39_hop_pre_output_blocks_on_a_pod_only_policy(self, tmp_path: Path) -> None:
        _seed_pod(tmp_path)
        _pod_policy("pod-block-output", _OUTPUT_BLOCK)
        _queue.enqueue_task_once("demo", "Ship it", channel="cli")
        runner = _OutputRunner({"lead": "the lead says CANARY-PHRASE"})

        results = _sweep.dispatch_pod("demo", runner=runner)

        assert results[0].status == "failed"
        assert runner.calls == ["lead"]
        assert "pod-block-output" in results[0].hops[0].error

    def test_defect_39_telegram_delegate_is_refused_on_a_pod_only_policy(
        self, tmp_path: Path
    ) -> None:
        _seed_pod(tmp_path)
        _pod_policy("pod-block-input", _INPUT_BLOCK)
        _fleet.upsert_binding("demo-lead", "42", "telegram")

        result = _tg._handle_delegate("demo-lead", "do CANARY-PHRASE")

        assert not result.ok
        assert "pod-block-input" in result.reply
        assert _queue.read_tasks("demo") == []

    def test_defect_39_approval_rationale_is_blocked_by_a_pod_only_policy(
        self, tmp_path: Path
    ) -> None:
        _seed_pod(tmp_path)
        _pod_policy("pod-block-input", _INPUT_BLOCK)

        assert _approval.screen_rationale("note CANARY-PHRASE", "demo") == ("", True)
        assert _approval.screen_rationale("note CANARY-PHRASE") != ("", True)

    @pytest.mark.parametrize("verb", ["grant", "deny"])
    def test_defect_39_approval_reason_is_blocked_by_a_pod_only_policy(
        self, tmp_path: Path, verb: str
    ) -> None:
        _seed_pod(tmp_path)
        _pod_policy("pod-block-input", _INPUT_BLOCK)
        token = _approval.approval_create("demo", "implementer", "tool call 'bash'")
        resolve = _approval.approval_grant if verb == "grant" else _approval.approval_deny

        with pytest.raises(_approval.ApprovalError, match="pod-block-input"):
            resolve(token, "cli", reason="because CANARY-PHRASE")

        assert _approval.approval_get(token)["state"] == "pending"

    def test_defect_39_answer_content_is_blocked_by_a_pod_only_policy(self, tmp_path: Path) -> None:
        _seed_pod(tmp_path, ("lead", "implementer"))
        ask = "name: ask\nsteps:\n  - id: lead\n    role: lead\n  - id: ask\n    input:\n"
        ask += "      from: lead\n  - id: implementer\n    role: implementer\n"
        digest = hashlib.sha256(ask.encode("utf-8")).hexdigest()
        bound = _pod.pod.bound_pipeline_path("demo")
        bound.parent.mkdir(parents=True, exist_ok=True)
        bound.write_text(ask, encoding="utf-8")
        _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)
        _queue.enqueue_task_once("demo", "needs a decision", channel="cli")
        _sweep.dispatch_pod("demo", runner=FakeDriver())
        parked = _queue.read_tasks("demo")[0]
        assert parked["status"] == "waiting_input"
        _pod_policy("pod-block-input", _INPUT_BLOCK)

        with pytest.raises(_answers.AnswerRejected):
            _answers.answer_task(
                "demo",
                parked["id"],
                "accept",
                {"answer": "CANARY-PHRASE"},
                channel="cli",
                actor="op",
            )

        assert _queue.read_tasks("demo")[0]["status"] == "waiting_input"


class TestDefect20PodRoleGateContract:
    def test_defect_20_dispatch_plan_gates_a_pod_only_role(self, tmp_path: Path) -> None:
        _seed_auditor_pod(tmp_path)

        steps, _index, _instr = _executor._resolve_pipeline_steps("demo", None)

        auditor = next(s for s in steps if s.step_id == "auditor")
        assert auditor.gate is not None

    def test_defect_20_dispatch_fails_a_pod_only_role_step_without_its_verdict(
        self, tmp_path: Path
    ) -> None:
        _seed_auditor_pod(tmp_path)
        _queue.enqueue_task_once("demo", "Audit it", channel="cli")
        runner = _OutputRunner({"auditor": "looks fine to me, no verdict word"})

        results = _sweep.dispatch_pod("demo", runner=runner)

        assert results[0].status == "failed"

    def test_defect_20_run_dry_run_plan_shows_the_pod_only_role_gate(self, tmp_path: Path) -> None:
        _seed_auditor_pod(tmp_path)

        plan = _plan_text(lambda: _run._dry_run("demo", None))

        assert "[auditor] role=auditor" in plan
        assert "gate: none" not in plan.split("[auditor]")[1]

    def test_defect_20_run_resolves_its_plan_with_the_pods_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_auditor_pod(tmp_path)
        seen: list[Any] = []
        real = _orch.resolve_plan

        def spy(
            spec: _pipeline.PipelineSpec, roster: dict[str, str], *, registry: Any = None
        ) -> Any:
            seen.append(registry)
            return real(spec, roster, registry=registry)

        monkeypatch.setattr(_orch, "resolve_plan", spy)

        _run._pod_dispatch("demo")

        assert seen and seen[0].get("auditor") is not None

    def test_defect_20_pod_plan_shows_the_pod_only_role_gate(self, tmp_path: Path) -> None:
        _seed_auditor_pod(tmp_path)

        result = _pod_run("plan", "--pod", "demo")

        assert result.exit_code == 0
        assert "gate: none" not in result.output.split("[auditor]")[1]


def _plan_text(call: Any) -> str:
    from docket.interfaces.cli.render import ui

    with ui.console.capture() as capture:
        call()
    return str(capture.get())


class TestDefect40PodCheckAllowCommands:
    def test_defect_40_pod_check_honours_the_pods_allow_commands(self, tmp_path: Path) -> None:
        _seed_pod(tmp_path)
        before = _pod_run("check", "ruff check .", "--role", "implementer", "--pod", "demo")
        assert "Result: allow" not in before.output
        assert _pod_run("set", "allowCommands", "ruff", "--pod", "demo").exit_code == 0

        after = _pod_run("check", "ruff check .", "--role", "implementer", "--pod", "demo")

        assert "Result: allow" in after.output
