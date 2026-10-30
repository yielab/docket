"""A home is laid out on two levels: ``docket init`` refuses one that keeps authored configuration
and runtime state side by side at its top, naming the entries and moving nothing."""

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


def _single_level_home(root: Path) -> Path:
    """Authored and runtime entries side by side at the top, plus a token the operator placed."""
    (root / "policies").mkdir(parents=True)
    (root / "policies" / "mine.yaml").write_text("id: mine\n")
    (root / "docket-models.json").write_text("{}")
    (root / "docket-models.json.bak").write_text("{}")
    (root / "sessions").mkdir()
    (root / "audit.log").write_text("")
    (root / ".audit.log.lock").write_text("")
    (root / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    (root / "token").write_text("secret")
    return root


def _tree(root: Path) -> dict[str, bytes | None]:
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in root.rglob("*")
    }


def test_the_entries_the_layout_places_under_config_and_state_are_found_at_the_top(
    tmp_path: Path,
) -> None:
    root = _single_level_home(tmp_path / "docket-home")
    found = sorted(p.name for p in layout.single_level_entries(root))
    assert found == [
        ".audit.log.lock",
        "audit.log",
        "docket-models.json",
        "docket-models.json.bak",
        "fleet.json",
        "policies",
        "sessions",
    ]


def test_a_two_level_home_and_a_missing_home_hold_no_such_entry(tmp_path: Path) -> None:
    (tmp_path / "docket-home" / "config" / "policies").mkdir(parents=True)
    (tmp_path / "docket-home" / "state").mkdir()
    (tmp_path / "docket-home" / "token").write_text("secret")
    assert layout.single_level_entries(tmp_path / "docket-home") == []
    assert layout.single_level_entries(tmp_path / "missing") == []


def test_init_refuses_a_home_holding_fleet_json_at_its_root_and_moves_nothing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "docket-home"
    root.mkdir()
    (root / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    before = _tree(root)
    with use_home(Home(root=root)):
        result = CliRunner().invoke(app, ["init", "demo", "--blueprint", "research"])
    assert result.exit_code == 1, result.output
    assert "fleet.json" in result.output
    assert _tree(root) == before


def test_init_names_every_entry_and_changes_nothing_in_a_larger_home(tmp_path: Path) -> None:
    root = _single_level_home(tmp_path / "docket-home")
    before = _tree(root)
    with use_home(Home(root=root)):
        result = CliRunner().invoke(app, ["init", "demo", "--blueprint", "research"])
    assert result.exit_code == 1, result.output
    for name in ("policies", "docket-models.json", "sessions", "audit.log", "fleet.json"):
        assert name in result.output
    assert _tree(root) == before
    assert not (root / "config").exists()
    assert not (root / "state").exists()


@pytest.mark.parametrize("beside", ["config", "state"])
def test_a_stray_top_level_entry_is_refused_beside_a_two_level_home_too(
    tmp_path: Path, beside: str
) -> None:
    root = tmp_path / "docket-home"
    (root / beside).mkdir(parents=True)
    (root / "sessions").mkdir()
    before = _tree(root)
    with use_home(Home(root=root)):
        result = CliRunner().invoke(app, ["init", "demo", "--blueprint", "research"])
    assert result.exit_code == 1, result.output
    assert "sessions" in result.output
    assert _tree(root) == before


def test_init_on_a_two_level_home_provisions_as_before(tmp_path: Path) -> None:
    root = tmp_path / "docket-home"
    (root / "token").parent.mkdir(parents=True)
    (root / "token").write_text("secret")
    with use_home(Home(root=root)):
        result = CliRunner().invoke(app, ["init", "demo", "--blueprint", "research"])
    assert result.exit_code == 0, result.output
    assert (root / "config").is_dir()
    assert (root / "token").read_text() == "secret"
