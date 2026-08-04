"""`docket eval` is retired — it must exit 1 with an explanation, not run anything.

`tests/evals/` was a "non-blocking specialist-role eval harness" that could not
actually run: it shelled out to the deleted OpenClaw daemon (`WORKSPACE` under
`$HOME/.openclaw/workspaces/<role>`, `openclaw agent --local --json`), and
`eval_skip_unless_command openclaw` made it skip silently rather than fail,
which is why the drift went unnoticed. Unlike `docket workflow`/`docket team`,
there is no replacement command — no CLI entry point runs a single agent turn
to repoint the harness at (`DocketDriver.run_turn` is only reached from pod
dispatch and `maintain distill`), so repairing it would mean inventing new
surface against a private port, not fixing a bug. The whole feature (CLI
command, `cli/_eval.py`, the doctor eval-results advisory, `tests/evals/`) was
removed instead (CL-J). This test locks in the removed-command notice added
to `src/docket/__main__.py`'s `_REMOVED` map — the same pattern used for the
`docket workflow`/`docket team` retirements (see test_workflow_command_removed.py
and test_team_command_removed.py).
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
        "DOCKET_HOME": str(tmp_path / ".docket"),
    }


def test_eval_exits_1(tmp_path: Path) -> None:
    rc, out, _ = _run(["eval"], _env(tmp_path))
    assert rc == 1
    assert "removed" in out.lower()


def test_eval_matches_team_exit_code(tmp_path: Path) -> None:
    """Same removed-command convention (and exit code) as the `team` retirement."""
    env = _env(tmp_path)
    eval_rc, _, _ = _run(["eval"], env)
    team_rc, _, _ = _run(["team", "queue"], env)
    assert eval_rc == team_rc == 1


def test_eval_notice_explains_no_replacement(tmp_path: Path) -> None:
    """Unlike workflow/team, there is no `docket <x>` successor to point at — the
    notice must say so plainly rather than inventing one."""
    rc, out, _ = _run(["eval"], _env(tmp_path))
    assert rc == 1
    assert "no replacement command" in out.lower()
    assert "tests/evals/" in out
    assert "deleted" in out.lower()


def test_eval_flags_still_exit_1(tmp_path: Path) -> None:
    """Any old flag/argument still hits the notice — there is no live parsing left."""
    rc, out, _ = _run(["eval", "--live", "--role", "reviewer"], _env(tmp_path))
    assert rc == 1
    assert "removed" in out.lower()


def test_evals_alias_behaves_identically_to_eval(tmp_path: Path) -> None:
    env = _env(tmp_path)
    evals_rc, evals_out, _ = _run(["evals"], env)
    eval_rc, eval_out, _ = _run(["eval"], env)
    assert evals_rc == eval_rc == 1
    assert evals_out == eval_out


def test_eval_module_is_gone() -> None:
    """cli/_eval.py must not exist as an importable module anymore."""
    import importlib

    try:
        importlib.import_module("docket.cli._eval")
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError("docket.cli._eval still imports — it should have been deleted")


def test_eval_not_a_registered_typer_command() -> None:
    """The Typer app itself must not register `eval` — __main__'s removed-command
    check runs before Typer ever sees it, so the app registry should have no trace."""
    from typer.core import TyperGroup
    from typer.main import get_command

    from docket.cli import app

    click_group = get_command(app)
    assert isinstance(click_group, TyperGroup)
    assert "eval" not in click_group.commands
