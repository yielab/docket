"""An old-layout home is served as it is and moved once by ``docket init``: authored
configuration goes under ``config/``, what docket writes under ``state/``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support import home as _support_home
from typer.testing import CliRunner

from docket.interfaces.cli.app import app
from docket.kernel import layout
from docket.kernel.home import Home, use_home

SUBJECT = "docket.kernel.layout"

_hermetic = _support_home.hermetic_no_tty


def _old_home(root: Path) -> Path:
    """An old-layout home: authored and runtime entries side by side at the top."""
    (root / "policies").mkdir(parents=True)
    (root / "policies" / "mine.yaml").write_text("id: mine\n")
    (root / "docket-models.json").write_text("{}")
    (root / "docket-models.json.bak").write_text("{}")
    (root / "recipes" / "r").mkdir(parents=True)
    (root / "sessions").mkdir()
    (root / "audit.log").write_text("")
    (root / ".audit.log.lock").write_text("")
    (root / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    overlay = root / "workspaces" / "pods" / "p" / "config" / "policies"
    overlay.mkdir(parents=True)
    (overlay / "pod.yaml").write_text("id: pod\n")
    (root / "workspaces" / "pods" / "p" / "memory.json").write_text("{}")
    (root / "token").write_text("secret")
    return root


def test_migrate_moves_authored_entries_to_config_and_the_rest_to_state(tmp_path: Path) -> None:
    root = _old_home(tmp_path / "old")
    moved = layout.migrate(root)
    assert "policies" in moved
    assert (root / "config" / "policies" / "mine.yaml").is_file()
    assert (root / "config" / "docket-models.json").is_file()
    assert (root / "config" / "docket-models.json.bak").is_file()
    assert (root / "config" / "recipes" / "r").is_dir()
    assert (root / "config" / "pods" / "p" / "policies" / "pod.yaml").is_file()
    assert not (root / "workspaces" / "pods" / "p" / "config").exists()
    assert (root / "state" / "sessions").is_dir()
    assert (root / "state" / "audit.log").is_file()
    assert (root / "state" / ".audit.log.lock").is_file()
    assert (root / "state" / "workspaces" / "pods" / "p" / "memory.json").is_file()
    assert sorted(p.name for p in root.iterdir()) == ["config", "state", "token"]


def test_a_second_migration_changes_nothing(tmp_path: Path) -> None:
    root = _old_home(tmp_path / "old")
    layout.migrate(root)
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    assert layout.migrate(root) == []
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == before


def test_both_layouts_at_once_is_refused_and_nothing_moves(tmp_path: Path) -> None:
    root = _old_home(tmp_path / "old")
    (root / "state").mkdir()
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    with pytest.raises(layout.LayoutConflict):
        layout.migrate(root)
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == before


def test_a_fresh_home_migrates_to_nothing(tmp_path: Path) -> None:
    assert layout.migrate(tmp_path / "missing") == []
    assert not (tmp_path / "missing").exists()


def test_an_old_layout_home_still_serves_status_without_init(tmp_path: Path) -> None:
    root = _old_home(tmp_path / "old")
    with use_home(Home(root=root)):
        result = CliRunner().invoke(app, ["status"])
    assert result.exit_code in (0, 1), result.output
    assert sorted(p.name for p in root.iterdir()) != ["config", "state", "token"]
    assert not (root / "config").exists()
    assert not (root / "state").exists()


def test_init_moves_an_old_layout_home_and_a_second_init_is_a_no_op(tmp_path: Path) -> None:
    root = _old_home(tmp_path / "old")
    runner = CliRunner()
    with use_home(Home(root=root)):
        first = runner.invoke(app, ["init", "demo", "--blueprint", "research"])
        assert first.exit_code == 0, first.output
        assert (root / "config" / "policies" / "mine.yaml").is_file()
        assert (root / "state" / "audit.log").is_file()
        assert not (root / "policies").exists()
        snapshot = {
            str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
        }
        again = runner.invoke(app, ["init", "demo", "--blueprint", "research"])
        assert again.exit_code == 1, again.output  # the pod exists; the layout is not touched
    assert not (root / "policies").exists()
    assert (root / "config" / "pods" / "p" / "policies" / "pod.yaml").is_file()
    assert snapshot["config/policies/mine.yaml"] == b"id: mine\n"
    assert sorted(p.name for p in root.iterdir()) == ["config", "state", "token"]
