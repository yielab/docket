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
from tests.conftest import repoint_docket_home

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
) -> Any:
    from docket.core import harness_pipeline as hp

    driver = DocketDriver(backend_factory=lambda model_name: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    return hp.run_recipe_task(
        workspace or _workspace(tmp_path),
        str(_recipe(tmp_path)),
        "in-place task",
        model=model,
        approval_mode=approval_mode,
        timeout=60,
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

    def test_every_member_is_pinned_to_the_given_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _ScriptedBackend([_final("lead plan"), _final("implementer done")])
        run = _run(tmp_path, monkeypatch, backend, model="pinned-model")

        members = pod.members_of([a.id for a in _fleet.list_agents()], run.project)
        assert members
        for member_id, _role, _idx in members:
            assert _fleet.meta_get(member_id, "model", "") == "pinned-model"
            assert _fleet.meta_get(member_id, "modelSource", "") == "pinned"

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
