"""In-place ephemeral pods: one recipe, one task, the codebase as the Implementer's cwd (hermetic).

The runner provisions a throwaway pod through the same core functions `docket init` uses,
applies a recipe through the `pod apply` path, dispatches exactly one task synchronously
against a scripted backend, and returns the persisted record.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest
from tests.conftest import record_isolation_off, repoint_docket_home

import docket.config as _cfg
from docket.core import fleet as _fleet
from docket.core import pod
from docket.core import pod_apply as _pod_apply
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, assistant
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver

SUBJECT = "docket.core.harness_pipeline"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)


class _ScriptedBackend:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: Any = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        return self._responses.pop(0)


def _final(text: str) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(5, 5)
    )


def _recipe(tmp_path: Path, body: str = "kind: pod\nname: x\nsettings:\n  budgetUsd: 4\n") -> Path:
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    (recipe / "pod.yaml").write_text(body, encoding="utf-8")
    return recipe


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "codebase"
    ws.mkdir()
    return ws


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: _ScriptedBackend,
    *,
    workspace: Path | None = None,
    model: str = "test-model",
    approval_mode: Literal["wait", "park", "refuse"] = "refuse",
    verify_cmd: str = "true",
    recipe: str | None = None,
    next_answer: Any = None,
) -> Any:
    from docket.core import harness_pipeline as hp

    driver = DocketDriver(backend_factory=lambda model_name: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    return hp.run_recipe_task(
        workspace or _workspace(tmp_path),
        recipe or str(_recipe(tmp_path)),
        "in-place task",
        model=model,
        approval_mode=approval_mode,
        timeout=60,
        verify_cmd=verify_cmd,
        next_answer=next_answer,
    )


class TestInPlaceRun:
    def test_one_task_runs_and_its_record_is_returned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _ScriptedBackend([_final("lead plan"), _final("implementer done")])
        run = _run(tmp_path, monkeypatch, backend)

        assert run.project.startswith("h-")
        assert len(run.project) == len("h-") + 8
        assert run.task["status"] == "done"
        assert [h["role"] for h in run.hops][:2] == ["lead", "implementer"]
        assert len(backend.calls) == 2

    def test_implementer_runs_in_the_codebase_with_no_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _ScriptedBackend([_final("lead plan"), _final("implementer done")])
        workspace = _workspace(tmp_path)
        run = _run(tmp_path, monkeypatch, backend, workspace=workspace)

        impl = f"{run.project}-implementer"
        assert _fleet.meta_get(impl, "worktreeDir", "") == ""
        assert _fleet.meta_get(impl, "codebase", "") == str(workspace)

    def test_every_member_runs_on_the_given_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _ScriptedBackend([_final("lead plan"), _final("implementer done")])
        run = _run(tmp_path, monkeypatch, backend, model="pinned-model")

        members = pod.members_of([a.id for a in _fleet.list_agents()], run.project)
        assert members
        for member_id, _role, _idx in members:
            assert _fleet.meta_get(member_id, "model", "") == "pinned-model"

    def test_approval_mode_is_set_through_the_typed_pod_setting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _ScriptedBackend([_final("lead plan"), _final("implementer done")])
        run = _run(tmp_path, monkeypatch, backend, approval_mode="park")

        assert pod.PodSettings.load_for(run.project).approval_mode == "park"

    def test_recipe_is_applied_before_the_task_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _ScriptedBackend([_final("lead plan"), _final("implementer done")])
        run = _run(tmp_path, monkeypatch, backend)

        assert pod.PodSettings.load_for(run.project).budget_usd == 4.0


class TestRequireVerify:
    def test_the_ephemeral_lead_carries_require_verify(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _ScriptedBackend([_final("lead plan"), _final("implementer done")])
        run = _run(tmp_path, monkeypatch, backend)

        assert pod.PodSettings.load_for(run.project).require_verify is True

    def test_the_verify_command_is_recorded_on_the_implementer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _ScriptedBackend([_final("lead plan"), _final("implementer done")])
        run = _run(tmp_path, monkeypatch, backend, verify_cmd="true")

        assert _fleet.meta_get(f"{run.project}-implementer", "verifyCmd", "") == "true"

    def test_an_implementer_with_no_verify_command_fails_the_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _ScriptedBackend([_final("lead plan"), _final("implementer done")])
        run = _run(tmp_path, monkeypatch, backend, verify_cmd="")

        assert run.task["status"] == "failed"
        assert "verifyCmd required" in run.task["reason"]


_INTAKE_NEEDS_INPUT = (
    "Need one thing.\n```json\n"
    '{"objective": "add rate limiting", "acceptance": ["429 after 100"], '
    '"resources": [], "questions": ["Which branch?"]}\n```\nNEEDS-INPUT'
)


class TestResumeAfterQuestion:
    def test_an_answer_resumes_the_parked_question_at_the_lead(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core.harness import Answer

        backend = _ScriptedBackend(
            [
                _final(_INTAKE_NEEDS_INPUT),
                _final("ready\nREADY"),
                _final("implementer done"),
                _final("APPROVE"),
            ]
        )
        seen: list[dict[str, Any]] = []

        def _answer(question: dict[str, Any]) -> Answer:
            seen.append(question)
            return Answer(
                questionId=question["id"], action="accept", content={"q1": "use the main branch"}
            )

        run = _run(tmp_path, monkeypatch, backend, recipe="intake", next_answer=_answer)

        assert len(seen) == 1
        assert run.task["status"] == "done"
        assert [h["role"] for h in run.hops] == [
            "lead",
            "operator",
            "lead",
            "implementer",
            "reviewer",
        ]
        assert "use the main branch" in str(backend.calls[1])

    def test_without_an_answer_source_the_task_waits_for_input(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _ScriptedBackend([_final(_INTAKE_NEEDS_INPUT)])
        run = _run(tmp_path, monkeypatch, backend, recipe="intake")

        assert run.task["status"] == "waiting_input"


class TestRefusals:
    def test_a_missing_workspace_is_refused_before_any_pod_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import harness_pipeline as hp

        backend = _ScriptedBackend([])
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        with pytest.raises(hp.RecipeRunError):
            hp.run_recipe_task(
                tmp_path / "does-not-exist",
                _recipe(tmp_path),
                "task",
                model="m",
                approval_mode="refuse",
                timeout=60,
            )
        assert not _cfg.PROJECTS_DIR.is_dir() or not any(_cfg.PROJECTS_DIR.iterdir())

    def test_an_unknown_recipe_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import harness_pipeline as hp

        with pytest.raises(_pod_apply.PodApplyError):
            hp.run_recipe_task(
                _workspace(tmp_path),
                "no-such-recipe-anywhere",
                "task",
                model="m",
                approval_mode="refuse",
                timeout=60,
            )
