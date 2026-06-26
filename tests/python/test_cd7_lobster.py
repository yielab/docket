"""CD-7: Lobster workflow validate + plan.

Acceptance criteria:
  - validate_lobster() returns [] on a well-formed YAML.
  - validate_lobster() returns error strings for every structural problem.
  - plan_lobster() renders a human-readable plan that names each step and
    explicitly states docket does NOT execute the workflow.
  - validate + plan actions are wired into cmd_workflow (smoke test).
  - suite green, mypy+ruff clean.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

import docket.config as _cfg
from docket.core.lobster import plan_lobster, validate_lobster

# ── helpers ────────────────────────────────────────────────────────────────────

VALID_YAML = """\
name: test-pipeline
description: CI pipeline

variables:
  TARGET: main

steps:
  - id: lint
    type: shell
    command: ruff check .

  - id: test
    type: shell
    command: pytest -v

  - id: summarise
    type: llm
    prompt: |
      Review the test output and write a one-paragraph summary.
    agent: myapp-lead

  - id: notify
    type: message
    channel: telegram
    message: "Pipeline done"
    target: "@team"
"""

MINIMAL_YAML = """\
name: minimal
steps:
  - id: step1
    type: shell
    command: echo hi
"""


# ── TestValidateLobster ────────────────────────────────────────────────────────


class TestValidateLobster:
    def test_valid_returns_empty(self) -> None:
        assert validate_lobster(VALID_YAML) == []

    def test_minimal_valid(self) -> None:
        assert validate_lobster(MINIMAL_YAML) == []

    def test_missing_name(self) -> None:
        yaml = "steps:\n  - id: s1\n    type: shell\n    command: echo hi\n"
        errs = validate_lobster(yaml)
        assert any("name" in e for e in errs)

    def test_missing_steps(self) -> None:
        yaml = "name: test\n"
        errs = validate_lobster(yaml)
        assert any("steps" in e for e in errs)

    def test_empty_steps(self) -> None:
        yaml = "name: test\nsteps: []\n"
        errs = validate_lobster(yaml)
        assert any("empty" in e for e in errs)

    def test_steps_not_list(self) -> None:
        yaml = "name: test\nsteps:\n  key: value\n"
        errs = validate_lobster(yaml)
        assert any("list" in e for e in errs)

    def test_step_missing_id(self) -> None:
        yaml = "name: test\nsteps:\n  - type: shell\n    command: echo hi\n"
        errs = validate_lobster(yaml)
        assert any("'id'" in e for e in errs)

    def test_step_missing_type(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    command: echo hi\n"
        errs = validate_lobster(yaml)
        assert any("'type'" in e for e in errs)

    def test_unknown_step_type(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    type: unknown-thing\n"
        errs = validate_lobster(yaml)
        assert any("unknown type" in e for e in errs)

    def test_duplicate_step_id(self) -> None:
        yaml = (
            "name: test\nsteps:\n"
            "  - id: dup\n    type: shell\n    command: echo 1\n"
            "  - id: dup\n    type: shell\n    command: echo 2\n"
        )
        errs = validate_lobster(yaml)
        assert any("duplicate id" in e for e in errs)

    def test_shell_missing_command(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    type: shell\n"
        errs = validate_lobster(yaml)
        assert any("command" in e for e in errs)

    def test_llm_missing_prompt(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    type: llm\n"
        errs = validate_lobster(yaml)
        assert any("prompt" in e for e in errs)

    def test_message_missing_channel(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    type: message\n    message: hi\n"
        errs = validate_lobster(yaml)
        assert any("channel" in e for e in errs)

    def test_message_missing_message(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    type: message\n    channel: tg\n"
        errs = validate_lobster(yaml)
        assert any("message" in e for e in errs)

    def test_poll_missing_file(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    type: poll\n"
        errs = validate_lobster(yaml)
        assert any("poll" in e and ("file" in e or "files" in e) for e in errs)

    def test_poll_with_file_ok(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    type: poll\n    file: /tmp/done.flag\n"
        assert validate_lobster(yaml) == []

    def test_poll_with_files_ok(self) -> None:
        yaml = (
            "name: test\nsteps:\n  - id: s1\n    type: poll\n"
            "    files:\n      - /tmp/a\n      - /tmp/b\n"
        )
        assert validate_lobster(yaml) == []

    def test_goto_missing_target(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    type: goto\n"
        errs = validate_lobster(yaml)
        assert any("target" in e for e in errs)

    def test_goto_with_target_ok(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    type: goto\n    target: lint\n"
        assert validate_lobster(yaml) == []

    def test_conditional_missing_fields(self) -> None:
        yaml = "name: test\nsteps:\n  - id: s1\n    type: conditional\n"
        errs = validate_lobster(yaml)
        assert any("condition" in e for e in errs)
        assert any("steps" in e for e in errs)

    def test_yaml_parse_error(self) -> None:
        yaml = "name: test\nsteps:\n  - {\n"
        errs = validate_lobster(yaml)
        assert len(errs) == 1
        assert "YAML parse error" in errs[0]

    def test_not_a_mapping(self) -> None:
        errs = validate_lobster("- just a list item\n")
        assert any("mapping" in e for e in errs)

    def test_multiple_errors_collected(self) -> None:
        yaml = (
            "name: test\nsteps:\n"
            "  - id: s1\n    type: shell\n"  # missing command
            "  - id: s2\n    type: llm\n"  # missing prompt
        )
        errs = validate_lobster(yaml)
        assert len(errs) >= 2


# ── TestPlanLobster ────────────────────────────────────────────────────────────


class TestPlanLobster:
    def test_plan_valid_returns_text(self) -> None:
        plan, errs = plan_lobster(VALID_YAML)
        assert errs == []
        assert plan != ""

    def test_plan_shows_workflow_name(self) -> None:
        plan, _ = plan_lobster(VALID_YAML)
        assert "test-pipeline" in plan

    def test_plan_shows_step_count(self) -> None:
        plan, _ = plan_lobster(VALID_YAML)
        assert "Steps (4)" in plan

    def test_plan_shows_all_step_ids(self) -> None:
        plan, _ = plan_lobster(VALID_YAML)
        for sid in ("lint", "test", "summarise", "notify"):
            assert sid in plan

    def test_plan_shows_step_types(self) -> None:
        plan, _ = plan_lobster(VALID_YAML)
        for stype in ("shell", "llm", "message"):
            assert stype in plan

    def test_plan_shows_description(self) -> None:
        plan, _ = plan_lobster(VALID_YAML)
        assert "CI pipeline" in plan

    def test_plan_shows_variables(self) -> None:
        plan, _ = plan_lobster(VALID_YAML)
        assert "Variables" in plan
        assert "TARGET" in plan

    def test_plan_honesty_note(self) -> None:
        plan, _ = plan_lobster(VALID_YAML)
        assert "docket does not execute" in plan.lower() or "docket does not execute" in plan

    def test_plan_daemon_hint(self) -> None:
        plan, _ = plan_lobster(VALID_YAML)
        assert "lobster run" in plan

    def test_plan_invalid_returns_errors(self) -> None:
        plan, errs = plan_lobster("name: x\nsteps: []\n")
        assert plan == ""
        assert len(errs) >= 1

    def test_plan_fallback_name_from_arg(self) -> None:
        yaml = MINIMAL_YAML.replace("name: minimal", "name: minimal")
        plan, _ = plan_lobster(yaml, "override-name")
        assert "minimal" in plan

    def test_plan_no_variables_section_when_empty(self) -> None:
        plan, _ = plan_lobster(MINIMAL_YAML)
        assert "Variables" not in plan


# ── TestCmdWorkflowActions: smoke tests via CLI ─────────────────────────────


class TestCmdWorkflowActions:
    """Smoke-test that validate and plan are reachable in cmd_workflow."""

    AGENT_META: ClassVar[dict[str, object]] = {
        "schemaVersion": 1,
        "kind": "project",
        "name": "My Shop Lead",
        "type": "lead",
        "scope": "project",
        "model": "anthropic/claude-haiku-4-5-20251001",
        "modelSource": "policy",
        "codebase": "/tmp/myshop",
        "stack": "Python",
    }

    @pytest.fixture()
    def agent_ws(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        oc_dir = tmp_path / ".openclaw"
        ws = oc_dir / "workspaces" / "projects" / "myshop"
        wf_dir = ws / "workflows"
        wf_dir.mkdir(parents=True)
        (ws / ".docket-meta.json").write_text(json.dumps(self.AGENT_META))
        (wf_dir / "test-pipeline.lobster.yml").write_text(VALID_YAML)
        monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects")
        return ws

    def test_validate_ok(self, agent_ws: Path) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["workflow", "myshop", "validate", "test-pipeline"])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_validate_missing_workflow(self, agent_ws: Path) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["workflow", "myshop", "validate", "no-such-workflow"])
        assert result.exit_code != 0

    def test_plan_renders_output(self, agent_ws: Path) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["workflow", "myshop", "plan", "test-pipeline"])
        assert result.exit_code == 0
        assert "test-pipeline" in result.output
        assert "docket does not execute" in result.output.lower()

    def test_dry_run_alias(self, agent_ws: Path) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["workflow", "myshop", "dry-run", "test-pipeline"])
        assert result.exit_code == 0
        assert "test-pipeline" in result.output

    def test_validate_bad_workflow_exits_nonzero(self, agent_ws: Path, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        # Write an invalid workflow
        wf_dir = agent_ws / "workflows"
        (wf_dir / "broken.lobster.yml").write_text("name: broken\nsteps: []\n")

        runner = CliRunner()
        result = runner.invoke(app, ["workflow", "myshop", "validate", "broken"])
        assert result.exit_code != 0
