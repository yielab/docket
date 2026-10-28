"""A role that declares a ``floor`` refuses a model whose recorded test of that prompt failed
(model-profiles.spec.md, "Prompt variants and the floor" requirement 4): the task settles as
``dispatch_refused`` with the fixed reason and no hop runs, with no fallback model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.support import pods as _support_pods
from tests.support.pods import seed_lean_pod as _seed_lean_pod

from docket.agent import ports as _rd
from docket.hops.application import executor as _executor
from docket.kernel.home import current_home
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.tasks.domain.state import Status
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import model_selection as _models
from docket.teams import prompt_tests, prompts

pod_home = _support_pods.pod_home_bare

SUBJECT = "docket.hops.gates.pre_hop"

_PROJECT = "myapp"


def _lead_with_floor(floor: str) -> None:
    """A pod overlay Lead that declares *floor*."""
    roles = current_home().pod_config_dir(_PROJECT) / "roles"
    roles.mkdir(parents=True)
    (roles / "lead.yaml").write_text(
        f"kind: role\nname: lead\nmodel: cheap\nfloor: [{floor}]\n", encoding="utf-8"
    )
    (roles / "lead.md").write_text("You are ${role}.\n", encoding="utf-8")


def _dispatch(calls: list[str]) -> Any:
    spec = _pipeline.PipelineSpec(name="solo", steps=[_step.Step(id="lead", role="lead")])

    def _runner(
        agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None
    ) -> _rd.TurnResult:
        calls.append(agent_id)
        return _rd.TurnResult(True, "done", 0.0, {})

    task = TaskRecord(id="task-1", description="x", status=Status.running)
    return _executor.dispatch_task(_PROJECT, task, runner=_runner, spec=spec)


def _record(result: str) -> str:
    model = str(_fleet.meta_get(f"{_PROJECT}-lead", "model", "") or current_home().default_model)
    sha = prompts.resolve_prompt(
        "hop", "lead", project=_PROJECT, model_class=_models.model_class_of(model)
    ).sha256
    prompt_tests.record(model, sha, "hop/lead", prompt_tests.PromptTestResult(result, 1, ()))
    return model


def test_a_role_refuses_a_model_that_failed_its_floor(pod_home: Path) -> None:
    _seed_lean_pod(_PROJECT)
    _lead_with_floor("hop/lead")
    model = _record("fail")
    calls: list[str] = []

    result = _dispatch(calls)

    assert result.status == "failed"
    assert result.failure_kind == "dispatch_refused"
    assert result.reason.startswith(
        f"model {model} failed the floor test of prompt hop/lead (sha256 "
    )
    assert calls == []


def test_a_model_that_passed_or_was_never_tested_runs(pod_home: Path) -> None:
    _seed_lean_pod(_PROJECT)
    _lead_with_floor("hop/lead")
    calls: list[str] = []

    assert _dispatch(calls).status != "failed"
    assert calls == [f"{_PROJECT}-lead"]

    _record("pass")
    calls.clear()

    assert _dispatch(calls).status != "failed"
    assert calls == [f"{_PROJECT}-lead"]
