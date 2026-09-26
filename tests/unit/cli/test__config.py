"""``docket.cli._config`` -- argument parsing and root resolution, in isolation.

The end-to-end oracle (report values match a real FakeDriver dispatch) lives in
tests/integration/test_config_explain.py; this file covers the pure pieces that
don't need a full pod fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

import docket.config as _cfg
from docket.cli import _config
from docket.core.models import AgentMeta

SUBJECT = "docket.cli._config"


class TestRootsFor:
    def test_worktree_wins_over_everything(self) -> None:
        meta = AgentMeta(kind="project", codebase="/repo", work_dir="/work")
        roots = _config._roots_for("agent-1", meta, "/worktree")
        assert roots == (Path("/worktree"),)

    def test_codebase_wins_over_work_dir(self) -> None:
        meta = AgentMeta(kind="project", codebase="/repo", work_dir="/work")
        roots = _config._roots_for("agent-1", meta, "")
        assert roots == (Path("/repo"),)

    def test_work_dir_when_no_codebase(self) -> None:
        meta = AgentMeta(kind="project", work_dir="/work")
        roots = _config._roots_for("agent-1", meta, "")
        assert roots == (Path("/work"),)

    def test_falls_back_to_the_agents_own_workspace(self) -> None:
        meta = AgentMeta(kind="project")
        roots = _config._roots_for("agent-1", meta, "")
        assert roots == (_cfg.workspace_dir("agent-1"),)


class TestDispatchUsage:
    def test_unknown_action_refuses(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(typer.Exit) as exc:
            _config.dispatch("nope", ["some-id"])
        assert exc.value.exit_code == 1
        assert "Unknown config action" in capsys.readouterr().err

    def test_explain_with_no_agent_id_refuses(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(typer.Exit) as exc:
            _config.dispatch("explain", [])
        assert exc.value.exit_code == 1
        assert "Usage:" in capsys.readouterr().err

    def test_explain_with_too_many_args_refuses(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(typer.Exit) as exc:
            _config.dispatch("explain", ["one", "two"])
        assert exc.value.exit_code == 1
        assert "Usage:" in capsys.readouterr().err
