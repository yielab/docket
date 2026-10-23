"""``docket pod validate`` and ``docket pod plan`` on a pipeline file, through the pod group."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, current_home, use_home
from docket.pipeline.application import steps as _steps
from docket.tasks.application import queue as _queue
from docket.teams import fleet as _fleet

SUBJECT = "docket.core"

_VALID_PIPELINE = """\
kind: pipeline
name: sample
description: A sample pipeline.
steps:
  - id: plan
    role: lead
  - id: build
    role: implementer
    gate:
      type: mechanical
      command: null
"""

_INVALID_PIPELINE = """\
kind: pipeline
name: broken
steps:
  - id: build
    role: implementer
    verifyCommand: "pytest -q"
"""


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")

    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps({"agents": [], "bindings": []}))

    with use_home(Home(home)):
        yield


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = current_home().projects_dir / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.rsplit("-", 1)[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member_id)


def _run(*args: str) -> Any:
    return CliRunner().invoke(_pod.pod_app, list(args))


def _plan(*args: str) -> Any:
    return _run("plan", "--pod", "demo", *args)


class TestPipelineValidateCli:
    def test_missing_file_is_an_error(self, tmp_path: Path) -> None:
        assert _run("validate", str(tmp_path / "nope.yaml")).exit_code == 1

    def test_valid_file_returns_zero(self, tmp_path: Path) -> None:
        f = tmp_path / "sample.pipeline.yaml"
        f.write_text(_VALID_PIPELINE)
        assert _run("validate", str(f)).exit_code == 0

    def test_invalid_file_returns_one(self, tmp_path: Path) -> None:
        f = tmp_path / "broken.pipeline.yaml"
        f.write_text(_INVALID_PIPELINE)
        assert _run("validate", str(f)).exit_code == 1

    def test_unresolvable_step_model_provider_returns_one_naming_the_step(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "bad-model.pipeline.yaml"
        f.write_text(_VALID_PIPELINE.replace("gate:", "model: nope/x\n    gate:"))
        result = _run("validate", str(f))
        assert result.exit_code == 1
        assert "build" in result.output
        assert "nope" in result.output


class TestPipelinePlanCli:
    def test_unknown_project_is_an_error(self) -> None:
        assert _run("plan", "--pod", "no-such-project").exit_code == 1

    def test_default_pipeline_plan_renders(self) -> None:
        _write_meta("demo-lead")
        result = _plan()
        assert result.exit_code == 0
        assert "default" in result.output
        assert "lead" in result.output
        assert "demo-lead" in result.output

    def test_research_pod_plan_renders_its_blueprint_pipeline_with_no_skips(self) -> None:
        """Every one of a research pod's five steps has a present member -- none renders as
        "skipped — role not in pod"."""
        _write_meta("demo-lead", {"blueprint": "research"})
        for role in ("researcher", "analyst", "writer", "critic"):
            _write_meta(f"demo-{role}")

        result = _plan()

        assert result.exit_code == 0
        for role in ("researcher", "analyst", "writer", "critic"):
            assert role in result.output
        assert "skipped — role not in pod" not in result.output

    def test_custom_file_plan_renders_that_pipeline(self, tmp_path: Path) -> None:
        _write_meta("demo-lead")
        f = tmp_path / "sample.pipeline.yaml"
        f.write_text(_VALID_PIPELINE)
        result = _plan("--pipeline", str(f))
        assert result.exit_code == 0
        assert "Pipeline: sample" in result.output
        assert "build" in result.output
        assert f"Source: file '{f}'" in result.output

    def test_a_pipeline_file_without_kind_is_planned(self, tmp_path: Path) -> None:
        _write_meta("demo-lead")
        f = tmp_path / "plain.yaml"
        f.write_text(_VALID_PIPELINE.replace("kind: pipeline\n", ""))
        assert _plan("--pipeline", str(f)).exit_code == 0

    def test_plan_renders_a_step_model_override(self, tmp_path: Path) -> None:
        _write_meta("demo-lead")
        _write_meta("demo-implementer")
        f = tmp_path / "with-model.pipeline.yaml"
        f.write_text(_VALID_PIPELINE.replace("gate:", "model: strong\n    gate:"))
        result = _plan("--pipeline", str(f))
        assert result.exit_code == 0
        assert "model=strong" in result.output

    def test_default_pipeline_plan_names_the_built_in_source(self) -> None:
        _write_meta("demo-lead")
        result = _plan()
        assert result.exit_code == 0
        assert "Source: built-in default" in result.output

    def test_blueprint_pipeline_plan_names_the_blueprint_source(self) -> None:
        _write_meta("demo-lead", {"blueprint": "research"})
        for role in ("researcher", "analyst", "writer", "critic"):
            _write_meta(f"demo-{role}")
        result = _plan()
        assert result.exit_code == 0
        assert "Source: blueprint 'research'" in result.output

    def test_bound_pipeline_plan_names_the_bound_source(self, tmp_path: Path) -> None:
        from docket.interfaces.cli.commands.pod import _pod_config_set_pipeline

        _write_meta("demo-lead")
        _write_meta("demo-implementer")
        f = tmp_path / "sample.pipeline.yaml"
        f.write_text(_VALID_PIPELINE)
        _pod_config_set_pipeline("demo", "demo-lead", str(f))

        result = _plan()

        assert result.exit_code == 0
        assert "Source: bound pipeline (hash " in result.output
        assert "Pipeline: sample" in result.output

    def test_invalid_custom_file_is_an_error(self, tmp_path: Path) -> None:
        _write_meta("demo-lead")
        f = tmp_path / "broken.pipeline.yaml"
        f.write_text(_INVALID_PIPELINE)
        assert _plan("--pipeline", str(f)).exit_code == 1

    def test_plan_renders_from_the_real_executor_not_a_second_printer(self) -> None:
        """`plan`'s output must come from core.orchestrator.render_plan/resolve_plan -- the
        exact same function the real executor calls."""
        from docket.pipeline.domain import plan as _orch
        from docket.teams import roles as _archetypes

        _write_meta("demo-lead")
        result = _plan()
        assert result.exit_code == 0

        expected_spec = _steps.effective_pipeline("demo", None)
        expected_plan = _orch.resolve_plan(
            expected_spec,
            _queue.pod_full_roster("demo"),
            registry=_archetypes.load_registry(),
        )
        assert _orch.render_plan(expected_plan) in result.output
