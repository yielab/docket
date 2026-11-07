"""The eval harness CLI. `check-solutions` proves every task's reference solution with no model.

uv run python -m evals.harness.run check-solutions [SUITE|TASK]
uv run python -m evals.harness.run run SELECTOR --provider P --model M [--epochs N] [--out DIR]
uv run python -m evals.harness.run nightly [--base DIR|SHA] [--out DIR]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from evals.harness.compare import ComparisonError, compare_runs, render, resolve_run
from evals.harness.graders import GradeContext, grade_one
from evals.harness.nightly import (
    DEFAULT_MAX_TOKENS,
    LOCAL_BASE_URL,
    LOCAL_CREDENTIAL,
    LOCAL_MODEL,
    LOCAL_PROVIDER,
    NIGHTLY_EPOCHS,
    NIGHTLY_SUITE,
    alarms,
    run_suite,
    stamped_out,
    unpaired,
)
from evals.harness.report import read_trials
from evals.harness.task import Grader, Task, TaskError, discover
from evals.harness.verify import run_hidden

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "tasks"
DEFAULT_HEAD = Path("evals-out")
_GIT_IDENTITY = ["-c", "user.name=eval", "-c", "user.email=eval@example.invalid"]

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Docket agent evals.")


@dataclass(frozen=True)
class Outcome:
    grader: str
    status: Literal["pass", "fail", "skipped"]
    reason: str


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command = ["git", *_GIT_IDENTITY, "-c", "commit.gpgsign=false", *args]
    return subprocess.run(command, cwd=repo, capture_output=True, text=True, check=False)


def _seed(task: Task, work: Path) -> Path:
    """Copy `repo/` into `work` and commit it as a fresh repository."""
    repo = work / "repo"
    shutil.copytree(task.repo, repo, symlinks=True)
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "--allow-empty", "-m", "seed"]):
        done = _git(repo, *args)
        if done.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {done.stderr.strip()}")
    return repo


def _apply_solution(task: Task, repo: Path) -> str | None:
    """Apply `solution/` (every `*.patch`, else a file tree); return a reason on failure."""
    patches = sorted(task.solution.glob("*.patch"))
    if not patches:
        shutil.copytree(task.solution, repo, symlinks=True, dirs_exist_ok=True)
        return None
    for patch in patches:
        done = _git(repo, "apply", str(patch))
        if done.returncode != 0:
            return f"{patch.name} does not apply: {done.stderr.strip()[-300:]}"
    return None


_OUTCOME = frozenset({"outcome.hidden_tests", "outcome.file_exact"})


def _grade(task: Task, grader: Grader, repo: Path, work: Path) -> Outcome:
    """Grade one required grader through the trial's own graders; only outcome graders that need
    no trial run here, the rest are skipped."""
    name = grader.name
    if name == "outcome.task_status":
        return Outcome(name, "skipped", "skipped: a task status needs a trial")
    if name not in _OUTCOME:
        return Outcome(name, "skipped", "skipped: not an outcome grader")
    verifier = (
        run_hidden(repo, task.hidden, work / "verify") if name == "outcome.hidden_tests" else None
    )
    result = grade_one(grader, GradeContext(repo=repo, verifier=verifier))
    return Outcome(name, "pass" if result.status == "pass" else "fail", result.reason)


def check_task(task: Task) -> list[Outcome]:
    """Apply the reference solution in a clean repository and grade every required grader."""
    with tempfile.TemporaryDirectory(prefix="eval-check-") as tmp:
        work = Path(tmp)
        repo = _seed(task, work)
        reason = _apply_solution(task, repo)
        if reason is not None:
            return [Outcome("solution", "fail", reason)]
        return [_grade(task, g, repo, work) for g in task.spec.graders.required]


@app.callback()
def main() -> None:
    """Docket agent evals."""


@app.command("check-solutions")
def check_solutions(
    selector: Annotated[str | None, typer.Argument(help="a suite name or a task id")] = None,
    root: Annotated[Path, typer.Option(help="the tasks directory")] = DEFAULT_ROOT,
) -> None:
    """Prove each task's reference solution passes its outcome graders; exit 1 on the first miss."""
    try:
        tasks = discover(root, selector)
    except TaskError as error:
        typer.echo(f"FAIL {error}")
        raise typer.Exit(1) from error
    if not tasks:
        typer.echo(f"no tasks under {root.name}/: nothing to check")
        return
    for task in tasks:
        outcomes = check_task(task)
        for outcome in outcomes:
            if outcome.status == "skipped":
                typer.echo(f"     {task.id} {outcome.grader} {outcome.reason}")
        failed = next((o for o in outcomes if o.status == "fail"), None)
        if failed is not None:
            typer.echo(f"FAIL {task.id} {failed.grader}: {failed.reason}")
            raise typer.Exit(1)
        typer.echo(f"ok   {task.id}")
    typer.echo(f"{len(tasks)} reference solution(s) pass")


