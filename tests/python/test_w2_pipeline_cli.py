"""``docket pipeline`` CLI surface (ROADMAP Phase 16 W-1 format / W-2 executor).

Exercises ``cli/_pipeline.py``'s ``run_pipeline`` dispatcher directly (the
same layer ``cli/__init__.py``'s ``cmd_pipeline`` delegates to) — validate,
plan, and run — plus a CliRunner smoke test proving it's actually wired on
the Typer app.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli._pipeline import run_pipeline
from docket.core import dispatch as _dispatch
from docket.edges.adapters import openclaw as _oc

_VALID_PIPELINE = """\
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
name: broken
steps:
  - id: build
    role: implementer
    verifyCommand: "pytest -q"
"""


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")

    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))

    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", oc_dir / "traces", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "RUNS_FILE", tmp_path / "docket-runs.json", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = _cfg.PROJECTS_DIR / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.rsplit("-", 1)[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "modelSource": "policy",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _oc.add_agent(member_id, meta["model"], meta["sessionKey"], "default")


class TestPipelineValidateCli:
    def test_missing_arg_is_an_error(self) -> None:
        assert run_pipeline("validate", []) == 1

    def test_missing_file_is_an_error(self, tmp_path: Path) -> None:
        assert run_pipeline("validate", [str(tmp_path / "nope.yaml")]) == 1

    def test_valid_file_returns_zero(self, tmp_path: Path) -> None:
        f = tmp_path / "sample.pipeline.yaml"
        f.write_text(_VALID_PIPELINE)
        assert run_pipeline("validate", [str(f)]) == 0

    def test_invalid_file_returns_one(self, tmp_path: Path) -> None:
        f = tmp_path / "broken.pipeline.yaml"
        f.write_text(_INVALID_PIPELINE)
        assert run_pipeline("validate", [str(f)]) == 1


class TestPipelinePlanCli:
    def test_missing_arg_is_an_error(self) -> None:
        assert run_pipeline("plan", []) == 1

    def test_unknown_project_is_an_error(self) -> None:
        assert run_pipeline("plan", ["no-such-project"]) == 1

    def test_default_pipeline_plan_renders(self, capsys: pytest.CaptureFixture[str]) -> None:
        _write_meta("demo-lead")
        rc = run_pipeline("plan", ["demo"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "default" in out
        assert "lead" in out
        assert "demo-lead" in out

    def test_custom_file_plan_renders_that_pipeline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_meta("demo-lead")
        f = tmp_path / "sample.pipeline.yaml"
        f.write_text(_VALID_PIPELINE)
        rc = run_pipeline("plan", ["demo", "--file", str(f)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Pipeline: sample" in out
        assert "build" in out

    def test_invalid_custom_file_is_an_error(self, tmp_path: Path) -> None:
        _write_meta("demo-lead")
        f = tmp_path / "broken.pipeline.yaml"
        f.write_text(_INVALID_PIPELINE)
        assert run_pipeline("plan", ["demo", "--file", str(f)]) == 1

    def test_plan_renders_from_the_real_executor_not_a_second_printer(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`plan`'s output must come from core.orchestrator.render_plan/
        resolve_plan -- the exact same function the real executor calls --
        never a hand-written second interpretation of the spec."""
        from docket.core import archetypes as _archetypes
        from docket.core import orchestrator as _orch

        _write_meta("demo-lead")
        rc = run_pipeline("plan", ["demo"])
        assert rc == 0
        out = capsys.readouterr().out

        expected_spec = _dispatch.effective_pipeline("demo", None)
        expected_plan = _orch.resolve_plan(
            expected_spec,
            _dispatch.pod_full_roster("demo"),
            registry=_archetypes.load_registry(),
        )
        assert _orch.render_plan(expected_plan) in out


class TestPipelineRunCli:
    def test_missing_arg_is_an_error(self) -> None:
        assert run_pipeline("run", []) == 1

    def test_no_pending_tasks_is_a_warning_not_an_error(self) -> None:
        _write_meta("demo-lead")
        assert run_pipeline("run", ["demo"]) == 0

    def test_invalid_custom_file_is_an_error(self, tmp_path: Path) -> None:
        _write_meta("demo-lead")
        f = tmp_path / "broken.pipeline.yaml"
        f.write_text(_INVALID_PIPELINE)
        assert run_pipeline("run", ["demo", "--file", str(f)]) == 1

    def test_run_dispatches_through_the_default_pipeline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Phase 19 P19-7a repointed core/dispatch.py's production driver
        # resolution at edges.adapters.docket_runtime.default_driver()
        # (DocketDriver), not the ACL's OpenClawDriver -- this fake `openclaw`
        # binary on PATH is only reached if we monkeypatch the resolution
        # point back, which is exactly what this test wants to keep proving
        # (the pipeline CLI wires through to a real dispatch, whichever
        # driver is behind it).
        monkeypatch.setattr(
            "docket.edges.adapters.docket_runtime.default_driver", _oc.OpenClawDriver
        )
        bindir = tmp_path / "bin"
        bindir.mkdir()
        script = bindir / "openclaw"
        script.write_text(
            "#!/usr/bin/env python3\nimport json\nprint(json.dumps({'output': 'done', 'cost': 0.0}))\n"
        )
        script.chmod(0o755)
        import os

        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")

        _write_meta("demo-lead")
        _dispatch.enqueue_task("demo", "a task")
        rc = run_pipeline("run", ["demo"])
        assert rc == 0
        assert _dispatch.read_tasks("demo")[0]["status"] == "done"


class TestPipelineUnknownSubcommand:
    def test_unknown_subcommand_errors(self) -> None:
        assert run_pipeline("bogus", []) == 1

    def test_no_subcommand_errors(self) -> None:
        assert run_pipeline(None, []) == 1


class TestPipelineCommandWiring:
    def test_pipeline_validate_wired_on_app(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        f = tmp_path / "sample.pipeline.yaml"
        f.write_text(_VALID_PIPELINE)
        runner = CliRunner()
        result = runner.invoke(app, ["pipeline", "validate", str(f)])
        assert result.exit_code == 0

    def test_pipeline_is_a_top_level_command(self) -> None:
        import typer.main

        from docket.cli import app

        click_command = typer.main.get_command(app)
        assert "pipeline" in click_command.commands
