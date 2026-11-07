"""SUBJECT: evals/evaluator/promote.py -- a real failed task of a home becomes a candidate task
directory: scrubbed, seeded at its base commit, with a hidden check that fails until a person
writes the real one."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
from tests.support.tasks import task
from typer.testing import CliRunner, Result

from docket.tasks.domain.task import TaskRecord
from evals.evaluator.run import app
from evals.tests.conftest import BUGGY, FIXED, HIDDEN_TEST
from evals.tests.homes import finished, hop, make_home

runner = CliRunner()
KEY = "sk-abcdefghijklmnopqrstuvwxyz0123456789"
LEAKS = re.compile(r"sk-|/home/|alice")


def git(repo: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.test",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.test",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    done = subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


@pytest.fixture
def codebase(tmp_path: Path) -> tuple[Path, str]:
    """A repository whose base commit holds a secret and a personal path, and one later commit."""
    repo = tmp_path / "shop"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "calc.py").write_text(BUGGY + f"API_KEY = '{KEY}'\nROOT = '/home/alice/Sites/shop'\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "later.py").write_text("LATER = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "later")
    return repo, base


def failed_task(base: str, **fields: object) -> TaskRecord:
    return finished(
        1,
        done=False,
        hops=[hop(evidence={"commit": "c", "baseCommit": base, "diffStat": None})],
        description=f"Fix add() in calc.py. The deploy key is {KEY}; the checkout lives in /home/alice/Sites/shop.",
        reason=f"gate failed: pytest said no under /home/alice/Sites/shop with {KEY}",
        failure_kind="gate_failed",
        **fields,
    )


def promote(home: Path, task_id: str, out: Path, *flags: str, pod: str = "alpha") -> Result:
    args = ["promote", task_id, "--pod", pod, "--home", str(home), "--out", str(out), *flags]
    return runner.invoke(app, args)


def scan(directory: Path) -> list[str]:
    hits = []
    for found in [directory, *directory.rglob("*")]:
        if LEAKS.search(str(found.relative_to(directory.parent))):
            hits.append(str(found))
        if found.is_file() and LEAKS.search(found.read_text(encoding="utf-8", errors="replace")):
            hits.append(str(found))
    return hits


@pytest.fixture
def promoted(tmp_path: Path, codebase: tuple[Path, str]) -> tuple[Path, Path, str]:
    repo, base = codebase
    record = failed_task(base)
    home = make_home(tmp_path, {"alpha": [record]}, codebase=str(repo))
    out = tmp_path / "tasks" / "candidates"
    result = promote(home, record.id, out)
    assert result.exit_code == 0, result.output
    (candidate,) = out.iterdir()
    return candidate, home, record.id


def test_a_failed_task_becomes_a_candidate_directory(promoted: tuple[Path, Path, str]) -> None:
    candidate, _, task_id = promoted
    spec = yaml.safe_load((candidate / "task.yaml").read_text())

    assert spec["id"] == candidate.name
    assert spec["suite"] == "candidates"
    assert spec["version"] == 1
    bare = task_id.removeprefix("task-")
    assert bare in spec["origin"] and "gate_failed" in spec["origin"]
    assert spec["instruction"].startswith("Fix add() in calc.py.")
    assert len(spec["instruction"]) <= 500
    assert not (candidate / "solution").exists()
    assert (candidate / "hidden").is_dir()


def test_the_seed_is_the_base_commit_not_the_head(promoted: tuple[Path, Path, str]) -> None:
    candidate, _, _ = promoted

    assert (candidate / "repo" / "calc.py").is_file()
    assert not (candidate / "repo" / "later.py").exists()
    assert "def add(a, b)" in (candidate / "repo" / "calc.py").read_text()


def test_no_secret_home_path_or_user_name_survives_anywhere(
    promoted: tuple[Path, Path, str],
) -> None:
    candidate, _, _ = promoted

    assert scan(candidate) == []
    assert "[REDACTED]" in (candidate / "repo" / "calc.py").read_text()


def test_a_pointer_to_the_trace_is_written(promoted: tuple[Path, Path, str]) -> None:
    candidate, _, task_id = promoted

    notes = (candidate / "candidate.md").read_text()

    assert "docket task trace" in notes
    assert task_id.removeprefix("task-")[:8] in notes
    assert "--pod alpha" in notes


def test_the_hidden_check_fails_until_a_person_writes_it(promoted: tuple[Path, Path, str]) -> None:
    candidate, _, _ = promoted
    checks = sorted(p.name for p in (candidate / "hidden").iterdir())

    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(candidate / "hidden")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert checks == ["test_todo.py"]
    assert done.returncode != 0
    assert "TODO" in done.stdout


def test_check_solutions_refuses_a_candidate_until_it_is_finished(
    promoted: tuple[Path, Path, str], tmp_path: Path
) -> None:
    candidate, _, _ = promoted
    root = candidate.parent.parent

    refused = runner.invoke(app, ["check-solutions", "--root", str(root)])
    assert refused.exit_code == 1
    assert "suite" in refused.output

    finished_dir = root / "capability" / candidate.name
    finished_dir.parent.mkdir()
    shutil.move(str(candidate), finished_dir)
    spec = yaml.safe_load((finished_dir / "task.yaml").read_text())
    spec["suite"] = "capability"
    (finished_dir / "task.yaml").write_text(yaml.safe_dump(spec))

    no_solution = runner.invoke(app, ["check-solutions", "--root", str(root)])
    assert no_solution.exit_code == 1
    assert "solution" in no_solution.output

    (finished_dir / "solution").mkdir()
    (finished_dir / "solution" / "calc.py").write_text(FIXED)
    todo = runner.invoke(app, ["check-solutions", "--root", str(root)])
    assert todo.exit_code == 1, "the TODO check must still fail the reference solution"

    (finished_dir / "hidden" / "test_todo.py").unlink()
    (finished_dir / "hidden" / "test_add.py").write_text(HIDDEN_TEST)
    ok = runner.invoke(app, ["check-solutions", "--root", str(root)])
    assert ok.exit_code == 0, ok.output


def test_a_task_that_did_not_fail_is_refused(tmp_path: Path, codebase: tuple[Path, str]) -> None:
    repo, _ = codebase
    done = finished(1)
    home = make_home(tmp_path, {"alpha": [done]}, codebase=str(repo))

    result = promote(home, done.id, tmp_path / "out")

    assert result.exit_code == 1
    assert "FAIL" in result.output and "not failed" in result.output
    assert not (tmp_path / "out").exists()


def test_an_unknown_task_and_an_unknown_pod_are_refused(tmp_path: Path) -> None:
    record = task(status="failed", completed_at="2026-11-01T10:00:00Z")
    home = make_home(tmp_path, {"alpha": [record]})

    assert "no task" in promote(home, "task-nope", tmp_path / "out").output
    other = promote(home, record.id, tmp_path / "out", pod="ghost")
    assert other.exit_code == 1 and "no pod" in other.output


def test_a_unique_prefix_of_the_id_finds_the_task(
    tmp_path: Path, codebase: tuple[Path, str]
) -> None:
    repo, base = codebase
    record = failed_task(base)
    home = make_home(tmp_path, {"alpha": [record]}, codebase=str(repo))

    result = promote(home, record.id.removeprefix("task-")[:8], tmp_path / "out")

    assert result.exit_code == 0, result.output


def test_a_task_without_a_resolvable_base_gets_an_empty_seed_and_says_so(tmp_path: Path) -> None:
    record = failed_task("0" * 40)
    home = make_home(tmp_path, {"alpha": [record]})

    result = promote(home, record.id, tmp_path / "out")

    assert result.exit_code == 0, result.output
    (candidate,) = (tmp_path / "out").iterdir()
    assert [p.name for p in (candidate / "repo").iterdir()] == [".gitkeep"]
    assert "No seed" in (candidate / "candidate.md").read_text()
    assert scan(candidate) == []


def test_promoting_twice_does_not_overwrite(
    promoted: tuple[Path, Path, str], tmp_path: Path
) -> None:
    candidate, home, task_id = promoted
    (candidate / "hidden" / "test_todo.py").write_text("# edited by a person\n")

    again = promote(home, task_id, candidate.parent)

    assert again.exit_code == 1 and "exists" in again.output
    assert (candidate / "hidden" / "test_todo.py").read_text() == "# edited by a person\n"