@app.command("compare")
def compare(
    base: Annotated[str, typer.Option(help="a run directory or a base sha")],
    head: Annotated[Path, typer.Option(help="the run directory to judge")] = DEFAULT_HEAD,
) -> None:
    """Pair a run with a base by task@version and print the difference; exit 1 if a run is missing."""
    try:
        result = compare_runs(resolve_run(str(head)), resolve_run(base))
    except (ComparisonError, OSError) as error:
        typer.echo(f"FAIL {error}")
        raise typer.Exit(1) from error
    typer.echo(render(result), nl=False)


def _discover(root: Path, selector: str | None) -> list[Task]:
    try:
        return discover(root, selector)
    except TaskError as error:
        typer.echo(f"FAIL {error}")
        raise typer.Exit(1) from error


@app.command("run")
def run(
    selector: Annotated[str, typer.Argument(help="a suite name or a task id")],
    provider: Annotated[str, typer.Option(help="the provider name to register")],
    model: Annotated[str, typer.Option(help="the model every role uses")],
    epochs: Annotated[int, typer.Option(min=1, help="trials per task")] = 1,
    out: Annotated[Path | None, typer.Option(help="default evals-out/<utc stamp>/")] = None,
    base_url: Annotated[str, typer.Option(help="an OpenAI-compatible endpoint")] = "",
    credential_env: Annotated[
        str | None, typer.Option(help="the NAME of the variable that holds the key")
    ] = None,
    max_tokens: Annotated[int, typer.Option(min=4000, help="the reply bound")] = DEFAULT_MAX_TOKENS,
    root: Annotated[Path, typer.Option(help="the tasks directory")] = DEFAULT_ROOT,
) -> None:
    """Run the selected tasks against a model, then write trials.jsonl, summary.md and summary.json."""
    keys: dict[str, str] = {}
    if credential_env is not None:
        if not os.environ.get(credential_env):
            typer.echo(f"FAIL {credential_env} is not set in the environment")
            raise typer.Exit(1)
        keys[credential_env] = os.environ[credential_env]
    tasks = _discover(root, selector)
    if not tasks:
        typer.echo(f"no tasks under {root.name}/ for {selector!r}: nothing to run")
        return
    target = out or stamped_out()
    run_suite(
        tasks,
        target,
        epochs=epochs,
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        base_url=base_url,
        credential=LOCAL_CREDENTIAL if base_url and not keys else "",
        credential_env=keys,
    )
    typer.echo((target / "summary.md").read_text(encoding="utf-8"), nl=False)


@app.command("nightly")
def nightly(
    base: Annotated[str | None, typer.Option(help="a run directory or a base sha")] = None,
    out: Annotated[Path | None, typer.Option(help="default evals-out/<utc stamp>/")] = None,
    provider: Annotated[str, typer.Option(help="the provider name to register")] = LOCAL_PROVIDER,
    model: Annotated[str, typer.Option(help="the model every role uses")] = LOCAL_MODEL,
    base_url: Annotated[str, typer.Option(help="the local endpoint")] = LOCAL_BASE_URL,
    epochs: Annotated[int, typer.Option(min=1, help="trials per task")] = NIGHTLY_EPOCHS,
    max_tokens: Annotated[int, typer.Option(min=4000, help="the reply bound")] = DEFAULT_MAX_TOKENS,
    root: Annotated[Path, typer.Option(help="the tasks directory")] = DEFAULT_ROOT,
) -> None:
    """Run `regression` on the local endpoint at this commit; exit 1 naming a task that regressed."""
    base_records: list[dict[str, Any]] | None = None
    if base is not None:
        try:
            base_records = read_trials(resolve_run(base))
        except (ComparisonError, OSError) as error:
            typer.echo(f"FAIL {error}")
            raise typer.Exit(1) from error
    tasks = _discover(root, NIGHTLY_SUITE)
    if not tasks:
        typer.echo(f"no tasks in suite {NIGHTLY_SUITE!r} under {root.name}/: nothing to run")
        return
    target = out or stamped_out()
    head = run_suite(
        tasks,
        target,
        epochs=epochs,
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        base_url=base_url,
        credential=LOCAL_CREDENTIAL,
        base=base,
    )
    typer.echo((target / "summary.md").read_text(encoding="utf-8"), nl=False)
    if base_records is None:
        typer.echo("no base given: nothing to alarm against")
        return
    for note in unpaired(head, base_records):
        typer.echo(note)
    raised = alarms(head, base_records)
    for alarm in raised:
        typer.echo(str(alarm))
    if raised:
        raise typer.Exit(1)
    typer.echo("no task regressed against the base")


if __name__ == "__main__":
    app()
