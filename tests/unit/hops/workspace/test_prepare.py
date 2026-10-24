"""Install-command resolution, the per-lockfile cache and its links for a task worktree."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.hops.workspace import prepare as _prepare
from docket.kernel import text as _text
from docket.kernel.home import Home, current_home, use_home

SUBJECT = "docket.hops.workspace.prepare"


@pytest.fixture(autouse=True)
def _cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(_prepare._git, "git_info_exclude", lambda common, patterns: None)
    with use_home(Home(tmp_path)) as home:
        yield home.prepare_cache_dir


def _tree(root: Path, lockfile: str = "package-lock.json", body: str = "{}") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if lockfile:
        (root / lockfile).write_text(body)
    return root


@pytest.mark.parametrize(
    ("lockfile", "command"),
    [
        ("package-lock.json", "npm ci"),
        ("pnpm-lock.yaml", "pnpm install --frozen-lockfile"),
        ("yarn.lock", "yarn install --immutable"),
        ("uv.lock", "uv sync --frozen"),
        ("poetry.lock", "poetry install"),
        ("Cargo.lock", "cargo fetch"),
    ],
)
def test_each_lockfile_maps_to_its_install_command(
    tmp_path: Path, lockfile: str, command: str
) -> None:
    spec = _prepare.resolve(_tree(tmp_path / "wt", lockfile), task_prepare=None, pod_prepare="")
    assert spec is not None
    assert (spec.command, spec.source) == (command, "lockfile")


def test_the_first_lockfile_in_the_table_wins(tmp_path: Path) -> None:
    root = _tree(tmp_path / "wt", "yarn.lock")
    (root / "package-lock.json").write_text("{}")
    spec = _prepare.resolve(root, task_prepare=None, pod_prepare="")
    assert spec is not None and spec.command == "npm ci"


def test_the_lock_hash_is_the_lockfiles_sha256(tmp_path: Path) -> None:
    root = _tree(tmp_path / "wt", body="abc")
    spec = _prepare.resolve(root, task_prepare=None, pod_prepare="")
    assert spec is not None and spec.lock_hash == hashlib.sha256(b"abc").hexdigest()


def test_no_lockfile_and_no_command_runs_nothing(tmp_path: Path) -> None:
    assert _prepare.resolve(_tree(tmp_path / "wt", ""), task_prepare=None, pod_prepare="") is None


def test_the_task_wins_over_the_pod_and_the_pod_over_the_lockfile(tmp_path: Path) -> None:
    root = _tree(tmp_path / "wt")
    task = _prepare.resolve(root, task_prepare=" make deps ", pod_prepare="pod cmd")
    pod = _prepare.resolve(root, task_prepare=None, pod_prepare="pod cmd")
    assert task is not None and (task.command, task.source) == ("make deps", "task")
    assert pod is not None and (pod.command, pod.source) == ("pod cmd", "pod")


@pytest.mark.parametrize(
    ("task_prepare", "pod_prepare"), [("", "x"), ("none", ""), ("NONE", "x"), (None, "none")]
)
def test_a_blank_or_none_turns_it_off_at_any_level(
    tmp_path: Path, task_prepare: object, pod_prepare: str
) -> None:
    root = _tree(tmp_path / "wt")
    assert _prepare.resolve(root, task_prepare=task_prepare, pod_prepare=pod_prepare) is None


def test_a_command_with_no_lockfile_still_runs(tmp_path: Path) -> None:
    spec = _prepare.resolve(_tree(tmp_path / "wt", ""), task_prepare="make", pod_prepare="")
    assert spec is not None and spec.lock_hash == ""


@pytest.mark.parametrize("bad", ["a\nb", "a\x00b", "x" * 1001])
def test_check_command_refuses_a_multiline_nul_or_long_command(bad: str) -> None:
    with pytest.raises(ValueError, match=r"one line|at most"):
        _text.check_command(bad)


def test_needs_prepare_only_when_command_or_lock_changed_or_a_link_broke(tmp_path: Path) -> None:
    root = _tree(tmp_path / "wt")
    spec = _prepare.resolve(root, task_prepare=None, pod_prepare="")
    assert spec is not None
    outcome = _prepare.PrepareOutcome(True, False, 0, 0.0, "")
    prepared = _prepare.record(spec, outcome)
    assert _prepare.needs_prepare(root, None, spec)
    assert not _prepare.needs_prepare(root, prepared, spec)
    assert _prepare.needs_prepare(root, {**prepared, "lockHash": "other"}, spec)
    assert _prepare.needs_prepare(root, {**prepared, "command": "other"}, spec)
    (root / "node_modules").symlink_to(tmp_path / "gone")
    assert _prepare.needs_prepare(root, prepared, spec)


class _Run:
    """A runner that installs ``node_modules`` into the worktree and counts its calls."""

    def __init__(self, root: Path, code: int = 0) -> None:
        self.root, self.code, self.calls = root, code, 0

    def __call__(self, command: str) -> tuple[int | None, str]:
        self.calls += 1
        if self.code == 0:
            (self.root / "node_modules" / ".bin").mkdir(parents=True)
            (self.root / "node_modules" / ".bin" / "tool").write_text("x")
        return self.code, "out"


def _spec(root: Path) -> _prepare.PrepareSpec:
    spec = _prepare.resolve(root, task_prepare=None, pod_prepare="")
    assert spec is not None
    return spec


def test_a_miss_runs_the_command_and_keeps_node_modules_as_the_entry(tmp_path: Path) -> None:
    root = _tree(tmp_path / "wt")
    codebase = str(tmp_path / "repo")
    run = _Run(root)
    outcome = _prepare.prepare_worktree(_spec(root), root, codebase, "", run)
    assert (outcome.ok, outcome.cache_hit, outcome.exit_code, run.calls) == (True, False, 0, 1)
    entry = _prepare.entry_dir(codebase, _spec(root))
    assert (entry / "node_modules" / ".bin" / "tool").is_file()
    assert (root / "node_modules").is_symlink()
    assert (root / "node_modules" / ".bin" / "tool").is_file()


def test_a_hit_runs_nothing_and_links_the_entry(tmp_path: Path) -> None:
    codebase = str(tmp_path / "repo")
    first = _tree(tmp_path / "wt1")
    _prepare.prepare_worktree(_spec(first), first, codebase, "", _Run(first))
    second = _tree(tmp_path / "wt2")
    run = _Run(second)
    outcome = _prepare.prepare_worktree(_spec(second), second, codebase, "", run)
    assert (outcome.ok, outcome.cache_hit, outcome.exit_code, run.calls) == (True, True, None, 0)
    assert (second / "node_modules" / ".bin" / "tool").is_file()


def test_a_failed_command_leaves_no_entry_and_reports_its_output(tmp_path: Path) -> None:
    root = _tree(tmp_path / "wt")
    codebase = str(tmp_path / "repo")
    outcome = _prepare.prepare_worktree(_spec(root), root, codebase, "", _Run(root, code=1))
    assert (outcome.ok, outcome.exit_code, outcome.output) == (False, 1, "out")
    directory = _prepare.codebase_dir(codebase)
    assert [p for p in directory.iterdir() if p.is_dir()] == []


def test_a_command_that_installs_nothing_keeps_no_entry(tmp_path: Path) -> None:
    root = _tree(tmp_path / "wt")
    codebase = str(tmp_path / "repo")
    outcome = _prepare.prepare_worktree(_spec(root), root, codebase, "", lambda command: (0, ""))
    assert outcome.ok and not outcome.cache_hit
    assert [p for p in _prepare.codebase_dir(codebase).iterdir() if p.is_dir()] == []


def test_without_a_lockfile_nothing_is_cached_or_linked(tmp_path: Path) -> None:
    root = _tree(tmp_path / "wt", "")
    spec = _prepare.resolve(root, task_prepare="make", pod_prepare="")
    assert spec is not None
    run = _Run(root)
    outcome = _prepare.prepare_worktree(spec, root, str(tmp_path / "repo"), "", run)
    assert outcome.ok and not (root / "node_modules").is_symlink()
    assert not current_home().prepare_cache_dir.exists()


def test_three_entries_are_kept_and_the_oldest_removed(tmp_path: Path) -> None:
    codebase = str(tmp_path / "repo")
    entries = []
    for index in range(4):
        root = _tree(tmp_path / f"wt{index}", body=f"lock-{index}")
        spec = _spec(root)
        _prepare.prepare_worktree(spec, root, codebase, "", _Run(root))
        entry = _prepare.entry_dir(codebase, spec)
        os.utime(entry, (1000 + index, 1000 + index))
        entries.append(entry)
    survivors = [p for p in _prepare.codebase_dir(codebase).iterdir() if p.is_dir()]
    assert len(survivors) == 3 and entries[0] not in survivors


def test_a_name_already_in_the_worktree_is_left_alone(tmp_path: Path) -> None:
    codebase = str(tmp_path / "repo")
    first = _tree(tmp_path / "wt1")
    _prepare.prepare_worktree(_spec(first), first, codebase, "", _Run(first))
    second = _tree(tmp_path / "wt2")
    (second / "node_modules").mkdir()
    _prepare.prepare_worktree(_spec(second), second, codebase, "", _Run(second))
    assert not (second / "node_modules").is_symlink()


def test_linked_entries_names_the_cache_entry_a_worktree_links_into(tmp_path: Path) -> None:
    codebase = str(tmp_path / "repo")
    root = _tree(tmp_path / "wt")
    _prepare.prepare_worktree(_spec(root), root, codebase, "", _Run(root))
    assert _prepare.linked_entries(root) == (_prepare.entry_dir(codebase, _spec(root)).resolve(),)


def test_linked_entries_ignores_a_link_that_leaves_the_cache(tmp_path: Path) -> None:
    root = _tree(tmp_path / "wt")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / "node_modules").symlink_to(outside)
    assert _prepare.linked_entries(root) == ()


def test_linked_entries_of_a_plain_directory_is_empty(tmp_path: Path) -> None:
    assert _prepare.linked_entries(tmp_path) == ()


def test_the_linked_names_are_excluded_from_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        _prepare._git, "git_info_exclude", lambda common, patterns: seen.append((common, patterns))
    )
    root = _tree(tmp_path / "wt")
    _prepare.prepare_worktree(_spec(root), root, str(tmp_path / "repo"), "/common", _Run(root))
    assert seen == [("/common", ("/node_modules",))]
