"""The eval harness CLI. `check-solutions` proves every task's reference solution with no model.

uv run python -m evals.harness.run check-solutions [SUITE|TASK]
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import typer

from evals.harness.compare import ComparisonError, compare_runs, render, resolve_run
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


def _file_exact(repo: Path, grader: Grader) -> Outcome:
    name = grader.name
    target = (repo / grader.params["path"]).resolve()
    if not target.is_relative_to(repo.resolve()):
        return Outcome(name, "fail", f"{grader.params['path']} leaves the repository")
    if not target.is_file():
        return Outcome(name, "fail", f"{grader.params['path']} was not produced")
    if target.read_bytes() != grader.params["content"].encode("utf-8"):
        return Outcome(name, "fail", f"{grader.params['path']} differs from the bytes asked for")
    return Outcome(name, "pass", f"{grader.params['path']} matches")


def _grade(task: Task, grader: Grader, repo: Path, work: Path) -> Outcome:
    name = grader.name
    if name == "outcome.hidden_tests":
        result = run_hidden(repo, task.hidden, work / "verify")
        tail = result.output_tail.strip().splitlines()[-1:] or [""]
        return Outcome(
            name, "pass" if result.status == "pass" else "fail", f"{result.status}: {tail[0]}"
        )
    if name == "outcome.file_exact":
        return _file_exact(repo, grader)
    if name == "outcome.task_status":
        return Outcome(name, "skipped", "skipped: a task status needs a trial")
    return Outcome(name, "skipped", "skipped: not an outcome grader")


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


if __name__ == "__main__":
    app()
