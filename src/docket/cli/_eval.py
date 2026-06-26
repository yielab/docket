"""docket eval — specialist-role eval harness runner.

The evals themselves are Bash scripts under
tests/evals/; this module locates that directory, sets the same environment
variables the Bash command exported (DOCKET_EVAL_LIVE / DOCKET_EVAL_TIER), and
shells out to the harness. `run_eval(...)` returns the process exit code:

  0  PASS        2  SKIP (agent not installed or live mode off)
  other  FAIL

The coordinator wraps the return value in typer.Exit(code).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from docket import ui


def _evals_dir() -> Path | None:
    """Locate tests/evals/ — repo root via DOCKET_CLI_ROOT or package layout."""
    root = Path(os.environ.get("DOCKET_CLI_ROOT", ""))
    if not root.is_dir():
        # src/docket/cli/_eval.py → parents[3] == repo root.
        root = Path(__file__).resolve().parents[3]
    evals = root / "tests" / "evals"
    return evals if evals.is_dir() else None


def _available_roles(evals: Path) -> str:
    """Space-joined role names ('foo.eval.sh' → 'foo') for the error hint."""
    names = sorted(p.name[: -len(".eval.sh")] for p in evals.glob("*.eval.sh"))
    return " ".join(names) + (" " if names else "")


def run_eval(
    live: bool = False,
    tier: str = "standard",
    role: str = "",
    recommend: bool = False,
) -> int:
    """Run the specialist-role eval harness (or print right-sizing hints).

    live:       enable live golden-task checks (exports DOCKET_EVAL_LIVE=1).
    tier:       model-class label recorded with results (economy|standard|premium).
    role:       run only <role>.eval.sh instead of all evals.
    recommend:  print per-role hints from stored results; run no evals.
    """
    evals = _evals_dir()
    if evals is None:
        ui.error("Cannot locate tests/evals/ directory")
        return 1

    live_val = "1" if live else "0"

    if recommend:
        ui.header("Eval model right-sizing hints")
        ui.console.print()
        return subprocess.run(
            ["bash", str(evals / "run-evals.sh"), "--recommend"],
            check=False,
        ).returncode

    if role:
        eval_file = evals / f"{role}.eval.sh"
        if not eval_file.is_file():
            ui.error(f"No eval found for role '{role}'. Available: {_available_roles(evals)}")
            return 1
        ui.header(f"Eval: {role}{' (live)' if live else ''}")
        ui.console.print()
        env = dict(os.environ, DOCKET_EVAL_LIVE=live_val, DOCKET_EVAL_TIER=tier)
        rc = subprocess.run(["bash", str(eval_file)], env=env, check=False).returncode
        ui.console.print()
        if rc == 0:
            ui.success(f"PASS — {role}")
        elif rc == 2:
            ui.warn(f"SKIP — {role} (agent not installed or live mode off)")
        else:
            ui.console.print(f"[red]✗[/red] FAIL — {role}")
        return rc

    env = dict(os.environ, DOCKET_EVAL_LIVE=live_val, DOCKET_EVAL_TIER=tier)
    return subprocess.run(["bash", str(evals / "run-evals.sh")], env=env, check=False).returncode
