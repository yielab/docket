"""W-3: `docket workflow` is retired — it must exit 1 with the pipeline mapping.

`docket workflow` used to manage a Lobster YAML dialect docket could lint but
not fully execute (the validator silently ignored four constructs its own
template emitted). ROADMAP decision D-16 retires it in favor of a single
pipeline dialect docket actually executes (`core/pipeline.py`, W-1/W-2). This
test locks in the removed-command notice added to `src/docket/__main__.py`'s
`_REMOVED` map — the same pattern used for the D-11 `docket team` retirement
(see test_ch4_team_removed.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run(args: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(tmp_path / ".openclaw"),
        "DOCKET_HOME": str(tmp_path / ".openclaw"),
        "DOCKET_NO_RESTART": "1",
    }


def test_workflow_exits_1(tmp_path: Path) -> None:
    rc, out, _ = _run(["workflow", "myshop"], _env(tmp_path))
    assert rc == 1
    assert "retired" in out.lower()


def test_workflow_matches_team_exit_code(tmp_path: Path) -> None:
    """Same removed-command convention (and exit code) as the D-11 `team` retirement."""
    env = _env(tmp_path)
    workflow_rc, _, _ = _run(["workflow", "myshop"], env)
    team_rc, _, _ = _run(["team", "queue"], env)
    assert workflow_rc == team_rc == 1


def test_workflow_notice_names_pipeline_replacement(tmp_path: Path) -> None:
    rc, out, _ = _run(["workflow", "myshop", "validate", "deploy"], _env(tmp_path))
    assert rc == 1
    assert "docket pipeline validate" in out
    assert "docket pipeline plan" in out
    assert "docket pipeline run" in out


def test_workflow_subcommands_still_exit_1(tmp_path: Path) -> None:
    """Any old subcommand/args still hits the notice — there is no live parsing left."""
    rc, out, _ = _run(["workflow", "myshop", "create", "deploy"], _env(tmp_path))
    assert rc == 1
    assert "retired" in out.lower()


def test_wf_alias_behaves_identically_to_workflow(tmp_path: Path) -> None:
    env = _env(tmp_path)
    wf_rc, wf_out, _ = _run(["wf", "myshop"], env)
    workflow_rc, workflow_out, _ = _run(["workflow", "myshop"], env)
    assert wf_rc == workflow_rc == 1
    assert wf_out == workflow_out


def test_old_workflow_files_preserved_language(tmp_path: Path) -> None:
    rc, out, _ = _run(["workflow"], _env(tmp_path))
    assert rc == 1
    assert ".lobster.yml" in out
    assert "untouched" in out.lower()


def test_lobster_module_is_gone() -> None:
    """core/lobster.py must not exist as an importable module anymore."""
    import importlib

    for name in ("docket.core.lobster", "docket.cli._workflow"):
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{name} still imports — it should have been deleted (W-3, D-16)")


def test_workflow_not_a_registered_typer_command() -> None:
    """The Typer app itself must not register `workflow` — __main__'s removed-command
    check runs before Typer ever sees it, so the app registry should have no trace."""
    from typer.core import TyperGroup
    from typer.main import get_command

    from docket.cli import app

    click_group = get_command(app)
    assert isinstance(click_group, TyperGroup)
    assert "workflow" not in click_group.commands
