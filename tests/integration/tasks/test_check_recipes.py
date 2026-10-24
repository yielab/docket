"""The ``anti-tautology`` and ``mutation`` recipes: command steps that read the task's base commit.

Each recipe is data only. These tests drive the shipped ``pipeline.yaml`` through real
``dispatch_pod`` claims over a real git repo, with a scripted runner whose Implementer hop writes
and commits files in the root it is handed, so the checks run against genuine git history.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from tests.integration.tasks.test_task_worktrees import _bind_pipeline, _git, _init_repo, _seed_pod
from tests.support import home as _support_home

import docket.kernel.templates as _templates
from docket.agent.ports import PIPELINE_WORKTREE_ENV, TurnResult
from docket.governance import security as _sec
from docket.hops.application import sweep as _sweep
from docket.tasks.application import queue as _queue

_hermetic = _support_home.hermetic_2

SUBJECT = "docket.tasks.application.queue"

_RECIPES = _templates.RECIPES_DIR


def _pipeline_text(recipe: str) -> str:
    return (_RECIPES / recipe / "pipeline.yaml").read_text(encoding="utf-8")


def _anti_tautology_with_this_interpreter() -> str:
    """The recipe's pipeline with its runner override pointed at this interpreter, edited the way
    an operator overrides it (the step's ``env``), so the check never depends on PATH's python3."""
    default = 'ANTI_TAUTOLOGY_RUNNER: "python3 -m pytest -q"'
    text = _pipeline_text("anti-tautology")
    assert default in text
    runner = f"{shlex.quote(sys.executable)} -m pytest -q"
    return text.replace(default, f"ANTI_TAUTOLOGY_RUNNER: {json.dumps(runner)}")


def _run_command(recipe: str) -> str:
    steps = yaml.safe_load(_pipeline_text(recipe))["steps"]
    (command,) = [s["run"] for s in steps if "run" in s]
    assert command
    return command


class _FilesRunner:
    """The Implementer hop writes ``files`` into its root and commits them unless told not to."""

    def __init__(self, files: dict[str, str], *, commit: bool = True) -> None:
        self.files = files
        self.commit = commit

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        if agent_id.endswith("-implementer"):
            root = Path((env or {})[PIPELINE_WORKTREE_ENV])
            for name, body in self.files.items():
                (root / name).write_text(body)
            if self.commit:
                _git(root, "add", ".")
                _git(root, "commit", "-m", "implementer work")
        return TurnResult(True, "done", 0.0, {})


@contextmanager
def _repo_with_module(tmp_path: Path) -> Iterator[Path]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "mod.py").write_text("def f():\n    return 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add mod")
    with _seed_pod(tmp_path, repo):
        yield repo


@pytest.mark.parametrize("recipe", ["anti-tautology", "mutation"])
def test_the_recipe_command_classifies_allow_by_default(recipe: str) -> None:
    verdict = _sec.classify_command(_run_command(recipe))

    assert verdict.action == "allow", verdict.reason


def test_a_test_that_already_passes_on_the_base_fails_the_task(tmp_path: Path) -> None:
    with _repo_with_module(tmp_path) as repo:
        _bind_pipeline(_anti_tautology_with_this_interpreter())
        _queue.enqueue_task_once("demo", "work", channel="cli")
        runner = _FilesRunner(
            {"test_mod.py": "from mod import f\n\n\ndef test_f():\n    assert f() == 1\n"}
        )

        (res,) = _sweep.dispatch_pod("demo", runner=runner, max_tasks=1)

        assert res.status == "failed"
        hops = _queue.read_tasks("demo")[0]["hops"]
        assert "do not test the change" in "".join(h.get("output", "") for h in hops)
        assert not [p for p in _git(repo, "worktree", "list").splitlines() if "anti-tautology" in p]


def test_an_uncommitted_test_that_already_passes_on_the_base_fails_the_task(tmp_path: Path) -> None:
    with _repo_with_module(tmp_path):
        _bind_pipeline(_anti_tautology_with_this_interpreter())
        _queue.enqueue_task_once("demo", "work", channel="cli")
        runner = _FilesRunner(
            {"test_mod.py": "from mod import f\n\n\ndef test_f():\n    assert f() == 1\n"},
            commit=False,
        )

        (res,) = _sweep.dispatch_pod("demo", runner=runner, max_tasks=1)

        assert res.status == "failed"
        hops = _queue.read_tasks("demo")[0]["hops"]
        assert "do not test the change" in "".join(h.get("output", "") for h in hops)


@pytest.mark.parametrize("recipe", ["anti-tautology", "mutation"])
def test_the_recipe_fails_without_a_head_commit(recipe: str, tmp_path: Path) -> None:
    with _repo_with_module(tmp_path) as repo:
        base = _git(repo, "rev-parse", "HEAD")
        env = {**os.environ, "DOCKET_BASE_COMMIT": base, "DOCKET_HEAD_COMMIT": ""}

        done = subprocess.run(
            _run_command(recipe), shell=True, cwd=repo, env=env, capture_output=True, text=True
        )

        assert done.returncode == 1
        assert "no head commit" in done.stdout


def test_a_test_that_fails_on_the_base_and_passes_after_the_change_finishes_done(
    tmp_path: Path,
) -> None:
    with _repo_with_module(tmp_path) as repo:
        _bind_pipeline(_anti_tautology_with_this_interpreter())
        _queue.enqueue_task_once("demo", "work", channel="cli")
        runner = _FilesRunner(
            {
                "mod.py": "def f():\n    return 2\n",
                "test_mod.py": "from mod import f\n\n\ndef test_f():\n    assert f() == 2\n",
            }
        )

        (res,) = _sweep.dispatch_pod("demo", runner=runner, max_tasks=1)

        assert res.status == "done", res.reason
        outputs = "".join(h.get("output", "") for h in _queue.read_tasks("demo")[0]["hops"])
        assert "fail on the base, as they should" in outputs
        assert not [p for p in _git(repo, "worktree", "list").splitlines() if "anti-tautology" in p]


def test_no_changed_test_file_passes_the_step_trivially(tmp_path: Path) -> None:
    with _repo_with_module(tmp_path):
        _bind_pipeline(_anti_tautology_with_this_interpreter())
        _queue.enqueue_task_once("demo", "work", channel="cli")

        (res,) = _sweep.dispatch_pod("demo", runner=_FilesRunner({"notes.txt": "x\n"}), max_tasks=1)

        assert res.status == "done", res.reason
        outputs = "".join(h.get("output", "") for h in _queue.read_tasks("demo")[0]["hops"])
        assert "nothing to check" in outputs


def test_the_mutation_step_scores_only_the_changed_source_file(tmp_path: Path) -> None:
    tool = os.environ.get("MUTATION_CMD", "mutmut")
    if shutil.which(shlex.split(tool)[0]) is None:
        pytest.skip("mutmut is not installed (pip install mutmut); the recipe needs it")
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["src"]\n')
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "src" / "pkg" / "__init__.py").write_text("")
    (repo / "src" / "pkg" / "other.py").write_text("def mul(a, b):\n    return a * b\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_calc.py").write_text(
        "from pkg.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    with _seed_pod(tmp_path, repo):
        _bind_pipeline(_pipeline_text("mutation"))
        _queue.enqueue_task_once("demo", "work", channel="cli")
        runner = _FilesRunner({"src/pkg/calc.py": "def add(a, b):\n    return a + b\n"})

        (res,) = _sweep.dispatch_pod("demo", runner=runner, max_tasks=1)

        assert res.status == "done", res.reason
        outputs = "".join(h.get("output", "") for h in _queue.read_tasks("demo")[0]["hops"])
        assert "pkg.calc.*" in outputs
        assert "pkg.other" not in outputs
